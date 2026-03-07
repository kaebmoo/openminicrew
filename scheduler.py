"""Scheduler — APScheduler single-process + SQLite jobstore
   - Custom per-user schedules (from DB)
   - Morning briefing seeded as default schedule
   - Memory cleanup
   - Watchdog + heartbeat for reliability
"""

import asyncio
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from core.config import (
    TIMEZONE, MORNING_BRIEFING_TIME, MORNING_BRIEFING_TOOL,
    CHAT_HISTORY_RETENTION_DAYS, TOOL_EXEC_TIMEOUT,
    MISSED_JOB_WINDOW_HOURS, HEARTBEAT_INTERVAL_MINUTES,
    TOOL_LOG_RETENTION_DAYS, EMAIL_LOG_RETENTION_DAYS,
    PENDING_MSG_RETENTION_DAYS, JOB_RUN_RETENTION_DAYS,
)
from core import db
from core.logger import get_logger
from interfaces.telegram_common import send_message

log = get_logger(__name__)


def _apscheduler_listener(event):
    """Log APScheduler job events เข้าระบบ log ของเรา"""
    if event.code == EVENT_JOB_MISSED:
        log.warning(f"[APScheduler] Job MISSED: {event.job_id}")
    elif event.code == EVENT_JOB_ERROR:
        log.error(
            f"[APScheduler] Job ERROR: {event.job_id} — {event.exception}\n"
            f"{traceback.format_tb(event.traceback)[-1] if event.traceback else ''}"
        )
    elif event.code == EVENT_JOB_EXECUTED:
        log.info(f"[APScheduler] Job OK: {event.job_id}")

scheduler = BackgroundScheduler(
    timezone=TIMEZONE,
    job_defaults={"misfire_grace_time": 3600, "coalesce": True},
)
_last_run_info = {"last_run": None}


# === Tool execution for scheduled jobs ===

def _run_tool_for_user(user_id: str, chat_id: str, tool_name: str, args: str = "",
                       job_id: str = None, scheduled_at: str = None,
                       schedule_id: int = None):
    """Helper: รัน tool แล้วส่งผลไป Telegram — retry + save pending ถ้าส่งไม่ได้"""
    log.info(f"[Scheduled] Starting {tool_name} for user={user_id}, chat={chat_id}")
    try:
        success = _run_tool_for_user_inner(user_id, chat_id, tool_name, args)
        if job_id and scheduled_at:
            status = "success" if success else "failed"
            db.log_job_run(job_id, scheduled_at, status=status)

        # Auto-deactivate "once" schedules หลังรันสำเร็จ
        if success and schedule_id:
            sched = db.get_schedule_by_id(schedule_id)
            if sched and sched.get("cron_expr", "").startswith("once:"):
                db.remove_schedule(schedule_id, user_id)
                log.info(f"[Scheduled] Auto-deactivated once schedule id={schedule_id}")

    except Exception as e:
        log.error(
            f"[Scheduled] Unhandled exception in {tool_name} for {user_id}: {e}\n"
            + traceback.format_exc()
        )
        if job_id and scheduled_at:
            try:
                db.log_job_run(job_id, scheduled_at, status="failed")
            except Exception:
                pass


def _run_tool_for_user_inner(user_id: str, chat_id: str, tool_name: str, args: str = ""):
    from tools.registry import registry

    tool = registry.get_tool(tool_name)
    if not tool:
        log.warning(f"Scheduled tool not found: {tool_name}")
        return False

    # Step 1: รัน tool เพื่อได้ผลลัพธ์
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                asyncio.wait_for(tool.execute(user_id, args), timeout=TOOL_EXEC_TIMEOUT)
            )
        finally:
            loop.close()
    except Exception as e:
        log.error(f"Scheduled {tool_name} failed for {user_id}: {e}\n{traceback.format_exc()}")
        db.log_tool_usage(user_id, tool_name, status="failed", error_message=str(e))
        result = f"[Scheduled] {tool_name} ล้มเหลว: {e}"

    # Step 2: ส่ง Telegram — send_message มี tenacity retry 3 ครั้ง (1-5s backoff) อยู่แล้ว
    # ถ้ายังส่งไม่ได้ → save pending ทันที (ไม่ block scheduler thread)
    try:
        send_message(chat_id, result)
        _last_run_info["last_run"] = tool_name
        log.info(f"Scheduled {tool_name} sent to {chat_id}")
        return True
    except Exception as e:
        log.warning(f"Scheduled send failed for {chat_id}: {e} — saving to pending")
        db.save_pending_message(chat_id, result, source=f"scheduled:{tool_name}")
        return False


