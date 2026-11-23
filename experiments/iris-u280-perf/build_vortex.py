"""Build the native Iris device module with the same locked rules as PTX."""
import argparse
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_c_v03_receipt import TOOLCHAIN
from ptx_module import inspect_vxbin, makefile, target, validate
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, VORTEX, read_json, require, run_stage, write_json


def build(run, prior, recorder, label, lock):
    ptx = prior / "modules" / label
    meta, _ = validate(ptx, lock.read_bytes())
    require(meta["source_sha256"] == sha256(ROOT / "ptx/samples/iris_nearest_centroid_u32.ptx"),
            "archived Iris PTX differs from the current source")
    proof = read_json(ptx / "build.json")
    head = run_stage(recorder, label + "_head", ["git", "-C", VORTEX, "rev-parse", "HEAD"], run).strip()
    require(head == read_json(ROOT / "configs/target_lock.json")["vortex"]["commit"] == proof["source_commit"],
            "upstream commit differs")
    run_stage(recorder, label + "_diff", ["git", "-C", VORTEX, "diff", "--exit-code", "HEAD", "--"], run)
    locked, defines, _ = target(lock.read_bytes(), (ptx / "hardware.json").read_bytes())
    files = {name: digest for name, digest in locked["toolchain"]["observed_file_sha256"].items()
             if name.startswith(("llvm-vortex/", "libc64/", "libcrt64/", "riscv64-gnu-toolchain/"))}
    require(proof["toolchain_files"] == files and all(sha256(TOOLCHAIN / name) == digest for name, digest in files.items()),
            "toolchain differs from the PTX build")
    configs = "CONFIGS=" + " ".join("-D%s=%d" % item for item in sorted(defines.items()))
    isolated = ROOT / "build" / run.name / label
    isolated.mkdir(parents=True)
    module = run / label
    module.mkdir()
    shutil.copyfile(HERE / "vortex_kernel.cpp", module / "kernel.cpp")
    (module / "Makefile").write_text(makefile().replace("VX_HDRS := kernel_body.hpp", "VX_HDRS :="), encoding="ascii")
    (module / ".depend").write_text("# Device-only build.\n", encoding="ascii")
    run_stage(recorder, label + "_configure", ["bash", VORTEX / "configure", "--xlen=64", "--tooldir=" + str(TOOLCHAIN)], isolated)
    run_stage(recorder, label + "_kernel_lib", ["make", "-j2", "-C", isolated / "sw/kernel", "XLEN=64", configs], run)
    run_stage(recorder, label + "_native", ["make", "-C", module, "ROOT_DIR=" + str(isolated),
              "VORTEX_HOME=" + str(VORTEX), "XLEN=64", "KERNEL_LIB=vortex2", configs, "kernel.vxbin", "kernel.dump"], run)
    inspected = inspect_vxbin((module / "kernel.vxbin").read_bytes())
    evidence = dict(native_image_sha256=sha256(module / "kernel.vxbin"), native_source_sha256=sha256(module / "kernel.cpp"),
                    native_disassembly_sha256=sha256(module / "kernel.dump"), ptx_image_sha256=meta["image_sha256"],
                    ptx_manifest_sha256=sha256(ptx / "manifest.json"), lock_sha256=sha256(lock),
                    source_commit=head, toolchain_files=files, symbol=inspected)
    write_json(module / "native.json", evidence)
    return evidence


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    cli.add_argument("prior", type=Path)
    a = cli.parse_args()
    run = a.output.resolve()
    run.mkdir()
    report = dict(status="RUNNING", board_execution="NOT_RUN", commands=[], modules={},
                  argv=[sys.executable, "-B", *sys.argv], started_at=utc_now())
    rec = Recorder(run, report, dict(os.environ))
    try:
        for label, lock in (("board", BOARD_LOCK), ("sim", SIM_LOCK)):
            report["modules"][label] = build(run, a.prior.resolve(), rec, label, lock)
        report.update(status="PASS", exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
