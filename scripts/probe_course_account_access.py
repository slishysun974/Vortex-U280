"""Compare documented EDA/U280 SSH endpoints via default and existing WLAN transport."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import struct
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--interface-index", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        def probe(spec):
            host, transport = spec
            result = dict(host=host, port=22, transport=transport, tcp="NOT_RUN", ssh_banner="NOT_RUN",
                          authentication="NOT_RUN", timeout_seconds=5)
            before = time.monotonic()
            stage = "setup"
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                try:
                    connection.settimeout(5)
                    if transport == "WLAN":
                        connection.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", args.interface_index))
                        connection.bind((args.source, 0))
                    stage = "tcp_connect"
                    connection.connect((host, 22))
                    result["tcp"] = "PASS"
                    stage = "ssh_banner"
                    banner = connection.recv(256).decode("ascii", "replace").strip()
                    result.update(ssh_banner="PASS" if banner.startswith("SSH-") else "FAIL", banner=banner)
                except OSError as error:
                    if stage == "tcp_connect":
                        result["tcp"] = "FAIL"
                    elif stage == "ssh_banner":
                        result["ssh_banner"] = "FAIL"
                    result.update(error_stage=stage, error_type=type(error).__name__, error=str(error))
            result["elapsed_seconds"] = round(time.monotonic() - before, 3)
            return result
        specs = [(host, route) for host in ("192.0.2.28", "192.0.2.28") for route in ("default", "WLAN")]
        with ThreadPoolExecutor(max_workers=4) as pool:
            probes = list(pool.map(probe, specs))
        ready = any(p["host"] == "192.0.2.28" and p["ssh_banner"] == "PASS" for p in probes)
        result = dict(schema_version="course-account-network-v1", collected_at=datetime.now(timezone.utc).isoformat(),
                      argv=sys.argv, candidate_username="u280user", source=args.source, interface_index=args.interface_index,
                      scope="transport only; no credential sent, no login, no remote command or device query",
                      u280_authentication="NOT_RUN", u280_network="PASS" if ready else "FAIL",
                      u280_access="NOT_RUN" if ready else "BLOCKED", probes=probes, exit_code=0 if ready else 1)
        destination.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
