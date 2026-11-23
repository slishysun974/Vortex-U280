"""Check the existing fixed D10/D12 lane observation paths from archived bytes."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))

from ptx_module import BOARD_LOCK_SHA, digest, read_json, write_json
from run_native_smoke import sha256, utc_now
from u280_aligned_pair import preflight
from u280_board_smoke import RUNTIME_SHAS, XCLBIN_SHA, XCLBIN_UUID

D8 = PROJECT / "results/ab-d8-u280-source-20261109-v1"
D10 = PROJECT / "results/u280-archive-20261109-v5/returned"
D12 = PROJECT / "results/u280-runtime-20261109-v4/returned/runtime"
PRIOR = PROJECT / "results/u280-aligned-mpm-20261122-v1"
FROZEN = PROJECT / "results/u280-aligned-predicate-preflight-20261121-v1/bundle"
COMPILED = PROJECT / "results/u280-aligned-load-build-20261122-v2"

SECTION_NAMES = {0: "BITSTREAM", 2: "EMBEDDED_METADATA", 4: "DEBUG_DATA", 6: "MEM_TOPOLOGY",
                 7: "CONNECTIVITY", 8: "IP_LAYOUT", 9: "DEBUG_IP_LAYOUT", 11: "CLOCK_FREQ_TOPOLOGY",
                 14: "BUILD_METADATA", 20: "PARTITION_METADATA", 22: "SYSTEM_METADATA",
                 26: "GROUP_TOPOLOGY", 27: "GROUP_CONNECTIVITY"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return read_json(path.read_bytes())


def inspect_xclbin(output):
    path = D10 / "artifacts/vortex_afu.xclbin"
    archived = (D10 / "inspection/xclbin_info.stdout").read_bytes()
    size = path.stat().st_size
    require(sha256(path) == XCLBIN_SHA, "fixed D10 artifact differs")
    with path.open("rb") as stream:
        header = stream.read(0x1C8)
        require(header[:8] == b"xclbin2\0" and struct.unpack_from("<Q", header, 0x130)[0] == size,
                "unexpected fixed D10 xclbin container")
        image_uuid = str(uuid.UUID(bytes=header[0x1A0:0x1B0]))
        count, = struct.unpack_from("<I", header, 0x1C0)
        require(image_uuid == XCLBIN_UUID and count == 11, "fixed D10 UUID or section count differs")
        table = stream.read(count * 40)
    rows = []
    end = len(header) + len(table)
    for kind, label, offset, length in struct.iter_unpack("<I16s4xQQ", table):
        require(end <= offset <= size and 0 < length <= size - offset, "invalid D10 section extent")
        rows.append(dict(kind=kind, name=SECTION_NAMES[kind], label=label.split(b"\0")[0].decode("ascii"),
                         offset=offset, bytes=length))
        end = offset + length
    names = [row["name"] for row in rows]
    official = re.search(r"Sections:\s+(.*?)\r?\n=+", archived.decode(), re.S).group(1)
    require(names == [name.strip() for name in official.split(",")], "section table differs from archived XRT inspection")
    with path.open("rb") as stream:
        stream.seek(end)
        mirror = stream.read()
    start_marker, end_marker = b"XCLBIN_MIRROR_DATA_START", b"XCLBIN_MIRROR_DATA_END"
    require(mirror.startswith(start_marker) and mirror.endswith(end_marker), "unexpected XRT mirror metadata")
    mirror_sections = [dict(fields) for key, fields in
                       json.loads(mirror[len(start_marker):-len(end_marker)], object_pairs_hook=list)
                       if key == "section_header"]
    require([(int(s["Kind"]), s["Name"], int(s["Offset"], 16), int(s["Size"], 16)) for s in mirror_sections]
            == [(s["kind"], s["label"], s["offset"], s["bytes"]) for s in rows], "XRT mirror section table differs")
    (output / "xclbin-header-and-sections.bin").write_bytes(header + table)
    (output / "xclbin-mirror.bin").write_bytes(mirror)
    (output / "xclbin_info.stdout").write_bytes(archived)
    (output / "xclbin_info.stderr").write_bytes((D10 / "inspection/xclbin_info.stderr").read_bytes())
    require(not {"DEBUG_IP_LAYOUT", "DEBUG_DATA"}.intersection(names), "D10 has debug metadata requiring review")
    return dict(sha256=XCLBIN_SHA, uuid=image_uuid, sections=rows, mirror_sha256=digest(mirror))


def inspect_trace_paths(output, nm, record):
    d8_manifest = D8 / "package/manifest.json"
    d10_build = load(D10 / "build/result.json")
    require(sha256(d8_manifest) == d10_build["input_manifest_sha256"] == sha256(D10 / "build/input_manifest.json"),
            "D10 does not use the archived D8 input manifest")
    d8 = next(row for row in load(D8 / "summary.json")["commands"] if row["label"] == "candidate_merged_config")
    flags = next(arg.removeprefix("--cflags=").split() for arg in d8["argv"] if arg.startswith("--cflags="))
    require(d8["exit_code"] == d10_build["exit_code"] == 0 and "-DNDEBUG" in flags and "-DSYNTHESIS" in flags,
            "D10 source/build receipt differs")
    options = load(D10 / "inspection/build_metadata.json")["build_metadata"]["xclbin"]["generated_by"]["options"]
    require(not any(flag.startswith(("-DSCOPE", "-DCHIPSCOPE", "-DDBG_SCOPE")) for flag in flags) and
            not re.search(r"--(?:debug|profile)(?:[.\s=]|$)", options), "D10 trace flags require review")
    (output / "d10-link-options.txt").write_bytes((options + "\n").encode())

    routed = D10 / "reports/link/imp/impl_1_full_util_routed.rpt"
    debug_cells = [line for line in routed.read_text(encoding="utf-8").splitlines()
                   if re.search(r"\b(?:ila|vio|system_ila|dbg_hub|axi_perf_mon)\b|user_debug_", line, re.I)]
    require(len(debug_cells) == 2 and all("user_debug_" in line for line in debug_cells),
            "routed debug resources require review")
    (output / "d10-routed-debug-cells.txt").write_bytes(("\n".join(debug_cells) + "\n").encode())

    d12 = load(D12 / "result.json")
    commands = [row for row in d12["commands"] if row["label"] in ("stub", "xrt")]
    require(len(commands) == 2 and all(row["exit_code"] == 0 and "TARGET=hw" in row["argv"] and
            not re.search(r"-D(?:SCOPE|CHIPSCOPE|NOXRT)(?:\s|=|$)", " ".join(row["argv"])) for row in commands),
            "D12 production build flags differ")
    for name, expected in RUNTIME_SHAS.items():
        library = D12 / "lib" / name
        require(sha256(library) == expected, "fixed D12 library differs: " + name)
        argv = [str(nm), "-C", str(library)]
        done = subprocess.run(argv, capture_output=True, timeout=30)
        stdout = output / (name + ".nm.stdout")
        stderr = output / (name + ".nm.stderr")
        stdout.write_bytes(done.stdout)
        stderr.write_bytes(done.stderr)
        record["commands"].append(dict(argv=argv, exit_code=done.returncode, stdout=stdout.name, stderr=stderr.name))
        require(done.returncode == 0 and b"vx_scope_" not in done.stdout, "compiled SCOPE path requires review")
    symbols = (output / "libvortex.so.nm.stdout").read_bytes()
    require(b"vx_device_mpm_query" in symbols and b"cp_ring_append_" in symbols, "D12 aggregate/CP paths differ")
    return dict(d8_config_command=d8, d8_manifest_sha256=sha256(d8_manifest),
                d10_routed_debug_cells=[line.strip() for line in debug_cells], d12_build_commands=commands,
                d12_library_sha256=RUNTIME_SHAS, hardware_scope=False, host_scope=False,
                cp_trace="host CP ring descriptors", base_mpm="per-core aggregate counters",
                hbm_axi="downstream of LSU coalescing and cache")


def review_old_outputs():
    plan, manifests, _ = preflight(FROZEN, COMPILED)
    prior = load(PRIOR / "result.json")
    raw = PRIOR / "returned" / PRIOR.name
    binding = load(raw / "binding/binding.json")
    require(prior["status"] == prior["board_execution"] == "PASS" and binding["target_lock_hash"] == BOARD_LOCK_SHA and
            binding["xclbin_sha256"] == XCLBIN_SHA and binding["libraries"] == RUNTIME_SHAS, "prior board identity differs")
    samples = (raw / "samples.jsonl").read_bytes()
    outputs = {}
    require(digest(samples) == prior["receipt"]["samples_sha256"], "prior paired samples differ")
    rows = [read_json(line) for line in samples.splitlines()]
    for (op, route), manifest in manifests.items():
        case = "{}/16381".format(op)
        output = raw / "outputs" / case / (route + ".out.bin")
        wanted = FROZEN / "inputs" / case / "expected.bin"
        actual = output.read_bytes()
        expected = wanted.read_bytes()
        match = [row for row in rows if (row["operator"], row["n"], row["route"]) == (op, 16381, route)]
        require(actual == expected and digest(actual) == plan["files"]["inputs/" + case + "/expected.bin"] and
                len(match) == plan["warm"] + plan["trials"] and all(row["output_sha256"] == digest(actual) for row in match),
                "prior full output or sentinel differs")
        outputs[op + "/" + route] = dict(module_sha256=manifest["image_sha256"], output_sha256=digest(actual),
                                        bytes=len(actual), archived_launches=len(match))
    return dict(status="PASS", source_run=PRIOR.name, samples_sha256=digest(samples), outputs=outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nm", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    record = dict(schema="u280-fixed-tail-lane-observability-v1", argv=[sys.executable, "-B", *sys.argv],
                  started_at=utc_now(), commands=[], board_execution="NOT_RUN", tail_zero_requests="NOT_RUN")
    try:
        record["d10"] = inspect_xclbin(args.output)
        record["paths"] = inspect_trace_paths(args.output, args.nm.resolve(), record)
        record["archived_outputs"] = review_old_outputs()
        record.update(status="BLOCKED", audit_status="PASS", exit_code=0,
                      reason="Fixed D10/D12 exposes no pre-coalescer request observation with lane identity.")
    except (OSError, ValueError, KeyError, AttributeError, StopIteration, subprocess.SubprocessError) as error:
        record.update(status="FAIL", audit_status="FAIL", exit_code=1, reason=str(error))
    record["files"] = {p.name: sha256(p) for p in args.output.iterdir() if p.is_file()}
    record["finished_at"] = utc_now()
    write_json(args.output / "summary.json", record)
    print(json.dumps({key: record[key] for key in ("status", "audit_status", "exit_code", "reason")}))
    return record["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
