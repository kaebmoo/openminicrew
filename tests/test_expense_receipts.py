import asyncio
import sys
import types
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from core import db
from core import security
from tools.expense import ExpenseTool


class _ExpenseToolForTest(ExpenseTool):
    async def extract_for_test(self, image_bytes: bytes, hint: str = ""):
        return await self._extract_expense_from_image(image_bytes, hint)


def _reset_db_connection():
    db.close_thread_local_connection()


def _init_temp_db(tmp_path, monkeypatch, *, encryption_key: str | None = None):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", encryption_key or "")
    _reset_db_connection()
    db.init_db()


def test_expense_note_is_encrypted_at_rest_and_decrypted_on_read(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)

    db.upsert_user("u1", "chat-1", "User One")
    expense_id = db.add_expense("u1", 120.0, "อาหาร", "Villa Market — ข้าวกลางวัน")

    with db.get_conn() as conn:
        row = conn.execute("SELECT note FROM expenses WHERE id = ?", (expense_id,)).fetchone()

    assert row["note"].startswith(security.SENSITIVE_FIELD_PREFIX)

    items = db.list_expenses("u1")
    assert items[0]["note"] == "Villa Market — ข้าวกลางวัน"


def test_list_expenses_migrates_legacy_plaintext_note_when_key_present(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO expenses (user_id, amount, currency, category, note, source_type, source_hash, expense_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("u1", 89.0, "THB", "อาหาร", "Legacy plaintext note", "", "", "2026-03-25", "2026-03-25T10:00:00"),
        )

    items = db.list_expenses("u1")
    assert items[0]["note"] == "Legacy plaintext note"

    with db.get_conn() as conn:
        row = conn.execute("SELECT note FROM expenses WHERE user_id = ?", ("u1",)).fetchone()

    assert row["note"].startswith(security.SENSITIVE_FIELD_PREFIX)


def test_receipt_photo_duplicate_is_rejected_when_already_recorded(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)

    db.upsert_user("u1", "chat-1", "User One")
    source_hash = hashlib.sha256(b"same-image").hexdigest()
    existing_id = db.add_expense(
        "u1",
        245.0,
        "อาหาร",
        "Cafe ABC — lunch",
        source_type=ExpenseTool.RECEIPT_SOURCE_TYPE,
        source_hash=source_hash,
    )

    tool = ExpenseTool()
    with patch("interfaces.telegram_common.download_telegram_photo", return_value=b"same-image"), \
         patch.object(tool, "_extract_expense_from_image", new=AsyncMock(return_value=[{"amount": 245.0, "category": "อาหาร", "note": "lunch"}])) as mock_extract:
        result = asyncio.run(tool.execute("u1", "__photo:file-1"))

    assert f"#{existing_id}" in result
    assert "เคยถูกบันทึกแล้ว" in result
    mock_extract.assert_not_awaited()


def test_receipt_photo_duplicate_is_rejected_while_pending_confirmation(tmp_path, monkeypatch):
    from core.callback_handler import store_pending_expense

    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)

    db.upsert_user("u1", "chat-1", "User One")
    source_hash = hashlib.sha256(b"pending-image").hexdigest()
    store_pending_expense(
        "u1",
        [{"amount": 59.0, "category": "เครื่องดื่ม", "note": "กาแฟเย็น"}],
        "Cafe XYZ",
        source_type=ExpenseTool.RECEIPT_SOURCE_TYPE,
        source_hash=source_hash,
    )

    tool = ExpenseTool()
    with patch("interfaces.telegram_common.download_telegram_photo", return_value=b"pending-image"), \
         patch.object(tool, "_extract_expense_from_image", new=AsyncMock(return_value=[{"amount": 59.0, "category": "เครื่องดื่ม", "note": "กาแฟเย็น"}])) as mock_extract:
        result = asyncio.run(tool.execute("u1", "__photo:file-2"))

    assert "กำลังรอการยืนยันอยู่แล้ว" in result
    mock_extract.assert_not_awaited()


def test_pending_expense_split_persists_source_hash_for_all_rows(tmp_path, monkeypatch):
    from core.callback_handler import _handle_expense_split, store_pending_expense

    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)

    db.upsert_user("u1", "chat-1", "User One")
    source_hash = hashlib.sha256(b"split-image").hexdigest()
    pending_id = store_pending_expense(
        "u1",
        [
            {"amount": 45.0, "category": "อาหาร", "note": "ข้าวผัด"},
            {"amount": 25.0, "category": "เครื่องดื่ม", "note": "น้ำเปล่า"},
        ],
        "Food Court",
        source_type=ExpenseTool.RECEIPT_SOURCE_TYPE,
        source_hash=source_hash,
    )

    result = _handle_expense_split("u1", pending_id)
    rows = db.get_expenses_by_source_hash("u1", ExpenseTool.RECEIPT_SOURCE_TYPE, source_hash)

    assert "บันทึกแยก 2 รายการแล้ว" in result
    assert len(rows) == 2
    assert rows[0]["note"]
    assert rows[1]["note"]


