#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    "Usage: $0 LIGHTSAIL_INSTANCE_NAME [AWS_REGION]" \
    "" \
    "Opens public IPv4 TCP ingress for ports 80 and 443." \
    "It does not change SSH or any other firewall rule."
}

instance_name="${1:-}"
aws_region="${2:-}"

if [[ ! "${instance_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  usage >&2
  exit 64
fi
command -v aws >/dev/null 2>&1 || {
  printf '%s\n' "ERROR: AWS CLI is not installed." >&2
  exit 1
}

region_args=()
if [[ -n "${aws_region}" ]]; then
  region_args=(--region "${aws_region}")
fi

open_port() {
  local port="$1"
  local label="$2"
  local status
  status="$(aws lightsail open-instance-public-ports \
    "${region_args[@]}" \
    --instance-name "${instance_name}" \
    --port-info \
      "fromPort=${port},toPort=${port},protocol=TCP,cidrs=0.0.0.0/0" \
    --query 'operation.status' \
    --output text)"
  printf 'Opened TCP %s (%s) on Lightsail instance %s: %s\n' \
    "${port}" "${label}" "${instance_name}" "${status}"
}

open_port 80 HTTP
open_port 443 HTTPS
