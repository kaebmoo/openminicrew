import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from core import api_keys
from core.security import get_gmail_credentials


def test_shared_service_falls_back_to_env():
    with patch("core.api_keys.db.get_user_api_key", return_value=None), \
         patch.object(api_keys.config, "TMD_API_KEY", "shared-tmd-key"):
        assert api_keys.get_api_key("u1", "tmd") == "shared-tmd-key"


def test_private_service_never_falls_back_to_env():
    with patch("core.api_keys.db.get_user_api_key", return_value=None), \
         patch.object(api_keys.config, "GOOGLE_MAPS_API_KEY", "shared-google-maps"):
        assert api_keys.get_api_key("u1", "work_imap_password") is None


def test_gmail_credentials_do_not_fallback_to_owner(tmp_path, monkeypatch):
    missing_token = tmp_path / "missing.json"
    monkeypatch.setattr("core.security.get_gmail_token_path", lambda user_id: Path(missing_token))

    assert get_gmail_credentials("non-owner") is None


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