import asyncio
import sys
import types
import hashlib
from pathlib import Path
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