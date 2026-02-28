"""Telegram Common — shared logic สำหรับทั้ง polling และ webhook mode
   - send message (with split for long text)
   - rate limiting
   - message parsing
"""

import time
import threading
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import TELEGRAM_BOT_TOKEN
from core.logger import get_logger

log = get_logger(__name__)

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
MAX_MSG_LENGTH = 4096  # Telegram max message length


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
def send_message(chat_id: str | int, text: str, parse_mode: str = None):
    """ส่งข้อความไป Telegram — auto-split ถ้ายาวเกิน"""
    if not text:
        return

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
        except Exception as e:
            log.error(f"Telegram send error: {e}")
            raise


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
