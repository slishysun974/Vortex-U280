"""Replay the sealed answers and all four Iris captures without opening a device."""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import sys

from board import BINDINGS, HERE, PROJECT, check_commands, verify_returned
from review import CORPUS_SHA, check_corpus
from run_native_smoke import Recorder, sha256, utc_now
from run_ptx_copy import read_json, require, run_stage, write_json
from runtime_backends import BACKENDS


def replay(a, out, rec):
    frozen = a.freeze / "corpus"
    manifest = check_corpus(frozen)
    py = [sys.executable,"-B"]
    for name in ("freeze", "compiled", "models", "selftest"):
        stage = getattr(a,name)
        check_commands(stage,read_json(stage/"summary.json"))
    classifier = read_json(frozen/"classifier.json")
    require(sha256(HERE/"freeze.py") == read_json(a.freeze/"summary.json")["oracle_sha256"], "oracle changed")
    run_stage(rec, "recompute_oracle", py+[HERE/"freeze.py",out/"recomputed"], out)
    check_corpus(out/"recomputed")

    physical = a.board/"returned"/a.board.name
    result = read_json(a.board/"result.json")
    prep = read_json(a.board/"preparation.json")
    tr = json.loads((a.board/"transport.json").read_text(encoding="utf-8-sig"))
    require(result["status"] == tr["status"] == "PASS" and tr["exit_code"] == tr["ssh_exit_code"] == result["exit_code"] == 0
            and result["worker_exit_code"] == 0 and prep["corpus_sha256"] == CORPUS_SHA
            and prep["model_summary_sha256"] == sha256(a.models/"summary.json"), "board/transport receipt differs")
    files = {p.relative_to(physical).as_posix():sha256(p) for p in physical.rglob("*") if p.is_file()}
    require(files == result["returned_files"], "returned artifact set or hash differs")
    require(verify_returned(prep,result,physical) == result["receipt"], "board replay differs")
    rec.summary.update(corpus_sha256=CORPUS_SHA, returned_files=len(files), raw_captures={}, backends={},
                       receipts={str(p.relative_to(PROJECT)):sha256(p) for p in (
                           a.freeze/"summary.json", a.compiled/"summary.json", a.models/"summary.json",
                           a.selftest/"summary.json", a.board/"result.json", a.board/"transport.json")})
    board_rows = []
    for backend in (*BACKENDS, "u280-xrt"):
        board = backend == "u280-xrt"
        raw = (physical if board else a.models)/backend
        binding = physical/"binding/binding.json" if board else BINDINGS/backend/"binding.json"
        module = a.compiled/"modules"/("board" if board else "sim")
        built = read_json(a.compiled/"summary.json")["modules"]["board" if board else "sim"]
        require(built["manifest_sha256"] == sha256(module/"manifest.json"), "module differs from build")
        source = run_stage(rec, "review_"+backend, py+[HERE/"review.py","--frozen",frozen,"--capture",raw,
                           "--binding",binding,"--backend",backend,"--module",module], out)
        review = json.loads(source)
        earlier = result["receipt"] if board else read_json(a.models/"summary.json")["models"][backend]
        require(review == earlier, "replayed receipt differs: "+backend)
        matrix = [[0]*3 for _ in range(3)]
        data = (raw/"test45/out.after.bin").read_bytes()
        for i, ref in enumerate(classifier["predictions"]):
            offset = 16+i*16
            words = list(struct.unpack_from("<4I",data,offset))
            matrix[ref["true"]][words[3]] += 1
            if board:
                board_rows.append(dict(source_line=ref["line"], features_mm=ref["x_mm"], true_class=ref["true"],
                    output_byte_offset=offset, words=words, expected=ref["distances"]+[ref["predicted"]]))
        require(matrix == classifier["confusion_true_by_predicted"], "device confusion matrix differs")
        rec.summary["backends"][backend] = dict(launches=review["launches"], confusion=matrix,
            correct=sum(matrix[c][c] for c in range(3)), samples=len(classifier["predictions"]),
            distances=135, classes=45, full_buffer_snapshots=review["full_buffer_snapshots"],
            rejected_fields=[d["field"] for d in review["negative_controls"]], binding_sha256=sha256(binding))
        rec.summary["raw_captures"][backend] = {p.relative_to(raw).as_posix():sha256(p)
                                               for p in sorted(raw.rglob("*")) if p.is_file()}
    for spec in manifest["cases"]:
        cid = spec["id"]
        board_output = (physical/"u280-xrt"/cid/"out.after.bin").read_bytes()
        require(all((a.models/backend/cid/"out.after.bin").read_bytes() == board_output for backend in BACKENDS),
                "cross-backend output differs: "+cid)
    write_json(out/"board-predictions.json", board_rows)
    rec.summary["board_predictions_sha256"] = sha256(out/"board-predictions.json")
    print("Replayed the oracle, 36 launches, and all returned files. Board accuracy 40/45.")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("tag")
    for name in ("freeze","compiled","models","board","selftest"):
        cli.add_argument("--"+name, type=lambda v: Path(v).resolve(), required=True)
    args = cli.parse_args()
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,48}",args.tag), "invalid run tag")
    out = PROJECT/"results"/("iris-review-"+args.tag)
    out.mkdir()
    report = dict(status="RUNNING", argv=[sys.executable,"-B",*sys.argv], started_at=utc_now(), commands=[])
    rec = Recorder(out,report,dict(os.environ))
    try:
        replay(args,out,rec)
        report.update(status="PASS",exit_code=0)
    except Exception as error:
        report.update(status="FAIL",exit_code=1,error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"],out,report.get("error",""))
    sys.exit(report["exit_code"])
