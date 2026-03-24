"""Matcha Provider — OpenAI-compatible chat completions API.

รองรับทั้ง shared key จาก .env และ per-user key จาก /setkey matcha <key>
ใช้ httpx (async native) + SSL verify configurable สำหรับ internal gateway
"""

import json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.providers.base import BaseLLMProvider
from core.config import (
    MATCHA_API_KEY,
    MATCHA_BASE_URL,
    MATCHA_MODEL_CHEAP,
    MATCHA_MODEL_MID,
    MATCHA_SSL_VERIFY,
    MATCHA_TIMEOUT,
)
from core.logger import get_logger

log = get_logger(__name__)

# defaults เมื่อ .env ไม่ได้ตั้งค่า
_DEFAULT_API_URL = "https://api.opentyphoon.ai/v1/chat/completions"
_DEFAULT_MODEL = "gpt-4o"

_RETRYABLE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
)


def _resolve_api_url(base_url: str) -> str:
    """
    Resolve the full chat completions URL.

    รองรับทั้ง 2 แบบ:
    - MATCHA_API_URL = https://gateway.example.com/v1/chat/completions  (full URL)
    - MATCHA_BASE_URL = https://gateway.example.com/v1                 (base URL)
    """
    if not base_url:
        return _DEFAULT_API_URL

    # ถ้า URL ลงท้ายด้วย /chat/completions แล้ว → ใช้ตรงๆ
    if base_url.rstrip("/").endswith("/chat/completions"):
        return base_url.rstrip("/")

    # ไม่งั้น → ต่อ path
    return f"{base_url.rstrip('/')}/chat/completions"


class MatchaProvider(BaseLLMProvider):
    name = "matcha"

    def is_configured(self) -> bool:
        """ตรวจว่ามี shared key จาก .env หรือไม่"""
        return bool(MATCHA_API_KEY)

    def is_available_for_user(self, user_id: str) -> bool:
        """ตรวจว่า user นี้ใช้ matcha ได้ไหม (shared key หรือ per-user key)"""
        if self.is_configured():
            return True
        from core.api_keys import get_api_key
        return bool(get_api_key(user_id, "matcha"))

    def _get_api_key(self, user_id: str = None) -> str:
        """Resolve API key: user key > shared key"""
        if user_id:
            from core.api_keys import get_api_key
            user_key = get_api_key(user_id, "matcha")
            if user_key:
                return user_key
        return MATCHA_API_KEY

    def get_model(self, tier: str = "cheap") -> str:
        if tier == "mid":
            return MATCHA_MODEL_MID or _DEFAULT_MODEL
        return MATCHA_MODEL_CHEAP or _DEFAULT_MODEL

    def convert_tool_spec(self, spec: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec.get("parameters", {"type": "object", "properties": {}}),
            },
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict],
        tier: str = "cheap",
        system: str = "",
        tools: list[dict] | None = None,
        user_id: str = None,
    ) -> dict:
        api_key = self._get_api_key(user_id)
        if not api_key:
            raise ValueError("ยังไม่มี API key สำหรับ Matcha — ใช้ /setkey matcha <key>")

        api_url = _resolve_api_url(MATCHA_BASE_URL)
        model = self.get_model(tier)

        payload_messages = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = [self.convert_tool_spec(t) for t in tools]
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        log.info(f"Matcha request: url={api_url}, model={model}, ssl_verify={MATCHA_SSL_VERIFY}")

        try:
            async with httpx.AsyncClient(
                verify=MATCHA_SSL_VERIFY,
                timeout=MATCHA_TIMEOUT,
            ) as client:
                response = await client.post(api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as e:
            # Log ข้อมูลเต็มเพื่อ debug
            body = e.response.text[:500] if e.response else "N/A"
            log.error(
                f"Matcha API error: status={e.response.status_code}, "
                f"url={api_url}, model={model}, body={body}"
            )
            raise
        except httpx.HTTPError as e:
            log.error(f"Matcha connection error: {type(e).__name__}: {e}, url={api_url}")
            raise

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        tool_call = None

        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            first_call = tool_calls[0]
            function = first_call.get("function", {})
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"args": arguments}
            tool_call = {
                "name": function.get("name"),
                "args": arguments,
            }

        usage = data.get("usage", {})
        token_used = int(
            (usage.get("prompt_tokens") or 0)
            + (usage.get("completion_tokens") or 0)
        )

        return {
            "content": content,
            "tool_call": tool_call,
            "model": model,
            "token_used": token_used,
        }
