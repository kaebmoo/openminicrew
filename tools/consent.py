"""Consent Tool — จัดการ consent ผ่านภาษาธรรมชาติ"""

from core import db
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

# mapping ชื่อ consent ภาษาไทย/อังกฤษ → consent_type
_CONSENT_MAP = {
    "chat": db.CONSENT_CHAT_HISTORY,
    "chat_history": db.CONSENT_CHAT_HISTORY,
    "สนทนา": db.CONSENT_CHAT_HISTORY,
    "ประวัติ": db.CONSENT_CHAT_HISTORY,
    "ประวัติสนทนา": db.CONSENT_CHAT_HISTORY,
    "บันทึกการสนทนา": db.CONSENT_CHAT_HISTORY,
    "location": db.CONSENT_LOCATION,
    "ตำแหน่ง": db.CONSENT_LOCATION,
    "พิกัด": db.CONSENT_LOCATION,
    "gps": db.CONSENT_LOCATION,
    "gmail": db.CONSENT_GMAIL,
    "อีเมล": db.CONSENT_GMAIL,
    "email": db.CONSENT_GMAIL,
}

_ACTION_MAP = {
    "on": True, "grant": True, "allow": True, "enable": True,
    "เปิด": True, "อนุญาต": True, "ยินยอม": True,
    "off": False, "revoke": False, "deny": False, "disable": False,
    "ปิด": False, "ยกเลิก": False, "ไม่อนุญาต": False, "ไม่ยินยอม": False,
    "status": None, "สถานะ": None, "ดู": None,
}

_ACTION_KEYS_BY_LENGTH = sorted(_ACTION_MAP.keys(), key=len, reverse=True)


