"""BaseTool — abstract class ที่ทุก tool ต้อง inherit"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.logger import get_logger
from core.prompt_loader import load_metadata, load_prompt
from tools.response import MediaResponse

log = get_logger(__name__)


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
        """Default get_tool_spec() — โหลด description จาก prompts/tools/<name>.md

        ถ้าไฟล์ markdown ไม่มี → fallback ไป self.description (backward compat ระหว่าง migration)

        Override ถ้า tool มี parameters มากกว่า args เดียว
        """
        prompt_path = f"tools/{self.name}.md"
        metadata: dict = {}
        try:
            description = load_prompt(prompt_path).strip()
            metadata = load_metadata(prompt_path)
            args_desc = metadata.get("parameters_args", "")
        except FileNotFoundError:
            description = self.description
            args_desc = ""

        properties: dict = {}
        required: list[str] = []
        if args_desc:
            properties["args"] = {
                "type": "string",
                "description": args_desc.strip(),
            }
            # default: args required. Opt-out ด้วย frontmatter args_required: false
            args_required = metadata.get("args_required", "true").lower()
            if args_required not in ("false", "0", "no"):
                required.append("args")

        return {
            "name": self.name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
