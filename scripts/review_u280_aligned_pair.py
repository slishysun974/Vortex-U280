"""Review the exact captured U280 staging, frozen outputs and paired timings."""
import statistics
from itertools import groupby

from c_v03_board import review_gate
from ptx_module import digest, read_json
from ptx_u280_aligned import (OPERATORS, PROBE_SHA256, ROUTES, probe_observation,
                              require, verify_cp_read, verify_vm_query)
from run_native_smoke import sha256
from u280_aligned_pair import preflight
from u280_aligned_counters import COUNTERS, COUNTER_LIMIT, launch_delta

PHASES = ("load_ns", "h2d_ns", "execute_wait_ns", "d2h_ns", "total_ns")


def document(path):
    return read_json(path.read_bytes())


def review_probes(run, bundle, plan, manifests, gate):
    proof = run / "alignment.json"
    receipt = document(proof)
    require(receipt["status"] == "PASS" and receipt["run_id"] == run.name and
            receipt["binding_sha256"] == gate["binding_sha256"] and receipt["probe_sha256"] == PROBE_SHA256 and
            receipt["cp_dev_caps"] == gate["cp_dev_caps"] and receipt["vm_query"] == gate["vm_query"] and
            gate["aligned_staging"] == dict(status="PASS", sha256=sha256(proof)), "staging receipt differs from the live gate")
    verify_cp_read(receipt["cp_dev_caps"])
    verify_vm_query(receipt["vm_query"])
    observed = []
    offset = 4 * plan["guard_words"]
    for op in OPERATORS:
        manifest = manifests[op, "aligned"]
        roles = [field["name"] for field in manifest["params"] if field["kind"] == "pointer"]
        for spec in plan["cases"]:
            n = spec["n"]
            attempts = []
            payloads = []
            for attempt, marker in enumerate((0xff, 0xee), 1):
                path = run / "probe" / op / str(n) / str(attempt)
                before = {role: (path / (role + ".before.bin")).read_bytes() for role in roles}
                after = {role: (path / (role + ".after.bin")).read_bytes() for role in roles}
                end = offset + 16 * (1 + len(manifest["params"]))
                for role in roles:
                    original = (bundle / "inputs" / op / str(n) / (role + ".bin")).read_bytes()
                    expected = original[:offset] + bytes([marker]) * (end - offset) + original[end:] if role == "x" else original
                    require(before[role] == expected, "probe initial bytes or marker differ")
                payload = (path / "params.bin").read_bytes()
                row = probe_observation(manifest, payload, before, after, offset)
                scalars = {f["name"]: f["value"] for f in row["fields"] if f["name"] not in roles}
                require(scalars == (dict(n=n, alpha=plan["affine_alpha"]) if op == "affine" else dict(n=n)),
                        "probe used a different scalar payload")
                payloads.append(payload)
                attempts.append(row)
            require(attempts[0]["a0"] == attempts[1]["a0"] and payloads[0] == payloads[1],
                    "probe did not reuse the retired slot and workload payload")
            observed.append(dict(operator=op, n=n, attempts=attempts))
    require(observed == receipt["workloads"], "raw probe readbacks differ from staging receipt")
    return sum(len(row["attempts"]) for row in observed)


