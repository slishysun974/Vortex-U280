"""Package and run the eight ordinary-address V03 cases on the fixed U280."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve()
if sys.version_info[:2] == (3, 6):
    sys.path.insert(0, str(HERE.parents[1] / "vendor/dataclasses-0.8"))

from check_c_v03_receipt import CORPUS_SHA, DELIVERIES, capture, corpus, review_backend
from ptx_module import BOARD_LOCK_SHA, validate
from ptx_u280 import BUSES, QUERY_SOURCE, RUNTIME_SHAS, XCLBIN_SHA, create_binding
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, read_json, require, run_stage, write_json
from runtime_backends import BACKENDS

SCHEMA = "c-v03-u280-ordinary-v1"
BOARD_BACKEND = "u280-xrt"
PY_FILES = (
    HERE.name, "check_c_v03_receipt.py", "native_dependencies.py", "ptx_frontend.py", "ptx_frontend_v12.py",
    "ptx_launch.py", "ptx_module.py", "ptx_runtime.py", "ptx_u280.py", "run_native_smoke.py",
    "run_ptx_copy.py", "runtime_backends.py", "u280_board_smoke.py",
)


def check_commands(run, report):
    require(report["status"] == "PASS" and report["exit_code"] == 0 and report["commands"],
            "missing successful source run: " + str(run))
    for command in report["commands"]:
        code = 1 if command["label"].startswith(("wrong_lock_", "reject_model_lock_")) else 0
        require(command["returncode"] == code and not command["timed_out"] and
                sha256(run / command["log"]) == command["log_sha256"], "source command or log differs")


def preflight(root):
    plan = read_json(root / "plan.json")
    require(plan["schema"] == SCHEMA and plan["corpus_sha256"] == CORPUS_SHA and
            plan["xclbin_sha256"] == XCLBIN_SHA and plan["runtime_sha256"] == RUNTIME_SHAS,
            "wrong V03 package schema or target")
    observed = {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob("*")
                if p.is_file() and p != root / "plan.json"}
    require(observed == plan["files"], "package member or hash differs")
    lock = (root / "target_lock.json").read_bytes()
    require(sha256(root / "target_lock.json") == BOARD_LOCK_SHA, "requires the fixed U280 lock")
    frozen = corpus(root / "corpus")
    require(set(plan["modules"]) == set(DELIVERIES), "wrong module set")
    for entry in DELIVERIES:
        module = root / "modules" / entry
        metadata, _ = validate(module, lock)
        require(metadata["entry"] == entry and metadata["source_sha256"] ==
                frozen["files"]["sources/" + entry + ".ptx"] and
                (module / "hardware.json").read_bytes() == (root / "hardware.json").read_bytes() and
                plan["modules"][entry] == dict(image_sha256=metadata["image_sha256"],
                                               manifest_sha256=sha256(module / "manifest.json")),
                "packaged module differs: " + entry)
    return plan, frozen


def prepare(run, build, models):
    built, simulated = (read_json(path / "summary.json") for path in (build, models))
    check_commands(build, built)
    check_commands(models, simulated)
    frozen = build / "corpus"
    manifest = corpus(frozen)
    require(built["corpus_sha256"] == simulated["corpus_sha256"] == CORPUS_SHA and
            built["board_lock_sha256"] == BOARD_LOCK_SHA, "build and model inputs differ")
    for name in ("check_c_v03_receipt.py", "ptx_frontend_v12.py", "ptx_launch.py", "ptx_module.py",
                 "ptx_runtime.py", "runtime_backends.py", "run_native_smoke.py", "run_ptx_copy.py"):
        require(sha256(HERE.parent / name) == simulated["implementation"][name],
                "implementation changed since model capture: " + name)
    for backend in BACKENDS:
        accepted = review_backend(models, frozen, backend, manifest)
        require(accepted == read_json(models / (backend + ".review.json")), "model receipt differs: " + backend)

    root = run / "bundle"
    (root / "scripts").mkdir(parents=True)
    for name in PY_FILES:
        shutil.copyfile(HERE.parent / name, root / "scripts" / name)
    (root / "query.cpp").write_bytes(QUERY_SOURCE.encode())
    shutil.copyfile(BOARD_LOCK, root / "target_lock.json")
    shutil.copyfile(BOARD_LOCK.with_name("fpga.json"), root / "hardware.json")
    shutil.copytree(frozen, root / "corpus")
    vendor = PROJECT / "third_party/dataclasses-0.8"
    backport = read_json(vendor / "provenance.json")
    require(backport["wheel_sha256"] == "0201d89fa866f68c8ebd9d08ee6ff50c0b255f8ec63a71c16fda7af82bb887bf",
            "unexpected Python backport")
    dependency = root / "vendor/dataclasses-0.8"
    dependency.mkdir(parents=True)
    for name, expected in backport["files"].items():
        require(Path(name).name == name and sha256(vendor / name) == expected, "backport member differs")
        shutil.copyfile(vendor / name, dependency / name)
    shutil.copyfile(vendor / "provenance.json", dependency / "provenance.json")

    modules = {}
    for entry in DELIVERIES:
        mod = build / "modules" / entry
        model = models / "modules" / entry
        metadata, image = validate(mod, BOARD_LOCK.read_bytes())
        _, model_image = validate(model, SIM_LOCK.read_bytes())
        require(built["modules"][entry]["manifest_sha256"] == sha256(mod / "manifest.json") and
                simulated["modules"][entry]["rebuilt_manifest_sha256"] == sha256(model / "manifest.json") and
                image == model_image, "module identity or model image differs: " + entry)
        out = root / "modules" / entry
        out.mkdir(parents=True)
        for name in ("manifest.json", *metadata["files"]):
            shutil.copyfile(mod / name, out / name)
        modules[entry] = dict(image_sha256=metadata["image_sha256"], manifest_sha256=sha256(mod / "manifest.json"))

    files = {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}
    write_json(root / "plan.json", dict(schema=SCHEMA, corpus_sha256=CORPUS_SHA, modules=modules, files=files,
        xclbin_sha256=XCLBIN_SHA, runtime_sha256=RUNTIME_SHAS, build_summary_sha256=sha256(build / "summary.json"),
        model_summary_sha256=sha256(models / "summary.json")))
    preflight(root)
    return Path(shutil.make_archive(str(run / "v03-u280-input"), "gztar", root_dir=run, base_dir="bundle"))


def bind(root, run, bdf, recorder):
    home = Path.home()
    libs = home / "vortex-u280-runtime/u280-runtime-20261109-v4/build/lib"
    bit = home / "vortex-u280-builds/u280-link-20261109-103830-671/out/vortex_afu.xclbin"
    require(sha256(bit) == XCLBIN_SHA and all(sha256(libs / n) == h for n, h in RUNTIME_SHAS.items()),
            "D10/D12 files differ")
    for name in ("XCL_EMULATION_MODE", "VORTEX_CP_POLL_TIMEOUT_S", "PYTHONPATH"):
        recorder.env.pop(name, None)
    recorder.env.update(VORTEX_DRIVER="xrt", XCLBIN_PATH=str(bit), VORTEX_PROFILING="0",
                        LD_LIBRARY_PATH=str(libs) + ":" + recorder.env.get("LD_LIBRARY_PATH", ""))
    for name in RUNTIME_SHAS:
        output = run_stage(recorder, "ldd_" + name, ["ldd", libs / name], run)
        require("not found" not in output, "unresolved D12 dependency: " + name)
    query = run / "xrt_bdf"
    run_stage(recorder, "compile_bdf_query", ["/opt/rh/devtoolset-9/root/usr/bin/g++", "-std=c++17", "-O2",
        "-I/opt/xilinx/xrt/include", root / "query.cpp", "-L/opt/xilinx/xrt/lib", "-lxrt_coreutil", "-o", query], run)
    devices = run / "devices.json"
    run_stage(recorder, "enumerate", ["xbutil", "examine", "--format", "JSON", "--output", devices], run)
    listing = read_json(devices)["system"]["host"]["devices"]
    indices = [i for i, d in enumerate(listing) if d["bdf"] == bdf and d["is_ready"] == "true"]
    require(len(indices) == 1, "BDF is not uniquely ready")
    index = indices[0]
    recorder.env["XRT_DEVICE_INDEX"] = str(index)
    create_binding(run / "binding", root / "target_lock.json", root / "hardware.json", libs, bit, query, bdf, index)
    recorder.summary.update(bdf=bdf, xrt_index=index)


def review_gate(run):
    binding = run / "binding/binding.json"
    gate_dir = binding.parent / "sessions" / run.name
    gate = read_json(gate_dir / "gate.json")
    require(gate["run_id"] == run.name and gate["binding_sha256"] == sha256(binding) and
            gate["status"] == gate["open_gate"] == gate["close_gate"] == "PASS" and
            int(gate["clock_readback"]["freq_mhz"]) == 200 and gate["artifact_hashes"]["xclbin"] == XCLBIN_SHA and
            gate["artifact_hashes"]["libraries"] == RUNTIME_SHAS and gate["artifact_hashes"]["lock"] == BOARD_LOCK_SHA,
            "physical open/close evidence differs")
    for label in ("device_list", "preflight", "loaded"):
        report = gate["reports"][label]
        require(report["file"] == label + ".json" and sha256(gate_dir / report["file"]) == report["sha256"],
                "raw board report differs: " + label)
    return sha256(gate_dir / "gate.json")


def review(root, run, frozen):
    gate_hash = review_gate(run)
    binding = run / "binding/binding.json"
    receipt = review_backend(run, root / "corpus", BOARD_BACKEND, frozen, binding=binding)
    receipt.update(gate_sha256=gate_hash,
                   capture_sha256=sha256(run / BOARD_BACKEND / "capture.json"))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action")
    pack = actions.add_parser("prepare")
    pack.add_argument("--run-id", required=True)
    pack.add_argument("--build", type=Path, required=True)
    pack.add_argument("--models", type=Path, required=True)
    for action in ("preflight", "run", "review", "capture"):
        cli = actions.add_parser(action)
        cli.add_argument("--bundle", type=Path, required=True)
        if action != "preflight":
            cli.add_argument("--output", type=Path, required=True)
        if action == "run":
            cli.add_argument("--bdf", required=True, choices=["0000:" + b + ":00.1" for b in BUSES])
    args = parser.parse_args()
    if args.action is None:
        parser.error("an action is required")
    if args.action == "prepare":
        run = PROJECT / "results" / args.run_id
        prefix = "c-v03-board-kit-"
    elif args.action == "run":
        run = args.output.resolve()
        prefix = "c-v03-u280-"
    else:
        root = args.bundle.resolve()
        _, frozen = preflight(root)
        if args.action == "capture":
            run = args.output.resolve()
            capture(run, root / "corpus", BOARD_BACKEND, frozen, binding=run / "binding/binding.json",
                    target_lock=root / "target_lock.json", modules=root / "modules")
            return 0
        result = (review(root, args.output.resolve(), frozen) if args.action == "review" else
                  dict(status="PASS", scope="offline package and module preflight", cases=len(frozen["cases"]),
                       plan_sha256=sha256(root / "plan.json"), board_execution="NOT_RUN"))
        print(json.dumps(result))
        return 0

    if not re.fullmatch(prefix + r"[A-Za-z0-9_-]{1,50}", run.name) or (
            args.action == "prepare" and run.name != args.run_id):
        parser.error("choose a fresh " + prefix + "* run directory")
    run.mkdir()
    report = dict(schema=SCHEMA, run_id=run.name, argv=[sys.executable, "-B", *sys.argv], commands=[],
                  started_at=utc_now(), status="RUNNING", board_execution="NOT_RUN",
                  high_address="NOT_RUN", physical_recovery="NOT_RUN", timing7="OPEN", independent_E="NOT_RUN")
    rec = Recorder(run, report, dict(os.environ))
    try:
        if args.action == "prepare":
            package = prepare(run, args.build.resolve(), args.models.resolve())
            report.update(scope="offline portable board input", archive=package.name, archive_sha256=sha256(package),
                          plan_sha256=sha256(run / "bundle/plan.json"))
        else:
            root = args.bundle.resolve()
            _, frozen = preflight(root)
            report.update(scope="physical U280 ordinary-address cases", plan_sha256=sha256(root / "plan.json"))
            bind(root, run, args.bdf, rec)
            # Native XRT dependencies must be on the child loader's startup path.
            command, _ = rec.command("capture", [sys.executable, "-B", root / "scripts" / HERE.name,
                "capture", "--bundle", root, "--output", run], run, 720)
            captured = run / BOARD_BACKEND / "capture.json"
            if captured.is_file():
                record = read_json(captured)
                if record["launch_attempts"]:
                    report["board_execution"] = "FAIL"
            elif command["timed_out"]:
                report["board_execution"] = "FAIL"
            require(command["returncode"] == 0 and not command["timed_out"], "physical capture failed")
            report.update(board_execution="PASS", receipt=review(root, run, frozen))
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
