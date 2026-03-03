"""Email Summary Tool — ดึงเมลจาก Gmail + สรุปด้วย LLM"""

import asyncio
import base64
import re
from email.utils import parseaddr
from html import unescape

from googleapiclient.discovery import build

from tools.base import BaseTool
from core.security import get_gmail_credentials
from core.config import GMAIL_MAX_RESULTS
from core import db
from core.llm import llm_router
from core.user_manager import get_user, get_preference
from core.logger import get_logger

log = get_logger(__name__)


def _extract_text(payload: dict) -> str:
    """ดึง text จาก email payload (recursive สำหรับ multipart)"""
    if payload.get("mimeType", "").startswith("text/plain"):
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    if payload.get("mimeType", "").startswith("text/html"):
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", html)
            return unescape(text).strip()

    for part in payload.get("parts", []):
        text = _extract_text(part)
        if text:
            return text

    return ""


class EmailSummaryTool(BaseTool):
    name = "email_summary"
    description = "สรุปอีเมลที่ยังไม่ได้อ่านจาก Gmail"
    commands = ["/email"]
    preferred_tier = "mid"

    # Mapping ของ time range shortcuts
    TIME_RANGES = {
        "today": ("1d", "วันนี้"),
        "1d": ("1d", "วันนี้"),
        "3d": ("3d", "3 วันล่าสุด"),
        "7d": ("7d", "7 วันล่าสุด"),
        "14d": ("14d", "14 วันล่าสุด"),
        "30d": ("30d", "30 วันล่าสุด"),
    }

    def _parse_args(self, args: str) -> tuple[bool, str, str, str]:
        """
        Parse arguments → (force, gmail_newer_than, time_label, search_query)
        เช่น "force 7d"          → (True, "7d", "7 วันล่าสุด", "")
             "บัตรเครดิต 7d"     → (False, "7d", "7 วันล่าสุด", "บัตรเครดิต")
             "from:ktc.co.th"    → (False, "1d", "วันนี้", "from:ktc.co.th")
             ""                  → (False, "1d", "วันนี้", "")
        """
        # เก็บ args ต้นฉบับ (ไม่ lower) เพราะ search query อาจมี case สำคัญ
        original_args = args.strip() if args else ""
        tokens = original_args.split() if original_args else []
        tokens_lower = [t.lower() for t in tokens]

        # ดึง force
        force = "force" in tokens_lower

        # หา time range + แยก search tokens
        newer_than = "1d"
        time_label = "วันนี้"
        search_tokens = []

        for token, token_low in zip(tokens, tokens_lower):
            if token_low == "force":
                continue
            elif token_low in self.TIME_RANGES:
                newer_than, time_label = self.TIME_RANGES[token_low]
            elif re.match(r"^\d+d$", token_low):
                newer_than = token_low
                time_label = f"{token_low[:-1]} วันล่าสุด"
            else:
                search_tokens.append(token)

        search_query = " ".join(search_tokens)
        return force, newer_than, time_label, search_query

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        force, newer_than, time_label, search_query = self._parse_args(args)

        # ใช้ LLM ตาม user preference (fallback เป็น default)
        user = get_user(user_id) or {}
        provider = get_preference(user, "default_llm")
        # สร้าง label สำหรับแสดงผล
        display_label = time_label
        if search_query:
            display_label = f"{time_label} ค้นหา: \"{search_query}\""

        # 1. ดึง Gmail credentials
        creds = get_gmail_credentials(user_id)
        if not creds:
            from core.config import WEBHOOK_HOST
            if WEBHOOK_HOST:
                return "❌ ยังไม่ได้เชื่อมต่อ Gmail\nกรุณาพิมพ์ /authgmail เพื่อ authorize"
            return "❌ ยังไม่ได้เชื่อมต่อ Gmail\nกรุณารัน: python main.py --auth-gmail"

        try:
            loop = asyncio.get_event_loop()
            service = build("gmail", "v1", credentials=creds)

            # 2. ดึงเมลตามช่วงเวลา + search query
            query = f"is:unread newer_than:{newer_than}"
            if search_query:
                query += f" {search_query}"
            log.info(f"Gmail query: {query}")

            # run_in_executor เพื่อไม่ block event loop (Gmail API เป็น sync)
            results = await loop.run_in_executor(
                None,
                lambda: service.users().messages().list(
                    userId="me", q=query, maxResults=GMAIL_MAX_RESULTS
                ).execute()
            )

            messages = results.get("messages", [])
            if not messages:
                return f"ไม่พบอีเมลที่ตรงกับ: {display_label}"

            # 3. ดึงรายละเอียดแต่ละฉบับ (ข้ามที่เคยสรุปแล้ว ยกเว้น force)
            emails_data = []
            skipped = 0
            for msg_meta in messages:
                msg_id = msg_meta["id"]

                if not force and db.is_email_processed(user_id, msg_id):
                    skipped += 1
                    continue

                msg = await loop.run_in_executor(
                    None,
                    lambda mid=msg_id: service.users().messages().get(
                        userId="me", id=mid, format="full"
                    ).execute()
                )

                headers = {h["name"]: h["value"]
                           for h in msg.get("payload", {}).get("headers", [])}

                subject = headers.get("Subject", "(ไม่มีหัวข้อ)")
                sender_raw = headers.get("From", "(unknown)")
                _, sender_email = parseaddr(sender_raw)
                sender = sender_raw if sender_email else sender_raw

                body = _extract_text(msg.get("payload", {}))
                body = body[:2000]  # ตัดเนื้อหายาวเกินไป

                emails_data.append({
                    "id": msg_id,
                    "subject": subject,
                    "sender": sender,
                    "snippet": body[:500] if body else msg.get("snippet", ""),
                })

            if not emails_data:
                hint = f"ใน{display_label} สรุปไปหมดแล้ว ({skipped} ฉบับ)"
                hint += "\n\nลองใช้:\n"
                hint += "• /email force — สรุปใหม่ทั้งหมด\n"
                hint += "• /email 3d — ดูย้อนหลัง 3 วัน\n"
                hint += "• /email 7d — ดูย้อนหลัง 7 วัน\n"
                hint += "• /email บัตรเครดิต — ค้นหาเรื่องที่สนใจ"
                return hint

            # 4. ส่งให้ LLM สรุป
            emails_text = ""
            for i, em in enumerate(emails_data, 1):
                emails_text += f"\n--- Email #{i} ---\n"
                emails_text += f"From: {em['sender']}\n"
                emails_text += f"Subject: {em['subject']}\n"
                emails_text += f"Content: {em['snippet']}\n"

            system = (
                "คุณเป็นผู้ช่วยสรุปอีเมลอัจฉริยะ ตอบเป็นภาษาไทย\n\n"
                "ให้สรุปอีเมลตามรูปแบบนี้:\n\n"
                "1. **ภาพรวม** — สรุปสั้นๆ 1-2 บรรทัดว่าวันนี้มีอีเมลอะไรบ้างโดยรวม\n\n"
                "2. **🔴 ต้องดำเนินการ (Action Required)** — อีเมลที่ต้องทำอะไรบางอย่าง "
                "เช่น ตรวจสอบธุรกรรม ตอบกลับ นัดหมาย (ถ้ามี)\n\n"
                "3. **จัดกลุ่มตามประเภท** — จัดอีเมลที่เหลือเป็นกลุ่ม เช่น:\n"
                "   - 💰 การเงิน/ธุรกรรม\n"
                "   - 💼 งาน/ธุรกิจ\n"
                "   - 📊 การลงทุน/หุ้น\n"
                "   - 🛒 โปรโมชั่น/การตลาด\n"
                "   - 📰 ข่าวสาร/จดหมายข่าว\n"
                "   - 🔔 แจ้งเตือน/อื่นๆ\n"
                "   (เลือกกลุ่มที่เหมาะสมกับเนื้อหาจริง ไม่ต้องใช้ทุกกลุ่ม)\n\n"
                "4. **สรุปท้าย** — สิ่งที่ควรให้ความสำคัญก่อน\n\n"
                "ในแต่ละรายการให้บอกสั้นๆ: ใครส่ง + เรื่องอะไร + ต้องทำอะไร (ถ้ามี)\n"
                "รวมอีเมลที่คล้ายกันเข้าด้วยกัน เช่น Grab receipts หลายฉบับ ให้รวมเป็นรายการเดียว\n"
                "ใช้ emoji ให้อ่านง่าย กระชับ ไม่ต้องยาวเกินไป"
            )
            resp = await llm_router.chat(
                messages=[{"role": "user", "content": f"สรุปอีเมล {len(emails_data)} ฉบับ ({display_label}):\n{emails_text}"}],
                provider=provider,
                tier=self.preferred_tier,
                system=system,
            )

            # 5. บันทึกว่าสรุปแล้ว
            for em in emails_data:
                db.mark_email_processed(user_id, em["id"], em["subject"], em["sender"])

            # 6. Log usage
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=f"{len(emails_data)} emails ({display_label})",
                output_summary=resp["content"][:200],
                llm_model=resp["model"],
                token_used=resp["token_used"],
                status="success",
            )

            return f"📬 สรุปอีเมล {len(emails_data)} ฉบับ ({display_label}):\n\n{resp['content']}"

        except Exception as e:
            log.error(f"Email summary failed for {user_id}: {e}")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                error_message=str(e),
            )
            return f"เกิดข้อผิดพลาดในการดึงอีเมล: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "email_summary",
            "description": (
                "สรุปอีเมลที่ยังไม่ได้อ่าน หรืออีเมลมาใหม่/ล่าสุด จาก Gmail ของผู้ใช้ "
                "สามารถระบุช่วงเวลาได้ เช่น today, 3d, 7d, 30d "
                "ค้นหาเรื่องที่สนใจได้ เช่น บัตรเครดิต, from:ktc.co.th "
                "ใส่ force เพื่อสรุปใหม่แม้เคยสรุปแล้ว"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "ตัวเลือก: today, 3d, 7d, 30d (ช่วงเวลา), "
                            "force (สรุปใหม่), "
                            "คำค้นหา เช่น 'บัตรเครดิต', 'from:ktc.co.th', 'netflix' "
                            "ใช้ร่วมกันได้ เช่น 'บัตรเครดิต 7d' หรือ 'force from:grab.com 30d'"
                        ),
                    }
                },
                "required": [],
            },
        }