def flush_pending(chat_id: str):
    """ส่งข้อความค้างส่งทั้งหมดสำหรับ chat_id นี้ — เรียกจาก dispatcher ตอนส่งสำเร็จ"""
    pending = db.get_pending_messages(chat_id)
    if not pending:
        return

    for msg in pending:
        try:
            header = f"📬 *ข้อความค้างส่ง* ({msg['source']}, {msg['created_at'][:16]}):\n\n"
            send_message(chat_id, header + msg["message"])
            db.delete_pending_message(msg["id"])
            log.info(f"Flushed pending message {msg['id']} to {chat_id}")
        except Exception as e:
            log.warning(f"Failed to flush pending {msg['id']}: {e} — will retry later")
            break  # หยุดส่ง ถ้ายังส่งไม่ได้


# === System jobs ===

def _flush_all_pending():
    """Periodic: ส่ง pending messages ทุก user — เผื่อ user ไม่ได้ interact"""
    try:
        users = db.get_all_users()
        for u in users:
            if u["is_active"]:
                flush_pending(str(u["telegram_chat_id"]))
    except Exception as e:
        log.warning(f"Periodic flush_pending failed: {e}")


def _heartbeat_job():
    """Heartbeat: log ว่า scheduler thread ยัง alive"""
    log.info("[Heartbeat] Scheduler is alive")


def _cleanup_job():
    """Daily cleanup: chat history + old logs + old emails + old pending + old job_runs"""
    try:
        db.cleanup_old_chats(CHAT_HISTORY_RETENTION_DAYS)
        db.cleanup_old_logs(TOOL_LOG_RETENTION_DAYS)
        db.cleanup_old_emails(EMAIL_LOG_RETENTION_DAYS)
        db.cleanup_old_pending(PENDING_MSG_RETENTION_DAYS)
        db.cleanup_old_job_runs(JOB_RUN_RETENTION_DAYS)
        _last_run_info["last_run"] = "cleanup"
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Cleanup failed: {e}")


# === Schedule helpers ===

def _make_trigger(cron_expr: str):
    """สร้าง APScheduler trigger จาก cron_expr — รองรับ cron ปกติและ 'once:...'"""
    if cron_expr.startswith("once:"):
        dt_str = cron_expr[5:]  # "2026-03-10 09:00"
        tz = ZoneInfo(TIMEZONE)
        run_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        return DateTrigger(run_date=run_date, timezone=TIMEZONE)
    return CronTrigger.from_crontab(cron_expr, timezone=TIMEZONE)


def _seed_default_schedules():
    """Seed owner's morning briefing เป็น DB row ถ้ายังไม่มี"""
    from core.config import OWNER_TELEGRAM_CHAT_ID
    from tools.registry import registry

    owner_id = str(OWNER_TELEGRAM_CHAT_ID)
    tool_name = MORNING_BRIEFING_TOOL

    # Validate time format
    try:
        hour, minute = MORNING_BRIEFING_TIME.split(":")
        hour, minute = int(hour), int(minute)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        log.error(
            f"MORNING_BRIEFING_TIME ไม่ถูกต้อง: '{MORNING_BRIEFING_TIME}' "
            f"(ต้องเป็น HH:MM เช่น 07:00) — ข้าม seed"
        )
        return

    # Validate tool exists
    if not registry.get_tool(tool_name):
        available = [t.name for t in registry.get_all() if t.name != "schedule"]
        log.error(
            f"MORNING_BRIEFING_TOOL ไม่พบ: '{tool_name}' "
            f"(ใช้ได้: {', '.join(available)}) — ข้าม seed"
        )
        return

    cron_expr = f"{minute} {hour} * * *"

    if not db.schedule_exists(owner_id, tool_name, cron_expr):
        db.add_schedule(owner_id, tool_name, cron_expr)
        log.info(f"Seeded default schedule: {tool_name} at {MORNING_BRIEFING_TIME}")
    else:
        log.info(f"Default schedule already exists ({tool_name} {MORNING_BRIEFING_TIME}) — skip seed")


