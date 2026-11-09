#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--apply" || $# != 1 ]]; then
    echo "Usage: bash setup-host.sh --apply (inside the dedicated Ubuntu 22.04 build host)" >&2
    exit 2
fi

source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 22.04 || "$(uname -m)" != x86_64 ]]; then
    echo "Requires the dedicated Ubuntu 22.04 x86_64 host." >&2
    exit 2
fi
if [[ "$EUID" != 0 ]]; then
    echo "Run as root inside the dedicated host." >&2
    exit 2
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates python3 pkg-config ccache \
    zlib1g-dev libtinfo-dev libncurses-dev uuid-dev \
    libboost-serialization-dev libpng-dev libhwloc-dev

getconf GNU_LIBC_VERSION
g++ --version
cmake --version
