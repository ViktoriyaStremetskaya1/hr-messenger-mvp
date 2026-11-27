#!/usr/bin/env bash
# Восстановление базы из резервной копии (ЗАМЕНЯЕТ текущие данные).
#   bash /opt/hr-messenger/scripts/restore.sh /opt/hr-messenger/backups/hr-2026-01-31_033000.sql.gz
#
# В .env должны быть те же PHONE_ENC_KEYS и PHONE_HASH_KEY, что и на момент копии,
# иначе телефоны кандидатов не расшифруются.
set -euo pipefail
cd "$(dirname "$0")/.."

file=${1:-}
if [ -z "$file" ] || [ ! -f "$file" ]; then
  echo "Укажите файл копии. Доступные копии:" >&2
  ls -1t backups/hr-*.sql.gz 2>/dev/null >&2 || echo "  (нет)" >&2
  exit 1
fi
gzip -t "$file"

if [ -t 0 ]; then
  read -r -p "Текущие данные будут заменены данными из $(basename "$file"). Продолжить? [д/Н]: " answer
  case "$answer" in [ДдYy]*) ;; *) echo "Отменено."; exit 1 ;; esac
fi

profile=sandbox
grep -qE '^DOMAIN=.+' .env && profile=prod

echo "Сохраняю текущее состояние на всякий случай..."
bash scripts/backup.sh

echo "Останавливаю приложение..."
docker compose --profile "$profile" stop api worker
docker compose up -d db
until docker compose exec -T db pg_isready -U hr >/dev/null 2>&1; do sleep 1; done

echo "Восстанавливаю..."
gunzip -c "$file" | docker compose exec -T db psql -U hr -d hr -v ON_ERROR_STOP=1 -q >/dev/null

echo "Запускаю приложение..."
docker compose --profile "$profile" up -d
echo "Готово."
