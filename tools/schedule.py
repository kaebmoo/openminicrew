"""Schedule Tool — จัดการ scheduled tasks (add / remove / list)
   รองรับ: daily, weekday, weekly, monthly, once
   User ใช้ shorthand ง่ายๆ หรือ LLM แปลงจากภาษาธรรมชาติ
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.base import BaseTool
from core import db
from core.config import TIMEZONE
from core.user_manager import is_owner, get_user
from core.logger import get_logger

log = get_logger(__name__)

_TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DAY_MAP = {
    "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0,
    "จันทร์": 1, "อังคาร": 2, "พุธ": 3, "พฤหัส": 4, "พฤหัสบดี": 4,
    "ศุกร์": 5, "เสาร์": 6, "อาทิตย์": 0,
}

_DAY_DISPLAY = {0: "อาทิตย์", 1: "จันทร์", 2: "อังคาร", 3: "พุธ",
                4: "พฤหัส", 5: "ศุกร์", 6: "เสาร์"}


# === Helpers ===

def _normalize_time(t: str) -> str:
    """Normalize time string: '8:47' → '08:47', '07:00' → '07:00'"""
    m = _TIME_RE.match(t.strip())
    if not m:
        raise ValueError(f"รูปแบบเวลาไม่ถูก: {t} (ใช้ HH:MM เช่น 07:00)")
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23:
        raise ValueError(f"ชั่วโมงต้องอยู่ระหว่าง 0-23 (ได้: {hour})")
    return f"{hour:02d}:{minute:02d}"


def _time_to_parts(t: str) -> tuple[int, int]:
    normalized = _normalize_time(t)
    return int(normalized[:2]), int(normalized[3:])


def _build_cron(repeat: str, time_str: str, day: str = "") -> str:
    """Convert shorthand → cron_expr (or 'once:...' for one-time)"""
    hour, minute = _time_to_parts(time_str)

    if repeat == "daily":
        return f"{minute} {hour} * * *"

    if repeat == "weekday":
        return f"{minute} {hour} * * 1-5"

    if repeat == "weekly":
        day_num = _DAY_MAP.get(day.lower())
        if day_num is None:
            raise ValueError(
                f"ไม่รู้จักวัน: {day}\n"
                "ใช้: mon tue wed thu fri sat sun\n"
                "หรือ: จันทร์ อังคาร พุธ พฤหัส ศุกร์ เสาร์ อาทิตย์"
            )
        return f"{minute} {hour} * * {day_num}"

    if repeat == "monthly":
        try:
            dom = int(day)
            if not 1 <= dom <= 31:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"วันที่ในเดือนไม่ถูก: {day} (ใช้ 1-31)")
        return f"{minute} {hour} {dom} * *"

    if repeat == "once":
        if not day or not _DATE_RE.match(day):
            raise ValueError(f"ต้องระบุวันที่: YYYY-MM-DD (ได้: {day})")
        return f"once:{day} {time_str}"

    raise ValueError(
        f"ไม่รู้จัก repeat type: {repeat}\n"
        "ใช้: daily, weekday, weekly, monthly, once"
    )


def _cron_to_display(cron_expr: str) -> str:
    """Convert cron_expr → Thai display text"""
    if cron_expr.startswith("once:"):
        dt_str = cron_expr[5:]
        return f"{dt_str} (ครั้งเดียว)"

    parts = cron_expr.split()
    if len(parts) < 5:
        return cron_expr

    minute, hour, dom, _month, dow = parts
    time_str = f"{int(hour):02d}:{int(minute):02d}"

    if dom == "*" and dow == "*":
        return f"ทุกวัน {time_str}"
    if dom == "*" and dow == "1-5":
        return f"จ-ศ {time_str}"
    if dom == "*" and dow.isdigit():
        day_name = _DAY_DISPLAY.get(int(dow), dow)
        return f"ทุก{day_name} {time_str}"
    if dow == "*" and dom.isdigit():
        return f"วันที่ {dom} ทุกเดือน {time_str}"

    return f"{cron_expr} ({time_str})"


def _available_tools_str() -> str:
    from tools.registry import registry
    names = [t.name for t in registry.get_all() if t.name != "schedule"]
    return ", ".join(sorted(names))


def _resolve_tool_name(query: str) -> str | None:
    """ค้นหา tool จาก query — ดูชื่อ, commands, description จาก registry"""
    from tools.registry import registry

    query_lower = query.strip().lower()
    if not query_lower:
        return None

    # 1. Exact match on name
    if registry.get_tool(query_lower):
        return query_lower

    # 2. Match on command (e.g. "/email" → email_summary)
    for tool in registry.get_all():
        if tool.name == "schedule":
            continue
        for cmd in getattr(tool, "commands", []):
            if query_lower == cmd.lstrip("/"):
                return tool.name

    # 3. Keyword search in name + description
    for tool in registry.get_all():
        if tool.name == "schedule":
            continue
        searchable = f"{tool.name} {getattr(tool, 'description', '')}".lower()
        if query_lower in searchable:
            return tool.name

    return None


async def _resolve_tool_via_llm(query: str) -> str | None:
    """Fallback: ใช้ LLM แปลงชื่อ tool จากภาษาธรรมชาติ"""
    from tools.registry import registry

    tools_list = []
    for t in registry.get_all():
        if t.name == "schedule":
            continue
        tools_list.append(f"{t.name}: {t.description}")

    if not tools_list:
        return None

    try:
        from core.llm import llm_router
        resp = await llm_router.chat(
            messages=[{
                "role": "user",
                "content": (
                    f"ผู้ใช้ต้องการ schedule tool ที่เกี่ยวกับ: '{query}'\n"
                    f"เลือก tool ที่เหมาะสมจากรายการนี้:\n"
                    + "\n".join(f"- {t}" for t in tools_list) + "\n\n"
                    "ตอบแค่ชื่อ tool เดียวเท่านั้น (เช่น email_summary) "
                    "ถ้าไม่มี tool ที่ตรงให้ตอบ NONE"
                ),
            }],
            tier="cheap",
        )
        answer = resp.get("content", "").strip().lower()
        # ตรวจว่า answer เป็นชื่อ tool จริง
        if answer and answer != "none" and registry.get_tool(answer):
            log.info(f"LLM resolved tool: '{query}' → {answer}")
            return answer
    except Exception as e:
        log.warning(f"LLM tool resolution failed: {e}")

    return None


# === Tool Class ===

class ScheduleTool(BaseTool):
    name = "schedule"
    description = "จัดการตารางเวลา — ตั้ง/ลบ/ดู scheduled tasks ที่ bot รันอัตโนมัติ"
    commands = ["/schedule"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "",
                      action: str = "", repeat: str = "", time: str = "",
                      day: str = "", date: str = "", tool_name: str = "",
                      tool_args: str = "", schedule_id: str = "",
                      **kwargs) -> str:
        # LLM path: action ถูกส่งมาตรง
        if action:
            action = action.strip().lower()
            # "once" ใช้ date แทน day
            if repeat == "once" and date and not day:
                day = date
            if action == "add":
                return await self._add(user_id, repeat or "daily", time, day, tool_name, tool_args)
            if action in ("remove", "delete"):
                return self._remove(user_id, schedule_id)
            if action == "list":
                return self._list(user_id)
            return self._usage()

        # Direct command path: parse args
        if not args or not args.strip():
            return self._list(user_id)
        return await self._parse_direct(user_id, args.strip())

    # --- Direct command parsing ---

    async def _parse_direct(self, user_id: str, args: str) -> str:
        tokens = args.split()
        sub = tokens[0].lower()

        if sub == "list":
            return self._list(user_id)

        if sub in ("remove", "delete"):
            if len(tokens) < 2:
                return "ใช้: /schedule remove <id>"
            return self._remove(user_id, tokens[1])

        if sub == "add":
            return await self._parse_add(user_id, tokens[1:])

        # Shorthand: /schedule 07:00 email_summary
        if _TIME_RE.match(sub):
            return await self._parse_add(user_id, tokens)

        # Shorthand: /schedule daily 07:00 email_summary
        if sub in ("daily", "weekday", "weekly", "monthly", "once"):
            return await self._parse_add(user_id, tokens)

        return self._usage()

    async def _parse_add(self, user_id: str, tokens: list[str]) -> str:
        """Parse add tokens: [repeat] [day/date] <HH:MM> <tool> [args...]"""
        if not tokens:
            return self._usage()

        repeat = "daily"
        day = ""
        time_str = ""
        tool = ""
        tool_args_list = []

        i = 0
        # (1) repeat type
        if tokens[i].lower() in ("daily", "weekday", "weekly", "monthly", "once"):
            repeat = tokens[i].lower()
            i += 1

        if i >= len(tokens):
            return self._usage()

        # (2) day/date สำหรับ weekly/monthly/once
        if repeat == "weekly" and not _TIME_RE.match(tokens[i]):
            day = tokens[i]
            i += 1
        elif repeat == "monthly" and not _TIME_RE.match(tokens[i]):
            day = tokens[i]
            i += 1
        elif repeat == "once" and _DATE_RE.match(tokens[i]):
            day = tokens[i]
            i += 1

        if i >= len(tokens):
            return self._usage()

        # (3) time
        time_str = tokens[i]
        i += 1

        # (4) tool name
        if i < len(tokens):
            tool = tokens[i]
            i += 1

        # (5) remaining = tool args
        if i < len(tokens):
            tool_args_list = tokens[i:]

        t_args = " ".join(tool_args_list) if tool_args_list else ""
        return await self._add(user_id, repeat, time_str, day, tool, t_args)

    # --- Core operations ---

    async def _add(self, user_id: str, repeat: str, time_str: str,
                   day: str, tool_name: str, tool_args: str) -> str:
        from tools.registry import registry

        # Default repeat
        if not repeat:
            repeat = "daily"

        # Validate + normalize time (accept "8:47" → "08:47")
        if not time_str:
            return "กรุณาระบุเวลา (HH:MM) เช่น 07:00"
        try:
            time_str = _normalize_time(time_str)
        except ValueError as e:
            return str(e)

        # Validate tool — resolve from registry (name, commands, description)
        tool_name = tool_name.strip() if tool_name else ""
        if not tool_name:
            return f"กรุณาระบุ tool\nที่ใช้ได้: {_available_tools_str()}\nดูรายละเอียด: /help"

        # Step 1: resolve จาก registry (fast, no LLM cost)
        resolved = _resolve_tool_name(tool_name)
        if not resolved:
            # Step 2: fallback ให้ LLM แปลง (handles Thai/ambiguous names)
            resolved = await _resolve_tool_via_llm(tool_name)
        if resolved:
            tool_name = resolved
        else:
            return (
                f"ไม่พบ tool: {tool_name}\n"
                f"ที่ใช้ได้: {_available_tools_str()}\n"
                "ดูรายละเอียด: /help"
            )

        if tool_name == "schedule":
            return "ไม่สามารถ schedule ตัว schedule tool เองได้"

        # Build cron
        try:
            cron_expr = _build_cron(repeat, time_str, day)
        except ValueError as e:
            return str(e)

        # Validate once date is in the future
        if cron_expr.startswith("once:"):
            dt_str = cron_expr[5:]
            try:
                tz = ZoneInfo(TIMEZONE)
                sched_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                if sched_dt <= datetime.now(tz):
                    return f"เวลาที่ระบุผ่านไปแล้ว: {dt_str}"
            except ValueError:
                return f"รูปแบบวันที่/เวลาไม่ถูก: {dt_str}"

        # Check duplicate
        if db.schedule_exists(user_id, tool_name, cron_expr):
            return f"มี schedule นี้อยู่แล้ว: {_cron_to_display(cron_expr)} {tool_name}"

        # Insert
        sid = db.add_schedule(user_id, tool_name, cron_expr, tool_args or "")
        log.info(f"Schedule added: id={sid} user={user_id} {cron_expr} {tool_name}")

        # Reload scheduler live
        try:
            from scheduler import reload_custom_schedules
            reload_custom_schedules()
        except Exception as e:
            log.error(f"reload_custom_schedules failed: {e}")

        args_display = f" ({tool_args})" if tool_args else ""
        return (
            f"✅ เพิ่ม schedule แล้ว (ID: {sid})\n"
            f"  🕐 {_cron_to_display(cron_expr)}\n"
            f"  🔧 {tool_name}{args_display}"
        )

    def _remove(self, user_id: str, schedule_id_str: str) -> str:
        try:
            sid = int(schedule_id_str)
        except (ValueError, TypeError):
            return f"ID ไม่ถูกต้อง: {schedule_id_str}"

        # Owner สามารถลบของใครก็ได้
        user = get_user(user_id)
        if user and is_owner(user):
            sched = db.get_schedule_by_id(sid)
            if not sched or not sched["is_active"]:
                return f"ไม่พบ schedule ID {sid}"
            db.remove_schedule(sid, sched["user_id"])
        else:
            success = db.remove_schedule(sid, user_id)
            if not success:
                return f"ไม่พบ schedule ID {sid} (หรือไม่ใช่ของคุณ)"

        log.info(f"Schedule removed: id={sid} by user={user_id}")

        # Reload scheduler live
        try:
            from scheduler import reload_custom_schedules
            reload_custom_schedules()
        except Exception as e:
            log.error(f"reload_custom_schedules failed: {e}")

        return f"✅ ลบ schedule ID {sid} แล้ว"

    def _list(self, user_id: str) -> str:
        user = get_user(user_id)

        if user and is_owner(user):
            schedules = db.get_active_schedules()
            header = "📋 Schedule ทั้งหมด"
        else:
            schedules = db.get_user_schedules(user_id)
            header = "📋 Schedule ของคุณ"

        if not schedules:
            return f"{header}: (ว่าง)\n\nเพิ่ม: /schedule add 07:00 email_summary"

        lines = [f"{header} ({len(schedules)} รายการ):\n"]
        for s in schedules:
            display = _cron_to_display(s["cron_expr"])
            args_display = f" ({s['args']})" if s.get("args") else ""
            owner_tag = ""
            if user and is_owner(user) and str(s["user_id"]) != str(user_id):
                owner_tag = f" [user:{s['user_id']}]"
            lines.append(f"  [{s['id']}] {display} — {s['tool_name']}{args_display}{owner_tag}")

        lines.append("")
        lines.append("เพิ่ม: /schedule add [repeat] <HH:MM> <tool> [args]")
        lines.append("ลบ:   /schedule remove <id>")
        lines.append(f"repeat: daily, weekday, weekly, monthly, once")
        return "\n".join(lines)

    def _usage(self) -> str:
        return (
            "📋 *Schedule — วิธีใช้*\n\n"
            "/schedule — ดูรายการ\n"
            "/schedule add 07:00 email\\_summary — ทุกวัน\n"
            "/schedule add weekday 08:30 traffic สุขุมวิท — จ-ศ\n"
            "/schedule add weekly mon 09:00 news\\_summary — ทุกจันทร์\n"
            "/schedule add monthly 1 07:00 email\\_summary — ทุกวันที่ 1\n"
            "/schedule add once 2026-03-10 09:00 email\\_summary — ครั้งเดียว\n"
            "/schedule remove 3 — ลบ\n"
            f"\nTools: {_available_tools_str()}"
        )

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ตั้งเวลา/ตั้งนาฬิกาปลุก/schedule ให้ bot รัน tool อัตโนมัติตามเวลาที่กำหนด "
                "ใช้เมื่อผู้ใช้พูดว่า: ตั้งเวลา, เตือน, ทุกเช้า, ทุกวัน, ตอนกี่โมง, "
                "schedule, alarm, remind, cron "
                "เช่น 'ตั้งเวลาเช็คอีเมลทุกเช้า 7 โมง' 'เตือนดูข่าวตอน 8 โมง' "
                "'ตั้งเวลาเช็คอัตราแลกเปลี่ยนตอน 9 โมง' "
                "action=add เพิ่ม, action=remove ลบ, action=list ดูรายการ "
                "ถ้าผู้ใช้บอกเวลาและ tool → add ทันที ถ้าถามว่าตั้งอะไรไว้ → list"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "remove", "list"],
                        "description": "add=เพิ่ม schedule, remove=ลบ, list=ดูรายการ",
                    },
                    "repeat": {
                        "type": "string",
                        "enum": ["daily", "weekday", "weekly", "monthly", "once"],
                        "description": (
                            "daily=ทุกวัน (default), weekday=จันทร์-ศุกร์, "
                            "weekly=ทุกสัปดาห์ (ระบุ day), "
                            "monthly=ทุกเดือน (ระบุ day เป็นวันที่ 1-31), "
                            "once=ครั้งเดียว (ระบุ date)"
                        ),
                    },
                    "time": {
                        "type": "string",
                        "description": (
                            "เวลา HH:MM เช่น 07:00, 08:30, 18:00 "
                            "แปลงจากภาษาไทย: 7โมง=07:00, 8โมงครึ่ง=08:30, "
                            "บ่าย2=14:00, 5โมงเย็น=17:00, 2ทุ่ม=20:00"
                        ),
                    },
                    "day": {
                        "type": "string",
                        "description": (
                            "สำหรับ weekly: mon/tue/wed/thu/fri/sat/sun "
                            "สำหรับ monthly: วันที่ 1-31"
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": "สำหรับ once: YYYY-MM-DD เช่น 2026-03-10",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": (
                            "ชื่อ tool ที่จะ schedule (ใช้ชื่อภาษาอังกฤษ): "
                            "email_summary (เช็คอีเมล/สรุปอีเมล), "
                            "work_email (อีเมลงาน), "
                            "news_summary (ข่าว/สรุปข่าว), "
                            "exchange_rate (อัตราแลกเปลี่ยน/ค่าเงิน), "
                            "traffic (จราจร/เส้นทาง), "
                            "lotto (หวย/สลากกินแบ่ง), "
                            "places (สถานที่ใกล้เคียง)"
                        ),
                    },
                    "tool_args": {
                        "type": "string",
                        "description": "arguments เพิ่มเติม เช่น 'สุขุมวิท' สำหรับ traffic, ไม่บังคับ",
                    },
                    "schedule_id": {
                        "type": "string",
                        "description": "ID ของ schedule ที่จะลบ (สำหรับ action=remove เท่านั้น)",
                    },
                },
                "required": ["action"],
            },
        }
