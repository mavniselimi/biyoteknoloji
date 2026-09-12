#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  printf '%s\n' \
    "Run this once with sudo: sudo ./deploy/aws/install-docker-ubuntu.sh" >&2
  exit 64
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
systemctl enable --now docker

login_user="${SUDO_USER:-}"
if [[ -n "${login_user}" && "${login_user}" != "root" ]]; then
  usermod -aG docker "${login_user}"
  printf '%s\n' \
    "Docker installed. Log out and back in once so ${login_user} gets Docker access."
else
  printf '%s\n' "Docker and Compose installed and started."
fi
