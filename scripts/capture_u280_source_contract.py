"""Capture fixed-source platform requirements; never invokes XRT or FPGA tools."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from run_native_smoke import PROJECT, sha256, utc_now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    lock = json.loads((PROJECT / "configs/target_lock.json").read_text())
    manifest_path = PROJECT / lock["evidence"] / "source_manifest.json"
    manifest = {e["path"]: e["sha256"] for e in json.loads(manifest_path.read_text())}
    relatives = ["sw/runtime/xrt/vortex.cpp", "hw/syn/xilinx/xrt/platforms.mk",
                 "hw/syn/xilinx/xrt/Makefile", "docs/fpga_setup.md"]
    files = []
    for relative in relatives:
        source = PROJECT / "upstream/vortex" / relative
        destination = args.output / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        digest = sha256(destination)
        files.append(dict(path=relative, sha256=digest, matches_fixed_manifest=digest == manifest[relative]))
    passed = sha256(manifest_path) == lock["source_manifest_sha256"] and all(f["matches_fixed_manifest"] for f in files)
    result = dict(schema_version="u280-source-contract-v1", started_at=utc_now(), argv=sys.argv,
                  status="PASS" if passed else "FAIL", exit_code=0 if passed else 1,
                  scope="four source files match pinned manifest only; platform/device execution NOT_RUN",
                  lock_sha256=sha256(PROJECT / "configs/target_lock.json"), source_commit=lock["vortex"]["commit"],
                  files=files, physical_xrt="NOT_RUN", fpga_build="NOT_RUN", board="NOT_RUN",
                  reviewed_requirements={
                      "device_selection": "XRT_DEVICE_INDEX parsed as integer; map assigned BDF/UUID to index before execution",
                      "device_open_side_effect": "real XRT init loads XCLBIN_PATH; do not use native device-open as read-only inventory",
                      "u280_memory": "32 banks, 33-bit platform address width, m_axi_mem_0 to HBM[0:31]",
                      "control_memory": "m_axi_host to HOST[0]; real C++ XRT uses host_only BO",
                      "model_difference": "NOXRT model host buffers use aligned_alloc; cannot validate real host-memory bridge",
                      "build_prerequisites": "actual PLATFORM, XILINX_VITIS/XILINX_VIVADO, license and isolated new FPGA build",
                  })
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
