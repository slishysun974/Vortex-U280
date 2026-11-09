ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates python3 pkg-config ccache \
    zlib1g-dev libtinfo-dev libncurses-dev uuid-dev \
    libboost-serialization-dev libpng-dev libhwloc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
CMD ["python3", "-B", "scripts/run_native_smoke.py", "--help"]
