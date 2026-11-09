"""Verify D13 evidence and compare platform warnings without automatic waivers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from review_u280_timing import rule_table

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def warnings(text):
    parts = re.split(r"(?m)^(TIMING-\d+#\d+) Critical Warning\s*\n", text)
    result = []
    for i in range(1, len(parts), 2):
        detail = parts[i + 1].split("Related violations:", 1)[0].strip()
        normalized = re.sub(r"constraint position \d+", "constraint position <N>", detail)
        result.append(dict(id=parts[i], rule=parts[i].split("#")[0], detail=detail,
                           normalized=" ".join(normalized.split())))
    return result


def clock_groups(text):
    scope = ""
    groups = []
    for line in text.splitlines():
        if line.startswith("current_instance "):
            scope = line
        elif line.startswith("set_clock_groups "):
            groups.append(dict(scope=scope, command=line))
    return groups


def path_summary(text):
    return {key: re.findall(pattern, text, re.M) for key, pattern in dict(
        sources=r"^  Source: +(.+)$", destinations=r"^  Destination: +(.+)$",
        types=r"^  Path Type: +(.+)$", slack=r"^Slack.*$",
        exceptions=r"^  Timing Exception: +(.+)$").items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness-run", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", x) for x in (args.run_id, args.readiness_run)):
        parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    result = dict(schema_version="u280-d13-review-v1", status="RUNNING", argv=sys.argv,
        scope="returned DCP reports, provenance, and frozen input verification; no automatic timing waiver",
        checks=[], board_readiness="BLOCKED", board_load="NOT_RUN", board_execution="NOT_RUN",
        processor_rtl="NOT_RUN", afu_model="NOT_RUN", ptx_device="NOT_RUN")

    def check(name, condition):
        result["checks"].append(dict(check=name, status="PASS" if condition else "FAIL"))
        if not condition:
            raise ValueError(name)

    try:
        run = ROOT / "results" / args.readiness_run
        probe, prep, transport = (read(run / p) for p in ("probe.json", "preparation.json", "transport.json"))
        check("response identity", probe["run_id"] == args.readiness_run and probe["nonce"] == prep["nonce"])
        check("worker identity", probe["remote_probe_sha256"] == prep["remote_probe_sha256"] == sha(run / "u280_remote_readiness.py"))
        check("Tcl identity", prep["tcl_sha256"] == sha(run / "u280_readiness_audit.tcl"))
        check("returned stdout", probe["raw_stdout_sha256"] == sha(run / "probe.stdout"))
        for name, item in probe["files"].items():
            if "local_path" in item:
                path = run / item["local_path"]
                check("returned " + name, sha(path) == item["sha256"] and path.stat().st_size == item["bytes"])
        result["collection"] = dict(status=probe["timing_collection"], commands=probe["commands"],
                                    transport_exit_code=transport["exit_code"])
        check("both DCP commands completed", probe["timing_collection"] == "PASS" and len(probe["commands"]) == 2 and
              all(c["exit_code"] == 0 and not c.get("timed_out") for c in probe["commands"]))
        result["dcps"] = {k: probe[k] for k in ("final_checkpoint", "baseline_checkpoint")}
        reports = {}
        for label in ("implemented", "baseline"):
            directory = run / "returned" / label
            text = (directory / "methodology.rpt").read_text()
            rules = rule_table(text)
            critical = warnings(text)
            check(label + " summary/detail consistency", len(critical) == sum(r["count"] for r in rules if r["severity"] == "Critical Warning"))
            reports[label] = dict(rules=rules, critical_warnings=critical,
                optional_errors=(directory / "optional_errors.txt").read_text(),
                check_timing=(directory / "check_timing.rpt").read_text())
        baseline = {x["normalized"] for x in reports["baseline"]["critical_warnings"]}
        for item in reports["implemented"]["critical_warnings"]:
            item["also_in_platform_baseline"] = item["normalized"] in baseline
            item["disposition"] = "OPEN_REQUIRES_REVIEW"
        result["reports"] = reports
        check("exact nine implemented/eight baseline warnings", len(reports["implemented"]["critical_warnings"]) == 9 and
              len(reports["baseline"]["critical_warnings"]) == 8 and
              sum(x["also_in_platform_baseline"] for x in reports["implemented"]["critical_warnings"]) == 8)
        check("optional queries succeeded", all(not x["optional_errors"].strip() for x in reports.values()))
        details = {}
        for label in ("implemented", "baseline"):
            directory = run / "returned" / label
            objects = (directory / "objects.txt").read_text()
            fanout = objects.split("=== timing14_fanout ===", 1)[1].strip().splitlines()
            rows = [re.split(r" {2,}", line.strip()) for line in (directory / "clock_interaction.rpt").read_text().splitlines()]
            details[label] = dict(
                missing_delay_ports=re.findall(r"(?m)^io_\S+$", reports[label]["check_timing"]),
                timing14_fanout=fanout, clock_groups=clock_groups((directory / "effective.xdc").read_text()),
                timing7={direction: path_summary((directory / ("timing7_" + direction + ".rpt")).read_text())
                         for direction in ("forward", "reverse")},
                unsafe_interactions=[row for row in rows if any("unsafe" in field for field in row)],
                kernel00_interactions=[row for row in rows if row and "clk_kernel_00_unbuffered_net" in row[:2]])
        a, b = details["implemented"], details["baseline"]
        check("ten missing-delay ports match baseline", len(a["missing_delay_ports"]) == 10 and a["missing_delay_ports"] == b["missing_delay_ports"])
        check("BSCAN fanout matches baseline and stays in static partition", a["timing14_fanout"] == b["timing14_fanout"] and
              a["timing14_fanout"][0] == "count=20" and len(a["timing14_fanout"][1:]) == 20 and
              all(x.startswith("level0_i/blp/") for x in a["timing14_fanout"][1:]))
        check("all 12 clock-group commands and scopes preserved", len(a["clock_groups"]) == 12 and a["clock_groups"] == b["clock_groups"])
        check("no kernel00 asynchronous-group interaction reported", bool(a["kernel00_interactions"]) and
              all("Asynchronous Groups" not in row for row in a["kernel00_interactions"]))
        check("TIMING-7 sampled path identities/slacks/exceptions match", a["timing7"] == b["timing7"] and
              len(a["timing7"]["forward"]["sources"]) == 10 and len(a["timing7"]["reverse"]["sources"]) == 9)
        check("one inherited unsafe clock interaction remains", len(a["unsafe_interactions"]) == 1 and a["unsafe_interactions"] == b["unsafe_interactions"] and
              a["unsafe_interactions"][0][:2] == ["io_clk_pcie_00_clk_p", "dma_ip_axi_aclk_1"])
        result["detailed_comparison"] = details
        for item in reports["implemented"]["critical_warnings"]:
            item["tool_warning_remains"] = True
            if item["rule"] == "TIMING-1":
                item["disposition"] = "STATIC_CAUSE_IDENTIFIED_ACTUAL_CLOCK_PENDING"
            elif item["rule"] == "TIMING-7":
                item["disposition"] = "OPEN_PLATFORM_CDC_REVIEW_REQUIRED"
            else:
                item["disposition"] = "REVIEWED_PLATFORM_RETAINED_NOT_WAIVED"
        result["review_conclusion"] = dict(status="COMPLETE_WITH_OPEN_ITEMS", inherited_warning_count=8,
            new_clock_warning_count=1, platform_items_scope_reviewed=7, tool_warnings_eliminated=0,
            timing_blocker="TIMING-7: unchanged platform crossing is still classified Partial False Path (unsafe); baseline identity is not a safety waiver",
            actual_clock_check="TIMING-1: verify loaded UUID and measured 200 MHz before any kernel execution",
            missing_delay="same ten platform ports; internal unconstrained endpoints remain zero; this is not external I/O timing acceptance",
            hardware_action="HOST blocked by sudo policy; no board load or native execution")
        # Preserve the original report and its exact 21-endpoint coverage context.
        archived = ROOT / "results/u280-archive-20261109-v5/returned/reports/link/imp/impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt"
        check("D10 timing report identity", sha(archived) == "c16769502472d936e0b6267f279674e6646e5490ef0dbeec9caf3b7025993e3f")
        text = archived.read_text()
        start = text.index("From Clock:  io_clk_pcie_00_clk_p\n  To Clock:  dma_ip_axi_aclk_1")
        end = text.find("\nPath Group: ", start)
        section = text[start:end if end >= 0 else None]
        result["timing7_archived_paths"] = dict(
            source_report_sha256=sha(archived), report_endpoint_count=21,
            sources=sorted(set(re.findall(r"(?m)^  Source: +(.+)$", section))),
            destinations=sorted(set(re.findall(r"(?m)^  Destination: +(.+)$", section))),
            types=sorted(set(re.findall(r"(?m)^  Path Type: +(.+)$", section))),
            limitation="Reported path samples may not enumerate every endpoint; positive slack is not a clock relationship proof")
        (output / "timing7_archived_section.rpt").write_text(section)
        fixed = read(ROOT / "configs/target_lock.json")
        check("root lock preserved", sha(ROOT / "configs/target_lock.json") == (ROOT / "configs/target_lock.sha256").read_text().split()[0])
        manifest = ROOT / fixed["evidence"] / "source_manifest.json"
        check("source manifest identity", sha(manifest) == fixed["source_manifest_sha256"])
        entries = read(manifest)
        check("3329 fixed source files", len(entries) == 3329 and all(sha(ROOT / "upstream/vortex" / x["path"]) == x["sha256"] for x in entries))
        result["status"] = "PASS"
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    shutil.copy2(__file__, output / Path(__file__).name)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], error=result.get("error"), checks=len(result["checks"]))))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