class ConsentTool(BaseTool):
    name = "consent"
    description = "จัดการ consent/ความยินยอม เช่น เปิด-ปิดประวัติสนทนา ตำแหน่ง อีเมล"
    commands = []  # ไม่มี direct command — /consent อยู่ใน SYSTEM_COMMANDS แล้ว
    direct_output = True

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "จัดการ consent/ความยินยอมของผู้ใช้ เปิด-ปิดการเก็บข้อมูล. "
                "ใช้เมื่อ user พูดเกี่ยวกับการอนุญาต/ยกเลิกการเก็บข้อมูล. "
                "เช่น 'เปิดยินยอมบันทึกการสนทนา', 'ปิดเก็บตำแหน่ง', "
                "'ยกเลิกการยินยอมบันทึกการสนทนา', 'ดูสถานะ consent'. "
                "consent ที่มี: chat (ประวัติสนทนา), location (ตำแหน่ง GPS), gmail (อีเมล)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "รูปแบบ: '<consent_type> <action>' "
                            "consent_type: chat | location | gmail "
                            "action: on | off | status "
                            "เช่น 'chat on', 'location off', 'chat status' "
                            "ถ้าไม่ระบุ args หรือแค่ 'status' จะแสดงสถานะทั้งหมด"
                        ),
                    }
                },
                "required": ["args"],
            },
        }

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        args = (args or "").strip().lower()

        # ไม่ระบุ args หรือแค่ "status" → แสดงสถานะทั้งหมด
        if not args or args in ("status", "สถานะ", "ดู"):
            return self._show_status(user_id)

        # parse consent_type + action
        consent_type, granted = self._parse_args(args)

        if consent_type is None:
            return (
                "ไม่เข้าใจคำสั่ง กรุณาระบุชนิด consent:\n"
                "• chat — ประวัติสนทนา\n"
                "• location — ตำแหน่ง GPS\n"
                "• gmail — อีเมล\n\n"
                "ตัวอย่าง: 'chat on', 'location off'"
            )

        if granted is None:
            # แสดงสถานะเฉพาะ consent ที่ระบุ
            return self._show_status(user_id, consent_type)

        # ดำเนินการ
        result = db.apply_user_consent(user_id, consent_type, granted, source="tool")

        return self._format_result(consent_type, result, granted)

    def _parse_args(self, args: str) -> tuple[str | None, bool | None]:
        """Parse args → (consent_type, granted|None)"""
        tokens = args.split()

        consent_type = None
        action = None

        for token in tokens:
            if token in _CONSENT_MAP and consent_type is None:
                consent_type = _CONSENT_MAP[token]
            if token in _ACTION_MAP and action is None:
                action = _ACTION_MAP[token]

        # ถ้าไม่เจอ consent_type จาก exact match → ลอง substring
        if consent_type is None:
            for key, ct in _CONSENT_MAP.items():
                if key in args:
                    consent_type = ct
                    break

        # ถ้าไม่เจอ action → ลอง substring
        if action is None:
            for key in _ACTION_KEYS_BY_LENGTH:
                if key in args:
                    action = _ACTION_MAP[key]
                    break

        return consent_type, action

    def _show_status(self, user_id: str, consent_type: str = None) -> str:
        rows = {r["consent_type"]: r for r in db.list_user_consents(user_id)}

        status_map = {
            db.CONSENT_STATUS_GRANTED: "✅ เปิด",
            db.CONSENT_STATUS_REVOKED: "🔒 ปิด",
            db.CONSENT_STATUS_NOT_SET: "⚪ ยังไม่ตั้งค่า",
        }

        if consent_type:
            row = rows.get(consent_type, {})
            status = row.get("status", db.CONSENT_STATUS_NOT_SET)
            label = self._type_label(consent_type)
            return f"📋 {label}: {status_map.get(status, status)}"

        lines = ["📋 สถานะ consent ทั้งหมด:\n"]
        for ct in db.CONSENT_TYPES:
            row = rows.get(ct, {})
            status = row.get("status", db.CONSENT_STATUS_NOT_SET)
            label = self._type_label(ct)
            lines.append(f"• {label}: {status_map.get(status, status)}")
        lines.append("\nเปลี่ยนได้ เช่น 'เปิด chat' หรือ 'ปิดตำแหน่ง'")
        return "\n".join(lines)

    @staticmethod
    def _type_label(consent_type: str) -> str:
        labels = {
            db.CONSENT_CHAT_HISTORY: "ประวัติสนทนา (chat)",
            db.CONSENT_LOCATION: "ตำแหน่ง (location)",
            db.CONSENT_GMAIL: "อีเมล (gmail)",
        }
        return labels.get(consent_type, consent_type)

    @staticmethod
    def _format_result(consent_type: str, result: dict, granted: bool) -> str:
        status = result.get("status", "")

        if consent_type == db.CONSENT_GMAIL:
            if granted:
                return "ℹ️ การให้สิทธิ์ Gmail ต้องทำผ่าน OAuth\nใช้ /authgmail เพื่อเชื่อมต่อ"
            return "✅ ยกเลิก consent Gmail แล้ว"

        if consent_type == db.CONSENT_LOCATION:
            deleted = result.get("location_deleted", False)
            if granted:
                return (
                    "✅ เปิดเก็บตำแหน่งแล้ว\n"
                    "ส่งตำแหน่งได้เลย (กดปุ่ม 📎 → Location)"
                )
            msg = "🔒 ปิดเก็บตำแหน่งแล้ว"
            if deleted:
                msg += "\nลบตำแหน่งที่เคยบันทึกไว้แล้ว"
            return msg

        # chat_history
        if granted:
            return (
                "✅ เปิดเก็บประวัติสนทนาแล้ว\n"
                "ระบบจะจำบริบทการสนทนาเพื่อตอบได้ต่อเนื่อง"
            )
        deleted_h = result.get("chat_history_deleted", 0)
        deleted_c = result.get("conversations_deleted", 0)
        msg = "🔒 ปิดเก็บประวัติสนทนาแล้ว"
        if deleted_h or deleted_c:
            msg += f"\nลบประวัติ {deleted_h} รายการ, สนทนา {deleted_c} รายการ"
        return msg
