"""Run frozen Vortex native or PTX cases after a guarded U280 device open."""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
import zlib


BUSES = ("b1", "b4", "3d", "40", "41")
SHELL_UUID = "fb2b2c5a19ed63593fea95f51fbc8eb9"
XCLBIN_UUID = "b60ca9fb-1506-3033-c156-e03ff687f492"
XCLBIN_SHA = "bbac2ab73073b24ba857fb34eadf22bf1c11dc745527f064c4eec61b70d2c843"
RUNTIME_SHAS = {
    "libvortex.so": "d3538d2fc7c695a4a0102106aa45e9ef7a9e939fc44c3b15c547ff97d0dffe3e",
    "libvortex-xrt.so": "250769482e98c1cee84bd165a9e2af1c7b3f74a5b77dcf389ac1f4ea5aa7a8c1",
}
CASE = "010"
OUTPUT_KINDS = ("x", "y", "z", "audit")
PTX_LAYOUTS = {
    "copy_u32": (24, (("x", 8, 0), ("z", 8, 8), ("n", 4, 16))),
    "vadd_u32": (32, (("x", 8, 0), ("y", 8, 8), ("z", 8, 16), ("n", 4, 24))),
    "affine_u32": (32, (("x", 8, 0), ("y", 8, 8), ("z", 8, 16), ("n", 4, 24), ("alpha", 4, 28))),
}
PTX_SUITE = (
    ("ptx-copy-trace-20261110-v1", "copy_u32", "0106"),
    ("ptx-arithmetic-20261110-v1", "vadd_u32", "0106"),
    ("ptx-arithmetic-20261110-v1", "affine_u32", "0322"),
)
PTX_REGRESSION = tuple(
    (source, entry, case)
    for source, entry, cases in (
        ("ptx-copy-trace-20261110-v1", "copy_u32", ("0010", "0058", "0070", "0082", "0094", "0106")),
        ("ptx-arithmetic-20261110-v1", "vadd_u32", ("0010", "0058", "0070", "0106")),
        ("ptx-arithmetic-20261110-v1", "affine_u32", ("0034", "0176", "0210", "0250", "0322")),
    ) for case in cases
)
OPEN_MARKER = "U280_SMOKE_DEVICE_OPEN"
GATE_SOURCE = r"""
#include <vortex2.h>
#include <xrt/xrt_device.h>
#include <cstdlib>
#include <iostream>

static int gated_open(uint32_t ordinal, vx_device_h* device) {
  try {
    const unsigned index = std::stoul(std::getenv("XRT_DEVICE_INDEX"));
    const auto bdf = xrt::device(index).get_info<xrt::info::device::bdf>();
    std::cerr << "XRT index " << index << " BDF " << bdf << std::endl;
    if (bdf != std::getenv("U280_EXPECTED_BDF"))
      return -1;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return -1;
  }
  auto result = vx_device_open(ordinal, device);
  if (result != VX_SUCCESS)
    return result;
  std::cerr << "U280_SMOKE_DEVICE_OPEN" << std::endl;
  if (std::cin.get() == 'R')
    return VX_SUCCESS;
  vx_device_release(*device);
  return -1;
}

#define vx_device_open gated_open
#include "source/main.cpp"
"""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def capacity(value):
    # The XRT 2022.1 report renders byte counts with binary size suffixes.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(Bytes?|[KMG]i?B)?", str(value), re.I)
    require(match is not None, "unrecognized XRT HOST capacity: " + str(value))
    unit = (match[2] or "B").upper()[0]
    return int(float(match[1]) * 1024 ** "BKMG".index(unit))


def idle(kds):
    return all(re.search(r"^" + label + r":[ \t]+0[ \t]*$", kds, re.M)
               for label in ("outstanding execs", "contexts")) and bool(
        re.search(r"^client pid:\s*\Z", kds, re.M))


def snapshot(device):
    names = ("ready", "interface_uuids", "kdsstat", "host_mem_size", "xclbinuuid")
    return {name: (device / name).read_text().strip() for name in names}


def output_names(case_id, kinds=OUTPUT_KINDS):
    return tuple(case_id + "_" + name + ".bin" for name in kinds)


def compare_outputs(work, bundle, result, stdout):
    if "sequence" in bundle:
        return compare_sequence_outputs(work, bundle, result, stdout)
    captures = re.findall(r"(?m)^CAPTURED (\d+) ", stdout)
    result["captured_cases"] = captures
    for case_id in bundle["cases"]:
        outputs = {}
        for name in output_names(case_id, bundle.get("output_kinds", OUTPUT_KINDS)):
            expected_sha = bundle["expected"][name]
            path = work / "output" / name
            if path.is_file():
                raw = path.read_bytes()
                digest = sha(raw)
                outputs[name] = dict(status="PASS" if digest == expected_sha else "FAIL",
                                     sha256=digest, expected_sha256=expected_sha,
                                     base64=base64.b64encode(raw).decode("ascii"))
            else:
                outputs[name] = dict(status="NOT_RUN", expected_sha256=expected_sha)
        result["outputs"].update(outputs)
        if case_id in captures:
            status = "PASS" if all(item["status"] == "PASS" for item in outputs.values()) else "FAIL"
        else:
            status = "FAIL" if any(item["status"] != "NOT_RUN" for item in outputs.values()) else "NOT_RUN"
        result["case_results"][case_id] = status
    result["passed_cases"] = sum(status == "PASS" for status in result["case_results"].values())
    allowed = set(bundle["expected"])
    if "ptx" in bundle:
        allowed.add(bundle["cases"][0] + "_params.bin")
    result["unexpected_outputs"] = sorted(path.name for path in (work / "output").iterdir()
                                          if path.name not in allowed)


