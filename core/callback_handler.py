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
# { pending_id: {
#     "pending_id": str, "user_id": str, "items": list[dict], "store": str,
#     "source_type": str, "source_hash": str, "created_at": float,
#     # Phase A (confidence + conversational edit):
#     "overall_confidence": str, "is_handwritten": bool,
#     "store_confidence": str, "store_raw_guess": str,
#     "edit_state": None | "awaiting_line_N" | "awaiting_free_text_confirm",
#     "edit_history": list, "chat_id": Any, "message_id": Any, "telemetry_id": int | None,
# } }
_pending_expenses: dict[str, dict] = {}
_pending_lock = threading.Lock()
_PENDING_TTL = 900  # 15 นาที (เผื่อเวลา conversational edit หลายรอบ)

_counter = 0
_counter_lock = threading.Lock()


def store_pending_expense(
    user_id: str,
    items: list[dict],
    store: str = "",
    source_type: str = "",
    source_hash: str = "",
    *,
    overall_confidence: str = "high",
    is_handwritten: bool = False,
    store_confidence: str = "high",
    store_raw_guess: str = "",
    chat_id=None,
    message_id=None,
    telemetry_id=None,
) -> str:
    """เก็บรายการ expense ที่รอ user ยืนยัน → return pending_id

    field ใหม่ (Phase A) เป็น keyword-only optional ทั้งหมด — caller เดิมที่ไม่ส่งมา
    จะได้ค่า default ที่ปลอดภัย (confidence=high, ไม่ใช่ลายมือ, ไม่มี edit state)
    """
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
            "pending_id": pending_id,
            "user_id": user_id,
            "items": items,
            "store": store,
            "source_type": (source_type or "").strip(),
            "source_hash": (source_hash or "").strip(),
            "created_at": now,
            # ---- Phase A: confidence + conversational edit ----
            "overall_confidence": overall_confidence,
            "is_handwritten": is_handwritten,
            "store_confidence": store_confidence,
            "store_raw_guess": store_raw_guess,
            "edit_state": None,
            "edit_history": [],
            "chat_id": chat_id,
            "message_id": message_id,
            "telemetry_id": telemetry_id,
        }
    return pending_id


def has_pending_expense_source(user_id: str, source_type: str, source_hash: str) -> bool:
    """Return True เมื่อมี receipt เดิมรอยืนยันอยู่แล้ว"""
    normalized_source_type = (source_type or "").strip()
    normalized_source_hash = (source_hash or "").strip()
    if not normalized_source_type or not normalized_source_hash:
        return False

    now = time.time()
    with _pending_lock:
        expired = [k for k, v in _pending_expenses.items() if now - v["created_at"] > _PENDING_TTL]
        for key in expired:
            del _pending_expenses[key]

        for pending in _pending_expenses.values():
            if pending["user_id"] != user_id:
                continue
            if pending.get("source_type") == normalized_source_type and pending.get("source_hash") == normalized_source_hash:
                return True
    return False


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


def peek_pending_expense(pending_id: str, user_id: str) -> dict | None:
    """ดู pending โดยไม่ลบ (ใช้ระหว่าง edit flow ที่ต้องคง pending ไว้) —
    None ถ้าไม่เจอ / ผิด user / หมดอายุ. คืน dict ตัวจริง (mutate in place ได้)"""
    with _pending_lock:
        data = _pending_expenses.get(pending_id)
        if not data or data["user_id"] != user_id:
            return None
        if time.time() - data["created_at"] > _PENDING_TTL:
            return None
        return data


