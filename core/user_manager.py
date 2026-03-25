"""User Manager — จัดการ user, auth, preferences"""

from core.config import OWNER_TELEGRAM_CHAT_ID, OWNER_DISPLAY_NAME, DEFAULT_LLM, TIMEZONE
from core import db
from core.logger import get_logger

log = get_logger(__name__)


def init_owner():
    """สร้าง owner user ตอน startup (idempotent)"""
    db.upsert_user(
        user_id=str(OWNER_TELEGRAM_CHAT_ID),
        chat_id=OWNER_TELEGRAM_CHAT_ID,
        display_name=OWNER_DISPLAY_NAME,
        role="owner",
        default_llm=DEFAULT_LLM,
        timezone=TIMEZONE,
    )
    log.info("Owner initialized: %s (chat_id: %s)", OWNER_DISPLAY_NAME, OWNER_TELEGRAM_CHAT_ID)


def get_user(chat_id: str | int) -> dict | None:
    """หา user จาก Telegram chat_id — return None ถ้าไม่ authorized"""
    return db.get_user_by_chat_id(str(chat_id))


def get_user_by_id(user_id: str | int) -> dict | None:
    return db.get_user_by_id(str(user_id))


def register_user(chat_id: str | int, display_name: str = "") -> dict:
    user_id = str(chat_id)
    final_name = display_name.strip() or user_id
    db.upsert_user(
        user_id=user_id,
        chat_id=str(chat_id),
        display_name=final_name,
        role="user",
        default_llm=DEFAULT_LLM,
        timezone=TIMEZONE,
        ensure_default_consents=False,
    )
    db.initialize_explicit_consents_for_new_user(user_id, source="registration")
    log.info("Registered new user: %s (%s)", final_name, chat_id)
    return db.get_user_by_chat_id(str(chat_id)) or {
        "user_id": user_id,
        "telegram_chat_id": str(chat_id),
        "display_name": final_name,
        "role": "user",
        "default_llm": DEFAULT_LLM,
        "timezone": TIMEZONE,
    }


def is_authorized(chat_id: str | int) -> bool:
    return get_user(chat_id) is not None


def is_owner(user: dict) -> bool:
    return user.get("role") == "owner"


def get_preference(user: dict, key: str) -> str:
    """ดึง preference ของ user"""
    defaults = {"default_llm": DEFAULT_LLM, "timezone": TIMEZONE}
    return user.get(key, defaults.get(key, ""))


def set_preference(user_id: str, key: str, value: str):
    db.update_user_preference(user_id, key, value)


def update_profile(user_id: str, display_name: str | None = None,
                   phone_number: str | None = None, national_id: str | None = None):
    db.update_user_profile(user_id, display_name=display_name,
                           phone_number=phone_number, national_id=national_id)
