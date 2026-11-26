"""Шифрование персональных данных (телефонов).

- Значение шифруется AES-256-GCM, формат хранения: "<key_id>:<base64(nonce|ciphertext)>".
  Поддерживается ротация: первый ключ в PHONE_ENC_KEYS используется для шифрования,
  остальные — только для расшифровки старых записей.
- Для поиска и дедупликации хранится HMAC-SHA256 от нормализованного номера.
"""
import base64
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


@lru_cache
def _keys() -> tuple[str, dict[str, AESGCM]]:
    raw = get_settings().phone_enc_keys
    keys: dict[str, AESGCM] = {}
    active = ""
    for i, part in enumerate(p.strip() for p in raw.split(",") if p.strip()):
        key_id, b64 = part.split(":", 1)
        key = base64.b64decode(b64)
        if len(key) != 32:
            raise ValueError(f"Ключ {key_id} должен быть 32 байта")
        keys[key_id] = AESGCM(key)
        if i == 0:
            active = key_id
    if not active:
        raise ValueError("PHONE_ENC_KEYS пуст")
    return active, keys


def encrypt(value: str) -> str:
    active, keys = _keys()
    nonce = os.urandom(12)
    ct = keys[active].encrypt(nonce, value.encode(), None)
    return f"{active}:{base64.b64encode(nonce + ct).decode()}"


def decrypt(token: str) -> str:
    _, keys = _keys()
    key_id, b64 = token.split(":", 1)
    data = base64.b64decode(b64)
    return keys[key_id].decrypt(data[:12], data[12:], None).decode()


def phone_hash(normalized_phone: str) -> str:
    key = get_settings().phone_hash_key.encode()
    return hmac.new(key, normalized_phone.encode(), hashlib.sha256).hexdigest()


def needs_reencrypt(token: str) -> bool:
    active, _ = _keys()
    return not token.startswith(f"{active}:")
