"""One bounded TCP check of the documented U280 SSH endpoint; no authentication."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        result = dict(schema_version="u280-tcp-probe-v1", endpoint="192.0.2.28",
                      port=22, timeout_seconds=5, started_at=datetime.now(timezone.utc).isoformat(),
                      argv=sys.argv, scope="TCP connection only; no SSH authentication or device query",
                      login="NOT_RUN", board="NOT_RUN")
        started = time.monotonic()
        try:
            with socket.create_connection((result["endpoint"], result["port"]), timeout=5):
                result.update(tcp="PASS", exit_code=0)
        except OSError as error:
            result.update(tcp="FAIL", exit_code=1, error_type=type(error).__name__,
                          error=str(error), errno=error.errno)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        destination.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
