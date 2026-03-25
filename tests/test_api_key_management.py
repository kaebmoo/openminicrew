import sys
import types
import json
import stat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from core import api_keys
from core import security
from core.security import get_gmail_client_config, get_gmail_credentials, import_gmail_client_secrets


def _encrypt_for_test(key: str, payload: str) -> str:
    return Fernet(key.encode()).encrypt(payload.encode()).decode()


def _decrypt_for_test(key: str, payload: str) -> str:
    return Fernet(key.encode()).decrypt(payload.encode()).decode()


def test_shared_service_falls_back_to_env():
    with patch("core.api_keys.db.get_user_api_key", return_value=None), \
         patch.object(api_keys.config, "TMD_API_KEY", "shared-tmd-key"):
        assert api_keys.get_api_key("u1", "tmd") == "shared-tmd-key"


def test_private_service_never_falls_back_to_env():
    with patch("core.api_keys.db.get_user_api_key", return_value=None), \
         patch.object(api_keys.config, "GOOGLE_MAPS_API_KEY", "shared-google-maps"):
        assert api_keys.get_api_key("u1", "work_imap_password") is None


def test_get_api_key_returns_none_when_key_missing_for_stored_private_key(monkeypatch, caplog):
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    with patch("core.api_keys.db.get_user_api_key", return_value="gAAAAencrypted"):
        value = api_keys.get_api_key("u1", "gmail")

    assert value is None
    assert "ENCRYPTION_KEY not set while reading encrypted stored private key" in caplog.text


