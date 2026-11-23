"""Reproduce the labelled folds, distinct synthetic inputs and exact output bytes."""
import argparse
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "iris-u280"))
from freeze import DATA, RAW_SHA, answer, fit, pack, split

SIZES = (45, 150, 1024, 4096, 16381, 65533)
SEED = 20261123
ROLES = ("x", "sums", "out")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def store(path, value):
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def generate(out):
    out.mkdir()
    inputs = out / "inputs"
    inputs.mkdir()
    raw = (DATA / "bezdekIris.data").read_bytes()
    if digest(raw) != RAW_SHA:
        raise ValueError("UCI data changed")
    train, test = split(raw)
    rows = sorted(train + test)
    model = fit(train)
    unique = {tuple(row) for _, _, row in rows}
    bounds = [(min(dim), max(dim)) for dim in zip(*(row for _, _, row in rows))]
    rng = random.Random(SEED)
    synthetic = []
    while len(synthetic) < max(SIZES):
        item = tuple(rng.randint(lo, hi) for lo, hi in bounds)
        if item not in unique:
            unique.add(item)
            synthetic.append(item)
    cases, schedule, folds = [], [], []
    specifications = []
    for fold in range(5):
        training, testing = [], []
        for label in range(3):
            group = [entry for entry in rows if entry[1] == label]
            testing.extend(group[fold::5])
            remaining = [entry for i, entry in enumerate(group) if i % 5 != fold]
            training.extend(entry for i, entry in enumerate(remaining) if i % 8 != fold)
        assert len(training) == 105 and len(testing) == 30
        assert not {e[0] for e in training} & {e[0] for e in testing}
        key = "fold%d" % fold
        sums = fit(training)
        folds.append(dict(id=key, train=[r[0] for r in training], test=[r[0] for r in testing],
                          true=[r[1] for r in testing], sums=sums))
        specifications.append((key, [r[2] for r in testing], sums))
    assert sorted(line for fold in folds for line in fold["test"]) == list(range(1,151))
    for n in SIZES:
        features = [r[2] for r in test] if n == 45 else [r[2] for r in rows] if n == 150 else synthetic[:n]
        specifications.append(("n%d" % n, features, model))
    expected_hashes = {}
    for idx, (key, features, sums) in enumerate(specifications):
        directory = inputs / key
        directory.mkdir()
        n = len(features)
        grid = (n+31)//32
        spec = dict(id=key, n=n, block=32, grid=grid, offset=16, access_bytes=dict(x=16*n,sums=48,out=16*n))
        cases.append(spec)
        guard = lambda mark: struct.pack("<I", 0xf0000000 + 256*idx + mark)
        for i,(role, initial, words) in enumerate((("x",pack(features),grid*128),("sums",pack(sums),12),
                                                   ("out",b"",grid*128))):
            allocation = (guard(3*i)*4 + initial + guard(3*i+1)*(words-len(initial)//4) + guard(3*i+2)*4)
            (directory/(role+".input.bin")).write_bytes(allocation)
        output = bytearray(allocation)
        output[16:16+16*n] = pack(answer(row,sums) for row in features)
        (out/(key+".expected.bin")).write_bytes(output)
        expected_hashes[key] = digest(output)

    def add(key, role, trial):
        schedule.append(dict(seq=len(schedule)+1, case=key, scope=role, trial=trial))

    for i in range(2):
        add("n45","probe",i)
    for i in range(5):
        add("fold%d"%i,"fold",i)
    for scope, repetitions in (("warmup",5),("timed",30)):
        for trial in range(repetitions):
            for j in range(len(SIZES)):
                add("n%d"%SIZES[(j+trial)%len(SIZES)],scope,trial)
    store(inputs/"manifest.json",dict(cases=cases,schedule=schedule))
    store(out/"folds.json",folds)
    members = {p.relative_to(out).as_posix():digest(p.read_bytes()) for p in sorted(out.rglob("*")) if p.is_file()}
    store(out/"freeze.json",dict(version="iris-perf-v1", source_sha256=RAW_SHA, seed=SEED, ranges_mm=bounds,
                               unique_synthetic=len(synthetic), sizes=SIZES, warmup=5, timed=30,
                               expected=expected_hashes, files=members))
    print("150 out-of-fold rows; 65533 distinct synthetic vectors; 217 launches; freeze",digest((out/"freeze.json").read_bytes()))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output",type=Path)
    generate(cli.parse_args().output)
