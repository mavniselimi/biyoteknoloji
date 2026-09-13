#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "${script_dir}/../.." && pwd)"
compose_file="${script_dir}/docker-compose.yml"
env_file="${script_dir}/.env"
secrets_dir="${repo_dir}/deploy/secrets"
credentials_dir="${repo_dir}/.deploy-out/aws"
project_name="pgx_aws"

usage() {
  printf '%s\n' \
    "Usage: $0 init|check|deploy|bootstrap|status|logs|restart|stop" \
    "" \
    "  init       create deploy/aws/.env and random database secrets" \
    "  check      validate configuration without starting containers" \
    "  deploy     build, migrate once, and start app + HTTPS proxy" \
    "  bootstrap  create the named DEMO_USER and a local credential file" \
    "  status     show containers and probe public liveness" \
    "  logs       follow app/proxy logs" \
    "  restart    restart app/proxy without touching the database volume" \
    "  stop       stop containers; preserves all named volumes"
}

compose() {
  # Local Compose implements file-backed secrets as bind mounts. Preserve a
  # restrictive 0640 mode and grant the unprivileged application process the
  # host user's primary group so it can read only the database URL secret.
  PGX_SECRET_GID="$(id -g)" docker compose \
    --env-file "${env_file}" \
    --project-name "${project_name}" \
    --file "${compose_file}" \
    "$@"
}

prepare_secret_permissions() {
  local database_url_file="${secrets_dir}/database_url"
  [[ -f "${database_url_file}" ]] || return 0
  chgrp "$(id -g)" "${database_url_file}"
  chmod 640 "${database_url_file}"
}

read_env_value() {
  local wanted="$1"
  local key value
  while IFS='=' read -r key value; do
    if [[ "${key}" == "${wanted}" ]]; then
      printf '%s' "${value}"
      return 0
    fi
  done < "${env_file}"
  return 1
}

require_tools() {
  command -v docker >/dev/null 2>&1 || {
    printf '%s\n' "ERROR: docker is not installed." >&2
    return 1
  }
  docker compose version >/dev/null 2>&1 || {
    printf '%s\n' "ERROR: Docker Compose v2 is not available." >&2
    return 1
  }
  docker info >/dev/null 2>&1 || {
    printf '%s\n' "ERROR: the Docker daemon is not reachable by this user." >&2
    return 1
  }
}

