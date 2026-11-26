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
ENV
chmod 600 .env
echo ".env создан. Сохраните PHONE_ENC_KEYS и PHONE_HASH_KEY в надёжном месте: без них телефоны не расшифровать."
