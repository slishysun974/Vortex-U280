"""Frame a sealed V03 board package and verify the returned raw board evidence."""

import argparse
import ast
import base64
import json
from pathlib import Path
import re
import sys
import tarfile
import uuid

from ae_v03_execute import (SCHEMA as AE_SCHEMA, board_review as ae_board_review,
                            preflight as ae_preflight, review_capture as ae_review_capture)
from c_runtime_board import decode_into
from c_v03_board import PY_FILES, preflight, review
from c_v03_high_board import CASES, SCOPE, board_review, high_preflight, review_capture
from check_c_v03_receipt import BINDINGS
from run_native_smoke import PROJECT, sha256
from run_ptx_copy import read_json, require, write_json
from runtime_backends import BACKENDS
from u280_board_smoke import BUSES
from u280_aligned_pair import preflight as aligned_preflight
from u280_perf_pair import (PILOT as PERF_PILOT, SCHEMA as PERF_SCHEMA, SUITE_SCHEMA as PERF_SUITE_SCHEMA,
                            board_review as perf_board_review, operations as perf_operations,
                            preflight as perf_preflight, review_capture as perf_review_capture)


BOOTSTRAP = '''import base64, hashlib, io, json, pathlib, subprocess, sys, tarfile
run_id, nonce, bdf, expected, data, entry = INPUT[:6]
result = dict(run_id=run_id, nonce=nonce, status="FAIL", exit_code=1, board_execution="NOT_RUN")
work = pathlib.Path.home() / "vortex-c-v03-board" / run_id
out = work / run_id
created = False
try:
    archive = base64.b64decode(data, validate=True)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError("archive hash mismatch")
    work.mkdir(parents=True)
    created = True
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if parts[0] != "bundle" or any(p in ("", ".", "..") for p in parts) or not (member.isfile() or member.isdir()):
                raise ValueError("unexpected archive member")
        tar.extractall(str(work))
    bundle = work / "bundle"
    aligned = entry == "u280_aligned_pair.py"
    argv = [sys.executable, "-B", str(bundle / "scripts" / entry), "run", "--bundle", str(bundle / "frozen" if aligned else bundle),
            "--output", str(out), "--bdf", bdf]
    if aligned:
        argv += ["--compiled", str(bundle / "compiled")]
        if INPUT[6:] == (True,):
            argv.append("--counters")
    result.update(argv=argv, archive_sha256=expected, python=list(sys.version_info[:3]))
    done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result.update(worker_exit_code=done.returncode, stdout=done.stdout.decode(errors="replace"),
                  stderr=done.stderr.decode(errors="replace"))
    if (out / "summary.json").is_file():
        summary = json.loads((out / "summary.json").read_text())
        result["board_execution"] = summary["board_execution"]
        for key in ("alias", "last_phase", "launch_attempts", "capture_error"):
            if key in summary:
                result[key] = summary[key]
        if done.returncode == 0 and summary["status"] == "PASS" and summary["board_execution"] == "PASS":
            result.update(status="PASS", exit_code=0)
except Exception as error:
    result["error"] = str(error)
export = {}
if created and out.is_dir():
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.name != "xrt_bdf":
            raw = path.read_bytes()
            export[path.relative_to(out).as_posix()] = dict(sha256=hashlib.sha256(raw).hexdigest(),
                                                          base64=base64.b64encode(raw).decode("ascii"))
result["export"] = export
print("C_V03_BEGIN_" + nonce)
print(json.dumps(result))
print("C_V03_END_" + nonce)
'''


