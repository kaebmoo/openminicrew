import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.consent import ConsentTool
from tools.smart_inbox import SmartInboxTool
from tools.traffic import TrafficTool


def test_consent_parser_prefers_negative_phrases():
    tool = ConsentTool()

    assert tool._parse_args("ไม่อนุญาตเก็บตำแหน่ง") == ("location_access", False)
    assert tool._parse_args("ไม่ยินยอมบันทึกการสนทนา") == ("chat_history", False)
    assert tool._parse_args("ขอไม่อนุญาต location") == ("location_access", False)


def test_traffic_parser_handles_compact_natural_language_routes():
    tool = TrafficTool()

    assert tool._parse_route_args("จากสยามไปสีลมรถติดไหม") == ("สยาม", "สีลม")
    assert tool._parse_route_args("สยามไปสีลม") == ("สยาม", "สีลม")
    assert tool._parse_route_args("ไปบางรักรถติดไหม") == ("ที่นี่", "บางรัก")


def test_smart_inbox_parse_action_items_ignores_non_list_lines():
    analysis = "- ส่งเอกสารให้ HR\n1. ตอบลูกค้าเรื่องสัญญา\n2026-04-01 ประชุมทีม\n• ตรวจ invoice"

    items = SmartInboxTool._parse_action_items(analysis)

    assert items == [
        "ส่งเอกสารให้ HR",
        "ตอบลูกค้าเรื่องสัญญา",
        "ตรวจ invoice",
    ]


def test_smart_inbox_auto_mode_creates_only_parsed_action_items():
    tool = SmartInboxTool()

    with patch("tools.smart_inbox.get_gmail_credentials", return_value=object()), \
         patch("tools.smart_inbox.get_user_by_id", return_value={"smart_inbox_mode": "auto"}), \
         patch("tools.smart_inbox.build", return_value=object()), \
         patch.object(tool, "_fetch_recent_messages", new=AsyncMock(return_value=[{"subject": "s", "from": "f", "date": "d", "body": "b"}])), \
         patch.object(tool, "_extract_action_items", new=AsyncMock(return_value="- ส่งเอกสารให้ HR\n2026-04-01 ประชุมทีม\n• ตรวจ invoice")), \
         patch("tools.smart_inbox.db.add_todo", side_effect=[11, 12]) as mock_add_todo, \
         patch("tools.smart_inbox.db.log_tool_usage"):
        result = asyncio.run(tool.execute("u1", ""))

    assert mock_add_todo.call_count == 2
    created_titles = [call.kwargs["title"] for call in mock_add_todo.call_args_list]
    assert created_titles == ["ส่งเอกสารให้ HR", "ตรวจ invoice"]
    assert "#11" in result and "#12" in result