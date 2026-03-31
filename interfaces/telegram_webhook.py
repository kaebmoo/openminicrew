"""Telegram Webhook Mode — FastAPI server
   - ตอบ 200 ทันที
   - ทำงานจริงใน BackgroundTask
   - error handling + user notification
   - /health endpoint
   - secret_token verification
"""

import asyncio
import time
import requests
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException

from core.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET,
    WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_PATH,
)
from core.user_manager import get_user, register_user
from core.api_keys import summarize_workspace_key_hygiene
from core import db
from core.llm import llm_router
from core.logger import get_logger
from core.readiness import STATUS_FAIL, collect_startup_readiness
from interfaces.telegram_common import parse_command, send_message

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_start_time = time.time()


async def _scheduler_watchdog():
    """Background task: ตรวจ scheduler thread ทุก 2.5 นาที → restart ถ้าตาย"""
    from scheduler import ensure_scheduler_alive
    while True:
        await asyncio.sleep(150)
        try:
            ensure_scheduler_alive()
        except Exception as e:
            log.error(f"[Watchdog] Error in scheduler check: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: set webhook + watchdog / Shutdown: cleanup"""
    # Readiness check (defense-in-depth — main.py checks too)
    from core.readiness import collect_startup_readiness
    report = collect_startup_readiness(bot_mode="webhook")
    if report["should_fail_fast"]:
        failed = [c["name"] for c in report["checks"] if c["status"] == "fail" and c.get("required")]
        log.error("Startup readiness FAILED: %s", failed)
        raise RuntimeError(f"Webhook startup blocked: {failed}")
    elif report["status"] != "ok":
        log.warning("Startup readiness warnings: %s", report["status"])

    # Set webhook
    webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    payload = {"url": webhook_url, "allowed_updates": ["message", "callback_query"]}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET

    resp = requests.post(f"{API_BASE}/setWebhook", json=payload, timeout=10)
    if resp.ok:
        log.info(f"Webhook set: {webhook_url}")
    else:
        log.error(f"Failed to set webhook: {resp.text}")

    # Start scheduler watchdog
    watchdog_task = asyncio.create_task(_scheduler_watchdog())
    log.info("[Watchdog] Scheduler watchdog started (interval: 150s)")

    yield

    # Shutdown: cancel watchdog + delete webhook
    watchdog_task.cancel()
    requests.post(f"{API_BASE}/deleteWebhook", timeout=10)
    log.info("Webhook deleted, shutting down")


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """รับ update จาก Telegram — ตอบ 200 ทันที, ทำงานใน background"""

    # Verify secret token
    if TELEGRAM_WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        data = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    # ตอบ 200 ทันที แล้วโยนงานไป background
    background_tasks.add_task(_process_update, data)
    return {"ok": True}


@app.get("/gmail-callback")
async def gmail_callback(code: str = None, state: str = None, error: str = None):
    """รับ Google OAuth callback หลัง user authorize Gmail"""
    from core.gmail_oauth import complete_oauth

    if error:
        log.warning(f"Gmail OAuth denied: {error}")
        return {"error": f"Authorization denied: {error}"}

    if not code or not state:
        return {"error": "Missing code or state"}

    result = complete_oauth(code, state)
    if not result:
        return {"error": "Invalid or expired link. Please use /authgmail again."}

    user_id, chat_id = result

    # อัปเดต DB ให้ gmail_authorized = 1
    try:
        from core.db import get_conn
        from datetime import datetime
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET gmail_authorized = 1, updated_at = ? WHERE user_id = ?",
                (datetime.now().isoformat(), str(user_id)),
            )
    except Exception as db_err:
        log.warning(f"Failed to update gmail_authorized in DB: {db_err}")

    try:
        send_message(int(chat_id), "✅ Gmail authorized เรียบร้อยแล้ว\\! ลองใช้ /email ได้เลย 📬")
    except Exception as e:
        log.error(f"Failed to notify user {user_id} after Gmail auth: {e}")

    return {"ok": True, "message": "Gmail authorized! You can close this window."}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    uptime = time.time() - _start_time

    readiness = collect_startup_readiness(bot_mode="webhook")
    api_key_hygiene = summarize_workspace_key_hygiene()
    audit_summary = db.get_security_audit_summary(hours=24)
    db_health = db.check_health()
    llm_health = llm_router.health_check()
    last_schedule = db.get_last_scheduler_run()
    status = readiness["status"]
    if db_health.get("db") != "ok":
        status = STATUS_FAIL
    elif api_key_hygiene["status"] != "ok" and status == "ok":
        status = "degraded"

    return {
        "status": status,
        "bot_mode": "webhook",
        "uptime_seconds": round(uptime, 1),
        "startup_readiness": readiness,
        "api_key_hygiene": api_key_hygiene,
        "security_audit": audit_summary,
        "db": db_health,
        "llm": llm_health,
        "last_scheduler_run": last_schedule,
        "timestamp": datetime.now().isoformat(),
    }


