import sys
import types
import asyncio
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "/Users/seal/Documents/GitHub/openminicrew")

fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from tools.response import MediaResponse


@patch("interfaces.telegram_common.send_tool_response")
@patch("dispatcher.save_assistant_message")
@patch("dispatcher.save_user_message")
@patch("dispatcher.ensure_conversation", return_value="conv1")
@patch("dispatcher.db.get_conversation_title", return_value=None)
@patch("dispatcher.db.update_conversation")
@patch("dispatcher.user_rate_limiter.allow", return_value=True)
@patch("dispatcher.request_dedup.is_duplicate", return_value=False)
@patch("dispatcher.dispatch", new_callable=AsyncMock)
def test_process_message_sends_media_response(
    mock_dispatch,
    _mock_is_duplicate,
    _mock_allow,
    _mock_update_conversation,
    _mock_get_title,
    _mock_ensure_conversation,
    _mock_save_user_message,
    mock_save_assistant_message,
    mock_send_tool_response,
):
    from dispatcher import process_message

    media = MediaResponse(text="ภาพพยากรณ์", image=b"png-bytes", image_caption="forecast")
    mock_dispatch.return_value = (media, "weather", None, 0)

    fake_scheduler = types.SimpleNamespace(flush_pending=lambda chat_id: None)
    with patch.dict(sys.modules, {"scheduler": fake_scheduler}):
        asyncio.run(process_message("u1", {"user_id": "u1"}, 123, "weather"))

    mock_send_tool_response.assert_called_once_with(123, media)
    mock_save_assistant_message.assert_called_once()
    assert mock_save_assistant_message.call_args[0][1] == "ภาพพยากรณ์"


def test_matcha_provider_parses_tool_call():
    import httpx
    from core.providers.matcha_provider import MatchaProvider

    provider = MatchaProvider()
    fake_json = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "weather",
                                "arguments": '{"args":"bangkok"}',
                            }
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    fake_response = httpx.Response(
        status_code=200,
        json=fake_json,
        request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
    )

    async def fake_post(self, url, **kwargs):
        return fake_response

    async def run_test():
        with patch.object(httpx.AsyncClient, "post", fake_post), \
             patch("core.providers.matcha_provider.MATCHA_API_KEY", "key"), \
             patch("core.providers.matcha_provider.MATCHA_BASE_URL", "https://example.com/v1"), \
             patch("core.providers.matcha_provider.MATCHA_MODEL_CHEAP", "matcha-cheap"), \
             patch("core.providers.matcha_provider.MATCHA_MODEL_MID", "matcha-mid"):
            result = await provider.chat(messages=[{"role": "user", "content": "hi"}])
            assert result["tool_call"] == {"name": "weather", "args": {"args": "bangkok"}}
            assert result["token_used"] == 15

    asyncio.run(run_test())