def get_active_edit_pending(user_id: str) -> dict | None:
    """หา pending expense ที่กำลังอยู่ใน edit mode (edit_state != None) ของ user

    Read-only scan — ไม่ลบ entry ที่หมดอายุ (ปล่อยให้ pop/store เป็นจุดเดียวที่ cleanup)
    คืน pending dict ตัวจริงใน _pending_expenses (mutate in place ได้) หรือ None
    """
    now = time.time()
    with _pending_lock:
        for pending in _pending_expenses.values():
            if pending.get("user_id") != user_id:
                continue
            if pending.get("edit_state") is None:
                continue
            if now - pending["created_at"] > _PENDING_TTL:
                continue
            return pending
    return None


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

    elif data.startswith("consent:"):
        result = _handle_consent_callback(user_id, data)
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

    elif data.startswith("exp_edit:"):
        pending_id = data.replace("exp_edit:", "")
        _handle_expense_edit_start(user_id, pending_id, chat_id, message_id)
        if callback_id:
            answer_callback_query(callback_id)

    elif data.startswith("exp_type_manually:"):
        pending_id = data.replace("exp_type_manually:", "")
        result = _handle_expense_type_manually(user_id, pending_id)
        if message_id and chat_id:
            edit_message_text(chat_id, message_id, result)
        if callback_id:
            answer_callback_query(callback_id)

    elif data.startswith("exp_edit_done:"):
        pending_id = data.replace("exp_edit_done:", "")
        _handle_expense_edit_done(user_id, pending_id, chat_id, message_id)
        if callback_id:
            answer_callback_query(callback_id)

    elif data.startswith("exp_apply_freetext:"):
        pending_id = data.replace("exp_apply_freetext:", "")
        _handle_apply_freetext(user_id, pending_id, chat_id, message_id)
        if callback_id:
            answer_callback_query(callback_id)

    elif data.startswith("exp_cancel_freetext:"):
        pending_id = data.replace("exp_cancel_freetext:", "")
        _handle_cancel_freetext(user_id, pending_id, chat_id, message_id)
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
    source_type = pending.get("source_type", "")
    source_hash = pending.get("source_hash", "")

    lines = [f"💸 บันทึกแยก {len(items)} รายการแล้ว:"]
    total = 0.0
    receipt_date = ""
    for item in items:
        amount = item["amount"]
        category = item.get("category", "ทั่วไป")
        note = item.get("note", "")
        if store and store not in note:
            note = f"{store} — {note}" if note else store
        item_date = item.get("receipt_date", "")
        receipt_date = receipt_date or item_date

        expense_id = db.add_expense(
            user_id,
            amount=amount,
            category=category,
            note=note,
            expense_date=item_date,
            source_type=source_type,
            source_hash=source_hash,
        )
        line = f"  [#{expense_id}] {amount:,.2f} บาท — {category}"
        if note:
            line += f": {note}"
        lines.append(line)
        total += amount

    if len(items) > 1:
        lines.append(f"\nรวม {total:,.2f} บาท")
    if receipt_date:
        lines.append(f"วันที่: {receipt_date}")
    return "\n".join(lines)


def _handle_expense_combine(user_id: str, pending_id: str) -> str:
    """รวมทุกรายการเป็น 1 รายการเดียว"""
    from core import db

    pending = pop_pending_expense(pending_id, user_id)
    if not pending:
        return "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่"

    items = pending["items"]
    store = pending.get("store", "")
    source_type = pending.get("source_type", "")
    source_hash = pending.get("source_hash", "")
    total = sum(it["amount"] for it in items)
    receipt_date = next((it.get("receipt_date", "") for it in items if it.get("receipt_date")), "")

    # ใช้หมวดหมู่จากรายการที่แพงที่สุด
    main_item = max(items, key=lambda x: x["amount"])
    category = main_item.get("category", "ทั่วไป")

    # รวม note
    notes = [it.get("note", "") for it in items if it.get("note")]
    note = store
    if notes:
        combined = ", ".join(n for n in notes[:3])  # จำกัด 3 รายการ
        note = f"{store} — {combined}" if store else combined

    expense_id = db.add_expense(
        user_id,
        amount=total,
        category=category,
        note=note,
        expense_date=receipt_date,
        source_type=source_type,
        source_hash=source_hash,
    )
    date_hint = f"\n  วันที่: {receipt_date}" if receipt_date else ""
    return f"💸 บันทึกรวม 1 รายการแล้ว\n  [#{expense_id}] {total:,.2f} บาท — {category}: {note}{date_hint}"


