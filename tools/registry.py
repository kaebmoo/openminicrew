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

        for _finder, module_name, _ in pkgutil.iter_modules([str(tools_dir)]):
            if module_name in ("base", "registry", "__init__"):
                continue

            try:
                module = importlib.import_module(f"tools.{module_name}")

                for _attr_name, attr in inspect.getmembers(module, inspect.isclass):
                    if issubclass(attr, BaseTool) and attr is not BaseTool:
                        instance = attr()
                        self._register(instance)

            except (ImportError, AttributeError, TypeError, ValueError) as e:
                log.error("Failed to load tool module '%s': %s", module_name, e, exc_info=True)

        log.info("Discovered %s tools: %s", len(self.tools), list(self.tools.keys()))

    def _register(self, tool: BaseTool):
        if not tool.name:
            log.warning("Skipping tool with empty name: %s", type(tool))
            return

        self.tools[tool.name] = tool
        for cmd in tool.commands:
            existing = self.command_map.get(cmd)
            if existing and existing.name != tool.name:
                log.warning(
                    "Skipping duplicate command %s for tool %s; already registered to %s",
                    cmd,
                    tool.name,
                    existing.name,
                )
                continue
            self.command_map[cmd] = tool

        log.info("Registered tool: %s (commands: %s)", tool.name, tool.commands)

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

        # ---- Tool commands (auto-generated from registry) ----
        # จัดกลุ่มตาม category
        email_tools = [t for t in self.tools.values() if t.name in ("gmail_summary", "work_email")]
        media_tools = [t for t in self.tools.values() if t.name in ("qrcode_gen", "promptpay")]
        util_tools = [t for t in self.tools.values() if t.name in ("unit_converter", "web_search")]
        task_tools = [t for t in self.tools.values() if t.name in ("todo", "reminder", "calendar", "smart_inbox")]
        finance_tools = [t for t in self.tools.values() if t.name in ("expense",)]
        categorized_names = {t.name for group in [email_tools, media_tools, util_tools, task_tools, finance_tools] for t in group}
        other_tools = [t for t in self.tools.values() if t.name not in categorized_names]

        def _add_group(title: str, tools: list):
            if not tools:
                return
            lines.append(f"\n{title}")
            for tool in tools:
                cmds = ", ".join(tool.commands)
                lines.append(f"  {cmds} — {tool.description}")

        _add_group("📧 *อีเมล*", email_tools)
        _add_group("📸 *QR/สร้างภาพ*", media_tools)
        _add_group("🔧 *เครื่องมือ*", util_tools)
        _add_group("📋 *งานและนัดหมาย*", task_tools)
        _add_group("💸 *การเงิน*", finance_tools)
        _add_group("📦 *อื่นๆ*", other_tools)

        # ---- System commands ----
        lines.append("\n⚙️ *ระบบ*")
        lines.append("  /start — ลงทะเบียนและดู onboarding")
        lines.append("  /new — เริ่มสนทนาใหม่")
        lines.append("  /history — ดูประวัติสนทนา")
        lines.append("  /setname <ชื่อ> — ตั้งชื่อที่แสดง")
        lines.append("  /setphone <เบอร์> — บันทึกเบอร์โทร")
        lines.append("  /setid <เลขบัตร 13 หลัก> — บันทึกเลขบัตรประชาชน")
        lines.append("  /authgmail — เชื่อมต่อ Gmail")
        lines.append("  /disconnectgmail — ยกเลิกการเชื่อมต่อ Gmail")
        lines.append("  /clearlocation — ลบตำแหน่งล่าสุดที่บันทึกไว้")
        lines.append("  /consent [gmail|location|chat] [on|off] — จัดการ consent แบบ explicit")
        lines.append("  /privacy — ดู retention และตัวเลือกด้านข้อมูลส่วนบุคคล")
        lines.append("  /delete_my_data confirm — ลบข้อมูลการใช้งานที่ผูกกับบัญชีแบบถาวร (คง audit trail ขั้นต่ำไว้)")
        lines.append("  /model — ดู/เปลี่ยน LLM (claude, gemini, matcha)")
        lines.append("  /setkey <service> <value> — บันทึก API key ของตัวเอง")
        lines.append("  /mykeys — ดูรายการ key ของตัวเอง")
        lines.append("  /removekey <service> — ลบ key ที่บันทึกไว้")
        lines.append("  /keyaudit — owner only, ดูรายงาน rows ของ user_api_keys ที่ยังเป็น plaintext")
        lines.append("  /help — แสดงข้อความนี้")

        # ---- Tip ----
        lines.append("\n💡 *พิมพ์อิสระได้เลย* — AI จะเลือก tool ให้อัตโนมัติ")
        lines.append("หรือถ่ายรูปบิล/slip ส่งมา → บันทึกรายจ่ายอัตโนมัติ")

        return "\n".join(lines)


# Singleton
registry = ToolRegistry()
