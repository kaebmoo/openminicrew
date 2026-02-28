"""Gemini Provider — Google Gemini API"""

from typing import Any

from google import genai
from google.genai import types as genai_types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.providers.base import BaseLLMProvider
from core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL_CHEAP, GEMINI_MODEL_MID,
)
from core.logger import get_logger

log = get_logger(__name__)


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self):
        self._client = None
        if GEMINI_API_KEY:
            self._client = genai.Client(api_key=GEMINI_API_KEY)

    def is_configured(self) -> bool:
        return self._client is not None

    def get_model(self, tier: str = "cheap") -> str:
        return GEMINI_MODEL_MID if tier == "mid" else GEMINI_MODEL_CHEAP

    def convert_tool_spec(self, spec: dict) -> genai_types.Tool:
        """Convert generic tool spec → Gemini function_declarations format"""
        func_decl = genai_types.FunctionDeclaration(
            name=spec["name"],
            description=spec["description"],
            parameters=spec.get("parameters"),
        )
        return genai_types.Tool(function_declarations=[func_decl])

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
    ) -> dict:
        model = self.get_model(tier)

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
            config_kwargs["tools"] = [self.convert_tool_spec(t) for t in tools]

        config = genai_types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        resp = self._client.models.generate_content(
            model=model,
            contents=gemini_contents,
            config=config,
        )

        # Parse response
        content = ""
        tool_call = None

        if resp.candidates and resp.candidates[0].content:
            for part in resp.candidates[0].content.parts:
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
                getattr(resp.usage_metadata, "prompt_token_count", 0) +
                getattr(resp.usage_metadata, "candidates_token_count", 0)
            )

        return {
            "content": content,
            "tool_call": tool_call,
            "model": model,
            "token_used": token_used,
        }
