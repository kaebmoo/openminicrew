import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def _reset_db_connection():
    db.close_thread_local_connection()


def test_mark_email_processed_minimizes_subject_and_sender(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    db.mark_email_processed("u1", "msg-1", "Payroll for March", "Finance Team <payroll@example.com>")

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT message_id, subject, sender, sender_domain, has_subject FROM processed_emails WHERE user_id = ?",
            ("u1",),
        ).fetchone()

    assert row["message_id"] == "msg-1"
    assert row["subject"] is None
    assert row["sender"] is None
    assert row["sender_domain"] is None
    assert row["has_subject"] == 1


def test_log_tool_usage_stores_explicit_structured_fields_and_redacted_error(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    db.log_tool_usage(
        "u1",
        "gmail_summary",
        status="failed",
        **db.make_log_field("input", "subject: payroll@example.com April bonus", kind="gmail_batch_request"),
        **db.make_log_field("output", "Found 3 payroll emails from payroll@example.com", kind="gmail_summary_text"),
        **db.make_error_fields("Unauthorized access to payroll@example.com token"),
    )

    with db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT input_summary, output_summary, error_message,
                   input_kind, input_ref, input_size,
                   output_kind, output_ref, output_size,
                   error_kind, error_code, error_safe_message
            FROM tool_logs WHERE user_id = ?
            """,
            ("u1",),
        ).fetchone()

    assert row["input_summary"] is None
    assert row["output_summary"] is None
    assert row["error_message"] is None
    assert row["input_kind"] == "gmail_batch_request"
    assert row["input_ref"].startswith(db.REDACTED_REF_PREFIX)
    assert row["input_size"] > 0
    assert row["output_kind"] == "gmail_summary_text"
    assert row["output_ref"].startswith(db.REDACTED_REF_PREFIX)
    assert row["output_size"] > 0
    assert row["error_kind"] == "access"
    assert row["error_code"] == "auth_failed"
    assert "payroll@example.com" not in row["error_safe_message"]


def test_init_db_minimizes_legacy_processed_emails_and_tool_logs(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    _reset_db_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO processed_emails (user_id, message_id, subject, sender, processed_at) VALUES (?, ?, ?, ?, ?)",
            ("u1", "msg-legacy", "Secret Subject", "CEO <ceo@corp.example>", "2026-03-25T00:00:00"),
        )
        conn.execute(
            """
            INSERT INTO tool_logs (user_id, tool_name, input_summary, output_summary, llm_model, token_used, status, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "u1",
                "web_search",
                "search for salary adjustment memo",
                "found memo for ceo@corp.example",
                "test-model",
                10,
                "failed",
                "timeout while contacting ceo@corp.example",
                "2026-03-25T00:00:00",
            ),
        )

    db.init_db()

    with db.get_conn() as conn:
        email_row = conn.execute(
            "SELECT subject, sender, sender_domain, has_subject FROM processed_emails WHERE message_id = ?",
            ("msg-legacy",),
        ).fetchone()
        log_row = conn.execute(
            "SELECT input_summary, output_summary, error_message, input_kind, output_kind, error_code, error_safe_message FROM tool_logs WHERE tool_name = ?",
            ("web_search",),
        ).fetchone()

    assert email_row["subject"] is None
    assert email_row["sender"] is None
    assert email_row["sender_domain"] is None
    assert email_row["has_subject"] == 1
    assert log_row["input_summary"] is None
    assert log_row["output_summary"] is None
    assert log_row["error_message"] is None
    assert log_row["input_kind"]
    assert log_row["output_kind"]
    assert log_row["error_code"] == "timeout"
    assert "ceo@corp.example" not in log_row["error_safe_message"]


def test_dispatch_direct_tool_failure_logs_structured_fields():
    import asyncio
    import types
    from dispatcher import dispatch

    fake_tool = types.SimpleNamespace(
        name="calendar_tool",
        execute=AsyncMock(side_effect=RuntimeError("calendar backend timeout")),
    )

    with patch("dispatcher.registry.get_by_command", return_value=fake_tool), \
         patch("dispatcher.db.log_tool_usage") as mock_log_tool_usage:
        response, tool_used, _, _ = asyncio.run(
            dispatch("u1", {"telegram_chat_id": "123", "role": "user"}, "/calendar list")
        )

    assert tool_used == "calendar_tool"
    assert "เกิดข้อผิดพลาด" in response
    kwargs = mock_log_tool_usage.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert kwargs["input_kind"] == "tool_command"
    assert kwargs["error_code"] == "timeout"


def test_webhook_background_failure_logs_structured_dead_letter():
    import asyncio
    import interfaces.telegram_webhook as telegram_webhook

    update = {
        "message": {
            "chat": {"id": 12345},
            "message_id": 77,
            "text": "สรุปอีเมลให้หน่อย",
        }
    }

    with patch.object(telegram_webhook, "get_user", return_value={"user_id": "u1", "telegram_chat_id": "12345"}), \
         patch("dispatcher.process_message", new=AsyncMock(side_effect=RuntimeError("dispatcher timeout"))), \
         patch.object(telegram_webhook, "send_message"), \
         patch.object(telegram_webhook.db, "log_tool_usage") as mock_log_tool_usage:
        asyncio.run(telegram_webhook._process_update(update))

    kwargs = mock_log_tool_usage.call_args.kwargs
    assert kwargs["tool_name"] == "dispatcher"
    assert kwargs["input_kind"] == "telegram_message"
    assert kwargs["error_code"] == "timeout"