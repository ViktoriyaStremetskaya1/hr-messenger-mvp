#!/usr/bin/env bash
# Резервная копия базы: pg_dump → gzip в каталог backups/ рядом с проектом.
# Копии старше KEEP_DAYS дней (по умолчанию 14) удаляются.
# Запускается каждый день из cron (/etc/cron.d/hr-messenger-backup), можно запустить и вручную:
#   bash /opt/hr-messenger/scripts/backup.sh
#
# Внимание: в копии телефоны кандидатов зашифрованы. Для восстановления нужны ключи
# PHONE_ENC_KEYS и PHONE_HASH_KEY из .env — храните их отдельно от копий.
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR=${BACKUP_DIR:-$PWD/backups}
KEEP_DAYS=${KEEP_DAYS:-14}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077

name="hr-$(date +%Y-%m-%d_%H%M%S).sql.gz"
part="$BACKUP_DIR/.$name.part"
trap 'rm -f "$part"' EXIT

docker compose exec -T db pg_dump -U hr -d hr --no-owner --clean --if-exists | gzip -9 > "$part"
gzip -t "$part"
mv "$part" "$BACKUP_DIR/$name"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'hr-*.sql.gz' -mmin +$((KEEP_DAYS * 24 * 60)) -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name '.hr-*.part' -mmin +60 -delete

echo "$(date '+%F %T') копия создана: $BACKUP_DIR/$name ($(du -h "$BACKUP_DIR/$name" | cut -f1))"