def test_normalize_receipt_date_accepts_valid_iso():
    assert ExpenseTool._normalize_receipt_date("2026-05-10") == "2026-05-10"


def test_normalize_receipt_date_rejects_thai_buddhist_and_garbage():
    # Gemini bug: ส่งพ.ศ. หลุดมาเป็น ค.ศ. — ปี 2569 อยู่นอกช่วง 2000-2100
    assert ExpenseTool._normalize_receipt_date("2569-05-10") == ""
    assert ExpenseTool._normalize_receipt_date("18/05/2569") == ""
    assert ExpenseTool._normalize_receipt_date("null") == ""
    assert ExpenseTool._normalize_receipt_date(None) == ""
    assert ExpenseTool._normalize_receipt_date("") == ""


def test_receipt_photo_uses_receipt_date_when_provided(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    tool = ExpenseTool()
    extracted = [{
        "amount": 120.0, "category": "อาหาร", "note": "lunch",
        "store": "Cafe A", "receipt_date": "2026-05-10",
    }]
    with patch("interfaces.telegram_common.download_telegram_photo", return_value=b"img-bytes-1"), \
         patch.object(tool, "_extract_expense_from_image", new=AsyncMock(return_value=extracted)):
        result = asyncio.run(tool.execute("u1", "__photo:file-A"))

    rows = db.list_expenses("u1")
    assert len(rows) == 1
    assert rows[0]["expense_date"] == "2026-05-10"
    assert "2026-05-10" in result


def test_receipt_photo_falls_back_to_today_when_receipt_date_missing(tmp_path, monkeypatch):
    from datetime import date as _date
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    tool = ExpenseTool()
    extracted = [{
        "amount": 80.0, "category": "เครื่องดื่ม", "note": "coffee",
        "store": "Cafe B", "receipt_date": "",
    }]
    with patch("interfaces.telegram_common.download_telegram_photo", return_value=b"img-bytes-2"), \
         patch.object(tool, "_extract_expense_from_image", new=AsyncMock(return_value=extracted)):
        result = asyncio.run(tool.execute("u1", "__photo:file-B"))

    today = _date.today().isoformat()
    rows = db.list_expenses("u1")
    assert rows[0]["expense_date"] == today
    assert today in result


def test_multi_item_preview_shows_receipt_date(tmp_path, monkeypatch):
    from tools.response import InlineKeyboardResponse

    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    tool = ExpenseTool()
    extracted = [
        {"amount": 100.0, "category": "อาหาร", "note": "ข้าวผัด", "store": "ร้าน X", "receipt_date": "2026-05-10"},
        {"amount": 50.0, "category": "เครื่องดื่ม", "note": "ชา", "store": "ร้าน X", "receipt_date": "2026-05-10"},
    ]
    with patch("interfaces.telegram_common.download_telegram_photo", return_value=b"img-multi"), \
         patch.object(tool, "_extract_expense_from_image", new=AsyncMock(return_value=extracted)):
        result = asyncio.run(tool.execute("u1", "__photo:file-multi"))

    assert isinstance(result, InlineKeyboardResponse)
    assert "วันที่: 2026-05-10" in result.text


def test_pending_split_propagates_receipt_date_to_all_rows(tmp_path, monkeypatch):
    from core.callback_handler import _handle_expense_split, store_pending_expense

    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    pending_id = store_pending_expense(
        "u1",
        [
            {"amount": 50.0, "category": "อาหาร", "note": "ก๋วยเตี๋ยว", "receipt_date": "2026-05-10"},
            {"amount": 25.0, "category": "เครื่องดื่ม", "note": "ชา", "receipt_date": "2026-05-10"},
        ],
        "Food Court",
    )

    _handle_expense_split("u1", pending_id)
    rows = db.list_expenses("u1")
    assert len(rows) == 2
    assert all(r["expense_date"] == "2026-05-10" for r in rows)


def test_apply_grand_total_ratio_distributes_sc_vat():
    """SC/VAT should be distributed proportionally across items"""
    tool = ExpenseTool()
    items = [
        {"amount": 260.0, "category": "อาหาร", "note": "เนื้อ"},
        {"amount": 145.0, "category": "อาหาร", "note": "ตำ"},
        {"amount": 280.0, "category": "อาหาร", "note": "แกงส้ม"},
        {"amount": 260.0, "category": "อาหาร", "note": "ไข่เจียว"},
        {"amount": 60.0, "category": "อาหาร", "note": "ข้าวสวย"},
        {"amount": 45.0, "category": "เครื่องดื่ม", "note": "Coke Light"},
        {"amount": 45.0, "category": "เครื่องดื่ม", "note": "Soda"},
    ]
    data = {"subtotal": 1095.0, "grand_total": 1288.0}
    adjusted = tool._apply_grand_total_ratio(items, data)

    total = sum(it["amount"] for it in adjusted)
    assert total == 1288.0, f"Total should equal grand_total, got {total}"
    # Each item should be larger than original (ratio > 1)
    for orig, adj in zip(items, adjusted):
        assert adj["amount"] > orig["amount"]


def test_net_discounts_matches_special_price_grouped_at_bottom():
    """CJ More: discounts รวมท้ายใบ + note 'ราคาพิเศษ Xบ' → ต้องจับคู่ item ถูก
    ไม่ใช่กองทุกส่วนลดลงรายการสุดท้ายให้ยอดตรง"""
    items = [
        {"amount": 24.0, "category": "เครื่องดื่ม", "note": "ซีโอโซดา"},
        {"amount": 39.0, "category": "เครื่องดื่ม", "note": "ดีน่านม"},
        {"amount": 69.0, "category": "อาหาร", "note": "โก๋แก่"},
        {"amount": 128.0, "category": "เครื่องดื่ม", "note": "น้ำแร่ 1500ml"},
        {"amount": 455.0, "category": "เครื่องดื่ม", "note": "เบียร์"},
        {"amount": -26.0, "category": "ทั่วไป", "note": "โปรโมชั่นราคาพิเศษ 102บ"},
        {"amount": -4.0, "category": "ทั่วไป", "note": "โปรโมชั่นราคาพิเศษ 35บ"},
        {"amount": -3.0, "category": "ทั่วไป", "note": "โปรโมชั่นราคาพิเศษ 66บ"},
    ]
    result = ExpenseTool._net_discounts(items, grand_total=682.0)

    assert len(result) == 5
    amounts = {r["note"]: r["amount"] for r in result}
    assert amounts["ซีโอโซดา"] == 24.0           # ไม่ลด
    assert amounts["ดีน่านม"] == 35.0             # 39 - 4
    assert amounts["โก๋แก่"] == 66.0              # 69 - 3
    assert amounts["น้ำแร่ 1500ml"] == 102.0      # 128 - 26
    assert amounts["เบียร์"] == 455.0             # เบียร์ไม่ลด ห้ามยัด
    assert sum(r["amount"] for r in result) == 682.0


def test_net_discounts_falls_back_to_preceding_item_when_no_special_price_hint():
    """ส่วนลดติดทันทีหลัง item (รูปแบบ A) ไม่มี 'ราคาพิเศษ' hint → ใช้ heuristic เดิม"""
    items = [
        {"amount": 100.0, "category": "อาหาร", "note": "ข้าวผัด"},
        {"amount": -10.0, "category": "ทั่วไป", "note": "CPN3 - BHT"},
        {"amount": 50.0, "category": "เครื่องดื่ม", "note": "ชา"},
    ]
    result = ExpenseTool._net_discounts(items, grand_total=140.0)
    amounts = {r["note"]: r["amount"] for r in result}
    assert amounts["ข้าวผัด"] == 90.0
    assert amounts["ชา"] == 50.0


def test_apply_grand_total_ratio_no_change_when_missing():
    """When subtotal/grand_total are missing, items stay unchanged"""
    tool = ExpenseTool()
    items = [{"amount": 100.0, "category": "อาหาร", "note": "test"}]
    result = tool._apply_grand_total_ratio(items, {})
    assert result[0]["amount"] == 100.0


def test_apply_grand_total_ratio_no_change_when_equal():
    """When subtotal == grand_total (no SC/VAT), items stay unchanged"""
    tool = ExpenseTool()
    items = [{"amount": 100.0, "category": "อาหาร", "note": "test"}]
    result = tool._apply_grand_total_ratio(items, {"subtotal": 100.0, "grand_total": 100.0})
    assert result[0]["amount"] == 100.0


def test_extract_expense_from_image_does_not_log_plaintext_response(monkeypatch):
    monkeypatch.setattr("core.config.GEMINI_API_KEY", "test-gemini-key")

    response_text = '{"store":"Secret Shop","items":[{"amount":120,"category":"อาหาร","note":"เลขบัตร 1234"}]}'
    def _build_content(**kwargs):
        return SimpleNamespace(**kwargs)

    fake_response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text=response_text)]
                )
            )
        ]
    )
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(
                generate_content=AsyncMock(return_value=fake_response)
            )
        )
    )
    fake_part = SimpleNamespace(
        from_bytes=lambda **kwargs: SimpleNamespace(),
        from_text=lambda **kwargs: SimpleNamespace(),
    )
    fake_types = SimpleNamespace(
        Part=fake_part,
        Content=_build_content,
    )
    fake_genai = SimpleNamespace(Client=lambda **kwargs: fake_client)

    tool = _ExpenseToolForTest()
    with patch.dict(sys.modules, {"google": SimpleNamespace(genai=fake_genai), "google.genai": SimpleNamespace(types=fake_types)}), \
         patch("tools.expense.log.info") as mock_log_info, \
         patch("tools.expense.log.warning") as mock_log_warning:
        result = asyncio.run(tool.extract_for_test(b"fake-image-bytes"))

    assert result == [{
        "amount": 120.0, "category": "อาหาร", "note": "เลขบัตร 1234",
        "confidence": "high", "raw_guess": "",
        "store": "Secret Shop", "receipt_date": "",
        "is_handwritten": False, "store_confidence": "high",
        "store_raw_guess": "", "grand_total": None,
    }]
    info_messages = " ".join(str(call.args) for call in mock_log_info.call_args_list)
    warning_messages = " ".join(str(call.args) for call in mock_log_warning.call_args_list)
    assert response_text not in info_messages
    assert response_text not in warning_messages
    assert "Secret Shop" not in info_messages
    assert "เลขบัตร 1234" not in info_messages


