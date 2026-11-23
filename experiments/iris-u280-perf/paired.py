"""Prepare and independently verify the same-card Iris native/PTX experiment."""
import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import statistics
import struct
import sys
import tarfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze import FROZEN, ROLES, check, distribution, lines, read, sha
from c_v03_board import check_commands, review_gate
from ptx_module import validate
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, write_json
from u280_aligned_counters import COUNTERS, COUNTER_LIMIT, launch_delta

VERSION = "iris-native-ptx-pair-v1"
ROUTES = ("native", "ptx")
WARMUP, TIMED = 5, 30


def input_plan(corpus, physical):
    check(sha(corpus / "freeze.json") == FROZEN, "Iris corpus identity differs")
    frozen = read(corpus / "freeze.json")
    for name, digest in frozen["files"].items():
        check(sha(corpus / name) == digest, "frozen member differs: " + name)
    sizes = frozen["sizes"] if physical else (45, 1024)
    keys = ["n%d" % n for n in sizes]
    specs = {s["id"]: s for s in read(corpus / "inputs/manifest.json")["cases"]}
    schedule = [dict(case=keys[0], scope="probe", pair=i, position=0, route="ptx", save=False)
                for i in range(2)] if physical else []
    pairs = WARMUP + TIMED if physical else 1
    for pair in range(pairs):
        offset = pair % len(keys)
        order = ROUTES if pair % 2 == 0 else ROUTES[::-1]
        for key in keys[offset:] + keys[:offset]:
            for position, route in enumerate(order):
                schedule.append(dict(case=key, pair=pair, position=position, route=route,
                                     scope="warmup" if physical and pair < WARMUP else "timed",
                                     save=pair == pairs - 1))
    return dict(version=VERSION, cases=[specs[k] for k in keys], schedule=schedule,
                expected={k: frozen["expected"][k] for k in keys})


def inputs_and_modules(a, lock, native, physical):
    corpus = a.corpus.resolve()
    plan = input_plan(corpus, physical)
    ptx, _ = validate(a.module, lock.read_bytes())
    proof = read(native / "native.json")
    check(proof["lock_sha256"] == sha(lock) and proof["ptx_image_sha256"] == ptx["image_sha256"]
          and proof["ptx_manifest_sha256"] == sha(a.module / "manifest.json")
          and proof["native_image_sha256"] == sha(native / "kernel.vxbin"), "build identities differ")
    files = {"inputs/manifest.json": json.dumps(plan, sort_keys=True).encode()}
    for case in plan["cases"]:
        for role in ROLES:
            name = "inputs/{}/{}.input.bin".format(case["id"], role)
            files[name] = (corpus / name).read_bytes()
    for name in ["manifest.json", *ptx["files"]]:
        files["module/" + name] = (a.module / name).read_bytes()
    files["module/native.json"] = (native / "native.json").read_bytes()
    files["module/native.vxbin"] = (native / "kernel.vxbin").read_bytes()
    return plan, files, proof


def prepare(a):
    from c_v03_board import PY_FILES
    from c_v03_board_transport import BOOTSTRAP
    from prepare import IMAGE, QUERY_SOURCE

    native = a.native.resolve()
    plan, files, proof = inputs_and_modules(a, BOARD_LOCK, native, True)
    check(proof["ptx_image_sha256"] == IMAGE, "Iris PTX differs from the previously measured image")
    files.update({"query.cpp": QUERY_SOURCE.encode(), "target_lock.json": BOARD_LOCK.read_bytes(),
                  "hardware.json": BOARD_LOCK.with_name("fpga.json").read_bytes()})
    for name in (*PY_FILES, "u280_aligned_counters.py"):
        files["scripts/" + name] = (ROOT / "scripts" / name).read_bytes()
    files["scripts/board_worker.py"] = (HERE.parent / "iris-u280/board_worker.py").read_bytes()
    files["scripts/iris_inputs.py"] = (HERE.parent / "iris-u280/capture.py").read_bytes()
    files["scripts/capture.py"] = (HERE / "measure_pair.py").read_bytes()
    vendor = ROOT / "third_party/dataclasses-0.8"
    for name, digest in read(vendor / "provenance.json")["files"].items():
        check(sha(vendor / name) == digest, "Python backport differs")
        files["vendor/dataclasses-0.8/" + name] = (vendor / name).read_bytes()
    worker_plan = dict(version=VERSION, cases=[s["case"] for s in plan["schedule"]],
                       files={k: hashlib.sha256(v).hexdigest() for k, v in files.items()})
    files["plan.json"] = json.dumps(worker_plan, sort_keys=True).encode()
    run = ROOT / "results" / a.run_id
    run.mkdir()
    archive = run / "board-input.tar.gz"
    with tarfile.open(archive, "x:gz") as tar:
        for name, data in sorted(files.items()):
            if name.endswith(".py"):
                ast.parse(data.decode(), filename=name, feature_version=(3, 6))
            item = tarfile.TarInfo("bundle/" + name)
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
    nonce = uuid.uuid4().hex
    args = (run.name, nonce, "0000:b1:00.1", sha(archive), base64.b64encode(archive.read_bytes()).decode(), "board_worker.py")
    payload = run / "payload.py"
    payload.write_bytes(("INPUT = " + repr(args) + "\n" + BOOTSTRAP).encode("ascii"))
    write_json(run / "preparation.json", dict(status="PASS", exit_code=0, board_execution="NOT_RUN",
               argv=[sys.executable, "-B", *sys.argv], run_id=run.name, nonce=nonce, bdf=args[2], entry=args[-1],
               version=VERSION, archive_sha256=args[3], payload_sha256=sha(payload), plan_sha256=hashlib.sha256(files["plan.json"]).hexdigest(),
               input_manifest_sha256=worker_plan["files"]["inputs/manifest.json"], expected_cases=len(plan["schedule"]),
               corpus=a.corpus.resolve().relative_to(ROOT).as_posix(), native_proof=proof))
    print("PASS", run, len(plan["schedule"]), "planned launches")


