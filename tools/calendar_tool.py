"""Google Calendar tool using the same per-user Google OAuth token."""

from datetime import datetime, timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core import db
from core.security import get_gmail_credentials
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

LIST_WINDOW_DAYS = 30
LIST_MAX_ITEMS = 10
LIST_FETCH_LIMIT = 50


class CalendarTool(BaseTool):
    name = "calendar_tool"
    description = "ดู เพิ่ม และลบนัดหมายใน Google Calendar ของผู้ใช้"
    commands = ["/cal", "/calendar"]
    direct_output = False

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        raw_args = (args or "").strip()
        try:
            creds = get_gmail_credentials(user_id)
            if not creds:
                result = "❌ ยังไม่ได้เชื่อมต่อ Google Calendar/Gmail\nกรุณาใช้ /authgmail แล้ว authorize ใหม่"
            else:
                service = build("calendar", "v3", credentials=creds)
                tokens = raw_args.split()
                if not tokens or tokens[0].lower() == "list":
                    result = self._list_events(service)
                else:
                    sub = tokens[0].lower()
                    if sub == "add" and len(tokens) >= 5:
                        result = self._add_event(service, tokens[1], tokens[2], tokens[3], " ".join(tokens[4:]))
                    elif sub == "delete" and len(tokens) >= 2:
                        result = self._delete_event(service, tokens[1])
                    else:
                        result = "❌ ใช้: /calendar list | /calendar add YYYY-MM-DD HH:MM HH:MM ชื่องาน | /calendar delete <ลำดับหรือ event_id>"

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", raw_args, kind="calendar_command"),
                **db.make_log_field("output", result, kind="calendar_result"),
            )
            return result
        except HttpError as exc:
            log.warning("Calendar API error for %s: %s", user_id, exc)
            result = self._format_calendar_error(exc)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", raw_args, kind="calendar_command"),
                **db.make_error_fields(str(exc)),
            )
            return result
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.error("Calendar tool failed for %s: %s", user_id, exc)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", raw_args, kind="calendar_command"),
                **db.make_error_fields(str(exc)),
            )
            return "❌ ใช้งาน Google Calendar ไม่สำเร็จในตอนนี้\nกรุณาลองใหม่อีกครั้ง ถ้ายังไม่หายให้เชื่อมต่อใหม่ด้วย /authgmail"

    def _list_events(self, service) -> str:
        items = self._fetch_list_items(service)
        if not items:
            return f"📅 ไม่มีนัดหมายที่กำลังจะมาถึงใน {LIST_WINDOW_DAYS} วันข้างหน้า"
        lines = [f"📅 นัดหมายที่กำลังจะมาถึงใน {LIST_WINDOW_DAYS} วันข้างหน้า:\n"]
        for index, item in enumerate(items, start=1):
            start = self._format_event_start(item)
            lines.append(f"{index}. {start} — {item.get('summary', '(ไม่มีชื่อ)')}")
        return "\n".join(lines)

    def _prepare_list_items(self, items: list[dict]) -> list[dict]:
        filtered = []
        recurring_seen = set()

        for item in items:
            if self._should_skip_event(item):
                continue

            recurring_key = item.get("recurringEventId") or item.get("iCalUID")
            if recurring_key and recurring_key in recurring_seen:
                continue
            if recurring_key:
                recurring_seen.add(recurring_key)

            filtered.append(item)
            if len(filtered) >= LIST_MAX_ITEMS:
                break

        return filtered

    def _format_event_start(self, item: dict) -> str:
        start_info = item.get("start", {})
        date_time = start_info.get("dateTime")
        if date_time:
            return date_time[:16].replace("T", " ")
        return start_info.get("date", "(ไม่ทราบเวลา)")

    def _should_skip_event(self, item: dict) -> bool:
        event_type = (item.get("eventType") or "").lower()
        if event_type in {"focusTime", "fromgmail"}:
            return True
        return False

    def _format_calendar_error(self, exc: Exception) -> str:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            resp = getattr(exc, "resp", None)
            status_code = getattr(resp, "status", None)

        message = str(exc)
        lowered = message.lower()

        if status_code == 403 and "accessnotconfigured" in lowered:
            return (
                "❌ Google Calendar API ของโปรเจกต์นี้ยังไม่ได้เปิดใช้งาน\n"
                "ให้เปิด Google Calendar API ใน Google Cloud Console ก่อน แล้วรอ 2-5 นาทีค่อยลองใหม่"
            )

        if status_code == 403 and ("insufficient" in lowered or "permission" in lowered or "forbidden" in lowered):
            return (
                "❌ สิทธิ์ของ Google Calendar ยังไม่พอสำหรับคำสั่งนี้\n"
                "กรุณาเชื่อมต่อใหม่ด้วย /authgmail แล้วลองอีกครั้ง"
            )

        if status_code == 401:
            return (
                "❌ Google Calendar token หมดอายุหรือถูกเพิกถอน\n"
                "กรุณาเชื่อมต่อใหม่ด้วย /authgmail"
            )

        if status_code == 404:
            return "❌ ไม่พบ event หรือ calendar ที่ต้องการ"

        return (
            "❌ ใช้งาน Google Calendar ไม่สำเร็จ"
            + (f" (HTTP {status_code})" if status_code else "")
            + "\nกรุณาลองใหม่อีกครั้ง ถ้ายังไม่หายให้ใช้ /authgmail เพื่อเชื่อมต่อใหม่"
        )

    def _add_event(self, service, date_str: str, start_time: str, end_time: str, title: str) -> str:
        start_dt = f"{date_str}T{start_time}:00+07:00"
        end_dt = f"{date_str}T{end_time}:00+07:00"
        event = {
            "summary": title,
            "start": {"dateTime": start_dt, "timeZone": "Asia/Bangkok"},
            "end": {"dateTime": end_dt, "timeZone": "Asia/Bangkok"},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return f"✅ เพิ่มนัดหมายแล้ว\n{title}\n{start_dt} - {end_dt}\nid: {created.get('id')}"

    def _delete_event(self, service, event_ref: str) -> str:
        event_id = self._resolve_event_id_for_delete(service, event_ref)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return f"✅ ลบนัดหมาย {event_id} แล้ว"

    def _resolve_event_id_for_delete(self, service, event_ref: str) -> str:
        candidate = (event_ref or "").strip()
        if candidate.isdigit():
            index = int(candidate)
            if index <= 0:
                raise ValueError("ลำดับต้องมากกว่า 0")
            items = self._fetch_list_items(service)
            if index > len(items):
                raise ValueError(f"ไม่พบรายการลำดับ {index}")
            return items[index - 1].get("id", "")
        return candidate

    def _fetch_list_items(self, service) -> list[dict]:
        now = datetime.utcnow().isoformat() + "Z"
        time_max = (datetime.utcnow() + timedelta(days=LIST_WINDOW_DAYS)).isoformat() + "Z"
        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=time_max,
            maxResults=LIST_FETCH_LIMIT,
            singleEvents=True,
            orderBy="startTime",
            timeZone="Asia/Bangkok",
        ).execute()
        return self._prepare_list_items(result.get("items", []))

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "ดู เพิ่ม หรือลบนัดใน Google Calendar เช่น '/calendar list', '/calendar add 2026-03-30 09:00 10:00 ประชุมทีม'",
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "คำสั่ง calendar"}},
                "required": [],
            },
        }