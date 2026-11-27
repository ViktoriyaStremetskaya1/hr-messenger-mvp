#!/usr/bin/env bash
# Установка HR Messenger на чистый сервер Ubuntu 24.04. Запускать от root.
# Скрипт можно запускать повторно: уже сделанные шаги он пропускает, данные не трогает.
#
# Обычный запуск (подробно — docs/DEPLOY.md):
#   apt-get update && apt-get install -y git && \
#   git clone https://<ТОКЕН>@github.com/ViktoriyaStremetskaya1/hr-messenger-mvp.git /opt/hr-messenger && \
#   bash /opt/hr-messenger/scripts/server-setup.sh
#
# Переменные окружения (если не заданы — скрипт спросит):
#   DOMAIN        домен сервера, например hr.example.kz
#   GIT_URL       адрес репозитория (нужен, только если /opt/hr-messenger ещё нет)
#   ADMIN_LOGIN, ADMIN_NAME, ADMIN_PASSWORD — создать администратора без вопросов
#   APP_DIR       каталог установки (по умолчанию /opt/hr-messenger)
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/hr-messenger}
DOMAIN=${DOMAIN:-}
GIT_URL=${GIT_URL:-}
export DEBIAN_FRONTEND=noninteractive

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[0;32m    ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m    ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\n\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

# Терминал для вопросов (работает и при запуске через «curl ... | bash»)
HAS_TTY=false
if { : </dev/tty; } 2>/dev/null; then HAS_TTY=true; fi

ask() { # ask "Вопрос" ПЕРЕМЕННАЯ
  local answer=""
  $HAS_TTY || die "нет терминала для вопроса «$1». Передайте значение через переменную окружения $2."
  read -r -p "    $1: " answer </dev/tty
  printf -v "$2" '%s' "$answer"
}

yes_no() { # yes_no "Вопрос" д|н  → код 0, если «да»
  local answer="" hint="[Д/н]"
  [ "$2" = "н" ] && hint="[д/Н]"
  $HAS_TTY || { [ "$2" = "д" ]; return; }
  read -r -p "    $1 $hint: " answer </dev/tty
  answer=${answer:-$2}
  case "$answer" in [ДдYy]*) return 0 ;; *) return 1 ;; esac
}

env_value() { # значение переменной из .env
  [ -f "$APP_DIR/.env" ] || return 0
  grep -E "^$1=" "$APP_DIR/.env" | tail -n1 | cut -d= -f2- || true
}

valid_domain() {
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$ ]]
}

compose() { docker compose --project-directory "$APP_DIR" --profile prod "$@"; }

# ---------------------------------------------------------------------------
say "Проверка системы"
[ "$(id -u)" -eq 0 ] || die "запустите от root: sudo -i, затем команду ещё раз."
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ]; then
    die "нужен Ubuntu 24.04, а на сервере ${PRETTY_NAME:-неизвестная система}."
  fi
  [ "${VERSION_ID:-}" = "24.04" ] || warn "скрипт проверен на Ubuntu 24.04, у вас ${PRETTY_NAME}. Продолжаю."
fi
ok "система: ${PRETTY_NAME:-Ubuntu}"

