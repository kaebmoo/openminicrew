import sys
import types
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from core import db
from core import api_keys
from core import security


def _reset_db_connection():
    db.close_thread_local_connection()


def _init_temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()


def test_sensitive_field_decrypts_with_previous_key(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", new_key)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY_PREVIOUS", old_key)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY_PREVIOUS_LIST", "")

    encrypted = security.SENSITIVE_FIELD_PREFIX + Fernet(old_key.encode()).encrypt(b"0812345678").decode()
    assert security.decrypt_sensitive_field(encrypted, field_name="phone_number") == "0812345678"


def test_get_api_key_decrypts_with_previous_key(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", new_key)
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY_PREVIOUS", old_key)
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY_PREVIOUS_LIST", "")

    stored_cipher = Fernet(old_key.encode()).encrypt(b"legacy-secret").decode()
    monkeypatch.setattr(db, "get_user_api_key", lambda user_id, service: stored_cipher)

    assert api_keys.get_api_key("u1", "gmail") == "legacy-secret"


def test_purge_user_data_writes_security_audit_log(tmp_path, monkeypatch):
    _init_temp_db(tmp_path, monkeypatch)

    db.upsert_user("u1", "chat-1", "User One")
    summary = db.purge_user_data("u1")

    assert summary["user_found"] is True
    assert summary["security_audit_logs_retained"] == 1

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT action, resource_type, target_user_id, outcome FROM security_audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row["action"] == "purge_user_data"
    assert row["resource_type"] == "user_data"
    assert row["target_user_id"] == "u1"
    assert row["outcome"] == "success"


def test_summarize_expenses_keyword_search_matches_encrypted_notes(tmp_path, monkeypatch):
    _init_temp_db(tmp_path, monkeypatch)

    db.upsert_user("u1", "chat-1", "User One")
    db.add_expense("u1", 120.0, "อาหาร", "ก๋วยเตี๋ยวหมู")
    db.add_expense("u1", 80.0, "อาหาร", "กาแฟเย็น")
    db.add_expense("u1", 50.0, "เดินทาง", "BTS")

    rows = db.summarize_expenses("u1", "2026-03-01", "2026-03-31", keyword="กาแฟ")

    assert rows == [{"category": "อาหาร", "total": 80.0, "count": 1}]


def test_rotate_user_api_key_encryption_reencrypts_with_primary_key(tmp_path, monkeypatch):
    _init_temp_db(tmp_path, monkeypatch)

    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", new_key)
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY_PREVIOUS", old_key)
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY_PREVIOUS_LIST", "")

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO user_api_keys (user_id, service, api_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                "u1",
                "tmd",
                Fernet(old_key.encode()).encrypt(b"legacy-secret").decode(),
                "2026-03-27T00:00:00",
                "2026-03-27T00:00:00",
            ),
        )

    result = api_keys.rotate_user_api_key_encryption()

    assert result["rotated_rows"] == 1
    record = db.get_user_api_key_record("u1", "tmd")
    assert Fernet(new_key.encode()).decrypt(record["api_key"].encode()).decode() == "legacy-secret"
