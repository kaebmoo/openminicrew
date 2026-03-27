import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.asyncio
async def test_delete_my_data_requires_confirm():
    from dispatcher import dispatch

    response, tool_used, model, tokens = await dispatch(
        user_id="u1",
        user={"telegram_chat_id": "123", "role": "user"},
        text="/delete_my_data",
    )

    assert "confirm" in response
    assert tool_used is None
    assert model is None
    assert tokens == 0


@pytest.mark.asyncio
async def test_delete_my_data_confirm_purges_and_reloads_scheduler():
    from dispatcher import dispatch

    purge_summary = {
        "user_found": True,
        "chat_history": 2,
        "conversations": 1,
        "processed_emails": 1,
        "tool_logs": 3,
        "reminders": 1,
        "todos": 1,
        "expenses": 1,
        "user_locations": 1,
        "oauth_states": 1,
        "user_api_keys": 1,
        "pending_messages": 1,
        "schedules": 1,
        "job_runs": 1,
        "users": 1,
        "gmail_token_deleted": True,
        "security_audit_logs_retained": 1,
    }

    with patch("core.privacy_commands.db.purge_user_data", return_value=purge_summary) as mock_purge, \
         patch("core.privacy_commands._reload_scheduler_after_purge") as mock_reload:
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/delete_my_data confirm",
        )

    mock_purge.assert_called_once_with("u1")
    mock_reload.assert_called_once()
    assert "ลบข้อมูลการใช้งานที่ผูกกับบัญชีของคุณแบบถาวรแล้ว" in response
    assert "governance audit trail retained: 1" in response


@pytest.mark.asyncio
async def test_delete_my_data_confirm_handles_missing_user():
    from dispatcher import dispatch

    with patch("core.privacy_commands.db.purge_user_data", return_value={"user_found": False, "gmail_token_deleted": False}), \
         patch("core.privacy_commands._reload_scheduler_after_purge"):
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/delete_my_data confirm",
        )

    assert "ไม่พบข้อมูลผู้ใช้" in response


@pytest.mark.asyncio
async def test_disconnectgmail_revokes_access_without_purging_other_data():
    from dispatcher import dispatch

    summary = {"user_updated": True, "oauth_states": 1, "gmail_token_deleted": True}

    with patch("core.privacy_commands.db.revoke_gmail_access", return_value=summary) as mock_revoke:
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/disconnectgmail",
        )

    mock_revoke.assert_called_once_with("u1")
    assert "ยกเลิกการเชื่อมต่อ Gmail แล้ว" in response
    assert "/delete_my_data confirm" in response


@pytest.mark.asyncio
async def test_clearlocation_deletes_only_saved_location():
    from dispatcher import dispatch

    with patch("core.privacy_commands.db.delete_location", return_value=True) as mock_delete:
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/clearlocation",
        )

    mock_delete.assert_called_once_with("u1")
    assert "ลบตำแหน่งล่าสุด" in response


@pytest.mark.asyncio
async def test_keyaudit_reports_plaintext_rows_for_owner():
    from dispatcher import dispatch

    report = {
        "total_keys": 3,
        "encrypted_count": 2,
        "plaintext_count": 1,
        "encryption_key_configured": True,
        "items": [
            {
                "user_id": "u1",
                "service": "work_imap_password",
                "updated_at": "2026-03-25T08:19:50",
                "value_length": 9,
            }
        ],
    }

    with patch("core.privacy_commands.get_plaintext_user_api_key_report", return_value=report):
        response, _, _, _ = await dispatch(
            user_id="owner-1",
            user={"telegram_chat_id": "123", "role": "owner"},
            text="/keyaudit",
        )

    assert "Plaintext rows" in response
    assert "service=work_imap_password" in response
    assert "len=9" in response


@pytest.mark.asyncio
async def test_keyaudit_requires_owner():
    from dispatcher import dispatch

    response, _, _, _ = await dispatch(
        user_id="u1",
        user={"telegram_chat_id": "123", "role": "user"},
        text="/keyaudit",
    )

    assert "เฉพาะ owner" in response


