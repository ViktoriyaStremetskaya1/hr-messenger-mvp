#!/usr/bin/env sh
# Генерирует .env со случайными секретами. Не перезаписывает существующий файл.
set -e
cd "$(dirname "$0")/.."
if [ -f .env ]; then echo ".env уже существует — не трогаю"; exit 0; fi
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
key32() { python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"; }
cat > .env <<ENV
APP_ENV=prod
POSTGRES_PASSWORD=$(rand 24)
SECRET_KEY=$(rand 48)
PHONE_ENC_KEYS=v1:$(key32)
PHONE_HASH_KEY=$(rand 32)
COOKIE_SECURE=false
CORS_ORIGINS=http://localhost:8080
WEB_PORT=8080

# --- WhatsApp: по умолчанию песочница (docker compose --profile sandbox up) ---
WA_API_BASE=http://wa-mock:9000
WA_API_VERSION=v23.0
WA_PHONE_NUMBER_ID=100000000000001
WA_BUSINESS_ACCOUNT_ID=200000000000001
WA_ACCESS_TOKEN=$(rand 32)
WA_APP_SECRET=$(rand 32)
WA_VERIFY_TOKEN=$(rand 16)
WA_DISPLAY_PHONE=
ENV
chmod 600 .env
echo ".env создан. Сохраните PHONE_ENC_KEYS и PHONE_HASH_KEY в надёжном месте: без них телефоны не расшифровать."
