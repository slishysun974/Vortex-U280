"""Freeze Iris inference inputs and exact rational answers before device execution."""
import argparse
import csv
import hashlib
import json
import shutil
import struct
from fractions import Fraction
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
RAW_SHA = "0fed2a99db77ec533a62dc66894d3ec6df3b58b6a8f3cf4a6b47e4086b7f97dc"
CLASSES = ["Iris-setosa", "Iris-versicolor", "Iris-virginica"]


def save(path, value):
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def split(data):
    counts = [0] * 3
    train, test = [], []
    for line, fields in enumerate(csv.reader(data.decode("ascii").splitlines()), 1):
        if not fields:
            continue
        check(len(fields) == 5, "invalid fields on line %d" % line)
        c = CLASSES.index(fields[-1])
        mm = [Fraction(s) * 10 for s in fields[:4]]
        check(all(v.denominator == 1 and 0 <= v <= 100 for v in mm), "invalid mm on line %d" % line)
        group = test if counts[c] % 10 in (0, 3, 7) else train
        group.append((line, c, list(map(int, mm))))
        counts[c] += 1
    check(counts == [50, 50, 50], "unexpected class counts")
    for c in range(3):
        check(sum(v[1] == c for v in train) == 35 and sum(v[1] == c for v in test) == 15, "split differs")
    a, b = ({v[0] for v in group} for group in (train, test))
    check(not a & b and a | b == set(range(1, 151)), "source rows differ")
    return train, test


def fit(train):
    return [[sum(row[j] for _, label, row in train if label == c) for j in range(4)] for c in range(3)]


def answer(row, model):
    distances = []
    for sums in model:
        exact = sum((Fraction(x) - Fraction(s, 35)) ** 2 for x, s in zip(row, sums)) * 1225
        check(exact.denominator == 1 and 0 <= exact <= 49000000, "distance outside exact u32 domain")
        distances.append(int(exact))
    return distances + [distances.index(min(distances))]


def pack(rows):
    return b"".join(struct.pack("<4I", *row) for row in rows)


def freeze(out):
    out.mkdir()
    raw = (DATA / "bezdekIris.data").read_bytes()
    check(hashlib.sha256(raw).hexdigest() == RAW_SHA, "UCI source identity differs")
    shutil.copytree(DATA, out / "data")
    train, test = split(raw)
    model = fit(train)
    check(model == [[1753,1199,511,86], [2093,988,1489,470], [2302,1032,1940,712]], "training sums differ")
    rows = [r for _, _, r in test]
    lines = [line for line, _, _ in test]
    save(out / "split.json", dict(row_number_origin=1, train=[r[0] for r in train], test=lines,
                                  classes=CLASSES, features_mm=["sepal_length","sepal_width","petal_length","petal_width"]))
    pred = [answer(row, model) for row in rows]
    matrix = [[0] * 3 for _ in CLASSES]
    for (_, label, _), result in zip(test, pred):
        matrix[label][result[3]] += 1
    check(matrix == [[15,0,0],[0,12,3],[0,2,13]] and pred[0] == [2397,1309034,2819202,0], "CPU cross-check differs")
    save(out / "classifier.json", dict(sums_mm=model, confusion_true_by_predicted=matrix,
         correct=sum(matrix[c][c] for c in range(3)), total=len(test),
         predictions=[dict(line=line, true=label, x_mm=row, distances=p[:3], predicted=p[3])
                      for (line, label, row), p in zip(test, pred)]))

    cases = [(name, rows[:n], model, lines[:n]) for name, n in
             (("test45",45), ("empty",0), ("one",1), ("n31",31), ("n32",32), ("n33",33))]
    cases.extend([
        ("permuted", rows, [model[c] for c in (1,2,0)], lines),
        ("ties", [[1,1,0,0],[2,2,0,0]], [[0]*4,[70,0,0,0],[0,70,0,0]], ["ties-1","ties-2"]),
        ("endpoints", [[0]*4,[100]*4], [[0]*4,[3500]*4,[1750]*4], ["endpoints-1","endpoints-2"]),
    ])
    specs = []
    for index, (name, features, sums, ids) in enumerate(cases):
        directory = out / name
        directory.mkdir()
        n = len(features)
        grid = max(1, (n+31)//32)
        spec = dict(id=name, n=n, block=32, grid=grid, rows=ids, offset=16, access_bytes=dict(x=16*n, sums=48, out=16*n))
        specs.append(spec)
        expected = [answer(row, sums) for row in features]
        save(directory / "answers.json", expected)
        for role_id, (role, size, initial) in enumerate((
                ("x", grid*32*16, pack(features)), ("sums", 48, pack(sums)), ("out", grid*32*16, b""))):
            # Unique u32 patterns across roles, cases and positions, all above the maximum distance.
            base = 0xC0000000 + (index << 20) + (role_id << 16)
            image = bytearray(b"".join(struct.pack("<I", base + j) for j in range(size//4 + 8)))
            image[16:16+len(initial)] = initial
            (directory / (role + ".input.bin")).write_bytes(image)
            if role == "out":
                image[16:16+16*n] = pack(expected)
                (directory / "out.expected.bin").write_bytes(image)
    hashes = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(out.rglob("*")) if p.is_file()}
    save(out / "manifest.json", dict(version="iris-u280-corpus-v1", cases=specs, files=hashes))
    print("150 rows; train 105, test 45; correct 40/45; confusion", matrix)
    print("9 cases; manifest SHA-256", hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest())


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("output", type=Path)
    freeze(cli.parse_args().output)