def _handle_consent_callback(user_id: str, data: str) -> str:
    """จัดการ consent callback จาก inline keyboard

    data format: consent:<type>:<on|off>
    เช่น consent:location:on, consent:location:off
    """
    from core import db

    parts = data.split(":")
    if len(parts) != 3:
        return "❌ ข้อมูล callback ไม่ถูกต้อง"

    _, consent_type_short, action = parts

    consent_map = {
        "location": db.CONSENT_LOCATION,
        "chat": db.CONSENT_CHAT_HISTORY,
        "gmail": db.CONSENT_GMAIL,
    }
    consent_type = consent_map.get(consent_type_short)
    if not consent_type:
        return f"❌ ไม่รู้จัก consent type: {consent_type_short}"

    if action not in ("on", "off"):
        return f"❌ action ไม่ถูกต้อง: {action}"

    granted = action == "on"
    status = db.CONSENT_STATUS_GRANTED if granted else db.CONSENT_STATUS_REVOKED
    db.set_user_consent(user_id, consent_type, status, source="inline_keyboard")

    # ข้อความตอบกลับตาม consent type
    _CONSENT_RESPONSES = {
        "chat": {
            "on": "✅ เปิดเก็บประวัติสนทนาแล้ว\nระบบจะจำบริบทการสนทนาเพื่อตอบได้ต่อเนื่อง\n\nพิมพ์ /help เพื่อดูเครื่องมือทั้งหมด หรือพิมพ์คำถามได้เลย",
            "off": "🔒 ปิดเก็บประวัติสนทนาแล้ว\nระบบจะไม่จำบริบทก่อนหน้า แต่ใช้งานได้ตามปกติ\n\nพิมพ์ /help เพื่อดูเครื่องมือทั้งหมด หรือพิมพ์คำถามได้เลย",
        },
        "location": {
            "on": "✅ อนุญาตเก็บตำแหน่งแล้ว\nส่งตำแหน่งได้เลย 📍 (กดปุ่ม 📎 → Location)",
            "off": "🔒 ไม่เก็บตำแหน่ง\nฟีเจอร์ค้นหาสถานที่ใกล้เคียงจะใช้ไม่ได้ เปลี่ยนใจได้ที่ /consent location on",
        },
        "gmail": {
            "on": "✅ consent gmail = granted",
            "off": "🔒 consent gmail = revoked",
        },
    }
    responses = _CONSENT_RESPONSES.get(consent_type_short, {})
    return responses.get(action, f"✅ consent {consent_type_short} = {status}")


# ============================================================
# Conversational edit (Phase A) — guided + free-text hybrid
# ============================================================

# หมวดหมู่ที่อนุญาตสำหรับ validate operations จาก LLM parse / guided edit
_KNOWN_CATEGORIES = {
    "อาหาร", "เครื่องดื่ม", "เดินทาง", "ช็อปปิ้ง", "ของใช้",
    "สาธารณูปโภค", "สุขภาพ", "บันเทิง", "การศึกษา", "โอนเงิน", "ทั่วไป",
}


def _next_unconfident_line(items: list[dict]) -> int | None:
    """คืนเลขบรรทัด (1-based) แรกที่ confidence != high หรือ None ถ้าทุกบรรทัด high"""
    for i, it in enumerate(items, 1):
        if it.get("confidence", "high") != "high":
            return i
    return None