def verify_ptx_launch(work, bundle, result, stdout):
    contract = bundle["ptx"]
    raw = (work / "output" / (bundle["cases"][0] + "_params.bin")).read_bytes()
    result["ptx_launch"] = dict(payload_base64=base64.b64encode(raw).decode("ascii"), payload_sha256=sha(raw),
                                image_sha256=contract["image_sha256"], status="FAIL")
    size, layout = PTX_LAYOUTS[contract.get("entry", "copy_u32")]
    args = re.findall(r"(?m)^PTX_COPY_ARGS" + "".join(r" {}=(\d+)".format(name) for name, _, _ in layout) + "$", stdout)
    entries = re.findall(r"(?m)^PTX_COPY_ENTRY (\d+)$", stdout)
    require(len(args) == 1 and entries == [str(contract["runtime_entry_pc"])], "unexpected PTX launch entry or args")
    case = contract["case"]
    require("CAPTURED {id} n={n} block={block} grid={grid}".format(**case) in stdout.splitlines(),
            "unexpected PTX launch geometry")
    values = dict(zip((name for name, _, _ in layout), map(int, args[0])))
    payload = bytearray(size)
    addresses = []
    for name, width, offset in layout:
        value = values[name]
        if width == 8:
            require(32 <= value and value % 4 == 0 and value - 32 + 4 * case["words"] <= 2 ** 64,
                    "unexpected PTX buffer address")
            addresses.append(value)
        else:
            require(value == case[name], "unexpected PTX scalar: " + name)
        payload[offset:offset + width] = value.to_bytes(width, "little")
    addresses.sort()
    require(all(right - left >= 4 * case["words"] for left, right in zip(addresses, addresses[1:])),
            "overlapping PTX buffers")
    require(raw == payload, "PTX payload mismatch")
    result["ptx_launch"].update(status="PASS", entry_pc=int(entries[0]), args=values)


def compare_sequence_outputs(work, bundle, result, stdout):
    result["captured_cases"] = re.findall(r"(?m)^CAPTURED (\d+) ", stdout)
    allowed = set(bundle["expected"]) | {cid + "_params.bin" for cid in bundle["cases"]}
    for name in sorted(allowed):
        path = work / "output" / name
        if path.is_file():
            raw = path.read_bytes()
            digest = sha(raw)
            expected = bundle["expected"].get(name)
            result["outputs"][name] = dict(sha256=digest, base64=base64.b64encode(raw).decode("ascii"),
                status="PASS" if expected and digest == expected else ("FAIL" if expected else "NOT_CHECKED"))
        else:
            result["outputs"][name] = dict(status="NOT_RUN")
    result["unexpected_outputs"] = sorted(p.name for p in (work / "output").iterdir() if p.name not in allowed)
    for cid in bundle["cases"]:
        arrays = [item for name, item in result["outputs"].items() if name.startswith(cid + "_") and not name.endswith("_params.bin")]
        result["case_results"][cid] = ("PASS" if all(item["status"] == "PASS" for item in arrays) else "FAIL") if cid in result["captured_cases"] else "NOT_RUN"
    result["passed_cases"] = sum(status == "PASS" for status in result["case_results"].values())


def verify_sequence_launch(work, bundle, result, stdout):
    namespace = {}
    exec(compile((work / "sequence_contract.py").read_bytes(), "sequence_contract.py", "exec"), namespace)
    result["sequence_verification"] = namespace["verify_capture"](bundle["sequence"], stdout, work / "output")
    for cid in bundle["cases"]:
        result["outputs"][cid + "_params.bin"]["status"] = "PASS"


