#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Резервная копия БД PostgreSQL (pg_dump) в каталог backups/.
# Запуск вручную или из cron: 0 3 * * *  /path/to/scripts/backup_db.sh
# Восстановление: gunzip -c backups/<файл>.sql.gz | \
#   docker compose -f docker-compose.prod.yml exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
set -a; source .env; set +a

COMPOSE="docker compose -f docker-compose.prod.yml"
OUT_DIR="backups"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$OUT_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="${OUT_DIR}/lawyer_${STAMP}.sql.gz"

echo "==> Создаю резервную копию: ${FILE}"
$COMPOSE exec -T db pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip > "${FILE}"

echo "==> Удаляю копии старше ${KEEP_DAYS} дней"
find "$OUT_DIR" -name 'lawyer_*.sql.gz' -mtime "+${KEEP_DAYS}" -delete || true

echo "Готово: ${FILE}"