def prepare(run, kit, bdf, models=None):
    source = read_json(kit / "summary.json")
    archive = kit / source["archive"]
    bundle = kit / "bundle"
    schema = read_json(bundle / "plan.json")["schema"]
    acceptance = schema == AE_SCHEMA
    perf = schema in (PERF_SCHEMA, PERF_SUITE_SCHEMA)
    if perf:
        plan = perf_preflight(bundle)
        frozen = dict(cases=plan["cases"])
    else:
        plan, frozen = ae_preflight(bundle) if acceptance else preflight(bundle)
    require(source["status"] == "PASS" and sha256(archive) == source["archive_sha256"] and
            sha256(bundle / "plan.json") == source["plan_sha256"], "prepared kit differs")
    high = plan.get("experiment") == SCOPE
    entry, cases = "c_v03_board.py", len(frozen["cases"])
    model_summary = None
    if perf:
        entry = "u280_perf_pair.py"
        cases = 2 * len(perf_operations(plan)) * len(plan["cases"]) * (plan["warm"] + plan["trials"])
        require(models is not None, "performance transport requires the timing pilot")
        model_summary = models / "summary.json"
        record = read_json(model_summary)
        require(record["status"] == "PASS" and record["exit_code"] == 0 and record["schema"] == schema and
                record["plan_sha256"] == source["plan_sha256"] and len(record["commands"]) == 1,
                "performance pilot did not pass")
        command = record["commands"][0]
        require(command["returncode"] == 0 and not command["timed_out"] and
                sha256(models / command["log"]) == command["log_sha256"], "pilot command or log differs")
        require(perf_review_capture(bundle, models, "simx", BINDINGS / "simx/binding.json", *PERF_PILOT) ==
                record["receipt"], "performance pilot receipt differs")
    elif high or acceptance:
        expected_schema = AE_SCHEMA if acceptance else SCOPE
        if acceptance:
            entry = "ae_v03_execute.py"
        else:
            high_preflight(bundle)
            entry, cases = "c_v03_high_board.py", len(CASES)
        require(models is not None, "board transport requires the new three-model receipts")
        model_summary = models / "summary.json"
        record = read_json(model_summary)
        require(record["status"] == "PASS" and record["exit_code"] == 0 and record["schema"] == expected_schema and
                len(record["commands"]) == len(BACKENDS), "three-model run did not pass")
        if acceptance:
            require(record["plan_sha256"] == source["plan_sha256"], "A/E model run used a different plan")
        for command in record["commands"]:
            require(command["returncode"] == 0 and not command["timed_out"] and
                    sha256(models / command["log"]) == command["log_sha256"], "model command or log differs")
        verify = ae_review_capture if acceptance else review_capture
        for backend in BACKENDS:
            receipt = verify(bundle, models, backend, BINDINGS / backend / "binding.json")
            require(record["models"][backend] == receipt, "model receipt differs: " + backend)
    nonce = uuid.uuid4().hex
    data = base64.b64encode(archive.read_bytes()).decode("ascii")
    args = (run.name, nonce, bdf, source["archive_sha256"], data, entry)
    raw = ("INPUT = " + repr(args) + "\n" + BOOTSTRAP).encode("ascii")
    compile(raw, "payload.py", "exec")
    run.mkdir()
    (run / "payload.py").write_bytes(raw)
    write_json(run / "preparation.json", dict(status="PASS", exit_code=0, scope="offline SSH framing",
        argv=[sys.executable, "-B", *sys.argv], run_id=run.name, nonce=nonce, kit=kit.name, bdf=bdf,
        archive_sha256=source["archive_sha256"], plan_sha256=source["plan_sha256"],
        payload_sha256=sha256(run / "payload.py"), expected_cases=cases, entry=entry,
        model_summary_sha256=sha256(model_summary) if model_summary else None, board_execution="NOT_RUN"))


def prepare_aligned(run, kit, compiled, bdf, *, counters=False):
    bundle = kit / "bundle"
    plan, manifests, _ = aligned_preflight(bundle, compiled)
    source, build = (read_json(path / "summary.json") for path in (kit, compiled))
    require(source["status"] == build["status"] == "PASS" and build["exit_code"] == 0 and
            build["plan_sha256"] == sha256(bundle / "plan.json"), "aligned build/preflight receipt differs")
    entry = "u280_aligned_pair.py"
    names = (*PY_FILES, entry, "ptx_u280_aligned.py", "ptx_frontend_v13.py", "ptx_frontend_v14.py")
    if counters:
        names += ("u280_aligned_counters.py",)
    members = {"scripts/" + name: PROJECT / "scripts" / name for name in names}
    members["native/u280_cp_caps_observer.cpp"] = PROJECT / "native/u280_cp_caps_observer.cpp"
    vendor = PROJECT / "third_party/dataclasses-0.8"
    for name, expected in read_json(vendor / "provenance.json")["files"].items():
        path = vendor / name
        require(path.parent == vendor and sha256(path) == expected, "Python 3.6 backport differs")
        members["third_party/dataclasses-0.8/" + name] = path
    for rel in (*plan["files"], "plan.json"):
        members["frozen/" + rel] = bundle / rel
    for (op, route), manifest in manifests.items():
        prefix = "modules/{}/{}".format(op, route)
        for name in (*manifest["files"], "manifest.json"):
            rel = prefix + "/" + name
            members["compiled/" + rel] = compiled / rel
    members["compiled/probe/kernel.vxbin"] = compiled / "probe/kernel.vxbin"
    for name in names:
        ast.parse(members["scripts/" + name].read_text(encoding="utf-8"), feature_version=(3, 6))
    ast.parse(BOOTSTRAP, feature_version=(3, 6))
    run.mkdir()
    archive = run / "board-input.tar.gz"
    hashes = {}
    with tarfile.open(archive, "x:gz") as tar:
        for rel, path in sorted(members.items()):
            require(path.is_file() and not path.is_symlink(), "nonregular board input: " + rel)
            hashes[rel] = sha256(path)
            tar.add(path, "bundle/" + rel, recursive=False)
    nonce, archive_hash = uuid.uuid4().hex, sha256(archive)
    args = (run.name, nonce, bdf, archive_hash, base64.b64encode(archive.read_bytes()).decode("ascii"), entry)
    if counters:
        args += (True,)
    payload = run / "payload.py"
    payload.write_bytes(("INPUT = " + repr(args) + "\n" + BOOTSTRAP).encode("ascii"))
    write_json(run / "preparation.json", dict(status="PASS", exit_code=0, scope="offline SSH framing",
        run_id=run.name, nonce=nonce, kit=kit.name, compiled=compiled.name, bdf=bdf, archive_sha256=archive_hash,
        plan_sha256=build["plan_sha256"], payload_sha256=sha256(payload), entry=entry, input_files=hashes,
        expected_cases=2 * len(plan["operators"]) * len(plan["cases"]) * (plan["warm"] + plan["trials"]),
        board_execution="NOT_RUN", counters=counters))


