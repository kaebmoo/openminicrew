"""Shared pytest fixtures for openminicrew tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _clear_pending_expenses():
    """กัน in-memory state รั่วข้ามเทสต์

    core.callback_handler._pending_expenses เป็น module-global. ตั้งแต่มี text-intercept
    (Phase A) entry ที่ค้างพร้อม edit_state จะถูก get_active_edit_pending() ของเทสต์อื่น
    หยิบไปใช้ → ล้างก่อน/หลังทุกเทสต์เพื่อ isolation
    """
    import core.callback_handler as ch
    with ch._pending_lock:
        ch._pending_expenses.clear()
    yield
    with ch._pending_lock:
        ch._pending_expenses.clear()
