#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker compose --profile panel up --build -d --wait --wait-timeout 180
echo 'Panel: http://SERVER_IP:8082/ ; no application login (trusted network deployment)'
