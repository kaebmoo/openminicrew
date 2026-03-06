"""Scheduler — APScheduler single-process + SQLite jobstore
   - Morning briefing (email summary)
   - Memory cleanup
   - Custom per-user schedules
"""

import asyncio
import traceback
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from core.config import TIMEZONE, MORNING_BRIEFING_TIME, CHAT_HISTORY_RETENTION_DAYS
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


def _run_tool_for_user(user_id: str, chat_id: str, tool_name: str, args: str = "",
                       job_id: str = None, scheduled_at: str = None):
    """Helper: รัน tool แล้วส่งผลไป Telegram — retry + save pending ถ้าส่งไม่ได้"""
    log.info(f"[Scheduled] Starting {tool_name} for user={user_id}, chat={chat_id}")
    try:
        success = _run_tool_for_user_inner(user_id, chat_id, tool_name, args)
        if success and job_id and scheduled_at:
            db.log_job_run(job_id, scheduled_at, status="success")
    except Exception as e:
        log.error(
            f"[Scheduled] Unhandled exception in {tool_name} for {user_id}: {e}\n"
            + traceback.format_exc()
        )


def _run_tool_for_user_inner(user_id: str, chat_id: str, tool_name: str, args: str = ""):
    from tools.registry import registry

    tool = registry.get_tool(tool_name)
    if not tool:
        log.warning(f"Scheduled tool not found: {tool_name}")
        return

    # Step 1: รัน tool เพื่อได้ผลลัพธ์
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                asyncio.wait_for(tool.execute(user_id, args), timeout=120)
            )
        finally:
            loop.close()
    except Exception as e:
        log.error(f"Scheduled {tool_name} failed for {user_id}: {e}\n{traceback.format_exc()}")
        db.log_tool_usage(user_id, tool_name, status="failed", error_message=str(e))
        result = f"[Scheduled] {tool_name} ล้มเหลว: {e}"

    # Step 2: ส่ง Telegram — retry with exponential backoff
    max_retries = 5
    for attempt in range(max_retries):
        try:
            send_message(chat_id, result)
            _last_run_info["last_run"] = tool_name
            log.info(f"Scheduled {tool_name} sent to {chat_id} (attempt {attempt + 1})")
            return True  # สำเร็จ → จบ
        except Exception as e:
            wait_seconds = 60 * (2 ** attempt)  # 1m → 2m → 4m → 8m → 16m
            log.warning(
                f"Scheduled send failed (attempt {attempt + 1}/{max_retries}): {e} "
                f"— retry in {wait_seconds}s"
            )
            if attempt < max_retries - 1:
                time.sleep(wait_seconds)

    # Step 3: retry หมด → เก็บไว้ใน pending_messages
    log.error(f"All {max_retries} send attempts failed for {chat_id}. Saving to pending.")
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


def _cleanup_job():
    """Daily cleanup: chat history + old logs + old emails + old pending + old job_runs"""
    try:
        db.cleanup_old_chats(CHAT_HISTORY_RETENTION_DAYS)
        db.cleanup_old_logs(90)
        db.cleanup_old_emails(90)
        db.cleanup_old_pending(7)
        db.cleanup_old_job_runs(30)
        _last_run_info["last_run"] = "cleanup"
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Cleanup failed: {e}")


def _morning_briefing_job():
    """Wrapper สำหรับ morning_briefing cron — คำนวณ scheduled_at ตอน runtime"""
    from core.config import OWNER_TELEGRAM_CHAT_ID
    tz = ZoneInfo(TIMEZONE)
    hour, minute = MORNING_BRIEFING_TIME.split(":")
    now = datetime.now(tz)
    scheduled_at = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    _run_tool_for_user(
        str(OWNER_TELEGRAM_CHAT_ID),
        str(OWNER_TELEGRAM_CHAT_ID),
        "email_summary",
        job_id="morning_briefing",
        scheduled_at=scheduled_at.isoformat(),
    )


