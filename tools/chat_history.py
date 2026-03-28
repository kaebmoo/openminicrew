"""Chat History Tool — ดูประวัติสนทนาผ่านภาษาธรรมชาติ"""

from core import db
from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)

_MAX_MESSAGES = 20  # จำนวนข้อความสูงสุดที่แสดงต่อสนทนา


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
                "หรือคำที่เกี่ยวข้องกับการดูบันทึกการสนทนาที่ผ่านมา. "
                "ค่าเริ่มต้นจะแสดงเนื้อหาข้อความของสนทนาล่าสุด. "
                "ถ้าระบุ mode='list' จะแสดงรายชื่อสนทนาทั้งหมด"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": (
                            "'view' (default) แสดงเนื้อหาข้อความของสนทนาล่าสุด, "
                            "'list' แสดงรายชื่อสนทนาทั้งหมด"
                        ),
                    },
                    "index": {
                        "type": "integer",
                        "description": "ลำดับสนทนาที่ต้องการดู (1 = ล่าสุด) ค่าเริ่มต้น 1",
                    },
                },
                "required": [],
            },
        }

    async def execute(self, user_id: str, mode: str = "view", index: int = 1, **kwargs) -> str:
        mode = (mode or "view").strip().lower()

        if mode == "list":
            return self._list_conversations(user_id)

        # default: แสดงเนื้อหาสนทนา
        return self._show_conversation(user_id, index)

    def _list_conversations(self, user_id: str) -> str:
        conversations = db.list_conversations(user_id, limit=10)
        if not conversations:
            return "📭 ยังไม่มีประวัติสนทนา"

        lines = ["📋 *ประวัติสนทนาล่าสุด:*\n"]
        for i, conv in enumerate(conversations, 1):
            title = conv["title"] or "ไม่มีชื่อ"
            count = conv["message_count"]
            time = conv["updated_at"][:16] if conv["updated_at"] else "—"
            lines.append(f"{i}. {title} ({count} ข้อความ, {time})")
        return "\n".join(lines)

    def _show_conversation(self, user_id: str, index: int = 1) -> str:
        conversations = db.list_conversations(user_id, limit=10)
        if not conversations:
            return "📭 ยังไม่มีประวัติสนทนา"

        if index < 1 or index > len(conversations):
            return f"❌ ไม่พบสนทนาลำดับที่ {index} (มีทั้งหมด {len(conversations)} สนทนา)"

        conv = conversations[index - 1]
        conv_id = conv["id"]
        title = conv["title"] or "ไม่มีชื่อ"
        total_count = conv["message_count"]

        messages = db.get_chat_context(user_id, limit=_MAX_MESSAGES, conversation_id=conv_id)
        if not messages:
            return f"📭 สนทนา '{title}' ไม่มีข้อความ (อาจถูกลบแล้ว)"

        header = f"💬 *{title}*"
        if total_count > _MAX_MESSAGES:
            header += f" (แสดง {len(messages)}/{total_count} ข้อความล่าสุด)"
        else:
            header += f" ({len(messages)} ข้อความ)"

        lines = [header, ""]
        for msg in messages:
            role = "🧑" if msg["role"] == "user" else "🤖"
            content = msg["content"] or ""
            # ตัดข้อความยาวเกิน
            if len(content) > 300:
                content = content[:300] + "…"
            lines.append(f"{role} {content}")

        if len(conversations) > 1:
            lines.append(f"\nมีสนทนาทั้งหมด {len(conversations)} รายการ")

        return "\n".join(lines)
