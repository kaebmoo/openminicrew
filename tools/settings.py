"""Settings tool — ตั้งค่าข้อมูลส่วนตัว: ชื่อ เบอร์โทร เลขบัตรประชาชน"""

from core import db
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

# map /command → action
_CMD_TO_ACTION = {
    "/setname": "setname",
    "/setphone": "setphone",
    "/setid": "setid",
}


class SettingsTool(BaseTool):
    name = "settings"
    description = "ดูหรือตั้งค่าข้อมูลส่วนตัว: ชื่อ เบอร์โทร เลขบัตรประชาชน"
    commands = ["/setname", "/setphone", "/setid"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        # กรณี LLM เรียก: kwargs มี action, value
        # กรณี direct command: kwargs มี command, args เป็น string
        action = kwargs.get("action") or _CMD_TO_ACTION.get(kwargs.get("command"), "")
        value = kwargs.get("value") or (args or "").strip()

        user = db.get_user_by_chat_id(user_id)
        if not user:
            return "❌ ไม่พบข้อมูลผู้ใช้"

        if action == "setname":
            return self._setname(user_id, user, value)
        elif action == "setphone":
            return self._setphone(user_id, user, value,
                                  chat_id=kwargs.get("chat_id"),
                                  message_id=kwargs.get("message_id"))
        elif action == "setid":
            return self._setid(user_id, user, value,
                               chat_id=kwargs.get("chat_id"),
                               message_id=kwargs.get("message_id"))
        elif action == "view":
            return self._view(user_id, user)
        else:
            return self._view(user_id, user)

    # ---- setname ----
    def _setname(self, user_id: str, user: dict, value: str) -> str:
        if not value:
            current = user.get("display_name")
            if current and current != user_id:
                return f"ชื่อปัจจุบัน: {current}\nเปลี่ยนชื่อ: /setname <ชื่อใหม่>"
            return "ยังไม่ได้ตั้งชื่อ\nใช้: /setname <ชื่อ>"
        db.update_user_profile(user_id, display_name=value)
        return f"✅ ตั้งชื่อเป็น {value} แล้ว"

    # ---- setphone ----
    def _setphone(self, user_id: str, user: dict, value: str, *,
                  chat_id=None, message_id=None) -> str:
        if not value:
            current = user.get("phone_number")
            if current:
                return f"เบอร์โทรปัจจุบัน: {current}\nเปลี่ยนเบอร์: /setphone <เบอร์ใหม่>"
            return "ยังไม่ได้บันทึกเบอร์โทร\nใช้: /setphone <เบอร์โทร>"

        from tools.promptpay import _normalize_phone

        try:
            promptpay_phone = _normalize_phone(value)
        except ValueError as err:
            return f"❌ เบอร์โทรไม่ถูกต้อง: {err}"

        normalized = "0" + promptpay_phone[4:]
        db.update_user_profile(user_id, phone_number=normalized)

        if chat_id and message_id:
            try:
                from interfaces.telegram_common import delete_message_safe
                delete_message_safe(chat_id, message_id)
            except ImportError as err:
                log.warning("Failed to import delete_message_safe: %s", err)

        return f"✅ บันทึกเบอร์โทรแล้ว: {normalized}"

    # ---- setid ----
    def _setid(self, user_id: str, user: dict, value: str, *,
               chat_id=None, message_id=None) -> str:
        if not value:
            current = user.get("national_id")
            if current:
                masked = "X" * 9 + current[-4:]
                return f"เลขบัตรประชาชนปัจจุบัน: {masked}\nเปลี่ยน: /setid <เลขบัตรใหม่>"
            return "ยังไม่ได้บันทึกเลขบัตรประชาชน\nใช้: /setid <เลขบัตรประชาชน 13 หลัก>"

        from tools.promptpay import _validate_national_id
        try:
            cleaned = _validate_national_id(value)
        except ValueError as e:
            return f"❌ เลขบัตรไม่ถูกต้อง: {e}"

        db.update_user_profile(user_id, national_id=cleaned)
        masked = "X" * 9 + cleaned[-4:]

        # ลบข้อความ user ที่มีเลขบัตรประชาชน เพื่อความปลอดภัย
        if chat_id and message_id:
            try:
                from interfaces.telegram_common import delete_message_safe
                delete_message_safe(chat_id, message_id)
            except ImportError as err:
                log.warning("Failed to import delete_message_safe: %s", err)

        return f"✅ บันทึกเลขบัตรประชาชนแล้ว: {masked}"

    # ---- view ----
    def _view(self, user_id: str, user: dict) -> str:
        display_name = user.get("display_name") or user_id
        phone = user.get("phone_number")
        national_id = user.get("national_id")

        lines = ["📋 ข้อมูลส่วนตัว:"]
        lines.append(f"• ชื่อ: {display_name}")
        lines.append(f"• เบอร์โทร: {phone}" if phone else "• เบอร์โทร: ยังไม่ได้ตั้ง (/setphone)")
        if national_id:
            masked = "X" * 9 + national_id[-4:]
            lines.append(f"• เลขบัตร: {masked}")
        else:
            lines.append("• เลขบัตร: ยังไม่ได้ตั้ง (/setid)")
        return "\n".join(lines)

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ดูหรือตั้งค่าข้อมูลส่วนตัว: ตั้งชื่อ (setname), ตั้งเบอร์โทร (setphone), "
                "ตั้งเลขบัตรประชาชน (setid), หรือดูข้อมูลทั้งหมด (view) "
                "เช่น 'ตั้งชื่อ kaebmoo', 'เบอร์โทรฉันคืออะไร', 'เปลี่ยนเบอร์เป็น 0891234567'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["setname", "setphone", "setid", "view"],
                        "description": "setname=ตั้งชื่อ, setphone=ตั้งเบอร์โทร, setid=ตั้งเลขบัตรประชาชน, view=ดูข้อมูลทั้งหมด",
                    },
                    "value": {
                        "type": "string",
                        "description": "ค่าที่ต้องการตั้ง (ไม่ต้องใส่ถ้าต้องการดูค่าปัจจุบัน)",
                    },
                },
                "required": ["action"],
            },
        }
