"""Prepare a short compressed SSH TTY command and independent result collector."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]


def prepare(run_id, timing_only=False):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("unsafe run id")
    source = (ROOT / "scripts/u280_remote_readiness.py").read_bytes()
    tcl = (ROOT / "scripts/u280_readiness_audit.tcl").read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    bundle = dict(run_id=run_id, nonce=uuid.uuid4().hex, remote_probe_sha256=digest, configure_host=not timing_only,
                  tcl_sha256=hashlib.sha256(tcl).hexdigest(), tcl_base64=base64.b64encode(tcl).decode("ascii"))
    payload = ("import base64, hashlib, json\n"
               "raw = base64.b64decode(%r)\n"
               "assert hashlib.sha256(raw).hexdigest() == %r\n"
               "namespace = {'__name__': 'u280_readiness'}\n"
               "exec(compile(raw, 'u280_remote_readiness.py', 'exec'), namespace)\n"
               "raise SystemExit(namespace['main'](json.loads(%r)))\n") % (
                   base64.b64encode(source).decode("ascii"), digest, json.dumps(bundle, ensure_ascii=True))
    compressed = base64.b64encode(zlib.compress(payload.encode("ascii"), 9)).decode("ascii")
    command = "exec python3 -B -c 'import base64,zlib,sys;exec(zlib.decompress(base64.b64decode(sys.argv[1])))' " + compressed
    if len(command) > 24000:
        raise ValueError("SSH command exceeds conservative Windows argument budget")
    collector = ("import json, pathlib, pwd, os\n"
                 "assert pwd.getpwuid(os.getuid()).pw_name == 'u280user'\n"
                 "path = pathlib.Path.home() / 'vortex-u280-readiness' / %r / 'result.json'\n"
                 "result = json.loads(path.read_text())\n"
                 "assert result['nonce'] == %r\n"
                 "print('U280_PROBE_BEGIN_' + result['nonce'])\n"
                 "print(json.dumps(result, ensure_ascii=True))\n"
                 "print('U280_PROBE_END_' + result['nonce'])\n") % (run_id, bundle["nonce"])
    run = ROOT / "results" / run_id
    run.mkdir(exist_ok=False)
    (run / "interactive_command.txt").write_text(command, encoding="ascii")
    (run / "collector.py").write_text(collector, encoding="ascii")
    (run / "bundle.json").write_text(json.dumps(bundle, indent=2))
    (run / "preparation.json").write_text(json.dumps(dict(run_id=run_id, nonce=bundle["nonce"],
        remote_probe_sha256=digest, tcl_sha256=bundle["tcl_sha256"],
        payload_sha256=hashlib.sha256(payload.encode("ascii")).hexdigest(),
        interactive_command_chars=len(command)), indent=2))
    for name in ("u280_remote_readiness.py", "u280_readiness_audit.tcl", "prepare_u280_readiness.py",
                 "Invoke-U280Readiness.ps1", "prepare_u280_probe.py", "wlan_ssh_proxy.py"):
        shutil.copy2(ROOT / "scripts" / name, run / name)
    print(str(run))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--timing-only", action="store_true")
    args = parser.parse_args()
    prepare(args.run_id, args.timing_only)
