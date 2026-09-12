#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    "Usage: $0 SECURITY_GROUP_ID [AWS_REGION]" \
    "" \
    "Adds public IPv4 TCP ingress for ports 80 and 443." \
    "It does not change SSH rules."
}

security_group_id="${1:-}"
aws_region="${2:-}"

if [[ ! "${security_group_id}" =~ ^sg-[0-9a-fA-F]+$ ]]; then
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

authorize_port() {
  local port="$1"
  local label="$2"
  local output
  if output="$(aws ec2 authorize-security-group-ingress \
      "${region_args[@]}" \
      --group-id "${security_group_id}" \
      --protocol tcp \
      --port "${port}" \
      --cidr 0.0.0.0/0 2>&1)"; then
    printf 'Opened TCP %s (%s) on %s.\n' \
      "${port}" "${label}" "${security_group_id}"
    return 0
  fi
  if [[ "${output}" == *"InvalidPermission.Duplicate"* ]]; then
    printf 'TCP %s (%s) was already open on %s.\n' \
      "${port}" "${label}" "${security_group_id}"
    return 0
  fi
  printf '%s\n' "${output}" >&2
  return 1
}

authorize_port 80 HTTP
authorize_port 443 HTTPS
