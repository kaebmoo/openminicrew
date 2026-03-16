"""Memory — จัดการ chat context per user per conversation"""

from datetime import datetime, timedelta
from core import db
from core.config import MAX_CONTEXT_MESSAGES
from core.logger import get_logger

log = get_logger(__name__)

# Idle timeout: ถ้าไม่มี message เกิน 30 นาที → เริ่ม conversation ใหม่อัตโนมัติ
CONVERSATION_IDLE_MINUTES = 30


def save_user_message(user_id: str, content: str, conversation_id: str = None):
    db.save_chat(user_id, "user", content, conversation_id=conversation_id)


def save_assistant_message(user_id: str, content: str,
                           tool_used: str = None, llm_model: str = None,
                           token_used: int = None, conversation_id: str = None):
    db.save_chat(user_id, "assistant", content,
                 tool_used=tool_used, llm_model=llm_model,
                 token_used=token_used, conversation_id=conversation_id)


def get_context(user_id: str, conversation_id: str = None) -> list[dict]:
    """ดึง chat history ล่าสุด N ข้อความ สำหรับส่งให้ LLM"""
    rows = db.get_chat_context(user_id, limit=MAX_CONTEXT_MESSAGES,
                               conversation_id=conversation_id)
    messages = []
    for r in rows:
        messages.append({
            "role": r["role"],
            "content": r["content"],
        })
    return messages


def ensure_conversation(user_id: str) -> str:
    """ดึง active conversation หรือสร้างใหม่ถ้าไม่มี / idle เกิน threshold"""
    conv_id = db.get_active_conversation(user_id)

    if conv_id:
        # ตรวจว่า conversation idle เกิน threshold หรือไม่
        if _is_conversation_idle(conv_id):
            log.info(f"[memory] conversation {conv_id} idle > {CONVERSATION_IDLE_MINUTES}min, starting new")
            db.end_conversation(conv_id)
            conv_id = db.create_conversation(user_id)
    else:
        conv_id = db.create_conversation(user_id)

    return conv_id


def start_new_conversation(user_id: str) -> str:
    """ปิด conversation เก่าแล้วสร้างใหม่"""
    old_conv = db.get_active_conversation(user_id)
    if old_conv:
        db.end_conversation(old_conv)
    return db.create_conversation(user_id)


def _is_conversation_idle(conv_id: str) -> bool:
    """ตรวจว่า conversation idle เกิน threshold หรือไม่"""
    last_time = db.get_last_message_time(conv_id)
    if not last_time:
        return True  # conversation ใหม่ที่ยังไม่มี message ถือว่า idle
    return (datetime.now() - last_time) > timedelta(minutes=CONVERSATION_IDLE_MINUTES)