# === Phase A: confidence parsing, button layout, telemetry ===

def test_normalize_confidence_clamps_to_enum():
    assert ExpenseTool._normalize_confidence("high") == "high"
    assert ExpenseTool._normalize_confidence("LOW") == "low"
    assert ExpenseTool._normalize_confidence(" Medium ") == "medium"
    # invalid / missing → default high
    assert ExpenseTool._normalize_confidence("0.9") == "high"
    assert ExpenseTool._normalize_confidence(None) == "high"
    assert ExpenseTool._normalize_confidence("") == "high"


def test_compute_overall_confidence_thresholds():
    high2 = [{"confidence": "high"}, {"confidence": "high"}]
    assert ExpenseTool._compute_overall_confidence(high2) == "high"
    # 1/2 low = 50% > 30% → low
    assert ExpenseTool._compute_overall_confidence([{"confidence": "high"}, {"confidence": "low"}]) == "low"
    # no low, but low+med 2/3 > 50% → medium
    assert ExpenseTool._compute_overall_confidence(
        [{"confidence": "high"}, {"confidence": "medium"}, {"confidence": "medium"}]
    ) == "medium"
    # missing confidence treated as not-low/not-med → high
    assert ExpenseTool._compute_overall_confidence([{}, {}]) == "high"
    assert ExpenseTool._compute_overall_confidence([]) == "high"


