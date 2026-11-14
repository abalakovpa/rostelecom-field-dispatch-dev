#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "${1:-}" != '--replace-demo-data' ]]; then
  echo 'Usage: bash scripts/update-city-data.sh --replace-demo-data' >&2
  echo 'Replaces reference, matrix and ALL days. Creates a full PostgreSQL backup first.' >&2
  exit 1
fi
umask 077
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%S)-$$"
backup="backups/before-city-update-$stamp.dump"
host_dir="$PWD"
if command -v cygpath >/dev/null 2>&1; then host_dir="$(cygpath -m "$PWD")"; export MSYS_NO_PATHCONV=1; export MSYS2_ARG_CONV_EXCL="*"; fi
payload="$(mktemp)"
resume=()
while IFS= read -r service; do
  case "$service" in api|request-panel) resume+=("$service");; esac
done < <(docker compose --profile panel ps --services --status running)
cleanup() {
  rm -f -- "$payload"
  if (( ${#resume[@]} )); then docker compose --profile panel up -d "${resume[@]}"; fi
}
trap cleanup EXIT
# No new HTTP writes can arrive between the backup and replacement.
if (( ${#resume[@]} )); then docker compose --profile panel stop "${resume[@]}"; fi
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup"
[[ -s "$backup" ]] || { echo 'Backup is empty, aborting.' >&2; exit 1; }
docker compose exec -T db pg_restore --list < "$backup" > /dev/null
docker compose run --rm --no-deps -T -v "$host_dir:/workspace:ro" --entrypoint python planner /workspace/scripts/prepare_reference.py > "$payload"
docker compose run --rm --no-deps -T api node scripts/replace-demo.mjs < "$payload"
echo "Backup saved: $backup"
echo 'Dataset updated atomically. Existing days were cleared; create new test orders in the panel.'