is_ipv4() {
  local address="$1"
  local first second third fourth octet
  [[ "${address}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS='.' read -r first second third fourth <<< "${address}"
  for octet in "${first}" "${second}" "${third}" "${fourth}"; do
    [[ "${octet}" == "0" || "${octet}" != 0* ]] || return 1
    ((10#${octet} <= 255)) || return 1
  done
}

is_dns_name() {
  local address="$1"
  [[ "${address}" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]
}

require_configuration() {
  [[ -f "${env_file}" ]] || {
    printf '%s\n' \
      "ERROR: ${env_file} is missing." \
      "Run '$0 init', then set DOMAIN to the static IP or DNS name." >&2
    return 1
  }

  local domain
  domain="$(read_env_value DOMAIN || true)"
  if ! is_ipv4 "${domain}" && ! is_dns_name "${domain}"; then
    printf '%s\n' \
      "ERROR: DOMAIN must be a public IPv4 address or DNS hostname." \
      "Do not include https://, a port, or a path." >&2
    return 1
  fi
  if [[ "${domain}" == "pgx.example.com" \
      || "${domain}" == "203.0.113.10" ]]; then
    printf '%s\n' \
      "ERROR: replace the example DOMAIN with the Lightsail static IP or DNS name." >&2
    return 1
  fi

  local secret_name
  for secret_name in database_url postgres_user postgres_password; do
    if [[ ! -s "${secrets_dir}/${secret_name}" ]]; then
      printf 'ERROR: missing secret file: %s\n' \
        "${secrets_dir}/${secret_name}" >&2
      return 1
    fi
  done
}

prepare_runtime_inputs() {
  local input_path
  for input_path in \
    "${repo_dir}/data/releases" \
    "${repo_dir}/data/candidate-rulesets"; do
    [[ -d "${input_path}" ]] || {
      printf 'ERROR: missing runtime input directory: %s\n' \
        "${input_path}" >&2
      return 1
    }
    # The application runs as UID 10001.  Git does not preserve directory
    # read/traverse modes, so make these non-secret, published candidate
    # inputs readable through their read-only container mounts.
    chmod -R o+rX "${input_path}"
  done

  input_path="${repo_dir}/data/canonical/dataset-quality-decisions.ndjson"
  [[ -f "${input_path}" ]] || {
    printf 'ERROR: missing runtime input file: %s\n' "${input_path}" >&2
    return 1
  }
  chmod o+r "${input_path}"
}

require_runtime_inputs() {
  local input_path unreadable
  for input_path in \
    "${repo_dir}/data/releases" \
    "${repo_dir}/data/candidate-rulesets"; do
    [[ -d "${input_path}" ]] || {
      printf 'ERROR: missing runtime input directory: %s\n' \
        "${input_path}" >&2
      return 1
    }
    unreadable="$(find "${input_path}" \
      \( -type d ! -perm -001 -o -type f ! -perm -004 \) \
      -print -quit)"
    if [[ -n "${unreadable}" ]]; then
      printf '%s\n' \
        "ERROR: runtime input is not readable by the container: ${unreadable}" \
        "Run '$0 init' to prepare its host permissions." >&2
      return 1
    fi
  done

  input_path="${repo_dir}/data/canonical/dataset-quality-decisions.ndjson"
  if [[ ! -f "${input_path}" ]] \
      || [[ -n "$(find "${input_path}" ! -perm -004 -print -quit)" ]]; then
    printf '%s\n' \
      "ERROR: runtime input is missing or unreadable: ${input_path}" \
      "Run '$0 init' to prepare its host permissions." >&2
    return 1
  fi
}

init() {
  umask 077
  mkdir -p "${secrets_dir}" "${credentials_dir}"
  prepare_runtime_inputs
  if [[ ! -f "${env_file}" ]]; then
    cp "${script_dir}/.env.example" "${env_file}"
    printf 'Created %s; set DOMAIN to the static IP or DNS name.\n' \
      "${env_file}"
  else
    printf 'Kept existing %s.\n' "${env_file}"
  fi

  if [[ -e "${secrets_dir}/postgres_user" \
      || -e "${secrets_dir}/postgres_password" \
      || -e "${secrets_dir}/database_url" ]]; then
    prepare_secret_permissions
    printf '%s\n' \
      "Kept existing database secret files; init never overwrites them." \
      "Prepared the database URL for the container's restricted host group."
    return 0
  fi

  command -v openssl >/dev/null 2>&1 || {
    printf '%s\n' "ERROR: openssl is required to generate a password." >&2
    return 1
  }
  local database_user="pgx_app"
  local database_password
  database_password="$(openssl rand -hex 32)"
  printf '%s' "${database_user}" > "${secrets_dir}/postgres_user"
  printf '%s' "${database_password}" > "${secrets_dir}/postgres_password"
  printf '%s' \
    "postgresql+psycopg://${database_user}:${database_password}@postgres:5432/pgx_production" \
    > "${secrets_dir}/database_url"
  chmod 600 "${secrets_dir}/postgres_user" \
    "${secrets_dir}/postgres_password"
  prepare_secret_permissions
  printf '%s\n' \
    "Created random database credentials." \
    "PostgreSQL inputs use 0600; the app DSN uses restricted group-read 0640."
}

check() {
  require_tools
  require_configuration
  prepare_secret_permissions
  require_runtime_inputs
  compose config --quiet
  printf '%s\n' "AWS Compose configuration is valid."
}

deploy() {
  check
  mkdir -p "${credentials_dir}"
  compose build app
  compose up --detach postgres
  # The deployment command reads DATABASE_URL_FILE inside the container,
  # prints only the redacted target, then invokes Alembic with the DSN in the
  # child environment rather than exposing it on a command line.
  compose --profile ops run --rm ops python -m pgx.application.deploy_cli \
    --root /app migrate
  compose up --detach app proxy
  printf '%s\n' \
    "Deployment started. Caddy will obtain the certificate automatically." \
    "Run '$0 status' to verify public liveness."
}

bootstrap() {
  require_tools
  require_configuration
  mkdir -p "${credentials_dir}"
  chmod 700 "${credentials_dir}"
  local demo_user
  demo_user="$(read_env_value PGX_DEMO_USER || true)"
  demo_user="${demo_user:-demo}"
  if [[ ! "${demo_user}" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
    printf '%s\n' "ERROR: PGX_DEMO_USER contains unsupported characters." >&2
    return 1
  fi
  local local_uid local_gid
  local_uid="$(id -u)"
  local_gid="$(id -g)"
  compose --profile ops run --rm \
    --user "${local_uid}:${local_gid}" \
    ops python /app/bootstrap_demo_environment.py setup \
    --user "${demo_user}:DEMO_USER" \
    --credentials-out /run/pgx-credentials/demo-credentials.txt
  printf 'Credentials: %s\n' \
    "${credentials_dir}/demo-credentials.txt"
}

status() {
  require_tools
  require_configuration
  compose ps
  local domain
  domain="$(read_env_value DOMAIN)"
  if command -v curl >/dev/null 2>&1; then
    printf '\nPublic liveness (%s):\n' "https://${domain}/health/live"
    curl --fail --show-error --silent \
      --connect-timeout 10 --max-time 20 \
      "https://${domain}/health/live"
    printf '\n'
  fi
}

command_name="${1:-}"
case "${command_name}" in
  init)
    init
    ;;
  check)
    check
    ;;
  deploy)
    deploy
    ;;
  bootstrap)
    bootstrap
    ;;
  status)
    status
    ;;
  logs)
    require_tools
    require_configuration
    compose logs --follow --tail 200 app proxy
    ;;
  restart)
    require_tools
    require_configuration
    compose restart app proxy
    ;;
  stop)
    require_tools
    require_configuration
    compose down
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