def collect(bundle, result):
    import pwd

    user = pwd.getpwuid(os.getuid())
    require(user.pw_name == "u280user", "unexpected remote account")
    home = Path(user.pw_dir).resolve()
    root = home / "vortex-u280-board-smoke"
    root.mkdir(mode=0o700, exist_ok=True)
    require(root.resolve() == root, "unexpected remote run root")
    work = root / bundle["run_id"]
    work.mkdir(mode=0o700)
    result["remote_directory"] = str(work)
    for name, item in bundle["files"].items():
        path = work / name
        raw = base64.b64decode(item["base64"], validate=True)
        require(sha(raw) == item["sha256"], "input digest mismatch: " + name)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
    (work / "output").mkdir()
    (work / "gate.cpp").write_text(GATE_SOURCE)

    def command(label, argv, seconds=15, env=None):
        record = dict(label=label, argv=[str(arg) for arg in argv], timeout_seconds=seconds)
        result["commands"].append(record)
        started = time.monotonic()
        try:
            proc = subprocess.run(record["argv"], cwd=str(work), env=env, timeout=seconds,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            record.update(exit_code=proc.returncode, stdout=proc.stdout.decode(errors="replace"),
                          stderr=proc.stderr.decode(errors="replace"))
        except subprocess.TimeoutExpired as exc:
            record.update(exit_code=None, timed_out=True,
                          stdout=(exc.stdout or b"").decode(errors="replace"),
                          stderr=(exc.stderr or b"").decode(errors="replace"))
        record["seconds"] = round(time.monotonic() - started, 3)
        return record

    def report(label, bdf=None):
        argv = ["xbutil", "examine", "--format", "JSON", "--output", label + ".json"]
        if bdf:
            argv += ["--device", bdf, "--report", "platform", "pcie-info", "dynamic-regions"]
        rec = command(label, argv)
        require(rec["exit_code"] == 0, label + " command failed")
        raw = (work / (label + ".json")).read_text()
        result["reports"][label] = raw
        data = json.loads(raw)
        if not bdf:
            return data["system"]["host"]["devices"]
        devices = data["devices"]
        require(len(devices) == 1 and devices[0]["device_id"] == bdf, "XRT report BDF mismatch")
        return devices[0]

    builds = home / "vortex-u280-builds"
    xclbin = builds / "u280-link-20261109-103830-671/out/vortex_afu.xclbin"
    libs = home / "vortex-u280-runtime/u280-runtime-20261109-v4/build/lib"
    for path, expected in [(xclbin, XCLBIN_SHA)] + [(libs / name, digest) for name, digest in RUNTIME_SHAS.items()]:
        digest = sha(path.read_bytes())
        result["artifact_sha256"][str(path)] = digest
        require(digest == expected, "artifact hash mismatch: " + str(path))
    env = dict(os.environ)
    env.update(VORTEX_DRIVER="xrt", XCLBIN_PATH=str(xclbin),
               LD_LIBRARY_PATH=str(libs) + ":" + env.get("LD_LIBRARY_PATH", ""))
    flags = (work / "resolved.cflags").read_text().split()
    compiler = "/opt/rh/devtoolset-9/root/usr/bin/g++"
    compile_rec = command("host_compile", [compiler, "-std=c++17", "-O2", "-Iinclude",
                          "-I/opt/xilinx/xrt/include"] + flags +
                          ["gate.cpp", "-L" + str(libs), "-L/opt/xilinx/xrt/lib",
                           "-lvortex", "-lxrt_coreutil", "-pthread", "-o", "smoke"], 60, env)
    result["host_compile"] = "PASS" if compile_rec["exit_code"] == 0 else "FAIL"
    require(result["host_compile"] == "PASS", "host compilation failed")
    result["host_sha256"] = sha((work / "smoke").read_bytes())
    fuser = shutil.which("fuser") or next(
        (p for p in ("/usr/sbin/fuser", "/sbin/fuser") if Path(p).is_file()), None)
    require(fuser is not None, "fuser unavailable for visible holder check")
    enumeration = report("device_list")

    def check_idle(device, label):
        info = snapshot(device)
        result["sysfs"][label] = info
        require((device / "driver").resolve().name == "xocl" and info["ready"] == "0x1"
                and SHELL_UUID in info["interface_uuids"].lower().replace("-", "").split(),
                "card not ready with expected shell")
        require(idle(info["kdsstat"]), "KDS has work, contexts or client PIDs")
        nodes = sorted("/dev/dri/" + p.name for p in (device / "drm").glob("renderD*"))
        require(len(nodes) == 1 and Path(nodes[0]).is_char_device(), "unexpected render node mapping")
        holders = command(label + "_holders", [fuser, "-v", nodes[0]])
        require(holders["exit_code"] == 1 and not holders["stdout"].strip()
                and not holders["stderr"].strip(), "render holder present or holder query failed")

    for bus in BUSES:
        bdf = "0000:" + bus + ":00.1"
        if bundle.get("pinned_bdf") and bundle["pinned_bdf"] != bdf:
            continue
        device = Path("/sys/bus/pci/devices") / bdf
        try:
            check_idle(device, bus + "_before_report")
            entry = report(bus + "_preflight", bdf)
            field = entry["pcie_info"]["shared_host_mem_size_bytes"]
            result["host_capacity"][bdf] = dict(reported=field, bytes=capacity(field))
            require(capacity(field) >= 256 * 1024 * 1024, "HOST below 256 MiB")
            indices = [index for index, item in enumerate(enumeration) if item["bdf"] == bdf
                       and item["is_ready"] == "true"]
            require(len(indices) == 1, "cannot determine unique ready XRT index")
            check_idle(device, bus + "_immediately_before_open")
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            result["rejected_cards"][bdf] = str(exc)
            continue
        result.update(selected_bdf=bdf, xrt_index=indices[0], card_preflight="PASS")
        env.update(XRT_DEVICE_INDEX=str(indices[0]), U280_EXPECTED_BDF=bdf)
        break
    else:
        result["status"] = "BLOCKED"
        raise RuntimeError("no eligible card met the preflight gates")

    argv = ["./smoke", "inputs", "output"]
    seconds = 300 if bundle["mode"] in ("regression", "ptx-sequence") else 90
    label = bundle["ptx"].get("entry", "copy_u32") if bundle["mode"] == "ptx-device" else (
        "ptx_copy" if bundle["mode"] == "ptx-copy" else "native_" + bundle["mode"])
    run = dict(label=label, argv=argv, exit_code=None, timeout_seconds=seconds)
    result["commands"].append(run)
    out_path, err_path = work / "smoke.stdout", work / "smoke.stderr"
    started = time.monotonic()
    result["device_open"] = "FAIL"
    with out_path.open("wb") as out, err_path.open("wb") as err:
        proc = subprocess.Popen(argv, cwd=str(work), env=env, stdin=subprocess.PIPE, stdout=out, stderr=err)
        try:
            deadline = started + 60
            while OPEN_MARKER not in err_path.read_text(errors="replace"):
                require(proc.poll() is None, "runtime open exited before the readback gate")
                require(time.monotonic() < deadline, "runtime open timed out")
                time.sleep(0.1)
            result["device_open"] = "PASS"
            result["readback"] = "FAIL"
            info = snapshot(device)
            result["sysfs"]["loaded"] = info
            require(info["xclbinuuid"].lower() == XCLBIN_UUID, "loaded xclbin UUID mismatch")
            for node in sorted(device.glob("icap.*/clock_freqs")):
                result["clock_sysfs"][str(node)] = node.read_text().strip()
            entry = report("loaded", bdf)
            clocks = entry["platforms"][0]["clocks"]
            data_clocks = [clock for clock in clocks if clock["id"] == "DATA_CLK"]
            require(len(data_clocks) == 1 and int(data_clocks[0]["freq_mhz"]) == 200,
                    "device DATA_CLK readback is not 200 MHz")
            result["clock_readback"] = data_clocks[0]
            result["readback"] = "PASS"
            result["board_execution"] = "FAIL"
            proc.stdin.write(b"R")
            proc.stdin.close()
            try:
                proc.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                run["timed_out"] = True
        finally:
            if proc.poll() is None:
                if not proc.stdin.closed:
                    proc.stdin.close()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            run.update(exit_code=proc.returncode, seconds=round(time.monotonic() - started, 3),
                       stdout=out_path.read_text(errors="replace"), stderr=err_path.read_text(errors="replace"))
            result["sysfs"]["after"] = snapshot(device)

    compare_outputs(work, bundle, result, run["stdout"])
    require(run["exit_code"] == 0 and not run.get("timed_out"), "host test failed or timed out")
    lines = run["stdout"].splitlines()
    require(result["captured_cases"] == bundle["cases"]
            and "CAPTURE_COMPLETE " + str(len(bundle["cases"])) in lines,
            "captured launches differ from the frozen case order or count")
    if "sequence" in bundle:
        verify_sequence_launch(work, bundle, result, run["stdout"])
        require(idle(result["sysfs"]["after"]["kdsstat"]), "card failed post-sequence idle gate")
    elif "ptx" in bundle:
        verify_ptx_launch(work, bundle, result, run["stdout"])
    else:
        require(all("BLOCK_REJECTION block={} actual=3 expected=3".format(block) in lines for block in (33, 64)),
                "missing expected oversize-block rejection")
    require(result["passed_cases"] == len(bundle["cases"]) and not result["unexpected_outputs"],
            "captured output set or contents differ from the frozen reference")
    result.update(board_execution="PASS", status="PASS")


def remote(bundle):
    if bundle["mode"] in ("ptx-suite", "ptx-regression", "ptx-boundaries"):
        return remote_ptx_suite(bundle)
    result = dict(run_id=bundle["run_id"], nonce=bundle["nonce"], status="FAIL",
                  started_at=datetime.datetime.now().astimezone().isoformat(),
                  host_compile="NOT_RUN", card_preflight="NOT_RUN", device_open="NOT_RUN",
                  readback="NOT_RUN", board_execution="NOT_RUN",
                  artifact_sha256={}, commands=[], reports={}, sysfs={}, outputs={}, clock_sysfs={},
                  host_capacity={}, rejected_cards={}, mode=bundle["mode"],
                  planned_cases=len(bundle["cases"]), case_results={},
                  holder_scope="KDS and holders visible to ordinary account; no exclusive reservation")
    try:
        collect(bundle, result)
    except Exception as exc:
        result["error"] = repr(exc)
    result["finished_at"] = datetime.datetime.now().astimezone().isoformat()
    return result


def remote_ptx_suite(bundle):
    boundaries = bundle["mode"] == "ptx-boundaries"
    regression = bundle["mode"] in ("ptx-regression", "ptx-boundaries")
    plan = [tuple(item) for item in bundle["boundary_plan"]] if boundaries else (PTX_REGRESSION if regression else PTX_SUITE)
    if boundaries:
        require(len(plan) == len(set(plan)) == 67 and all(source == bundle['source_run'] for source, _, _ in plan),
                'unexpected boundary plan')
    entries = [entry + "-" + case if regression else entry for _, entry, case in plan]
    jobs = bundle["jobs"]
    require([(job["ptx"]["source_run"], job["ptx"]["entry"], job["ptx"]["case"]["id"]) for job in jobs]
            == list(plan), "unexpected PTX suite job order")
    result = dict(run_id=bundle["run_id"], nonce=bundle["nonce"], mode=bundle["mode"], status="PASS",
                  planned_cases=len(entries), passed_cases=0, selected_bdf=None,
                  started_at=datetime.datetime.now().astimezone().isoformat(),
                  jobs={entry: dict(status="NOT_RUN", board_execution="NOT_RUN") for entry in entries})
    for entry, job in zip(entries, jobs):
        print("U280 PTX suite starting " + entry, flush=True)
        child = dict(job, mode="ptx-device", nonce=bundle["nonce"],
                     run_id=bundle["run_id"] + "-" + entry, pinned_bdf=result["selected_bdf"])
        completed = remote(child)
        result["jobs"][entry] = completed
        bdf = completed.get("selected_bdf")
        if not result["selected_bdf"]:
            result["selected_bdf"] = bdf
        if completed["status"] != "PASS":
            result.update(status=completed["status"], error=entry + ": " + completed.get("error", "failed"))
            break
        if bdf != result["selected_bdf"] or not bdf or not idle(completed["sysfs"]["after"]["kdsstat"]):
            result.update(status="FAIL", error=entry + ": BDF changed or card failed the post-run idle gate")
            break
        result["passed_cases"] += 1
    result["finished_at"] = datetime.datetime.now().astimezone().isoformat()
    return result


def ptx_inputs(root, source_run, verified):
    require(source_run and re.fullmatch(r"ptx-copy-[A-Za-z0-9_.-]{1,70}", source_run), "invalid PTX source run")
    run = root / "results" / source_run
    summary = json.loads((run / "summary.json").read_bytes())
    require(summary["status"] == "PASS" and summary["device_build"] == "PASS"
            and all(summary["backends"][backend]["status"] == "PASS" for backend in ("simx", "rtlsim")),
            "passing PTX SimX and RTL results required before board access")
    module = run / "module"
    package = json.loads((module / "manifest.json").read_bytes())
    require(package["schema_version"] == "ptx-vx-copy-device-package-v1" and package["entry"] == "copy_u32"
            and package["loadable"] and package["abi_version"] == "ptx-vx-args-v1"
            and package["params_size"] == 24
            and [(p["name"], p["size"], p["offset"]) for p in package["params"]] == [("x", 8, 0), ("z", 8, 8), ("n", 4, 16)],
            "unexpected PTX copy package/ABI")
    require(package["u280_candidate_lock_hash"] == sha(
        (root / "configs/candidates/u280-hbm32-v1/target_lock.json").read_bytes()), "U280 PTX target binding changed")
    files = {"include/vortex2.h": verified("include/vortex2.h"), "resolved.cflags": verified("resolved.cflags")}
    for name, destination in (("kernel.vxbin", "kernel.vxbin"), ("main.cpp", "source/main.cpp"),
                              ("copy_case.hpp", "source/copy_case.hpp")):
        data = (module / name).read_bytes()
        require(sha(data) == package["files"][name], "PTX package file changed: " + name)
        files[destination] = data
    require(sha(files["kernel.vxbin"]) == package["image_sha256"] == summary["image_sha256"],
            "PTX vxbin differs from the verified image")
    frozen = root / "results/ptx-frontend-host-20261108-v3/copy_u32"
    corpus_raw = (frozen / "corpus.json").read_bytes()
    require(sha(corpus_raw) == package["corpus_sha256"], "PTX copy corpus changed")
    corpus = json.loads(corpus_raw)
    case = package["case"]
    require(case in corpus["cases"] and case["id"] == "0026", "unexpected frozen PTX case")
    expected = {}
    kinds = ("x", "z")
    for name in output_names(case["id"], kinds):
        for group in ("inputs", "expected"):
            relative = group + "/" + name
            data = (module / relative).read_bytes()
            require(sha(data) == corpus["files"][relative], "PTX frozen file changed: " + relative)
            if group == "inputs":
                files[relative] = data
            else:
                expected[name] = sha(data)
    return files, dict(cases=[case["id"]], expected=expected, output_kinds=kinds,
                       ptx=dict(source_run=source_run, image_sha256=package["image_sha256"],
                                runtime_entry_pc=package["runtime_entry_pc"], case=case))


def ptx_device_inputs(root, source_run, entry, case_id, verified):
    # Local preparation only. The CentOS worker remains Python 3.6-compatible.
    from run_ptx_copy import CORPUS_HASHES, SIM_LOCK, BOARD_LOCK, case_header, capture_comparison, vxbin_entry

    require(source_run and re.fullmatch(r"ptx-(?:copy-trace|arithmetic)-[A-Za-z0-9_.-]{1,64}", source_run)
            and entry in PTX_LAYOUTS and case_id and re.fullmatch(r"\d{4}", case_id), "invalid PTX device selection")
    run = root / "results" / source_run
    summary = json.loads((run / "summary.json").read_bytes())
    require(summary["status"] == "PASS" and summary["run_id"] == source_run, "passing PTX simulation run required")
    copy_trace = entry == "copy_u32"
    if copy_trace:
        require(summary["schema_version"] == "ptx-vx-copy-trace-v1" and summary["image_origin"] == "ptx-copy-20261110-v2",
                "unexpected copy trace origin")
        module, case_dir = run / "module", run / case_id
        package = json.loads((root / "results/ptx-copy-20261110-v2/module/manifest.json").read_bytes())
        case = next((case for case in summary["cases"] if case["id"] == case_id), None)
        image_sha = summary["image_sha256"]
    else:
        require(summary["schema_version"] == "ptx-vx-arithmetic-sim-v1" and entry in summary["kernels"],
                "unexpected arithmetic simulation run")
        module = run / entry
        case_dir = module / case_id
        package = json.loads((module / "manifest.json").read_bytes())
        kernel = summary["kernels"][entry]
        require(kernel["device_build"] == "PASS", "PTX device build did not pass")
        case = next((record["case"] for record in kernel["backends"]["simx"] if record["case"]["id"] == case_id), None)
        image_sha = kernel["image_sha256"]
    require(case is not None, "case was not executed in the source run")

    sim_lock, board_lock = SIM_LOCK.read_bytes(), BOARD_LOCK.read_bytes()
    binding = json.loads((root / "results/ptx-copy-20261110-v2/module/manifest.json").read_bytes())
    require(sha(sim_lock) == binding["target_lock_hash"] == package.get("target_lock_sha256", package.get("target_lock_hash"))
            and sha(board_lock) == binding["u280_candidate_lock_hash"], "PTX simulator/U280 lock binding changed")
    size, layout = PTX_LAYOUTS[entry]
    ir = json.loads((module / "frontend/ir.json").read_bytes())
    require(package["entry"] == ir["entry"] == entry and package["abi_version"] == "ptx-vx-args-v1"
            and package["params"] == ir["params"] and package["params_size"] == ir["params_size"] == size
            and tuple((p["name"], p["size"], p["offset"]) for p in ir["params"]) == layout, "PTX device ABI mismatch")
    image, host = (module / "kernel.vxbin").read_bytes(), (module / "main.cpp").read_bytes()
    entry_pc = vxbin_entry(module / "kernel.vxbin", entry)
    require(sha(image) == package["files"]["kernel.vxbin"] == image_sha and entry_pc == package["runtime_entry_pc"]
            and sha(host) == package["files"]["main.cpp"] == sha((case_dir / "main.cpp").read_bytes()),
            "PTX image, entry, or host differs from the simulation package")

    frozen = root / "results/ptx-frontend-host-20261108-v3" / entry
    corpus_raw = (frozen / "corpus.json").read_bytes()
    corpus = json.loads(corpus_raw)
    require(sha(corpus_raw) == CORPUS_HASHES[entry] and case in corpus["cases"], "PTX frozen corpus mismatch")
    header = case_header(case, ir).encode("ascii")
    if not copy_trace:
        require((case_dir / "copy_case.hpp").read_bytes() == header, "PTX case header differs from simulation")
    files = {"include/vortex2.h": verified("include/vortex2.h"), "resolved.cflags": verified("resolved.cflags"),
             "kernel.vxbin": image, "source/main.cpp": host, "source/copy_case.hpp": header}
    expected = {}
    kinds = tuple(name for name, width, _ in layout if width == 8)
    for name in output_names(case_id, kinds):
        for group in ("inputs", "expected"):
            relative = group + "/" + name
            data = (case_dir / relative).read_bytes()
            require(len(data) == case["words"] * 4 and sha(data) == corpus["files"][relative],
                    "PTX frozen file changed: " + relative)
            if group == "inputs":
                files[relative] = data
            else:
                expected[name] = sha(data)
    for backend in ("simx", "rtlsim"):
        stage = case_dir / backend
        label = "{}_{}_run".format(backend, case_id) if copy_trace else "{}_{}_{}_run".format(entry, case_id, backend)
        commands = [rec for rec in summary["commands"] if rec["label"] == label]
        require(len(commands) == 1 and commands[0]["returncode"] == 0 and not commands[0]["timed_out"],
                "successful PTX simulation command required: " + backend)
        log = (run / commands[0]["log"]).read_bytes()
        require(sha(log) == commands[0]["log_sha256"], "PTX simulator log changed: " + backend)
        comparison = capture_comparison(case_dir, stage / "actual", log.decode("utf-8", errors="replace"), case, ir, entry_pc)
        trace = json.loads((stage / "trace.json").read_bytes())
        require(comparison["status"] == trace["status"] == "PASS" and trace["geometry_match"]
                and trace["observed_loads"] == case["expected_loads"] and trace["observed_stores"] == case["expected_stores"],
                "PTX capture or LSU evidence did not pass: " + backend)
    return files, dict(cases=[case_id], expected=expected, output_kinds=kinds,
                       ptx=dict(entry=entry, source_run=source_run, image_sha256=image_sha, runtime_entry_pc=entry_pc,
                                case=case, corpus_sha256=sha(corpus_raw), sim_lock_sha256=sha(sim_lock),
                                u280_lock_sha256=sha(board_lock), abi_version=package["abi_version"], params_size=size))


def native_inputs(mode, verified):
    names = ("source/main.cpp", "source/common.h", "include/vortex2.h", "resolved.cflags", "kernel.vxbin")
    files = {name: verified(name) for name in names}
    table = verified("inputs/cases.tsv")
    rows = table.splitlines()
    if mode == "smoke":
        rows = [row for row in rows if row.split()[0] == CASE.encode()]
        require(len(rows) == 1 and rows[0].split()[:7] == [b"010", b"0", b"1", b"32", b"1", b"1", b"0"],
                "unexpected frozen smoke case")
        table = rows[0] + b"\n"
    cases = [row.split()[0].decode("ascii") for row in rows]
    if mode == "regression":
        corpus = json.loads(verified("corpus.json"))
        require(cases == [case["id"] for case in corpus["cases"]]
                and cases == ["{:03d}".format(i) for i in range(152)]
                and sha(table) == corpus["case_table_sha256"], "unexpected frozen regression case table")
    files["inputs/cases.tsv"] = table
    expected = {}
    for case_id in cases:
        for name in output_names(case_id):
            files["inputs/" + name] = verified("inputs/" + name)
            expected[name] = sha(verified("expected/" + name))
    return files, dict(cases=cases, expected=expected)


def sequence_inputs(root, source_run, verified):
    from ptx_sequence_contract import verify_capture
    require(source_run and re.fullmatch(r"ptx-sequence-[A-Za-z0-9_.-]{1,64}", source_run), "invalid sequence source")
    run = root / "results" / source_run
    summary = json.loads((run / "summary.json").read_bytes())
    contract_raw = (run / "bundle/contract.json").read_bytes()
    contract = json.loads(contract_raw)
    require(summary["schema"] == "ptx-same-device-run-v1" and summary["status"] == "PASS"
            and summary["contract_sha256"] == sha(contract_raw), "passing sequence/contract required")
    require(contract["target_lock_sha256"] == sha((root / "configs/candidates/block32-v1/target_lock.json").read_bytes())
            and contract["board_lock_sha256"] == sha((root / "configs/candidates/u280-hbm32-v1/target_lock.json").read_bytes()),
            "sequence target binding changed")
    require(contract["frozen_manifest_sha256"] == sha((root / "configs/acceptance/e-ptx15-v1/manifest.json").read_bytes()),
            "sequence answer binding changed")
    for backend in ("simx", "rtlsim", "xrtsim"):
        require(summary["backends"][backend]["status"] == "PASS", "sequence backend failed: " + backend)
        command = next(c for c in summary["commands"] if c["label"] == backend + "_run")
        log = (run / command["log"]).read_bytes()
        require(command["returncode"] == 0 and not command["timed_out"] and sha(log) == command["log_sha256"],
                "sequence command/log changed")
        verify_capture(contract, log.decode(), run / backend / "actual")
    files = {"include/vortex2.h": verified("include/vortex2.h"), "resolved.cflags": verified("resolved.cflags")}
    for name, digest in contract["files"].items():
        require(not name.startswith("/") and ".." not in name.split("/"), "invalid sequence member")
        raw = (run / "bundle" / name).read_bytes()
        require(sha(raw) == digest, "sequence file changed: " + name)
        if not name.startswith("expected/"):
            files[name] = raw
    return files, dict(sequence=contract, source_run=source_run, cases=[c["id"] for c in contract["cases"]],
                       expected=contract["expected"], output_kinds=("x", "y", "z"))


def boundary_inputs(root, source_run, entry, case, verified):
    """Called only after full local command, trace and capture revalidation."""
    from run_ptx_copy import CORPUS_HASHES, SIM_LOCK, BOARD_LOCK
    run = root / 'results' / source_run
    module = run / entry
    package = json.loads((module / 'manifest.json').read_bytes())
    ir = json.loads((module / 'frontend/ir.json').read_bytes())
    size, layout = PTX_LAYOUTS[entry]
    require(ir['entry'] == entry and ir['params_size'] == size and
            tuple((p['name'], p['size'], p['offset']) for p in ir['params']) == layout, 'boundary ABI mismatch')
    original = json.loads((root / 'results/ptx-copy-20261110-v2/module/manifest.json').read_bytes())
    require(sha(SIM_LOCK.read_bytes()) == original['target_lock_hash'] == package['target_lock_sha256'] and
            sha(BOARD_LOCK.read_bytes()) == original['u280_candidate_lock_hash'], 'boundary target binding mismatch')
    directory = module / case['id']
    files = {'include/vortex2.h': verified('include/vortex2.h'), 'resolved.cflags': verified('resolved.cflags'),
             'kernel.vxbin': (module / 'kernel.vxbin').read_bytes(),
             'source/main.cpp': (directory / 'main.cpp').read_bytes(),
             'source/copy_case.hpp': (directory / 'copy_case.hpp').read_bytes()}
    kinds = tuple(name for name, width, _ in layout if width == 8)
    expected = {}
    for name in output_names(case['id'], kinds):
        files['inputs/' + name] = (directory / 'inputs' / name).read_bytes()
        expected[name] = sha((directory / 'expected' / name).read_bytes())
    return files, dict(cases=[case['id']], expected=expected, output_kinds=kinds,
        ptx=dict(entry=entry, source_run=source_run, image_sha256=package['image_sha256'],
                 runtime_entry_pc=package['runtime_entry_pc'], case=case, corpus_sha256=CORPUS_HASHES[entry],
                 sim_lock_sha256=sha(SIM_LOCK.read_bytes()), u280_lock_sha256=sha(BOARD_LOCK.read_bytes()),
                 abi_version='ptx-vx-args-v1', params_size=size))


def prepare(run_id, mode="smoke", ptx_run=None, ptx_entry=None, ptx_case=None):
    require(re.fullmatch(r"u280-board-" + mode + r"-[A-Za-z0-9_.-]{1,70}", run_id), "invalid run id")
    script = Path(__file__).resolve()
    root = script.parents[1]
    data = root / "results/u280-board-input-20261109-v1/input"
    manifest = (data / "manifest.json").read_bytes()
    require(sha(manifest) == "6c567b1fdef278b362baedcb9c377f500868eb90b7f2bedcfa65e7382ba3d402",
            "D13 input manifest changed")
    hashes = {item["path"]: item["sha256"] for item in json.loads(manifest)}

    def verified(name):
        raw = (data / name).read_bytes()
        require(sha(raw) == hashes[name], "D13 input changed: " + name)
        return raw

    def encoded(files):
        return {name: dict(sha256=sha(raw), base64=base64.b64encode(raw).decode("ascii")) for name, raw in files.items()}

    nonce = uuid.uuid4().hex
    identity = dict(run_id=run_id, nonce=nonce, mode=mode)
    if mode == 'ptx-boundaries':
        from verify_ab_closeout import check_boundaries
        require(ptx_run and re.fullmatch(r'ptx-boundaries-[A-Za-z0-9_.-]{1,64}', ptx_run), 'invalid boundary source run')
        check_boundaries(root / 'results' / ptx_run)
        summary = json.loads((root / 'results' / ptx_run / 'summary.json').read_bytes())
        jobs, records, plan = [], [], []
        for entry in ('copy_u32', 'vadd_u32', 'affine_u32'):
            for case in summary['kernels'][entry]['cases']:
                files, spec = boundary_inputs(root, ptx_run, entry, case, verified)
                plan.append((ptx_run, entry, case['id']))
                jobs.append(dict(spec, files=encoded(files)))
                records.append(dict(spec, inputs={name: sha(data) for name, data in files.items()}))
        bundle = dict(identity, jobs=jobs, boundary_plan=plan, source_run=ptx_run)
        preparation = dict(identity, jobs=records, boundary_plan=plan, source_run=ptx_run,
                           source_summary_sha256=sha((root / 'results' / ptx_run / 'summary.json').read_bytes()))
    elif mode in ("ptx-suite", "ptx-regression"):
        jobs, records = [], []
        for source, entry, case in (PTX_REGRESSION if mode == "ptx-regression" else PTX_SUITE):
            files, spec = ptx_device_inputs(root, source, entry, case, verified)
            jobs.append(dict(spec, files=encoded(files)))
            records.append(dict(spec, inputs={name: sha(data) for name, data in files.items()}))
        bundle = dict(identity, jobs=jobs)
        preparation = dict(identity, jobs=records)
    elif mode == "ptx-sequence":
        files, spec = sequence_inputs(root, ptx_run, verified)
    elif mode == "ptx-device":
        files, spec = ptx_device_inputs(root, ptx_run, ptx_entry, ptx_case, verified)
    elif mode == "ptx-copy":
        files, spec = ptx_inputs(root, ptx_run, verified)
    else:
        files, spec = native_inputs(mode, verified)
    if mode not in ("ptx-suite", "ptx-regression", "ptx-boundaries"):
        bundle = dict(spec, **identity, files=encoded(files))
        preparation = dict(spec, **identity, inputs={name: sha(data) for name, data in files.items()})
    raw = script.read_bytes()
    payload = """import base64, hashlib, json, zlib
script = base64.b64decode(%r)
digest = hashlib.sha256(script).hexdigest()
assert digest == %r
namespace = {'__name__': 'u280_remote_smoke'}
exec(compile(script, 'u280_board_smoke.py', 'exec'), namespace)
bundle = json.loads(zlib.decompress(base64.b64decode(%r)))
result = namespace['remote'](bundle)
result['script_sha256'] = digest
print('U280_SMOKE_BEGIN_' + bundle['nonce'])
print(json.dumps(result, indent=2))
print('U280_SMOKE_END_' + bundle['nonce'])
""" % (base64.b64encode(raw).decode("ascii"), sha(raw),
       base64.b64encode(zlib.compress(json.dumps(bundle).encode("ascii"))).decode("ascii"))
    run = root / "results" / run_id
    run.mkdir()
    (run / "payload.py").write_bytes(payload.encode("ascii"))
    preparation.update(status="PASS", scope="offline preparation", script_sha256=sha(raw),
                       payload_sha256=sha(payload.encode("ascii")))
    (run / "preparation.json").write_text(json.dumps(preparation, indent=2) + "\n")
    for path in (script, script.with_name("Invoke-U280BoardSmoke.ps1"), script.with_name("wlan_ssh_proxy.py")):
        shutil.copy2(path, run)
    print(str(run))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--mode", choices=("smoke", "regression", "ptx-copy", "ptx-device", "ptx-suite", "ptx-regression", "ptx-sequence", "ptx-boundaries"), default="smoke")
    parser.add_argument("--ptx-run")
    parser.add_argument("--ptx-entry", choices=tuple(PTX_LAYOUTS))
    parser.add_argument("--ptx-case")
    args = parser.parse_args()
    prepare(args.run_id, args.mode, args.ptx_run, args.ptx_entry, args.ptx_case)
