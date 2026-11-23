"""Offline receiver check against the two frozen corpora and original launch/LSU evidence."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
OLD = RESULTS / "ae-v03-frozen-20261121-v1"
NEW = RESULTS / "e-v14-frozen-20261122-v1"


def read(path):
    return json.loads(path.read_bytes())


def hash_file(path):
    return sha256(path.read_bytes()).hexdigest()


def check(condition, label):
    if not condition:
        raise ValueError(str(label))


def verify(out, built, models, trace):
    anchors = [(NEW, "b116876ecc4f7dbd7941df93e31aae1dad7e19c9b1aae4699afb31f8f8d8e523"),
               (OLD, "6a6331574453bbdd4118ab60fdb4f4b837527f28a7fed127aa8c8e8faeaaaa07")]
    for frozen, anchor in anchors:
        check(hash_file(frozen / "manifest.json") == anchor, frozen)
        for name, digest in read(frozen / "manifest.json")["files"].items():
            check(hash_file(frozen / name) == digest, name)
    index = {}
    for run in (built, models, trace):
        summary = read(run / "summary.json")
        check(summary["exit_code"] == 0 and summary["status"] == "PASS", run)
        for cmd in summary["commands"]:
            check(cmd["returncode"] == 0 and not cmd["timed_out"] and
                  hash_file(run / cmd["log"]) == cmd["log_sha256"], cmd["label"])
        index[run.name] = hash_file(run / "summary.json")
    versions = {k: hash_file(ROOT / "scripts" / (k + ".py")) for k in
                ("ptx_frontend", "ptx_frontend_v12", "ptx_frontend_v13", "ptx_frontend_v14",
                 "ptx_module", "ptx_runtime", "ptx_launch")}
    rows = {}
    for b in ("simx", "rtlsim", "xrtsim"):
        arrays = payloads = 0
        alias = models / b / "witness/alias"
        for item in (OLD / "alias").glob("*.bin"):
            check(item.read_bytes() == (alias / item.name).read_bytes(), item.name)
        for frozen, _ in anchors:
            for ordinal, s in enumerate(read(frozen / "manifest.json")["cases"], 1):
                new = frozen == NEW
                folder = (models / b if new else models / b / "witness") / s["id"]
                bases = read(folder / ("bases.json" if new else "reservations.json"))
                roles = s["roles"] if new else ["x", "z", "audit"]
                for r in roles:
                    for phase in ("before", "after"):
                        if new:
                            name = ("expected-z" if r == "z" and phase == "after" else r) + ".bin"
                            actual = folder / (r + "-" + phase + ".bin")
                        else:
                            name = r + (".input.bin" if phase == "before" else ".expected.bin")
                            actual = folder / (r + "." + phase + ".bin")
                        check(actual.read_bytes() == (frozen / s["id"] / name).read_bytes(), actual)
                        arrays += 1
                if new:
                    scalars = [s["n"]] + ([s["alpha"]] if s["op"] == "affine" else
                                          [s["selected"]] if s["op"] == "predicate_turn" else [])
                else:
                    if s["bases"] is not None:
                        check(bases == s["bases"], folder)
                    roles = roles[:2] if s["entry"] == "p0_form_witness" else roles
                    scalars = s["scalars"]
                blob = b"".join(struct.pack("<Q", bases[r] + 4*s["offsets"][r]) for r in roles)
                blob += b"".join(struct.pack("<I", v) for v in scalars)
                check((folder / "params.bin").read_bytes() == blob + bytes(-len(blob) % 8), folder)
                check(read(folder / "event.json") == dict(backend=b, event_id=ordinal, generation=0,
                                                          status="COMPLETE"), folder)
                payloads += 1
        observed = []
        for name, case in read(trace / "summary.json")["models"][b]["cases"].items():
            folder = trace / b / name
            lanes = read(folder / "requests.json")
            check(all(row["observed"] == row["expected"] for row in lanes), folder)
            observed.append(sum(len(row["observed"]) for row in lanes))
            check(observed[-1] == case["requests"], folder)
        check(arrays == 210 and payloads == 37 and sorted(observed) == [0, 2, 3, 3, 40], b)
        rows[b] = dict(full_buffer_readbacks=arrays, alias_readbacks=4, payloads=payloads,
                       events=payloads, trace_launches=len(observed), array_requests=sum(observed))
    return dict(status="PASS", exit_code=0, scope="independent local v1.4 acceptance on fixed D5 models",
                sources=versions, receipts=index, backends=rows, physical_u280="NOT_RUN",
                human_signoff="NOT_RUN", argv=sys.argv)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("output", "built", "models", "trace"):
        cli.add_argument(arg, type=Path)
    a = cli.parse_args()
    a.output.mkdir()
    try:
        result = verify(a.output, a.built, a.models, a.trace)
    except Exception as error:
        result = dict(status="FAIL", exit_code=1, error=str(error), argv=sys.argv)
    (a.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["status"], result.get("error", ""))
    sys.exit(result["exit_code"])
