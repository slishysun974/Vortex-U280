"""Frame the frozen performance schedule and the previously verified Iris board image."""
import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from c_v03_board import PY_FILES
from c_v03_board_transport import BOOTSTRAP
from ptx_module import validate
from ptx_u280 import BUSES, QUERY_SOURCE
from run_native_smoke import sha256
from run_ptx_copy import BOARD_LOCK, read_json, require, write_json

IMAGE = "9ae0e644040d13d558b58d2e5c8dd502a71a82017202168161bf2e09267ddcdd"


def prepare(a):
    freeze = read_json(a.corpus/"freeze.json")
    for name,digest in freeze["files"].items():
        require(sha256(a.corpus/name) == digest,"frozen member differs: "+name)
    meta, _ = validate(a.module,BOARD_LOCK.read_bytes())
    require(meta["image_sha256"] == IMAGE,"Iris physical image differs")
    files = {"query.cpp":QUERY_SOURCE.encode(),"target_lock.json":BOARD_LOCK.read_bytes(),
             "hardware.json":BOARD_LOCK.with_name("fpga.json").read_bytes()}
    for name in ["manifest.json",*meta["files"]]:
        files["module/"+name] = (a.module/name).read_bytes()
    for name in (*PY_FILES,"u280_aligned_counters.py"):
        files["scripts/"+name] = (ROOT/"scripts"/name).read_bytes()
    files["scripts/iris_inputs.py"] = (HERE.parent/"iris-u280/capture.py").read_bytes()
    files["scripts/board_worker.py"] = (HERE.parent/"iris-u280/board_worker.py").read_bytes()
    files["scripts/capture.py"] = (HERE/"measure.py").read_bytes()
    files["scripts/telemetry.py"] = (HERE/"telemetry.py").read_bytes()
    for name in freeze["files"]:
        if name.startswith("inputs/"):
            files[name] = (a.corpus/name).read_bytes()
    vendor = ROOT/"third_party/dataclasses-0.8"
    for name,digest in read_json(vendor/"provenance.json")["files"].items():
        require(sha256(vendor/name)==digest,"Python backport changed")
        files["vendor/dataclasses-0.8/"+name] = (vendor/name).read_bytes()
    schedule = json.loads(files["inputs/manifest.json"])["schedule"]
    plan = dict(version="iris-board-perf-v1",cases=[s["case"] for s in schedule],
                files={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
    files["plan.json"] = json.dumps(plan,sort_keys=True).encode()
    run = ROOT/"results"/a.run_id
    run.mkdir()
    archive = run/"board-input.tar.gz"
    with tarfile.open(archive,"x:gz") as tar:
        for name,data in sorted(files.items()):
            if name.endswith(".py"):
                ast.parse(data.decode(),filename=name,feature_version=(3,6))
            info = tarfile.TarInfo("bundle/"+name)
            info.size = len(data)
            tar.addfile(info,io.BytesIO(data))
    nonce = uuid.uuid4().hex
    args = (a.run_id,nonce,a.bdf,sha256(archive),base64.b64encode(archive.read_bytes()).decode(),"board_worker.py")
    payload = run/"payload.py"
    payload.write_bytes(("INPUT = "+repr(args)+"\n"+BOOTSTRAP).encode("ascii"))
    write_json(run/"preparation.json",dict(status="PASS",exit_code=0,run_id=a.run_id,bdf=a.bdf,nonce=nonce,
        version=plan["version"],entry=args[-1],expected_cases=len(schedule),board_execution="NOT_RUN",
        archive_sha256=sha256(archive),plan_sha256=hashlib.sha256(files["plan.json"]).hexdigest(),
        payload_sha256=sha256(payload),module_sha256=sha256(a.module/"manifest.json"),image_sha256=IMAGE,
        corpus=a.corpus.relative_to(ROOT).as_posix(),corpus_sha256=sha256(a.corpus/"freeze.json"),
        argv=[sys.executable,"-B",*sys.argv]))
    print("PASS",run,len(schedule),"launches; no reference outputs in board archive")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("run_id")
    for arg in ("corpus","module"):
        cli.add_argument("--"+arg,type=lambda v:Path(v).resolve(),required=True)
    cli.add_argument("--bdf",choices=["0000:"+b+":00.1" for b in BUSES],default="0000:b1:00.1")
    options = cli.parse_args()
    require(re.fullmatch(r"iris-board-perf-[A-Za-z0-9_-]{1,40}",options.run_id),"invalid board run ID")
    prepare(options)