# ---------------------------------------------------------------------------
say "Домен"
normalize_domain() {
  local d
  d=$(printf '%s' "$1" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
  d=${d#http://}; d=${d#https://}; d=${d%/}
  printf '%s' "$d"
}
if [ -z "$DOMAIN" ]; then DOMAIN=$(env_value DOMAIN); fi
DOMAIN=$(normalize_domain "$DOMAIN")
while [ -z "$DOMAIN" ] || ! valid_domain "$DOMAIN"; do
  [ -n "$DOMAIN" ] && warn "«$DOMAIN» не похоже на домен. Пример: hr.example.kz (без http:// и без /)"
  ask "Домен сервера (например hr.example.kz)" DOMAIN
  DOMAIN=$(normalize_domain "$DOMAIN")
done
ok "домен: $DOMAIN"

# ---------------------------------------------------------------------------
say "Установка пакетов (Docker, Git, файрвол)"
apt-get update -q
if ! apt-cache policy docker-compose-v2 | grep -q 'Candidate: [0-9]'; then
  warn "пакет docker-compose-v2 не найден — включаю репозиторий universe"
  apt-get install -y -q software-properties-common
  add-apt-repository -y universe
  apt-get update -q
fi
apt-get install -y -q docker.io docker-compose-v2 git ufw curl ca-certificates python3 cron gzip
systemctl enable --now docker >/dev/null
systemctl enable --now cron >/dev/null
docker compose version >/dev/null || die "docker compose не запускается"
ok "$(docker --version)"

# ---------------------------------------------------------------------------
say "Файрвол: открыты только SSH, 80 и 443"
ufw allow OpenSSH >/dev/null
# Если SSH работает на нестандартном порту, открываем и его — иначе можно потерять доступ к серверу.
for port in $(sshd -T 2>/dev/null | awk '$1 == "port" {print $2}'); do
  ufw allow "$port/tcp" >/dev/null
done
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
ok "ufw включён"

# ---------------------------------------------------------------------------
say "Код приложения в $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
  if git -C "$APP_DIR" pull --ff-only -q; then
    ok "обновлено до $(git -C "$APP_DIR" log -1 --format='%h %s')"
  else
    warn "не удалось обновить код (git pull). Продолжаю с текущей версией."
  fi
else
  if [ -e "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
    die "каталог $APP_DIR существует, но это не git-репозиторий. Переименуйте его и запустите снова."
  fi
  while [ -z "$GIT_URL" ]; do
    ask "Адрес репозитория (https://<токен>@github.com/.../hr-messenger-mvp.git)" GIT_URL
  done
  git clone -q "$GIT_URL" "$APP_DIR" || die "не удалось скачать код. Проверьте адрес и токен GitHub."
  ok "скачано: $(git -C "$APP_DIR" log -1 --format='%h %s')"
fi
# В .git/config может лежать токен — закрываем от других пользователей сервера
chmod 700 "$APP_DIR/.git"
chmod +x "$APP_DIR"/scripts/*.sh

# ---------------------------------------------------------------------------
say "Настройки (.env)"
ENV_CREATED=false
if [ -f "$APP_DIR/.env" ]; then
  ok ".env уже есть — не перезаписываю"
  current=$(env_value DOMAIN)
  if [ -z "$current" ]; then
    die "в существующем $APP_DIR/.env нет строки DOMAIN=. Добавьте DOMAIN=$DOMAIN, COOKIE_SECURE=true, CORS_ORIGINS=https://$DOMAIN и запустите снова."
  elif [ "$current" != "$DOMAIN" ]; then
    warn "в .env указан домен $current (а не $DOMAIN). Использую $current. Чтобы сменить домен, исправьте DOMAIN и CORS_ORIGINS в .env."
    DOMAIN=$current
  fi
else
  DOMAIN="$DOMAIN" sh "$APP_DIR/scripts/gen-env.sh"
  ENV_CREATED=true
  ok ".env создан со случайными ключами"
fi
chmod 600 "$APP_DIR/.env"
WEB_PORT=$(env_value WEB_PORT); WEB_PORT=${WEB_PORT:-8080}

# ---------------------------------------------------------------------------
say "Проверка DNS"
SERVER_IP=$(curl -fsS4 --max-time 8 https://api.ipify.org 2>/dev/null || true)
DOMAIN_IPS=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)
if [ -z "$DOMAIN_IPS" ]; then
  warn "домен $DOMAIN пока никуда не указывает. Проверьте A-запись у регистратора (IP сервера: ${SERVER_IP:-?})."
  warn "Приложение запустится, а HTTPS-сертификат появится сам, когда DNS обновится."
elif [ -n "$SERVER_IP" ] && [[ " $DOMAIN_IPS" != *" $SERVER_IP "* ]]; then
  warn "домен $DOMAIN указывает на $DOMAIN_IPS, а IP этого сервера — $SERVER_IP."
  warn "Исправьте A-запись. HTTPS заработает, когда DNS обновится."
else
  ok "$DOMAIN → ${DOMAIN_IPS% }"
fi

# ---------------------------------------------------------------------------
say "Сборка и запуск (первый раз — 5–15 минут)"
compose up -d --build --remove-orphans

say "Ожидание запуска приложения"
healthy=false
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1; then healthy=true; break; fi
  sleep 2
done
if ! $healthy; then
  compose ps || true
  compose logs --tail 60 api || true
  die "приложение не ответило за 3 минуты. Логи выше; повторный запуск скрипта безопасен."
fi
ok "приложение работает"

HTTPS_OK=false
for _ in $(seq 1 12); do
  if curl -fsS --max-time 8 "https://$DOMAIN/api/health" >/dev/null 2>&1; then HTTPS_OK=true; break; fi
  sleep 5
done
if $HTTPS_OK; then
  ok "HTTPS работает: https://$DOMAIN"
else
  warn "https://$DOMAIN пока не открывается. Обычно причина — DNS ещё не обновился."
  warn "Caddy продолжит попытки сам. Проверка: docker compose --profile prod logs caddy (в $APP_DIR)"
fi

# ---------------------------------------------------------------------------
say "Ежедневная резервная копия базы"
cat > /etc/cron.d/hr-messenger-backup <<CRON
# Резервная копия базы HR Messenger каждый день в 03:30 (время сервера). Хранится 14 дней.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 3 * * * root $APP_DIR/scripts/backup.sh >> /var/log/hr-messenger-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/hr-messenger-backup
ok "копии: $APP_DIR/backups, журнал: /var/log/hr-messenger-backup.log"

# ---------------------------------------------------------------------------
say "Администратор"
admins=$(compose exec -T db psql -U hr -d hr -tAc "select count(*) from users where role = 'admin' and is_active" 2>/dev/null | tr -d '[:space:]' || true)
admins=${admins:-0}
create_admin() { # create_admin ЛОГИН "ФИО"
  if [ -n "${ADMIN_PASSWORD:-}" ]; then
    compose exec -T -e ADMIN_PASSWORD api python -m app.create_admin --login "$1" --name "$2"
  else
    compose exec api python -m app.create_admin --login "$1" --name "$2"
  fi
}
if [ -n "${ADMIN_LOGIN:-}" ]; then
  create_admin "$ADMIN_LOGIN" "${ADMIN_NAME:-Администратор}" || warn "администратор не создан"
elif [ "$admins" != "0" ] && [[ "$admins" =~ ^[0-9]+$ ]]; then
  ok "администраторов в системе: $admins"
  if yes_no "Создать ещё одного или сбросить пароль?" н; then
    a_login=""; a_name=""
    while [ -z "$a_login" ]; do ask "Логин (латиницей, например admin)" a_login; done
    while [ -z "$a_name" ]; do ask "ФИО" a_name; done
    create_admin "$a_login" "$a_name" || warn "не получилось — можно повторить позже, команда в docs/DEPLOY.md"
  fi
elif $HAS_TTY && yes_no "Создать администратора сейчас?" д; then
  a_login=""; a_name=""
  while [ -z "$a_login" ]; do ask "Логин (латиницей, например admin)" a_login; done
  while [ -z "$a_name" ]; do ask "ФИО" a_name; done
  until create_admin "$a_login" "$a_name"; do
    yes_no "Попробовать ещё раз?" д || { warn "администратор не создан — команда в docs/DEPLOY.md"; break; }
  done
else
  warn "администратор не создан. Команда (в $APP_DIR):"
  warn "  docker compose exec api python -m app.create_admin --login admin --name \"Фамилия Имя\""
fi

# ---------------------------------------------------------------------------
say "Готово"
echo "    Адрес приложения:  https://$DOMAIN"
echo "    Webhook для Meta:  https://$DOMAIN/api/webhooks/whatsapp"
echo "    Verify token:      $(env_value WA_VERIFY_TOKEN)"
echo "    Обновление:        bash $APP_DIR/scripts/update.sh"
echo
printf '\033[1;31m    ВАЖНО: сохраните ключи шифрования вне сервера (менеджер паролей, сейф).\033[0m\n'
echo "    Без них телефоны кандидатов в базе и в резервных копиях не расшифровать."
if $ENV_CREATED; then
  echo
  echo "    PHONE_ENC_KEYS=$(env_value PHONE_ENC_KEYS)"
  echo "    PHONE_HASH_KEY=$(env_value PHONE_HASH_KEY)"
  echo
  echo "    Надёжнее всего скачать весь файл $APP_DIR/.env к себе (см. docs/DEPLOY.md)."
else
  echo "    Посмотреть ключи: grep -E '^PHONE_(ENC|HASH)_KEY' $APP_DIR/.env"
fi
