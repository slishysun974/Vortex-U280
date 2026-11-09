"""Prepare a hash-bound start/status request for the approved D9 link."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(run_id, mode, build_run):
    for value in (run_id, build_run):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
            raise ValueError("unsafe run id")
    if mode not in ("start", "status", "archive") or (mode == "start" and run_id != build_run):
        raise ValueError("invalid start/status identity")
    xo_run = "u280-preflight-20261109-100406-629"
    prior = ROOT / "results" / xo_run
    probe = json.loads((prior / "probe.json").read_text())
    build = probe["build_result"]
    if probe["status"] != "PASS" or build["status"] != "PASS" or build["stage"] != "xo":
        raise ValueError("accepted D9 XO required")
    builder = (prior / "returned/build/build_prepared.py").read_bytes()
    if sha(builder) != probe["files"]["build/build_prepared.py"]["sha256"]:
        raise ValueError("D9 builder snapshot mismatch")
    bundle = dict(run_id=run_id, build_run=build_run, xo_run=xo_run, mode=mode, nonce=uuid.uuid4().hex,
        authorized=mode == "start", authorization="2026-11-09 user: 按此启动; 2 CPUs, 6-hour v++ timeout, no RAM hard cap",
        builder_sha256=sha(builder), xo_sha256=build["artifact"]["sha256"], flow_sha256=build["flow_sha256"],
        input_identity={k: build[k] for k in ("target_lock_sha256", "input_manifest_sha256", "input_files")},
        platform_files=probe["platform_identity"])
    remote_name = "u280_remote_link.py"
    if mode == "archive":
        accepted = ROOT / "results/u280-link-20261109-155638-456/returned/build/result.json"
        completed = json.loads(accepted.read_text())
        if (completed["status"] != "PASS" or completed["exit_code"] != 0 or
                completed["stage"] != "link" or build_run != "u280-link-20261109-103830-671"):
            raise ValueError("archive requires the completed D10 link")
        bundle.update(accepted_result_sha256=sha(accepted.read_bytes()), artifact=completed["artifact"])
        remote_name = "u280_remote_archive.py"
    raw = (ROOT / "scripts" / remote_name).read_bytes()
    encoded = json.dumps(bundle, ensure_ascii=True).encode("ascii")
    payload = """import base64, hashlib, json, traceback
raw = base64.b64decode(%r)
assert hashlib.sha256(raw).hexdigest() == %r
bundle = json.loads(base64.b64decode(%r).decode('ascii'))
namespace = {'__name__':'u280_link_control'}
try:
    exec(compile(raw, 'u280_remote_link.py', 'exec'), namespace)
    result = namespace['collect'](bundle)
except Exception as exc:
    result = dict(status='FAIL', error=repr(exc), traceback=traceback.format_exc(), nonce=bundle['nonce'], run_id=bundle['run_id'])
result['remote_probe_sha256'] = hashlib.sha256(raw).hexdigest()
print('U280_PROBE_BEGIN_' + bundle['nonce'])
print(json.dumps(result, ensure_ascii=True, indent=2))
print('U280_PROBE_END_' + bundle['nonce'])
""" % (base64.b64encode(raw).decode("ascii"), sha(raw), base64.b64encode(encoded).decode("ascii"))
    run = ROOT / "results" / run_id
    run.mkdir(exist_ok=False)
    (run / "payload.py").write_bytes(payload.encode("ascii"))
    (run / "bundle.json").write_bytes(encoded)
    (run / "preparation.json").write_text(json.dumps(dict(run_id=run_id, nonce=bundle["nonce"],
        remote_probe_sha256=sha(raw), payload_sha256=sha(payload.encode("ascii")), bundle_sha256=sha(encoded)), indent=2))
    for name in ("prepare_u280_link.py", remote_name, "prepare_u280_probe.py", "wlan_ssh_proxy.py", "Invoke-U280Link.ps1"):
        shutil.copy2(ROOT / "scripts" / name, run / name)
    print(str(run))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--mode", choices=("start", "status", "archive"), required=True)
    parser.add_argument("--build-run", required=True)
    args = parser.parse_args()
    prepare(args.run_id, args.mode, args.build_run)
