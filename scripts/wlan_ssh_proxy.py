"""Relay OpenSSH over one explicitly selected Windows network interface."""
import argparse
import os
import socket
import struct
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--interface", type=int, required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Winsock IP_UNICAST_IF takes an interface index in network byte order.
        conn.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", args.interface))
        conn.bind((args.source, 0))
        conn.settimeout(10)
        conn.connect((args.host, args.port))
        conn.settimeout(None)

        def upstream():
            try:
                while True:
                    data = os.read(sys.stdin.fileno(), 65536)
                    if not data:
                        break
                    conn.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    conn.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        threading.Thread(target=upstream, daemon=True).start()
        while True:
            data = conn.recv(65536)
            if not data:
                break
            view = memoryview(data)
            while view:
                view = view[os.write(sys.stdout.fileno(), view):]
    except OSError as exc:
        print(f"WLAN SSH transport failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