@pytest.mark.asyncio
async def test_privacy_shows_retention_and_data_controls():
    from dispatcher import dispatch

    consent_rows = [
        {"consent_type": "gmail_access", "status": "granted"},
        {"consent_type": "location_access", "status": "granted"},
        {"consent_type": "chat_history", "status": "granted"},
    ]

    with patch("core.privacy_commands.db.get_location", return_value={"lat": 13.7, "lng": 100.5, "updated_at": "2025-01-01T00:00:00"}), \
         patch("core.privacy_commands.db.list_user_consents", return_value=consent_rows), \
         patch("core.privacy_commands.summarize_user_key_hygiene", return_value={
             "total_keys": 2,
             "rotation_due_count": 1,
             "weak_key_count": 1,
             "rotation_due_services": ["tmd"],
             "weak_key_services": ["matcha"],
             "advisory_only": True,
             "items": [],
             "status": "warn",
         }), \
         patch("core.security.get_gmail_token_path") as mock_token_path:
        mock_token_path.return_value.exists.return_value = False
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user", "gmail_authorized": True},
            text="/privacy",
        )

    assert "Chat history retention" in response
    assert "API key rotation policy is advisory only" in response
    assert "API keys due for rotation: tmd" in response
    assert "/disconnectgmail" in response
    assert "/delete_my_data confirm" in response


@pytest.mark.asyncio
async def test_consent_chat_off_revokes_and_reports_deleted_history():
    from dispatcher import dispatch

    result = {
        "consent_type": "chat_history",
        "status": "revoked",
        "chat_history_deleted": 5,
        "conversations_deleted": 2,
    }

    with patch("core.privacy_commands.db.apply_user_consent", return_value=result) as mock_apply:
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/consent chat off",
        )

    mock_apply.assert_called_once_with("u1", "chat_history", False, source="user_command")
    assert "deleted chat_history: 5" in response
    assert "revoked" in response


@pytest.mark.asyncio
async def test_consent_without_args_shows_summary():
    from dispatcher import dispatch

    consent_rows = [
        {"consent_type": "gmail_access", "status": "not_set"},
        {"consent_type": "location_access", "status": "revoked"},
        {"consent_type": "chat_history", "status": "granted"},
    ]

    with patch("core.privacy_commands.db.list_user_consents", return_value=consent_rows):
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/consent",
        )

    assert "Consent status" in response
    assert "Gmail: not set" in response
    assert "Location: revoked" in response


@pytest.mark.asyncio
async def test_start_new_user_shows_explicit_consent_onboarding():
    from dispatcher import dispatch

    consent_rows = [
        {"consent_type": "gmail_access", "status": "not_set"},
        {"consent_type": "location_access", "status": "not_set"},
        {"consent_type": "chat_history", "status": "not_set"},
    ]

    with patch("core.system_commands.db.initialize_explicit_consents_for_new_user") as mock_init, \
         patch("core.system_commands.db.list_user_consents", return_value=consent_rows):
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user", "display_name": "Somchai"},
            text="/start",
        )

    mock_init.assert_called_once_with("u1", source="start_onboarding")
    assert "Consent เริ่มต้นของผู้ใช้ใหม่ยังไม่เปิดอัตโนมัติ" in response
    assert "/consent chat on" in response
    assert "/consent location on" in response


@pytest.mark.asyncio
async def test_start_existing_user_reminds_if_consent_pending():
    from dispatcher import dispatch

    consent_rows = [
        {"consent_type": "gmail_access", "status": "not_set"},
        {"consent_type": "location_access", "status": "granted"},
        {"consent_type": "chat_history", "status": "granted"},
    ]

    with patch("core.system_commands.db.initialize_explicit_consents_for_new_user"), \
         patch("core.system_commands.db.list_user_consents", return_value=consent_rows), \
         patch("core.security.get_gmail_token_path") as mock_token_path:
        mock_token_path.return_value.exists.return_value = False
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={
                "telegram_chat_id": "123",
                "role": "user",
                "display_name": "Somchai",
                "phone_number": "0812345678",
                "gmail_authorized": False,
            },
            text="/start",
        )

    assert "Consent setup:" in response
    assert "ยังมี consent ที่ยังไม่ตั้งค่า" in response
