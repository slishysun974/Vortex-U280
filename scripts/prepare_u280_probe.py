"""Prepare and unpack the fixed, bounded U280 preflight bundle."""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if ROOT.name == "results":
    ROOT = ROOT.parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(run_id, probe_kind="component", platform_run=None, build_flow="pinned"):
    if probe_kind not in ("component", "host-platform", "xo"):
        raise ValueError("unsupported probe kind")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("unsafe run id")
    run = ROOT / "results" / run_id
    run.mkdir(exist_ok=False)
    lock_path = ROOT / "configs/target_lock.json"
    lock = json.loads(lock_path.read_text())
    manifest_path = ROOT / lock["evidence"] / "source_manifest.json"
    if sha(manifest_path.read_bytes()) != lock["source_manifest_sha256"]:
        raise ValueError("source manifest identity changed")
    manifest = {entry["path"]: entry["sha256"] for entry in json.loads(manifest_path.read_text())}
    files = {}
    source_names = (("hw/rtl/afu/common/VX_afu_axi_limit.sv", "hw/rtl/VX_platform.vh", "hw/rtl/VX_scope.vh")
                    if probe_kind == "component" else ())
    for relative in source_names:
        raw = (ROOT / "upstream/vortex" / relative).read_bytes()
        if sha(raw) != manifest[relative]:
            raise ValueError("fixed source differs: " + relative)
        files["rtl/" + Path(relative).name] = dict(sha256=sha(raw), base64=base64.b64encode(raw).decode("ascii"), source=relative)
    if probe_kind == "component":
        raw = (ROOT / "environment/u280-small-build/probe.tcl").read_bytes()
        files["probe.tcl"] = dict(sha256=sha(raw), base64=base64.b64encode(raw).decode("ascii"))
    nonce = uuid.uuid4().hex
    bundle = dict(schema_version="u280-small-build-input-v1", run_id=run_id, nonce=nonce, files=files,
                  probe_kind=probe_kind, source_commit=lock["vortex"]["commit"], target_lock_sha256=sha(lock_path.read_bytes()))
    if probe_kind == "xo":
        if build_flow not in ("pinned", "ip-ooc-v1"):
            raise ValueError("unknown build flow")
        bundle["build_flow"] = build_flow
        if not platform_run or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", platform_run):
            raise ValueError("XO requires a successful --platform-run")
        prior = ROOT / "results" / platform_run
        probe = json.loads((prior / "probe.json").read_text())
        if probe["status"] != "PASS" or probe["probe_kind"] != "host-platform":
            raise ValueError("HOST/platform preflight did not pass")
        metadata_path = prior / "returned/platform_metadata.json"
        if sha(metadata_path.read_bytes()) != probe["files"]["platform_metadata.json"]["sha256"]:
            raise ValueError("platform metadata identity mismatch")
        bundle["platform_files"] = [{k: x[k] for k in ("path", "bytes", "sha256")}
            for x in json.loads(metadata_path.read_text()) if x["status"] == "PASS"]
        if len(bundle["platform_files"]) != 2:
            raise ValueError("XPFM/XSA metadata required")
        bundle["platform_evidence"] = dict(run_id=platform_run, probe_sha256=sha((prior / "probe.json").read_bytes()))
        package = ROOT / "results/ab-d8-u280-source-20261109-v1/u280-rtl-input.tar.gz"
        if sha(package.read_bytes()) != "6759015dd48471589c3c98ce833d8d225fd1d3e1580e970223b7d703b686d44e":
            raise ValueError("D8 archive identity mismatch")
        for name, path in (("u280-rtl-input.tar.gz", package),
                           ("build_prepared.py", ROOT / "environment/u280-fpga/build_prepared.py")):
            raw = path.read_bytes()
            files[name] = dict(sha256=sha(raw), base64=base64.b64encode(raw).decode("ascii"))
    encoded = json.dumps(bundle, ensure_ascii=True).encode("ascii")
    remote_name = "u280_remote_xo.py" if probe_kind == "xo" else "u280_remote_probe.py"
    source = (ROOT / "scripts" / remote_name).read_bytes()
    payload = """import base64, hashlib, json, sys, traceback
raw = base64.b64decode(%r)
assert hashlib.sha256(raw).hexdigest() == %r
bundle = json.loads(base64.b64decode(%r).decode('ascii'))
namespace = {'__name__': 'u280_probe'}
try:
    exec(compile(raw, 'u280_remote_probe.py', 'exec'), namespace)
    result = namespace['collect'](bundle)
except Exception as exc:
    result = {'status':'FAIL', 'error':repr(exc), 'traceback':traceback.format_exc(), 'nonce':bundle['nonce'], 'run_id':bundle['run_id']}
result['remote_probe_sha256'] = hashlib.sha256(raw).hexdigest()
print('U280_PROBE_BEGIN_' + bundle['nonce'])
print(json.dumps(result, ensure_ascii=True, indent=2))
print('U280_PROBE_END_' + bundle['nonce'])
""" % (base64.b64encode(source).decode("ascii"), sha(source), base64.b64encode(encoded).decode("ascii"))
    (run / "payload.py").write_text(payload, encoding="ascii")
    (run / "bundle.json").write_bytes(encoded)
    (run / "preparation.json").write_text(json.dumps(dict(run_id=run_id, nonce=nonce,
        remote_probe_sha256=sha(source), payload_sha256=sha((run / "payload.py").read_bytes()), bundle_sha256=sha(encoded)), indent=2))
    for name in ("prepare_u280_probe.py", remote_name, "wlan_ssh_proxy.py", "Invoke-U280Preflight.ps1"):
        shutil.copy2(ROOT / "scripts" / name, run / name)
    shutil.copy2(lock_path, run / "target_lock.json")
    print(str(run))


def unpack(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("unsafe run id")
    run = ROOT / "results" / run_id
    prep = json.loads((run / "preparation.json").read_text())
    raw = (run / "probe.stdout").read_bytes()
    text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    begin, end = "U280_PROBE_BEGIN_" + prep["nonce"], "U280_PROBE_END_" + prep["nonce"]
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError("missing/duplicate result framing")
    result = json.loads(text.split(begin)[1].split(end)[0].strip())
    if result["run_id"] != run_id or result["nonce"] != prep["nonce"] or result["remote_probe_sha256"] != prep["remote_probe_sha256"]:
        raise ValueError("identity mismatch")
    returned = run / "returned"
    returned.mkdir(exist_ok=False)
    for relative, item in result.get("files", {}).items():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or ":" in relative or "\\" in relative:
            raise ValueError("unsafe returned file")
        if "base64" not in item:
            continue
        raw = base64.b64decode(item.pop("base64"), validate=True)
        if len(raw) != item["bytes"] or sha(raw) != item["sha256"]:
            raise ValueError("returned artifact digest mismatch")
        destination = returned.joinpath(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
        item["local_path"] = "returned/" + relative
    result["raw_stdout_sha256"] = sha((run / "probe.stdout").read_bytes())
    with (run / "probe.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(dict(status=result["status"], small_synthesis=result.get("small_synthesis"),
                         device_count=len(result.get("devices", [])))))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "unpack"))
    parser.add_argument("run_id")
    parser.add_argument("--probe-kind", choices=("component", "host-platform", "xo"), default="component")
    parser.add_argument("--platform-run")
    parser.add_argument("--build-flow", choices=("pinned", "ip-ooc-v1"), default="pinned")
    args = parser.parse_args()
    sys.exit(prepare(args.run_id, args.probe_kind, args.platform_run, args.build_flow) if args.mode == "prepare" else unpack(args.run_id))
