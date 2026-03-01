"""Telegram Common — shared logic สำหรับทั้ง polling และ webhook mode
   - send message (with split for long text + markdown to HTML)
   - rate limiting
   - typing indicator
   - message parsing
   - user location cache
"""

import json
import re
import time
import threading
import requests
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import TELEGRAM_BOT_TOKEN
from core.logger import get_logger

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
MAX_MSG_LENGTH = 4096  # Telegram max message length


# ------------------------------------------------------------------
# User Location (persisted in SQLite with configurable TTL)
# ------------------------------------------------------------------


def save_user_location(user_id: str, lat: float, lng: float):
    """บันทึกตำแหน่งล่าสุดของ user ลง DB"""
    from core import db
    db.save_location(str(user_id), lat, lng)
    log.info(f"Saved location for user {user_id}: {lat}, {lng}")


def get_user_location(user_id: str) -> dict | None:
    """ดึงตำแหน่งล่าสุดของ user — return None ถ้าไม่มีหรือหมดอายุ (TTL)"""
    from core import db
    from core.config import LOCATION_TTL_MINUTES
    return db.get_location(str(user_id), ttl_minutes=LOCATION_TTL_MINUTES)


def send_location_request(chat_id: str | int, text: str = "📍 กดปุ่มด้านล่างเพื่อส่งตำแหน่งปัจจุบัน"):
    """ส่ง keyboard button ขอตำแหน่งจาก user"""
    try:
        requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": json.dumps({
                    "keyboard": [[{"text": "📍 ส่งตำแหน่งปัจจุบัน", "request_location": True}]],
                    "resize_keyboard": True,
                    "one_time_keyboard": True,
                }),
            },
            timeout=10,
        )
    except Exception as e:
        log.error(f"Failed to send location request: {e}")


# ------------------------------------------------------------------
# Markdown → Telegram HTML converter
# ------------------------------------------------------------------

def markdown_to_telegram_html(text: str) -> str:
    """แปลง markdown ทั่วไป → Telegram HTML (subset ที่ Telegram รองรับ)

    รองรับ:
        **bold** → <b>bold</b>
        *italic* → <i>italic</i>
        `code` → <code>code</code>
        ```code block``` → <pre>code block</pre>
        [text](url) → <a href="url">text</a>
    """
    # 1. Escape HTML entities ก่อน (ป้องกัน <script> injection)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    # 2. Code blocks (``` ... ```) — ทำก่อน inline code
    text = re.sub(
        r"```(?:\w+)?\n?(.*?)```",
        r"<pre>\1</pre>",
        text,
        flags=re.DOTALL,
    )

    # 3. Inline code (`...`)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # 4. Bold (**...**)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # 5. Italic (*...*) — ระวังไม่ให้จับ ** ที่แปลงแล้ว
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # 6. Links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    return text



class RateLimiter:
    """Simple token bucket rate limiter for Telegram API"""

    def __init__(self, max_per_second: float = 25):
        self._interval = 1.0 / max_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_call = time.time()


_limiter = RateLimiter()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, requests.exceptions.ConnectionError)),
    reraise=True,
)
def send_message(chat_id: str | int, text: str, parse_mode: str = "auto"):
    """
    ส่งข้อความไป Telegram — auto-split ถ้ายาวเกิน

    parse_mode:
        "auto" (default) = แปลง markdown → HTML อัตโนมัติ, fallback plain text
        "HTML" / "Markdown" = ใช้ตามที่กำหนด
        None = ส่ง plain text
    """
    if not text:
        return

    # Auto mode: แปลง markdown → Telegram HTML
    if parse_mode == "auto":
        html_text = markdown_to_telegram_html(text)
        # ลองส่ง HTML ก่อน
        if _send_chunks(chat_id, html_text, "HTML"):
            return
        # Fallback: ส่ง plain text ถ้า HTML fail
        log.warning("HTML send failed, falling back to plain text")
        _send_chunks(chat_id, text, None)
    else:
        _send_chunks(chat_id, text, parse_mode)


def _send_chunks(chat_id: str | int, text: str, parse_mode: str | None) -> bool:
    """ส่งข้อความเป็น chunks — return True ถ้าสำเร็จทั้งหมด"""
    chunks = _split_message(text)
    for chunk in chunks:
        _limiter.wait()
        payload = {"chat_id": chat_id, "text": chunk}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=10)
            if not resp.ok:
                log.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            log.error(f"Telegram send error: {e}")
            return False
    return True


def send_typing(chat_id: str | int):
    """ส่งสถานะ typing ครั้งเดียว"""
    try:
        requests.post(
            f"{API_BASE}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass  # ไม่สำคัญถ้า fail


class TypingIndicator:
    """Context manager: ส่ง typing status ทุก 4 วินาทีจนกว่างานจะเสร็จ

    Usage:
        with TypingIndicator(chat_id):
            result = await long_running_task()
    """

    def __init__(self, chat_id: str | int, interval: float = 4.0):
        self.chat_id = chat_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def _keep_typing(self):
        while not self._stop_event.is_set():
            send_typing(self.chat_id)
            self._stop_event.wait(self.interval)

    def __enter__(self):
        self._thread = threading.Thread(target=self._keep_typing, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)


def _split_message(text: str) -> list[str]:
    """แบ่งข้อความยาวเป็น chunks ไม่เกิน MAX_MSG_LENGTH"""
    if len(text) <= MAX_MSG_LENGTH:
        return [text]

    chunks = []
    while text:
        if len(text) <= MAX_MSG_LENGTH:
            chunks.append(text)
            break

        # หาจุดตัดที่เหมาะสม (newline ก่อน แล้วค่อย space)
        cut = text.rfind("\n", 0, MAX_MSG_LENGTH)
        if cut == -1 or cut < MAX_MSG_LENGTH // 2:
            cut = text.rfind(" ", 0, MAX_MSG_LENGTH)
        if cut == -1 or cut < MAX_MSG_LENGTH // 2:
            cut = MAX_MSG_LENGTH

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    return chunks


def parse_command(text: str) -> tuple[str, str]:
    """
    แยก command กับ args
    "/email --max 10" → ("/email", "--max 10")
    "สรุปเมลให้หน่อย" → ("", "สรุปเมลให้หน่อย")
    """
    text = text.strip()
    if text.startswith("/"):
        parts = text.split(None, 1)
        cmd = parts[0].split("@")[0].lower()  # ตัด @botname ออก
        args = parts[1] if len(parts) > 1 else ""
        return cmd, args
    return "", text