def _photo_extract(items, img=b"img"):
    """helper: patch download + _extract_expense_from_image แล้วรัน execute

    img ต้องไม่ซ้ำข้ามเทสต์ — source_hash อิงจาก image bytes และ _pending_expenses
    เป็น module-global ที่ค้างข้ามเทสต์ (เลียนแบบ convention เดิมในไฟล์นี้)
    """
    tool = ExpenseTool()
    return tool, patch("interfaces.telegram_common.download_telegram_photo", return_value=img), \
        patch.object(tool, "_extract_expense_from_image", new=AsyncMock(return_value=items))


def test_low_confidence_multi_item_shows_edit_manual_buttons(tmp_path, monkeypatch):
    from tools.response import InlineKeyboardResponse
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    items = [
        {"amount": 90.0, "category": "เครื่องดื่ม", "note": "เบียร์", "confidence": "high",
         "store": "ร้าน", "receipt_date": "2026-05-10", "is_handwritten": True,
         "store_confidence": "low", "store_raw_guess": "ร้านเดา", "grand_total": None},
        {"amount": 10.0, "category": "เครื่องดื่ม", "note": "?", "confidence": "low", "raw_guess": "น้ำเล็ก",
         "store": "ร้าน", "receipt_date": "2026-05-10", "is_handwritten": True,
         "store_confidence": "low", "store_raw_guess": "ร้านเดา", "grand_total": None},
    ]
    tool, p_dl, p_ex = _photo_extract(items, img=b"img-low")
    with p_dl, p_ex:
        result = asyncio.run(tool.execute("u1", "__photo:file-low"))

    assert isinstance(result, InlineKeyboardResponse)
    flat = [b["callback_data"] for row in result.buttons for b in row]
    assert any(cd.startswith("exp_edit:") for cd in flat)
    assert any(cd.startswith("exp_type_manually:") for cd in flat)
    assert any(cd.startswith("exp_cancel:") for cd in flat)
    # low/medium → no split/combine
    assert not any(cd.startswith("exp_split:") for cd in flat)
    assert not any(cd.startswith("exp_combine:") for cd in flat)
    # confidence icon + raw_guess hint shown
    assert "[?]" in result.text and 'เดา: "น้ำเล็ก"' in result.text
    # telemetry row written, action still NULL (waiting on user)
    with db.get_conn() as conn:
        row = dict(conn.execute("SELECT * FROM ocr_telemetry ORDER BY id DESC LIMIT 1").fetchone())
    assert row["overall_confidence"] == "low" and row["is_handwritten"] == 1
    assert row["total_items"] == 2 and row["low_conf_items"] == 1 and row["user_action"] is None


