"""Recompute Iris board statistics from the frozen inputs and raw measurement records."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import sys

ROLES = ("x","sums","out")
FROZEN = "bab8e82ea2b1f23c06359f28e2dd60ee4f8a31ee80b50c1d0a620f0adc3efe96"


def check(ok, message):
    if not ok:
        raise ValueError(message)


def read(p):
    return json.loads(p.read_bytes())


def lines(p):
    return [json.loads(line) for line in p.read_bytes().splitlines()]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def distribution(values):
    ordered = sorted(values)
    return dict(median=statistics.median(ordered),p95=ordered[math.ceil(.95*len(ordered))-1],
                minimum=ordered[0],maximum=ordered[-1])


def analyze(corpus,raw):
    check(sha(corpus/"freeze.json")==FROZEN,"wrong performance corpus")
    frozen = read(corpus/"freeze.json")
    for name,digest in frozen["files"].items():
        check(sha(corpus/name)==digest,"corpus member differs: "+name)
    plan = read(corpus/"inputs/manifest.json")
    specs = {s["id"]:s for s in plan["cases"]}
    samples = lines(raw/"samples.jsonl")
    reads = lines(raw/"counter-reads.jsonl")
    check(len(samples)==len(plan["schedule"])==217 and len(reads)==8*len(samples),"incomplete measurement")
    status = read(raw/"counter-status.json")
    check(status["status"]=="PASS" and status["paired_launches"]==215 and len(status["pilots"])==2,"MPM qualification")
    for seq,(sample,identity) in enumerate(zip(samples,plan["schedule"])):
        key = identity["case"]
        n = specs[key]["n"]
        check(all(sample[k]==v for k,v in identity.items()) and sample["n"]==n,"schedule differs")
        check(sample["event"]==dict(status="COMPLETE",backend="u280-xrt",event_id=seq+1,generation=0)
              and sample["full_inputs_match"] is True and sample["output_sha256"]==frozen["expected"][key],
              "event, output or guards differ at launch %d"%(seq+1))
        bases = read(raw/key/"bases.json")
        ptr = struct.pack("<QQQI4x",*(bases[r]+16 for r in ROLES),n)
        check(all(b>0 and b%4==0 for b in bases.values()) and ptr==(raw/key/"params.bin").read_bytes()
              and hashlib.sha256(ptr).hexdigest()==sample["payload_sha256"],"ABI differs")
        snapshots = {}
        for j,(phase,counter,addr) in enumerate((p,c,a) for p in ("idle","before","after","settled")
                                                for c,a in (("cycles",0xb00),("instret",0xb02))):
            r = reads[seq*8+j]
            check(all(r[k]==v for k,v in identity.items()) and r["phase"]==phase and r["counter"]==counter
                  and r["address"]==addr and r["exit_code"]==0 and 0<=r["raw"]<2**44,"invalid counter response")
            snapshots.setdefault(phase,{})[counter] = r["raw"]
        check(snapshots["idle"]==snapshots["before"] and snapshots["after"]==snapshots["settled"],"unstable counters")
        for c in ("cycles","instret"):
            check(snapshots["after"][c]-snapshots["before"][c]==sample["counts"][c]>0,"counter delta differs")
        times = [sample[k] for k in ("h2d_ns","wait_ns","d2h_ns")]
        check(all(v>0 for v in times) and sum(times)==sample["total_ns"]
              and sample["retired_monotonic_ns"]-sample["submit_monotonic_ns"]==sample["wait_ns"],"timing differs")
    for key in specs:
        check((raw/key/"out.bin").read_bytes()==(corpus/(key+".expected.bin")).read_bytes(),"raw output differs: "+key)
    matrix = [[0]*3 for _ in range(3)]
    errors = []
    fold_correct = []
    for fold in read(corpus/"folds.json"):
        output = (raw/fold["id"]/"out.bin").read_bytes()
        correct = 0
        for i,(line,label) in enumerate(zip(fold["test"],fold["true"])):
            pred = struct.unpack_from("<4I",output,16+16*i)[3]
            matrix[label][pred] += 1
            if pred==label:
                correct += 1
            else:
                errors.append([line,label,pred])
        fold_correct.append(correct)
    groups = {}
    for n in frozen["sizes"]:
        group = [s for s in samples if s["scope"]=="timed" and s["n"]==n]
        check(len(group)==30,"sample count differs")
        stats = {k:distribution([s[k] for s in group]) for k in ("h2d_ns","wait_ns","d2h_ns","total_ns")}
        stats.update({k:distribution([s["counts"][k] for s in group]) for k in ("cycles","instret")})
        stats["warp_ipc"] = distribution([s["counts"]["instret"]/s["counts"]["cycles"] for s in group])
        groups[str(n)] = stats
    return dict(status="PASS",launches=len(samples),counter_reads=len(reads),timed=180,accuracy_correct=sum(fold_correct),
                accuracy_total=150,fold_correct=fold_correct,confusion=matrix,errors=sorted(errors),groups=groups)


def verify_returned(prep,result,returned):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/"scripts"))
    from c_v03_board import check_commands, review_gate
    summary = read(returned/"summary.json")
    check_commands(returned,summary)
    check(review_gate(returned)==summary["gate_sha256"] and summary["run_id"]==prep["run_id"]
          and summary["bdf"]==prep["bdf"] and summary["exit_code"]==result["worker_exit_code"]==0
          and summary["plan_sha256"]==prep["plan_sha256"] and result["archive_sha256"]==prep["archive_sha256"]
          and summary["board_execution"]=="PASS","board, worker or plan identity differs")
    raw = returned/"u280-xrt"
    capture = read(raw/"capture.json")
    check(capture["binding_sha256"]==sha(returned/"binding/binding.json") and capture["module_sha256"]==prep["module_sha256"]
          and capture["lock_sha256"]==read(returned/"binding/binding.json")["target_lock_hash"]
          and capture["final_state"]=="CLOSED" and capture["launch_attempts"]==217,"capture identity differs")
    return analyze(root/prep["corpus"],raw)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("corpus",type=Path)
    cli.add_argument("capture",type=Path)
    args = cli.parse_args()
    print(json.dumps(analyze(args.corpus,args.capture),indent=2))
