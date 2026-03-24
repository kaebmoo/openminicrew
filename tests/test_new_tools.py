import sys
import types
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from googleapiclient.errors import HttpError

from tools.promptpay import _build_promptpay_payload, _normalize_phone, _resolve_promptpay_input, ID_TYPE_NATIONAL_ID
from tools.qrcode_gen import QRCodeGenTool
from tools.response import MediaResponse
from tools.unit_converter import UnitConverterTool
from tools.todo import TodoTool
from tools.reminder import ReminderTool
from tools.web_search import WebSearchTool, _format_search_results, _rank_and_filter_results
from tools.calendar_tool import CalendarTool
from tools.expense import ExpenseTool
from tools.smart_inbox import SmartInboxTool
from tools.places import PlacesTool
from tools.base import BaseTool
from tools.registry import ToolRegistry


def test_promptpay_payload_contains_crc_suffix():
    payload = _build_promptpay_payload("0066812345678", amount=120.5)
    assert payload.startswith("000201")
    assert "6304" in payload
    assert len(payload) > 20


def test_promptpay_phone_fallback_normalization():
    assert _normalize_phone("081-234-5678") == "0066812345678"


def test_promptpay_resolves_valid_national_id():
    promptpay_id, id_type = _resolve_promptpay_input("1234567890121")
    assert promptpay_id == "1234567890121"
    assert id_type == ID_TYPE_NATIONAL_ID


def test_qrcode_execute_returns_media_response():
    tool = QRCodeGenTool()

    class FakeQR:
        def save(self, buf, kind, **kwargs):
            assert kind == "png"
            assert kwargs["scale"] == 8
            assert kwargs["border"] == 2
            buf.write(b"fake-png")

    fake_segno = SimpleNamespace(make=lambda payload, error: FakeQR())

    with patch("tools.qrcode_gen.import_module", return_value=fake_segno), \
         patch("tools.qrcode_gen.db.log_tool_usage"):
        result = asyncio.run(tool.execute("u1", "https://example.com"))

    assert isinstance(result, MediaResponse)
    assert result.image == b"fake-png"
    assert "example.com" in result.text


def test_unit_converter_length_and_land():
    tool = UnitConverterTool()
    assert "6.2137" in asyncio.run(tool.execute("u1", "10 km to mi"))
    assert "2,000" in asyncio.run(tool.execute("u1", "1-1-0 เป็น ตารางเมตร"))


def test_unit_converter_supports_reverse_length_aliases():
    tool = UnitConverterTool()
    assert "1.6093" in asyncio.run(tool.execute("u1", "1 mile to km"))
    assert "0.3048" in asyncio.run(tool.execute("u1", "1 foot to m"))
    assert "2" in asyncio.run(tool.execute("u1", "2 litres to l"))


def test_todo_add_and_done():
    tool = TodoTool()
    with patch("tools.todo.db.add_todo", return_value=7):
        text = asyncio.run(tool.execute("u1", "add ทำสไลด์ !high due:2026-03-30 18:00"))
    assert "#7" in text
    assert "high" in text

    with patch("tools.todo.db.update_todo_status", return_value=True):
        result = asyncio.run(tool.execute("u1", "done 7"))
    assert "done" in result


def test_reminder_fire_marks_sent():
    tool = ReminderTool()
    with patch("tools.reminder.db.get_reminder", return_value={"id": 3, "text": "ประชุมทีม"}), \
         patch("tools.reminder.db.mark_reminder_sent") as mock_mark:
        result = asyncio.run(tool.execute("u1", "fire 3"))
    mock_mark.assert_called_once_with(3)
    assert "ประชุมทีม" in result


def test_web_search_uses_ddg_fallback_result():
    tool = WebSearchTool()
    with patch.object(tool, "_search_ddg", return_value=[
        {
            "title": "Thai AI News",
            "url": "https://example.com/thai-ai",
            "snippet": "ข่าว AI ล่าสุดในไทย",
        }
    ]), \
         patch("tools.web_search.get_api_key", return_value=None), \
         patch("tools.web_search._generate_quick_summary", return_value=""), \
         patch("tools.web_search.db.log_tool_usage"):
        result = asyncio.run(tool.execute("u1", "thai ai"))
    assert "Thai AI News" in result
    assert "example.com" in result


