"""Extract D10 clock/methodology evidence without waiving hardware warnings."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "results/u280-archive-20261109-v5"


def rule_table(text):
    # Do not split at "2. REPORT DETAILS": it first occurs in the TOC.
    rows = [dict(rule=a, severity=b, description=c.strip(), count=int(d)) for a, b, c, d in re.findall(
        r"(?m)^\|\s*([A-Z]+-\d+)\s*\|\s*(Critical Warning|Warning|Advisory|Error)\s*\|([^|]+)\|\s*(\d+)\s*\|", text)]
    declared = re.search(r"Violations found:\s*(\d+)", text)
    if (not rows or not declared or len({r["rule"] for r in rows}) != len(rows) or
            sum(r["count"] for r in rows) != int(declared[1])):
        raise ValueError("missing/duplicate/inconsistent rule table")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", args.run_id):
        parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    archive = json.loads((ARCHIVE / "probe.json").read_text())
    # Reports were individually verified by the D11 decompression manifest.
    report_index = archive["report_inventory"]
    result = dict(schema_version="u280-timing-review-v1", argv=sys.argv, status="RUNNING",
        scope="archived report extraction and metadata consistency only", inputs={},
        board_readiness="BLOCKED", board_clock_observation="NOT_RUN", board_execution="NOT_RUN")
    names = {
        "methodology": "reports/link/imp/impl_1_hw_bb_locked_methodology_drc_routed.rpt",
        "timing": "reports/link/imp/impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt",
        "topology": "inspection/clock_freq_topology.json",
        "embedded": "inspection/embedded_metadata.xml",
        "drc": "reports/link/imp/impl_1_hw_bb_locked_drc_routed.rpt",
    }
    try:
        texts = {}
        for key, name in names.items():
            raw = (ARCHIVE / "returned" / name).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if name in archive["files"]:
                expected = archive["files"][name]
            else:
                expected = next(item for item in report_index if item["path"] == name[len("reports/"):])
            if digest != expected["sha256"] or len(raw) != expected["bytes"]:
                raise ValueError("archived input changed: " + name)
            result["inputs"][key] = dict(path=str((ARCHIVE / "returned" / name).relative_to(ROOT)),
                sha256=digest, bytes=len(raw))
            texts[key] = raw.decode("utf-8")
        parts = re.split(r"(?m)^(TIMING-\d+#\d+) Critical Warning\s*\n", texts["methodology"])
        critical = []
        for index in range(1, len(parts), 2):
            detail = parts[index + 1].split("Related violations:", 1)[0].strip()
            critical.append(dict(id=parts[index], detail=detail, disposition="OPEN",
                inferred_scope="platform scalable clock" if parts[index].startswith("TIMING-1#") else "platform PCIe/debug clock hierarchy",
                inference_basis="named cells/clocks in the archived report; not a vendor waiver"))
        counts = dict(collections.Counter(item["id"].split("#")[0] for item in critical))
        if counts != {"TIMING-1": 1, "TIMING-7": 1, "TIMING-14": 1, "TIMING-54": 6}:
            raise ValueError("unexpected critical warning inventory")
        methodology_rules, drc_rules = rule_table(texts["methodology"]), rule_table(texts["drc"])
        if {r["rule"]: r["count"] for r in methodology_rules if r["severity"] == "Critical Warning"} != counts:
            raise ValueError("critical summary and detail disagree")
        if any(r["severity"] in ("Error", "Critical Warning") for r in drc_rules):
            raise ValueError("ordinary DRC contains severe violations")
        clocks = json.loads(texts["topology"])["clock_freq_topology"]["m_clock_freq"]
        data_clock = [c for c in clocks if c["m_type"] == "DATA"]
        if len(data_clock) != 1 or data_clock[0]["m_freq_Mhz"] != "200":
            raise ValueError("200 MHz DATA clock required")
        mapped = [c.attrib for c in ET.fromstring(texts["embedded"]).findall(".//kernelClocks/clock")
                  if c.attrib["port"] == "DATA_CLK"]
        if mapped != [dict(port="DATA_CLK", frequency="200.0MHz", name="ulp_ucs/aclk_kernel_00")]:
            raise ValueError("unexpected kernel clock mapping")
        missing = {}
        for kind in ("no_input_delay", "no_output_delay", "unconstrained_internal_endpoints"):
            matches = set(re.findall(r"checking " + kind + r" \((\d+)\)", texts["timing"]))
            if len(matches) != 1:
                raise ValueError("ambiguous timing coverage")
            missing[kind] = int(matches.pop())
        if missing != dict(no_input_delay=7, no_output_delay=3, unconstrained_internal_endpoints=0):
            raise ValueError("unexpected boundary timing coverage")
        result.update(status="PASS", critical_warnings=critical, counts=counts, timing_coverage=missing,
            methodology_rules=methodology_rules, drc_rules=drc_rules,
            supersedes="D11 closeout empty rule arrays/zero methodology_critical_count were a TOC-split parser defect, not zero warnings; original retained.",
            clocks=clocks, data_clock_mapping=mapped,
            missing_delay_named_in_methodology="io_perst_n_00[0]",
            next_checks=[
                "Inspect implemented DCP for all 10 missing-delay port names and shell baseline/constraint provenance.",
                "Review TIMING-7 clock relationship and six TIMING-54 exceptions against the exact platform baseline.",
                "Review TIMING-14 platform BSCAN clock LUT; hierarchy alone does not waive the warning.",
                "After HOST readiness and controlled load, compare loaded UUID and actual clock with DATA_CLK=200 MHz before native execution.",
            ],
            official_references=[
                "https://docs.amd.com/r/2023.1-English/ug1393-vitis-application-acceleration/Identifying-Platform-Clocks",
                "https://xilinx.github.io/XRT/2022.1/html/debug-faq.html#incorrect-frequency-scaling",
                "https://xilinx.github.io/XRT/2022.1/html/hm.html",
            ])
    except Exception as exc:
        result.update(status="FAIL", error=repr(exc))
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    (output / "review_u280_timing.py").write_bytes(Path(__file__).read_bytes())
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(status=result["status"], error=result.get("error"), board_readiness=result["board_readiness"])))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
