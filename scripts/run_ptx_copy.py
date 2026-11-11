"""Package the frontend copy body and verify it on SimX, then processor RTL."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct

import ptx_frontend as ptx
from run_native_smoke import PROJECT, Recorder, sha256, utc_now


FRONTEND_RUN = PROJECT / "results/ptx-frontend-host-20261108-v3"
FRONTEND_EVIDENCE = FRONTEND_RUN / "copy_u32"
CORPUS_HASHES = {
    "copy_u32": "d750d1a6b7362066906a580c9e88b1d22dfb7bb43b802912ab577d289e995a16",
    "vadd_u32": "067a4f72128897c22be1f3fa2c97c7eefd41a9d107801c680c1272a808168d09",
    "affine_u32": "fdc57f89a1f8e00802faf7a67bafe83e25059a55a3b22f43b4018e2f535aa5b8",
}
SIM_LOCK = PROJECT / "configs/candidates/block32-v1/target_lock.json"
BOARD_LOCK = PROJECT / "configs/candidates/u280-hbm32-v1/target_lock.json"
VORTEX = Path("/opt/vortex-ab/sources/vortex-7fe19369587c-v1")
BUILDS = Path("/opt/vortex-ab/builds")
CASE_ID = "0026"


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def read_json(path):
    return json.loads(path.read_bytes())


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def capture_comparison(module, actual, stdout, case, ir, entry_pc):
    names = [param["name"] for param in ir["params"]]
    pointers = [param["name"] for param in ir["params"] if param["kind"] == "pointer"]
    captures = tuple(case["id"] + "_" + key + ".bin" for key in (*pointers, "params"))
    args_pattern = r"(?m)^PTX_COPY_ARGS" + "".join(r" {}=(\d+)".format(re.escape(name)) for name in names) + "$"
    args = re.findall(args_pattern, stdout)
    entries = re.findall(r"(?m)^PTX_COPY_ENTRY (\d+)$", stdout)
    require(len(args) == 1 and len(entries) == 1, "missing or duplicate runtime argument/entry record")
    values = tuple(map(int, args[0]))
    named = dict(zip(names, values))
    addresses = {name: named[name] for name in pointers}
    require(all(named[name] == case[name] for name in names if name not in addresses) and
            all(address >= 32 and address % 4 == 0 for address in addresses.values()) and
            len(set(addresses.values())) == len(addresses), "unexpected launch arguments")
    require(int(entries[0]) == entry_pc, "runtime resolved a different vxbin entry")
    require(set(path.name for path in actual.iterdir()) == set(captures), "unexpected capture set")
    payload = ptx.pack_arguments(ir, values)
    files = {}
    for name in captures:
        captured = (actual / name).read_bytes()
        expected = payload if name.endswith("_params.bin") else (module / "expected" / name).read_bytes()
        files[name] = dict(bytes=len(captured), sha256=sha256(actual / name), match=captured == expected)
    return dict(status="PASS" if all(item["match"] for item in files.values()) else "FAIL",
                case=case, files=files, device_addresses=addresses,
                runtime_entry_pc=int(entries[0]), payload_expected_hex=payload.hex())


def vxbin_entry(image, entry="copy_u32"):
    data = image.read_bytes()
    count, magic = struct.unpack("<I8s", data[-12:])
    require(count == 1 and magic == b"VXSYMTAB", "expected one named Vortex kernel")
    offset, size, _, pc = struct.unpack("<IHHQ", data[-28:-12])
    start, end = struct.unpack("<QQ", data[:16])
    require(offset == 0 and data[-28-size:-28] == entry.encode("ascii") and start <= pc < end,
            "vxbin footer does not bind " + entry)
    return pc


def run_stage(recorder, label, argv, cwd, timeout=60):
    record, output = recorder.command(label, argv, cwd, timeout)
    require(record["returncode"] == 0 and not record["timed_out"], label + " failed")
    return output


def stage_case(module, ir, case_id=CASE_ID):
    entry = ir["entry"]
    require(entry in CORPUS_HASHES, "unsupported sample entry")
    evidence = FRONTEND_RUN / entry
    corpus_path = evidence / "corpus.json"
    corpus_sha = sha256(corpus_path)
    require(corpus_sha == CORPUS_HASHES[entry], "frozen frontend corpus changed")
    corpus = read_json(corpus_path)
    case = next(item for item in corpus["cases"] if item["id"] == case_id)
    pointers = ("x", "z") if entry == "copy_u32" else ("x", "y", "z")
    scalars = ("n", "alpha") if entry == "affine_u32" else ("n",)
    signature = [(name, "u64", "pointer") for name in pointers] + [(name, "u32", "scalar") for name in scalars]
    require([(item["name"], item["type"], item["kind"]) for item in ir["params"]] == signature,
            "sample parameter signature mismatch")
    for group in ("inputs", "expected"):
        (module / group).mkdir()
        for key in pointers:
            name = "{}/{}_{}.bin".format(group, case_id, key)
            path = evidence / name
            require(sha256(path) == corpus["files"][name], "frozen case changed: " + name)
            require(path.stat().st_size == case["words"] * 4, "unexpected frozen case size")
            shutil.copy2(path, module / name)
    (module / "copy_case.hpp").write_text(case_header(case, ir), encoding="ascii")
    return case, corpus_sha


def case_header(case, ir):
    entry = ir["entry"]
    pointers = [item["name"] for item in ir["params"] if item["kind"] == "pointer"]
    scalars = [item["name"] for item in ir["params"] if item["kind"] == "scalar"]
    values = dict(n=case["n"], grid=case["grid"], block=case["block"],
                  buffer_bytes=case["words"] * 4, guard_bytes=32, params_size=ir["params_size"])
    values.update({item["name"] + "_offset": item["offset"] for item in ir["params"]})
    header = ["#pragma once", "#include <array>", "#include <cstdint>", "namespace copy_case {",
              'constexpr char id[] = "{}";'.format(case["id"]), 'constexpr char entry[] = "{}";'.format(entry)]
    header += ["constexpr uint32_t {} = {};".format(key, value) for key, value in values.items()]
    header += ["struct BufferSpec { const char* name; uint32_t offset; };",
               "struct ScalarSpec { const char* name; uint32_t offset; uint32_t value; };",
               "constexpr std::array<BufferSpec, {}> buffers{{{{".format(len(pointers))]
    header += ['  {{"{0}", {0}_offset}},'.format(name) for name in pointers]
    header += ["}};", "constexpr std::array<ScalarSpec, {}> scalars{{{{".format(len(scalars))]
    header += ['  {{"{0}", {0}_offset, {1}u}},'.format(name, case[name]) for name in scalars]
    header += ["}};", "}", ""]
    return "\n".join(header)


def backend_libraries(backend):
    build = BUILDS / ("ab-d5-block32-20261108-v1-" + backend)
    path = build / "sw/runtime"
    evidence = PROJECT / "results" / build.name / "artifacts/sw/runtime"
    names = ("libvortex.so", "libvortex-" + backend + ".so", "lib" + backend + ".so")
    hashes = {name: sha256(path / name) for name in names}
    require(hashes == {name: sha256(evidence / name) for name in names},
            "simulator/runtime identity differs from D5 " + backend)
    return path, hashes


def validate(run, recorder):
    summary = recorder.summary
    module = run / "module"
    module.mkdir()
    src = PROJECT / "native/ptx_copy"
    for name in ("kernel.cpp", "main.cpp", "Makefile"):
        shutil.copy2(src / name, module / name)
    source = PROJECT / "ptx/samples/copy_u32.ptx"
    run_stage(recorder, "frontend", ["python3", "-B", PROJECT / "scripts/ptx_frontend.py",
              source, "--target-lock", SIM_LOCK, "--output", module / "frontend"], run)
    frontend = read_json(module / "frontend/manifest.json")
    require(frontend["files"]["kernel_body.hpp"] ==
            read_json(FRONTEND_EVIDENCE / "module/manifest.json")["files"]["kernel_body.hpp"],
            "generated body differs from the checked frontend copy")
    shutil.copy2(module / "frontend/kernel_body.hpp", module / "kernel_body.hpp")
    ir = read_json(module / "frontend/ir.json")
    case, corpus_sha = stage_case(module, ir)
    sim_build = BUILDS / "ab-d5-block32-20261108-v1-simx"
    kernel_lib = sim_build / "sw/kernel/libvortex2.a"
    require(kernel_lib.is_file(), "existing Vortex kernel library required")
    require(sha256(sim_build / "tests/regression/common.mk") ==
            sha256(PROJECT / "upstream/vortex/tests/regression/common.mk"), "generated device build rules changed")
    require(run_stage(recorder, "source_commit", ["git", "-C", VORTEX, "rev-parse", "HEAD"], run).strip() ==
            read_json(SIM_LOCK)["vortex"]["commit"], "fixed Vortex commit mismatch")
    config = read_json(SIM_LOCK.with_name("native_smoke.json"))
    defines = " ".join("-D{}={}".format(name, value) for name, value in config["defines"].items())
    summary["device_build"] = "FAIL"
    run_stage(recorder, "device_build", ["make", "ROOT_DIR=" + str(sim_build),
              "CONFIGS=" + defines, "kernel.vxbin", "kernel.dump"], module, timeout=180)
    entry_pc = vxbin_entry(module / "kernel.vxbin")
    artifacts = ("kernel.cpp", "main.cpp", "copy_case.hpp", "kernel_body.hpp", "kernel.elf", "kernel.vxbin", "kernel.dump")
    manifest = dict(schema_version="ptx-vx-copy-device-package-v1", loadable=True, scope="copy_u32 smoke",
                    entry="copy_u32", image_file="kernel.vxbin", image_format="vortex-vxbin-vxsymtab",
                    runtime_entry_pc=entry_pc, source_sha256=sha256(source),
                    image_sha256=sha256(module / "kernel.vxbin"),
                    profile=frontend["profile"], abi_version=frontend["abi_version"],
                    params=ir["params"], params_size=ir["params_size"], params_align=ir["params_align"],
                    target_lock_hash=sha256(SIM_LOCK), u280_candidate_lock_hash=sha256(BOARD_LOCK),
                    kernel_lib_sha256=sha256(kernel_lib), corpus_sha256=corpus_sha, case=case,
                    files={name: sha256(module / name) for name in artifacts})
    write_json(module / "manifest.json", manifest)
    summary.update(device_build="PASS", image_sha256=manifest["image_sha256"])
    recorder.save()

    for backend in ("simx", "rtlsim"):
        stage = run / backend
        stage.mkdir()
        (stage / "actual").mkdir()
        lib, hashes = backend_libraries(backend)
        result = dict(status="FAIL", library_sha256=hashes, image_sha256=manifest["image_sha256"])
        summary["backends"][backend] = result
        host = stage / "ptx_copy"
        run_stage(recorder, backend + "_compile", ["g++", "-std=c++17", "-Wall", "-Wextra",
                  "-Werror", "-O2", "-I" + str(VORTEX / "sw/runtime/include"),
                  module / "main.cpp", "-L" + str(lib), "-lvortex", "-o", host], stage)
        stdout = run_stage(recorder, backend + "_run", ["env", "VORTEX_DRIVER=" + backend,
                           "LD_LIBRARY_PATH=" + str(lib), host, module / "inputs", stage / "actual"],
                           module, timeout=120)
        require("CAPTURE_COMPLETE 1" in stdout.splitlines(), "missing runtime completion marker")
        comparison = capture_comparison(module, stage / "actual", stdout, case, ir, entry_pc)
        write_json(stage / "comparison.json", comparison)
        require(comparison["status"] == "PASS", backend + " capture mismatch")
        result.update(status="PASS", comparison=backend + "/comparison.json")
        recorder.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    require(re.fullmatch(r"ptx-copy-[A-Za-z0-9_.-]{1,70}", args.run_id), "invalid run id")
    run = PROJECT / "results" / args.run_id
    run.mkdir()
    summary = dict(schema_version="ptx-vx-copy-device-run-v1", run_id=args.run_id, status="FAIL",
                   device_build="NOT_RUN", backends={name: {"status": "NOT_RUN"} for name in ("simx", "rtlsim", "u280")},
                   independent_acceptance="NOT_RUN", commands=[], started_at=utc_now())
    recorder = Recorder(run, summary, dict(os.environ))
    try:
        shutil.copy2(__file__, run)
        validate(run, recorder)
        summary["status"] = "PASS"
    except (RuntimeError, OSError, ValueError, struct.error) as exc:
        summary["error"] = str(exc)
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    print("{} {}".format(summary["status"], run))
    if "error" in summary:
        print(summary["error"])
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
