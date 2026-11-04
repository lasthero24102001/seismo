#!/bin/sh
# Восстановление: ./scripts/restore.sh backups/файл.dump   (ПЕРЕЗАПИШЕТ текущие данные)
set -e
[ -f "$1" ] || { echo "Укажите файл .dump"; exit 1; }
cd "$(dirname "$0")/.."
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < "$1"
echo "Восстановлено из $1"
