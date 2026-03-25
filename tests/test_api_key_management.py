import sys
import types
import json
import stat
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

from core import api_keys
from core import security
from core.security import get_gmail_credentials


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


def test_get_api_key_warns_when_key_missing_for_stored_private_key(monkeypatch, caplog):
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    with patch("core.api_keys.db.get_user_api_key", return_value="gAAAAencrypted"):
        value = api_keys.get_api_key("u1", "gmail")

    assert value == "gAAAAencrypted"
    assert "ENCRYPTION_KEY not set while reading stored private key" in caplog.text


def test_set_api_key_requires_encryption_key(monkeypatch):
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is required"):
        api_keys.set_api_key("u1", "tmd", "secret")


def test_set_api_key_encrypts_value_when_key_exists(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", key)

    with patch("core.api_keys.db.upsert_user_api_key") as mock_upsert:
        api_keys.set_api_key("u1", "tmd", "secret")

    stored_value = mock_upsert.call_args.args[2]
    assert stored_value != "secret"
    assert Fernet(key.encode()).decrypt(stored_value.encode()).decode() == "secret"


@pytest.mark.asyncio
async def test_apikey_tool_returns_error_when_encryption_key_missing(monkeypatch):
    from tools.apikeys import ApiKeysTool

    monkeypatch.setattr(api_keys.config, "ENCRYPTION_KEY", "")

    response = await ApiKeysTool().execute("u1", args="tmd abc123", command="/setkey")

    assert "ENCRYPTION_KEY is required" in response


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
        from_client_secrets_file=lambda *args, **kwargs: fake_flow_instance
    )

    key = Fernet.generate_key().decode()
    token_path = tmp_path / "gmail_u1.json"
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")

    from core import gmail_oauth

    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", key)
    monkeypatch.setattr(gmail_oauth, "GMAIL_CREDENTIALS_FILE", creds_file)
    monkeypatch.setattr(gmail_oauth, "Flow", fake_flow_class)
    monkeypatch.setattr(gmail_oauth.db, "get_oauth_state", lambda state: {"user_id": "u1", "chat_id": "c1"})
    monkeypatch.setattr(gmail_oauth, "get_gmail_token_path", lambda user_id: token_path)

    result = gmail_oauth.complete_oauth("code-123", "state-123")

    assert result == ("u1", "c1")
    stored = token_path.read_text()
    assert stored != fake_flow_instance.credentials.to_json()
    assert _decrypt_for_test(key, stored) == fake_flow_instance.credentials.to_json()


@pytest.mark.asyncio
async def test_dispatch_setkey_command():
    from dispatcher import dispatch

    with patch("dispatcher.set_api_key") as mock_set_api_key:
        response, tool_used, model, tokens = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/setkey tmd abc123",
        )

    mock_set_api_key.assert_called_once_with("u1", "tmd", "abc123")
    assert "บันทึก key" in response
    assert tool_used is None
    assert model is None
    assert tokens == 0


@pytest.mark.asyncio
async def test_dispatch_mykeys_command():
    from dispatcher import dispatch

    fake_keys = [{"service": "tmd", "updated_at": "2026-03-24T12:34:56"}]
    with patch("dispatcher.list_user_keys", return_value=fake_keys):
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/mykeys",
        )

    assert "tmd" in response


@pytest.mark.asyncio
async def test_dispatch_removekey_command():
    from dispatcher import dispatch

    with patch("dispatcher.remove_api_key", return_value=True) as mock_remove_api_key:
        response, _, _, _ = await dispatch(
            user_id="u1",
            user={"telegram_chat_id": "123", "role": "user"},
            text="/removekey work_imap_password",
        )

    mock_remove_api_key.assert_called_once_with("u1", "work_imap_password")
    assert "ลบ key" in response