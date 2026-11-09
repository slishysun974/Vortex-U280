"""Freeze existing D5 native cases with D12 server libraries; no board access."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
KERNEL_SHA = "19b5aeddbaf2a0d664295a7b0811b1fba9999aa73c0ee157994766db799f8505"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise ValueError("unsafe run id")
    run = ROOT / "results" / run_id
    run.mkdir(exist_ok=False)
    data = run / "input"
    data.mkdir()
    d5 = ROOT / "results/ab-d5-block32-20261108-v1-simx"
    d12 = ROOT / "results/u280-runtime-20261109-v4"
    runtime_prep = ROOT / "results/u280-runtime-gcc9-prepare-20261109-v2"
    summary = json.loads((d5 / "summary.json").read_text())
    corpus = json.loads((d5 / "boundary/corpus.json").read_text())
    runtime = json.loads((d12 / "returned/runtime/result.json").read_text())
    if (summary["native_boundary"]["status"] != "PASS" or len(corpus["cases"]) != 152 or
            runtime["status"] != "PASS"):
        raise ValueError("accepted D5/D12 evidence required")
    if sha(d5 / "boundary/corpus.json") != summary["native_boundary"]["corpus_sha256"]:
        raise ValueError("D5 corpus digest changed")
    manifest = []

    def copy(src, name, expected=None):
        digest = sha(src)
        if expected and digest != expected:
            raise ValueError("input identity mismatch: " + str(src))
        dest = data / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as out:
            out.write(src.read_bytes())
        manifest.append(dict(path=name, bytes=dest.stat().st_size, sha256=digest,
                             source=src.relative_to(ROOT).as_posix()))

    copy(d5 / "artifacts/tests/regression/boundary/kernel.vxbin", "kernel.vxbin", KERNEL_SHA)
    copy(d5 / "boundary/corpus.json", "corpus.json")
    copy(d5 / "boundary/inputs/cases.tsv", "inputs/cases.tsv", corpus["case_table_sha256"])
    for case in corpus["cases"]:
        for group in ("inputs", "expected"):
            for name, digest in case[group].items():
                if Path(name).name != name or not re.fullmatch(r"\d{3}_(x|y|z|audit)\.bin", name):
                    raise ValueError("unexpected corpus member")
                copy(d5 / "boundary" / group / name, group + "/" + name, digest)
    for name in ("main.cpp", "common.h", "kernel.cpp"):
        copy(d5 / "boundary/source" / name, "source/" + name, summary["native_boundary"]["source_sha256"][name])
    binding = json.loads((runtime_prep / "binding.json").read_text())
    header = next(x for x in binding["source_files"] if x["path"] == "sw/runtime/include/vortex2.h")
    copy(ROOT / "upstream/vortex" / header["path"], "include/vortex2.h", header["sha256"])
    copy(runtime_prep / "resolved.cflags", "resolved.cflags", binding["resolved_cflags_sha256"])
    for artifact in runtime["artifacts"]:
        copy(d12 / "returned/runtime" / artifact["path"], artifact["path"], artifact["sha256"])
    copy(runtime_prep / "binding.json", "runtime-binding.json")
    (data / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    package = run / "u280-native-board-input.tar.gz"
    with tarfile.open(package, "w:gz") as tar:
        for path in sorted(data.rglob("*")):
            if path.is_file():
                raw = path.read_bytes()
                info = tarfile.TarInfo("u280-native-board-input/" + path.relative_to(data).as_posix())
                info.size, info.mode, info.mtime = len(raw), 0o644, 0
                tar.addfile(info, io.BytesIO(raw))
    result = dict(schema_version="u280-native-board-input-v1", status="PASS", exit_code=0,
        scope="offline input identity/copy checks only", run_id=run_id, source_cases=152,
        kernel_sha256=KERNEL_SHA, input_files=len(manifest),
        package=dict(path=package.name, bytes=package.stat().st_size, sha256=sha(package)),
        manifest_sha256=sha(data / "manifest.json"), runtime_binding_sha256=sha(data / "runtime-binding.json"),
        host_compile="NOT_RUN", board_load="NOT_RUN", board_execution="NOT_RUN", ptx_device="NOT_RUN",
        reference="Preserved D5 same-author native u32 oracle; no regenerated answers; not independent E acceptance",
        gates=["HOST capacity readback", "timing warning dispositions", "fresh privileged idle/holder check",
               "compile host against bundled CentOS libraries", "loaded UUID and actual 200 MHz readback",
               "native smoke before complete 152-launch regression"])
    shutil.copy2(__file__, run / Path(__file__).name)
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    prepare(parser.parse_args().run_id)
