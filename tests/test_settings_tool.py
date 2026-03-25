import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.settings import SettingsTool


def test_settings_setphone_validates_and_normalizes_phone():
    tool = SettingsTool()
    user = {"user_id": "u1", "phone_number": None}

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.db.update_user_profile") as mock_update, \
         patch("interfaces.telegram_common.delete_message_safe") as mock_delete:
        import asyncio

        result = asyncio.run(
            tool.execute(
                "u1",
                args="081-234-5678",
                command="/setphone",
                chat_id="chat-1",
                message_id=99,
            )
        )

    mock_update.assert_called_once_with("u1", phone_number="0812345678")
    mock_delete.assert_called_once_with("chat-1", 99)
    assert "0812345678" in result


def test_settings_setphone_rejects_invalid_phone():
    tool = SettingsTool()
    user = {"user_id": "u1", "phone_number": None}

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.db.update_user_profile") as mock_update:
        import asyncio

        result = asyncio.run(tool.execute("u1", args="12345", command="/setphone"))

    mock_update.assert_not_called()
    assert "เบอร์โทรไม่ถูกต้อง" in result


def test_settings_setid_returns_error_when_encryption_key_missing():
    tool = SettingsTool()
    user = {"user_id": "u1", "national_id": None}

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.db.update_user_profile", side_effect=RuntimeError("ENCRYPTION_KEY is required for national_id storage")):
        import asyncio

        result = asyncio.run(tool.execute("u1", args="1234567890121", command="/setid"))

    assert "ENCRYPTION_KEY is required" in result