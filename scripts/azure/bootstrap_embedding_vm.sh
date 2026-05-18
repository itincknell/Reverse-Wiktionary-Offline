#!/usr/bin/env bash
set -euo pipefail

# One-time package bootstrap for the offline embedding VM.
#
# This script is intended to run through Azure VM Run Command before invoking
# the embedding job. It installs system tools only; Python project dependencies
# are installed by the remote job after it extracts the repo archive.

export DEBIAN_FRONTEND=noninteractive

while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 ||
  fuser /var/lib/dpkg/lock >/dev/null 2>&1 ||
  fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
  echo "waiting for apt/dpkg lock..."
  sleep 10
done

dpkg --configure -a

apt-get update

apt-get install -y \
  ca-certificates \
  curl \
  gzip \
  jq \
  python-is-python3 \
  python3-pip \
  python3-venv

if ! command -v az >/dev/null 2>&1; then
  curl -sL https://aka.ms/InstallAzureCLIDeb | bash
fi

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

python -m pip install --upgrade pip

systemctl enable docker
systemctl start docker

if id azureuser >/dev/null 2>&1; then
  usermod -aG docker azureuser
fi

az version
docker --version
docker compose version
python --version