def test_web_search_formats_results_compactly():
    result = _format_search_results(
        "ราคาน้ำมัน",
        [
            {
                "title": "ราคาน้ำมันวันนี้ | Caltex Thailand",
                "url": "https://www.caltex.com/th/motorists/products-and-services/fuel-prices.html",
                "snippet": "ราคาน้ำมัน\n\n## ราคาน้ำมัน\n\nปรับปรุงล่าสุด March 10, 2026 05:00AM | ดีเซล B7 29.94 | พาวเวอร์ ดีเซล 45.64 | [ ... ] โปรโมชั่นและข้อมูลอื่น ๆ",
            }
        ],
    )

    assert "1. ราคาน้ำมันวันนี้ | Caltex Thailand" in result
    assert "เว็บ: caltex.com" in result
    assert "ลิงก์: https://www.caltex.com/th/motorists/products-and-services/fuel-prices.html" in result
    assert "สรุป:" in result
    assert "[ ... ]" not in result
    assert "## ราคาน้ำมัน" not in result


def test_web_search_ranking_prefers_official_and_dedupes():
    ranked = _rank_and_filter_results(
        "ราคาน้ำมัน",
        [
            {
                "title": "ราคาน้ำมันวันนี้",
                "url": "https://energy.go.th/oil",
                "snippet": "ราคาน้ำมันวันนี้จากหน่วยงานรัฐ",
            },
            {
                "title": "ราคาน้ำมันวันนี้",
                "url": "https://www.energy.go.th/oil",
                "snippet": "duplicate",
            },
            {
                "title": "OpenClaw review on YouTube",
                "url": "https://youtube.com/watch?v=123",
                "snippet": "video",
            },
        ],
    )

    assert ranked[0]["url"] == "https://energy.go.th/oil"
    assert len(ranked) == 2


def test_web_search_execute_adds_quick_summary_for_factual_query():
    tool = WebSearchTool()
    with patch.object(tool, "_search_ddg", return_value=[
        {
            "title": "ราคาน้ำมันวันนี้",
            "url": "https://energy.go.th/oil",
            "snippet": "ดีเซล 29.94 บาท/ลิตร",
        }
    ]), \
         patch("tools.web_search.get_api_key", return_value=None), \
         patch("tools.web_search._generate_quick_summary", return_value="ดีเซลอยู่ราว 29.94 บาท/ลิตร"), \
         patch("tools.web_search.db.log_tool_usage"):
        result = asyncio.run(tool.execute("u1", "ราคาน้ำมันวันนี้"))

    assert "สรุปเร็ว: ดีเซลอยู่ราว 29.94 บาท/ลิตร" in result


def test_calendar_list_formats_events():
    tool = CalendarTool()
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {"id": "evt1", "summary": "ประชุม", "start": {"dateTime": "2026-03-30T09:00:00+07:00"}}
        ]
    }
    with patch("tools.calendar_tool.get_gmail_credentials", return_value=object()), \
         patch("tools.calendar_tool.build", return_value=service):
        result = asyncio.run(tool.execute("u1", "list"))
    assert "evt1" not in result
    assert "ประชุม" in result
    assert "2026-03-30 09:00" in result
    assert "1. 2026-03-30 09:00" in result


def test_calendar_list_keeps_birthday_and_collapses_recurring_events():
    tool = CalendarTool()
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "pay-1",
                "summary": "จ่ายค่า MacBook",
                "start": {"dateTime": "2026-03-27T09:00:00+07:00"},
                "recurringEventId": "series-pay",
            },
            {
                "id": "pay-2",
                "summary": "จ่ายค่า MacBook",
                "start": {"dateTime": "2026-04-27T09:00:00+07:00"},
                "recurringEventId": "series-pay",
            },
            {
                "id": "birthday-1",
                "summary": "วันเกิดของ Lek NCS",
                "start": {"date": "2026-06-28"},
                "eventType": "birthday",
            },
        ]
    }
    with patch("tools.calendar_tool.get_gmail_credentials", return_value=object()), \
         patch("tools.calendar_tool.build", return_value=service):
        result = asyncio.run(tool.execute("u1", "list"))

    assert "1. 2026-03-27 09:00 — จ่ายค่า MacBook" in result
    assert "2026-04-27 09:00" not in result
    assert "Lek NCS" in result


def test_calendar_delete_accepts_visible_list_index():
    tool = CalendarTool()
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt-delete-1",
                "summary": "ประชุมทีม",
                "start": {"dateTime": "2026-03-30T09:00:00+07:00"},
            }
        ]
    }

    with patch("tools.calendar_tool.get_gmail_credentials", return_value=object()), \
         patch("tools.calendar_tool.build", return_value=service):
        result = asyncio.run(tool.execute("u1", "delete 1"))

    service.events.return_value.delete.assert_called_once_with(
        calendarId="primary",
        eventId="evt-delete-1",
    )
    assert "evt-delete-1" in result


