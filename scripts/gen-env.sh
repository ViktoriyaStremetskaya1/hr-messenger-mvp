#!/usr/bin/env sh
# Генерирует .env со случайными секретами. Не перезаписывает существующий файл.
#
#   ./scripts/gen-env.sh                      — песочница на своём компьютере (http://localhost:8080)
#   DOMAIN=hr.example.kz ./scripts/gen-env.sh — боевой сервер: HTTPS через Caddy, настоящий WhatsApp
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then echo ".env уже существует — не трогаю"; exit 0; fi
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
key32() { python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"; }

DOMAIN=$(printf '%s' "${DOMAIN:-}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')
if [ -n "$DOMAIN" ]; then
  case "$DOMAIN" in
    http://*|https://*|*/*) echo "DOMAIN укажите без http:// и без /, например: hr.example.kz" >&2; exit 1 ;;
  esac
  COOKIE_SECURE=true
  CORS_ORIGINS="https://$DOMAIN"
  WA_COMMENT="# --- WhatsApp: боевой режим. Заполните данные из кабинета Meta (docs/WHATSAPP_SETUP.md) ---"
  WA_API_BASE=https://graph.facebook.com
  WA_PHONE_NUMBER_ID=
  WA_BUSINESS_ACCOUNT_ID=
  WA_ACCESS_TOKEN=
  WA_APP_SECRET=
else
  COOKIE_SECURE=false
  CORS_ORIGINS=http://localhost:8080
  WA_COMMENT="# --- WhatsApp: по умолчанию песочница (docker compose --profile sandbox up) ---"
  WA_API_BASE=http://wa-mock:9000
  WA_PHONE_NUMBER_ID=100000000000001
  WA_BUSINESS_ACCOUNT_ID=200000000000001
  WA_ACCESS_TOKEN=$(rand 32)
  WA_APP_SECRET=$(rand 32)
fi

umask 077
cat > .env <<ENV
APP_ENV=prod
POSTGRES_PASSWORD=$(rand 24)
SECRET_KEY=$(rand 48)
PHONE_ENC_KEYS=v1:$(key32)
PHONE_HASH_KEY=$(rand 32)
COOKIE_SECURE=$COOKIE_SECURE
CORS_ORIGINS=$CORS_ORIGINS
WEB_PORT=8080
ENV

if [ -n "$DOMAIN" ]; then
  cat >> .env <<ENV
# Домен сервера: на него Caddy получает HTTPS-сертификат
DOMAIN=$DOMAIN
# Профиль prod (Caddy) включается и в командах docker compose без --profile
COMPOSE_PROFILES=prod
ENV
fi

cat >> .env <<ENV

$WA_COMMENT
WA_API_BASE=$WA_API_BASE
WA_API_VERSION=v23.0
WA_PHONE_NUMBER_ID=$WA_PHONE_NUMBER_ID
WA_BUSINESS_ACCOUNT_ID=$WA_BUSINESS_ACCOUNT_ID
WA_ACCESS_TOKEN=$WA_ACCESS_TOKEN
WA_APP_SECRET=$WA_APP_SECRET
WA_VERIFY_TOKEN=$(rand 16)
WA_DISPLAY_PHONE=
ENV
chmod 600 .env
echo ".env создан. Сохраните PHONE_ENC_KEYS и PHONE_HASH_KEY в надёжном месте: без них телефоны не расшифровать."
