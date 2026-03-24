# tests/test_dispatch_retry.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_success_direct_output():
    """tool สำเร็จ + direct_output=True → return ทันที (1 LLM call)"""

    mock_tool = MagicMock()
    mock_tool.name = "lotto"
    mock_tool.direct_output = True
    mock_tool.execute = AsyncMock(return_value="🎰 ผลสลาก: 123456")

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool", return_value=mock_tool):

        mock_chat.return_value = {
            "content": "",
            "tool_call": {"name": "lotto", "args": {"args": ""}},
            "model": "claude-haiku",
            "token_used": 100,
        }

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="ผลหวยงวดล่าสุด",
            context=[{"role": "user", "content": "ผลหวยงวดล่าสุด"}],
            provider="claude",
            tool_specs=[],
        )

        response_text, tool_used, model, tokens = result

        assert response_text == "🎰 ผลสลาก: 123456"
        assert tool_used == "lotto"
        assert mock_chat.call_count == 1  # แค่ 1 call!
        assert tokens == 100


@pytest.mark.asyncio
async def test_success_with_summary():
    """tool สำเร็จ + direct_output=False → LLM สรุป (2 LLM calls)"""

    mock_tool = MagicMock()
    mock_tool.name = "some_tool"
    mock_tool.direct_output = False
    mock_tool.execute = AsyncMock(return_value="raw data...")

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool", return_value=mock_tool):

        mock_chat.side_effect = [
            # Call 1: LLM เรียก tool
            {
                "content": "",
                "tool_call": {"name": "some_tool", "args": {}},
                "model": "claude-haiku",
                "token_used": 100,
            },
            # Call 2: LLM สรุปผล
            {
                "content": "สรุปข้อมูล: ...",
                "tool_call": None,
                "model": "claude-haiku",
                "token_used": 80,
            },
        ]

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="ดูข้อมูล",
            context=[{"role": "user", "content": "ดูข้อมูล"}],
            provider="claude",
            tool_specs=[],
        )

        assert result[0] == "สรุปข้อมูล: ..."
        assert mock_chat.call_count == 2
        assert result[3] == 180  # 100 + 80


@pytest.mark.asyncio
async def test_unknown_tool_retry():
    """LLM เรียก tool ผิดชื่อ → retry → เลือกถูก → return ทันที"""

    mock_tool = MagicMock()
    mock_tool.name = "lotto"
    mock_tool.direct_output = True
    mock_tool.execute = AsyncMock(return_value="🎰 ผล...")

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool") as mock_get_tool, \
         patch("dispatcher.registry.get_all", return_value=[mock_tool]):

        mock_chat.side_effect = [
            # Attempt 1: tool ชื่อผิด
            {
                "content": "",
                "tool_call": {"name": "lottery", "args": {}},
                "model": "claude-haiku",
                "token_used": 100,
            },
            # Attempt 2: tool ชื่อถูก
            {
                "content": "",
                "tool_call": {"name": "lotto", "args": {"args": ""}},
                "model": "claude-haiku",
                "token_used": 100,
            },
        ]
        # ครั้งแรก: "lottery" → None, ครั้งที่สอง: "lotto" → tool
        mock_get_tool.side_effect = [None, mock_tool]

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="ตรวจหวย",
            context=[{"role": "user", "content": "ตรวจหวย"}],
            provider="claude",
            tool_specs=[],
        )

        assert result[0] == "🎰 ผล..."
        assert result[1] == "lotto"
        assert mock_chat.call_count == 2
        assert result[3] == 200


@pytest.mark.asyncio
async def test_tool_error_llm_responds():
    """tool execute error → LLM ตอบ user แทน"""

    mock_tool = MagicMock()
    mock_tool.name = "gmail_summary"
    mock_tool.direct_output = True
    mock_tool.execute = AsyncMock(side_effect=Exception("Gmail not authorized"))

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool", return_value=mock_tool), \
         patch("dispatcher.db.log_tool_usage"):

        mock_chat.side_effect = [
            # Attempt 1: เรียก tool
            {
                "content": "",
                "tool_call": {"name": "gmail_summary", "args": {}},
                "model": "claude-haiku",
                "token_used": 100,
            },
            # Attempt 2: LLM ตอบ user เอง
            {
                "content": "ยังไม่ได้ authorize Gmail กรุณาใช้ /authgmail ก่อน",
                "tool_call": None,
                "model": "claude-haiku",
                "token_used": 80,
            },
        ]

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="สรุปอีเมล",
            context=[{"role": "user", "content": "สรุปอีเมล"}],
            provider="claude",
            tool_specs=[],
        )

        assert "authgmail" in result[0] or "authorize" in result[0]
        assert mock_chat.call_count == 2
        assert result[3] == 180


