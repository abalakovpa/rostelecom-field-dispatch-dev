#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "${1:-}" == '--install-docker' ]]; then
  [[ $EUID -eq 0 ]] || { echo 'Use sudo for --install-docker' >&2; exit 1; }
  . /etc/os-release
  [[ "$ID" == ubuntu && ( "$VERSION_ID" == 24.04 || "$VERSION_ID" == 26.04 ) ]] || {
    echo 'Automatic installation supports Ubuntu 24.04 and 26.04 only.' >&2; exit 1;
  }
  apt-get update
  apt-get install -y docker.io docker-compose-v2
  systemctl enable --now docker
elif [[ $# -gt 0 ]]; then
  echo 'Usage: bash scripts/deploy.sh [--install-docker]' >&2
  exit 1
fi
command -v docker >/dev/null || {
  echo 'Install Docker Engine and Compose v2, or use --install-docker on Ubuntu 24.04 or 26.04.' >&2
  exit 1
}
docker compose version >/dev/null
docker info >/dev/null
if [[ ! -f .env ]]; then
  password="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  (umask 077; printf 'POSTGRES_PASSWORD=%s\nDB_PORT=5432\nAPI_PORT=8080\nLOG_LEVEL=info\n' "$password" > .env)
  unset password
  echo 'Created .env with a random database password.'
fi
chmod 600 .env
if grep -q 'CHANGE_ME' .env; then
  echo 'Replace CHANGE_ME in .env before deployment.' >&2
  exit 1
fi
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
echo 'API: http://127.0.0.1:8080/api/v1/health (default port). Database credentials: .env'
echo 'No existing volumes or applications were deleted.'
