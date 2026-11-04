#!/bin/sh
# Резервная копия БД на хосте: ./scripts/backup.sh  → backups/seismo_ДАТА.dump
set -e
cd "$(dirname "$0")/.."
f="backups/seismo_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$f"
echo "Готово: $f"
