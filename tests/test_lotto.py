"""Unit tests for tools/lotto.py — uses mocked API responses."""
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

from tools.lotto import LottoTool, _lotto_get


# ---------- sample API payloads ----------
SAMPLE_LATEST = {
    "status": "success",
    "response": {
        "date": "1 พฤศจิกายน 2567",
        "endpoint": "https://www.glo.or.th/",
        "prizes": [
            {"id": "prizeFirst", "reward": "6000000", "amount": 1, "number": ["123456"]},
            {"id": "prizeFirstNear", "reward": "100000", "amount": 2, "number": ["123455", "123457"]},
            {"id": "prizeSecond", "reward": "200000", "amount": 5,
             "number": ["111111", "222222", "333333", "444444", "555555"]},
            {"id": "prizeThird", "reward": "80000", "amount": 10,
             "number": [f"{i:06d}" for i in range(10)]},
            {"id": "prizeForth", "reward": "40000", "amount": 50,
             "number": [f"{i:06d}" for i in range(50)]},
            {"id": "prizeFifth", "reward": "20000", "amount": 100,
             "number": [f"{i:06d}" for i in range(100)]},
        ],
        "runningNumbers": [
            {"id": "runningNumberFrontThree", "reward": "4000",
             "amount": 2, "number": ["123", "789"]},
            {"id": "runningNumberBackThree", "reward": "4000",
             "amount": 2, "number": ["456", "999"]},
            {"id": "runningNumberBackTwo", "reward": "2000",
             "amount": 1, "number": ["56"]},
        ],
    },
}

SAMPLE_LIST = {
    "status": "success",
    "response": [
        {"id": "01112567", "date": "1 พฤศจิกายน 2567"},
        {"id": "16102567", "date": "16 ตุลาคม 2567"},
        {"id": "01102567", "date": "1 ตุลาคม 2567"},
    ],
}

EMPTY_RESPONSE = {"status": "success", "response": {"date": "", "prizes": []}}


def _mock_resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


@pytest.fixture
def tool():
    return LottoTool()


# ---------- _parse_args ----------
class TestParseArgs:
    def test_empty_summary(self, tool):
        assert tool._parse_args("")["mode"] == "summary"

    def test_six_digit_positional_is_month(self, tool):
        # NOTE: docstring claims "820866" → mode=check, but 6-digit positional
        # is actually treated as MMYYYY (month) by the implementation.
        # Use `check <num>` for unambiguous 6-digit checking.
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
        out = tool._format_summary(SAMPLE_LATEST["response"])
        assert "123456" in out
        assert "6,000,000" in out
        assert "รางวัลที่ 1" in out

    def test_check_first_prize_win(self, tool):
        out = tool._format_check_result("123456", SAMPLE_LATEST["response"])
        assert "ถูก" in out and "รางวัลที่ 1" in out

    def test_check_back_two(self, tool):
        out = tool._format_check_result("56", SAMPLE_LATEST["response"])
        assert "ถูก" in out

    def test_check_no_win(self, tool):
        # 987654: front3=987, back3=654, back2=54 — none in sample running numbers
        out = tool._format_check_result("987654", SAMPLE_LATEST["response"])
        assert "ไม่ถูกรางวัล" in out

    def test_six_digit_back_two_match(self, tool):
        # 999956 ends in 56 → wins back two
        out = tool._format_check_result("999956", SAMPLE_LATEST["response"])
        assert "เลขท้าย 2 ตัว" in out


# ---------- API fetch ----------
class TestFetch:
    @patch("tools.lotto._lotto_get")
    def test_fetch_latest_success(self, mock_get, tool):
        mock_get.return_value = _mock_resp(SAMPLE_LATEST)
        data = tool._fetch_lotto()
        assert data["date"] == "1 พฤศจิกายน 2567"
        mock_get.assert_called_once()
        assert mock_get.call_args[0][0].endswith("/latest")

    @patch("tools.lotto._lotto_get")
    def test_fetch_with_date_id(self, mock_get, tool):
        mock_get.return_value = _mock_resp(SAMPLE_LATEST)
        tool._fetch_lotto("01112567")
        assert "/lotto/01112567" in mock_get.call_args[0][0]

    @patch("tools.lotto._lotto_get")
    def test_fetch_empty_returns_none(self, mock_get, tool):
        mock_get.return_value = _mock_resp(EMPTY_RESPONSE)
        assert tool._fetch_lotto("99999999") is None

    @patch("tools.lotto._lotto_get")
    def test_fetch_exception_returns_none(self, mock_get, tool):
        mock_get.side_effect = RuntimeError("boom")
        assert tool._fetch_lotto() is None

    @patch("tools.lotto._lotto_get")
    def test_fetch_draw_list(self, mock_get, tool):
        mock_get.return_value = _mock_resp(SAMPLE_LIST)
        draws = tool._fetch_draw_list(page=1)
        assert len(draws) == 3
        assert "/list/1" in mock_get.call_args[0][0]


