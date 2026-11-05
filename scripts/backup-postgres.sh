#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  # The project .env is trusted operator configuration; do not export its secrets to child tools.
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
fi

: "${BACKUP_DIR:="$PROJECT_DIR/backups"}"
: "${OFFSITE_BACKUP_DIR:?Set OFFSITE_BACKUP_DIR to a mounted off-host backup location}"
: "${AGE_RECIPIENT:?Set AGE_RECIPIENT to the age public recipient}"

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
command -v age >/dev/null || { echo "age is required" >&2; exit 1; }
command -v realpath >/dev/null || { echo "realpath is required" >&2; exit 1; }

mkdir -p -- "$BACKUP_DIR" "$OFFSITE_BACKUP_DIR"
local_dir="$(realpath -- "$BACKUP_DIR")"
offsite_dir="$(realpath -- "$OFFSITE_BACKUP_DIR")"
if [[ "$local_dir" == "$offsite_dir" ]]; then
  echo "BACKUP_DIR and OFFSITE_BACKUP_DIR must be different directories" >&2
  exit 1
fi

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
backup_name="mes-${timestamp}.dump"
local_final="$local_dir/$backup_name"
offsite_final="$offsite_dir/$backup_name.age"
local_tmp="$(mktemp "$local_dir/.mes-${timestamp}.XXXXXX")"
offsite_tmp="$(mktemp "$offsite_dir/.mes-${timestamp}.XXXXXX")"
cleanup() {
  rm -f -- "$local_tmp" "$offsite_tmp"
}
trap cleanup EXIT
chmod 600 "$local_tmp" "$offsite_tmp"

docker compose exec -T db sh -ec \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host=127.0.0.1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' \
  >"$local_tmp"
test -s "$local_tmp"
age --encrypt --recipient "$AGE_RECIPIENT" --output "$offsite_tmp" "$local_tmp"
test -s "$offsite_tmp"
mv -- "$local_tmp" "$local_final"
mv -- "$offsite_tmp" "$offsite_final"

find "$local_dir" -maxdepth 1 -type f -name 'mes-*.dump' -mtime +14 -delete
find "$offsite_dir" -maxdepth 1 -type f -name 'mes-*.dump.age' -mtime +14 -delete

echo "Backup complete: $local_final"
echo "Encrypted off-host copy complete: $offsite_final"
