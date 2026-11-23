"""Frame answer-free Iris board inputs and verify returned captures locally."""
import argparse
import ast
import base64
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import uuid

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from c_v03_board import PY_FILES, check_commands, review_gate
from c_v03_board_transport import BOOTSTRAP
from check_c_v03_receipt import BINDINGS
from ptx_module import validate
from ptx_u280 import BUSES, QUERY_SOURCE
from run_native_smoke import sha256
from run_ptx_copy import BOARD_LOCK, SIM_LOCK, read_json, require, write_json
from runtime_backends import BACKENDS
from review import CORPUS_SHA, check_corpus, review


def prepare(run, frozen, build, models, bdf):
    corpus = check_corpus(frozen)
    built, simulated = (read_json(p/"summary.json") for p in (build,models))
    for p, report in ((build,built), (models,simulated)):
        check_commands(p, report)
    require(simulated["corpus_sha256"] == CORPUS_SHA and simulated["build_summary_sha256"] == sha256(build/"summary.json"),
            "model run used a different corpus/build")
    for target, lock in (("sim", SIM_LOCK), ("board", BOARD_LOCK)):
        path = build / "modules" / target
        meta, _ = validate(path, lock.read_bytes())
        require(built["modules"][target]["manifest_sha256"] == sha256(path/"manifest.json") and
                meta["source_sha256"] == built["ptx_sha256"], "changed module " + target)
    for backend in BACKENDS:
        receipt = review(frozen, corpus, models/backend, backend, BINDINGS/backend/"binding.json",
                         built["modules"]["sim"]["manifest_sha256"], negative=True)
        require(receipt == simulated["models"][backend], "model replay differs for "+backend)

    # Include only the three initial allocations per case. Row labels, answers and classifier stay local.
    specs = [{k:v for k,v in s.items() if k != "rows"} for s in corpus["cases"]]
    data = {"inputs/manifest.json": json.dumps(dict(cases=specs)).encode(),
            "query.cpp": QUERY_SOURCE.encode(), "target_lock.json": BOARD_LOCK.read_bytes(),
            "hardware.json": BOARD_LOCK.with_name("fpga.json").read_bytes()}
    for spec in specs:
        for role in ("x","sums","out"):
            rel = spec["id"]+"/"+role+".input.bin"
            data["inputs/"+rel] = (frozen/rel).read_bytes()
    board = build/"modules/board"
    for name in ["manifest.json", *read_json(board/"manifest.json")["files"]]:
        data["module/"+name] = (board/name).read_bytes()
    for name in PY_FILES:
        data["scripts/"+name] = (PROJECT/"scripts"/name).read_bytes()
    for name in ("capture.py","board_worker.py"):
        data["scripts/"+name] = (HERE/name).read_bytes()
    vendor = PROJECT / "third_party/dataclasses-0.8"
    for name, digest in read_json(vendor/"provenance.json")["files"].items():
        require(sha256(vendor/name) == digest, "Python backport differs")
        data["vendor/dataclasses-0.8/"+name] = (vendor/name).read_bytes()
    from hashlib import sha256 as digest
    files = {k:digest(v).hexdigest() for k,v in data.items()}
    plan = dict(version="iris-board-v1", corpus_sha256=CORPUS_SHA, cases=[s["id"] for s in specs], files=files)
    data["plan.json"] = json.dumps(plan, sort_keys=True).encode()
    run.mkdir()
    archive = run / "board-input.tar.gz"
    with tarfile.open(archive,"x:gz") as tar:
        for name, content in sorted(data.items()):
            if name.endswith(".py"):
                ast.parse(content.decode(), filename=name, feature_version=(3,6))
            info = tarfile.TarInfo("bundle/"+name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    nonce = uuid.uuid4().hex
    args = (run.name, nonce, bdf, sha256(archive), base64.b64encode(archive.read_bytes()).decode(), "board_worker.py")
    payload = run/"payload.py"
    payload.write_bytes(("INPUT = "+repr(args)+"\n"+BOOTSTRAP).encode("ascii"))
    ast.parse(payload.read_bytes(), feature_version=(3,6))
    write_json(run/"preparation.json", dict(status="PASS", exit_code=0, scope="offline SSH framing",
        run_id=run.name, nonce=nonce, bdf=bdf, archive_sha256=sha256(archive), payload_sha256=sha256(payload),
        entry="board_worker.py", expected_cases=9, board_execution="NOT_RUN", corpus_sha256=CORPUS_SHA,
        frozen=frozen.relative_to(PROJECT).as_posix(), compiled=build.relative_to(PROJECT).as_posix(),
        models=models.relative_to(PROJECT).as_posix(), plan_sha256=digest(data["plan.json"]).hexdigest(),
        module_sha256=built["modules"]["board"]["manifest_sha256"], model_summary_sha256=sha256(models/"summary.json"),
        argv=[sys.executable,"-B",*sys.argv], files=files))
    print("PASS", run, "9 cases, 27 input allocations")


def verify_returned(prep, result, returned):
    summary = read_json(returned/"summary.json")
    require(result["worker_exit_code"] == summary["exit_code"] == 0 and
            summary["status"] == summary["board_execution"] == "PASS" and
            prep["archive_sha256"] == result["archive_sha256"] and prep["plan_sha256"] == summary["plan_sha256"] and
            summary["run_id"] == prep["run_id"] and summary["bdf"] == prep["bdf"], "inconsistent board receipt")
    check_commands(returned,summary)
    require(review_gate(returned) == summary["gate_sha256"], "returned board gate differs")
    frozen = PROJECT / prep["frozen"]
    binding = returned/"binding/binding.json"
    actual = read_json(binding)
    require(actual["bdf"] == prep["bdf"] and actual["index"] == summary["xrt_index"], "physical card differs")
    board = PROJECT/prep["compiled"]/"modules/board"
    validate(board, BOARD_LOCK.read_bytes())
    require(sha256(board/"manifest.json") == prep["module_sha256"], "board module identity differs")
    return review(frozen, check_corpus(frozen), returned/"u280-xrt", "u280-xrt", binding, prep["module_sha256"], negative=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("run_id")
    for arg in ("frozen","compiled","models"):
        cli.add_argument("--"+arg, required=True, type=Path)
    cli.add_argument("--bdf", choices=["0000:"+b+":00.1" for b in BUSES], default="0000:b1:00.1")
    a = cli.parse_args()
    require(re.fullmatch(r"iris-board-[A-Za-z0-9_-]{1,50}",a.run_id), "use a fresh iris-board ID")
    prepare(PROJECT/"results"/a.run_id, a.frozen.resolve(), a.compiled.resolve(), a.models.resolve(), a.bdf)