def unpack(run):
    prep = read_json(run / "preparation.json")
    stdout = (run / "probe.stdout").read_text(encoding="utf-8-sig")
    nonce = prep["nonce"]
    match = re.search(r"(?ms)^C_V03_BEGIN_" + nonce + r"\r?\n(.*?)^C_V03_END_" + nonce + r"\s*$", stdout)
    require(match is not None, "no matching remote V03 result frame")
    result = json.loads(match[1])
    require(result["run_id"] == run.name and result["nonce"] == nonce, "remote run identity differs")
    returned = run / "returned" / run.name
    returned.mkdir(parents=True)
    decode_into(result.pop("export"), returned)
    if prep.get("entry") == "board_worker.py" and run.name.startswith("iris-board-"):
        if result["status"] == "PASS":
            if prep.get("version") == "iris-board-perf-v1":
                sys.path.insert(0, str(PROJECT / "experiments/iris-u280-perf"))
                from analyze import verify_returned
            else:
                sys.path.insert(0, str(PROJECT / "experiments/iris-u280"))
                from board import verify_returned
            try:
                result["receipt"] = verify_returned(prep, result, returned)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
                result.update(status="FAIL", board_execution="FAIL", exit_code=1, review_error=str(error))
    elif prep.get("entry") == "u280_aligned_pair.py":
        from review_u280_aligned_pair import review_returned
        try:
            result.update(review_returned(prep, result, returned, PROJECT / "results"))
        except (OSError, ValueError, TypeError, KeyError, StopIteration) as error:
            result.update(status="FAIL", exit_code=1, review_error=str(error))
    elif result["status"] == "PASS":
        bundle = PROJECT / "results" / prep["kit"] / "bundle"
        summary = read_json(returned / "summary.json")
        require(result["archive_sha256"] == prep["archive_sha256"] and summary["plan_sha256"] == prep["plan_sha256"] ==
                sha256(bundle / "plan.json") and summary["bdf"] == prep["bdf"], "board artifact or BDF differs")
        require(summary["status"] == summary["board_execution"] == "PASS" and
                summary["exit_code"] == result["worker_exit_code"] == 0, "board worker did not pass")
        if prep.get("entry") == "u280_perf_pair.py":
            receipt = perf_board_review(bundle, returned)
        elif prep.get("entry") == "ae_v03_execute.py":
            receipt = ae_board_review(bundle, returned)
        elif prep.get("entry") == "c_v03_high_board.py":
            receipt = board_review(bundle, returned)
        else:
            _, frozen = preflight(bundle)
            receipt = review(bundle, returned, frozen)
        require(receipt == summary["receipt"] and receipt["launches"] == prep["expected_cases"],
                "returned captures differ from board report")
        result["receipt"] = receipt
    result["returned_files"] = {p.relative_to(returned).as_posix(): sha256(p)
                                for p in returned.rglob("*") if p.is_file()}
    write_json(run / "result.json", result)
    print(result["status"], result.get("error", ""))
    return result["exit_code"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "prepare-aligned", "unpack"))
    parser.add_argument("run_id")
    parser.add_argument("--kit", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--compiled", type=Path)
    parser.add_argument("--counters", action="store_true")
    parser.add_argument("--bdf", choices=["0000:" + b + ":00.1" for b in BUSES], default="0000:b1:00.1")
    options = parser.parse_args()
    if not re.fullmatch(r"(?:c-v03-u280-|u280-aligned-|iris-board-)[A-Za-z0-9_-]{1,50}", options.run_id):
        parser.error("choose a fresh board run ID")
    if options.run_id.startswith("iris-board-") and options.action != "unpack":
        parser.error("prepare Iris board runs with experiments/iris-u280/board.py")
    run = PROJECT / "results" / options.run_id
    if options.action in ("prepare", "prepare-aligned"):
        if options.kit is None or options.kit.resolve().parent != PROJECT / "results":
            parser.error("--kit must name a prepared kit under results")
        if options.action == "prepare-aligned":
            if options.compiled is None or options.compiled.resolve().parent != PROJECT / "results":
                parser.error("--compiled must name an aligned build under results")
            prepare_aligned(run, options.kit.resolve(), options.compiled.resolve(), options.bdf, counters=options.counters)
        else:
            prepare(run, options.kit.resolve(), options.bdf, options.models.resolve() if options.models else None)
    else:
        sys.exit(unpack(run))