def test_calendar_error_access_not_configured_is_human_friendly():
    tool = CalendarTool()
    resp = MagicMock()
    resp.status = 403
    error = HttpError(
        resp=resp,
        content=b'{"error":{"message":"accessNotConfigured: Google Calendar API has not been used"}}',
        uri="https://example.com/calendar",
    )

    with patch("tools.calendar_tool.get_gmail_credentials", return_value=object()), \
         patch("tools.calendar_tool.build", side_effect=error):
        result = asyncio.run(tool.execute("u1", "list"))

    assert "ยังไม่ได้เปิดใช้งาน" in result
    assert "Google Calendar API" in result


def test_expense_summary_formats_rows():
    tool = ExpenseTool()
    with patch("tools.expense.db.summarize_expenses", return_value=[{"category": "อาหาร", "total": 250.0, "count": 2}]):
        result = asyncio.run(tool.execute("u1", "summary month"))
    assert "อาหาร" in result
    assert "250.00" in result


def test_smart_inbox_mode_command():
    tool = SmartInboxTool()
    with patch("tools.smart_inbox.set_preference") as mock_set:
        result = asyncio.run(tool.execute("u1", "mode auto"))
    mock_set.assert_called_once_with("u1", "smart_inbox_mode", "auto")
    assert "auto" in result


def test_places_no_longer_claims_search_command():
    tool = PlacesTool()
    assert "/search" not in tool.commands


def test_registry_keeps_first_duplicate_command_mapping():
    registry = ToolRegistry()

    class FirstTool(BaseTool):
        name = "first"
        description = "first"
        commands = ["/dup"]

        async def execute(self, user_id: str, args: str = "", **kwargs):
            return "first"

        def get_tool_spec(self) -> dict:
            return {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {}}}

    class SecondTool(BaseTool):
        name = "second"
        description = "second"
        commands = ["/dup"]

        async def execute(self, user_id: str, args: str = "", **kwargs):
            return "second"

        def get_tool_spec(self) -> dict:
            return {"name": self.name, "description": self.description, "parameters": {"type": "object", "properties": {}}}

    first_module = types.ModuleType("tools.first_module")
    second_module = types.ModuleType("tools.second_module")
    setattr(first_module, "FirstTool", FirstTool)
    setattr(second_module, "SecondTool", SecondTool)

    def fake_import_module(name: str):
        if name == "tools.first_module":
            return first_module
        if name == "tools.second_module":
            return second_module
        raise ImportError(name)

    with patch("tools.registry.pkgutil.iter_modules", return_value=[
        (None, "first_module", False),
        (None, "second_module", False),
    ]), patch("tools.registry.importlib.import_module", side_effect=fake_import_module):
        registry.discover()

    assert registry.get_by_command("/dup").name == "first"


# ── /model matcha with per-user key ──────────────────────────


def test_matcha_provider_available_with_user_key():
    """MatchaProvider.is_available_for_user ต้อง return True เมื่อ user มี key"""
    from core.providers.matcha_provider import MatchaProvider

    provider = MatchaProvider()

    # ไม่มี shared key → is_configured() = False
    with patch("core.providers.matcha_provider.MATCHA_API_KEY", ""):
        assert provider.is_configured() is False

        # mock per-user key → is_available_for_user = True
        with patch("core.api_keys.get_api_key", return_value="sk-user-key-123"):
            assert provider.is_available_for_user("user-abc") is True

        # ไม่มี per-user key → is_available_for_user = False
        with patch("core.api_keys.get_api_key", return_value=None):
            assert provider.is_available_for_user("user-abc") is False


def test_model_command_shows_matcha_when_user_has_key():
    """
    /model matcha ต้องสำเร็จเมื่อ user ตั้ง per-user key แล้ว
    แม้ .env จะไม่มี MATCHA_API_KEY
    """
    from dispatcher import _handle_model_command

    fake_user = {"user_id": "u1", "default_llm": "claude"}

    # Mock: matcha ไม่มี shared key แต่มี per-user key
    with patch("core.providers.matcha_provider.MATCHA_API_KEY", ""), \
         patch("core.api_keys.get_api_key", return_value="sk-user-key"), \
         patch("dispatcher.set_preference") as mock_set_pref:

        result = _handle_model_command("u1", fake_user, "matcha")

        assert "✅" in result
        assert "matcha" in result
        mock_set_pref.assert_called_once_with("u1", "default_llm", "matcha")


def test_model_command_rejects_matcha_without_any_key():
    """
    /model matcha ต้อง reject เมื่อไม่มีทั้ง shared key และ per-user key
    """
    from dispatcher import _handle_model_command

    fake_user = {"user_id": "u1", "default_llm": "claude"}

    with patch("core.providers.matcha_provider.MATCHA_API_KEY", ""), \
         patch("core.api_keys.get_api_key", return_value=None):

        result = _handle_model_command("u1", fake_user, "matcha")

        assert "❌" in result
        assert "matcha" in result