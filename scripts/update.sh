#!/usr/bin/env bash
# Обновление приложения до последней версии из репозитория:
#   bash /opt/hr-messenger/scripts/update.sh
#
# Перед обновлением делается резервная копия базы. Миграции базы применяются
# автоматически при запуске api (alembic upgrade head).
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Нет файла .env — сначала выполните установку (scripts/server-setup.sh)." >&2; exit 1; }

profile=sandbox
grep -qE '^DOMAIN=.+' .env && profile=prod
web_port=$(grep -E '^WEB_PORT=' .env | tail -n1 | cut -d= -f2- || true)
web_port=${web_port:-8080}

echo "==> Резервная копия перед обновлением"
if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
  bash scripts/backup.sh
else
  echo "    база не запущена — копию пропускаю"
fi

echo "==> Загрузка новой версии"
before=$(git rev-parse --short HEAD)
git pull --ff-only
after=$(git rev-parse --short HEAD)
if [ "$before" = "$after" ]; then
  echo "    новых изменений нет ($after), пересобираю на всякий случай"
else
  echo "    $before → $after"
  git log --oneline "$before..$after" | sed 's/^/    /'
fi

echo "==> Сборка и перезапуск (профиль $profile)"
docker compose --profile "$profile" up -d --build --remove-orphans

echo "==> Проверка"
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$web_port/api/health" >/dev/null 2>&1; then
    docker image prune -f >/dev/null || true
    echo "    приложение работает, версия $(git log -1 --format='%h %s')"
    exit 0
  fi
  sleep 2
done
docker compose --profile "$profile" logs --tail 60 api >&2 || true
echo "Приложение не ответило за 3 минуты. Логи выше. Резервная копия — в каталоге backups/." >&2
exit 1
