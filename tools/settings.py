"""Settings tool — ตั้งค่าข้อมูลส่วนตัว: ชื่อ เบอร์โทร เลขบัตรประชาชน + ดูบัญชีอีเมล"""

from core import db
from core.api_keys import get_api_key
from core.logger import get_logger
from core.security import get_gmail_credentials
from tools.base import BaseTool

log = get_logger(__name__)

# map /command → action
_CMD_TO_ACTION = {
    "/setname": "setname",
    "/setphone": "setphone",
    "/setid": "setid",
    "/myemail": "myemail",
}


class SettingsTool(BaseTool):
    name = "settings"
    description = "ดูหรือตั้งค่าข้อมูลส่วนตัว: ชื่อ เบอร์โทร เลขบัตรประชาชน + ดูบัญชีอีเมล"
    commands = ["/setname", "/setphone", "/setid", "/myemail"]
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
        elif action == "myemail":
            return self._myemail(user_id)
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
                db.log_security_audit(
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    action="read_profile_secret",
                    resource_type="users.phone_number",
                    resource_id=user_id,
                    outcome="success",
                    detail="setphone_view",
                )
                return f"เบอร์โทรปัจจุบัน: {current}\nเปลี่ยนเบอร์: /setphone <เบอร์ใหม่>"
            return "ยังไม่ได้บันทึกเบอร์โทร\nใช้: /setphone <เบอร์โทร>"

        from tools.promptpay import _normalize_phone

        try:
            promptpay_phone = _normalize_phone(value)
        except ValueError as err:
            return f"❌ เบอร์โทรไม่ถูกต้อง: {err}"

        normalized = "0" + promptpay_phone[4:]
        try:
            db.update_user_profile(user_id, phone_number=normalized)
        except RuntimeError as err:
            return f"❌ {err}"

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
                db.log_security_audit(
                    actor_user_id=user_id,
                    target_user_id=user_id,
                    action="read_profile_secret",
                    resource_type="users.national_id",
                    resource_id=user_id,
                    outcome="success",
                    detail="setid_view",
                )
                masked = "X" * 9 + current[-4:]
                return f"เลขบัตรประชาชนปัจจุบัน: {masked}\nเปลี่ยน: /setid <เลขบัตรใหม่>"
            return "ยังไม่ได้บันทึกเลขบัตรประชาชน\nใช้: /setid <เลขบัตรประชาชน 13 หลัก>"

        from tools.promptpay import _validate_national_id
        try:
            cleaned = _validate_national_id(value)
        except ValueError as e:
            return f"❌ เลขบัตรไม่ถูกต้อง: {e}"

        try:
            db.update_user_profile(user_id, national_id=cleaned)
        except RuntimeError as err:
            return f"❌ {err}"
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
        if phone:
            db.log_security_audit(
                actor_user_id=user_id,
                target_user_id=user_id,
                action="read_profile_secret",
                resource_type="users.phone_number",
                resource_id=user_id,
                outcome="success",
                detail="settings_view",
            )
        if national_id:
            db.log_security_audit(
                actor_user_id=user_id,
                target_user_id=user_id,
                action="read_profile_secret",
                resource_type="users.national_id",
                resource_id=user_id,
                outcome="success",
                detail="settings_view",
            )
            masked = "X" * 9 + national_id[-4:]
            lines.append(f"• เลขบัตร: {masked}")
        else:
            lines.append("• เลขบัตร: ยังไม่ได้ตั้ง (/setid)")
        return "\n".join(lines)

    # ---- myemail ----
    def _myemail(self, user_id: str) -> str:
        """แสดงบัญชีอีเมลที่ตั้งค่าไว้ (Gmail + Work Email)"""
        lines = ["📧 บัญชีอีเมลที่ตั้งค่าไว้:\n"]

        # --- Gmail ---
        gmail_email = None
        try:
            creds = get_gmail_credentials(user_id)
            if creds:
                from googleapiclient.discovery import build
                service = build("gmail", "v1", credentials=creds)
                profile = service.users().getProfile(userId="me").execute()
                gmail_email = profile.get("emailAddress")
        except Exception as e:
            log.warning("Failed to fetch Gmail profile for %s: %s", user_id, e)

        if gmail_email:
            lines.append(f"✅ Gmail: {gmail_email}")
        else:
            lines.append("❌ Gmail: ยังไม่ได้เชื่อมต่อ (ใช้ /authgmail)")

        # --- Work Email (IMAP) ---
        work_user = get_api_key(user_id, "work_imap_user")
        work_host = get_api_key(user_id, "work_imap_host")

        if work_user:
            host_info = f" ({work_host})" if work_host else ""
            lines.append(f"✅ Work Email: {work_user}{host_info}")
        else:
            lines.append("❌ Work Email: ยังไม่ได้ตั้งค่า")
            lines.append("   ตั้งค่าด้วย /setkey work_imap_host, /setkey work_imap_user, /setkey work_imap_password")

        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", "myemail", kind="tool_command"),
            **db.make_log_field("output", "\n".join(lines), kind="tool_result"),
        )

        return "\n".join(lines)

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ดูหรือตั้งค่าข้อมูลส่วนตัว หรือดูบัญชีอีเมลที่ตั้งค่าไว้. "
                "ใช้เมื่อ user ถามเรื่องข้อมูลส่วนตัว ชื่อ เบอร์โทร เลขบัตร หรือถามว่าใช้อีเมลอะไรอยู่. "
                "ไม่ใช่สำหรับอ่านหรือสรุปเนื้อหาอีเมล (ใช้ gmail_summary หรือ work_email). "
                "เช่น 'ตั้งชื่อ kaebmoo', 'เบอร์โทรฉันคืออะไร', 'ใช้ gmail อะไรอยู่', 'ตั้ง email ไว้ไหม'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["setname", "setphone", "setid", "view", "myemail"],
                        "description": "setname=ตั้งชื่อ, setphone=ตั้งเบอร์โทร, setid=ตั้งเลขบัตรประชาชน, view=ดูข้อมูลทั้งหมด, myemail=ดูบัญชีอีเมลที่ตั้งค่าไว้",
                    },
                    "value": {
                        "type": "string",
                        "description": "ค่าที่ต้องการตั้ง (ไม่ต้องใส่ถ้าต้องการดูค่าปัจจุบัน)",
                    },
                },
                "required": ["action"],
            },
        }
