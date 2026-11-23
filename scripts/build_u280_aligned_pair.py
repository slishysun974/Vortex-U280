"""Rebuild the frozen U280 aligned pair and bytewise field-address probe offline."""
import argparse
import os
from pathlib import Path
import shutil
import sys

from check_c_v03_receipt import TOOLCHAIN
from ptx_module import ALIGNED_PARAMETER_ACCESS, SAME_PREDICATE_LOWERING, inspect_vxbin, target, validate
from ptx_u280_aligned import PLAN_SHA256
from run_native_smoke import PROJECT, Recorder, sha256, utc_now
from run_ptx_copy import VORTEX, require, run_stage

PREPARED = PROJECT / "results/u280-aligned-predicate-preflight-20261121-v1/bundle"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    record = dict(status="RUNNING", exit_code=None, commands=[], started_at=utc_now(), board_execution="NOT_RUN")
    recorder = Recorder(output, record, dict(os.environ))
    try:
        require(sha256(PREPARED / "plan.json") == PLAN_SHA256, "frozen pair plan differs")
        run_stage(recorder, "verify_frozen", [sys.executable, "-B", PREPARED / "verify_bundle.py", PREPARED], output)
        lock, hardware = (PREPARED / name for name in ("target_lock.json", "hardware.json"))
        root = PROJECT / "build" / output.name
        record["modules"] = {}
        for op in ("copy", "vadd", "affine"):
            for route in ("aligned", "merged"):
                original = PREPARED / "candidates" / op / route
                directory = output / "modules" / op / route
                label = op + "_" + route
                argv = [sys.executable, "-B", PROJECT / "scripts/ptx_module.py"]
                lowering = ["--predicate-lowering", SAME_PREDICATE_LOWERING] if route == "merged" else []
                run_stage(recorder, "prepare_" + label, argv + ["prepare", original / "source.ptx", "--output",
                    directory, "--target-lock", lock, "--hardware", hardware, "--u280-aligned",
                    "--device-parameter-access", ALIGNED_PARAMETER_ACCESS, *lowering], output, 60)
                run_stage(recorder, "build_" + label, argv + ["build", directory, "--target-lock", lock,
                    "--vortex-source", VORTEX, "--tooldir", TOOLCHAIN, "--build-root", root / label], output, 360)
                manifest, image = validate(directory, lock.read_bytes())
                require(image == (original / "kernel.vxbin").read_bytes(), "official image differs: " + label)
                record["modules"][label] = manifest["image_sha256"]
        probe = output / "probe"
        probe.mkdir()
        shutil.copyfile(PROJECT / "native/u280_args_probe.cpp", probe / "kernel.cpp")
        shutil.copyfile(PREPARED / "probe/Makefile", probe / "Makefile")
        (probe / ".depend").write_text("# Device-only build.\n", encoding="utf-8")
        _, defines, _ = target(lock.read_bytes(), hardware.read_bytes())
        flags = "CONFIGS=" + " ".join("-D%s=%d" % item for item in sorted(defines.items()))
        run_stage(recorder, "build_bytewise_probe", ["make", "-C", probe, "ROOT_DIR=" + str(root / "copy_aligned"),
            "VORTEX_HOME=" + str(VORTEX), "XLEN=64", "KERNEL_LIB=vortex2", flags, "kernel.vxbin", "kernel.dump"], output, 180)
        inspect_vxbin((probe / "kernel.vxbin").read_bytes())
        record.update(probe_sha256=sha256(probe / "kernel.vxbin"), plan_sha256=PLAN_SHA256, status="PASS", exit_code=0)
    except Exception as error:
        record.update(status="FAIL", exit_code=1, error=str(error))
    record["finished_at"] = utc_now()
    recorder.save()
    print(record["status"], output, record.get("error", ""))
    return record["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