def review_samples(run, bundle, plan, *, counters=False):
    samples = (run / "samples.jsonl").read_bytes()
    schedule = document(bundle / "pair-schedule.json")
    rows = [read_json(line) for line in samples.splitlines()]
    require(len(rows) == 2 * len(schedule), "incomplete paired samples")
    timed = {}
    for i, spec in enumerate(schedule):
        case = "{operator}/{n}".format(**spec)
        expected = plan["files"]["inputs/" + case + "/expected.bin"]
        pair = {}
        for route, row in zip(spec["order"], rows[2 * i:2 * i + 2]):
            expected_row = dict(spec, route=route, output_sha256=expected, **{phase: row[phase] for phase in PHASES})
            if counters:
                expected_row["device_counts"] = row["device_counts"]
            require(row == expected_row,
                    "sample order or output hash differs")
            require(all(type(row[phase]) is int and row[phase] >= 0 for phase in PHASES) and
                    row["total_ns"] == sum(row[phase] for phase in PHASES[:-1]), "invalid phase durations")
            pair[route] = row
        if not spec["warmup"]:
            timed.setdefault(case, []).append(pair)
    medians, deltas = {}, {}
    for case, batch in timed.items():
        expected = (bundle / "inputs" / case / "expected.bin").read_bytes()
        case_dir = run / "outputs" / case
        require(all((case_dir / (route + ".out.bin")).read_bytes() == expected for route in ROUTES) and
                (case_dir / "aligned.params.bin").read_bytes() == (case_dir / "merged.params.bin").read_bytes(),
                "captured full output, sentinel or route payload differs")
        medians[case] = {route: {phase: statistics.median(p[route][phase] for p in batch)
                                 for phase in PHASES} for route in ROUTES}
        deltas[case] = {phase: statistics.median(p["merged"][phase] - p["aligned"][phase] for p in batch) for phase in PHASES}
    return dict(launches=len(rows), timed_pairs=sum(map(len, timed.values())),
                samples_sha256=digest(samples), median_ns=medians, median_merged_minus_aligned_ns=deltas)


def review_counters(run, receipt, *, clock_mhz):
    raw = (run / "counter-reads.jsonl").read_bytes()
    rows = [read_json(line) for line in (run / "samples.jsonl").read_bytes().splitlines()]
    phases = ("idle", "before", "after", "settled")
    expected_reads = [(phase, counter, addr) for phase in phases for counter, addr in COUNTERS.items()]
    sample_keys = ("scope", "operator", "n", "attempt", "pair", "route")
    samples = {}
    require(receipt["core"] == receipt["mpm_class"] == 0 and receipt["addresses"] == COUNTERS,
            "unexpected D10/D12 counter selection")
    query_rows = [read_json(line) for line in raw.splitlines()]
    for ident, group in groupby(query_rows, key=lambda row: tuple(row.get(key) for key in sample_keys)):
        reads = list(group)
        complete = ([(r["phase"], r["counter"], r["address"]) for r in reads] == expected_reads and
                    all(r["exit_code"] == 0 and 0 <= r["raw"] < COUNTER_LIMIT for r in reads))
        if not complete:
            require(receipt["status"] == "BLOCKED", "incomplete or invalid native MPM responses")
            continue
        try:
            delta = launch_delta({phase: {r["counter"]: r["raw"] for r in reads if r["phase"] == phase}
                                  for phase in phases})
        except ValueError:
            require(receipt["status"] == "BLOCKED", "MPM launch bracket changed during idle or never advanced")
            continue
        require(ident not in samples, "duplicate MPM launch bracket")
        samples[ident] = delta
    pilots = [{key: sample[key] for key in sample_keys if key in sample} for sample in receipt["pilots"]]
    for pilot, recorded in zip(pilots, receipt["pilots"]):
        require(samples.pop(tuple(pilot.get(key) for key in sample_keys)) == {name: recorded[name] for name in COUNTERS},
                "MPM pilot differs from the raw query return")
    timed = {}
    observed = 0
    for row in rows:
        ident = ("pair", row["operator"], row["n"], None, row["pair"], row["route"])
        delta = samples.pop(ident, None)
        require(row["device_counts"] == delta, "paired device counters differ from the raw query return")
        if delta is not None:
            observed += 1
            require(delta["cycles"] * 1000 <= (row["execute_wait_ns"] + 5000) * clock_mhz,
                    "device cycles exceed the host launch window")
            if not row["warmup"]:
                timed.setdefault((row["operator"], row["n"], row["pair"]), {})[row["route"]] = dict(
                    delta, execute_wait_ns=row["execute_wait_ns"])
    require(not samples and observed == receipt["paired_launches"], "orphan or missing MPM launch evidence")
    result = dict(status=receipt["status"], probe_launches=len(pilots), paired_launches=observed,
                  raw_reads=len(query_rows), raw_sha256=digest(raw))
    if receipt["status"] != "PASS":
        require(receipt["status"] == "BLOCKED", "counter capture did not reach a terminal state")
        return dict(result, reason=receipt["reason"])
    require(len(pilots) == 2 and observed == len(rows) and len(timed) * 2 == sum(not row["warmup"] for row in rows),
            "incomplete per-launch device counts")
    totals = {}
    keys = (*COUNTERS, "execute_wait_ns")
    for (op, n), group in groupby(timed, key=lambda item: item[:2]):
        pairs = [timed[item] for item in group]
        totals["{}/{}".format(op, n)] = dict(pairs=len(pairs),
            medians={route: {key: statistics.median(p[route][key] for p in pairs) for key in keys} for route in ROUTES},
            median_merged_minus_aligned={key: statistics.median(p["merged"][key] - p["aligned"][key] for p in pairs) for key in keys})
    return dict(result, workloads=totals)


