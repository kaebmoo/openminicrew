"""Unit tests for tools/lotto.py — Sanook-based implementation, mocked HTTP.

โครงสร้างปัจจุบัน (หลังย้ายจาก rayriffy API → Sanook):
  - ผลเต็มงวด parse จาก JSON-LD `articleBody` ในหน้า news.sanook.com/lotto/check/<DDMMYYYY>/
  - งวดล่าสุด + รายการงวด ดึงจาก Sanook RSS
  - Sanook ไม่ 404 — date ที่ไม่มีจริงจะ serve งวดล่าสุดแทน → ต้องเทียบวันที่ในหน้า
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Provide required env vars so core.config doesn't sys.exit during import
os.environ.setdefault("OWNER_TELEGRAM_CHAT_ID", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
os.environ.setdefault("BOT_API_EXCHANGE_TOKEN", "x")
os.environ.setdefault("BOT_API_HOLIDAY_TOKEN", "x")

from tools.lotto import LottoTool, _http_get_text, _thai_date_to_id


# ---------- sample data ----------
# dict รูปแบบที่ _parse_article_body คืน (และ formatter รับ)
SAMPLE_DATA = {
    "date": "1 มิถุนายน 2569",
    "endpoint": "https://news.sanook.com/lotto/check/01062569/",
    "prizes": [
        {"id": "prizeFirst", "reward": "6000000", "number": ["123456"]},
        {"id": "prizeFirstNear", "reward": "100000", "number": ["123455", "123457"]},
        {"id": "prizeSecond", "reward": "200000",
         "number": ["111111", "222222", "333333", "444444", "555555"]},
    ],
    "runningNumbers": [
        {"id": "runningNumberFrontThree", "reward": "4000", "number": ["123", "789"]},
        {"id": "runningNumberBackThree", "reward": "4000", "number": ["456", "999"]},
        {"id": "runningNumberBackTwo", "reward": "2000", "number": ["56"]},
    ],
}

# articleBody ตามรูปแบบหน้า Sanook (บรรทัดหัวข้อรางวัล + บรรทัดเลข)
SAMPLE_BODY = "\n".join([
    "ตรวจหวย 1 มิถุนายน 2569",
    "รางวัลที่ 1 รางวัลละ 6,000,000 บาท",
    "123456",
    "รางวัลข้างเคียงรางวัลที่ 1 รางวัลละ 100,000 บาท",
    "123455 123457",
    "รางวัลที่ 2 รางวัลละ 200,000 บาท",
    "111111 222222 333333",
    "เลขหน้า 3 ตัว รางวัลละ 4,000 บาท",
    "123 789",
    "เลขท้าย 3 ตัว รางวัลละ 4,000 บาท",
    "456 999",
    "เลขท้าย 2 ตัว รางวัลละ 2,000 บาท",
    "56",
])

# หน้า HTML ของ Sanook ที่ฝัง articleBody ใน JSON-LD (json.dumps จัดการ escape ให้)
SAMPLE_HTML = (
    '<html><script type="application/ld+json">'
    '{"@type": "NewsArticle", "articleBody": ' + json.dumps(SAMPLE_BODY, ensure_ascii=False) + '}'
    '</script></html>'
)

SAMPLE_RSS = """<?xml version="1.0"?>
<rss><channel>
<item><title>[[ตรวจหวย 1 มิถุนายน 2569]]</title>
<link>https://news.sanook.com/lotto/check/01062569/</link></item>
<item><title>[[ตรวจหวย 16 พฤษภาคม 2569]]</title>
<link>https://news.sanook.com/lotto/check/16052569/</link></item>
<item><title>[[ตรวจหวย 2 พฤษภาคม 2569]]</title>
<link>https://news.sanook.com/lotto/check/02052569/</link></item>
</channel></rss>"""


@pytest.fixture
def tool():
    return LottoTool()


# ---------- _thai_date_to_id ----------
class TestThaiDateToId:
    def test_valid_date(self):
        assert _thai_date_to_id("1 มิถุนายน 2569") == "01062569"

    def test_two_digit_day(self):
        assert _thai_date_to_id("16 พฤษภาคม 2569") == "16052569"

    def test_with_prefix_text(self):
        assert _thai_date_to_id("งวดวันที่ 2 พฤษภาคม 2569") == "02052569"

    def test_unknown_month_returns_none(self):
        assert _thai_date_to_id("1 มิถุนา 2569") is None

    def test_garbage_returns_none(self):
        assert _thai_date_to_id("ไม่มีวันที่") is None


# ---------- _parse_args (เหมือนเดิมจาก implementation เก่า) ----------
class TestParseArgs:
    def test_empty_summary(self, tool):
        assert tool._parse_args("")["mode"] == "summary"

    def test_six_digit_positional_is_month(self, tool):
        # 6-digit positional ถูกตีความเป็น MMYYYY (month)
        # ใช้ `check <num>` ถ้าต้องการตรวจเลข 6 หลักแบบไม่กำกวม
        p = tool._parse_args("123456")
        assert p["mode"] == "month"

    def test_six_digit_check_explicit(self, tool):
        p = tool._parse_args("check 820866")
        assert p["mode"] == "check"
        assert p["number"] == "820866"

    def test_eight_digit_is_date(self, tool):
        p = tool._parse_args("01112567")
        assert p["mode"] == "summary"
        assert p["date_id"] == "01112567"

    def test_explicit_check_with_date(self, tool):
        p = tool._parse_args("check 820866 16022568")
        assert p["mode"] == "check"
        assert p["number"] == "820866"
        assert p["date_id"] == "16022568"

    def test_list_with_page(self, tool):
        p = tool._parse_args("list 2")
        assert p["mode"] == "list"
        assert p["page"] == 2

    def test_two_digit_check(self, tool):
        p = tool._parse_args("check 56")
        assert p["mode"] == "check"
        assert p["number"] == "56"

    def test_month_mode(self, tool):
        p = tool._parse_args("month 112567")
        assert p["mode"] == "month"
        assert p["date_id"] == "112567"


# ---------- formatting helpers ----------
class TestFormatting:
    def test_format_reward(self, tool):
        assert tool._format_reward("6000000") == "6,000,000"
        assert tool._format_reward("abc") == "abc"

    def test_format_summary_contains_first_prize(self, tool):
        out = tool._format_summary(SAMPLE_DATA)
        assert "123456" in out
        assert "6,000,000" in out
        assert "รางวัลที่ 1" in out

    def test_check_first_prize_win(self, tool):
        out = tool._format_check_result("123456", SAMPLE_DATA)
        assert "ถูก" in out and "รางวัลที่ 1" in out

    def test_check_back_two(self, tool):
        out = tool._format_check_result("56", SAMPLE_DATA)
        assert "ถูก" in out

    def test_check_no_win(self, tool):
        # 987654: front3=987, back3=654, back2=54 — ไม่อยู่ใน running numbers ตัวอย่าง
        out = tool._format_check_result("987654", SAMPLE_DATA)
        assert "ไม่ถูกรางวัล" in out

    def test_six_digit_back_two_match(self, tool):
        # 999956 ลงท้าย 56 → ถูกเลขท้าย 2 ตัว
        out = tool._format_check_result("999956", SAMPLE_DATA)
        assert "เลขท้าย 2 ตัว" in out


# ---------- _parse_article_body ----------
class TestParseArticleBody:
    def test_parses_all_buckets(self, tool):
        data = tool._parse_article_body(SAMPLE_BODY, "01062569")
        assert data["date"] == "1 มิถุนายน 2569"
        prize_ids = {p["id"]: p for p in data["prizes"]}
        assert prize_ids["prizeFirst"]["number"] == ["123456"]
        assert prize_ids["prizeFirst"]["reward"] == "6000000"
        assert prize_ids["prizeFirstNear"]["number"] == ["123455", "123457"]
        running_ids = {r["id"]: r for r in data["runningNumbers"]}
        assert running_ids["runningNumberBackTwo"]["number"] == ["56"]
        assert running_ids["runningNumberFrontThree"]["number"] == ["123", "789"]

    def test_no_first_prize_returns_none(self, tool):
        body = "ตรวจหวย 1 มิถุนายน 2569\nเลขท้าย 2 ตัว รางวัลละ 2,000 บาท\n56"
        assert tool._parse_article_body(body, "01062569") is None

    def test_empty_body_returns_none(self, tool):
        assert tool._parse_article_body("", "01062569") is None


# ---------- _http_get_text fallback path ----------
class TestHttpGetText:
    @patch("tools.lotto.requests.get")
    def test_direct_success(self, mock_get):
        resp = MagicMock(status_code=200, text="<html>ok</html>")
        mock_get.return_value = resp
        assert _http_get_text("https://example.com/x") == "<html>ok</html>"
        assert mock_get.call_count == 1

    @patch("tools.lotto.requests.get")
    def test_direct_exception_falls_back_to_proxy(self, mock_get):
        mock_get.side_effect = [
            Exception("DNS failure"),
            MagicMock(status_code=200, text="proxied"),
        ]
        assert _http_get_text("https://news.sanook.com/lotto/check/01062569/") == "proxied"
        assert mock_get.call_count == 2
        assert "codetabs.com" in mock_get.call_args_list[1][0][0]

    @patch("tools.lotto.requests.get")
    def test_direct_non_200_falls_back_to_proxy(self, mock_get):
        mock_get.side_effect = [
            MagicMock(status_code=403, text="blocked"),
            MagicMock(status_code=200, text="proxied"),
        ]
        assert _http_get_text("https://example.com/x") == "proxied"
        assert mock_get.call_count == 2

    @patch("tools.lotto.requests.get")
    def test_both_fail_returns_none(self, mock_get):
        mock_get.side_effect = Exception("offline")
        assert _http_get_text("https://example.com/x") is None

    @patch("tools.lotto.requests.get")
    def test_proxy_fail_returns_direct_body(self, mock_get):
        # direct ตอบ non-200 แต่มี body + proxy พัง → คืน body ของ direct
        mock_get.side_effect = [
            MagicMock(status_code=500, text="direct-body"),
            Exception("proxy down"),
        ]
        assert _http_get_text("https://example.com/x") == "direct-body"


# ---------- fetch (mocked HTTP/RSS) ----------
class TestFetch:
    @patch("tools.lotto._http_get_text")
    def test_fetch_latest_uses_rss_then_html(self, mock_http, tool):
        mock_http.side_effect = [SAMPLE_RSS, SAMPLE_HTML]
        data = tool._fetch_lotto()
        assert data is not None
        assert data["date"] == "1 มิถุนายน 2569"
        # call แรกคือ RSS, call สองคือหน้า check ของงวดล่าสุดจาก RSS
        assert "rssfeeds.sanook.com" in mock_http.call_args_list[0][0][0]
        assert "/lotto/check/01062569/" in mock_http.call_args_list[1][0][0]

    @patch("tools.lotto._http_get_text")
    def test_fetch_explicit_date_matches(self, mock_http, tool):
        mock_http.return_value = SAMPLE_HTML
        data = tool._fetch_lotto("01062569")
        assert data is not None
        assert data["endpoint"].endswith("/01062569/")

    @patch("tools.lotto._http_get_text")
    def test_fetch_date_mismatch_returns_none(self, mock_http, tool):
        # Sanook ไม่ 404 — ขอ 16062569 แต่ได้หน้างวด 1 มิ.ย. → ต้องถือว่าไม่มีงวดนั้น
        mock_http.return_value = SAMPLE_HTML
        assert tool._fetch_lotto("16062569") is None

    @patch("tools.lotto._http_get_text")
    def test_fetch_no_article_body_returns_none(self, mock_http, tool):
        mock_http.return_value = "<html>no json-ld here</html>"
        assert tool._fetch_lotto("01062569") is None

    @patch("tools.lotto._http_get_text")
    def test_fetch_http_down_returns_none(self, mock_http, tool):
        mock_http.return_value = None
        assert tool._fetch_lotto("01062569") is None

    @patch("tools.lotto._http_get_text")
    def test_fetch_rss_items(self, mock_http, tool):
        mock_http.return_value = SAMPLE_RSS
        items = tool._fetch_rss_items()
        assert [i["id"] for i in items] == ["01062569", "16052569", "02052569"]
        assert items[0]["date"] == "1 มิถุนายน 2569"

    @patch("tools.lotto._http_get_text")
    def test_fetch_draw_list_page_2_is_empty(self, mock_http, tool):
        # RSS มีหน้าเดียว — page > 1 ต้องคืน [] โดยไม่ยิง HTTP
        assert tool._fetch_draw_list(page=2) == []
        mock_http.assert_not_called()


# ---------- execute() integration ----------
class TestExecute:
    @patch("tools.lotto.db")
    @patch("tools.lotto._http_get_text")
    def test_summary_latest(self, mock_http, mock_db, tool):
        mock_http.side_effect = [SAMPLE_RSS, SAMPLE_HTML]
        mock_db.make_log_field.return_value = {}
        out = asyncio.run(tool.execute(user_id="u1", args=""))
        assert "ผลสลากกินแบ่งรัฐบาล" in out
        assert "123456" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._http_get_text")
    def test_check_winning_number(self, mock_http, mock_db, tool):
        mock_http.side_effect = [SAMPLE_RSS, SAMPLE_HTML]
        mock_db.make_log_field.return_value = {}
        out = asyncio.run(tool.execute(user_id="u1", args="check 123456"))
        assert "ถูก" in out and "123456" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._http_get_text")
    def test_check_invalid_number(self, mock_http, mock_db, tool):
        mock_db.make_log_field.return_value = {}
        out = asyncio.run(tool.execute(user_id="u1", args="check abc"))
        assert "กรุณาใส่เลข" in out
        mock_http.assert_not_called()

    @patch("tools.lotto.db")
    @patch("tools.lotto._http_get_text")
    def test_api_down_no_date_returns_fallback(self, mock_http, mock_db, tool):
        mock_http.return_value = None
        mock_db.make_log_field.return_value = {}
        out = asyncio.run(tool.execute(user_id="u1", args=""))
        assert "ไม่สามารถดึงข้อมูล" in out
        assert "glo.or.th" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._http_get_text")
    def test_unknown_date_shows_nearby(self, mock_http, mock_db, tool):
        # ขอ 16062569 → Sanook serve งวด 1 มิ.ย. แทน (mismatch → not found)
        # จากนั้น _find_nearby_draws ดึง RSS หางวดใกล้เคียง
        mock_http.side_effect = [SAMPLE_HTML, SAMPLE_RSS]
        mock_db.make_log_field.return_value = {}
        out = asyncio.run(tool.execute(user_id="u1", args="16062569"))
        assert "ไม่มีผลสลาก" in out
        assert "01062569" in out  # งวดเดือนเดียวกันจาก RSS

    @patch("tools.lotto.db")
    @patch("tools.lotto._http_get_text")
    def test_list_mode(self, mock_http, mock_db, tool):
        mock_http.return_value = SAMPLE_RSS
        mock_db.make_log_field.return_value = {}
        out = asyncio.run(tool.execute(user_id="u1", args="list"))
        assert "1 มิถุนายน 2569" in out
        assert "/lotto 01062569" in out
