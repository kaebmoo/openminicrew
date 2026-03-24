"""API key resolution helpers with shared/private fallback rules."""

from __future__ import annotations

from core import db
from core import config

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - optional dependency at runtime
    Fernet = None
    InvalidToken = Exception

PRIVATE_ONLY_SERVICES = {
    "gmail",
    "calendar",
    "work_imap_host",
    "work_imap_user",
    "work_imap_password",
}

ENV_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google_maps": "GOOGLE_MAPS_API_KEY",
    "matcha": "MATCHA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "tmd": "TMD_API_KEY",
}

_fernet = Fernet(config.ENCRYPTION_KEY.encode()) if (Fernet and config.ENCRYPTION_KEY) else None


def normalize_service(service: str) -> str:
    return service.strip().lower()


def get_api_key(user_id: str, service: str) -> str | None:
    normalized_service = normalize_service(service)

    user_key = db.get_user_api_key(user_id, normalized_service)
    if user_key:
        return _decrypt(user_key)

    if normalized_service in PRIVATE_ONLY_SERVICES:
        return None

    env_name = ENV_KEY_MAP.get(normalized_service)
    if not env_name:
        return None

    return getattr(config, env_name, None) or None


def set_api_key(user_id: str, service: str, api_key: str):
    db.upsert_user_api_key(user_id, normalize_service(service), _encrypt(api_key))


def remove_api_key(user_id: str, service: str) -> bool:
    return db.delete_user_api_key(user_id, normalize_service(service))


def list_user_keys(user_id: str) -> list[dict]:
    return db.get_user_api_keys(user_id)


def get_supported_services() -> list[str]:
    services = set(PRIVATE_ONLY_SERVICES)
    services.update(ENV_KEY_MAP.keys())
    return sorted(services)


def _encrypt(value: str) -> str:
    if _fernet is None:
        return value
    return _fernet.encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    if _fernet is None:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return value