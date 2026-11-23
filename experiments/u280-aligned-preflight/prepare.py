"""Prepare the offline U280 aligned-predicate pairing and address probe."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tarfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / name) for name in (
    "scripts", "experiments/ptx-aligned-parameters", "experiments/ptx-performance-attribution",
    "experiments/ptx-aligned-production")]

import ptx_frontend_v13 as aligned
import ptx_frontend_v14 as merged
from audit import execute as audit
from build import compile_device
from check_c_v03_receipt import TOOLCHAIN
from ptx_module import ALIGNED_PARAMETER_ACCESS, SAME_PREDICATE_LOWERING, inspect_vxbin, target, validate
from ptx_u280 import QUERY_SOURCE
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, read_json, require, run_stage, write_json
from u280_perf_pair import TRIALS, WARM, operator_path, validate_ptx_layout, workloads
from validate import performance_bundles
from verify_bundle import ALPHA, BLOCK, COUNTS, GUARD, OPERATORS, ROLES, ROUTES, SCHEMA, geometry, layout, verify


MODELS = {"aligned": PROJECT / "results/local-ptx-aligned-production-build-20261121-v1",
          "merged": PROJECT / "results/local-ptx-same-predicate-production-build-20261121-v1"}
PROBE = PROJECT / "results/local-ptx-align-build-20261121-v1"
AFU = PROJECT / "results/local-ptx-same-predicate-afu-review-20261121-v1/summary.json"
HARNESS = Path(__file__).resolve().parent


def negative_checks(out, rec, source):
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    requests = (
        ("reject_board_aligned_prepare", cli + ["prepare", source, "--output", out / "unexpected-module",
           "--hardware", BOARD_LOCK.with_name("fpga.json"), "--device-parameter-access", ALIGNED_PARAMETER_ACCESS,
           "--predicate-lowering", SAME_PREDICATE_LOWERING, "--target-lock", BOARD_LOCK]),
        ("reject_d5_module_at_board_lock", cli + ["validate", MODELS["merged"] / "modules/copy", "--target-lock", BOARD_LOCK]),
    )
    import json
    for label, argv in requests:
        record, stdout = rec.command(label, argv, out, 60)
        require(record["returncode"] == 1 and not record["timed_out"] and
                json.loads(stdout)["error"]["code"] == "E_TARGET_MISMATCH", "formal physical rejection differs")
    require(not (out / "unexpected-module").exists(), "rejected board module left loadable output")


def stage_frozen(bundle):
    origins, sources = {}, {}
    for archive, build, plan in performance_bundles():
        for op, spec, subdir in workloads(plan):
            n = spec["n"]
            destination = bundle / "inputs" / op / str(n)
            destination.mkdir(parents=True)
            require(spec == geometry(n), "original workload geometry differs")
            files = {}
            for role in (*ROLES[op], "expected"):
                file = archive / "inputs" / subdir / (role + ".bin")
                name = (Path("inputs") / subdir / file.name).as_posix()
                require(sha256(file) == plan["files"][name], "frozen input differs: " + name)
                shutil.copyfile(file, destination / file.name)
                files[file.name] = plan["files"][name]
            origins[f"{op}/{n}"] = dict(plan=str((archive / "plan.json").relative_to(PROJECT).as_posix()),
                                       plan_sha256=sha256(archive / "plan.json"), files=files)
            sources[op] = operator_path(plan, build / "board", op) / "ptx"
    require(set(origins) == {f"{op}/{n}" for op in OPERATORS for n in COUNTS}, "incomplete frozen input coverage")
    return origins, sources


def board_compile_root(out, rec, source):
    # The official bytewise build checks the board target, source revision and
    # all device tool hashes before populating a fresh kernel-library directory.
    root = PROJECT / "build" / out.name
    board = out / "bytewise-control"
    cli = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
    run_stage(rec, "prepare_bytewise_control", cli + ["prepare", source / "source.ptx", "--output", board,
              "--hardware", BOARD_LOCK.with_name("fpga.json"), "--target-lock", BOARD_LOCK], out, 60)
    run_stage(rec, "build_bytewise_control", cli + ["build", board, "--build-root", root, "--tooldir", TOOLCHAIN,
              "--vortex-source", VORTEX, "--target-lock", BOARD_LOCK], out, 360)
    _, image = validate(board, BOARD_LOCK.read_bytes())
    require(image == (source / "kernel.vxbin").read_bytes(), "bytewise U280 control did not reproduce")
    _, defines, _ = target(BOARD_LOCK.read_bytes(), BOARD_LOCK.with_name("fpga.json").read_bytes())
    return root, "CONFIGS=" + " ".join("-D%s=%d" % item for item in sorted(defines.items()))


def stage_image(folder, dest, names):
    dest.mkdir(parents=True)
    for name in names:
        shutil.copyfile(folder / name, dest / name)


def candidates(bundle, out, rec, sources):
    root, config = board_compile_root(out, rec, sources["copy"])
    inventory = {}
    for op in OPERATORS:
        portable = sources[op]
        manifest, _ = validate(portable, BOARD_LOCK.read_bytes())
        validate_ptx_layout(manifest, op)
        ir = read_json(portable / "ir.json")
        want = layout(op)
        fields = [{k: field[k] for k in ("name", "offset", "size", "align")} for field in manifest["params"]]
        require(manifest["params_size"] == want["bytes"] and fields == want["fields"] and
                all(f["offset"] % f["align"] == 0 and f["offset"] + f["size"] <= want["bytes"] for f in fields),
                "board PTX parameter layout differs")
        inventory[op] = {}
        for route, generator in (("aligned", aligned), ("merged", merged)):
            model = MODELS[route] / "modules" / op
            model_manifest, model_image = validate(model, SIM_LOCK.read_bytes())
            require(model_manifest.get("predicate_lowering") == (SAME_PREDICATE_LOWERING if route == "merged" else None)
                    and model_manifest["device_parameter_access"] == ALIGNED_PARAMETER_ACCESS and
                    all((model / name).read_bytes() == (portable / name).read_bytes()
                        for name in ("source.ptx", "ir.json", "abi.json", "kernel.cpp", "Makefile")), "formal model/board source differs")
            folder = out / "compiled" / op / route
            stage_image(portable, folder, ("source.ptx", "ir.json", "abi.json", "kernel.cpp", "Makefile"))
            body, mapping = generator.emit_cpp(ir)
            require(body.encode() == (model / "kernel_body.hpp").read_bytes() and mapping == read_json(model / "source_map.json"),
                    "official code generation differs from the model artifact")
            (folder / "kernel_body.hpp").write_bytes(body.encode())
            write_json(folder / "source_map.json", mapping)
            built = compile_device(folder, root, config, rec, op + "_" + route)
            raw = (folder / "kernel.vxbin").read_bytes()
            require(raw == model_image, "board-built device image differs from the validated D5 image")
            evidence = dict(compiler=generator.COMPILER, parameter_access=ALIGNED_PARAMETER_ACCESS,
                            predicate_lowering=model_manifest.get("predicate_lowering"), layout=want,
                            board_lock_sha256=sha256(BOARD_LOCK), image_sha256=built["kernel.vxbin"],
                            model_image_sha256=model_manifest["image_sha256"], vxbin=inspect_vxbin(raw),
                            formal_loadable=False, board_execution="NOT_RUN")
            dest = bundle / "candidates" / op / route
            stage_image(folder, dest, ("source.ptx", "abi.json", "kernel.cpp", "kernel_body.hpp", "source_map.json",
                                      "Makefile", "kernel.vxbin", "kernel.elf", "kernel.dump"))
            write_json(dest / "candidate.json", evidence)
            inventory[op][route] = evidence
    probe = out / "compiled/probe"
    stage_image(PROBE / "probe", probe, ("kernel.cpp", "Makefile"))
    receipt = read_json(PROBE / "summary.json")
    require(receipt["status"] == "PASS" and all(sha256(probe / name) == receipt["probe"][name] for name in ("kernel.cpp", "Makefile")),
            "original bytewise probe source differs")
    built = compile_device(probe, root, config, rec, "bytewise_address_probe")
    require(built["kernel.vxbin"] == receipt["probe"]["kernel.vxbin"], "U280 probe differs from the exercised D5 probe")
    stage_image(probe, bundle / "probe", ("kernel.cpp", "Makefile", "kernel.vxbin", "kernel.dump"))
    return inventory, built["kernel.vxbin"]


def check_tar(archive, bundle):
    with tarfile.open(archive, "r:gz") as packed:
        seen = {}
        for member in packed:
            path = Path(member.name)
            require(not path.is_absolute() and path.parts[0] == "bundle" and ".." not in path.parts and
                    (member.isdir() or member.isfile()), "unsafe archived member")
            if member.isfile():
                name = Path(*path.parts[1:]).as_posix()
                require(name not in seen, "duplicate packaged member")
                with packed.extractfile(member) as stream:
                    seen[name] = hashlib.sha256(stream.read()).hexdigest()
    require(seen == {p.relative_to(bundle).as_posix(): sha256(p) for p in bundle.rglob("*") if p.is_file()},
            "archive bytes differ from verified staging tree")
    return len(seen)


def prepare(out, rec):
    bundle = out / "bundle"
    bundle.mkdir()
    offline = audit(out, rec)
    write_json(bundle / "offline-audit.json", offline)
    origins, sources = stage_frozen(bundle)
    negative_checks(out, rec, sources["copy"] / "source.ptx")
    images, probe = candidates(bundle, out, rec, sources)
    afu = read_json(AFU)
    require(afu["status"] == "PASS" and afu["exit_code"] == 0 and
            afu["build_sha256"] == sha256(MODELS["merged"] / "summary.json") and set(afu["original_inputs"]) == set(origins),
            "formal AFU model evidence differs")
    shutil.copyfile(BOARD_LOCK, bundle / "target_lock.json")
    shutil.copyfile(BOARD_LOCK.with_name("fpga.json"), bundle / "hardware.json")
    for name in ("README.md", "verify_bundle.py", "read_cp_caps.cpp"):
        shutil.copyfile(HARNESS / name, bundle / name)
    (bundle / "query.cpp").write_bytes(QUERY_SOURCE.encode())
    schedule = [dict(operator=op, n=n, pair=i, warmup=i < WARM,
                     order=list(ROUTES if i % 2 == 0 else ROUTES[::-1]))
                for op in OPERATORS for n in COUNTS for i in range(WARM + TRIALS)]
    write_json(bundle / "pair-schedule.json", schedule)
    plan = dict(schema=SCHEMA, operators=OPERATORS, cases=[geometry(n) for n in COUNTS], routes=ROUTES,
                block=BLOCK, guard_words=GUARD, affine_alpha=ALPHA, warm=WARM, trials=TRIALS,
                board_lock_sha256=sha256(BOARD_LOCK), xclbin_sha256=offline["xclbin_sha256"],
                xclbin_uuid=offline["xclbin_uuid"], runtime_sha256=offline["runtime_sha256"],
                formal_aligned_load="BLOCKED", live_vm="NOT_RUN", live_staging="NOT_RUN", board_execution="NOT_RUN",
                original_inputs=origins, images=images, probe_sha256=probe, afu_model_evidence_sha256=sha256(AFU),
                files={p.relative_to(bundle).as_posix(): sha256(p) for p in sorted(bundle.rglob("*")) if p.is_file()})
    write_json(bundle / "plan.json", plan)
    receipt = verify(bundle)
    run_stage(rec, "portable_bundle_preflight", [sys.executable, "-B", bundle / "verify_bundle.py", bundle], out, 60)
    archive = Path(shutil.make_archive(str(out / "u280-aligned-predicate-pair"), "gztar", root_dir=out, base_dir="bundle"))
    rec.summary.update(bundle=receipt, archive=archive.name, archive_sha256=sha256(archive),
                       archive_members=check_tar(archive, bundle), xrt_host_probe_compile="NOT_RUN")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    out = args.output.resolve()
    require(out.parent == PROJECT / "results" and out.name.startswith("u280-aligned-predicate-preflight-"), "use a fresh offline run")
    out.mkdir()
    report = dict(status="RUNNING", commands=[], started_at=utc_now(), argv=[sys.executable, "-B", *sys.argv],
                  board_execution="NOT_RUN", formal_aligned_load="BLOCKED", new_model_execution="NOT_RUN")
    rec = Recorder(out, report, dict(os.environ))
    try:
        prepare(out, rec)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], out, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
