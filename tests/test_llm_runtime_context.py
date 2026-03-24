import asyncio
from unittest.mock import AsyncMock, patch

from core.llm import llm_router


def test_llm_router_injects_current_runtime_context_into_system_prompt():
    fake_provider = AsyncMock()
    fake_provider.name = "fake"
    fake_provider.chat.return_value = {
        "content": "ok",
        "tool_call": None,
        "model": "fake-model",
        "token_used": 1,
    }

    with patch("core.llm.provider_registry.get_fallback", return_value=fake_provider):
        asyncio.run(
            llm_router.chat(
                messages=[{"role": "user", "content": "ราคาน้ำมันวันนี้"}],
                provider="claude",
                tier="cheap",
                system="ทดสอบ system prompt",
            )
        )

    _messages, _tier, system_prompt, _tools = fake_provider.chat.await_args.args
    assert "วันและเวลาปัจจุบันคือ" in system_prompt
    assert "พ.ศ." in system_prompt
    assert "ทดสอบ system prompt" in system_prompt