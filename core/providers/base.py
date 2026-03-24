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
        user_id: str = None,
    ) -> dict:
        """
        Send messages to LLM and return response.

        Args:
            user_id: สำหรับ resolve per-user API key (optional)

        Returns:
            {
                "content": str,
                "tool_call": dict | None,  # {"name": ..., "args": ...}
                "model": str,
                "token_used": int,
            }
        """
        ...

    def is_available_for_user(self, user_id: str) -> bool:
        """ตรวจว่า user นี้ใช้ provider นี้ได้ไหม (override ได้สำหรับ per-user key)"""
        return self.is_configured()

    @abstractmethod
    def convert_tool_spec(self, spec: dict) -> Any:
        """Convert generic tool spec → provider-specific format"""
        ...
