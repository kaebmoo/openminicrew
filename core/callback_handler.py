"""Callback Handler — ประมวลผล Telegram inline keyboard callbacks

รองรับ callback_data patterns:
  - exp_split:<pending_id>   → บันทึกแยกรายการ
  - exp_combine:<pending_id> → รวมเป็น 1 รายการ
  - exp_cancel:<pending_id>  → ยกเลิก ไม่บันทึก
"""

import threading
import time
from core.logger import get_logger

log = get_logger(__name__)

# ---- In-memory pending expense storage ----
# { pending_id: {"user_id": str, "items": list[dict], "store": str, "created_at": float} }
_pending_expenses: dict[str, dict] = {}
_pending_lock = threading.Lock()
_PENDING_TTL = 300  # 5 นาที

_counter = 0
_counter_lock = threading.Lock()


def store_pending_expense(user_id: str, items: list[dict], store: str = "") -> str:
    """เก็บรายการ expense ที่รอ user ยืนยัน → return pending_id"""
    global _counter
    with _counter_lock:
        _counter += 1
        pending_id = f"pe{_counter}_{int(time.time()) % 100000}"

    with _pending_lock:
        # Cleanup expired entries
        now = time.time()
        expired = [k for k, v in _pending_expenses.items() if now - v["created_at"] > _PENDING_TTL]
        for k in expired:
            del _pending_expenses[k]

        _pending_expenses[pending_id] = {
            "user_id": user_id,
            "items": items,
            "store": store,
            "created_at": now,
        }
    return pending_id


def pop_pending_expense(pending_id: str, user_id: str) -> dict | None:
    """ดึง pending expense ออกมา (ลบทิ้ง) — return None ถ้าไม่เจอหรือหมดอายุ"""
    with _pending_lock:
        data = _pending_expenses.pop(pending_id, None)
    if not data:
        return None
    if data["user_id"] != user_id:
        # Put it back — wrong user
        with _pending_lock:
            _pending_expenses[pending_id] = data
        return None
    if time.time() - data["created_at"] > _PENDING_TTL:
        return None
    return data


async def handle_callback(user_id: str, data: str, *, chat_id=None, message_id=None, callback_id=None):
    """Route callback_data ไปยัง handler ที่เหมาะสม"""
    from interfaces.telegram_common import answer_callback_query, edit_message_text

    if data.startswith("exp_split:"):
        pending_id = data.replace("exp_split:", "")
        result = _handle_expense_split(user_id, pending_id)
        if message_id and chat_id:
            edit_message_text(chat_id, message_id, result)
        if callback_id:
            answer_callback_query(callback_id)

    elif data.startswith("exp_combine:"):
        pending_id = data.replace("exp_combine:", "")
        result = _handle_expense_combine(user_id, pending_id)
        if message_id and chat_id:
            edit_message_text(chat_id, message_id, result)
        if callback_id:
            answer_callback_query(callback_id)

    elif data.startswith("exp_cancel:"):
        pending_id = data.replace("exp_cancel:", "")
        _pop_or_expired(user_id, pending_id)  # discard
        if message_id and chat_id:
            edit_message_text(chat_id, message_id, "❌ ยกเลิกแล้ว ไม่ได้บันทึกรายจ่าย")
        if callback_id:
            answer_callback_query(callback_id)

    else:
        log.warning("Unknown callback data: %s", data)
        if callback_id:
            answer_callback_query(callback_id, "ไม่รู้จักคำสั่งนี้")


def _pop_or_expired(user_id: str, pending_id: str) -> dict | None:
    """Pop pending or return None with user-friendly handling"""
    return pop_pending_expense(pending_id, user_id)


def _handle_expense_split(user_id: str, pending_id: str) -> str:
    """บันทึกแยกทุกรายการ"""
    from core import db

    pending = pop_pending_expense(pending_id, user_id)
    if not pending:
        return "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่"

    items = pending["items"]
    store = pending.get("store", "")

    lines = [f"💸 บันทึกแยก {len(items)} รายการแล้ว:"]
    total = 0.0
    for item in items:
        amount = item["amount"]
        category = item.get("category", "ทั่วไป")
        note = item.get("note", "")
        if store and store not in note:
            note = f"{store} — {note}" if note else store

        expense_id = db.add_expense(user_id, amount=amount, category=category, note=note)
        line = f"  [#{expense_id}] {amount:,.2f} บาท — {category}"
        if note:
            line += f": {note}"
        lines.append(line)
        total += amount

    if len(items) > 1:
        lines.append(f"\nรวม {total:,.2f} บาท")
    return "\n".join(lines)


def _handle_expense_combine(user_id: str, pending_id: str) -> str:
    """รวมทุกรายการเป็น 1 รายการเดียว"""
    from core import db

    pending = pop_pending_expense(pending_id, user_id)
    if not pending:
        return "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่"

    items = pending["items"]
    store = pending.get("store", "")
    total = sum(it["amount"] for it in items)

    # ใช้หมวดหมู่จากรายการที่แพงที่สุด
    main_item = max(items, key=lambda x: x["amount"])
    category = main_item.get("category", "ทั่วไป")

    # รวม note
    notes = [it.get("note", "") for it in items if it.get("note")]
    note = store
    if notes:
        combined = ", ".join(n for n in notes[:3])  # จำกัด 3 รายการ
        note = f"{store} — {combined}" if store else combined

    expense_id = db.add_expense(user_id, amount=total, category=category, note=note)
    return f"💸 บันทึกรวม 1 รายการแล้ว\n  [#{expense_id}] {total:,.2f} บาท — {category}: {note}"