def review_returned(preparation, remote, run, results):
    require(remote.get("archive_sha256") == preparation["archive_sha256"], "board input archive identity differs")
    summary_path = run / "summary.json"
    summary = document(summary_path) if summary_path.is_file() else {}
    gate_path = run / "binding/sessions" / run.name / "gate.json"
    gate = document(gate_path) if gate_path.is_file() else {}
    progress = dict(open_gate=gate.get("open_gate", "NOT_RUN"), cp_dev_caps=gate.get("cp_dev_caps"),
                    vm_query=gate.get("vm_query"), close_gate=gate.get("close_gate", "NOT_RUN"),
                    gate_error=gate.get("error"), probe_readbacks=len(list(run.glob("probe/*/*/*/params.bin"))),
                    samples_recorded=len((run / "samples.jsonl").read_bytes().splitlines()) if (run / "samples.jsonl").is_file() else 0)
    counter_path = run / "counter-status.json"
    counters = preparation.get("counters", False)
    if counters:
        progress["counters"] = document(counter_path) if counter_path.is_file() else dict(status="NOT_RUN")
    if remote["status"] != "PASS":
        return dict(progress=progress, stopped_reason=gate.get("error") or summary.get("error") or remote.get("error"))
    require(summary["status"] == summary["board_execution"] == "PASS" and summary["bdf"] == preparation["bdf"] and
            summary["exit_code"] == remote["worker_exit_code"] == 0, "board worker receipt differs")
    for command in summary["commands"]:
        require(command["returncode"] == 0 and not command["timed_out"] and
                command["log_sha256"] == sha256(run / command["log"]), "returned worker command failed or log differs")
    bundle = results / preparation["kit"] / "bundle"
    plan, manifests, _ = preflight(bundle, results / preparation["compiled"])
    probe_count = review_probes(run, bundle, plan, manifests, gate)
    samples = review_samples(run, bundle, plan, counters=counters)
    capture = document(run / "capture.json")
    require(capture == dict(launches=samples["launches"], samples_sha256=samples["samples_sha256"],
                            median_merged_minus_aligned_ns=samples["median_merged_minus_aligned_ns"],
                            alignment_sha256=sha256(run / "alignment.json"), gate_sha256=review_gate(run)) and
            sha256(run / "capture.json") == summary["capture_sha256"] and samples["launches"] == preparation["expected_cases"],
            "capture summary differs from raw evidence")
    if counters:
        samples["device_counts"] = review_counters(run, progress["counters"], clock_mhz=int(gate["clock_readback"]["freq_mhz"]))
    return dict(progress=progress, receipt=dict(samples, staging_launches=probe_count))
