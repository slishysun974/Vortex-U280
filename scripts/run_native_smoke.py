#!/usr/bin/env python3
"""Offline, isolated Linux smoke of the pinned upstream Vortex demo."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from native_dependencies import validate_bundle


PROJECT = Path(__file__).resolve().parents[1]
COMMIT = "7fe19369587c087f902c3e2bc2add612aa910a95"
TOOLCHAIN_REV = "v3.0.1"
TOOLCHAIN_COMMIT = "8c64cf921d3c6c456e80f00d24482d0aa2153a82"
DEFINES = {
    "VX_CFG_NUM_CLUSTERS": 1, "VX_CFG_NUM_CORES": 1,
    "VX_CFG_NUM_WARPS": 4, "VX_CFG_NUM_THREADS": 4,
}
TARGET_ID = "vortex-v3-rv64-1c4w4t-smoke-draft"
PROFILES = {
    "smoke": ("configs", TARGET_ID, DEFINES),
    "block32-v1": ("configs/candidates/block32-v1", "vortex-v3-rv64-1c8w4t-block32-draft-v1",
                   dict(DEFINES, VX_CFG_NUM_WARPS=8)),
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_build_path(path):
    # Upstream make/configure interpolate paths into shell and sed expressions.
    return not re.search(r"[\s$#:'\"`&|;<>\\]", str(path))


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def demo_passed(returncode, timed_out, output):
    return returncode == 0 and not timed_out and bool(
        re.search(r"(?m)^PASSED!\s*$", output)
    )


class Recorder:
    def __init__(self, directory, summary, env, scratch_logs=None):
        self.directory = directory
        self.summary = summary
        self.env = env
        self.scratch_logs = Path(scratch_logs) if scratch_logs else None
        (directory / "logs").mkdir()

    def save(self):
        destination = self.directory / "summary.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(destination)

    def command(self, label, argv, cwd, timeout=30):
        record = {
            "label": label, "argv": [str(arg) for arg in argv], "cwd": str(cwd),
            "started_at": utc_now(), "timeout_seconds": timeout,
            "returncode": None, "timed_out": False,
            "log": "logs/{:02d}_{}.log".format(len(self.summary["commands"]) + 1, label),
        }
        self.summary["commands"].append(record)
        self.save()
        before = time.monotonic()
        log_path = self.directory / record["log"]
        capture_path = self.scratch_logs / log_path.name if self.scratch_logs else log_path
        if self.scratch_logs:
            record["scratch_log"] = str(capture_path)
            self.save()
        with capture_path.open("wb") as log:
            process = None
            try:
                process = subprocess.Popen(record["argv"], cwd=cwd, env=self.env,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=(os.name == "posix"))
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    self.kill_group(process)
                except KeyboardInterrupt:
                    self.kill_group(process)
                    record["interrupted"] = True
                    raise
                finally:
                    record["returncode"] = process.returncode
            except OSError as error:
                record["launch_error"] = str(error)
                record["returncode"] = 127
                log.write((str(error) + "\n").encode("utf-8"))
            finally:
                record["finished_at"] = utc_now()
                record["elapsed_seconds"] = round(time.monotonic() - before, 3)
                if self.scratch_logs:
                    log.flush()
                    shutil.copyfile(capture_path, log_path)
        record["log_sha256"] = sha256(log_path)
        self.save()
        return record, log_path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def kill_group(process):
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()


def requirement(summary, name, valid, detail):
    summary["preflight"].append({"name": name, "ok": bool(valid), "detail": detail})
    if not valid:
        summary["blockers"].append("{}: {}".format(name, detail))
    return bool(valid)


def load_configuration(recorder):
    summary = recorder.summary
    config_dir, target_id, defines = PROFILES[summary.get("target_profile", "smoke")]
    snapshots = recorder.directory / "configs"
    snapshots.mkdir()
    documents = {}
    for name in ("native_smoke.json", "target_lock.json", "target_caps.json"):
        path = PROJECT / config_dir / name
        if not requirement(summary, "config_" + name, path.is_file(), str(path)):
            continue
        shutil.copy2(path, snapshots / name)
        summary["config_file_sha256"][name] = sha256(path)
        try:
            documents[name] = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as error:
            requirement(summary, "config_json", False, str(error))
    config = documents.get("native_smoke.json", {})
    lock = documents.get("target_lock.json", {})
    caps = documents.get("target_caps.json", {})
    requirement(summary, "fixed_target", config.get("target_id") == target_id and config.get("xlen") == 64
                and config.get("defines") == defines and config.get("simx_mode") == "timing",
                "expected " + target_id + ", RV64, fixed profile defines, timing simx")
    requirement(summary, "locked_source", lock.get("vortex", {}).get("commit") == COMMIT,
                "lock must refer to " + COMMIT)
    requirement(summary, "config_lock_hash", lock.get("hardware_config_sha256") ==
                summary["config_file_sha256"].get("native_smoke.json"), "native_smoke.json must match target_lock.json")
    requirement(summary, "caps_lock_hash", caps.get("target_lock_hash") ==
                summary["config_file_sha256"].get("target_lock.json"), "target_caps.json must match target_lock.json")
    for name, document in documents.items():
        requirement(summary, "target_" + name, document.get("target_id") == target_id and document.get("xlen") == 64,
                    "all config artifacts must describe the same RV64 smoke candidate")
    source_config = Path(summary["source"]["path"]) / "VX_config.toml"
    requirement(summary, "source_config_hash", source_config.is_file() and sha256(source_config) == config.get("source_config_sha256"),
                "source VX_config.toml must match captured candidate")
    summary["source"]["captured_manifest_sha256"] = lock.get("source_manifest_sha256")
    manifest = (PROJECT / lock.get("evidence", "") / "source_manifest.json").resolve()
    valid_manifest = within(manifest, PROJECT) and manifest.is_file()
    if requirement(summary, "source_manifest", valid_manifest, str(manifest)):
        shutil.copy2(manifest, recorder.directory / "source_manifest.json")
        requirement(summary, "source_manifest_hash", sha256(manifest) == lock.get("source_manifest_sha256"),
                    "source manifest must match target lock")
        source = Path(summary["source"]["path"])
        mismatches = []
        for entry in json.loads(manifest.read_text(encoding="utf-8")):
            path = (source / entry["path"]).resolve()
            if not within(path, source) or not path.is_file() or sha256(path) != entry["sha256"]:
                mismatches.append(entry["path"])
        summary["source"]["manifest_mismatches"] = mismatches
        requirement(summary, "captured_source_files", not mismatches,
                    "all captured source file hashes must match; mismatch count=" + str(len(mismatches)))
    return " ".join("-D{}={}".format(name, value) for name, value in sorted(config.get("defines", {}).items()))


def source_identity(recorder, source):
    summary = recorder.summary
    if not requirement(summary, "source_directory", source.is_dir(), str(source)):
        return
    for label, arguments in (
        ("source_commit", ["rev-parse", "HEAD"]),
        ("source_tree", ["rev-parse", "HEAD^{tree}"]),
        ("source_changes", ["diff", "--exit-code", "--ignore-submodules=untracked", "HEAD", "--"]),
        ("submodule_status", ["submodule", "status", "--recursive"]),
    ):
        # A Windows checkout inspected through WSL can need a full metadata refresh.
        record, output = recorder.command(label, ["git", "-C", source] + arguments, source, timeout=120)
        summary["source"][label] = output.strip()
        requirement(summary, label, record["returncode"] == 0 and not record["timed_out"],
                    "see " + record["log"])
    requirement(summary, "pinned_commit", summary["source"].get("source_commit") == COMMIT,
                "expected " + COMMIT)
    versions = source / "VERSION"
    if versions.is_file():
        summary["source"]["VERSION_sha256"] = sha256(versions)
        requirement(summary, "toolchain_revision", "TOOLCHAIN_REV=" + TOOLCHAIN_REV in versions.read_text(),
                    "required prebuilt revision " + TOOLCHAIN_REV)
    else:
        requirement(summary, "VERSION", False, "missing source VERSION")
    file_hashes = {}
    for relative in ("configure", "config.mk.in", "VX_config.toml", "VX_types.toml",
                     "ci/blackbox.sh", "tests/regression/common.mk", "tests/regression/demo/Makefile",
                     "tests/regression/demo/main.cpp", "tests/regression/demo/kernel.cpp"):
        path = source / relative
        if path.is_file():
            file_hashes[relative] = sha256(path)
        else:
            requirement(summary, "source_file", False, relative + " missing")
    summary["source"]["file_sha256"] = file_hashes


def preflight(recorder, args):
    summary = recorder.summary
    source_identity(recorder, args.source)
    native = requirement(summary, "platform", platform.system() == "Linux" and platform.machine() == "x86_64",
                         "{} {}; requires Linux x86_64".format(platform.system(), platform.machine()))
    for label, path in (("source_path", args.source), ("tooldir_path", args.tooldir),
                        ("run_path", recorder.directory), ("build_path", args.build_dir)):
        requirement(summary, label, safe_build_path(path), str(path))
    requirement(summary, "fresh_build_directory", not args.build_dir.exists(), str(args.build_dir))
    if not native:
        return
    record, output = recorder.command("glibc", ["getconf", "GNU_LIBC_VERSION"], args.source)
    match = re.search(r"glibc (\d+)\.(\d+)", output)
    requirement(summary, "glibc", record["returncode"] == 0 and match and
                tuple(map(int, match.groups())) >= (2, 35),
                output.strip() + "; pinned ubuntu/focal bundle requires glibc >= 2.35")
    summary["software_versions"]["glibc"] = output.strip()
    host_programs = ["bash", "git", "gcc", "g++", "cmake", "make", "python3", "ar", "find", "sed", "realpath"]
    if args.backend in ("rtlsim", "xrtsim"):
        # The pinned Verilator distribution's generated makefiles invoke ccache.
        host_programs.append("ccache")
    programs = {name: shutil.which(name, path=recorder.env["PATH"]) for name in host_programs}
    for name, binary in programs.items():
        if requirement(summary, "host_" + name, bool(binary), binary or "not found in PATH"):
            record, output = recorder.command("host_" + name.replace("+", "p"), [binary, "--version"], args.source)
            requirement(summary, "executable_" + name, record["returncode"] == 0, "see " + record["log"])
            summary["software_versions"][name] = output.strip()
    tools = {
        "clang": "llvm-vortex/bin/clang", "clangpp": "llvm-vortex/bin/clang++",
        "llvm_objcopy": "llvm-vortex/bin/llvm-objcopy", "llvm_objdump": "llvm-vortex/bin/llvm-objdump",
        "riscv_gcc": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc",
        "riscv_gcc_ar": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-gcc-ar",
        "riscv_objdump": "riscv64-gnu-toolchain/bin/riscv64-unknown-elf-objdump",
    }
    if args.backend in ("rtlsim", "xrtsim"):
        tools["verilator"] = "verilator/bin/verilator"
        tools["verilator_bin"] = "verilator/bin/verilator_bin"
    usable = {}
    for name, relative in tools.items():
        binary = args.tooldir / relative
        if requirement(summary, name, binary.is_file() and os.access(binary, os.X_OK), str(binary)):
            summary["toolchain_file_sha256"][relative] = sha256(binary)
            record, output = recorder.command(name + "_version", [binary, "--version"], args.source)
            usable[name] = requirement(summary, name + "_runnable", record["returncode"] == 0,
                                       "see " + record["log"])
            summary["software_versions"][name] = output.strip()
            if name in ("verilator", "verilator_bin"):
                requirement(summary, "pinned_" + name + "_version", bool(re.search(r"\bVerilator 5\.050\b", output)),
                            "processor RTL smoke requires pinned Verilator 5.050; see " + record["log"])
    for relative in ("libc64/lib/libc.a", "libc64/lib/libm.a", "libc64/include/stdio.h",
                     "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a"):
        path = args.tooldir / relative
        if requirement(summary, "toolchain_file", path.is_file() and path.stat().st_size > 0, str(path)):
            summary["toolchain_file_sha256"][relative] = sha256(path)
    requirement(summary, "riscv_sysroot", (args.tooldir / "riscv64-gnu-toolchain/riscv64-unknown-elf").is_dir(),
                "RV64 GNU sysroot is required")
    modules = ["softfloat", "ramulator"]
    statuses = summary["source"].get("submodule_status", "").splitlines()
    for module in modules:
        matching = [line for line in statuses if " third_party/" + module + " " in line or line.endswith(" third_party/" + module)]
        requirement(summary, "submodule_" + module, len(matching) == 1 and not matching[0].startswith(("-", "+", "U")),
                    matching[0] if matching else "missing initialized pinned submodule")
    deps_outside_source = not within(args.ramulator_deps, args.source)
    requirement(summary, "ramulator_deps_outside_source", deps_outside_source,
                str(args.ramulator_deps) + "; dependencies must stay outside the fixed source tree")
    if deps_outside_source:
        try:
            bundle = validate_bundle(args.ramulator_deps)
            summary["ramulator_dependencies"] = {
                "bundle_sha256": sha256(args.ramulator_deps / "bundle.json"),
                "dependencies": {name: {"commit": entry["commit"], "file_count": len(entry["files"])}
                                 for name, entry in bundle["dependencies"].items()},
            }
            requirement(summary, "ramulator_dependencies", True, "all pinned dependency file hashes match")
        except (OSError, ValueError, KeyError, TypeError) as error:
            requirement(summary, "ramulator_dependencies", False, str(error))
    probes = recorder.directory / "probes"
    probes.mkdir()
    (probes / "probe.c").write_text("int native_probe(void) { return 0; }\n", encoding="utf-8")
    (probes / "probe.cpp").write_text("#include <span>\nint main() { int a[1]={0}; return std::span<int>(a)[0]; }\n", encoding="utf-8")
    probe_commands = []
    if programs["g++"]:
        probe_commands.append(("host_cxx20_compile", [programs["g++"], "-std=c++20", "probe.cpp", "-o", "host_probe"]))
    if usable.get("riscv_gcc"):
        probe_commands.append(("riscv_gcc_compile", [args.tooldir / tools["riscv_gcc"], "-march=rv64imafd", "-mabi=lp64d", "-c", "probe.c", "-o", "gcc_probe.o"]))
    if usable.get("clang"):
        probe_commands.append(("vortex_clang_compile", [args.tooldir / tools["clang"], "--target=riscv64-unknown-elf",
                               "-march=rv64imafd", "-mabi=lp64d", "-Xclang", "-target-feature", "-Xclang", "+xvortex",
                               "-mllvm", "-disable-loop-idiom-all", "-c", "probe.c", "-o", "clang_probe.o"]))
    for label, command in probe_commands:
        record, output = recorder.command(label, command, probes)
        passed = requirement(summary, label, record["returncode"] == 0 and "not a recognized feature" not in output,
                             "see " + record["log"])
        if label == "host_cxx20_compile" and passed:
            record, _ = recorder.command("host_cxx20_run", [probes / "host_probe"], probes)
            requirement(summary, "host_cxx20_run", record["returncode"] == 0, "see " + record["log"])


def stage_third_party(source, build, ramulator_deps, manifest_path=None):
    bundle = validate_bundle(ramulator_deps)
    third_party = build / "third_party"
    third_party.mkdir()
    shutil.copy2(source / "third_party/Makefile", third_party)
    for name in ("softfloat", "ramulator"):
        def ignore(directory, names):
            ignored = {name for name in names if name == ".git" or name == "__pycache__" or
                       name.endswith((".o", ".a", ".so", ".d"))}
            if Path(directory) == source / "third_party/ramulator":
                ignored.update(("build", "ext"))
            return ignored
        shutil.copytree(source / "third_party" / name, third_party / name, ignore=ignore)
    for name, entry in bundle["dependencies"].items():
        destination = third_party / "ramulator/ext" / name
        for relative in entry["files"]:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ramulator_deps / name / relative, target)
            if sha256(target) != entry["files"][relative]:
                raise ValueError("staged dependency hash differs: " + name + "/" + relative)
    manifest = {str(path.relative_to(third_party)): sha256(path)
                for path in sorted(third_party.rglob("*")) if path.is_file()}
    destination = manifest_path or build.parent / "third_party_sources.json"
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return third_party


def run_build(recorder, args, configs):
    build = args.build_dir
    build.mkdir(parents=True, exist_ok=False)
    flags = ["CONFIGS=" + configs, "XLEN=64", "THREADS=" + str(args.jobs)]
    steps = [("configure", ["bash", args.source / "configure", "--xlen=64", "--tooldir=" + str(args.tooldir)], build)]
    for label, command, cwd in steps:
        record, _ = recorder.command(label, command, cwd, args.timeout)
        if record["returncode"] != 0 or record["timed_out"]:
            return False, label
    effective_configs = configs + (" -DSIMULATION -DSV_DPI" if args.backend in ("rtlsim", "xrtsim") else "")
    record, resolved = recorder.command("resolve_backend_configuration", ["python3", "-B", build / "ci/gen_config.py",
        "--config=" + str(args.source / "VX_config.toml"),
        "--cflags=" + effective_configs + " -DVX_CFG_XLEN=64", "--format=cflags"], build, args.timeout)
    if record["returncode"] != 0 or record["timed_out"]:
        return False, "resolve_backend_configuration"
    backend_config = recorder.directory / "resolved_backend.cflags"
    backend_config.write_text(resolved, encoding="utf-8")
    recorder.summary["effective_backend_configuration"] = {
        "raw_configs": effective_configs, "resolved_cflags": str(backend_config.name), "sha256": sha256(backend_config),
        "source": "pinned sim/{}/Makefile mandatory SIMULATION/SV_DPI flags".format(args.backend)
                  if args.backend in ("rtlsim", "xrtsim") else "common hardware defines; SimX timing backend",
        "simulation_controls": ["NOXRT", "XRTSIM", "TARGET=xrtsim"] if args.backend == "xrtsim" else [],
    }
    third_party = stage_third_party(args.source, build, args.ramulator_deps,
                                    recorder.directory / "third_party_sources.json")
    recorder.summary["third_party_sources_sha256"] = sha256(recorder.directory / "third_party_sources.json")
    flags.append("THIRD_PARTY_DIR=" + str(third_party))
    if args.backend == "xrtsim":
        flags.append("TARGET=xrtsim")
    make = ["make", "-j" + str(args.jobs)] + flags
    app = build / "tests/regression/demo"
    runtime_backend = "xrt" if args.backend == "xrtsim" else args.backend
    steps = [
        ("ramulator_configure_offline", ["cmake", "-S", third_party / "ramulator", "-B", third_party / "ramulator/build",
                                        "-DFETCHCONTENT_FULLY_DISCONNECTED=ON", "-DFETCHCONTENT_UPDATES_DISCONNECTED=ON"], build),
        ("third_party", make + ["-C", third_party, "softfloat", "ramulator"], build),
        ("kernel_libraries", make + ["-C", build / "sw/kernel"], build),
        ("runtime_stub", make + ["-C", build / "sw/runtime/stub"], build),
        ("demo_build", make + ["-C", app], build),
        ("runtime_build", make + ["-C", app, "runtime-" + runtime_backend], build),
        ("demo_run", make + ["-C", app, "run-" + runtime_backend, "OPTS=-n1"], build),
    ]
    for label, command, cwd in steps:
        record, output = recorder.command(label, command, cwd, args.timeout)
        if label == "demo_run":
            recorder.summary["demo_execution"] = "PASS" if demo_passed(record["returncode"], record["timed_out"], output) else "FAIL"
            recorder.summary["demo_exit_code"] = record["returncode"]
        if record["returncode"] != 0 or record["timed_out"]:
            return False, label
        if label == "demo_run":
            recorder.summary["demo_marker_found"] = demo_passed(record["returncode"], record["timed_out"], output)
            return recorder.summary["demo_marker_found"], label
    return False, "demo_not_executed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Only upstream demo smoke; xrtsim tests an AFU model, never a physical board or vendor hw_emu.")
    parser.add_argument("--tooldir", type=Path, required=True, help="existing v3.0.1 prebuilt toolchain root; never downloaded by this script")
    parser.add_argument("--backend", choices=("simx", "rtlsim", "xrtsim"), default="simx")
    parser.add_argument("--target-profile", choices=tuple(PROFILES), default="smoke",
                        help="versioned candidate; block32-v1 does not replace the active smoke lock")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--native-boundary", action="store_true",
                        help="after demo, execute A/B native u32 boundary tests; not PTX or E acceptance")
    parser.add_argument("--native-trace", action="store_true",
                        help="DEBUG=3 LSU predicate checks in a fresh SimX/processor RTL build")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("native_%Y%m%dT%H%M%S_%fZ"))
    parser.add_argument("--source", type=Path, default=PROJECT / "upstream/vortex")
    parser.add_argument("--ramulator-deps", type=Path, default=PROJECT / "dependencies/ramulator",
                        help="external dependency bundle created by native_dependencies.py; never downloads")
    parser.add_argument("--build-dir", type=Path, help="new isolated Linux build directory; logs stay under results/run-id")
    parser.add_argument("--results-dir", type=Path, default=PROJECT / "results")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds per build or demo command")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if args.native_trace and (args.native_boundary or args.backend == "xrtsim"):
        parser.error("native-trace is a separate SimX/processor RTL experiment")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("run-id must be a single safe filename (1-96 ASCII letters, digits, _, . or -)")
    if args.timeout <= 0 or args.jobs <= 0:
        parser.error("timeout and jobs must be positive")
    args.source, args.tooldir = args.source.resolve(), args.tooldir.resolve()
    args.ramulator_deps = args.ramulator_deps.resolve()
    directory = args.results_dir.resolve() / args.run_id
    args.build_dir = args.build_dir.resolve() if args.build_dir else directory / "build"
    if within(directory, args.source):
        parser.error("run directory must stay outside the fixed source tree")
    if within(args.build_dir, args.source) or within(args.build_dir, args.tooldir):
        parser.error("build directory must stay outside the fixed source and toolchain trees")
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("run directory already exists; use a new --run-id: " + str(directory))
    summary = {
        "schema_version": 7, "run_id": args.run_id, "status": "RUNNING", "started_at": utc_now(),
        "debug_level": 3 if args.native_trace else 0,
        "target_profile": args.target_profile, "target_id": PROFILES[args.target_profile][1],
        "backend": args.backend, "check_only": args.check_only, "upstream_smoke": "NOT_RUN",
        "p0_three_kernels": "NOT_RUN", "afu_verification": "NOT_RUN", "hardware_verification": "NOT_RUN",
        "demo_execution": "NOT_RUN", "processor_rtl_verification": "NOT_RUN",
        "afu_scope": "NOXRT/XRTSIM AFU RTL model only; no vendor runtime, hw_emu, shell or board acceptance",
        "scope": "upstream demo only; " + PROFILES[args.target_profile][1] + "; project P0 unverified",
        "script_sha256": sha256(__file__), "source": {"path": str(args.source), "expected_commit": COMMIT},
        "tooldir": str(args.tooldir), "expected_toolchain_revision": TOOLCHAIN_REV,
        "ramulator_deps": str(args.ramulator_deps),
        "build_path": str(args.build_dir),
        "expected_toolchain_commit": TOOLCHAIN_COMMIT,
        "toolchain_provenance": "provided directory; version outputs and file hashes recorded, release archive identity not attested",
        "commands": [], "preflight": [], "blockers": [], "software_versions": {"runner_python": sys.version},
        "toolchain_file_sha256": {}, "config_file_sha256": {},
    }
    env = {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR", "SYSTEMROOT", "WINDIR") if key in os.environ}
    env.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "CCACHE_DISABLE": "1", "VORTEX_PROFILING": "0",
                "PYTHONDONTWRITEBYTECODE": "1", "XLEN": "64"})
    recorder = Recorder(directory, summary, env)
    if args.native_trace:
        env["DEBUG"] = "3"
        implementation = directory / "implementation"
        implementation.mkdir()
        for name in ("run_native_smoke.py", "native_boundary.py", "native_predicate_trace.py", "native_dependencies.py"):
            shutil.copy2(PROJECT / "scripts" / name, implementation / name)
    code = 1
    try:
        configs = load_configuration(recorder)
        env["CONFIGS"] = configs
        summary["configs"] = configs
        preflight(recorder, args)
        if summary["blockers"]:
            summary["status"] = "BLOCKED"
            code = 2
        elif args.check_only:
            summary["status"] = "PASS"
            summary["scope"] = "preflight only; no Vortex demo or P0 kernel executed"
            summary["readiness"] = "READY"
            code = 0
        else:
            passed, last_step = run_build(recorder, args, configs)
            summary["last_step"] = last_step
            summary["status"] = "PASS" if passed else "FAIL"
            summary["upstream_smoke"] = summary["status"]
            if args.backend == "xrtsim":
                summary["afu_verification"] = summary["demo_execution"]
            if args.backend == "rtlsim":
                summary["processor_rtl_verification"] = summary["demo_execution"]
            if passed and args.native_boundary:
                from native_boundary import run_boundary
                summary["status"] = "RUNNING"
                passed, last_step = run_boundary(recorder, args, configs)
                summary["last_step"] = last_step
                summary["status"] = "PASS" if passed else "FAIL"
                summary["scope"] = "upstream demo plus A/B native u32 boundary regression; PTX and independent acceptance NOT_RUN"
            if passed and args.native_trace:
                from native_predicate_trace import run_trace
                summary["status"] = "RUNNING"
                passed, last_step = run_trace(recorder, args, configs)
                summary["last_step"] = last_step
                summary["status"] = "PASS" if passed else "FAIL"
                summary["scope"] = "native u32 LSU request trace; PTX, AFU, U280 and independent E acceptance NOT_RUN"
            code = 0 if passed else 1
            artifacts = recorder.directory / "artifacts"
            artifact_paths = ("config.mk", "sw/VX_config.h", "hw/VX_config.vh",
                             "sw/runtime/rtlsim_config.stamp", "sw/runtime/rtlsim_rt_config.stamp",
                             "sw/runtime/simx_config.stamp", "sw/runtime/simx_rt_config.stamp",
                             "sw/runtime/xrtsim_config.stamp", "sw/runtime/xrt_config.stamp",
                             "sw/runtime/libvortex.so", "sw/runtime/libsimx.so", "sw/runtime/librtlsim.so",
                             "sw/runtime/libvortex-simx.so", "sw/runtime/libvortex-rtlsim.so",
                             "sw/runtime/libxrtsim.so", "sw/runtime/libvortex-xrt.so",
                             "tests/regression/demo/demo", "tests/regression/demo/kernel.vxbin",
                             "tests/regression/demo/kernel.dump", "tests/regression/demo/kernel.elf")
            if args.native_boundary or args.native_trace:
                artifact_paths += tuple("tests/regression/boundary/" + name for name in
                                        ("boundary", "kernel.vxbin", "kernel.dump", "kernel.elf", "config.stamp"))
            for relative in artifact_paths:
                path = args.build_dir / relative
                if path.is_file():
                    copied = artifacts / relative
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, copied)
                    summary.setdefault("build_artifacts", {})[relative] = {
                        "path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size,
                        "review_copy": str(copied.relative_to(recorder.directory)),
                    }
    except KeyboardInterrupt:
        summary["status"] = "FAIL"
        summary["error"] = "interrupted; active process group killed"
        code = 130
    except Exception as error:
        summary["status"] = "FAIL"
        summary["error"] = "{}: {}".format(type(error).__name__, error)
    finally:
        summary["finished_at"] = utc_now()
        recorder.save()
    print(json.dumps({"status": summary["status"], "upstream_smoke": summary["upstream_smoke"],
                      "summary": str(directory / "summary.json"), "blockers": summary["blockers"]}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
