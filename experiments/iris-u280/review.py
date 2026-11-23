"""Verify raw Iris captures offline against the sealed mathematical reference."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

CORPUS_SHA = "34d9c44e029649b5a2306235c7fef6765beea0d02a4e7b290a85917104deaeb2"
ROLES = ("x", "sums", "out")
FIELDS = ("D0","D1","D2","class")


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, message):
    if not ok:
        raise ValueError(message)


def check_corpus(root):
    path = root / "manifest.json"
    check(sha(path) == CORPUS_SHA, "unexpected Iris corpus version")
    manifest = read(path)
    for name, digest in manifest["files"].items():
        check(sha(root / name) == digest, "changed corpus member " + name)
    return manifest


class Difference(ValueError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__(json.dumps(detail))


def compare(actual, expected, spec, backend, role, phase):
    if actual == expected:
        return
    detail = dict(backend=backend, case=spec["id"], role=role, phase=phase)
    if len(actual) != len(expected):
        raise Difference(dict(detail, field="size", expected=len(expected), actual=len(actual)))
    byte = next(i for i, (a,b) in enumerate(zip(actual,expected)) if a != b)
    word = byte & ~3
    row = (byte-16)//16
    field = (byte//4) % 4
    sample = None
    if byte < 16:
        name = "front_guard"
    elif byte >= len(actual)-16:
        name = "back_guard"
    elif role == "sums":
        name = "model[%d][%d]" % (row,field)
    elif row >= spec["n"]:
        name = "tail"
    else:
        name = FIELDS[field] if role == "out" else "x[%d]" % field
        sample = spec["rows"][row]
    raise Difference(dict(detail, row=row, sample=sample, field=name, byte_offset=byte,
                          expected=struct.unpack_from("<I",expected,word)[0],
                          actual=struct.unpack_from("<I",actual,word)[0]))


def review(frozen, manifest, out, backend, binding, module_sha, negative=False):
    record = read(out/"capture.json")
    cases = manifest["cases"]
    caps = record["initial_caps"]
    check(record["backend"] == caps["backend"] == backend and record["binding_sha256"] == sha(binding)
          and record["module_sha256"] == module_sha and record["lock_sha256"] == read(binding)["target_lock_hash"]
          and (caps["cores"],caps["warps"],caps["threads"]) == (1,8,4)
          and "error" not in record and record["final_state"] == "CLOSED"
          and record["launch_attempts"] == len(cases) and record["completed"] == [s["id"] for s in cases],
          "capture identity, device state or sequence differs")
    receipts, rejected = [], []
    for event_id, spec in enumerate(cases, 1):
        cid, n = spec["id"], spec["n"]
        ref, raw = frozen / cid, out / cid
        bases = read(raw/"bases.json")
        regions = sorted((bases[r], (ref/(r+".input.bin")).stat().st_size) for r in ROLES)
        check(all(b > 0 and b % 4 == 0 for b, _ in regions) and
              all(b+l <= next_b for (b,l),(next_b,_) in zip(regions,regions[1:])), "overlapping or unaligned buffers")
        payload = struct.pack("<QQQI4x", *(bases[r]+16 for r in ROLES), n)
        check((raw/"params.bin").read_bytes() == payload and
              read(raw/"event.json") == dict(status="COMPLETE",backend=backend,event_id=event_id,generation=0),
              "payload or completion differs: " + cid)
        for role in ROLES:
            initial = (ref/(role+".input.bin")).read_bytes()
            expected = (ref/"out.expected.bin").read_bytes() if role == "out" else initial
            compare((raw/(role+".before.bin")).read_bytes(), initial, spec, backend, role, "before")
            compare((raw/(role+".after.bin")).read_bytes(), expected, spec, backend, role, "after")
        actual = (raw/"out.after.bin").read_bytes()
        values = [list(words) for words in struct.iter_unpack("<4I", actual[16:16+16*n])]
        check(values == read(ref/"answers.json"), "decoded integer mismatch: " + cid)
        receipts.append(dict(id=cid, status="PASS", samples=n, distance_words=3*n, class_words=n,
                             output_sha256=sha(raw/"out.after.bin"), tail_rows=32*spec["grid"]-n))
        if negative and cid == "test45":
            for offset, field in ((16,"D0"), (28,"class"), (16+16*n,"tail")):
                corrupted = bytearray(actual)
                corrupted[offset] ^= 1
                try:
                    compare(corrupted, expected, spec, backend, "out", "after")
                except Difference as error:
                    check(error.detail["field"] == field and error.detail["byte_offset"] == offset, "wrong diagnostic")
                    rejected.append(error.detail)
                else:
                    raise ValueError("undetected corruption in " + field)
    return dict(status="PASS", launches=len(cases), cases=receipts, negative_controls=rejected,
                capture_sha256=sha(out/"capture.json"), full_buffer_snapshots=6*len(cases))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("frozen","capture","binding","module"):
        cli.add_argument("--"+arg, required=True, type=Path)
    cli.add_argument("--backend", required=True)
    a = cli.parse_args()
    print(json.dumps(review(a.frozen, check_corpus(a.frozen), a.capture, a.backend, a.binding,
                            sha(a.module/"manifest.json"), negative=True), indent=2))
