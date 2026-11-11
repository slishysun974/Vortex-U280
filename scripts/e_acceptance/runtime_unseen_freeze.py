"""Independent E corpus. Read only source PTX/contracts; never implementation outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def freeze(destination):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "sources").mkdir()
    (destination / "vectors").mkdir()
    base = ROOT / "results/c-runtime-merge-20261111-v3/modules/sim"
    sources = {}
    for kind in ("copy", "vadd", "affine"):
        source = (base / kind / "source.ptx").read_text(encoding="utf-8")
        for variant in (False, True):
            name = kind + ("_variant" if variant else "")
            text = source
            if variant:
                text = text.replace(kind + "_u32", "e_november_" + kind)
                text = text.replace("%r", "%evalue").replace("%a", "%eptr").replace("%p", "%outside")
                text = text.replace("setp.lt.u32", "setp.ge.u32").replace("@%outside", "@!%outside")
                text = text.replace(", 4;", ", 0x4U;")
                if kind == "copy":
                    text = text.replace("  @!%outside st.global", "  @!%outside sub.u32 %evalue3, %evalue3, 0;\n  @!%outside st.global")
                elif kind == "vadd":
                    text = text.replace("%evalue5, %evalue3, %evalue4;", "%evalue5, %evalue4, %evalue3;")
                    text = text.replace("  @!%outside st.global", "  @!%outside add.u32 %evalue5, %evalue5, 0;\n  @!%outside st.global")
                else:
                    text = text.replace("%evalue5, %evalue3, %evalue7;", "%evalue5, %evalue7, %evalue3;")
                    text = text.replace("  @!%outside st.global", "  @!%outside mul.lo.u32 %evalue6, %evalue6, 1;\n  @!%outside st.global")
            path = destination / "sources" / (name + ".ptx")
            path.write_text(text, encoding="utf-8", newline="\n")
            sources[name] = dict(file=str(path.relative_to(destination)).replace("\\", "/"), sha256=sha(path.read_bytes()),
                                 semantics=kind, entry=("e_november_" + kind if variant else kind + "_u32"))
    shapes = [(0, 3), (2, 5), (5, 6), (17, 9), (47, 13), (79, 19), (193, 23), (509, 29)]
    alphas = [0, 1, 0xffffffff, 0x80000001, 0xfffffffe, 65537, 0x9e3779b9, 0x40000003]
    boundary = [0, 1, 0xffffffff, 0x80000000, 0x7fffffff, 0xfffffffe, 0xaaaaaaaa, 0x55555555]
    cases = []
    modules = list(sources)
    for row, (n, block) in enumerate(shapes):
        # Reverse alternate rows: the end module repeats at the next boundary.
        for column, module in enumerate(modules if row % 2 == 0 else list(reversed(modules))):
            number = len(cases)
            case_id = "e%03d" % number
            prefix = destination / "vectors" / case_id
            prefix.mkdir()
            offsets = {"x": 1 + (number * 7) % 23, "y": 2 + (number * 11) % 29, "z": 3 + (number * 13) % 31}
            arrays = {}
            for role in ("x", "y", "z"):
                words = []
                for i in range(600):
                    digest = hashlib.sha256(("E-runtime-unseen-20261111-v1:%s:%s:%d" % (case_id, role, i)).encode()).digest()
                    words.append(int.from_bytes(digest[:4], "little"))
                if role != "z":
                    for i in range(n):
                        if i % 11 < 8:
                            words[offsets[role] + i] = boundary[(i + (3 if role == "y" else 0) + row) % 8]
                arrays[role] = words
                (prefix / (role + ".input.bin")).write_bytes(struct.pack("<600I", *words))
            expected = list(arrays["z"])
            semantics = sources[module]["semantics"]
            for i in range(n):
                x = arrays["x"][offsets["x"] + i]
                y = arrays["y"][offsets["y"] + i]
                value = x if semantics == "copy" else (x + y if semantics == "vadd" else alphas[row] * x + y)
                expected[offsets["z"] + i] = value % 4294967296
            (prefix / "z.expected.bin").write_bytes(struct.pack("<600I", *expected))
            files = {p.name: sha(p.read_bytes()) for p in sorted(prefix.iterdir())}
            cases.append(dict(id=case_id, module=module, semantics=semantics, n=n, block=block,
                              grid=max(1, (n + block - 1) // block) + row % 3,
                              alpha=alphas[row], offsets_words=offsets, allocation_words=600,
                              allocation_generation=number // 24, files=files))
    production_names = ["scripts/ptx_frontend_v12.py", "scripts/ptx_module.py", "scripts/ptx_launch.py", "scripts/ptx_runtime.py", "scripts/ptx_u280.py", "scripts/runtime_backends.py", "scripts/bind_simx_runtime.py", "configs/target_lock.json", "configs/c_runtime/api_v1.json"]
    production = {name: sha((ROOT / name).read_bytes()) for name in production_names}
    inputs = ["docs/COLLABORATION_PROTOCOL.md", "docs/PTX_COMPATIBILITY_PROFILE.md", "configs/ptx_frontend/v1/profile.json"]
    manifest = dict(schema="e-runtime-unseen-frozen-v1", seed="E-runtime-unseen-20261111-v1", cases=cases, sources=sources,
                    baseline="c-runtime-merge-20261111-v3", production_at_freeze=production,
                    specification_hashes={p: sha((ROOT / p).read_bytes()) for p in inputs},
                    freeze_generator_sha256=sha(Path(__file__).read_bytes()),
                    independence="E authored before opening prior expected outputs, actual outputs, implementation oracle or smoke generator. No production import in oracle.",
                    oracle="i=block_id*B+thread_id; active iff i<N. copy x; vadd x+y; affine alpha*x+y, modulo 2^32. All 600 words x/y unchanged. z changes only [offset,offset+N).",
                    abi="Little endian: copy <QQI4x; vadd <QQQI4x; affine <QQQII. Pointers=recorded allocation device base+4*offset. Scalars n/alpha from frozen case.",
                    lifecycle="One context and one queue for all 48 launches; one resident module; alternating modules, seven consecutive same-module boundaries; reuse allocations then free/reallocate after case 23; wait completed and READY before reads.",
                    acceptance="All commands exit 0; 48 completed events per backend; exact full arrays and raw payload; launch RUNNING/wait READY; no generation change; no CPU fallback.",
                    limits=["No claim of arbitrary P0, high-address stress, false-predicate trace invisibility, hardware faults/recovery, performance or human E signature.", "Unseen means independently constructed without consulting development vectors; cannot prove no coincidental individual integer matches prior data."])
    dump(destination / "manifest.json", manifest)
    digest = sha((destination / "manifest.json").read_bytes())
    (destination / "manifest.sha256").write_text(digest + "  manifest.json\n", encoding="ascii")
    print(digest, len(cases))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    freeze(Path(parser.parse_args().out))
