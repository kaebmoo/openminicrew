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
    log.info(f"Owner initialized: {OWNER_DISPLAY_NAME} (chat_id: {OWNER_TELEGRAM_CHAT_ID})")


def get_user(chat_id: str | int) -> dict | None:
    """หา user จาก Telegram chat_id — return None ถ้าไม่ authorized"""
    return db.get_user_by_chat_id(str(chat_id))


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
