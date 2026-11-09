"""Prepare the fixed D11 runtime compile and read-only platform inspection."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SHA = "9976e187005d38005c1733d0bc5e9f337450109252bb908662fc9c4839c79b84"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(run_id, profile="pinned"):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("unsafe run id")
    if profile not in ("pinned", "gcc9-v1"):
        raise ValueError("unknown runtime profile")
    prior = ROOT / ("results/u280-runtime-prepare-20261109-v1" if profile == "pinned" else
                    "results/u280-runtime-gcc9-prepare-20261109-v2")
    expected_sha = PACKAGE_SHA if profile == "pinned" else "6911b8dcbcc0c2a4ea6aa5ea6d636de470c442159e2f062e0861227f3d05ee16"
    accepted = json.loads((prior / "result.json").read_text())
    package = (prior / "u280-runtime200-input.tar.gz").read_bytes()
    if (accepted["status"] != "PASS" or accepted["exit_code"] != 0 or
            sha(package) != expected_sha or accepted["package"]["sha256"] != expected_sha):
        raise ValueError("accepted D11 runtime package required")
    probe = (ROOT / "scripts/u280_remote_probe.py").read_bytes()
    bundle = dict(schema_version="u280-runtime-request-v1", run_id=run_id, nonce=uuid.uuid4().hex,
        source_commit=accepted["binding"]["source_commit"],
        runtime_profile=profile,
        package=dict(sha256=expected_sha, bytes=len(package), base64=base64.b64encode(package).decode("ascii")),
        inspection=dict(sha256=sha(probe), base64=base64.b64encode(probe).decode("ascii")),
        binding_sha256=sha((prior / "binding.json").read_bytes()),
        manifest_sha256=sha((prior / "manifest.json").read_bytes()))
    raw = (ROOT / "scripts/u280_remote_runtime.py").read_bytes()
    encoded = json.dumps(bundle, ensure_ascii=True).encode("ascii")
    payload = """import base64, hashlib, json, traceback
raw = base64.b64decode(%r)
assert hashlib.sha256(raw).hexdigest() == %r
bundle = json.loads(base64.b64decode(%r).decode('ascii'))
namespace = {'__name__':'u280_runtime_control'}
try:
    exec(compile(raw, 'u280_remote_runtime.py', 'exec'), namespace)
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
        remote_probe_sha256=sha(raw), payload_sha256=sha(payload.encode("ascii")),
        bundle_sha256=sha(encoded), package_sha256=expected_sha, runtime_profile=profile), indent=2) + "\n")
    for name in ("prepare_u280_runtime_remote.py", "u280_remote_runtime.py", "u280_remote_probe.py",
                 "prepare_u280_probe.py", "wlan_ssh_proxy.py", "Invoke-U280Runtime.ps1"):
        shutil.copy2(ROOT / "scripts" / name, run / name)
    print(str(run))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--profile", choices=("pinned", "gcc9-v1"), default="pinned")
    args = parser.parse_args()
    prepare(args.run_id, args.profile)
