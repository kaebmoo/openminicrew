"""Expense tracker tool — บันทึกรายจ่ายด้วยการพิมพ์ หรือถ่ายรูปบิล/slip"""

import json
import re
from datetime import date, timedelta

from core import db
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)


class ExpenseTool(BaseTool):
    name = "expense"
    description = "บันทึกรายจ่าย ดูรายการล่าสุด สรุปรายจ่าย หรือถ่ายรูปบิล/slip เพื่อบันทึกอัตโนมัติ"
    commands = ["/exp", "/expense"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        raw_args = (args or "").strip()

        try:
            # ตรวจว่าเป็นรูปภาพจาก Telegram (format: __photo:<file_id> <caption>)
            if raw_args.startswith("__photo:"):
                result = await self._handle_photo(user_id, raw_args)
            else:
                tokens = raw_args.split()
                if not tokens:
                    result = self._usage()
                else:
                    sub = tokens[0].lower()
                    if sub == "list":
                        result = self._list(user_id)
                    elif sub == "summary":
                        period = tokens[1].lower() if len(tokens) > 1 else "month"
                        result = self._summary(user_id, period)
                    else:
                        if sub == "add":
                            tokens = tokens[1:]
                        result = self._add(user_id, tokens)

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=raw_args[:100],
                output_summary=result[:200],
                status="success",
            )
            return result
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            log.error("Expense tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                input_summary=raw_args[:100],
                status="failed",
                error_message=str(e),
            )
            return f"❌ ใช้งาน expense ไม่สำเร็จ: {e}"

    def _add(self, user_id: str, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return self._usage()
        try:
            amount = float(tokens[0].replace(",", ""))
        except ValueError:
            return "❌ จำนวนเงินไม่ถูกต้อง — ตัวอย่าง: /expense 120 อาหาร ก๋วยเตี๋ยว"
        category = tokens[1]
        note = " ".join(tokens[2:]).strip()
        expense_id = db.add_expense(user_id, amount=amount, category=category, note=note)
        return f"💸 บันทึกรายจ่ายแล้ว [#{expense_id}]\n{amount:,.2f} บาท\nหมวด: {category}" + (f"\nหมายเหตุ: {note}" if note else "")

    def _list(self, user_id: str) -> str:
        expenses = db.list_expenses(user_id)
        if not expenses:
            return "💸 ยังไม่มีรายจ่ายที่บันทึกไว้"
        lines = ["💸 รายจ่ายล่าสุด:\n"]
        for item in expenses:
            lines.append(f"[{item['id']}] {item['expense_date']} — {item['category']} {item['amount']:,.2f} บาท {item['note']}")
        return "\n".join(lines)

    def _summary(self, user_id: str, period: str) -> str:
        today = date.today()
        if period == "today":
            start_date = end_date = today.isoformat()
        elif period == "7d":
            start_date = (today - timedelta(days=6)).isoformat()
            end_date = today.isoformat()
        else:
            start_date = today.replace(day=1).isoformat()
            end_date = today.isoformat()

        rows = db.summarize_expenses(user_id, start_date, end_date)
        if not rows:
            return "💸 ไม่มีรายจ่ายในช่วงที่เลือก"
        total = sum(float(item["total"]) for item in rows)
        lines = [f"💸 สรุปรายจ่าย {start_date} ถึง {end_date}\nรวม {total:,.2f} บาท\n"]
        for item in rows:
            lines.append(f"• {item['category']}: {float(item['total']):,.2f} บาท ({item['count']} รายการ)")
        return "\n".join(lines)

    async def _handle_photo(self, user_id: str, raw_args: str) -> str:
        """รับรูปบิล/slip จาก Telegram → ใช้ Gemini Vision วิเคราะห์ → บันทึกรายจ่าย"""
        # Parse __photo:<file_id> <caption>
        parts = raw_args.split(None, 1)
        file_id = parts[0].replace("__photo:", "")
        caption = parts[1] if len(parts) > 1 else ""

        # Download image from Telegram
        from interfaces.telegram_common import download_telegram_photo
        image_bytes = download_telegram_photo(file_id)
        if not image_bytes:
            return "❌ ไม่สามารถดาวน์โหลดรูปได้ กรุณาลองส่งใหม่"

        # Use Gemini Vision to analyze the receipt/slip
        extracted = await self._extract_expense_from_image(image_bytes, caption)
        if not extracted:
            return "❌ ไม่สามารถอ่านข้อมูลจากรูปได้ กรุณาลองถ่ายใหม่ให้ชัดขึ้น หรือพิมพ์เอง: /expense 120 อาหาร"

        # บันทึกรายจ่าย
        amount = extracted["amount"]
        category = extracted.get("category", "ทั่วไป")
        note = extracted.get("note", "")
        if caption and not note:
            note = caption

        expense_id = db.add_expense(user_id, amount=amount, category=category, note=note)
        return (
            f"📸 บันทึกรายจ่ายจากรูปแล้ว [#{expense_id}]\n"
            f"{amount:,.2f} บาท\n"
            f"หมวด: {category}"
            + (f"\nหมายเหตุ: {note}" if note else "")
        )

    async def _extract_expense_from_image(self, image_bytes: bytes, hint: str = "") -> dict | None:
        """ใช้ Gemini Vision วิเคราะห์รูปบิล/slip → return {amount, category, note} หรือ None"""
        try:
            from google import genai
            from google.genai import types as genai_types
            from core.config import GEMINI_API_KEY

            if not GEMINI_API_KEY:
                log.warning("Gemini API key not configured, cannot analyze receipt image")
                return None

            client = genai.Client(api_key=GEMINI_API_KEY, http_options={"timeout": 30000})

            prompt = (
                "วิเคราะห์รูปนี้ซึ่งเป็นใบเสร็จ, บิล, หรือ slip การโอนเงิน\n"
                "ดึงข้อมูลออกมาเป็น JSON format:\n"
                '{"amount": <จำนวนเงิน (number)>, "category": "<หมวดหมู่>", "note": "<รายละเอียดสั้นๆ>"}\n'
                "หมวดหมู่ที่แนะนำ: อาหาร, เครื่องดื่ม, เดินทาง, ช็อปปิ้ง, สาธารณูปโภค, สุขภาพ, บันเทิง, การศึกษา, โอนเงิน, ทั่วไป\n"
                "ตอบเฉพาะ JSON เท่านั้น ไม่ต้องอธิบายเพิ่ม\n"
                "ถ้าอ่านไม่ออกหรือไม่ใช่ใบเสร็จ/บิล/slip ให้ตอบ: null"
            )
            if hint:
                prompt += f"\nข้อมูลเพิ่มเติมจากผู้ใช้: {hint}"

            image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            text_part = genai_types.Part.from_text(text=prompt)

            resp = await client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=[genai_types.Content(role="user", parts=[image_part, text_part])],
            )

            if not resp.candidates or not resp.candidates[0].content:
                return None

            response_text = ""
            for part in resp.candidates[0].content.parts or []:
                if part.text:
                    response_text += part.text

            response_text = response_text.strip()
            if not response_text or response_text == "null":
                return None

            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group())
            amount = float(data.get("amount", 0))
            if amount <= 0:
                return None

            return {
                "amount": amount,
                "category": data.get("category", "ทั่วไป"),
                "note": data.get("note", ""),
            }

        except Exception as e:
            log.error("Failed to extract expense from image: %s", e)
            return None

    def _usage(self) -> str:
        return (
            "ใช้: /expense 120 อาหาร ก๋วยเตี๋ยว\n"
            "/expense list — ดูรายจ่ายล่าสุด\n"
            "/expense summary month — สรุปรายจ่ายเดือนนี้\n"
            "📸 หรือถ่ายรูปบิล/slip ส่งมา จะบันทึกอัตโนมัติ"
        )

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "บันทึกและสรุปรายจ่าย เช่น '/expense 120 อาหาร ข้าวกลางวัน', '/expense list', '/expense summary month' "
                "หรือส่งรูปถ่ายบิล/slip เพื่อบันทึกอัตโนมัติ"
            ),
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "คำสั่ง expense"}},
                "required": ["args"],
            },
        }
