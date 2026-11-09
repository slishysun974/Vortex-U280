"""Create the independent U280 source-preparation candidate exactly once."""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")


def main():
    parent = ROOT / "configs/candidates/block32-v1/target_lock.json"
    lock = copy.deepcopy(json.loads(parent.read_text()))
    folder = ROOT / "configs/candidates/u280-hbm32-v1"
    folder.mkdir(exist_ok=False)
    config = dict(schema_version="u280-fpga-candidate-v1", status="draft", frozen=False,
        target_id="vortex-v3-rv64-1c8w4t-u280-hbm32-draft-v1", xlen=64,
        defines={"VX_CFG_NUM_CLUSTERS": 1, "VX_CFG_NUM_CORES": 1,
                 "VX_CFG_NUM_WARPS": 8, "VX_CFG_NUM_THREADS": 4,
                 "PLATFORM_MERGED_MEMORY_INTERFACE": True},
        platform="/opt/xilinx/platforms/xilinx_u280_gen3x16_xdma_1_202211_1/xilinx_u280_gen3x16_xdma_1_202211_1.xpfm",
        device_part="xcu280-fsvh2892-2L-e", target="hw", kernel_frequency_mhz=200,
        frequency_scaling=0, jobs=2, implementation_max_threads=2,
        expected_memory_masters=["m_axi_mem_0"], expected_host_master="m_axi_host",
        connectivity=["vortex_afu_1.m_axi_mem_0:HBM[0:31]", "vortex_afu_1.m_axi_host:HOST[0]"],
        platform_memory=dict(banks=32, address_bits=33, data_bits=512),
        build_policy="source preprocessing allowed; full synthesis/implementation requires resource confirmation",
        clock_scope="200 MHz is a proposed build target, not a measured frequency",
        acceptance={k: "NOT_RUN" for k in ("source_preparation", "vivado_elaboration", "xo_packaging",
            "synthesis", "implementation", "host_memory", "board_execution", "independent_reproduction")})
    write(folder / "fpga.json", config)
    lock.update(schema_version="target-lock-u280-hbm32-draft-v1", target_id=config["target_id"],
        hardware_config_file="configs/candidates/u280-hbm32-v1/fpga.json",
        hardware_config_sha256=digest(folder / "fpga.json"), acceptance=config["acceptance"],
        observations=dict(parent_lock_sha256=digest(parent),
            root_lock_sha256=digest(ROOT / "configs/target_lock.json"),
            revision_scope="8w4t native candidate to physical U280: SYNTHESIS/VIVADO DSP FPU, 32-bank 33-bit HBM, merged AXI master, HOST[0]; new builds required; ABI/PTX unchanged"),
        platform_tools=dict(platform_name=Path(config["platform"]).stem,
            vivado="2023.1", vitis="2023.1", xrt="2.13.479", shell="xilinx_u280_gen3x16_xdma_base_1",
            observation_evidence="results/u280-inventory-20261108-232952-683/inventory.json",
            compatibility_acceptance="NOT_RUN"))
    write(folder / "target_lock.json", lock)
    (folder / "target_lock.sha256").write_text(digest(folder / "target_lock.json") + "\n", encoding="ascii")
    print(folder)


if __name__ == "__main__":
    main()
