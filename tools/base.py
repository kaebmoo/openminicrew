"""BaseTool — abstract class ที่ทุก tool ต้อง inherit"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tools.response import MediaResponse


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    commands: list[str] = []
    direct_output: bool = True  # True = ส่งผลลัพธ์ตรงๆ ไม่ต้องผ่าน LLM สรุปซ้ำ
    preferred_tier: str = "cheap"  # cheap = Haiku/Flash, mid = Sonnet/Pro

    @abstractmethod
    async def execute(self, user_id: str, args: str = "", **kwargs) -> str | MediaResponse:
        """ทำงานหลัก — รับ user_id เสมอ, return ข้อความหรือ MediaResponse"""
        ...

    def get_tool_spec(self) -> dict:
        """
        Return generic tool spec — LLM Router จะแปลง format ให้ตรง provider

        Override ถ้า tool มี parameters
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