def test_list_user_keys_marks_encrypted_values_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    with patch("core.api_keys.db.get_user_api_keys", return_value=[
        {
            "service": "gmail",
            "api_key": "gAAAAencrypted",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
    ]):
        items = api_keys.list_user_keys("u1")

    assert items[0]["value_available"] is False
    assert items[0]["is_weak"] is False
    assert items[0]["rotation_days"] == api_keys.get_rotation_period_days("gmail")


def test_backfill_plaintext_user_api_keys_encrypts_legacy_rows(tmp_path, monkeypatch):
    from core import db

    db_path = tmp_path / "test.db"
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", key)
    db.close_thread_local_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO user_api_keys (user_id, service, api_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("u1", "matcha", "plaintext-key", "2026-03-25T00:00:00", "2026-03-25T00:00:00"),
        )

    summary = api_keys.backfill_plaintext_user_api_keys()

    row = db.get_user_api_key_record("u1", "matcha")
    assert summary["migrated_rows"] == 1
    assert row["api_key"] != "plaintext-key"
    assert row["api_key"].startswith("gAAAA")
    assert Fernet(key.encode()).decrypt(row["api_key"].encode()).decode() == "plaintext-key"


def test_plaintext_user_api_key_report_hides_values(tmp_path, monkeypatch):
    from core import db

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")
    db.close_thread_local_connection()
    db.init_db()

    db.upsert_user("u1", "chat-1", "User One")
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO user_api_keys (user_id, service, api_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("u1", "work_imap_password", "plaintext-key", "2026-03-25T00:00:00", "2026-03-25T00:00:00"),
        )

    report = api_keys.get_plaintext_user_api_key_report()

    assert report["plaintext_count"] == 1
    assert report["items"][0]["service"] == "work_imap_password"
    assert report["items"][0]["value_length"] == len("plaintext-key")
    assert "api_key" not in report["items"][0]


def test_set_api_key_requires_encryption_key(monkeypatch):
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is required"):
        api_keys.set_api_key("u1", "tmd", "secret")


def test_set_api_key_encrypts_value_when_key_exists(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", key)

    with patch("core.api_keys.db.upsert_user_api_key") as mock_upsert:
        api_keys.set_api_key("u1", "tmd", "realistic-secret-token-12345")

    stored_value = mock_upsert.call_args.args[2]
    assert stored_value != "realistic-secret-token-12345"
    assert Fernet(key.encode()).decrypt(stored_value.encode()).decode() == "realistic-secret-token-12345"


def test_set_api_key_rejects_placeholder_like_values(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", key)

    with pytest.raises(ValueError, match="weak or placeholder-like"):
        api_keys.set_api_key("u1", "tmd", "abc123")


def test_rotation_period_days_respect_config(monkeypatch):
    monkeypatch.setattr(api_keys.config, "API_KEY_ROTATION_DAYS_DEFAULT", 200)
    monkeypatch.setattr(api_keys.config, "WORK_IMAP_PASSWORD_ROTATION_DAYS", 45)
    monkeypatch.setattr(api_keys.config, "WORK_IMAP_USER_ROTATION_DAYS", 120)
    monkeypatch.setattr(api_keys.config, "WORK_IMAP_HOST_ROTATION_DAYS", 300)

    assert api_keys.get_rotation_period_days("tmd") == 200
    assert api_keys.get_rotation_period_days("work_imap_password") == 45
    assert api_keys.get_rotation_period_days("work_imap_user") == 120
    assert api_keys.get_rotation_period_days("work_imap_host") == 300


def test_list_user_keys_includes_rotation_and_weakness_metadata(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", key)

    old_cipher = Fernet(key.encode()).encrypt(b"dummy").decode()
    fresh_cipher = Fernet(key.encode()).encrypt(b"realistic-secret-token-12345").decode()

    with patch("core.api_keys.db.get_user_api_keys", return_value=[
        {
            "service": "tmd",
            "api_key": old_cipher,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        },
        {
            "service": "matcha",
            "api_key": fresh_cipher,
            "created_at": "2026-03-20T00:00:00",
            "updated_at": "2026-03-20T00:00:00",
        },
    ]):
        items = api_keys.list_user_keys("u1")

    stale = next(item for item in items if item["service"] == "tmd")
    fresh = next(item for item in items if item["service"] == "matcha")
    assert stale["rotation_due"] is True
    assert stale["is_weak"] is True
    assert fresh["rotation_due"] is False
    assert fresh["is_weak"] is False


@pytest.mark.asyncio
async def test_apikey_tool_returns_error_when_encryption_key_missing(monkeypatch):
    from tools.apikeys import ApiKeysTool

    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    response = await ApiKeysTool().execute("u1", args="tmd abc123", command="/setkey")

    assert "ENCRYPTION_KEY is required" in response


@pytest.mark.asyncio
async def test_apikey_tool_reports_rotation_guidance_on_set(monkeypatch):
    from tools.apikeys import ApiKeysTool

    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", Fernet.generate_key().decode())

    with patch("tools.apikeys.set_api_key") as mock_set:
        response = await ApiKeysTool().execute("u1", args="tmd realistic-secret-token-12345", command="/setkey")

    mock_set.assert_called_once_with("u1", "tmd", "realistic-secret-token-12345")
    assert "rotate ภายใน" in response


@pytest.mark.asyncio
async def test_apikey_tool_lists_rotation_due_and_weak_legacy_key():
    from tools.apikeys import ApiKeysTool

    with patch("tools.apikeys.list_user_keys", return_value=[
        {
            "service": "tmd",
            "updated_at": "2025-01-01T00:00:00",
            "rotation_due": True,
            "rotation_days": 180,
            "age_days": 400,
            "is_weak": True,
            "weak_reasons": ["placeholder value"],
        }
    ]):
        response = await ApiKeysTool().execute("u1", command="/mykeys")

    assert "rotation due" in response
    assert "age: 400d" in response
    assert "weak legacy value" in response
    assert "placeholder value" in response
    assert "advisory only" in response


def test_gmail_credentials_do_not_fallback_to_owner(tmp_path, monkeypatch):
    missing_token = tmp_path / "missing.json"
    monkeypatch.setattr("core.security.get_gmail_token_path", lambda user_id: Path(missing_token))

    assert get_gmail_credentials("non-owner") is None


def test_get_gmail_credentials_reads_encrypted_token(tmp_path, monkeypatch):
    token_path = tmp_path / "gmail_u1.json"
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)

    payload = json.dumps({"token": "abc", "refresh_token": "refresh", "client_id": "cid", "client_secret": "secret"})
    token_path.write_text(_encrypt_for_test(key, payload))
    monkeypatch.setattr("core.security.get_gmail_token_path", lambda user_id: token_path)

    fake_creds = types.SimpleNamespace(valid=True, expired=False, refresh_token="refresh", to_json=lambda: payload)
    with patch("core.security.Credentials.from_authorized_user_info", return_value=fake_creds) as mock_loader:
        assert get_gmail_credentials("u1") is fake_creds

    assert mock_loader.call_args.args[0]["token"] == "abc"


def test_get_gmail_credentials_migrates_plaintext_token_when_key_present(tmp_path, monkeypatch):
    token_path = tmp_path / "gmail_u1.json"
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)

    payload = json.dumps({"token": "abc", "refresh_token": "refresh", "client_id": "cid", "client_secret": "secret"})
    token_path.write_text(payload)
    monkeypatch.setattr("core.security.get_gmail_token_path", lambda user_id: token_path)

    fake_creds = types.SimpleNamespace(valid=True, expired=False, refresh_token="refresh", to_json=lambda: payload)
    with patch("core.security.Credentials.from_authorized_user_info", return_value=fake_creds):
        assert get_gmail_credentials("u1") is fake_creds

    stored = token_path.read_text()
    assert stored != payload
    assert _decrypt_for_test(key, stored) == payload


def test_authorize_gmail_interactive_requires_encryption_key(tmp_path, monkeypatch):
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")

    monkeypatch.setattr(security, "GMAIL_CREDENTIALS_FILE", creds_file)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", "")

    assert security.authorize_gmail_interactive("u1") is False


def test_import_gmail_client_secrets_encrypts_destination(tmp_path, monkeypatch):
    source_file = tmp_path / "downloaded.json"
    target_file = tmp_path / "managed-credentials.json"
    key = Fernet.generate_key().decode()
    payload = json.dumps({"installed": {"client_id": "cid", "client_secret": "secret"}})
    source_file.write_text(payload)

    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)
    monkeypatch.setattr(security, "GMAIL_CREDENTIALS_FILE", target_file)

    result = import_gmail_client_secrets(source_file)

    assert result == target_file
    stored = target_file.read_text()
    assert stored != payload
    assert _decrypt_for_test(key, stored) == payload


def test_get_gmail_client_config_migrates_plaintext_file_when_key_present(tmp_path, monkeypatch):
    creds_file = tmp_path / "credentials.json"
    key = Fernet.generate_key().decode()
    payload = json.dumps({"installed": {"client_id": "cid", "client_secret": "secret"}})
    creds_file.write_text(payload)

    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)
    monkeypatch.setattr(security, "GMAIL_CREDENTIALS_FILE", creds_file)

    client_config = get_gmail_client_config()

    assert client_config == {"installed": {"client_id": "cid", "client_secret": "secret"}}
    stored = creds_file.read_text()
    assert stored != payload
    assert _decrypt_for_test(key, stored) == payload


