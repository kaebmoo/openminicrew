"""Claude Provider — Anthropic Claude API"""

import asyncio
from typing import Any

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.providers.base import BaseLLMProvider
from core.config import (
    ANTHROPIC_API_KEY, OWNER_TELEGRAM_CHAT_ID,
    CLAUDE_MODEL_CHEAP, CLAUDE_MODEL_MID,
)
from core.logger import get_logger

log = get_logger(__name__)

_RETRYABLE = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    ConnectionError,
    TimeoutError,
)


class ClaudeProvider(BaseLLMProvider):
    name = "claude"

    def __init__(self):
        self._client: anthropic.AsyncAnthropic | None = None
        self._client_loop_id: int | None = None  # track event loop ที่สร้าง client
        self._user_clients: dict[str, anthropic.AsyncAnthropic] = {}
        self._user_clients_loop_id: int | None = None

    def _get_client(self, api_key: str) -> anthropic.AsyncAnthropic:
        """Get or create AsyncAnthropic client — recreate ถ้า event loop เปลี่ยน"""
        loop_id = id(asyncio.get_running_loop())

        if api_key == ANTHROPIC_API_KEY:
            # shared client
            if self._client is not None and self._client_loop_id == loop_id:
                return self._client
            if self._client is not None:
                log.info("Claude shared client: event loop changed, recreating")
            self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=60.0)
            self._client_loop_id = loop_id
            return self._client
        else:
            # per-user client — ถ้า loop เปลี่ยน ต้อง clear cache ทั้งหมด
            if self._user_clients_loop_id != loop_id:
                if self._user_clients:
                    log.info("Claude user clients: event loop changed, clearing cache")
                self._user_clients.clear()
                self._user_clients_loop_id = loop_id

            if api_key not in self._user_clients:
                self._user_clients[api_key] = anthropic.AsyncAnthropic(
                    api_key=api_key, timeout=60.0,
                )
            return self._user_clients[api_key]

    def is_configured(self) -> bool:
        return bool(ANTHROPIC_API_KEY)

    def _has_personal_key(self, user_id: str) -> bool:
        """ตรวจว่า user มี per-user key ของตัวเอง (ไม่ fallback ไป shared key)"""
        from core.db import get_user_api_key
        return bool(get_user_api_key(str(user_id), "anthropic"))

    def is_available_for_user(self, user_id: str) -> bool:
        """Claude ใช้ shared key ได้เฉพาะ owner — user ทั่วไปต้อง /setkey anthropic <key>"""
        # owner ใช้ shared key ได้
        if str(user_id) == str(OWNER_TELEGRAM_CHAT_ID) and self.is_configured():
            return True
        # user ทั่วไปต้องมี key ส่วนตัว
        return self._has_personal_key(user_id)

    def _get_api_key(self, user_id: str = None) -> str:
        """Resolve API key: user key > shared key (owner only)"""
        if user_id:
            from core.api_keys import get_api_key
            user_key = get_api_key(user_id, "anthropic")
            if user_key:
                return user_key
        # fallback shared key — ถ้าถึงตรงนี้แปลว่าเป็น owner
        return ANTHROPIC_API_KEY

    def get_model(self, tier: str = "cheap") -> str:
        return CLAUDE_MODEL_MID if tier == "mid" else CLAUDE_MODEL_CHEAP

    def convert_tool_spec(self, spec: dict) -> dict:
        """Convert generic tool spec → Anthropic tool_use format"""
        return {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec.get("parameters", {"type": "object", "properties": {}}),
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
        model = self.get_model(tier)

        # Resolve API key: per-user key > shared key
        api_key = self._get_api_key(user_id)
        if not api_key:
            raise ValueError("ยังไม่มี API key สำหรับ Claude — ใช้ /setkey anthropic <key>")

        # Get/create client — จัดการ event loop change อัตโนมัติ
        client = self._get_client(api_key)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": 2000,
            "messages": messages,
        }
        if system:
            # Prompt caching: system prompt as content blocks with cache_control
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            converted = [self.convert_tool_spec(t) for t in tools]
            # Prompt caching: mark last tool with cache_control as breakpoint
            if converted:
                converted[-1]["cache_control"] = {"type": "ephemeral"}
            kwargs["tools"] = converted

        resp = await client.messages.create(**kwargs)

        content = ""
        tool_call = None

        for block in resp.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_call = {"name": block.name, "args": block.input}

        token_used = (resp.usage.input_tokens + resp.usage.output_tokens) if resp.usage else 0

        # Log prompt caching metrics
        if resp.usage:
            cache_created = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
            if cache_created or cache_read:
                log.info(
                    f"Claude cache — created: {cache_created}, "
                    f"read: {cache_read}, input: {resp.usage.input_tokens}"
                )

        return {
            "content": content,
            "tool_call": tool_call,
            "model": model,
            "token_used": token_used,
        }
