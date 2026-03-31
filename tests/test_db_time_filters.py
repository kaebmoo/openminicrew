import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def _reset_db_connection():
    db.close_thread_local_connection()


def test_get_oauth_state_rejects_expired_iso_timestamp(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    expires_at = (datetime.now() - timedelta(minutes=1)).isoformat()
    db.save_oauth_state("state-1", "u1", "chat-1", expires_at)

    assert db.get_oauth_state("state-1") is None


def test_get_location_respects_ttl_for_iso_timestamp(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    db.apply_user_consent("u1", db.CONSENT_LOCATION, True)
    db.save_location("u1", 13.7, 100.5)

    expired_at = (datetime.now() - timedelta(minutes=90)).isoformat()
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE user_locations SET updated_at = ? WHERE user_id = ?",
            (expired_at, "u1"),
        )

    assert db.get_location("u1", ttl_minutes=60) is None


def test_cleanup_old_pending_removes_iso_timestamp_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.save_pending_message("chat-1", "hello")
    old_created_at = (datetime.now() - timedelta(days=10)).isoformat()
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE pending_messages SET created_at = ? WHERE chat_id = ?",
            (old_created_at, "chat-1"),
        )

    db.cleanup_old_pending(days=7)

    assert db.get_pending_messages("chat-1") == []