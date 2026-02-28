"""Telegram Long Polling Mode — ดึง update จาก Telegram API แบบ loop"""

import asyncio
import requests

from core.config import TELEGRAM_BOT_TOKEN
from core.user_manager import get_user
from core.logger import get_logger

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def start_polling():
    """Start long polling loop — blocking"""
    log.info("Starting Telegram bot in POLLING mode...")

    # ลบ webhook เก่า (ถ้ามี)
    requests.post(f"{API_BASE}/deleteWebhook")

    offset = None

    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=35)

            if not resp.ok:
                log.warning(f"getUpdates failed: {resp.status_code}")
                import time as _time
                _time.sleep(5)
                continue

            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                _handle_update(update)

        except KeyboardInterrupt:
            log.info("Polling stopped by user")
            break
        except Exception as e:
            log.error(f"Polling error: {e}")
            import time
            time.sleep(5)


def _handle_update(update: dict):
    """ประมวลผล update — เรียก dispatcher"""
    message = update.get("message")
    if not message:
        return

    text = message.get("text", "").strip()
    if not text:
        return

    chat_id = message["chat"]["id"]

    # Auth check
    user = get_user(chat_id)
    if not user:
        log.warning(f"Unauthorized chat_id: {chat_id}")
        return

    user_id = user["user_id"]

    # Run async dispatcher in sync context
    from dispatcher import process_message

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(process_message(user_id, user, chat_id, text))
        else:
            loop.run_until_complete(process_message(user_id, user, chat_id, text))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_message(user_id, user, chat_id, text))
