"""Telegram Long Polling Mode — ดึง update จาก Telegram API แบบ loop"""

import asyncio
import threading
import requests

from core.config import TELEGRAM_BOT_TOKEN, POLLING_TIMEOUT, POLLING_REQUEST_TIMEOUT
from core.user_manager import get_user
from core.logger import get_logger

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def start_polling():
    """Start long polling loop — blocking"""
    log.info("Starting Telegram bot in POLLING mode...")

    # ตรวจก่อนว่ามี webhook ตั้งอยู่ไหม — ถ้ามี แสดงว่า server production กำลังใช้งาน
    try:
        info = requests.get(f"{API_BASE}/getWebhookInfo", timeout=5).json()
        active_url = info.get("result", {}).get("url", "")
        if active_url:
            log.error("=" * 60)
            log.error(f"ABORT: Webhook กำลังใช้งานอยู่ที่: {active_url}")
            log.error("การรัน polling จะ deleteWebhook และทำให้ server หยุดรับ update!")
            log.error("ถ้าต้องการรัน polling ทดสอบ: ใช้ Bot Token แยกต่างหาก")
            log.error("ถ้าต้องการ override: ตั้ง POLLING_FORCE=true ใน .env")
            log.error("=" * 60)
            import sys, os
            if os.getenv("POLLING_FORCE", "").lower() != "true":
                sys.exit(1)
            log.warning("POLLING_FORCE=true — ลบ webhook และเริ่ม polling (server จะหยุดรับ update)")
    except Exception as e:
        log.warning(f"ไม่สามารถตรวจสอบ webhook info: {e} — ดำเนินการต่อ")

    # ลบ webhook ก่อน polling
    requests.post(f"{API_BASE}/deleteWebhook")

    offset = None
    _watchdog_counter = 0

    while True:
        try:
            # Watchdog: ตรวจ scheduler ทุก ~5 รอบ polling (~2.5 นาที)
            _watchdog_counter += 1
            if _watchdog_counter >= 5:
                _watchdog_counter = 0
                from scheduler import ensure_scheduler_alive
                ensure_scheduler_alive()

            params = {"timeout": POLLING_TIMEOUT, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=POLLING_REQUEST_TIMEOUT)

            if not resp.ok:
                log.warning(f"getUpdates failed: {resp.status_code}")
                import time as _time
                _time.sleep(5)
                continue

            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                log.info(f"Received update_id: {update['update_id']}")
                threading.Thread(
                    target=_handle_update, args=(update,), daemon=True
                ).start()

        except KeyboardInterrupt:
            log.info("Polling stopped by user")
            break
        except requests.exceptions.ReadTimeout:
            continue  # normal long-poll timeout, retry immediately
        except Exception as e:
            log.error(f"Polling error: {e}")
            import time
            time.sleep(5)


def _handle_update(update: dict):
    """ประมวลผล update — เรียก dispatcher"""
    message = update.get("message")
    if not message:
        log.debug(f"Update has no 'message' field: {list(update.keys())}")
        return

    chat_id = message["chat"]["id"]
    log.info(f"Incoming message from chat_id: {chat_id}")

    # Auth check
    user = get_user(chat_id)
    if not user:
        log.warning(f"Unauthorized chat_id: {chat_id}")
        return

    user_id = user["user_id"]

    # Handle location message
    location = message.get("location")
    if location:
        from interfaces.telegram_common import save_user_location, send_message
        save_user_location(user_id, location["latitude"], location["longitude"])
        send_message(chat_id, "📍 ได้รับตำแหน่งแล้ว! ลองถามได้เลย เช่น \"ร้านกาแฟแถวนี้\" หรือ \"แถวนี้ ไป สยาม\"")
        return

    text = message.get("text", "").strip()
    if not text:
        log.info(f"Empty text from chat_id: {chat_id} (message keys: {list(message.keys())})")
        return

    log.info(f"Processing text from {user_id}: {text[:80]}")

    # Run async dispatcher in sync context
    from dispatcher import process_message

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(process_message(user_id, user, chat_id, text))
    except Exception as e:
        log.error(f"process_message failed for {user_id}: {e}", exc_info=True)
    finally:
        loop.close()
        log.info(f"Finished processing for {user_id}")
