"""Telegram Long Polling Mode — ดึง update จาก Telegram API แบบ loop"""

import asyncio
import concurrent.futures
import json
import threading
import requests

from core.config import TELEGRAM_BOT_TOKEN, POLLING_TIMEOUT, POLLING_REQUEST_TIMEOUT
from core.user_manager import get_user, register_user
from core.logger import get_logger
from interfaces.telegram_common import parse_command, send_message

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class _PollingAsyncRuntime:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def _run_loop(self, loop: asyncio.AbstractEventLoop):
        """รัน event loop กลางสำหรับงาน async ใน polling mode"""
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def ensure_loop(self) -> asyncio.AbstractEventLoop:
        """คืน event loop กลางตัวเดิม หรือสร้างใหม่ถ้ายังไม่มี/ถูกปิดไปแล้ว"""
        with self.lock:
            if self.loop and not self.loop.is_closed() and self.thread and self.thread.is_alive():
                return self.loop

            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop,
                args=(loop,),
                daemon=True,
                name="telegram-polling-async-loop",
            )
            thread.start()

            self.loop = loop
            self.thread = thread
            log.info("Started shared async event loop for polling mode")
            return loop

    def stop(self):
        """หยุด event loop กลางตอนปิด polling"""
        with self.lock:
            if self.loop and not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=2)
            if self.loop and not self.loop.is_closed():
                self.loop.close()

            self.loop = None
            self.thread = None


_async_runtime = _PollingAsyncRuntime()


def _is_expected_dispatch_failure(exc: BaseException) -> bool:
    """ข้อผิดพลาดที่มักเกิดตอน loop กำลังปิด ไม่ต้องพ่น stack trace ยาว"""
    return isinstance(exc, (asyncio.CancelledError, concurrent.futures.CancelledError, TimeoutError)) or (
        isinstance(exc, RuntimeError) and "event loop is closed" in str(exc).lower()
    )


def ensure_shared_async_loop() -> asyncio.AbstractEventLoop:
    """Public helper สำหรับใช้ loop กลางของ polling mode"""
    return _async_runtime.ensure_loop()


def stop_shared_async_loop():
    """Public helper สำหรับหยุด loop กลางของ polling mode"""
    _async_runtime.stop()


def handle_update(update: dict):
    """Public wrapper สำหรับประมวลผล update หนึ่งรายการ"""
    _handle_update(update)


def start_polling():
    """Start long polling loop — blocking"""
    # Readiness check (defense-in-depth — main.py checks too)
    from core.readiness import collect_startup_readiness
    report = collect_startup_readiness(bot_mode="polling")
    if report["should_fail_fast"]:
        failed = [c["name"] for c in report["checks"] if c["status"] == "fail" and c.get("required")]
        log.error("Startup readiness FAILED: %s", failed)
        raise RuntimeError(f"Polling startup blocked: {failed}")
    elif report["status"] != "ok":
        for check in report["checks"]:
            if check["status"] in ("warn", "fail"):
                log.warning("Readiness warning: %s — %s", check["name"], check.get("detail", ""))

    log.info("Starting Telegram bot in POLLING mode...")
    ensure_shared_async_loop()

    # ตรวจก่อนว่ามี webhook ตั้งอยู่ไหม — ถ้ามี แสดงว่า server production กำลังใช้งาน
    try:
        info = requests.get(f"{API_BASE}/getWebhookInfo", timeout=5).json()
        active_url = info.get("result", {}).get("url", "")
        if active_url:
            log.error("ABORT polling: active webhook detected at %s", active_url)
            log.error("Polling would deleteWebhook and stop the webhook receiver")
            log.error("Use a separate bot token for polling tests or set POLLING_FORCE=true to override")
            import sys, os
            if os.getenv("POLLING_FORCE", "").lower() != "true":
                sys.exit(1)
            log.warning("POLLING_FORCE=true enabled, deleting webhook and continuing in polling mode")
    except Exception as e:
        log.warning("Unable to inspect webhook info, continuing in polling mode: %s", e)

    # ลบ webhook ก่อน polling
    requests.post(f"{API_BASE}/deleteWebhook", timeout=10)

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

            params = {"timeout": POLLING_TIMEOUT, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=POLLING_REQUEST_TIMEOUT)

            if not resp.ok:
                log.warning("getUpdates failed with status %s", resp.status_code)
                import time as _time
                _time.sleep(5)
                continue

            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                log.info("Received update_id: %s", update["update_id"])
                threading.Thread(
                    target=_handle_update, args=(update,), daemon=True
                ).start()

        except KeyboardInterrupt:
            log.info("Polling stopped by user")
            stop_shared_async_loop()
            break
        except requests.exceptions.ReadTimeout:
            continue  # normal long-poll timeout, retry immediately
        except Exception as e:
            log.error("Polling error: %s", e)
            import time
            time.sleep(5)


