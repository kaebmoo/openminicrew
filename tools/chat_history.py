"""Chat History Tool — ดูประวัติสนทนาผ่านภาษาธรรมชาติ"""

from core import db
from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)


class ChatHistoryTool(BaseTool):
    name = "chat_history"
    description = "ดูประวัติสนทนา / chat history"
    commands = []  # ไม่มี direct command — /history อยู่ใน SYSTEM_COMMANDS แล้ว
    direct_output = True

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ดูประวัติสนทนา / chat history ของผู้ใช้. "
                "ใช้เมื่อ user พูดถึง 'ดูประวัติสนทนา', 'chat history', "
                "'เรียกดู chat history', 'แสดงประวัติ', 'history' "
                "หรือคำที่เกี่ยวข้องกับการดูบันทึกการสนทนาที่ผ่านมา"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "จำนวนสนทนาที่จะแสดง (ค่าเริ่มต้น 10)",
                    }
                },
                "required": [],
            },
        }

    async def execute(self, user_id: str, limit: int = 10, **kwargs) -> str:
        conversations = db.list_conversations(user_id, limit=limit)
        if not conversations:
            return "📭 ยังไม่มีประวัติสนทนา"

        lines = ["📋 *ประวัติสนทนาล่าสุด:*\n"]
        for i, conv in enumerate(conversations, 1):
            title = conv["title"] or "ไม่มีชื่อ"
            count = conv["message_count"]
            time = conv["updated_at"][:16] if conv["updated_at"] else "—"
            lines.append(f"{i}. {title} ({count} ข้อความ, {time})")
        return "\n".join(lines)
