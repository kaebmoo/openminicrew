"""Tests for /myemail command in SettingsTool"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.settings import SettingsTool


def test_myemail_no_gmail_no_work_email():
    """ไม่มี Gmail credentials + ไม่มี Work Email → แสดง ❌ ทั้งคู่"""
    tool = SettingsTool()
    user = {"user_id": "u1"}

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.get_gmail_credentials", return_value=None), \
         patch("tools.settings.get_api_key", return_value=None), \
         patch("tools.settings.db.log_tool_usage"), \
         patch("tools.settings.db.make_log_field", return_value={}):

        result = asyncio.run(
            tool.execute("u1", args="", command="/myemail")
        )

    assert "❌ Gmail" in result
    assert "❌ Work Email" in result
    assert "/authgmail" in result
    assert "/setkey" in result


def test_myemail_with_gmail_connected():
    """มี Gmail credentials → แสดง ✅ Gmail พร้อม email address"""
    tool = SettingsTool()
    user = {"user_id": "u1"}

    mock_creds = MagicMock()
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "test@gmail.com"
    }

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.get_gmail_credentials", return_value=mock_creds), \
         patch("tools.settings.get_api_key", return_value=None), \
         patch("googleapiclient.discovery.build", return_value=mock_service), \
         patch("tools.settings.db.log_tool_usage"), \
         patch("tools.settings.db.make_log_field", return_value={}):

        result = asyncio.run(
            tool.execute("u1", args="", command="/myemail")
        )

    assert "✅ Gmail: test@gmail.com" in result
    assert "❌ Work Email" in result


def test_myemail_with_work_email():
    """มี Work Email IMAP → แสดง ✅ Work Email พร้อม user + host"""
    tool = SettingsTool()
    user = {"user_id": "u1"}

    def mock_get_api_key(user_id, service):
        if service == "work_imap_user":
            return "user@company.com"
        if service == "work_imap_host":
            return "mail.company.com"
        return None

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.get_gmail_credentials", return_value=None), \
         patch("tools.settings.get_api_key", side_effect=mock_get_api_key), \
         patch("tools.settings.db.log_tool_usage"), \
         patch("tools.settings.db.make_log_field", return_value={}):

        result = asyncio.run(
            tool.execute("u1", args="", command="/myemail")
        )

    assert "❌ Gmail" in result
    assert "✅ Work Email: user@company.com (mail.company.com)" in result


def test_myemail_both_connected():
    """มีทั้ง Gmail + Work Email → แสดง ✅ ทั้งคู่"""
    tool = SettingsTool()
    user = {"user_id": "u1"}

    mock_creds = MagicMock()
    mock_service = MagicMock()
    mock_service.users.return_value.getProfile.return_value.execute.return_value = {
        "emailAddress": "myaccount@gmail.com"
    }

    def mock_get_api_key(user_id, service):
        if service == "work_imap_user":
            return "worker@org.co.th"
        if service == "work_imap_host":
            return "mail.org.co.th"
        return None

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.get_gmail_credentials", return_value=mock_creds), \
         patch("tools.settings.get_api_key", side_effect=mock_get_api_key), \
         patch("googleapiclient.discovery.build", return_value=mock_service), \
         patch("tools.settings.db.log_tool_usage"), \
         patch("tools.settings.db.make_log_field", return_value={}):

        result = asyncio.run(
            tool.execute("u1", args="", command="/myemail")
        )

    assert "✅ Gmail: myaccount@gmail.com" in result
    assert "✅ Work Email: worker@org.co.th (mail.org.co.th)" in result


def test_myemail_via_llm_action():
    """LLM ส่ง action=myemail → ทำงานเหมือน /myemail"""
    tool = SettingsTool()
    user = {"user_id": "u1"}

    with patch("tools.settings.db.get_user_by_chat_id", return_value=user), \
         patch("tools.settings.get_gmail_credentials", return_value=None), \
         patch("tools.settings.get_api_key", return_value=None), \
         patch("tools.settings.db.log_tool_usage"), \
         patch("tools.settings.db.make_log_field", return_value={}):

        result = asyncio.run(
            tool.execute("u1", args="", action="myemail")
        )

    assert "📧 บัญชีอีเมลที่ตั้งค่าไว้" in result