async def _process_update(data: dict):
    """Background task — ประมวลผล Telegram update"""
    # ---- Inline keyboard callback ----
    callback_query = data.get("callback_query")
    if callback_query:
        await _handle_callback_query(callback_query)
        return

    message = data.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")

    text = message.get("text", "").strip()
    command, _args = parse_command(text)

    # Auth check
    user = get_user(chat_id)
    if not user:
        if command == "/start":
            sender = message.get("from", {})
            display_name = sender.get("first_name", "") or sender.get("username", "") or str(chat_id)
            user = register_user(chat_id, display_name)
            from core.config import OWNER_TELEGRAM_CHAT_ID
            if str(chat_id) != str(OWNER_TELEGRAM_CHAT_ID):
                send_message(OWNER_TELEGRAM_CHAT_ID, f"🔔 ผู้ใช้ใหม่ลงทะเบียนแล้ว: {display_name} (chat_id: {chat_id})")
        else:
            log.warning(f"Unauthorized chat_id: {chat_id}")
            send_message(chat_id, "สวัสดี! ยินดีต้อนรับสู่ OpenMiniCrew\nลงทะเบียนเพื่อเริ่มใช้งาน พิมพ์ /start")
            return

    user_id = user["user_id"]

    # Handle location message
    location = message.get("location")
    if location:
        from interfaces.telegram_common import save_user_location
        saved = save_user_location(user_id, location["latitude"], location["longitude"])
        if saved:
            send_message(chat_id, "📍 ได้รับตำแหน่งแล้ว! ลองถามได้เลย เช่น \"ร้านกาแฟแถวนี้\" หรือ \"แถวนี้ ไป สยาม\"")
        else:
            from interfaces.telegram_common import send_inline_keyboard
            send_inline_keyboard(chat_id,
                "🔒 ยังไม่ได้ให้ consent สำหรับ location\nอนุญาตให้บันทึกตำแหน่งไหม?",
                [[
                    {"text": "✅ อนุญาต", "callback_data": "consent:location:on"},
                    {"text": "❌ ไม่อนุญาต", "callback_data": "consent:location:off"},
                ]]
            )
        return

    # Handle photo messages (e.g. expense receipt)
    photo_list = message.get("photo")
    if photo_list and not text:
        file_id = photo_list[-1]["file_id"]
        caption = message.get("caption", "").strip()
        text = f"__photo:{file_id}" + (f" {caption}" if caption else "")

    if not text:
        return

    try:
        from dispatcher import process_message
        await process_message(user_id, user, chat_id, text, message_id=message_id)

    except Exception as e:
        log.error(f"Background task failed for user {user_id}: {e}")
        # แจ้ง user ว่าเกิดข้อผิดพลาด
        try:
            error_msg = "เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง"
            send_message(chat_id, error_msg)
        except Exception:
            log.error("Failed to send error notification to user")

        # Log เป็น dead letter
        db.log_tool_usage(
            user_id=user_id,
            tool_name="dispatcher",
            status="failed",
            **db.make_log_field("input", text, kind="telegram_message"),
            **db.make_error_fields(str(e)),
        )


async def _handle_callback_query(callback_query: dict):
    """ประมวลผล inline keyboard callback"""
    from interfaces.telegram_common import answer_callback_query, edit_message_text
    from core.callback_handler import handle_callback

    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    from_user = callback_query.get("from", {})
    telegram_chat_id = from_user.get("id") or chat_id

    log.info("Callback query from %s: data=%s", telegram_chat_id, data)

    user = get_user(telegram_chat_id)
    if not user:
        answer_callback_query(callback_id, "กรุณาลงทะเบียนก่อน /start")
        return

    user_id = user["user_id"]

    try:
        await handle_callback(user_id, data, chat_id=chat_id, message_id=message_id, callback_id=callback_id)
    except Exception as e:
        log.error("Callback handler failed: %s", e, exc_info=True)
        answer_callback_query(callback_id, "เกิดข้อผิดพลาด")


def start_webhook():
    """Start FastAPI server"""
    import uvicorn

    log.info(f"Starting Telegram bot in WEBHOOK mode on port {WEBHOOK_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=WEBHOOK_PORT)