def test_write_token_payload_sets_private_permissions(tmp_path, monkeypatch):
    token_path = tmp_path / "gmail_u1.json"
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)

    payload = json.dumps({"token": "abc", "refresh_token": "refresh", "client_id": "cid", "client_secret": "secret"})
    security.write_gmail_token_payload(token_path, payload)

    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600


def test_ensure_gmail_credentials_file_secure_hardens_permissions(tmp_path, monkeypatch):
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    creds_file.chmod(0o644)

    monkeypatch.setattr(security, "GMAIL_CREDENTIALS_FILE", creds_file)

    assert security.ensure_gmail_credentials_file_secure() is True
    assert stat.S_IMODE(creds_file.stat().st_mode) == 0o600


def test_complete_oauth_uses_encrypted_token_storage(tmp_path, monkeypatch):
    fake_flow_instance = types.SimpleNamespace(
        fetch_token=lambda code: None,
        credentials=types.SimpleNamespace(
            to_json=lambda: json.dumps({"token": "abc", "refresh_token": "refresh", "client_id": "cid", "client_secret": "secret"})
        ),
    )
    fake_flow_class = types.SimpleNamespace(
        from_client_config=lambda *args, **kwargs: fake_flow_instance
    )

    key = Fernet.generate_key().decode()
    token_path = tmp_path / "gmail_u1.json"

    from core import gmail_oauth

    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)
    monkeypatch.setattr(gmail_oauth, "Flow", fake_flow_class)
    monkeypatch.setattr(gmail_oauth, "get_gmail_client_config", lambda: {"installed": {"client_id": "cid", "client_secret": "secret"}})
    monkeypatch.setattr(gmail_oauth.db, "get_oauth_state", lambda state: {"user_id": "u1", "chat_id": "c1"})
    monkeypatch.setattr(gmail_oauth.db, "set_user_consent", lambda *args, **kwargs: None)
    monkeypatch.setattr(gmail_oauth, "get_gmail_token_path", lambda user_id: token_path)

    result = gmail_oauth.complete_oauth("code-123", "state-123")

    assert result == ("u1", "c1")
    stored = token_path.read_text()
    assert stored != fake_flow_instance.credentials.to_json()
    assert _decrypt_for_test(key, stored) == fake_flow_instance.credentials.to_json()


