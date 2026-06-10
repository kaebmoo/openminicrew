"""Tests for conversational edit flow (Phase A) in core.callback_handler"""

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.callback_handler as ch


# ---- helpers --------------------------------------------------------------

class _Capture:
    """เก็บข้อความ/ปุ่มที่ถูกส่ง แทน Telegram I/O จริง"""
    def __init__(self):
        self.events = []

    def inline(self, chat_id, text, buttons):
        self.events.append(("inline", text, buttons))

    def message(self, chat_id, text, *a, **k):
        self.events.append(("message", text, None))

    def edit(self, chat_id, message_id, text):
        self.events.append(("edit", text, None))
        return True

    def callbacks(self):
        flat = []
        for kind, _text, buttons in self.events:
            if kind == "inline" and buttons:
                for row in buttons:
                    for b in row:
                        flat.append(b["callback_data"])
        return flat

    def last_inline_text(self):
        return [t for k, t, _ in self.events if k == "inline"][-1]


def _patches(cap):
    return (
        patch("interfaces.telegram_common.send_inline_keyboard", cap.inline),
        patch("interfaces.telegram_common.send_message", cap.message),
        patch("interfaces.telegram_common.edit_message_text", cap.edit),
    )


def _mk_pending(items, overall="low"):
    pid = ch.store_pending_expense("u1", items, "ร้าน", overall_confidence=overall)
    return pid, ch._pending_expenses[pid]


def _run_reply(cap, pending, text):
    p_inline, p_msg, p_edit = _patches(cap)
    with p_inline, p_msg, p_edit:
        asyncio.run(ch.handle_edit_reply("u1", pending, text, 555, 1))


def _install_fake_parser(ops, confidence="high"):
    mod = types.ModuleType("core.edit_parser")

    async def parse_edit_intent(items, user_message, user_id=None):
        return {"operations": ops, "confidence": confidence}

    mod.parse_edit_intent = parse_edit_intent
    return patch.dict(sys.modules, {"core.edit_parser": mod})


# ---- guided short-reply ---------------------------------------------------

def test_short_reply_updates_current_line_and_finishes():
    items = [
        {"amount": 90.0, "category": "เครื่องดื่ม", "note": "เบียร์", "confidence": "high", "raw_guess": ""},
        {"amount": 10.0, "category": "เครื่องดื่ม", "note": "?", "confidence": "low", "raw_guess": "น้ำเล็ก"},
    ]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_2"
    cap = _Capture()
    _run_reply(cap, p, "น้ำเปล่า")

    assert p["items"][1]["note"] == "น้ำเปล่า"
    assert p["items"][1]["confidence"] == "high"
    # ไม่เหลือบรรทัด low → จบ → final preview มี split/combine
    assert p["edit_state"] is None
    flat = cap.callbacks()
    assert any(c.startswith("exp_split:") for c in flat)
    assert any(c.startswith("exp_combine:") for c in flat)


