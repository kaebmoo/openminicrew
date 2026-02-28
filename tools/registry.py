"""Tool Registry — auto-discover tools จาก tools/ directory"""

import importlib
import inspect
import pkgutil
from pathlib import Path

from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, BaseTool] = {}
        self.command_map: dict[str, BaseTool] = {}

    def discover(self):
        """Scan tools/ directory หา class ที่ inherit BaseTool แล้ว register"""
        tools_dir = Path(__file__).parent

        for finder, module_name, _ in pkgutil.iter_modules([str(tools_dir)]):
            if module_name in ("base", "registry", "__init__"):
                continue

            try:
                module = importlib.import_module(f"tools.{module_name}")

                for attr_name, attr in inspect.getmembers(module, inspect.isclass):
                    if issubclass(attr, BaseTool) and attr is not BaseTool:
                        instance = attr()
                        self._register(instance)

            except Exception as e:
                log.error(f"Failed to load tool module '{module_name}': {e}")

        log.info(f"Discovered {len(self.tools)} tools: {list(self.tools.keys())}")

    def _register(self, tool: BaseTool):
        if not tool.name:
            log.warning(f"Skipping tool with empty name: {type(tool)}")
            return

        self.tools[tool.name] = tool
        for cmd in tool.commands:
            self.command_map[cmd] = tool

        log.info(f"Registered tool: {tool.name} (commands: {tool.commands})")

    def get_tool(self, name: str) -> BaseTool | None:
        return self.tools.get(name)

    def get_by_command(self, command: str) -> BaseTool | None:
        return self.command_map.get(command)

    def get_all(self) -> list[BaseTool]:
        return list(self.tools.values())

    def get_all_specs(self) -> list[dict]:
        return [t.get_tool_spec() for t in self.tools.values()]

    def get_help_text(self) -> str:
        lines = ["🤖 *OpenMiniCrew — คำสั่งทั้งหมด*\n"]

        # ---- Tool commands ----
        lines.append("📧 *อีเมล*")
        email_tool = self.tools.get("email_summary")
        if email_tool:
            lines.append("  /email — สรุปอีเมลวันนี้")
            lines.append("  /email 3d — ย้อนหลัง 3 วัน")
            lines.append("  /email 7d — ย้อนหลัง 7 วัน")
            lines.append("  /email 30d — ย้อนหลัง 30 วัน")
            lines.append("  /email force — สรุปใหม่ทั้งหมด")
            lines.append("  /email บัตรเครดิต — ค้นหาเรื่องที่สนใจ")
            lines.append("  /email from:ktc.co.th 7d — จากผู้ส่ง + ช่วงเวลา")

        # ---- Other tools (auto-generated) ----
        other_tools = [t for t in self.tools.values() if t.name != "email_summary"]
        if other_tools:
            lines.append("\n🔧 *เครื่องมืออื่นๆ*")
            for tool in other_tools:
                cmds = ", ".join(tool.commands)
                lines.append(f"  {cmds} — {tool.description}")

        # ---- System commands ----
        lines.append("\n⚙️ *ระบบ*")
        lines.append("  /model claude — เปลี่ยนเป็น Claude")
        lines.append("  /model gemini — เปลี่ยนเป็น Gemini")
        lines.append("  /help — แสดงข้อความนี้")

        # ---- Tip ----
        lines.append("\n💡 *พิมพ์อิสระได้เลย* — AI จะเลือก tool ให้อัตโนมัติ")
        lines.append("เช่น \"ช่วยสรุปอีเมลวันนี้\" หรือ \"อีเมลจาก Grab 7 วันล่าสุด\"")

        return "\n".join(lines)


# Singleton
registry = ToolRegistry()
