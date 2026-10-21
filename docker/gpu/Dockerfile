# climbing-coach-gpu
# CUDA 12.8 + cuDNN 9 on Ubuntu 24.04. System Python is 3.12.
# No PyTorch. No MMPose. Those belong in docker/train (Phase 6).
#
# ffmpeg URL and sha256 match .github/workflows/ci.yml.
# Host keys are created at container start, not during the image build.

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:ac55d124da4882b497f732d8dfd9a702d5447a5f29d08d56da6f64f0a1eb34bc

LABEL org.opencontainers.image.source="https://github.com/LittleSadFox/project-9c"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/cc/venv/bin:/usr/local/bin:${PATH}" \
    CC_MODELS_DIR=/workspace/models \
    CC_GOLDEN_DIR=/workspace/videos

# Same pinned static ffmpeg 7 build as CI.
ARG FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/ffmpeg-n7.1.5-12-g1fdbca85aa-linux64-gpl-7.1.tar.xz
ARG FFMPEG_SHA256=c1e6caf48923dd8e6bc5e54d51ba70c321175b8162ae9c414c392990e72f0e79
ARG RUNPODCTL_URL=https://github.com/runpod/runpodctl/releases/download/v3.0.1/runpodctl-linux-amd64
ARG RUNPODCTL_SHA256=b66d11eca8cacbf18a2de6943c6e18a79ffbdc8a3c30aa13a49dc6cfc15d4239

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
        libglib2.0-0 \
        libgomp1 \
        openssh-server \
        python3 \
        python3-pip \
        python3-venv \
        shellcheck \
        tini \
        xz-utils \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/ssh/ssh_host_* \
    && test -z "$(find /etc/ssh -maxdepth 1 -name 'ssh_host_*' -print)" \
    && python3 --version | grep -E 'Python 3\.12\.' \
    && curl -fsSL -o /tmp/ffmpeg.tar.xz "$FFMPEG_URL" \
    && echo "${FFMPEG_SHA256}  /tmp/ffmpeg.tar.xz" | sha256sum -c - \
    && mkdir -p /tmp/ffmpeg \
    && tar -xJf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg \
    && bin_dir="$(find /tmp/ffmpeg -maxdepth 2 -type d -name bin | head -n 1)" \
    && install -m 0755 "${bin_dir}/ffmpeg" /usr/local/bin/ffmpeg \
    && install -m 0755 "${bin_dir}/ffprobe" /usr/local/bin/ffprobe \
    && rm -rf /tmp/ffmpeg /tmp/ffmpeg.tar.xz \
    && ffmpeg -version | head -n 1 | grep -E 'ffmpeg version n?[7-9]\.' \
    && curl -fsSL -o /tmp/runpodctl "$RUNPODCTL_URL" \
    && echo "${RUNPODCTL_SHA256}  /tmp/runpodctl" | sha256sum -c - \
    && install -m 0755 /tmp/runpodctl /usr/local/bin/runpodctl \
    && rm -f /tmp/runpodctl \
    && mkdir -p /var/run/sshd /root/.ssh /opt/cc/bin \
    && printf '%s\n' \
        'Port 22' \
        'PermitRootLogin prohibit-password' \
        'PasswordAuthentication no' \
        'PubkeyAuthentication yes' \
        'KbdInteractiveAuthentication no' \
        'UsePAM no' \
        'X11Forwarding no' \
        > /etc/ssh/sshd_config.d/cc.conf

COPY backend/requirements-gpu.txt backend/requirements-dev.txt backend/requirements-nodeps.txt /opt/cc/pins/

RUN python3 -m venv /opt/cc/venv \
    && /opt/cc/venv/bin/python -m pip install --upgrade 'pip==25.2' \
    && /opt/cc/venv/bin/python -m pip install --no-cache-dir -r /opt/cc/pins/requirements-gpu.txt \
    && /opt/cc/venv/bin/python -m pip install --no-cache-dir -r /opt/cc/pins/requirements-dev.txt \
    && /opt/cc/venv/bin/python -m pip install --no-cache-dir --no-deps -r /opt/cc/pins/requirements-nodeps.txt \
    && /opt/cc/venv/bin/python -c "import onnxruntime; assert onnxruntime.__version__ == '1.23.2', onnxruntime.__version__" \
    && /opt/cc/venv/bin/python -c "import importlib.util, sys; sys.exit(1 if importlib.util.find_spec('torch') or importlib.util.find_spec('mmpose') or importlib.util.find_spec('mmcv') else 0)" \
    && command -v runpodctl \
    && test -x /usr/sbin/sshd \
    && command -v git \
    && command -v curl \
    && command -v jq \
    && command -v shellcheck \
    && command -v tini

COPY docker/gpu/entrypoint.sh /opt/cc/bin/entrypoint.sh
COPY scripts/gpu /opt/cc/scripts/gpu

RUN chmod 0755 /opt/cc/bin/entrypoint.sh /opt/cc/scripts/gpu/*.sh

WORKDIR /opt/cc
EXPOSE 22
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/cc/bin/entrypoint.sh"]
