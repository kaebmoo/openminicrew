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
from core.user_manager import get_user
from core import db
from core.llm import llm_router
from core.logger import get_logger
from interfaces.telegram_common import send_message

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: set webhook / Shutdown: cleanup"""
    # Set webhook
    webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    payload = {"url": webhook_url}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET

    resp = requests.post(f"{API_BASE}/setWebhook", json=payload, timeout=10)
    if resp.ok:
        log.info(f"Webhook set: {webhook_url}")
    else:
        log.error(f"Failed to set webhook: {resp.text}")

    yield

    # Shutdown: delete webhook
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

    data = await request.json()

    # ตอบ 200 ทันที แล้วโยนงานไป background
    background_tasks.add_task(_process_update, data)
    return {"ok": True}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    uptime = time.time() - _start_time

    db_health = db.check_health()
    llm_health = llm_router.health_check()
    last_schedule = db.get_last_scheduler_run()

    return {
        "status": "ok",
        "bot_mode": "webhook",
        "uptime_seconds": round(uptime, 1),
        "db": db_health,
        "llm": llm_health,
        "last_scheduler_run": last_schedule,
        "timestamp": datetime.now().isoformat(),
    }


async def _process_update(data: dict):
    """Background task — ประมวลผล Telegram update"""
    message = data.get("message")
    if not message:
        return

    chat_id = message["chat"]["id"]

    # Auth check
    user = get_user(chat_id)
    if not user:
        log.warning(f"Unauthorized chat_id: {chat_id}")
        return

    user_id = user["user_id"]

    # Handle location message
    location = message.get("location")
    if location:
        from interfaces.telegram_common import save_user_location
        save_user_location(user_id, location["latitude"], location["longitude"])
        send_message(chat_id, "📍 ได้รับตำแหน่งแล้ว! ลองถามได้เลย เช่น \"ร้านกาแฟแถวนี้\" หรือ \"แถวนี้ ไป สยาม\"")
        return

    text = message.get("text", "").strip()
    if not text:
        return

    try:
        from dispatcher import process_message
        await process_message(user_id, user, chat_id, text)

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
            error_message=str(e),
        )


def start_webhook():
    """Start FastAPI server"""
    import uvicorn

    log.info(f"Starting Telegram bot in WEBHOOK mode on port {WEBHOOK_PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=WEBHOOK_PORT)