# ---------- _lotto_get fallback path ----------
class TestLottoGetFallback:
    @patch("tools.lotto.requests.get")
    def test_direct_success(self, mock_get):
        mock_get.return_value = _mock_resp({"ok": 1})
        resp = _lotto_get("https://example.com/x")
        assert resp.status_code == 200
        assert mock_get.call_count == 1

    @patch("tools.lotto.requests.get")
    def test_falls_back_to_proxy(self, mock_get):
        # First call (direct) raises, second (proxy) succeeds
        mock_get.side_effect = [
            Exception("DNS failure"),
            _mock_resp({"ok": 1}),
        ]
        resp = _lotto_get("https://lotto.api.rayriffy.com/latest")
        assert resp.status_code == 200
        assert mock_get.call_count == 2
        # second call hits codetabs proxy
        assert "codetabs.com" in mock_get.call_args_list[1][0][0]

    @patch("tools.lotto.requests.get")
    def test_both_fail_returns_500(self, mock_get):
        mock_get.side_effect = Exception("offline")
        resp = _lotto_get("https://lotto.api.rayriffy.com/latest")
        assert resp.status_code == 500


# ---------- execute() integration ----------
@pytest.mark.asyncio
class TestExecute:
    @patch("tools.lotto.db")
    @patch("tools.lotto._lotto_get")
    async def test_summary_latest(self, mock_get, mock_db, tool):
        mock_get.return_value = _mock_resp(SAMPLE_LATEST)
        mock_db.make_log_field.return_value = {}
        out = await tool.execute(user_id="u1", args="")
        assert "ผลสลากกินแบ่งรัฐบาล" in out
        assert "123456" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._lotto_get")
    async def test_check_winning_number(self, mock_get, mock_db, tool):
        mock_get.return_value = _mock_resp(SAMPLE_LATEST)
        mock_db.make_log_field.return_value = {}
        out = await tool.execute(user_id="u1", args="check 123456")
        assert "ถูก" in out and "123456" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._lotto_get")
    async def test_check_invalid_number(self, mock_get, mock_db, tool):
        mock_db.make_log_field.return_value = {}
        out = await tool.execute(user_id="u1", args="check abc")
        assert "กรุณาใส่เลข" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._lotto_get")
    async def test_api_down_no_date_returns_fallback(self, mock_get, mock_db, tool):
        mock_get.side_effect = Exception("network down")
        mock_db.make_log_field.return_value = {}
        out = await tool.execute(user_id="u1", args="")
        assert "ไม่สามารถดึงข้อมูล" in out
        assert "glo.or.th" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._lotto_get")
    async def test_unknown_date_shows_nearby(self, mock_get, mock_db, tool):
        # First call: lotto/<date> returns empty; second: list for nearby
        mock_get.side_effect = [
            _mock_resp(EMPTY_RESPONSE),
            _mock_resp(SAMPLE_LIST),
        ]
        mock_db.make_log_field.return_value = {}
        out = await tool.execute(user_id="u1", args="01112599")
        assert "ไม่มีผลสลาก" in out

    @patch("tools.lotto.db")
    @patch("tools.lotto._lotto_get")
    async def test_list_mode(self, mock_get, mock_db, tool):
        mock_get.return_value = _mock_resp(SAMPLE_LIST)
        mock_db.make_log_field.return_value = {}
        out = await tool.execute(user_id="u1", args="list")
        assert "1 พฤศจิกายน 2567" in out
        assert "/lotto 01112567" in out
