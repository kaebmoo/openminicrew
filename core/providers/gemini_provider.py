"""Gemini Provider — Google Gemini API"""

import asyncio
from typing import Any

from google import genai
from google.genai import types as genai_types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.providers.base import BaseLLMProvider
from core.config import (
    GEMINI_API_KEY, OWNER_TELEGRAM_CHAT_ID,
    GEMINI_MODEL_CHEAP, GEMINI_MODEL_MID,
)
from core.logger import get_logger

log = get_logger(__name__)

_GEMINI_HTTP_OPTS = {"timeout": 60000}  # 60s timeout (milliseconds)


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self):
        self._client: genai.Client | None = None
        self._client_loop_id: int | None = None
        self._user_clients: dict[str, genai.Client] = {}
        self._user_clients_loop_id: int | None = None

    def is_configured(self) -> bool:
        return bool(GEMINI_API_KEY)

    def _has_personal_key(self, user_id: str) -> bool:
        """ตรวจว่า user มี per-user key ของตัวเอง (ไม่ fallback ไป shared key)"""
        from core.db import get_user_api_key
        return bool(get_user_api_key(str(user_id), "gemini"))

    def is_available_for_user(self, user_id: str) -> bool:
        """Gemini: owner ใช้ shared key ได้, user ทั่วไปต้อง /setkey gemini <key>
        หมายเหตุ: fallback จากระบบยังใช้ shared key ได้ ผ่าน get_fallback() ที่ตรวจแค่ is_configured()
        """
        if str(user_id) == str(OWNER_TELEGRAM_CHAT_ID) and self.is_configured():
            return True
        return self._has_personal_key(user_id)

    def _get_api_key(self, user_id: str = None) -> str:
        """Resolve API key: user key > shared key"""
        if user_id:
            from core.api_keys import get_api_key
            user_key = get_api_key(user_id, "gemini")
            if user_key:
                return user_key
        return GEMINI_API_KEY

    async def _get_client(self, api_key: str) -> genai.Client:
        """Get or create genai.Client — recreate ถ้า event loop เปลี่ยน"""
        loop_id = id(asyncio.get_running_loop())

        if api_key == GEMINI_API_KEY:
            if self._client is not None and self._client_loop_id == loop_id:
                return self._client
            if self._client is not None:
                log.info("Gemini shared client: event loop changed, recreating")
                await self._close_client(self._client)
            self._client = genai.Client(api_key=api_key, http_options=_GEMINI_HTTP_OPTS)
            self._client_loop_id = loop_id
            return self._client
        else:
            if self._user_clients_loop_id != loop_id:
                if self._user_clients:
                    log.info("Gemini user clients: event loop changed, clearing cache")
                    for old_client in self._user_clients.values():
                        await self._close_client(old_client)
                self._user_clients.clear()
                self._user_clients_loop_id = loop_id

            if api_key not in self._user_clients:
                self._user_clients[api_key] = genai.Client(
                    api_key=api_key, http_options=_GEMINI_HTTP_OPTS,
                )
            return self._user_clients[api_key]

    @staticmethod
    async def _close_client(client: genai.Client):
        """ปิด client เก่าอย่างถูกต้องด้วย async — ป้องกัน __del__ สร้าง orphan task"""
        try:
            await client.aclose()
        except Exception:
            pass

    def get_model(self, tier: str = "cheap") -> str:
        return GEMINI_MODEL_MID if tier == "mid" else GEMINI_MODEL_CHEAP

    def convert_tool_spec(self, spec: dict) -> genai_types.FunctionDeclaration:
        """Convert generic tool spec → Gemini function_declarations format"""
        return genai_types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters=spec.get("parameters"),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
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
            raise ValueError("ยังไม่มี API key สำหรับ Gemini — ใช้ /setkey gemini <key>")

        # Get/create client — จัดการ event loop change อัตโนมัติ
        client = await self._get_client(api_key)

        # Convert messages to Gemini format
        gemini_contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            gemini_contents.append(
                genai_types.Content(
                    role=role,
                    parts=[genai_types.Part.from_text(text=msg["content"])]
                )
            )

        # Build config
        config_kwargs = {}
        if system:
            config_kwargs["system_instruction"] = system
        if tools:
            # Wrap all declarations in a single Tool
            config_kwargs["tools"] = [
                genai_types.Tool(function_declarations=[self.convert_tool_spec(t) for t in tools])
            ]

        config = genai_types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        resp = await client.aio.models.generate_content(
            model=model,
            contents=gemini_contents,
            config=config,
        )

        # Parse response
        content = ""
        tool_call = None

        if not resp.candidates:
            log.warning("Gemini returned no candidates (possibly blocked by safety filter)")
        elif resp.candidates[0].finish_reason and str(resp.candidates[0].finish_reason) not in ("STOP", "FinishReason.STOP", "1"):
            log.warning(f"Gemini finish_reason: {resp.candidates[0].finish_reason}")

        if resp.candidates and resp.candidates[0].content:
            for part in (resp.candidates[0].content.parts or []):
                if part.text:
                    content += part.text
                elif part.function_call:
                    tool_call = {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args) if part.function_call.args else {},
                    }

        token_used = 0
        if resp.usage_metadata:
            token_used = (
                (getattr(resp.usage_metadata, "prompt_token_count", 0) or 0) +
                (getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
            )
            # Log implicit caching metrics
            cached_tokens = getattr(resp.usage_metadata, "cached_content_token_count", 0) or 0
            if cached_tokens:
                log.info(
                    f"Gemini cache — cached: {cached_tokens}, "
                    f"prompt: {getattr(resp.usage_metadata, 'prompt_token_count', 0)}"
                )

        return {
            "content": content,
            "tool_call": tool_call,
            "model": model,
            "token_used": token_used,
        }
