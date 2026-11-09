"""Extract hash-bound report members into a fresh directory, rejecting unsafe archives."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def unpack(archive, inventory, destination):
    expected = {}
    for item in inventory:
        name = item["path"]
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or
                path.as_posix() != name or name in expected or item["bytes"] < 0):
            raise ValueError("unsafe or duplicate report manifest path")
        expected[name] = item
    if not expected or sum(i["bytes"] for i in expected.values()) > 2 * 1024 ** 3:
        raise ValueError("report manifest size bound")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != set(expected):
            raise ValueError("report archive inventory mismatch")
        for member in members:
            if not member.isfile() or member.size != expected[member.name]["bytes"]:
                raise ValueError("non-regular or incorrectly sized report member")
        destination.mkdir(exist_ok=False)
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with tar.extractfile(member) as source, target.open("xb") as out:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != expected[member.name]["sha256"]:
                raise ValueError("report hash mismatch: " + member.name)
    return len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    probe = json.loads((args.run / "probe.json").read_text())
    if probe["status"] != "PASS":
        raise ValueError("successful archive transport required")
    path = args.run / "returned/inspection/reports.tar.gz"
    item = probe["files"]["inspection/reports.tar.gz"]
    if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError("compressed report identity mismatch")
    count = unpack(path, probe["report_inventory"], args.run / "returned/reports")
    print(json.dumps(dict(status="PASS", reports=count)))


if __name__ == "__main__":
    main()
