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
                "หรือคำที่เกี่ยวข้องกับการดูบันทึกการสนทนาที่ผ่านมา"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "ถ้าไม่ระบุ → แสดงรายชื่อสนทนาทั้งหมด. "
                            "ถ้าระบุตัวเลข เช่น '1' หรือ '3' → แสดงเนื้อหาของสนทนาลำดับนั้น. "
                            "เช่น 'ดู chat history' → ไม่ต้องส่ง args, "
                            "'ดูสนทนาที่ 1' → args='1'"
                        ),
                    }
                },
                "required": [],
            },
        }

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        args = (args or "").strip()

        # ถ้ามีตัวเลข → แสดงเนื้อหาสนทนาลำดับนั้น
        if args.isdigit():
            return self._show_conversation(user_id, int(args))

        # default → แสดงรายชื่อสนทนา
        return self._list_conversations(user_id)

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
        lines.append("\nพิมพ์หมายเลขเพื่อดูเนื้อหา เช่น 'ดูสนทนาที่ 1'")
        return "\n".join(lines)

    def _show_conversation(self, user_id: str, index: int) -> str:
        conversations = db.list_conversations(user_id, limit=10)
        if not conversations:
            return "📭 ยังไม่มีประวัติสนทนา"

        if index < 1 or index > len(conversations):
            return f"❌ ไม่พบสนทนาลำดับที่ {index} (มีทั้งหมด {len(conversations)} สนทนา)"

        conv = conversations[index - 1]
        conv_id = conv["id"]
        title = conv["title"] or "ไม่มีชื่อ"

        messages = db.get_chat_context(user_id, limit=_MAX_MESSAGES, conversation_id=conv_id)
        if not messages:
            return f"📭 สนทนา '{title}' ไม่มีข้อความ (อาจถูกลบแล้ว)"

        lines = [f"💬 *{title}* ({len(messages)} ข้อความ)\n"]
        for msg in messages:
            role = "🧑" if msg["role"] == "user" else "🤖"
            content = msg["content"] or ""
            # ตัดข้อความยาวเกิน
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"{role} {content}")
        return "\n".join(lines)