def _format_edit_line_prompt(items: list[dict], n: int) -> str:
    """ข้อความถามบรรทัด n ในโหมด guided"""
    item = items[n - 1]
    note = item.get("note") or "?"
    amount = item.get("amount", 0)
    raw_guess = item.get("raw_guess", "")
    guess = f' [เดา: "{raw_guess}"]' if raw_guess else ""
    return (
        f'แก้บรรทัด {n}/{len(items)}: "{note}"{guess} — {amount:,.2f}\n'
        f"พิมพ์ชื่อจริง หรือ: ลบ / ข้าม / เสร็จ / ยกเลิกการแก้"
    )


def _send_edit_line_prompt(pending: dict, chat_id, n: int):
    """ส่งคำถามบรรทัด n พร้อมปุ่ม [เสร็จ] (กดแทนพิมพ์ 'เสร็จ' ได้)"""
    from interfaces.telegram_common import send_inline_keyboard
    text = _format_edit_line_prompt(pending["items"], n)
    buttons = [[{"text": "✅ เสร็จ", "callback_data": f"exp_edit_done:{pending['pending_id']}"}]]
    send_inline_keyboard(chat_id, text, buttons)


def _send_final_preview(pending: dict, chat_id):
    """แสดง preview สุดท้ายหลังแก้เสร็จ พร้อมปุ่ม [แยก]/[รวม]/[ยกเลิก] (กลับเข้า flow เดิม)"""
    from interfaces.telegram_common import send_inline_keyboard
    items = pending["items"]
    pending_id = pending["pending_id"]
    total = sum(it["amount"] for it in items)
    lines = ["✅ แก้ไขเสร็จ — ตรวจทานแล้วเลือกบันทึก:"]
    for idx, it in enumerate(items, 1):
        note = it.get("note") or "?"
        lines.append(f"{idx}. {note} — {it['amount']:,.2f} ({it.get('category', 'ทั่วไป')})")
    lines.append(f"\nรวม {total:,.2f} บาท")
    buttons = [
        [
            {"text": f"📋 แยก {len(items)} รายการ", "callback_data": f"exp_split:{pending_id}"},
            {"text": "📦 รวม 1 รายการ", "callback_data": f"exp_combine:{pending_id}"},
        ],
        [{"text": "❌ ยกเลิก", "callback_data": f"exp_cancel:{pending_id}"}],
    ]
    send_inline_keyboard(chat_id, "\n".join(lines), buttons)


def _advance_or_finish(pending: dict, chat_id):
    """หาบรรทัดถัดไปที่ confidence != high → ถ้ามีถามต่อ, ถ้าไม่มีจบ edit → preview สุดท้าย"""
    nxt = _next_unconfident_line(pending["items"])
    if nxt is not None:
        pending["edit_state"] = f"awaiting_line_{nxt}"
        _send_edit_line_prompt(pending, chat_id, nxt)
    else:
        pending["edit_state"] = None
        _send_final_preview(pending, chat_id)


