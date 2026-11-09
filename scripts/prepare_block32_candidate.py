"""Create the versioned 8w x 4t candidate without changing the active lock."""
import json
from pathlib import Path
import subprocess
import sys

from run_native_smoke import PROJECT, PROFILES, sha256


def write(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")


def main():
    relative, target_id, defines = PROFILES["block32-v1"]
    destination = PROJECT / relative
    destination.mkdir(parents=True, exist_ok=False)
    baseline = PROJECT / "configs"
    config = json.loads((baseline / "native_smoke.json").read_text())
    flags = " ".join("-D{}={}".format(k, v) for k, v in sorted(defines.items()))
    command = [sys.executable, "-B", str(PROJECT / "upstream/vortex/ci/gen_config.py"),
               "--config=" + str(PROJECT / "upstream/vortex/VX_config.toml"),
               "--cflags=" + flags + " -DVX_CFG_XLEN=64", "--format=cflags"]
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (destination / "resolve.stdout").write_bytes(completed.stdout)
    (destination / "resolve.stderr").write_bytes(completed.stderr)
    write(destination / "preparation.json", dict(argv=command, exit_code=completed.returncode,
          baseline_lock_sha256=sha256(baseline / "target_lock.json"),
          changed_define={"VX_CFG_NUM_WARPS": {"old": 4, "new": 8}},
          acceptance="NOT_RUN; separate candidate; not adopted by C/D/E"))
    completed.check_returncode()
    config.update(target_id=target_id, defines=defines, schema_version="ab-hardware-block32-candidate-v1",
                  scope="Native block32 candidate only; PTX and independent acceptance NOT_RUN",
                  resolved_config_sha256=sha256(destination / "resolve.stdout"))
    write(destination / "native_smoke.json", config)
    lock = json.loads((baseline / "target_lock.json").read_text())
    lock.update(target_id=target_id, schema_version="target-lock-block32-draft-v1",
                hardware_config_file=relative + "/native_smoke.json",
                hardware_config_sha256=sha256(destination / "native_smoke.json"),
                observations={"parent_lock_sha256": sha256(baseline / "target_lock.json"),
                              "revision_scope": "NUM_WARPS 4 to 8; new isolated builds required; source/toolchain/ABI/PTX unchanged"},
                acceptance={"independent_reproduction": "NOT_RUN", "native_simx": "NOT_RUN",
                            "native_rtlsim": "NOT_RUN", "xrt_afu_sim": "NOT_RUN", "u280": "BLOCKED"})
    lock["runtime"]["built"] = False
    for name in ("rtlsim", "simx", "xrtsim"):
        lock["simulators"][name]["built"] = False
        lock["simulators"][name].pop("evidence", None)
    write(destination / "target_lock.json", lock)
    caps = dict(schema_version="target-caps-block32-draft-v1", target_id=target_id, xlen=64,
                status="draft", frozen=False, target_lock_hash=sha256(destination / "target_lock.json"),
                physical_threads_per_warp_candidate=4, warps_per_core_candidate=8, cores_candidate=1,
                resident_threads_per_core_candidate=32, p0_default_block_32_verified=False,
                launch_limits_verified=None, independent_reproduction="NOT_RUN",
                ptx_profile="ptx-vx-p0-v0.1-draft", safe_abort_verified=None,
                limits=["Candidate only; no independent acceptance, PTX, board or performance claim.",
                        "Changing configuration requires rebuilding kernel/runtime/simulators.",
                        "4 physical lanes is not 32-lane warp compatibility."],
                evidence_level="prepared only; execution observations are in separate immutable run results")
    write(destination / "target_caps.json", caps)
    print(json.dumps({"candidate": str(destination), "lock_sha256": sha256(destination / "target_lock.json")}))


if __name__ == "__main__":
    main()