def test_short_reply_advances_to_next_unconfident_line():
    items = [
        {"amount": 90.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": "a"},
        {"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": "b"},
    ]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    _run_reply(cap, p, "ข้าวผัด")

    assert p["items"][0]["note"] == "ข้าวผัด"
    # ยังเหลือบรรทัด 2 low → ถามต่อบรรทัด 2 (ยังไม่จบ)
    assert p["edit_state"] == "awaiting_line_2"
    assert "แก้บรรทัด 2/2" in cap.last_inline_text()


# ---- reserved tokens ------------------------------------------------------

def test_reserved_delete_removes_current_line():
    items = [
        {"amount": 90.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""},
        {"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": "x"},
    ]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_2"
    cap = _Capture()
    _run_reply(cap, p, "ลบ")

    assert len(p["items"]) == 1
    assert p["items"][0]["note"] == "ข้าว"
    assert p["edit_state"] is None  # ไม่เหลือ low → จบ


def test_reserved_skip_uses_raw_guess_and_advances():
    items = [
        {"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": "น้ำเล็ก"},
    ]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    _run_reply(cap, p, "ข้าม")

    assert "น้ำเล็ก" in p["items"][0]["note"]
    assert p["items"][0]["confidence"] == "high"
    assert p["edit_state"] is None


def test_reserved_done_finishes_with_split_combine():
    items = [
        {"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""},
        {"amount": 20.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""},
    ]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    _run_reply(cap, p, "เสร็จ")

    assert p["edit_state"] is None
    flat = cap.callbacks()
    assert any(c.startswith("exp_split:") for c in flat)
    assert any(c.startswith("exp_combine:") for c in flat)


def test_reserved_done_single_item_shows_save_button_only():
    items = [{"amount": 10.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""}]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    _run_reply(cap, p, "เสร็จ")

    flat = cap.callbacks()
    assert any(c.startswith("exp_split:") for c in flat)       # [✅ บันทึก]
    assert not any(c.startswith("exp_combine:") for c in flat)  # 1 รายการ ไม่มีปุ่มรวม


def test_reserved_cancel_exits_to_confidence_buttons():
    items = [{"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""}]
    _pid, p = _mk_pending(items, overall="low")
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    _run_reply(cap, p, "ยกเลิกการแก้")

    assert p["edit_state"] is None
    flat = cap.callbacks()
    # low confidence → ปุ่มเดิม = แก้รายการ + พิมพ์เอง (ไม่มี split/combine)
    assert any(c.startswith("exp_type_manually:") for c in flat)
    assert not any(c.startswith("exp_split:") for c in flat)


# ---- free-text (LLM parse) -----------------------------------------------

def test_edit_keyword_routes_to_llm_and_stages_confirm():
    items = [
        {"amount": 90.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""},
        {"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""},
    ]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_2"
    ops = [{"op": "edit", "line": 1, "note": "ข้าวผัด"}]
    cap = _Capture()
    with _install_fake_parser(ops):
        _run_reply(cap, p, "บรรทัด 1 เป็น ข้าวผัด")

    assert p["staged_operations"] == ops
    assert p["edit_state"] == "awaiting_free_text_confirm"
    flat = cap.callbacks()
    assert any(c.startswith("exp_apply_freetext:") for c in flat)
    assert any(c.startswith("exp_cancel_freetext:") for c in flat)
    # ยังไม่ apply จริงจนกว่าจะกดยืนยัน
    assert p["items"][0]["note"] == "ข้าว"


def test_long_reply_without_keyword_routes_to_llm():
    items = [{"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""}]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    ops = [{"op": "edit", "line": 1, "note": "x"}]
    long_text = "ก" * 35  # >= 30 chars, ไม่มี edit-keyword → ยังเข้า LLM
    cap = _Capture()
    with _install_fake_parser(ops):
        _run_reply(cap, p, long_text)

    assert p["edit_state"] == "awaiting_free_text_confirm"


def test_llm_parse_failure_returns_to_guided():
    items = [{"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""}]
    _pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    with _install_fake_parser([], confidence="low"):
        _run_reply(cap, p, "เพิ่มอะไรสักอย่างที่งงมาก ๆ ไม่รู้เรื่อง")

    # ไม่มี ops → ไม่ stage, อยู่ guided ที่บรรทัดเดิม + ถามใหม่
    assert p["edit_state"] == "awaiting_line_1"
    assert p.get("staged_operations") is None
    assert any(k == "message" for k, *_ in cap.events)  # ส่งข้อความ "ไม่เข้าใจ"
    assert "แก้บรรทัด 1/1" in cap.last_inline_text()


# ---- callback handlers (apply / cancel free-text) -------------------------

def test_apply_freetext_applies_staged_ops():
    items = [
        {"amount": 90.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""},
        {"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""},
    ]
    pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_free_text_confirm"
    p["edit_return_line"] = 2
    p["staged_operations"] = [{"op": "edit", "line": 2, "note": "ชาเย็น", "amount": 25}]
    cap = _Capture()
    p_inline, p_msg, p_edit = _patches(cap)
    with p_inline, p_msg, p_edit:
        ch._handle_apply_freetext("u1", pid, chat_id=555, message_id=999)

    assert p["items"][1]["note"] == "ชาเย็น"
    assert p["items"][1]["amount"] == 25.0
    assert p["staged_operations"] is None
    assert p["free_text_used"] is True
    # line2 ตอนนี้ high แล้ว → จบ → final preview
    assert p["edit_state"] is None


def test_cancel_freetext_returns_to_guided_line():
    items = [{"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""}]
    pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_free_text_confirm"
    p["edit_return_line"] = 1
    p["staged_operations"] = [{"op": "delete", "line": 1}]
    cap = _Capture()
    p_inline, p_msg, p_edit = _patches(cap)
    with p_inline, p_msg, p_edit:
        ch._handle_cancel_freetext("u1", pid, chat_id=555, message_id=999)

    assert p["staged_operations"] is None
    assert p["edit_state"] == "awaiting_line_1"
    assert len(p["items"]) == 1  # ไม่ได้ลบจริง


# ---- regression: review findings ------------------------------------------

def test_delete_last_item_discards_pending_without_crash():
    """P1: ลบจนไม่เหลือรายการ → pending ถูกทิ้ง ไม่ไปต่อ final preview (กัน combine max([]) error)"""
    items = [{"amount": 10.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": ""}]
    pid, p = _mk_pending(items)
    p["edit_state"] = "awaiting_line_1"
    cap = _Capture()
    _run_reply(cap, p, "ลบ")
    assert p["items"] == []
    assert pid not in ch._pending_expenses  # discarded
    assert p["edit_state"] is None
    assert any(k == "message" for k, *_ in cap.events)


def test_combine_on_empty_items_returns_friendly_message():
    """P1 defensive: _handle_expense_combine บน items ว่าง ต้องไม่ crash (max([]))"""
    pid, _p = _mk_pending([])
    result = ch._handle_expense_combine("u1", pid)
    assert "ไม่มีรายการ" in result


def test_split_on_empty_items_returns_friendly_message():
    pid, _p = _mk_pending([])
    result = ch._handle_expense_split("u1", pid)
    assert "ไม่มีรายการ" in result


def test_stale_apply_freetext_is_noop_after_exit():
    """P2: ออกจาก edit (edit_state=None) แล้วกด [ยืนยัน] เก่า → ต้องไม่ apply staged ops"""
    items = [{"amount": 90.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""}]
    pid, p = _mk_pending(items)
    p["edit_state"] = None  # จำลองออกจาก edit ด้วย slash command
    p["staged_operations"] = [{"op": "edit", "line": 1, "note": "เปลี่ยนผิด"}]
    cap = _Capture()
    p_inline, p_msg, p_edit = _patches(cap)
    with p_inline, p_msg, p_edit:
        ch._handle_apply_freetext("u1", pid, chat_id=5, message_id=6)
    assert p["items"][0]["note"] == "ข้าว"  # ไม่ถูก apply
    assert p.get("staged_operations") is None
    assert any("หมดอายุ" in t for k, t, _ in cap.events if k == "edit")


def test_stale_cancel_freetext_does_not_reenter_edit():
    """P2: กด [ยกเลิกการแก้] เก่าหลังออกจาก edit → ต้องไม่ดึงกลับเข้า edit mode"""
    items = [{"amount": 90.0, "category": "อาหาร", "note": "ข้าว", "confidence": "high", "raw_guess": ""}]
    pid, p = _mk_pending(items)
    p["edit_state"] = None
    p["staged_operations"] = [{"op": "delete", "line": 1}]
    cap = _Capture()
    p_inline, p_msg, p_edit = _patches(cap)
    with p_inline, p_msg, p_edit:
        ch._handle_cancel_freetext("u1", pid, chat_id=5, message_id=6)
    assert p["edit_state"] is None  # ไม่กลับเข้า edit mode
    assert p.get("staged_operations") is None


def test_apply_operations_add_inherits_receipt_date():
    """P2: add op ต้องสืบทอด receipt_date จากรายการเดิม (split อ่าน date จาก item)"""
    items = [{"amount": 40.0, "category": "อาหาร", "note": "ข้าว", "receipt_date": "2026-05-10"}]
    ch._apply_operations(items, [{"op": "add", "note": "ชา", "amount": 20, "category": "เครื่องดื่ม"}])
    assert items[-1]["receipt_date"] == "2026-05-10"
    assert items[-1]["note"] == "ชา"
