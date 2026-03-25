"""Todo tool."""

from core import db
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)


class TodoTool(BaseTool):
    name = "todo"
    description = "จัดการรายการงานที่ต้องทำ พร้อมสถานะ priority และ due date"
    commands = ["/todo"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        raw_args = (args or "").strip()

        try:
            tokens = raw_args.split()
            if not tokens:
                result = self._list(user_id, "open")
            else:
                sub = tokens[0].lower()
                if sub == "list":
                    status = tokens[1].lower() if len(tokens) > 1 else "open"
                    result = self._list(user_id, status)
                elif sub in ("done", "finish"):
                    if len(tokens) < 2:
                        result = "❌ ใช้: /todo done <id>"
                    else:
                        result = self._update_status(user_id, int(tokens[1]), "done")
                elif sub in ("remove", "delete"):
                    if len(tokens) < 2:
                        result = "❌ ใช้: /todo remove <id>"
                    else:
                        result = self._remove(user_id, int(tokens[1]))
                elif sub == "add":
                    result = self._add(user_id, " ".join(tokens[1:]))
                else:
                    result = self._add(user_id, " ".join(tokens))

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", raw_args, kind="todo_command"),
                **db.make_log_field("output", result, kind="todo_result"),
            )
            return result
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            log.error("Todo tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", raw_args, kind="todo_command"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ ใช้งาน todo ไม่สำเร็จ: {e}"

    def _add(self, user_id: str, content: str) -> str:
        if not content.strip():
            return "❌ ใช้: /todo <งานที่ต้องทำ>"

        priority = "medium"
        due_at = ""
        title = content.strip()

        for marker, value in (("!high", "high"), ("!low", "low")):
            if marker in title:
                priority = value
                title = title.replace(marker, "").strip()

        if " due:" in title:
            title, due_at = title.split(" due:", 1)
            title = title.strip()
            due_at = due_at.strip()

        todo_id = db.add_todo(user_id, title=title, priority=priority, due_at=due_at)
        return f"✅ เพิ่ม todo แล้ว [#{todo_id}]\n📝 {title}\n⚡ priority: {priority}" + (f"\n📅 due: {due_at}" if due_at else "")

    def _list(self, user_id: str, status: str) -> str:
        status_filter = None if status == "all" else status
        todos = db.list_todos(user_id, status_filter)
        if not todos:
            return "📝 ยังไม่มี todo" if status_filter in (None, "open") else f"📝 ไม่มี todo สถานะ {status}"
        lines = [f"📝 Todo ({status}):\n"]
        for item in todos[:30]:
            due = f" | due {item['due_at'][:16]}" if item.get("due_at") else ""
            lines.append(f"[{item['id']}] {item['title']} | {item['priority']} | {item['status']}{due}")
        return "\n".join(lines)

    def _update_status(self, user_id: str, todo_id: int, status: str) -> str:
        if not db.update_todo_status(todo_id, user_id, status):
            return f"❌ ไม่พบ todo #{todo_id}"
        return f"✅ อัปเดต todo #{todo_id} เป็น {status} แล้ว"

    def _remove(self, user_id: str, todo_id: int) -> str:
        if not db.remove_todo(todo_id, user_id):
            return f"❌ ไม่พบ todo #{todo_id}"
        return f"✅ ลบ todo #{todo_id} แล้ว"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "จัดการ todo เช่น '/todo ซื้อของ', '/todo add ทำสไลด์ !high due:2026-03-30 18:00', '/todo list', '/todo done 1'",
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "คำสั่ง todo"}},
                "required": [],
            },
        }