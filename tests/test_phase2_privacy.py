import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
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
from core.user_manager import register_user


def _reset_db_connection():
    db.close_thread_local_connection()


def test_update_user_profile_encrypts_sensitive_fields_and_reads_plaintext(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    key = Fernet.generate_key().decode()

    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    db.update_user_profile("u1", phone_number="0812345678", national_id="1101700203451")

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT phone_number, national_id FROM users WHERE user_id = ?",
            ("u1",),
        ).fetchone()

    assert row["phone_number"] != "0812345678"
    assert row["national_id"] != "1101700203451"
    assert row["phone_number"].startswith(security.SENSITIVE_FIELD_PREFIX)
    assert row["national_id"].startswith(security.SENSITIVE_FIELD_PREFIX)

    user = db.get_user_by_id("u1")
    assert user["phone_number"] == "0812345678"
    assert user["national_id"] == "1101700203451"


def test_get_user_by_id_migrates_plaintext_profile_fields_when_key_present(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    key = Fernet.generate_key().decode()

    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE users SET phone_number = ?, national_id = ? WHERE user_id = ?",
            ("0812345678", "1101700203451", "u1"),
        )

    user = db.get_user_by_id("u1")

    assert user["phone_number"] == "0812345678"
    assert user["national_id"] == "1101700203451"
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT phone_number, national_id FROM users WHERE user_id = ?",
            ("u1",),
        ).fetchone()
    assert row["phone_number"].startswith(security.SENSITIVE_FIELD_PREFIX)
    assert row["national_id"].startswith(security.SENSITIVE_FIELD_PREFIX)


def test_chat_history_consent_revocation_deletes_history_and_blocks_future_saves(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"

    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    conv_id = db.create_conversation("u1", "secret")
    db.save_chat("u1", "user", "hello", conversation_id=conv_id)
    assert len(db.get_chat_context("u1")) == 1

    result = db.apply_user_consent("u1", db.CONSENT_CHAT_HISTORY, False)

    assert result["status"] == db.CONSENT_STATUS_REVOKED
    assert result["chat_history_deleted"] == 1
    assert result["conversations_deleted"] == 1
    assert db.get_chat_context("u1") == []

    db.save_chat("u1", "assistant", "should not persist")
    assert db.get_chat_context("u1") == []


def test_location_requires_explicit_consent_before_save(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"

    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    consents = {row["consent_type"]: row["status"] for row in db.list_user_consents("u1")}
    assert consents[db.CONSENT_CHAT_HISTORY] == db.CONSENT_STATUS_GRANTED
    assert consents[db.CONSENT_LOCATION] == db.CONSENT_STATUS_NOT_SET
    assert consents[db.CONSENT_GMAIL] == db.CONSENT_STATUS_NOT_SET

    assert db.save_location("u1", 13.7, 100.5) is False
    assert db.get_location("u1", ttl_minutes=0) is None
    assert db.get_user_consent("u1", db.CONSENT_LOCATION)["status"] == db.CONSENT_STATUS_NOT_SET

    db.apply_user_consent("u1", db.CONSENT_LOCATION, True)

    assert db.save_location("u1", 13.7, 100.5) is True
    assert db.get_user_consent("u1", db.CONSENT_LOCATION)["status"] == db.CONSENT_STATUS_GRANTED
    assert db.get_location("u1", ttl_minutes=0)["lat"] == 13.7


def test_register_user_creates_explicit_not_set_consents_for_new_user(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"

    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    register_user("chat-1", "User One")

    consents = {row["consent_type"]: row["status"] for row in db.list_user_consents("chat-1")}
    assert consents[db.CONSENT_CHAT_HISTORY] == db.CONSENT_STATUS_NOT_SET
    assert consents[db.CONSENT_LOCATION] == db.CONSENT_STATUS_NOT_SET
    assert consents[db.CONSENT_GMAIL] == db.CONSENT_STATUS_NOT_SET


def test_startup_readiness_warns_without_encryption_key_in_polling(monkeypatch):
    from core import readiness

    monkeypatch.setattr(readiness.config, "ENCRYPTION_KEY", "")

    report = readiness.collect_startup_readiness(bot_mode="polling", policy="auto")

    assert report["policy"] == "warn"
    assert report["status"] == "degraded"
    encryption_check = next(check for check in report["checks"] if check["name"] == "encryption_key")
    assert encryption_check["status"] == "warn"
    assert "encrypted_profile_fields" in encryption_check["impacts"]


def test_main_startup_self_check_fails_fast_in_webhook_mode(monkeypatch):
    fake_scheduler = types.SimpleNamespace(init_scheduler=lambda: None, stop_scheduler=lambda: None)

    with patch.dict(sys.modules, {"scheduler": fake_scheduler}):
        import importlib
        import main
        importlib.reload(main)

        monkeypatch.setattr(main, "collect_startup_readiness", lambda bot_mode="webhook": {
            "bot_mode": bot_mode,
            "policy": "strict",
            "status": "fail",
            "should_fail_fast": True,
            "checks": [
                {"name": "encryption_key", "status": "fail", "summary": "ENCRYPTION_KEY missing", "detail": "", "required": True, "impacts": ["gmail_oauth"]},
            ],
        })

        with pytest.raises(RuntimeError):
            main._run_startup_self_check("webhook")


def test_webhook_health_includes_startup_readiness(monkeypatch):
    import interfaces.telegram_webhook as telegram_webhook

    readiness_report = {
        "bot_mode": "webhook",
        "policy": "strict",
        "status": "degraded",
        "should_fail_fast": False,
        "checks": [
            {
                "name": "encryption_key",
                "status": "warn",
                "summary": "ENCRYPTION_KEY missing",
                "detail": "Encrypted profile fields are unavailable",
                "required": False,
                "impacts": ["encrypted_profile_fields"],
            }
        ],
    }

    monkeypatch.setattr(telegram_webhook, "collect_startup_readiness", lambda bot_mode="webhook": readiness_report)
    monkeypatch.setattr(telegram_webhook, "summarize_workspace_key_hygiene", lambda: {
        "total_keys": 3,
        "rotation_due_count": 1,
        "weak_key_count": 1,
        "impacted_user_count": 2,
        "advisory_only": True,
        "status": "warn",
    })
    monkeypatch.setattr(telegram_webhook.db, "check_health", lambda: {"db": "ok"})
    monkeypatch.setattr(telegram_webhook.db, "get_last_scheduler_run", lambda: {"job": "cleanup"})
    monkeypatch.setattr(telegram_webhook.llm_router, "health_check", lambda: {"claude_configured": True})

    result = asyncio.run(telegram_webhook.health_check())

    assert result["status"] == "degraded"
    assert result["startup_readiness"]["checks"][0]["name"] == "encryption_key"
    assert result["api_key_hygiene"]["advisory_only"] is True
    assert result["api_key_hygiene"]["rotation_due_count"] == 1
    assert result["db"] == {"db": "ok"}