import asyncio
import base64
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from tools.exchange_rate import ExchangeRateTool
from tools.gmail_summary import GmailSummaryTool
from tools.news_summary import NewsSummaryTool
from tools.schedule import ScheduleTool
from tools.work_email import AttachmentData, EmailData, WorkEmailTool


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def test_news_summary_uses_user_id_for_preference_lookup():
    tool = NewsSummaryTool()
    rss = (
        "<rss><channel>"
        "<item><title>News One - Source A</title><link>https://example.com/a</link></item>"
        "</channel></rss>"
    ).encode("utf-8")

    with patch("tools.news_summary.requests.get", return_value=_FakeResponse(rss)), \
         patch("tools.news_summary.get_user_by_id", return_value={"user_id": "u-1", "default_llm": "claude"}), \
         patch("tools.news_summary.llm_router.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": "สรุปข่าว", "model": "claude-test", "token_used": 10}
        result = asyncio.run(tool.execute("u-1", "เศรษฐกิจ"))

    assert "สรุปข่าว" in result
    assert mock_chat.call_args.kwargs["provider"] == "claude"


def test_gmail_summary_uses_user_id_for_preference_lookup():
    tool = GmailSummaryTool()
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "m1"}]
    }
    payload_data = base64.urlsafe_b64encode("สวัสดี".encode("utf-8")).decode("ascii")
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "เรื่องด่วน"},
                {"name": "From", "value": "Boss <boss@example.com>"},
            ],
            "body": {"data": payload_data},
        },
        "snippet": "สวัสดี",
    }

    with patch("tools.gmail_summary.get_gmail_credentials", return_value=object()), \
         patch("tools.gmail_summary.build", return_value=service), \
         patch("tools.gmail_summary.get_user_by_id", return_value={"user_id": "user-42", "default_llm": "gemini"}), \
         patch("tools.gmail_summary.db.is_email_processed", return_value=False), \
         patch("tools.gmail_summary.db.mark_email_processed"), \
         patch("tools.gmail_summary.db.log_tool_usage"), \
         patch("tools.gmail_summary.llm_router.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": "สรุปเมล", "model": "gemini-test", "token_used": 11}
        result = asyncio.run(tool.execute("user-42", "7d"))

    assert "สรุปเมล" in result
    assert mock_chat.call_args.kwargs["provider"] == "gemini"


def test_work_email_uses_user_id_for_preference_lookup():
    tool = WorkEmailTool()
    email_data = EmailData(
        message_id="m1",
        subject="Budget",
        sender="finance@example.com",
        date="Tue, 31 Mar 2026 09:00:00 +0700",
        body="งบประมาณล่าสุด",
        attachments=[AttachmentData(filename="budget.pdf", size_bytes=12, mime_type="application/pdf")],
    )

    with patch.object(tool, "_resolve_imap_credentials", return_value=("host", "user", "pass")), \
         patch.object(tool, "_sync_fetch_all", return_value=([email_data], 0)), \
         patch("tools.work_email.get_user_by_id", return_value={"user_id": "emp-1", "default_llm": "matcha"}), \
         patch("tools.work_email.db.mark_email_processed"), \
         patch("tools.work_email.db.log_tool_usage"), \
         patch("tools.work_email.llm_router.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": "สรุปเมลงาน", "model": "matcha-test", "token_used": 12}
        result = asyncio.run(tool.execute("emp-1", "today"))

    assert "สรุปเมลที่ทำงาน" in result
    assert mock_chat.call_args.kwargs["provider"] == "matcha"


def test_schedule_owner_remove_uses_user_id_lookup():
    tool = ScheduleTool()
    fake_scheduler = types.SimpleNamespace(reload_custom_schedules=lambda: None)

    with patch("tools.schedule.get_user_by_id", return_value={"user_id": "owner-user", "role": "owner"}), \
         patch("tools.schedule.db.get_schedule_by_id", return_value={"id": 7, "user_id": "u2", "is_active": 1}), \
         patch("tools.schedule.db.remove_schedule") as mock_remove, \
         patch.dict(sys.modules, {"scheduler": fake_scheduler}):
        result = tool._remove("owner-user", "7")

    mock_remove.assert_called_once_with(7, "u2")
    assert "ลบ schedule ID 7 แล้ว" in result


def test_exchange_rate_execute_accepts_none_args():
    tool = ExchangeRateTool()

    with patch("tools.exchange_rate._fetch_exchange_rate", return_value={
        "buying_sight": "33.10",
        "buying_transfer": "33.20",
        "selling": "33.30",
    }), \
         patch("tools.exchange_rate.db.log_tool_usage"):
        result = asyncio.run(tool.execute("u1", args=None))

    assert "USD" in result
    assert "GBP" in result