def check_missed_jobs():
    """ตรวจว่า job ไหนควรรันใน 12 ชั่วโมงที่ผ่านมาแต่ไม่มีบันทึก → รัน catchup"""
    from core.config import OWNER_TELEGRAM_CHAT_ID

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    hour, minute = MORNING_BRIEFING_TIME.split(":")

    # คำนวณว่า morning_briefing ควรเกิดตอนไหนล่าสุด
    today_scheduled = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if now < today_scheduled:
        # ยังไม่ถึงเวลาวันนี้ → ดูเมื่อวาน
        candidate = today_scheduled - timedelta(days=1)
    else:
        # ผ่านเวลาวันนี้แล้ว → ดูวันนี้
        candidate = today_scheduled

    # ตรวจว่าเกิดภายใน 12 ชั่วโมงที่ผ่านมา
    cutoff = now - timedelta(hours=12)
    if candidate < cutoff:
        log.info("[Catchup] morning_briefing: last scheduled time too old — skip")
        return

    # ตรวจว่ารันไปแล้วหรือยัง
    last_run = db.get_last_job_run("morning_briefing")
    if last_run:
        last_scheduled_at = datetime.fromisoformat(last_run["scheduled_at"])
        if last_scheduled_at.date() >= candidate.date():
            log.info(f"[Catchup] morning_briefing already ran today ({last_run['scheduled_at'][:16]}) — skip")
            return

    log.warning(f"[Catchup] morning_briefing missed at {candidate.strftime('%Y-%m-%d %H:%M')} — running now")
    scheduled_at_str = candidate.isoformat()
    _run_tool_for_user(
        str(OWNER_TELEGRAM_CHAT_ID),
        str(OWNER_TELEGRAM_CHAT_ID),
        "email_summary",
        job_id="morning_briefing",
        scheduled_at=scheduled_at_str,
    )


def init_scheduler():
    """เริ่ม scheduler + ลง default jobs"""

    # Catchup: ตรวจ missed jobs ก่อน start scheduler
    try:
        check_missed_jobs()
    except Exception as e:
        log.error(f"[Catchup] check_missed_jobs failed: {e}\n{traceback.format_exc()}")

    # Morning briefing (email summary สำหรับ owner)
    hour, minute = MORNING_BRIEFING_TIME.split(":")
    from core.config import OWNER_TELEGRAM_CHAT_ID

    scheduler.add_job(
        _morning_briefing_job,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=TIMEZONE),
        id="morning_briefing",
        replace_existing=True,
        name="Morning Email Briefing",
    )

    # Daily cleanup (03:00)
    scheduler.add_job(
        _cleanup_job,
        trigger=CronTrigger(hour=3, minute=0, timezone=TIMEZONE),
        id="daily_cleanup",
        replace_existing=True,
        name="Daily Cleanup",
    )

    # Load per-user schedules from DB
    custom_schedules = db.get_active_schedules()
    for sched in custom_schedules:
        try:
            user = db.get_user_by_chat_id(sched["user_id"])
            if not user:
                continue

            scheduler.add_job(
                _run_tool_for_user,
                trigger=CronTrigger.from_crontab(sched["cron_expr"], timezone=TIMEZONE),
                args=[sched["user_id"], user["telegram_chat_id"],
                      sched["tool_name"], sched.get("args", "")],
                id=f"custom_{sched['id']}",
                replace_existing=True,
                name=f"Custom: {sched['tool_name']} for {sched['user_id']}",
            )
        except Exception as e:
            log.error(f"Failed to load schedule {sched['id']}: {e}")

    scheduler.add_listener(
        _apscheduler_listener,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    scheduler.start()
    jobs = scheduler.get_jobs()
    log.info(f"Scheduler started with {len(jobs)} jobs")
    for job in jobs:
        log.info(f"  → {job.id}: next run at {job.next_run_time}")


def stop_scheduler():
    """Graceful shutdown"""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        log.info("Scheduler stopped")
