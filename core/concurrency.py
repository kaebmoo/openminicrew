"""Concurrency utilities — rate limiting, dedup, semaphore
   ใช้สำหรับป้องกัน spam, duplicate requests, และ API overload
"""

import asyncio
import hashlib
import time
import threading
from collections import defaultdict

from core.logger import get_logger

log = get_logger(__name__)


class UserRateLimiter:
    """Per-user sliding window rate limiter

    จำกัดจำนวน request ต่อ user ภายใน window ที่กำหนด
    ใช้ in-memory — reset เมื่อ restart (ไม่เป็นปัญหาสำหรับ rate limit)

    Usage:
        limiter = UserRateLimiter(max_requests=5, window_seconds=60)
        if not limiter.allow(user_id):
            return "ส่งข้อความเร็วเกินไป"
    """

    def __init__(self, max_requests: int = 10, window_seconds: float = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, user_id: str) -> bool:
        """Return True ถ้า user ยังไม่เกิน limit"""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            # ลบ timestamps เก่าที่เกิน window
            timestamps = self._timestamps[user_id]
            self._timestamps[user_id] = [t for t in timestamps if t > cutoff]

            if len(self._timestamps[user_id]) >= self.max_requests:
                log.warning(
                    f"Rate limit hit: user {user_id} "
                    f"({len(self._timestamps[user_id])}/{self.max_requests} in {self.window_seconds}s)"
                )
                return False

            self._timestamps[user_id].append(now)
            return True

    def remaining(self, user_id: str) -> int:
        """จำนวน request ที่เหลือใน window ปัจจุบัน"""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            active = [t for t in self._timestamps.get(user_id, []) if t > cutoff]
            return max(0, self.max_requests - len(active))


class RequestDedup:
    """Request deduplication — ป้องกัน user กดส่งซ้ำ

    ตรวจจับข้อความเดียวกันจาก user เดียวกัน ภายใน ttl_seconds
    ใช้ hash ของ (user_id + text) เป็น key

    Usage:
        dedup = RequestDedup(ttl_seconds=5)
        if dedup.is_duplicate(user_id, text):
            return  # skip
    """

    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _make_key(self, user_id: str, text: str) -> str:
        raw = f"{user_id}:{text}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_duplicate(self, user_id: str, text: str) -> bool:
        """Return True ถ้าเป็นข้อความซ้ำ"""
        now = time.time()
        key = self._make_key(user_id, text)

        with self._lock:
            # Cleanup: ลบ entries ที่หมดอายุ (ทำทุกครั้งเพื่อป้องกัน memory leak)
            expired = [k for k, t in self._seen.items() if now - t > self.ttl_seconds]
            for k in expired:
                del self._seen[k]

            if key in self._seen:
                log.info(f"Duplicate request detected: user {user_id}")
                return True

            self._seen[key] = now
            return False

    def remove(self, user_id: str, text: str):
        """ลบ dedup entry — ให้ user retry ได้หลัง error"""
        key = self._make_key(user_id, text)
        with self._lock:
            self._seen.pop(key, None)


class LLMSemaphore:
    """Global concurrency limit สำหรับ LLM API calls

    ป้องกันไม่ให้ยิง LLM พร้อมกันมากเกินไป → ลด risk ของ 429 Too Many Requests

    หมายเหตุ: ใน polling mode แต่ละ message ใช้ event loop ใหม่ — semaphore
    ต้อง reset ตาม loop ไม่งั้น count ติดค้างข้าม loop และ deadlock ได้

    Usage:
        sem = LLMSemaphore(max_concurrent=5)
        async with sem.acquire():
            result = await llm.chat(...)
    """

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy init — สร้าง semaphore ใหม่ถ้า event loop เปลี่ยน"""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._semaphore is None or self._loop is not current_loop:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._loop = current_loop

        return self._semaphore

    def acquire(self):
        """Return async context manager สำหรับ acquire/release"""
        return self._get_semaphore()


# === Singletons ===

# Per-user: 10 messages ต่อ 60 วินาที
user_rate_limiter = UserRateLimiter(max_requests=10, window_seconds=60)

# Dedup: ข้อความเดียวกันภายใน 5 วินาที ถือว่าซ้ำ
request_dedup = RequestDedup(ttl_seconds=5.0)

# LLM: สูงสุด 5 calls พร้อมกัน
llm_semaphore = LLMSemaphore(max_concurrent=5)
