"""Google Calendar tool using the same per-user Google OAuth token."""

import re
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

    def get_tool_spec(self) -> dict:
        from core.prompt_loader import load_prompt
        try:
            desc = load_prompt(f"tools/{self.name}.md").strip()
        except FileNotFoundError:
            desc = self.description
        return {
            "name": self.name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "add", "delete"],
                        "description": "list = ดูนัดหมาย, add = เพิ่ม, delete = ลบ",
                    },
                    "date": {
                        "type": "string",
                        "description": "วันที่รูปแบบ YYYY-MM-DD (ปี ค.ศ.) — ต้องแปลงจากวันที่ไทย/พ.ศ. ก่อน",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "เวลาเริ่มรูปแบบ HH:MM (24h) เช่น 09:00",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "เวลาสิ้นสุด HH:MM (24h). ถ้าไม่ระบุจะ default = เริ่ม + 1 ชม.",
                    },
                    "title": {
                        "type": "string",
                        "description": "ชื่อ/หัวข้อนัดหมาย (สรุปสั้น ๆ ไม่ต้องใส่ URL/สถานที่)",
                    },
                    "description": {
                        "type": "string",
                        "description": "รายละเอียดเพิ่มเติม — ใส่ URL (Zoom/Meet/Teams), agenda, หมายเหตุ. Google Calendar จะตรวจจับ URL ให้กลายเป็นปุ่ม join อัตโนมัติ",
                    },
                    "location": {
                        "type": "string",
                        "description": "สถานที่จริง (ตึก/ห้อง/ที่อยู่). ถ้าเป็นประชุมออนไลน์ปล่อยว่าง แล้วใส่ลิงก์ใน description แทน",
                    },
                    "event_ref": {
                        "type": "string",
                        "description": "ใช้กับ action=delete: ลำดับจาก list หรือ event_id",
                    },
                },
                "required": ["action"],
            },
        }

    async def execute(
        self,
        user_id: str,
        args: str = "",
        action: str | None = None,
        date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        title: str | None = None,
        description: str = "",
        location: str = "",
        event_ref: str | None = None,
        **kwargs,
    ) -> str:
        raw_args = (args or "").strip()
        try:
            creds = get_gmail_credentials(user_id)
            if not creds:
                result = "❌ ยังไม่ได้เชื่อมต่อ Google Calendar/Gmail\nกรุณาใช้ /authgmail แล้ว authorize ใหม่"
            elif action:
                service = build("calendar", "v3", credentials=creds)
                result = self._dispatch_structured(
                    service,
                    action=action,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    title=title,
                    description=description,
                    location=location,
                    event_ref=event_ref,
                )
            else:
                service = build("calendar", "v3", credentials=creds)
                tokens = raw_args.split()
                if not tokens or tokens[0].lower() == "list":
                    result = self._list_events(service)
                else:
                    sub = tokens[0].lower()
                    if sub == "add":
                        add_rest = " ".join(tokens[1:])
                        if not add_rest.strip():
                            result = "❌ กรุณาระบุชื่อนัดหมาย วันที่ และเวลา\nตัวอย่าง: add ประชุมทีม 2026-04-22 14:00"
                        else:
                            try:
                                date_str, start_t, end_t, title_t, desc_t, loc_t = self._parse_add_args(add_rest)
                                result = self._add_event(
                                    service, date_str, start_t, end_t, title_t,
                                    description=desc_t, location=loc_t,
                                )
                            except ValueError as ve:
                                result = f"❌ {ve}\nตัวอย่าง: add ประชุมทีม 2026-04-22 14:00"
                    elif sub == "delete" and len(tokens) >= 2:
                        result = self._delete_event(service, tokens[1])
                    else:
                        result = "❌ ใช้: /calendar list | /calendar add ชื่องาน YYYY-MM-DD HH:MM | /calendar delete <ลำดับหรือ event_id>"

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

    def _parse_add_args(self, raw: str) -> tuple:
        """Extract date, start_time, end_time, title, description, location.

        Supports any argument order. URLs are pulled into description
        and an optional '@สถานที่' marker is pulled into location.
          - add 2026-04-22 14:00 15:00 ประชุมทีม
          - add ประชุมทีม 2026-04-22 14:00 https://zoom.us/j/123
          - add ประชุมทีม 2026-04-22 14:00-15:00 @ห้องประชุม A
        End time defaults to start + 1 hour if omitted.
        """
        # 0) Pull URLs out → description
        urls = re.findall(r'https?://\S+', raw)
        rest = re.sub(r'https?://\S+', '', raw)
        description = "\n".join(urls)

        # 0b) Pull '@location' marker (until next whitespace+@ or end)
        location = ""
        loc_m = re.search(r'@(\S[^@]*?)(?=\s+@|$)', rest)
        if loc_m:
            location = loc_m.group(1).strip()
            rest = rest[:loc_m.start()] + rest[loc_m.end():]

        # 1) Extract date YYYY-MM-DD
        date_m = re.search(r'(\d{4}-\d{2}-\d{2})', rest)
        if not date_m:
            raise ValueError("ไม่พบวันที่ (YYYY-MM-DD)")
        date_str = date_m.group(1)
        rest = rest[:date_m.start()] + rest[date_m.end():]

        # 2) Try time range HH:MM-HH:MM first
        range_m = re.search(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})', rest)
        if range_m:
            start_time = self._zero_pad_time(range_m.group(1))
            end_time = self._zero_pad_time(range_m.group(2))
            rest = rest[:range_m.start()] + rest[range_m.end():]
        else:
            # 3) Extract individual HH:MM tokens
            times = re.findall(r'(?<!\d)(\d{1,2}:\d{2})(?!\d)', rest)
            if not times:
                raise ValueError("ไม่พบเวลา (HH:MM)")
            start_time = self._zero_pad_time(times[0])
            if len(times) >= 2:
                end_time = self._zero_pad_time(times[1])
            else:
                h, m = int(start_time.split(':')[0]), int(start_time.split(':')[1])
                end_time = f"{(h + 1) % 24:02d}:{m:02d}"
            for t in times:
                rest = re.sub(re.escape(t), '', rest, count=1)

        # 4) Remaining text → title
        title = re.sub(r'\s+', ' ', rest).strip(' \t\n-–:')
        if not title:
            title = "(ไม่มีชื่อ)"

        return date_str, start_time, end_time, title, description, location

    @staticmethod
    def _zero_pad_time(t: str) -> str:
        """Ensure HH:MM is zero-padded, e.g. '9:00' → '09:00'."""
        parts = t.split(':')
        return f"{int(parts[0]):02d}:{parts[1]}"

    def _add_event(
        self,
        service,
        date_str: str,
        start_time: str,
        end_time: str,
        title: str,
        description: str = "",
        location: str = "",
    ) -> str:
        start_dt = f"{date_str}T{start_time}:00+07:00"
        end_dt = f"{date_str}T{end_time}:00+07:00"
        event = {
            "summary": title,
            "start": {"dateTime": start_dt, "timeZone": "Asia/Bangkok"},
            "end": {"dateTime": end_dt, "timeZone": "Asia/Bangkok"},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        created = service.events().insert(calendarId="primary", body=event).execute()
        extras = []
        if location:
            extras.append(f"📍 {location}")
        if description:
            extras.append(description)
        extras_block = ("\n" + "\n".join(extras)) if extras else ""
        return f"✅ เพิ่มนัดหมายแล้ว\n{title}\n{start_dt} - {end_dt}{extras_block}\nid: {created.get('id')}"

    def _dispatch_structured(
        self,
        service,
        action: str,
        date: str | None,
        start_time: str | None,
        end_time: str | None,
        title: str | None,
        description: str,
        location: str,
        event_ref: str | None,
    ) -> str:
        act = (action or "").strip().lower()
        if act == "list":
            return self._list_events(service)
        if act == "delete":
            if not event_ref:
                return "❌ ต้องระบุ event_ref (ลำดับหรือ event_id)"
            return self._delete_event(service, event_ref)
        if act == "add":
            if not date or not start_time or not title:
                return "❌ add ต้องมี date (YYYY-MM-DD), start_time (HH:MM) และ title"
            try:
                start_t = self._zero_pad_time(start_time)
                if end_time:
                    end_t = self._zero_pad_time(end_time)
                else:
                    h, m = int(start_t.split(":")[0]), int(start_t.split(":")[1])
                    end_t = f"{(h + 1) % 24:02d}:{m:02d}"
            except (ValueError, IndexError):
                return "❌ start_time/end_time ต้องเป็นรูปแบบ HH:MM"
            return self._add_event(
                service, date, start_t, end_t, title,
                description=description or "",
                location=location or "",
            )
        return f"❌ action ไม่ถูกต้อง: {action!r} (ใช้ list / add / delete)"

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