def _load_custom_schedules():
    """Load all active schedules from DB → register as APScheduler jobs"""
    custom_schedules = db.get_active_schedules()
    loaded = 0
    for sched in custom_schedules:
        try:
            user = db.get_user_by_chat_id(sched["user_id"])
            if not user:
                continue

            # Skip "once" schedules ที่ผ่านไปแล้ว
            cron_expr = sched["cron_expr"]
            if cron_expr.startswith("once:"):
                dt_str = cron_expr[5:]
                tz = ZoneInfo(TIMEZONE)
                try:
                    run_date = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                    if run_date <= datetime.now(tz):
                        db.remove_schedule(sched["id"], sched["user_id"])
                        log.info(f"Auto-deactivated expired once schedule id={sched['id']}")
                        continue
                except ValueError:
                    log.warning(f"Invalid once schedule format: {cron_expr}")
                    continue

            job_id = f"custom_{sched['id']}"
            scheduler.add_job(
                _run_tool_for_user,
                trigger=_make_trigger(cron_expr),
                args=[sched["user_id"], user["telegram_chat_id"],
                      sched["tool_name"], sched.get("args", "")],
                kwargs={"job_id": job_id, "schedule_id": sched["id"]},
                id=job_id,
                replace_existing=True,
                name=f"Custom: {sched['tool_name']} for {sched['user_id']}",
            )
            loaded += 1
        except Exception as e:
            log.error(f"Failed to load schedule {sched['id']}: {e}")
    return loaded


def reload_custom_schedules():
    """Remove all custom_* jobs → reload from DB — เรียกจาก schedule tool หลัง add/remove"""
    if not scheduler.running:
        log.warning("Scheduler not running — skip reload")
        return

    # Remove existing custom jobs
    for job in scheduler.get_jobs():
        if job.id.startswith("custom_"):
            scheduler.remove_job(job.id)

    loaded = _load_custom_schedules()
    log.info(f"Reloaded {loaded} custom schedules")


# === Catchup: ตรวจ missed jobs ===

def check_missed_jobs():
    """ตรวจทุก active schedule ว่ามี job ที่ miss ใน 12 ชม. ที่ผ่านมาหรือไม่ → catchup"""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    cutoff = now - timedelta(hours=MISSED_JOB_WINDOW_HOURS)

    schedules = db.get_active_schedules()
    for sched in schedules:
        try:
            cron_expr = sched["cron_expr"]

            # Skip "once" schedules — ไม่ต้อง catchup
            if cron_expr.startswith("once:"):
                continue

            # Parse cron เพื่อหาเวลาที่ควรรัน
            parts = cron_expr.split()
            if len(parts) < 5:
                continue

            sched_minute, sched_hour = int(parts[0]), int(parts[1])
            dom, _month, dow = parts[2], parts[3], parts[4]

            # คำนวณว่าวันนี้ควรรันตอนไหน
            today_scheduled = now.replace(
                hour=sched_hour, minute=sched_minute, second=0, microsecond=0
            )

            # ตรวจว่าวันนี้ตรงกับ cron pattern หรือไม่
            today_weekday = now.weekday()  # Monday=0
            # Convert Python weekday (Mon=0) to cron weekday (Sun=0)
            cron_weekday = (today_weekday + 1) % 7

            if dow != "*":
                # Check day-of-week: "1-5", "1", etc.
                if "-" in dow:
                    low, high = map(int, dow.split("-"))
                    if not (low <= cron_weekday <= high):
                        continue
                elif "," in dow:
                    if cron_weekday not in map(int, dow.split(",")):
                        continue
                elif cron_weekday != int(dow):
                    continue

            if dom != "*" and now.day != int(dom):
                continue

            # ตรวจว่าเวลาผ่านไปแล้วและอยู่ในช่วง cutoff
            if today_scheduled > now:
                continue  # ยังไม่ถึงเวลา
            if today_scheduled < cutoff:
                continue  # เก่าเกิน 12 ชม.

            # ตรวจว่ารันไปแล้วหรือยัง
            job_id = f"custom_{sched['id']}"
            last_run = db.get_last_job_run(job_id)
            if last_run:
                last_at = datetime.fromisoformat(last_run["scheduled_at"])
                if last_at.date() >= today_scheduled.date():
                    continue  # รันวันนี้แล้ว

            # ยังไม่ได้รัน → catchup
            user = db.get_user_by_chat_id(sched["user_id"])
            if not user:
                continue

            log.warning(
                f"[Catchup] Schedule {sched['id']} ({sched['tool_name']}) "
                f"missed at {today_scheduled.strftime('%H:%M')} — running now"
            )
            _run_tool_for_user(
                sched["user_id"],
                user["telegram_chat_id"],
                sched["tool_name"],
                sched.get("args", ""),
                job_id=job_id,
                scheduled_at=today_scheduled.isoformat(),
                schedule_id=sched["id"],
            )

        except Exception as e:
            log.error(f"[Catchup] Failed for schedule {sched['id']}: {e}")


