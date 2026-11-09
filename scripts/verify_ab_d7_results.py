"""Verify D7 component synthesis and read-only card evidence, not board acceptance."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--probe", required=True)
    args = parser.parse_args()
    for value in vars(args).values():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
            parser.error("unsafe run id")
    output = ROOT / "results" / args.run_id
    output.mkdir(exist_ok=False)
    run = ROOT / "results" / args.probe
    checks, cards = [], []

    def check(name, ok):
        checks.append(dict(name=name, status="PASS" if ok else "FAIL"))

    try:
        p = read_json(run / "probe.json")
        prep = read_json(run / "preparation.json")
        bundle = read_json(run / "bundle.json")
        transport = read_json(run / "transport.json")
        check("transport and synthesis exit", transport["status"] == p["status"] == "PASS"
              and transport["exit_code"] == transport["ssh_exit_code"] == 0)
        check("identity", p["username"] == "u280user" and p["nonce"] == prep["nonce"] == bundle["nonce"]
              and p["run_id"] == args.probe)
        for name, field in (("payload.py", "payload_sha256"), ("bundle.json", "bundle_sha256"),
                            ("u280_remote_probe.py", "remote_probe_sha256")):
            check("input " + name, digest(run / name) == prep[field])
        check("executed remote code identity", p["remote_probe_sha256"] == prep["remote_probe_sha256"])
        check("raw output", digest(run / "probe.stdout") == p["raw_stdout_sha256"])
        raw = (run / "probe.stdout").read_bytes()
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        framed = json.loads(text.split("U280_PROBE_BEGIN_" + prep["nonce"])[1]
                           .split("U280_PROBE_END_" + prep["nonce"])[0])
        check("raw result agrees", all(framed[k] == p[k] for k in p if k not in ("files", "raw_stdout_sha256")))
        lock = read_json(run / "target_lock.json")
        manifest_path = ROOT / lock["evidence"] / "source_manifest.json"
        check("frozen manifest", digest(manifest_path) == lock["source_manifest_sha256"])
        manifest = {v["path"]: v["sha256"] for v in read_json(manifest_path)}
        for name, item in bundle["files"].items():
            raw = base64.b64decode(item["base64"], validate=True)
            check("bundled " + name, hashlib.sha256(raw).hexdigest() == item["sha256"] == p["inputs"][name])
            if "source" in item:
                check("pinned source " + name, manifest[item["source"]] == item["sha256"])
        for name, item in p["files"].items():
            check("returned " + name, digest(run / item["local_path"]) == item["sha256"]
                  and (run / item["local_path"]).stat().st_size == item["bytes"])
        commands = {c["label"]: c for c in p["commands"]}
        for label, command in commands.items():
            for stream in ("stdout", "stderr"):
                check(label + " " + stream, digest(run / "returned" / command[stream]) == command[stream + "_sha256"])
            if not label.startswith("holders_"):
                check(label + " command", command["returncode"] == 0 and not command["timed_out"])
        limits = p["build_limits"]
        check("bounded build", len(limits["cpu_affinity"]) <= 2 and limits["vivado_max_threads"] == 2
              and limits["nice_increment"] == 10 and commands["small_synthesis"]["timeout_seconds"] == 300)
        log = (run / "returned/vivado.log").read_text()
        check("actual license checkout", "Got license for feature 'Synthesis' and/or device 'xcu280'" in log
              and "Releasing license: Synthesis" in log and p["license_for_small_synthesis"] == "PASS")
        check("synthesis completed", "U280_SMALL_SYNTH_PASS" in log and "synth_design completed successfully" in log
              and p["small_synthesis"] == "PASS" and (run / "returned/post_synth.dcp").stat().st_size > 0)
        for key in ("board_programming", "board_reset", "device_configuration", "full_vortex_synthesis", "place_route", "board_execution"):
            check("scope " + key, p[key] == "NOT_RUN")
        check("eight physical card reports", len(p["devices"]) == 8)
        for d in p["devices"]:
            bdf = d["bdf"]
            x = read_json(run / "returned" / d["xrt_report"])["devices"][0]
            check(bdf + " report identity", x["device_id"] == bdf)
            idle = True
            for phase in ("before", "after"):
                s = d[phase]
                kds = s["kdsstat"].get("text", "")
                idle = idle and all(re.search(pattern, kds, re.M) for pattern in
                    (r"^contexts:\s*0\s*$", r"^outstanding execs:\s*0\s*$", r"^client pid:\s*$"))
                check(bdf + " " + phase + " ready", s["ready"].get("text", "").strip() == "0x1")
                check(bdf + " " + phase + " host observation", s["host_mem_size"].get("text", "").strip() == "0")
            cus = [cu for dr in x["dynamic_regions"] for cu in dr.get("compute_units", [])]
            idle = bool(idle and cus and all("IDLE" in cu["status"]["bits_set"] for cu in cus))
            check(bdf + " idle snapshot", idle)
            holder = commands["holders_" + bdf.replace(":", "_").replace(".", "_")]
            no_visible = holder["returncode"] == 1 and all(
                (run / "returned" / holder[stream]).stat().st_size == 0 for stream in ("stdout", "stderr"))
            # fuser exit 1 is preserved; it does not prove absence of other users' holders.
            platform = x["platforms"][0]
            cards.append(dict(bdf=bdf, observed_idle_candidate=idle, cu_count=len(cus),
                              no_visible_fuser_output=no_visible, fuser_exit_code=holder["returncode"],
                              reservation="NOT_ACQUIRED", host_mem_size=0,
                              shell=platform["static_region"], controller=platform["controller"]["satellite_controller"],
                              interface_uuid=d["after"]["interface_uuids"]["text"].strip(),
                              xclbin_uuid=d["after"]["xclbinuuid"]["text"].strip()))
        for name, count in (("ab-d7-script-checks-20261108-v1", 76), ("ab-d7-windows-bundle-checks-20261109-v1", 3)):
            directory = ROOT / "results" / name
            check(name, read_json(directory / "result.json")["exit_code"] == 0
                  and "Ran %d tests" % count in (directory / "tests.log").read_text(encoding="utf-8-sig"))
        for name, expected in (("target_lock.json", "924b17abadbbda710ead2053ac0873fb0698161c983f8ff1feb9b96a16a19ffe"),
                               ("target_caps.json", "b48d0e940a27ff53bf0708320067c31b7560c7fc489b9ad52319b1a0adf126ec"),
                               ("native_smoke.json", "046ca59d289390bc1d0424fc35df0d552cc7a2f92c6c649d8c318d284c433b87")):
            check("default unchanged " + name, digest(ROOT / "configs" / name) == expected)
    except Exception as exc:
        checks.append(dict(name="verification exception", status="FAIL", detail=repr(exc)))
    result = dict(schema_version="ab-d7-closeout-v1", status="PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
                  checks=checks, passed=sum(c["status"] == "PASS" for c in checks), total=len(checks), cards=cards,
                  probe_run=args.probe, probe_sha256=digest(run / "probe.json"),
                  scope="Evidence verification; small component synthesis and read-only observations only; no full FPGA or board acceptance",
                  host_memory="NOT_ENABLED", board_ready_for_vortex=False, argv=sys.argv,
                  finished_at=datetime.now(timezone.utc).isoformat())
    result["exit_code"] = 0 if result["status"] == "PASS" else 1
    shutil.copy2(__file__, output / Path(__file__).name)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "passed", "total", "exit_code")}))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
