"""API Keys tool — จัดการ API keys สำหรับบริการต่างๆ"""

from core.api_keys import get_supported_services, list_user_keys, remove_api_key, set_api_key
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

_CMD_TO_ACTION = {
    "/setkey": "set",
    "/mykeys": "list",
    "/removekey": "remove",
}


class ApiKeysTool(BaseTool):
    name = "apikeys"
    description = "จัดการ API keys สำหรับบริการต่างๆ: เพิ่ม ดู ลบ"
    commands = ["/setkey", "/mykeys", "/removekey"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        action = kwargs.get("action") or _CMD_TO_ACTION.get(kwargs.get("command"), "")
        raw_args = (args or "").strip()

        if action == "set":
            return self._set(user_id, raw_args,
                             service=kwargs.get("service"),
                             value=kwargs.get("value"),
                             chat_id=kwargs.get("chat_id"),
                             message_id=kwargs.get("message_id"))
        elif action == "list":
            return self._list(user_id)
        elif action == "remove":
            service = kwargs.get("service") or raw_args.lower()
            return self._remove(user_id, service)
        else:
            return self._list(user_id)

    def _set(self, user_id: str, raw_args: str, *,
             service=None, value=None, chat_id=None, message_id=None) -> str:
        # LLM call: service + value ใน kwargs
        # Direct command: raw_args = "tmd abc123"
        if not service or not value:
            parts = raw_args.split(None, 1)
            if len(parts) < 2:
                services = ", ".join(get_supported_services())
                return (
                    "❌ ใช้: /setkey <service> <value>\n"
                    f"services ที่รองรับ: {services}"
                )
            service, value = parts[0].strip().lower(), parts[1].strip()

        if not value:
            return "❌ ค่า key ว่างไม่ได้"

        set_api_key(user_id, service, value)

        # ลบข้อความ user ที่มี API key เพื่อความปลอดภัย
        if chat_id and message_id:
            try:
                from interfaces.telegram_common import delete_message_safe
                delete_message_safe(chat_id, message_id)
            except Exception as e:
                log.warning(f"Failed to delete message: {e}")

        return f"✅ บันทึก key สำหรับ `{service}` แล้ว"

    def _list(self, user_id: str) -> str:
        keys = list_user_keys(user_id)
        if not keys:
            return "🔑 ยังไม่มี key ที่บันทึกไว้"

        lines = ["🔑 *API keys ของคุณ*\n"]
        for item in keys:
            updated = (item.get("updated_at") or "")[:16] or "-"
            lines.append(f"• `{item['service']}` (updated: {updated})")
        return "\n".join(lines)

    def _remove(self, user_id: str, service: str) -> str:
        if not service:
            return "❌ ใช้: /removekey <service>"

        deleted = remove_api_key(user_id, service)
        if not deleted:
            return f"ℹ️ ไม่พบ key สำหรับ `{service}`"
        return f"✅ ลบ key สำหรับ `{service}` แล้ว"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "จัดการ API keys สำหรับบริการต่างๆ เช่น TMD (กรมอุตุ), Google Maps "
                "เพิ่ม key (set), ดู keys ที่มี (list), ลบ key (remove)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["set", "list", "remove"],
                        "description": "set=เพิ่ม key, list=ดู keys ที่มี, remove=ลบ key",
                    },
                    "service": {
                        "type": "string",
                        "description": "ชื่อ service เช่น tmd, google_maps",
                    },
                    "value": {
                        "type": "string",
                        "description": "ค่า API key (สำหรับ action=set)",
                    },
                },
                "required": ["action"],
            },
        }
