"""BaseLLMProvider — abstract class ที่ทุก LLM provider ต้อง inherit"""

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMProvider(ABC):
    name: str = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """ตรวจว่ามี API key / พร้อมใช้งานหรือไม่"""
        ...

    @abstractmethod
    def get_model(self, tier: str = "cheap") -> str:
        """Return model name ตาม tier (cheap/mid)"""
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tier: str = "cheap",
        system: str = "",
        tools: list[dict] | None = None,
    ) -> dict:
        """
        Send messages to LLM and return response.

        Returns:
            {
                "content": str,
                "tool_call": dict | None,  # {"name": ..., "args": ...}
                "model": str,
                "token_used": int,
            }
        """
        ...

    @abstractmethod
    def convert_tool_spec(self, spec: dict) -> Any:
        """Convert generic tool spec → provider-specific format"""
        ...
