"""Claude Provider — Anthropic Claude API"""

from typing import Any

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.providers.base import BaseLLMProvider
from core.config import (
    ANTHROPIC_API_KEY,
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
        self._client = None
        if ANTHROPIC_API_KEY:
            self._client = anthropic.AsyncAnthropic(
                api_key=ANTHROPIC_API_KEY,
                timeout=60.0,  # 60s timeout — ป้องกัน polling thread ค้าง
            )

    def is_configured(self) -> bool:
        return self._client is not None

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
    ) -> dict:
        model = self.get_model(tier)

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

        resp = await self._client.messages.create(**kwargs)

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
