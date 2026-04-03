"""Gmail Summary Tool — ดึงเมลจาก Gmail + สรุปด้วย LLM"""

import asyncio
import base64
import re
from datetime import datetime
from email.utils import parseaddr
from html import unescape

from googleapiclient.discovery import build

from tools.base import BaseTool
from core.security import get_gmail_credentials
from core.config import GMAIL_MAX_RESULTS
from core import db
from core.llm import llm_router
from core.user_manager import get_user_by_id, get_preference
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


class GmailSummaryTool(BaseTool):
    name = "gmail_summary"
    description = "สรุปอีเมลที่ยังไม่ได้อ่านจาก Gmail"
    commands = ["/gmail", "/email"]
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

    FILLER_PHRASES = (
        "มีอะไรบ้าง",
        "อะไรบ้าง",
    )

    THAI_TIME_PATTERNS = (
        re.compile(r"(?:(?:ใน|ย้อนหลัง)\s*)?(\d{1,3})\s*วัน(?:ที่ผ่านมา|ล่าสุด)?"),
    )

    def _extract_time_range(self, text: str) -> tuple[str, str, str]:
        newer_than = "1d"
        time_label = "วันนี้"
        remaining = text

        for pattern in self.THAI_TIME_PATTERNS:
            match = pattern.search(remaining)
            if not match:
                continue
            days = match.group(1)
            newer_than = f"{days}d"
            time_label = "วันนี้" if days == "1" else f"{days} วันล่าสุด"
            remaining = (remaining[:match.start()] + " " + remaining[match.end():]).strip()
            return newer_than, time_label, remaining

        return newer_than, time_label, remaining

    def _normalize_search_query(self, text: str) -> str:
        normalized = text
        for phrase in self.FILLER_PHRASES:
            normalized = normalized.replace(phrase, " ")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _build_gmail_query(self, force: bool, newer_than: str, search_query: str) -> str:
        parts = [f"newer_than:{newer_than}"]

        # Default summary keeps the inbox view focused on unread mail.
        # Explicit searches or force re-runs should search all matching mail,
        # otherwise users get false negatives for older/read receipts.
        if not force and not search_query:
            parts.insert(0, "is:unread")

        if search_query:
            parts.append(search_query)

        return " ".join(parts)

    def _parse_args(self, args: str) -> tuple[bool, str, str, str]:
        """
        Parse arguments → (force, gmail_newer_than, time_label, search_query)
        เช่น "force 7d"          → (True, "7d", "7 วันล่าสุด", "")
             "บัตรเครดิต 7d"     → (False, "7d", "7 วันล่าสุด", "บัตรเครดิต")
             "from:ktc.co.th"    → (False, "1d", "วันนี้", "from:ktc.co.th")
             ""                  → (False, "1d", "วันนี้", "")
        """
        original_args = args.strip() if args else ""
        normalized_args = re.sub(r"\bforce\b", " ", original_args, flags=re.IGNORECASE).strip()

        newer_than, time_label, remaining_args = self._extract_time_range(normalized_args)

        tokens = remaining_args.split() if remaining_args else []
        tokens_lower = [t.lower() for t in tokens]

        force = bool(re.search(r"\bforce\b", original_args, flags=re.IGNORECASE))

        search_tokens = []

        for token, token_low in zip(tokens, tokens_lower):
            if token_low in self.TIME_RANGES:
                newer_than, time_label = self.TIME_RANGES[token_low]
            elif re.match(r"^\d+d$", token_low):
                newer_than = token_low
                time_label = f"{token_low[:-1]} วันล่าสุด"
            else:
                search_tokens.append(token)

        search_query = self._normalize_search_query(" ".join(search_tokens))
        return force, newer_than, time_label, search_query

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        force, newer_than, time_label, search_query = self._parse_args(args)

        # ใช้ LLM ตาม user preference (fallback เป็น default)
        user = get_user_by_id(user_id) or {}
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
            loop = asyncio.get_running_loop()
            service = build("gmail", "v1", credentials=creds)

            # 2. ดึงเมลตามช่วงเวลา + search query
            query = self._build_gmail_query(force, newer_than, search_query)
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

            now_str = datetime.now().strftime("%d %b %Y %H:%M")
            system = (
                f"คุณเป็นผู้ช่วยสรุปอีเมลอัจฉริยะ ตอบเป็นภาษาไทย\n"
                f"เวลาปัจจุบันที่คุณกำลังอ่านและสรุปคือ: {now_str}\n"
                f"คำแนะนำสำคัญเรื่องเวลา (โปรดทำตาม 2 ขั้นตอนนี้อย่างเคร่งครัด): \n"
                f"1. ทำความเข้าใจเวลาของเหตุการณ์เปรียบเทียบจาก 'วันที่ส่งอีเมล (Date)' เช่น ถ้าย้อนดูอีเมลที่ส่งวันที่ 9 และเนื้อหาบอกว่า 'เมื่อวาน' = เหตุการณ์คือวันที่ 8, 'พรุ่งนี้' = เหตุการณ์คือวันที่ 10, หรือ '10 มี.ค.' = เหตุการณ์คือ 10 มี.ค.\n"
                f"2. เวลาพิมพ์สรุปให้ผู้ใช้ ให้แปลงวันที่จากข้อ 1 มาเทียบกับ 'เวลาปัจจุบัน ({now_str})' เสมอ เช่น ถ้าเหตุการณ์จากข้อ 1 คือวันที่ 10 มี.ค. และเวลาปัจจุบันคือ 10 มี.ค. ต้องใช้คำว่า 'วันนี้' หรือ 'เช้านี้' หรือ '10 มี.ค.' ห้ามสรุปว่า 'พรุ่งนี้' เด็ดขาด!\n\n"
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
                llm_model=resp["model"],
                token_used=resp["token_used"],
                status="success",
                **db.make_log_field("input", f"{len(emails_data)} emails ({display_label})", kind="gmail_batch_request"),
                **db.make_log_field("output", resp["content"], kind="gmail_summary_text"),
            )

            return f"📬 สรุปอีเมล {len(emails_data)} ฉบับ ({display_label}):\n\n{resp['content']}"

        except Exception as e:
            log.error(f"Email summary failed for {user_id}: {e}", exc_info=True)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_error_fields(str(e)),
            )
            return f"เกิดข้อผิดพลาดในการดึงอีเมล: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "gmail_summary",
            "description": (
                "สรุปอีเมลจาก Gmail ส่วนตัวของ user (ต้อง /authgmail ก่อน). "
                "ใช้เมื่อ user ถามเรื่องอีเมล Gmail. "
                "ไม่ใช่สำหรับอีเมลที่ทำงาน IMAP (ใช้ work_email) "
                "และไม่ใช่สำหรับหา action items จากอีเมล (ใช้ smart_inbox). "
                "เช่น 'เช็คอีเมล', 'สรุปอีเมลวันนี้', 'มีเมลจาก grab ไหม'"
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

