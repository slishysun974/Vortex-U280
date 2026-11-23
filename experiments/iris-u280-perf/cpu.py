"""Build and time the native single-thread CPU baseline on the same frozen schedule."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from analyze import FROZEN, check, distribution, read, sha
from run_native_smoke import Recorder, utc_now
from run_ptx_copy import run_stage


def verify_samples(corpus, path):
    manifest = read(corpus/"inputs/manifest.json")
    sizes = {spec["id"]:spec["n"] for spec in manifest["cases"]}
    with path.open() as f:
        rows = list(csv.reader(f))
    check(len(rows)==len(manifest["schedule"])==217,"CPU schedule incomplete")
    groups, cpus = {}, set()
    for (seq,key,scope,trial,n,ns,cpu),spec in zip(rows,manifest["schedule"]):
        check(spec==dict(seq=int(seq),case=key,scope=scope,trial=int(trial)) and int(n)==sizes[key] and int(ns)>0,
              "CPU sample identity or elapsed time differs")
        cpus.add(int(cpu))
        if scope=="timed":
            groups.setdefault(n,[]).append(int(ns))
    check(len(cpus)==1 and all(len(v)==30 for v in groups.values()),"CPU affinity or trial count differs")
    return {n:distribution(values) for n,values in groups.items()}, cpus.pop()


def run(corpus,out,rec):
    check(sha(corpus/"freeze.json")==FROZEN,"unexpected corpus")
    for name,digest in read(corpus/"freeze.json")["files"].items():
        check(sha(corpus/name)==digest,"changed corpus input")
    manifest = read(corpus/"inputs/manifest.json")
    sizes = {s["id"]:s["n"] for s in manifest["cases"]}
    schedule = out/"schedule.txt"
    schedule.write_text("".join("{seq} {case} {n} {scope} {trial}\n".format(n=sizes[s["case"]],**s) for s in manifest["schedule"]))
    compiler = run_stage(rec,"compiler",["g++","--version"],out).splitlines()[0]
    cpuinfo = run_stage(rec,"cpu_model",["lscpu"],out)
    model = re.search(r"(?m)^Model name:\s*(.+)$",cpuinfo).group(1)
    binary = out/"benchmark"
    compile_cmd = ["g++","-O3","-march=native","-std=c++17","-fno-lto","-fopt-info-vec-optimized",
                   HERE/"cpu_kernel.cpp",HERE/"cpu_bench.cpp","-o",binary]
    run_stage(rec,"compile",compile_cmd,out)
    cpu = min(os.sched_getaffinity(0))
    output = run_stage(rec,"native_run",["taskset","-c",str(cpu),binary,corpus,schedule],out,120)
    (out/"samples.csv").write_bytes(output.encode())
    groups,observed_cpu = verify_samples(corpus,out/"samples.csv")
    check(observed_cpu==cpu,"CPU affinity changed")
    rec.summary.update(compiler=compiler,cpu_model=model,kernel=platform.release(),logical_cpu=cpu,
                       threads=1,groups_ns=groups,launches=217,timed=180,corpus_sha256=FROZEN,
                       samples_sha256=sha(out/"samples.csv"),binary_sha256=sha(binary),
                       source_sha256={p:sha(HERE/p) for p in ("cpu_kernel.cpp","cpu_bench.cpp")})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("corpus",type=Path)
    p.add_argument("output",type=Path)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir()
    report = dict(status="RUNNING",commands=[],started_at=utc_now(),argv=[sys.executable,"-B",*sys.argv])
    rec = Recorder(out,report,dict(os.environ,LC_ALL="C"))
    try:
        run(a.corpus.resolve(),out,rec)
        report.update(status="PASS",exit_code=0)
    except Exception as error:
        report.update(status="FAIL",exit_code=1,error=str(error))
    report["finished_at"] = utc_now()
    rec.save()
    print(report["status"],out,report.get("error",""))
    sys.exit(report["exit_code"])
