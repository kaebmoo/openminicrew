"""Memory — จัดการ chat context per user"""

from core import db
from core.config import MAX_CONTEXT_MESSAGES
from core.logger import get_logger

log = get_logger(__name__)


def save_user_message(user_id: str, content: str):
    db.save_chat(user_id, "user", content)


def save_assistant_message(user_id: str, content: str,
                           tool_used: str = None, llm_model: str = None,
                           token_used: int = None):
    db.save_chat(user_id, "assistant", content,
                 tool_used=tool_used, llm_model=llm_model,
                 token_used=token_used)


def get_context(user_id: str) -> list[dict]:
    """ดึง chat history ล่าสุด N ข้อความ สำหรับส่งให้ LLM"""
    rows = db.get_chat_context(user_id, limit=MAX_CONTEXT_MESSAGES)
    messages = []
    for r in rows:
        messages.append({
            "role": r["role"],
            "content": r["content"],
        })
    return messages