def _handle_update(update: dict):
    """ประมวลผล update — เรียก dispatcher หรือ callback_query"""
    # ---- Inline keyboard callback ----
    callback_query = update.get("callback_query")
    if callback_query:
        try:
            _handle_callback_query(callback_query)
        except Exception as e:
            log.error("Unhandled error in callback_query handler: %s", e, exc_info=True)
            # พยายาม answer เพื่อหยุด loading indicator
            try:
                from interfaces.telegram_common import answer_callback_query
                answer_callback_query(callback_query.get("id", ""), "เกิดข้อผิดพลาด")
            except Exception:
                pass
        return

    message = update.get("message")
    if not message:
        log.debug("Update has no message field: keys=%s", list(update.keys()))
        return

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")
    log.info("Incoming message from chat_id: %s", chat_id)

    text = message.get("text", "").strip()
    command, _args = parse_command(text)

    # Auth check
    user = get_user(chat_id)
    if not user:
        if command == "/start":
            sender = message.get("from", {})
            display_name = sender.get("first_name", "") or sender.get("username", "") or str(chat_id)
            user = register_user(chat_id, display_name)
            if str(chat_id) != str(user.get("telegram_chat_id")):
                user = get_user(chat_id) or user
            from core.config import OWNER_TELEGRAM_CHAT_ID
            if str(chat_id) != str(OWNER_TELEGRAM_CHAT_ID):
                send_message(OWNER_TELEGRAM_CHAT_ID, f"🔔 ผู้ใช้ใหม่ลงทะเบียนแล้ว: {display_name} (chat_id: {chat_id})")
        else:
            log.warning("Unauthorized chat_id: %s", chat_id)
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
        # Telegram ส่ง photo เป็น array (หลายขนาด) — ใช้ตัวใหญ่สุด
        file_id = photo_list[-1]["file_id"]
        caption = message.get("caption", "").strip()
        text = f"__photo:{file_id}" + (f" {caption}" if caption else "")

    if not text:
        log.info("Empty text from chat_id: %s (message keys: %s)", chat_id, list(message.keys()))
        return

    log.info("Processing text from %s: %s", user_id, text[:80])

    # Run async dispatcher in sync context
    from dispatcher import process_message
    loop = _async_runtime.ensure_loop()
    future = asyncio.run_coroutine_threadsafe(
        process_message(user_id, user, chat_id, text, message_id=message_id),
        loop,
    )
    try:
        future.result()
    except Exception as e:
        if _is_expected_dispatch_failure(e):
            log.warning("process_message interrupted for %s: %s", user_id, e)
        else:
            log.exception("process_message failed for %s: %s", user_id, e)
    finally:
        log.info("Finished processing for %s", user_id)


def _handle_callback_query(callback_query: dict):
    """ประมวลผล inline keyboard callback"""
    from interfaces.telegram_common import answer_callback_query, edit_message_text
    from core.user_manager import get_user
    from core.callback_handler import handle_callback

    callback_id = callback_query.get("id", "")
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    from_user = callback_query.get("from", {})
    telegram_chat_id = from_user.get("id") or chat_id

    log.info("Callback query received: from=%s, data=%s, chat=%s, msg=%s",
             telegram_chat_id, data, chat_id, message_id)

    user = get_user(telegram_chat_id)
    if not user:
        log.warning("Callback from unregistered user: %s", telegram_chat_id)
        answer_callback_query(callback_id, "กรุณาลงทะเบียนก่อน /start")
        return

    user_id = user["user_id"]
    log.info("Callback routing: user=%s, data=%s", user_id, data)

    loop = _async_runtime.ensure_loop()
    future = asyncio.run_coroutine_threadsafe(
        handle_callback(user_id, data, chat_id=chat_id, message_id=message_id, callback_id=callback_id),
        loop,
    )
    try:
        future.result(timeout=30)
        log.info("Callback handled successfully: user=%s, data=%s", user_id, data)
    except Exception as e:
        log.error("Callback handler failed: %s", e, exc_info=True)
        answer_callback_query(callback_id, "เกิดข้อผิดพลาด")
