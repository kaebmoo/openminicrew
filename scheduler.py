"""Scheduler — APScheduler single-process + SQLite jobstore
   - Morning briefing (email summary)
   - Memory cleanup
   - Custom per-user schedules
"""

import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import TIMEZONE, MORNING_BRIEFING_TIME, CHAT_HISTORY_RETENTION_DAYS
from core import db
from core.logger import get_logger
from interfaces.telegram_common import send_message

log = get_logger(__name__)

scheduler = BackgroundScheduler(timezone=TIMEZONE)
_last_run_info = {"last_run": None}


def _run_tool_for_user(user_id: str, chat_id: str, tool_name: str, args: str = ""):
    """Helper: รัน tool แล้วส่งผลไป Telegram"""
    from tools.registry import registry

    tool = registry.get_tool(tool_name)
    if not tool:
        log.warning(f"Scheduled tool not found: {tool_name}")
        return

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(tool.execute(user_id, args))
        finally:
            loop.close()

        send_message(chat_id, result)
        _last_run_info["last_run"] = tool_name

    except Exception as e:
        log.error(f"Scheduled {tool_name} failed for {user_id}: {e}")
        db.log_tool_usage(user_id, tool_name, status="failed", error_message=str(e))
        try:
            send_message(chat_id, f"[Scheduled] {tool_name} ล้มเหลว: {e}")
        except Exception:
            pass


def _cleanup_job():
    """Daily cleanup: chat history + old logs + old emails"""
    try:
        db.cleanup_old_chats(CHAT_HISTORY_RETENTION_DAYS)
        db.cleanup_old_logs(90)
        db.cleanup_old_emails(90)
        _last_run_info["last_run"] = "cleanup"
        log.info("Cleanup completed")
    except Exception as e:
        log.error(f"Cleanup failed: {e}")


def init_scheduler():
    """เริ่ม scheduler + ลง default jobs"""

    # Morning briefing (email summary สำหรับ owner)
    hour, minute = MORNING_BRIEFING_TIME.split(":")
    from core.config import OWNER_TELEGRAM_CHAT_ID

    scheduler.add_job(
        _run_tool_for_user,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=TIMEZONE),
        args=[str(OWNER_TELEGRAM_CHAT_ID), OWNER_TELEGRAM_CHAT_ID, "email_summary"],
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

    scheduler.start()
    log.info(f"Scheduler started with {len(scheduler.get_jobs())} jobs")


def stop_scheduler():
    """Graceful shutdown"""
    if scheduler.running:
        scheduler.shutdown(wait=True)
        log.info("Scheduler stopped")
