"""BaseTool — abstract class ที่ทุก tool ต้อง inherit"""

from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    commands: list[str] = []

    @abstractmethod
    async def execute(self, user_id: str, args: str = "") -> str:
        """ทำงานหลัก — รับ user_id เสมอ, return ผลลัพธ์เป็น string"""
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
