from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все секреты и настройки окружения читаются только из переменных окружения / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"  # dev | test | prod
    database_url: str = "postgresql+asyncpg://hr:hr@localhost:5432/hr"
    redis_url: str = "redis://localhost:6379/0"

    # Подпись сессионных JWT
    secret_key: str = Field(min_length=32)
    session_ttl_hours: int = 12
    cookie_secure: bool = False

    # Шифрование ПДн: base64 32-байтные ключи. Формат: "v1:<key>,v2:<key>" — первый ключ активный.
    phone_enc_keys: str
    # Ключ HMAC для поиска/дедупликации по телефону (не меняется без перехеширования)
    phone_hash_key: str

    timezone: str = "Asia/Almaty"
    cors_origins: str = "http://localhost:5173"

    data_retention_days: int = 365


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
