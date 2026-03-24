"""Smart Inbox tool for extracting action items from Gmail."""

import asyncio
from email.utils import parseaddr

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core import db
from core.llm import llm_router
from core.security import get_gmail_credentials
from core.user_manager import get_user_by_id, set_preference
from core.logger import get_logger
from tools.base import BaseTool
from tools.gmail_summary import _extract_text

log = get_logger(__name__)


class SmartInboxTool(BaseTool):
    name = "smart_inbox"
    description = "วิเคราะห์อีเมล หา action items และสร้าง todo อัตโนมัติได้"
    commands = ["/inbox"]
    direct_output = True
    preferred_tier = "mid"

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        raw_args = (args or "").strip()

        try:
            tokens = raw_args.split()
            if tokens[:1] == ["mode"] and len(tokens) >= 2:
                mode = tokens[1].lower()
                if mode not in ("confirm", "auto"):
                    result = "❌ ใช้: /inbox mode confirm|auto"
                else:
                    set_preference(user_id, "smart_inbox_mode", mode)
                    result = f"✅ ตั้ง Smart Inbox mode เป็น {mode} แล้ว"
            else:
                creds = get_gmail_credentials(user_id)
                if not creds:
                    result = "❌ ยังไม่ได้เชื่อมต่อ Gmail\nกรุณาใช้ /authgmail"
                else:
                    user = get_user_by_id(user_id) or {}
                    mode = user.get("smart_inbox_mode", "confirm")
                    service = build("gmail", "v1", credentials=creds)
                    messages = await self._fetch_recent_messages(service)
                    if not messages:
                        result = "📥 ไม่พบอีเมลที่น่าติดตามในช่วงล่าสุด"
                    else:
                        analysis = await self._extract_action_items(messages)
                        action_items = [line.strip("- • ") for line in analysis.splitlines() if line.strip() and line.strip().startswith(("-", "•", "1", "2", "3", "4", "5"))]

                        created = []
                        if mode == "auto":
                            for item in action_items[:10]:
                                todo_id = db.add_todo(user_id, title=item, source_type="smart_inbox", source_ref="gmail")
                                created.append(todo_id)

                        lines = [f"📥 Smart Inbox ({mode})\n", analysis]
                        if created:
                            lines.append("\n✅ สร้าง todo อัตโนมัติ: " + ", ".join(f"#{todo_id}" for todo_id in created))
                        elif mode == "confirm":
                            lines.append("\n💡 mode confirm: ยังไม่สร้าง todo อัตโนมัติ ถ้าต้องการ auto ใช้ /inbox mode auto")
                        result = "\n".join(lines)

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=raw_args[:100],
                output_summary=result[:200],
                status="success",
            )
            return result
        except (HttpError, OSError, RuntimeError, TypeError, ValueError) as e:
            log.error("Smart inbox failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=raw_args[:100],
                status="failed",
                error_message=str(e),
            )
            return f"❌ ใช้งาน Smart Inbox ไม่สำเร็จ: {e}"

    async def _fetch_recent_messages(self, service) -> list[dict]:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: service.users().messages().list(userId="me", q="newer_than:7d", maxResults=10).execute(),
        )
        messages = []
        for meta in results.get("messages", []):
            msg = await loop.run_in_executor(
                None,
                lambda mid=meta["id"]: service.users().messages().get(userId="me", id=mid, format="full").execute(),
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = parseaddr(headers.get("From", ""))[1] or headers.get("From", "")
            body = _extract_text(msg.get("payload", {}))[:1000]
            messages.append({
                "subject": headers.get("Subject", "(ไม่มีหัวข้อ)"),
                "from": sender,
                "date": headers.get("Date", ""),
                "body": body,
            })
        return messages

    async def _extract_action_items(self, messages: list[dict]) -> str:
        content = []
        for idx, msg in enumerate(messages, 1):
            content.append(f"Email {idx}\nFrom: {msg['from']}\nSubject: {msg['subject']}\nDate: {msg['date']}\nBody: {msg['body']}\n")
        resp = await llm_router.chat(
            messages=[{"role": "user", "content": "สรุป action items จากอีเมลเหล่านี้เป็น bullet list ภาษาไทย พร้อมบอกว่าควรทำอะไรต่อ\n\n" + "\n".join(content)}],
            tier=self.preferred_tier,
            system="คุณเป็นผู้ช่วยจัดการ inbox สกัดเฉพาะงานที่ต้องทำ นัดหมายที่ต้องจำ และสิ่งที่ต้องตามต่อ ตอบเป็น bullet list ภาษาไทยที่กระชับ",
        )
        return resp.get("content", "ไม่มี action item ที่ชัดเจน")

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "วิเคราะห์อีเมลล่าสุด หา action items และสร้าง todo ได้ เช่น '/inbox' หรือ '/inbox mode auto'",
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "คำสั่ง smart inbox"}},
                "required": [],
            },
        }