def test_high_confidence_multi_item_shows_split_combine_edit(tmp_path, monkeypatch):
    from tools.response import InlineKeyboardResponse
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    items = [
        {"amount": 100.0, "category": "อาหาร", "note": "ข้าวผัด", "confidence": "high",
         "store": "ร้าน X", "receipt_date": "2026-05-10"},
        {"amount": 50.0, "category": "เครื่องดื่ม", "note": "ชา", "confidence": "high",
         "store": "ร้าน X", "receipt_date": "2026-05-10"},
    ]
    tool, p_dl, p_ex = _photo_extract(items, img=b"img-high")
    with p_dl, p_ex:
        result = asyncio.run(tool.execute("u1", "__photo:file-high"))

    assert isinstance(result, InlineKeyboardResponse)
    flat = [b["callback_data"] for row in result.buttons for b in row]
    assert any(cd.startswith("exp_split:") for cd in flat)
    assert any(cd.startswith("exp_combine:") for cd in flat)
    assert any(cd.startswith("exp_edit:") for cd in flat)
    assert any(cd.startswith("exp_cancel:") for cd in flat)


def test_single_low_confidence_item_is_not_auto_saved(tmp_path, monkeypatch):
    from tools.response import InlineKeyboardResponse
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    items = [{"amount": 60.0, "category": "อาหาร", "note": "?", "confidence": "low", "raw_guess": "ข้าวเดา",
              "store": "", "receipt_date": "2026-05-10", "is_handwritten": True, "grand_total": None}]
    tool, p_dl, p_ex = _photo_extract(items, img=b"img-single-low")
    with p_dl, p_ex:
        result = asyncio.run(tool.execute("u1", "__photo:file-single-low"))

    # ไม่ auto-save → ยังไม่มีรายการใน DB, ได้ preview + ปุ่มแทน
    assert isinstance(result, InlineKeyboardResponse)
    assert db.list_expenses("u1") == []
    flat = [b["callback_data"] for row in result.buttons for b in row]
    assert any(cd.startswith("exp_type_manually:") for cd in flat)


def test_single_high_confidence_item_auto_saves_and_logs_telemetry(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    _init_temp_db(tmp_path, monkeypatch, encryption_key=key)
    db.upsert_user("u1", "chat-1", "User One")

    items = [{"amount": 80.0, "category": "เครื่องดื่ม", "note": "coffee", "confidence": "high",
              "store": "Cafe B", "receipt_date": "2026-05-10", "is_handwritten": False, "grand_total": None}]
    tool, p_dl, p_ex = _photo_extract(items, img=b"img-single-high")
    with p_dl, p_ex:
        result = asyncio.run(tool.execute("u1", "__photo:file-single-high"))

    assert "บันทึกรายจ่ายจากรูปแล้ว" in result
    assert len(db.list_expenses("u1")) == 1
    with db.get_conn() as conn:
        row = dict(conn.execute("SELECT * FROM ocr_telemetry ORDER BY id DESC LIMIT 1").fetchone())
    assert row["user_action"] == "split" and row["total_items"] == 1 and row["overall_confidence"] == "high"