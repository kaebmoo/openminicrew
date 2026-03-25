import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from core import db
from core import security


def _reset_db_connection():
    db.close_thread_local_connection()


def test_purge_user_data_removes_all_user_records(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()

    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(security, "CREDENTIALS_DIR", credentials_dir)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    db.create_conversation("u1", "secret convo")
    conv_id = db.get_active_conversation("u1")
    db.save_chat("u1", "user", "hello", conversation_id=conv_id)
    db.mark_email_processed("u1", "msg-1", "subject", "sender@example.com")
    db.log_tool_usage("u1", "gmail_summary", input_summary="secret input", output_summary="secret output")
    db.add_reminder("u1", "reminder", "2030-01-01T10:00:00")
    db.add_todo("u1", "todo title", "todo notes")
    db.add_expense("u1", 120.0, "food", "expense note")
    db.apply_user_consent("u1", db.CONSENT_LOCATION, True)
    db.save_location("u1", 13.7, 100.5)
    db.save_oauth_state("state-1", "u1", "chat-1", "2999-01-01T00:00:00")
    db.upsert_user_api_key("u1", "tmd", "ciphertext")
    schedule_id = db.add_schedule("u1", "reminder", "0 9 * * *", "secret args")
    db.save_pending_message("chat-1", "pending secret")
    db.log_job_run(f"custom_{schedule_id}", "2030-01-01T09:00:00")

    token_path = security.get_gmail_token_path("u1")
    token_path.write_text("token-data")

    summary = db.purge_user_data("u1")

    assert summary["user_found"] is True
    assert summary["users"] == 1
    assert summary["chat_history"] == 1
    assert summary["conversations"] == 1
    assert summary["processed_emails"] == 1
    assert summary["tool_logs"] == 1
    assert summary["reminders"] == 1
    assert summary["todos"] == 1
    assert summary["expenses"] == 1
    assert summary["user_locations"] == 1
    assert summary["oauth_states"] == 1
    assert summary["user_consents"] == 3
    assert summary["user_api_keys"] == 1
    assert summary["pending_messages"] == 1
    assert summary["schedules"] == 1
    assert summary["job_runs"] == 1
    assert summary["gmail_token_deleted"] is True

    assert db.get_user_by_id("u1") is None
    assert db.get_chat_context("u1") == []
    assert db.list_conversations("u1") == []
    assert db.get_user_schedules("u1") == []
    assert db.get_pending_messages("chat-1") == []
    assert not token_path.exists()


def test_purge_user_data_returns_not_found_for_missing_user(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    summary = db.purge_user_data("missing")

    assert summary == {"user_found": False, "gmail_token_deleted": False}


def test_revoke_gmail_access_deletes_token_and_marks_user_disconnected(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()

    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(security, "CREDENTIALS_DIR", credentials_dir)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET gmail_authorized = 1 WHERE user_id = ?", ("u1",))
    db.save_oauth_state("state-1", "u1", "chat-1", "2999-01-01T00:00:00")

    token_path = security.get_gmail_token_path("u1")
    token_path.write_text("token-data")

    summary = db.revoke_gmail_access("u1")

    assert summary["user_updated"] is True
    assert summary["oauth_states"] == 1
    assert summary["gmail_token_deleted"] is True
    assert not token_path.exists()
    user = db.get_user_by_id("u1")
    assert user["gmail_authorized"] == 0
    assert db.get_user_consent("u1", db.CONSENT_GMAIL)["status"] == db.CONSENT_STATUS_REVOKED


def test_delete_location_and_cleanup_stale_locations(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    db.apply_user_consent("u1", db.CONSENT_LOCATION, True)
    db.save_location("u1", 13.7, 100.5)

    assert db.delete_location("u1") is True
    assert db.get_location("u1", ttl_minutes=0) is None

    db.save_location("u1", 13.8, 100.6)
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE user_locations SET updated_at = datetime('now', '-120 minutes') WHERE user_id = ?",
            ("u1",),
        )

    db.cleanup_stale_locations(ttl_minutes=60)

    assert db.get_location("u1", ttl_minutes=0) is None