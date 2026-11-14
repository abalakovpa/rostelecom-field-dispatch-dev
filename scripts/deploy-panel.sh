#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ ! -f .env ]]; then echo 'Run scripts/deploy.sh first.' >&2; exit 1; fi
if ! grep -q '^PANEL_PASSWORD=' .env; then
  secret="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  printf '\nPANEL_PASSWORD=%s\n' "$secret" >> .env
  unset secret
fi
chmod 600 .env
docker compose --profile panel up --build -d --wait --wait-timeout 180
echo 'Panel: http://SERVER_IP:8082/ ; username: admin'
echo 'Password is PANEL_PASSWORD in .env. Use HTTPS before handling real data.'