@pytest.mark.asyncio
async def test_max_retries():
    """LLM เรียก tool ผิดทุกรอบ → หมด MAX_RETRIES → return None"""

    mock_tool = MagicMock()
    mock_tool.name = "lotto"

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool", return_value=None), \
         patch("dispatcher.registry.get_all", return_value=[mock_tool]):

        mock_chat.return_value = {
            "content": "",
            "tool_call": {"name": "nonexistent", "args": {}},
            "model": "claude-haiku",
            "token_used": 50,
        }

        from dispatcher import _dispatch_with_retry, MAX_RETRIES

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="อะไรก็ได้",
            context=[{"role": "user", "content": "อะไรก็ได้"}],
            provider="claude",
            tool_specs=[],
        )

        assert result[0] is None
        assert mock_chat.call_count == MAX_RETRIES
        assert result[3] == 50 * MAX_RETRIES


@pytest.mark.asyncio
async def test_text_only():
    """LLM ตอบ text ตรง → 1 call → จบ"""

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {
            "content": "สวัสดีครับ มีอะไรให้ช่วยไหม?",
            "tool_call": None,
            "model": "claude-haiku",
            "token_used": 50,
        }

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="สวัสดี",
            context=[{"role": "user", "content": "สวัสดี"}],
            provider="claude",
            tool_specs=[],
        )

        assert result[0] == "สวัสดีครับ มีอะไรให้ช่วยไหม?"
        assert result[1] is None
        assert mock_chat.call_count == 1
        assert result[3] == 50


@pytest.mark.asyncio
async def test_empty_response_retries_then_calls_tool():
    """LLM ตอบว่างรอบแรก → retry → เรียก tool สำเร็จ"""

    mock_tool = MagicMock()
    mock_tool.name = "news_summary"
    mock_tool.direct_output = True
    mock_tool.execute = AsyncMock(return_value="📰 ข่าววันนี้")

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool", return_value=mock_tool):

        mock_chat.side_effect = [
            {
                "content": "",
                "tool_call": None,
                "model": "claude-haiku",
                "token_used": 90,
            },
            {
                "content": "",
                "tool_call": {"name": "news_summary", "args": {}},
                "model": "claude-haiku",
                "token_used": 100,
            },
        ]

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="สรุปข่าวให้ด้วย",
            context=[{"role": "user", "content": "สรุปข่าวให้ด้วย"}],
            provider="claude",
            tool_specs=[],
        )

        assert result[0] == "📰 ข่าววันนี้"
        assert result[1] == "news_summary"
        assert mock_chat.call_count == 2
        assert result[3] == 190


@pytest.mark.asyncio
async def test_llm_api_error():
    """LLM API พัง → break ทันที → return None"""

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = Exception("API rate limit exceeded")

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="ผลหวย",
            context=[{"role": "user", "content": "ผลหวย"}],
            provider="claude",
            tool_specs=[],
        )

        assert result[0] is None
        assert mock_chat.call_count == 1  # ไม่ retry LLM error
        assert result[3] == 0


@pytest.mark.asyncio
async def test_summary_fail_returns_raw():
    """direct_output=False + summary LLM พัง → return ผล tool ดิบ"""

    mock_tool = MagicMock()
    mock_tool.name = "some_tool"
    mock_tool.direct_output = False
    mock_tool.execute = AsyncMock(return_value="raw data here")

    with patch("dispatcher.llm_router.chat", new_callable=AsyncMock) as mock_chat, \
         patch("dispatcher.registry.get_tool", return_value=mock_tool):

        mock_chat.side_effect = [
            # Call 1: LLM เรียก tool
            {
                "content": "",
                "tool_call": {"name": "some_tool", "args": {}},
                "model": "claude-haiku",
                "token_used": 100,
            },
            # Call 2: summary LLM พัง
            Exception("API error"),
        ]

        from dispatcher import _dispatch_with_retry

        result = await _dispatch_with_retry(
            user_id="test",
            user={"telegram_chat_id": "123"},
            text="ดูข้อมูล",
            context=[{"role": "user", "content": "ดูข้อมูล"}],
            provider="claude",
            tool_specs=[],
        )

        # ได้ผล tool ดิบแทน (ดีกว่าไม่ได้อะไรเลย)
        assert result[0] == "raw data here"
        assert result[1] == "some_tool"