def verify_samples(corpus, raw, plan, backend):
    physical = backend == "u280-xrt"
    samples = lines(raw / "samples.jsonl")
    schedule = plan["schedule"]
    specs = {s["id"]: s for s in plan["cases"]}
    check(len(samples) == len(schedule), "incomplete capture")
    reads = lines(raw / "counter-reads.jsonl") if physical else []
    check(len(reads) == (8 * len(samples) if physical else 0), "incomplete counter reads")
    for seq, (sample, identity) in enumerate(zip(samples, schedule)):
        key, route = identity["case"], identity["route"]
        n = specs[key]["n"]
        check(all(sample[k] == v for k, v in identity.items()) and sample["n"] == n
              and sample["event"] == dict(status="COMPLETE", backend=backend, event_id=seq+1, generation=0)
              and sample["full_inputs_match"] is True and sample["output_sha256"] == plan["expected"][key],
              "event, inputs or outputs differ at launch %d" % (seq + 1))
        bases = read(raw / key / "bases.json")
        payload = struct.pack("<QQQI4x", *(bases[role] + 16 for role in ROLES), n)
        check(all(b > 0 and b % 4 == 0 for b in bases.values())
              and hashlib.sha256(payload).hexdigest() == sample["payload_sha256"], "launch arguments differ")
        if identity["save"]:
            check((raw / key / (route + ".out.bin")).read_bytes() == (corpus / (key + ".expected.bin")).read_bytes()
                  and (raw / key / (route + ".params.bin")).read_bytes() == payload, "raw readback or arguments differ")
        if physical:
            snapshots = {}
            for j, (phase, counter) in enumerate((p, c) for p in ("idle", "before", "after", "settled") for c in COUNTERS):
                row = reads[seq * 8 + j]
                check(all(row[k] == v for k, v in identity.items()) and row["phase"] == phase and row["counter"] == counter
                      and row["address"] == COUNTERS[counter] and row["exit_code"] == 0
                      and 0 <= row["raw"] < COUNTER_LIMIT, "counter read differs")
                snapshots.setdefault(phase, {})[counter] = row["raw"]
            check(launch_delta(snapshots) == sample["counts"], "counter delta differs")
    result = dict(status="PASS", launches=len(samples), counter_reads=len(reads), backend=backend)
    if not physical:
        return result
    qualification = read(raw / "counter-status.json")
    check(qualification["status"] == "PASS" and qualification["paired_launches"] == len(samples) - 2
          and qualification["pilots"] == [dict(item, **s["counts"]) for item, s in zip(schedule[:2], samples[:2])]
          and samples[0]["counts"]["instret"] == samples[1]["counts"]["instret"], "invalid counter qualification")
    groups = {}
    for key in specs:
        timed = [s for s in samples if s["case"] == key and s["scope"] == "timed"]
        by_route = {r: [s["counts"] for s in timed if s["route"] == r] for r in ROUTES}
        check(all(len(v) == TIMED for v in by_route.values()), "timed sample count differs")
        stats = {}
        for counter in COUNTERS:
            native, ptx = ([s[counter] for s in by_route[r]] for r in ROUTES)
            stats[counter] = dict(native=distribution(native), ptx=distribution(ptx),
                                  ptx_minus_native=distribution([p - n for p, n in zip(ptx, native)]),
                                  ptx_over_native=statistics.median(ptx) / statistics.median(native))
        groups[str(specs[key]["n"])] = stats
    result.update(groups=groups, timed_pairs=len(specs) * TIMED, warmup_pairs=len(specs) * WARMUP)
    return result