def _apply_operations(items: list[dict], operations: list[dict]) -> int:
    """ใช้ operations (edit/delete/add) กับ items in place → คืนจำนวน op ที่ apply สำเร็จ

    edit/add ทำก่อน (ไม่เลื่อน index ของบรรทัดเดิม), delete ทำหลังสุดเรียงจากมากไปน้อย
    เพื่อให้เลขบรรทัดยังอ้างอิงตำแหน่งเดิมได้ถูกต้อง
    """
    applied = 0
    for op in operations:
        kind = op.get("op")
        if kind == "edit":
            ln = op.get("line")
            if isinstance(ln, int) and 1 <= ln <= len(items):
                it = items[ln - 1]
                if op.get("note"):
                    it["note"] = op["note"]
                if op.get("amount") is not None:
                    try:
                        it["amount"] = float(op["amount"])
                    except (TypeError, ValueError):
                        pass
                if op.get("category"):
                    it["category"] = op["category"]
                it["confidence"] = "high"
                applied += 1
        elif kind == "add":
            try:
                amount = float(op.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            items.append({
                "amount": amount,
                "category": op.get("category", "ทั่วไป"),
                "note": op.get("note", ""),
                "confidence": "high",
                "raw_guess": "",
            })
            applied += 1

    del_lines = sorted(
        (op.get("line") for op in operations
         if op.get("op") == "delete" and isinstance(op.get("line"), int)),
        reverse=True,
    )
    for ln in del_lines:
        if 1 <= ln <= len(items):
            del items[ln - 1]
            applied += 1
    return applied


def _handle_expense_edit_start(user_id: str, pending_id: str, chat_id, message_id):
    """exp_edit — เข้า edit mode, ถามบรรทัดแรกที่ confidence != high (หรือบรรทัด 1 ถ้า high หมด)"""
    from interfaces.telegram_common import edit_message_text
    pending = peek_pending_expense(pending_id, user_id)
    if not pending:
        if chat_id and message_id:
            edit_message_text(chat_id, message_id, "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่")
        return
    pending["chat_id"] = chat_id
    pending["message_id"] = message_id
    items = pending["items"]
    n = _next_unconfident_line(items) or 1
    pending["edit_state"] = f"awaiting_line_{n}"
    # แก้ข้อความต้นทาง (ไม่ส่ง reply_markup) → ปุ่มเดิมหายไป กัน double-click
    if chat_id and message_id:
        edit_message_text(chat_id, message_id, "✏️ เข้าโหมดแก้รายการ — ตอบกลับตามคำถามด้านล่าง")
    _send_edit_line_prompt(pending, chat_id, n)


def _handle_expense_type_manually(user_id: str, pending_id: str) -> str:
    """exp_type_manually — ทิ้ง OCR result, ส่ง template ให้ user พิมพ์เอง (terminal)"""
    from core import db
    pending = pop_pending_expense(pending_id, user_id)
    if not pending:
        return "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่"
    db.update_ocr_action(pending.get("telemetry_id"), "typed_manually")
    return (
        "⌨️ พิมพ์รายการเองได้เลย เช่น:\n"
        "/expense 120 อาหาร ข้าวกะเพรา\n"
        "บันทึกทีละรายการได้ตามต้องการ"
    )


def _handle_expense_edit_done(user_id: str, pending_id: str, chat_id, message_id):
    """exp_edit_done — จบ edit mode → preview สุดท้ายพร้อม [แยก]/[รวม]/[ยกเลิก]"""
    from interfaces.telegram_common import edit_message_text
    pending = peek_pending_expense(pending_id, user_id)
    if not pending:
        if chat_id and message_id:
            edit_message_text(chat_id, message_id, "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่")
        return
    pending["edit_state"] = None
    if chat_id and message_id:
        edit_message_text(chat_id, message_id, "✅ จบการแก้ไข")
    _send_final_preview(pending, chat_id or pending.get("chat_id"))


def _handle_apply_freetext(user_id: str, pending_id: str, chat_id, message_id):
    """exp_apply_freetext — apply staged operations → advance/finish"""
    from interfaces.telegram_common import edit_message_text
    pending = peek_pending_expense(pending_id, user_id)
    if not pending:
        if chat_id and message_id:
            edit_message_text(chat_id, message_id, "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่")
        return
    ops = pending.get("staged_operations") or []
    applied = _apply_operations(pending["items"], ops)
    pending["staged_operations"] = None
    pending["free_text_used"] = True
    pending.setdefault("edit_history", []).append(f"freetext: {applied} ops")
    if chat_id and message_id:
        edit_message_text(chat_id, message_id, f"✅ ปรับ {applied} รายการแล้ว")
    _advance_or_finish(pending, chat_id or pending.get("chat_id"))


def _handle_cancel_freetext(user_id: str, pending_id: str, chat_id, message_id):
    """exp_cancel_freetext — ทิ้ง staged operations → กลับ guided mode ที่บรรทัดเดิม"""
    from interfaces.telegram_common import edit_message_text
    pending = peek_pending_expense(pending_id, user_id)
    if not pending:
        if chat_id and message_id:
            edit_message_text(chat_id, message_id, "⏰ หมดเวลาแล้ว กรุณาส่งรูปใหม่")
        return
    pending["staged_operations"] = None
    return_line = pending.get("edit_return_line") or _next_unconfident_line(pending["items"]) or 1
    pending["edit_state"] = f"awaiting_line_{return_line}"
    if chat_id and message_id:
        edit_message_text(chat_id, message_id, "↩️ ยกเลิกการแก้นี้ กลับไปแก้ทีละบรรทัด")
    _send_edit_line_prompt(pending, chat_id or pending.get("chat_id"), return_line)


def _current_edit_line(pending: dict) -> int | None:
    """ดึงเลขบรรทัดปัจจุบันจาก edit_state 'awaiting_line_N'"""
    state = pending.get("edit_state") or ""
    if state.startswith("awaiting_line_"):
        try:
            return int(state.rsplit("_", 1)[1])
        except ValueError:
            return None
    return None


def _confidence_buttons(pending: dict) -> list:
    """ปุ่มตาม overall_confidence เดิม (ใช้ตอน user ออกจาก edit mode โดยไม่จบการแก้)"""
    pid = pending["pending_id"]
    n = len(pending["items"])
    if pending.get("overall_confidence", "high") == "high":
        return [
            [
                {"text": f"📋 แยก {n} รายการ", "callback_data": f"exp_split:{pid}"},
                {"text": "📦 รวม 1 รายการ", "callback_data": f"exp_combine:{pid}"},
            ],
            [
                {"text": "✏️ แก้รายการ", "callback_data": f"exp_edit:{pid}"},
                {"text": "❌ ยกเลิก", "callback_data": f"exp_cancel:{pid}"},
            ],
        ]
    return [
        [{"text": "✏️ แก้รายการ", "callback_data": f"exp_edit:{pid}"}],
        [
            {"text": "⌨️ พิมพ์เอง", "callback_data": f"exp_type_manually:{pid}"},
            {"text": "❌ ยกเลิก", "callback_data": f"exp_cancel:{pid}"},
        ],
    ]


def _send_exit_edit_preview(pending: dict, chat_id):
    """ออกจาก edit mode (ไม่จบการแก้) → แสดงปุ่มเดิมตาม confidence"""
    from interfaces.telegram_common import send_inline_keyboard
    items = pending["items"]
    total = sum(it["amount"] for it in items)
    lines = ["↩️ ออกจากโหมดแก้ไข — เลือกได้:"]
    for idx, it in enumerate(items, 1):
        lines.append(f"{idx}. {it.get('note') or '?'} — {it['amount']:,.2f} ({it.get('category', 'ทั่วไป')})")
    lines.append(f"\nรวม {total:,.2f} บาท")
    send_inline_keyboard(chat_id, "\n".join(lines), _confidence_buttons(pending))


def _send_freetext_confirm(pending: dict, chat_id, operations: list[dict]):
    """แสดงสรุป operations ที่ parse ได้ พร้อมปุ่ม [ยืนยัน]/[ยกเลิกการแก้]"""
    from interfaces.telegram_common import send_inline_keyboard
    lines = ["จะปรับตามนี้:"]
    for op in operations:
        kind = op.get("op")
        ln = op.get("line")
        if kind == "edit":
            parts = []
            if op.get("note"):
                parts.append(f'ชื่อ→"{op["note"]}"')
            if op.get("amount") is not None:
                parts.append(f'ราคา→{op["amount"]}')
            if op.get("category"):
                parts.append(f'หมวด→{op["category"]}')
            lines.append(f"- แก้บรรทัด {ln}: " + ", ".join(parts))
        elif kind == "delete":
            lines.append(f"- ลบบรรทัด {ln}")
        elif kind == "add":
            lines.append(f'- เพิ่ม "{op.get("note", "")}" {op.get("amount", "")} ({op.get("category", "ทั่วไป")})')
    buttons = [[
        {"text": "✅ ยืนยัน", "callback_data": f"exp_apply_freetext:{pending['pending_id']}"},
        {"text": "✖️ ยกเลิกการแก้", "callback_data": f"exp_cancel_freetext:{pending['pending_id']}"},
    ]]
    send_inline_keyboard(chat_id, "\n".join(lines), buttons)


# keyword ที่บ่งบอกว่าเป็นคำสั่งแก้แบบ free-text (ต้องใช้ LLM parse)
_EDIT_KEYWORDS = ("บรรทัด", "เพิ่ม", "ลบ", "แก้", "ใส่")


async def handle_edit_reply(user_id: str, pending: dict, text: str, chat_id, message_id):
    """ประมวลผลข้อความ text ที่ user ตอบระหว่างอยู่ใน edit mode

    ลำดับ: reserved tokens → ตอบสั้นไม่มี keyword (guided ชื่อใหม่) → free-text (LLM parse + confirm)
    """
    from interfaces.telegram_common import send_message

    text = (text or "").strip()
    if not text:
        return

    # ถ้ากำลังรอ confirm free-text แต่ user พิมพ์ใหม่ → ทิ้ง staged แล้วประมวลผลข้อความใหม่
    if pending.get("edit_state") == "awaiting_free_text_confirm":
        pending["staged_operations"] = None
        ret = pending.get("edit_return_line") or _next_unconfident_line(pending["items"]) or 1
        pending["edit_state"] = f"awaiting_line_{ret}"

    low = text.lower()
    n = _current_edit_line(pending)
    items = pending["items"]

    # ---- Reserved tokens ----
    if low in ("ยกเลิก", "ยกเลิกการแก้"):
        pending["edit_state"] = None
        _send_exit_edit_preview(pending, chat_id)
        return

    if low in ("เสร็จ", "พอ", "จบ"):
        pending["edit_state"] = None
        _send_final_preview(pending, chat_id)
        return

    if low == "ลบ":
        if n and 1 <= n <= len(items):
            del items[n - 1]
            pending.setdefault("edit_history", []).append(f"line {n}: deleted")
        _advance_or_finish(pending, chat_id)
        return

    if low == "ข้าม":
        if n and 1 <= n <= len(items):
            it = items[n - 1]
            raw = it.get("raw_guess", "")
            it["note"] = (f"{raw} (ไม่ชัวร์)") if raw else (it.get("note") or "? (อ่านไม่ออก)")
            it["confidence"] = "high"  # ให้ advance ข้ามบรรทัดนี้
            pending.setdefault("edit_history", []).append(f"line {n}: skipped")
        _advance_or_finish(pending, chat_id)
        return

    # ---- guided (ตอบสั้น ไม่มี keyword) vs free-text ----
    is_short = len(text) < 30
    has_keyword = any(kw in text for kw in _EDIT_KEYWORDS)
    if is_short and not has_keyword:
        if n and 1 <= n <= len(items):
            items[n - 1]["note"] = text
            items[n - 1]["confidence"] = "high"
            pending.setdefault("edit_history", []).append(f"line {n}: -> {text}")
        _advance_or_finish(pending, chat_id)
        return

    # ---- free-text → LLM parse (Step 8 helper) ----
    from core.edit_parser import parse_edit_intent
    parsed = await parse_edit_intent(items, text, user_id=user_id)
    operations = parsed.get("operations") or []
    if not operations:
        send_message(chat_id, "ขอโทษ ไม่เข้าใจคำสั่ง ลองพิมพ์ใหม่ทีละบรรทัด หรือพิมพ์ชื่อรายการตรง ๆ")
        if n:
            _send_edit_line_prompt(pending, chat_id, n)
        return

    pending["staged_operations"] = operations
    pending["edit_return_line"] = n or (_next_unconfident_line(items) or 1)
    pending["edit_state"] = "awaiting_free_text_confirm"
    _send_freetext_confirm(pending, chat_id, operations)