# === Init / Reload / Stop ===

def _safe_check_missed_jobs():
    """Wrapper สำหรับ one-shot catchup — จับ exception ไม่ให้ crash scheduler"""
    try:
        check_missed_jobs()
    except Exception as e:
        log.error(f"[Catchup] check_missed_jobs failed: {e}\n{traceback.format_exc()}")


def init_scheduler():
    """เริ่ม scheduler + seed defaults + load schedules"""

    # Seed morning briefing ถ้ายังไม่มี
    _seed_default_schedules()

    # Daily cleanup (03:00)
    scheduler.add_job(
        _cleanup_job,
        trigger=CronTrigger(hour=3, minute=0, timezone=TIMEZONE),
        id="daily_cleanup",
        replace_existing=True,
        name="Daily Cleanup",
    )

    # Heartbeat (ช่วย detect ถ้า thread ตาย)
    scheduler.add_job(
        _heartbeat_job,
        trigger=IntervalTrigger(minutes=HEARTBEAT_INTERVAL_MINUTES),
        id="heartbeat",
        replace_existing=True,
        name="Scheduler Heartbeat",
    )

    # Periodic flush pending messages (ทุก 5 นาที)
    scheduler.add_job(
        _flush_all_pending,
        trigger=IntervalTrigger(minutes=5),
        id="flush_pending",
        replace_existing=True,
        name="Flush Pending Messages",
    )

    # Load per-user schedules from DB (includes seeded morning briefing)
    loaded = _load_custom_schedules()

    scheduler.add_listener(
        _apscheduler_listener,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    scheduler.start()

    # Catchup missed jobs — รัน background 10s หลัง start (ไม่ block startup)
    scheduler.add_job(
        _safe_check_missed_jobs,
        trigger=DateTrigger(
            run_date=datetime.now(ZoneInfo(TIMEZONE)) + timedelta(seconds=10),
        ),
        id="catchup_missed",
        replace_existing=True,
        name="Catchup Missed Jobs (one-shot)",
    )

    jobs = scheduler.get_jobs()
    log.info(f"Scheduler started with {len(jobs)} jobs ({loaded} custom)")
    for job in jobs:
        log.info(f"  → {job.id}: next run at {job.next_run_time}")


def is_scheduler_alive() -> bool:
    """ตรวจว่า scheduler thread ยังทำงานอยู่ไหม"""
    if not scheduler.running:
        return False
    # BackgroundScheduler ใช้ _thread — ถ้า thread ตายไป scheduler.running ยังเป็น True
    thread = getattr(scheduler, '_thread', None)
    if thread is None:
        return False
    return thread.is_alive()


def ensure_scheduler_alive():
    """Watchdog: ตรวจและ restart scheduler ถ้า thread ตาย — เรียกจาก polling/webhook"""
    if is_scheduler_alive():
        return

    log.error("[Watchdog] Scheduler thread is DEAD! Restarting...")

    # Shutdown เก่า (ถ้ายังค้าง)
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception:
        pass

    # Re-init scheduler
    try:
        init_scheduler()
        log.info("[Watchdog] Scheduler restarted successfully")
    except Exception as e:
        log.error(f"[Watchdog] Failed to restart scheduler: {e}\n{traceback.format_exc()}")


def stop_scheduler():
    """Graceful shutdown"""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        log.info("Scheduler stopped")