def verify_returned(prep, result, returned):
    summary = read(returned / "summary.json")
    check_commands(returned, summary)
    check(review_gate(returned) == summary["gate_sha256"] and summary["run_id"] == prep["run_id"]
          and summary["bdf"] == prep["bdf"] and summary["exit_code"] == result["worker_exit_code"] == 0
          and summary["plan_sha256"] == prep["plan_sha256"] and result["archive_sha256"] == prep["archive_sha256"]
          and summary["board_execution"] == "PASS", "board, worker or plan identity differs")
    gate_dir = returned / "binding/sessions" / prep["run_id"]
    gate = read(gate_dir / "gate.json")
    end_path = gate_dir / "paired-end.json"
    check(sha(end_path) == gate["reports"]["paired-end"]["sha256"], "end-of-run clock report differs")
    end_device, = read(end_path)["devices"]
    clocks = [c for c in end_device["platforms"][0]["clocks"] if c["id"] == "DATA_CLK"]
    check(end_device["device_id"] == prep["bdf"] and clocks == [gate["clock_readback"]], "end-of-run BDF or clock differs")
    raw = returned / "u280-xrt"
    capture = read(raw / "capture.json")
    proof = prep["native_proof"]
    check(capture["binding_sha256"] == sha(returned / "binding/binding.json")
          and capture["lock_sha256"] == proof["lock_sha256"] == gate["artifact_hashes"]["lock"]
          and capture["input_manifest_sha256"] == prep["input_manifest_sha256"]
          and capture["ptx_manifest_sha256"] == proof["ptx_manifest_sha256"]
          and capture["images"] == {r: proof[r + "_image_sha256"] for r in ROUTES}
          and capture["final_state"] == "CLOSED" and capture["launch_attempts"] == prep["expected_cases"],
          "capture identity differs")
    corpus = ROOT / prep["corpus"]
    return dict(verify_samples(corpus, raw, input_plan(corpus, True), "u280-xrt"),
                bdf=prep["bdf"], clock_mhz=int(clocks[0]["freq_mhz"]), image_sha256=capture["images"])


def pilot(a):
    import os
    from check_c_v03_receipt import BINDINGS
    from run_native_smoke import Recorder, utc_now
    from run_ptx_copy import run_stage

    run = ROOT / "results" / a.run_id
    plan, files, proof = inputs_and_modules(a, SIM_LOCK, a.native, False)
    run.mkdir()
    for name, data in files.items():
        path = run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    binding = BINDINGS / "simx/binding.json"
    env = dict(os.environ, VORTEX_DRIVER="simx", LD_LIBRARY_PATH=read(binding)["library_dir"], VORTEX_PROFILING="0")
    report = dict(status="RUNNING", board_execution="NOT_RUN", commands=[], images=proof, started_at=utc_now())
    recorder = Recorder(run, report, env)
    try:
        out = run / "simx"
        run_stage(recorder, "paired_simx", [sys.executable, "-B", HERE / "measure_pair.py", "--inputs", run / "inputs",
                  "--module", run / "module", "--binding", binding, "--lock", SIM_LOCK, "--output", out,
                  "--backend", "simx"], run, 180)
        report.update(verify_samples(a.corpus, out, plan, "simx"), exit_code=0)
    except Exception as error:
        report.update(status="FAIL", exit_code=1, error=str(error))
    report["finished_at"] = utc_now()
    recorder.save()
    print(report["status"], run, report.get("error", ""))
    return report["exit_code"]


def review(run):
    prep = read(run / "preparation.json")
    result = read(run / "result.json")
    transport = read(run / "transport.json")
    returned = run / "returned" / run.name
    check(prep["run_id"] == result["run_id"] == transport["run_id"] == run.name and prep["version"] == VERSION
          and prep["status"] == result["status"] == transport["status"] == "PASS"
          and prep["exit_code"] == result["exit_code"] == transport["exit_code"] == transport["ssh_exit_code"] == 0
          and sha(run / "board-input.tar.gz") == prep["archive_sha256"]
          and sha(run / "payload.py") == prep["payload_sha256"], "preparation or transport identity differs")
    observed = {p.relative_to(returned).as_posix(): sha(p) for p in returned.rglob("*") if p.is_file()}
    check(observed == result["returned_files"], "returned files differ")
    receipt = verify_returned(prep, result, returned)
    check(receipt == result["receipt"], "recomputed receipt differs")
    print(json.dumps(dict(receipt, verified_files=len(observed)), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "pilot", "review"):
        cli = actions.add_parser(action)
        cli.add_argument("run_id")
        if action != "review":
            for arg in ("corpus", "module", "native"):
                cli.add_argument("--" + arg, type=lambda v: Path(v).resolve(), required=True)
    a = parser.parse_args()
    prefix = "iris-pair-simx-" if a.action == "pilot" else "iris-board-pair-"
    check(re.fullmatch(prefix + r"[A-Za-z0-9_-]{1,38}", a.run_id), "invalid run ID")
    if a.action == "review":
        review(ROOT / "results" / a.run_id)
    else:
        sys.exit(prepare(a) if a.action == "prepare" else pilot(a))
