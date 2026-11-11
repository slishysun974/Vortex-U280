"""E-only integrity helpers. No production imports or executable oracle."""
import hashlib
import json
from pathlib import Path

FROZEN_SHA256 = "ee47fa9d641a1c94f35666610d4910924c233fb83f13b1e859c26ce3de95a654"
PRODUCTION = ("ptx_frontend_v12.py", "ptx_module.py", "ptx_launch.py", "ptx_runtime.py", "ptx_u280.py", "runtime_backends.py")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def need(condition, message):
    if not condition:
        raise ValueError(message)


def corpus(path, digest=FROZEN_SHA256):
    path = Path(path)
    need(sha((path / "manifest.json").read_bytes()) == digest, "frozen manifest identity")
    manifest = read(path / "manifest.json")
    for source in manifest["sources"].values():
        need(sha((path / source["file"]).read_bytes()) == source["sha256"], "source identity")
    for case in manifest["cases"]:
        for name, expected in case["files"].items():
            need(sha((path / "vectors" / case["id"] / name).read_bytes()) == expected, "vector identity " + case["id"] + "/" + name)
    return manifest