def test_generate_auth_url_uses_decrypted_client_config(monkeypatch):
    from core import gmail_oauth

    captured = {}

    class FakeFlow:
        def authorization_url(self, **kwargs):
            captured["authorization_kwargs"] = kwargs
            return "https://auth.example", None

    def fake_from_client_config(client_config, **kwargs):
        captured["client_config"] = client_config
        captured["flow_kwargs"] = kwargs
        return FakeFlow()

    monkeypatch.setattr(gmail_oauth, "WEBHOOK_HOST", "https://example.com")
    monkeypatch.setattr(gmail_oauth, "get_gmail_client_config", lambda: {"installed": {"client_id": "cid", "client_secret": "secret"}})
    monkeypatch.setattr(gmail_oauth, "Flow", types.SimpleNamespace(from_client_config=fake_from_client_config))
    monkeypatch.setattr(gmail_oauth.db, "save_oauth_state", lambda *args, **kwargs: None)

    url = gmail_oauth.generate_auth_url("u1", "chat-1")

    assert url == "https://auth.example"
    assert captured["client_config"]["installed"]["client_id"] == "cid"
    assert captured["flow_kwargs"]["scopes"] == gmail_oauth.GMAIL_SCOPES
    assert captured["flow_kwargs"]["redirect_uri"] == gmail_oauth.get_redirect_uri()


def test_main_import_gmail_client_secrets_command(monkeypatch, capsys):
    import main as main_module

    monkeypatch.setattr(sys, "argv", ["main.py", "--import-gmail-client-secrets", "/tmp/client.json"])
    monkeypatch.setattr(main_module, "import_gmail_client_secrets", lambda path: Path("credentials.json"))

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "Imported Gmail client secrets" in captured.out


@pytest.mark.asyncio
async def test_dispatch_setkey_command():
    from dispatcher import dispatch

    fake_tool = types.SimpleNamespace(
        name="apikeys",
        execute=AsyncMock(return_value="✅ บันทึก key แล้ว"),
    )

    with patch("dispatcher.registry.get_by_command", return_value=fake_tool):
        response, tool_used, model, tokens = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/setkey tmd abc123",
        )

    fake_tool.execute.assert_awaited_once_with("u1", "tmd abc123", command="/setkey", chat_id=None, message_id=None)
    assert "บันทึก key" in response
    assert tool_used == "apikeys"
    assert model is None
    assert tokens == 0


@pytest.mark.asyncio
async def test_dispatch_mykeys_command():
    from dispatcher import dispatch

    fake_tool = types.SimpleNamespace(
        name="apikeys",
        execute=AsyncMock(return_value="tmd\n2026-03-24T12:34:56"),
    )
    with patch("dispatcher.registry.get_by_command", return_value=fake_tool):
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/mykeys",
        )

    fake_tool.execute.assert_awaited_once_with("u1", "", command="/mykeys", chat_id=None, message_id=None)
    assert "tmd" in response


@pytest.mark.asyncio
async def test_dispatch_removekey_command():
    from dispatcher import dispatch

    fake_tool = types.SimpleNamespace(
        name="apikeys",
        execute=AsyncMock(return_value="✅ ลบ key แล้ว"),
    )
    with patch("dispatcher.registry.get_by_command", return_value=fake_tool):
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/removekey work_imap_password",
        )

    fake_tool.execute.assert_awaited_once_with("u1", "work_imap_password", command="/removekey", chat_id=None, message_id=None)
    assert "ลบ key" in response