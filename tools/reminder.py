"""Reminder tool built on top of schedules table."""

from datetime import datetime
from zoneinfo import ZoneInfo

from core import db
from core.config import TIMEZONE
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)


class ReminderTool(BaseTool):
    name = "reminder"
    description = "ตั้งการเตือนครั้งเดียวตามวันเวลา และดู/ลบรายการเตือนได้"
    commands = ["/remind"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        raw_args = (args or "").strip()

        try:
            tokens = raw_args.split()
            if not tokens:
                result = self._usage()
            elif tokens[0].lower() == "fire" and len(tokens) >= 2:
                reminder = db.get_reminder(int(tokens[1]))
                if not reminder:
                    result = "⏰ ไม่พบ reminder"
                else:
                    db.mark_reminder_sent(reminder["id"])
                    result = f"⏰ เตือน: {reminder['text']}"
            else:
                sub = tokens[0].lower()
                if sub == "list":
                    result = self._list(user_id)
                elif sub in ("remove", "delete", "cancel"):
                    if len(tokens) < 2:
                        result = "❌ ใช้: /remind remove <id>"
                    else:
                        result = self._remove(user_id, int(tokens[1]))
                elif len(tokens) < 3:
                    result = self._usage()
                else:
                    date_str = tokens[0]
                    time_str = tokens[1]
                    reminder_text = " ".join(tokens[2:]).strip()
                    result = await self._add(user_id, date_str, time_str, reminder_text)

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", raw_args, kind="reminder_command"),
                **db.make_log_field("output", result, kind="reminder_result"),
            )
            return result
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            log.error("Reminder tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", raw_args, kind="reminder_command"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ ใช้งาน reminder ไม่สำเร็จ: {e}"

    async def _add(self, user_id: str, date_str: str, time_str: str, reminder_text: str) -> str:
        tz = ZoneInfo(TIMEZONE)
        try:
            run_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            return "❌ ใช้รูปแบบ /remind YYYY-MM-DD HH:MM ข้อความเตือน"

        if run_dt <= datetime.now(tz):
            return "❌ เวลาที่ระบุผ่านไปแล้ว"

        reminder_id = db.add_reminder(user_id, reminder_text, run_dt.isoformat())
        schedule_id = db.add_schedule(user_id, self.name, f"once:{date_str} {time_str}", f"fire {reminder_id}")
        db.update_reminder_schedule(reminder_id, schedule_id)

        try:
            from scheduler import reload_custom_schedules
            reload_custom_schedules()
        except (RuntimeError, ValueError) as e:
            log.error("Failed to reload scheduler for reminder %s: %s", reminder_id, e)

        return f"✅ ตั้งเตือนแล้ว [#{reminder_id}]\n🕐 {date_str} {time_str}\n📝 {reminder_text}"

    def _list(self, user_id: str) -> str:
        reminders = db.list_user_reminders(user_id)
        if not reminders:
            return "⏰ ยังไม่มี reminder ที่รออยู่"
        lines = ["⏰ Reminder ของคุณ:\n"]
        for item in reminders:
            lines.append(f"[{item['id']}] {item['remind_at'][:16]} — {item['text']}")
        return "\n".join(lines)

    def _remove(self, user_id: str, reminder_id: int) -> str:
        reminder = db.get_reminder(reminder_id, user_id)
        if not reminder:
            return f"❌ ไม่พบ reminder #{reminder_id}"
        if reminder.get("schedule_id"):
            db.remove_schedule(reminder["schedule_id"], user_id)
        db.remove_reminder(reminder_id, user_id)
        try:
            from scheduler import reload_custom_schedules
            reload_custom_schedules()
        except RuntimeError:
            pass
        return f"✅ ลบ reminder #{reminder_id} แล้ว"

    def _usage(self) -> str:
        return (
            "ตัวอย่าง:\n"
            "• /remind 2026-03-30 09:00 ประชุมทีม\n"
            "• /remind list\n"
            "• /remind remove 1"
        )

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ตั้งเตือนครั้งเดียวตามวันเวลาที่ระบุ แล้ว bot จะส่งข้อความเตือน. "
                "ใช้เมื่อ user ต้องการให้เตือนอะไรสักอย่างในเวลาที่กำหนด (ครั้งเดียว). "
                "ไม่ใช่สำหรับจดงานที่ต้องทำ (ใช้ todo) "
                "หรือ schedule tool ซ้ำๆ (ใช้ schedule). "
                "เช่น 'เตือนประชุม 2026-03-30 09:00', 'remind list'"
            ),
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "คำสั่ง reminder"}},
                "required": ["args"],
            },
        }