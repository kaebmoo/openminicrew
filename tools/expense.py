"""Expense tracker tool — บันทึกรายจ่ายด้วยการพิมพ์ หรือถ่ายรูปบิล/slip"""

import hashlib
import json
import re
from datetime import date, timedelta

from google.genai import errors as genai_errors

from core import db
from core.logger import get_logger
from core.prompt_loader import load_prompt
from tools.base import BaseTool

log = get_logger(__name__)


class ExpenseTool(BaseTool):
    name = "expense"
    description = "บันทึกรายจ่าย ดูรายการล่าสุด สรุปรายจ่าย หรือถ่ายรูปบิล/slip เพื่อบันทึกอัตโนมัติ"
    commands = ["/exp", "/expense"]
    direct_output = True
    RECEIPT_SOURCE_TYPE = "telegram_photo"

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
                    elif sub == "delete":
                        result = self._delete(user_id, tokens[1:])
                    elif sub == "edit":
                        result = self._edit(user_id, tokens[1:])
                    elif sub == "summary":
                        # summary compare month / summary compare 7d
                        if len(tokens) > 1 and tokens[1].lower() == "compare":
                            compare_period = tokens[2].lower() if len(tokens) > 2 else "month"
                            result = self._compare(user_id, compare_period)
                        else:
                            period = tokens[1].lower() if len(tokens) > 1 else "month"
                            # tokens ที่เหลือหลัง period: category หรือ keyword
                            category = ""
                            keyword = ""
                            for t in tokens[2:]:
                                if t in self._KNOWN_CATEGORIES:
                                    category = t
                                elif not keyword:
                                    keyword = t
                            result = self._summary(user_id, period, category=category, keyword=keyword)
                    else:
                        if sub == "add":
                            tokens = tokens[1:]
                        result = self._add(user_id, tokens)

            from tools.response import InlineKeyboardResponse
            log_output = result.memory_text or result.text if isinstance(result, InlineKeyboardResponse) else result
            input_log = db.make_log_field("input", raw_args, kind="expense_command")
            output_log = db.make_log_field("output", log_output, kind="expense_result")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                input_kind=input_log["input_kind"],
                input_ref=input_log["input_ref"],
                input_size=input_log["input_size"],
                output_kind=output_log["output_kind"],
                output_ref=output_log["output_ref"],
                output_size=output_log["output_size"],
            )
            return result
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            log.error("Expense tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", raw_args, kind="expense_command"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ ใช้งาน expense ไม่สำเร็จ: {e}"

    # คำที่ไม่ใช่ชื่อหมวดหมู่ — LLM มักใส่หน่วยเงินมาด้วย
    _CURRENCY_WORDS = {"บาท", "baht", "thb", "฿"}

    # หมวดหมู่ที่รู้จัก — ใช้ตรวจว่า token เป็นชื่อหมวดจริงหรือเป็นแค่ชื่อรายการ
    _KNOWN_CATEGORIES = {
        "อาหาร", "เครื่องดื่ม", "เดินทาง", "ช็อปปิ้ง", "ของใช้",
        "สาธารณูปโภค", "สุขภาพ", "บันเทิง", "การศึกษา", "โอนเงิน", "ทั่วไป",
        "food", "drink", "transport", "shopping", "utility", "health",
        "entertainment", "education", "transfer", "general",
    }

    _INCOME_KEYWORDS = {"รับเงิน", "รับโอน", "เงินเข้า", "โอนเข้า", "income", "receive", "รับจ่าย"}

    # ไอคอน + label สำหรับแสดง confidence ต่อรายการ (Phase A)
    _CONF_ICON = {"high": "[v]", "medium": "[~]", "low": "[?]"}
    _CONF_LABEL = {"high": "สูง", "medium": "ปานกลาง", "low": "ต่ำ"}

    def _is_income_intent(self, tokens: list[str]) -> bool:
        """ตรวจว่า tokens มี keyword รายรับ"""
        text_lower = " ".join(tokens).lower()
        return any(kw in text_lower for kw in self._INCOME_KEYWORDS)

    def _add(self, user_id: str, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return self._usage()

        # Guard: income intent
        if self._is_income_intent(tokens):
            return (
                "ดูเหมือนเป็นรายรับ ไม่ใช่รายจ่าย -- ไม่ได้บันทึก\n"
                "ถ้าต้องการสร้าง QR รับเงิน ใช้: /pay 150\n"
                "ถ้าต้องการบันทึกรายจ่ายจริง ใช้: /expense 150 หมวด หมายเหตุ"
            )

        try:
            amount = float(tokens[0].replace(",", ""))
        except ValueError:
            return "❌ จำนวนเงินไม่ถูกต้อง — ตัวอย่าง: /expense 120 อาหาร ก๋วยเตี๋ยว"

        # กรองคำที่เป็นหน่วยเงินออก (LLM มักส่ง "65 บาท เบียร์" แทน "65 เครื่องดื่ม เบียร์")
        rest = [t for t in tokens[1:] if t.lower() not in self._CURRENCY_WORDS]

        if not rest:
            # เหลือแค่ตัวเลขกับ "บาท" → ไม่มีข้อมูลพอ
            category, note = "ทั่วไป", ""
        elif len(rest) == 1:
            # token เดียว: ถ้าเป็นหมวดที่รู้จัก → ใช้เป็น category, ไม่งั้น → เป็น note
            if rest[0] in self._KNOWN_CATEGORIES:
                category, note = rest[0], ""
            else:
                category, note = "ทั่วไป", rest[0]
        else:
            # 2+ tokens: ตัวแรกเป็น category, ที่เหลือเป็น note
            if rest[0] in self._KNOWN_CATEGORIES:
                category = rest[0]
                note = " ".join(rest[1:]).strip()
            else:
                # ตัวแรกไม่ใช่หมวดที่รู้จัก → ทุก token เป็น note
                category = "ทั่วไป"
                note = " ".join(rest).strip()

        expense_id = db.add_expense(
            user_id,
            amount=amount,
            category=category,
            note=self._normalize_note(note),
        )
        return f"💸 บันทึกรายจ่ายแล้ว [#{expense_id}]\n{amount:,.2f} บาท\nหมวด: {category}" + (f"\nหมายเหตุ: {note}" if note else "")

    def _list(self, user_id: str) -> str:
        expenses = db.list_expenses(user_id)
        if not expenses:
            return "💸 ยังไม่มีรายจ่ายที่บันทึกไว้"
        lines = ["💸 รายจ่ายล่าสุด:\n"]
        for i, item in enumerate(expenses, 1):
            lines.append(f"{i}. {item['expense_date']} — {item['category']} {item['amount']:,.2f} บาท {item['note']}")
        lines.append("\nลบ: /expense delete <ลำดับ>  แก้ราคา: /expense edit <ลำดับ> <ราคาใหม่>")
        return "\n".join(lines)

    def _delete(self, user_id: str, tokens: list[str]) -> str:
        if not tokens:
            return "ใช้: /expense delete <ลำดับ> เช่น /expense delete 3"
        try:
            index = int(tokens[0])
        except ValueError:
            return "❌ ระบุลำดับเป็นตัวเลข เช่น /expense delete 3"

        expenses = db.list_expenses(user_id)
        if index < 1 or index > len(expenses):
            return f"❌ ไม่พบรายจ่ายลำดับที่ {index} (มีทั้งหมด {len(expenses)} รายการ)"

        item = expenses[index - 1]
        if db.delete_expense(user_id, item["id"]):
            return f"🗑 ลบรายจ่ายแล้ว: {item['amount']:,.2f} บาท {item['category']} {item['note']}"
        return "❌ ไม่สามารถลบรายจ่ายได้"

    def _edit(self, user_id: str, tokens: list[str]) -> str:
        if len(tokens) < 2:
            return "ใช้: /expense edit <ลำดับ> <ราคาใหม่> เช่น /expense edit 3 120"
        try:
            index = int(tokens[0])
        except ValueError:
            return "❌ ระบุลำดับเป็นตัวเลข เช่น /expense edit 3 120"
        try:
            new_amount = float(tokens[1])
        except ValueError:
            return "❌ ราคาใหม่ต้องเป็นตัวเลข"
        if new_amount <= 0:
            return "❌ ราคาต้องมากกว่า 0"

        expenses = db.list_expenses(user_id)
        if index < 1 or index > len(expenses):
            return f"❌ ไม่พบรายจ่ายลำดับที่ {index} (มีทั้งหมด {len(expenses)} รายการ)"

        item = expenses[index - 1]
        old_amount = item["amount"]
        if db.update_expense(user_id, item["id"], amount=new_amount):
            return f"✏️ แก้ไขแล้ว: {item['note']}\n{old_amount:,.2f} → {new_amount:,.2f} บาท"
        return "❌ ไม่สามารถแก้ไขรายจ่ายได้"

    def _summary(self, user_id: str, period: str, category: str = "", keyword: str = "") -> str:
        today = date.today()
        if period == "today":
            start_date = end_date = today.isoformat()
        elif period == "7d":
            start_date = (today - timedelta(days=6)).isoformat()
            end_date = today.isoformat()
        else:
            start_date = today.replace(day=1).isoformat()
            end_date = today.isoformat()

        rows = db.summarize_expenses(user_id, start_date, end_date, category=category, keyword=keyword)
        if not rows:
            filter_desc = keyword or category or ""
            msg = f"💸 ไม่มีรายจ่าย '{filter_desc}' ในช่วงที่เลือก" if filter_desc else "💸 ไม่มีรายจ่ายในช่วงที่เลือก"
            return msg
        total = sum(float(item["total"]) for item in rows)
        filter_label = ""
        if keyword:
            filter_label = f" '{keyword}'"
        elif category:
            filter_label = f" หมวด {category}"
        header = f"💸 สรุปรายจ่าย{filter_label} {start_date} ถึง {end_date}\nรวม {total:,.2f} บาท\n"
        lines = [header]
        for item in rows:
            lines.append(f"• {item['category']}: {float(item['total']):,.2f} บาท ({item['count']} รายการ)")
        return "\n".join(lines)

    def _compare(self, user_id: str, period: str) -> str:
        """เปรียบเทียบรายจ่าย 2 ช่วงเวลา (เดือนนี้ vs เดือนที่แล้ว, 7 วันนี้ vs 7 วันก่อน)"""
        today = date.today()

        if period == "7d":
            # Period B (ปัจจุบัน): 7 วันล่าสุด
            end_b = today
            start_b = today - timedelta(days=6)
            # Period A (ก่อนหน้า): 7 วันก่อนหน้านั้น
            end_a = start_b - timedelta(days=1)
            start_a = end_a - timedelta(days=6)
            label_a = f"{start_a.strftime('%d/%m')}–{end_a.strftime('%d/%m')}"
            label_b = f"{start_b.strftime('%d/%m')}–{end_b.strftime('%d/%m')}"
        else:
            # Default: month — เดือนนี้ vs เดือนที่แล้ว
            # Period B (เดือนปัจจุบัน)
            start_b = today.replace(day=1)
            end_b = today
            # Period A (เดือนก่อน)
            last_month_end = start_b - timedelta(days=1)
            start_a = last_month_end.replace(day=1)
            end_a = last_month_end

            thai_months = [
                "", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
            ]
            label_a = f"{thai_months[start_a.month]} {start_a.year}"
            label_b = f"{thai_months[start_b.month]} {start_b.year}"

        rows_a = db.summarize_expenses(user_id, start_a.isoformat(), end_a.isoformat())
        rows_b = db.summarize_expenses(user_id, start_b.isoformat(), end_b.isoformat())

        if not rows_a and not rows_b:
            return "💸 ไม่มีรายจ่ายในทั้ง 2 ช่วงที่เลือก"

        # สร้าง map category → total
        map_a = {r["category"]: float(r["total"]) for r in rows_a}
        map_b = {r["category"]: float(r["total"]) for r in rows_b}
        all_cats = list(dict.fromkeys(list(map_a.keys()) + list(map_b.keys())))

        lines = [
            f"💸 เปรียบเทียบรายจ่าย",
            f"{label_a} vs {label_b}",
            "",
            f"{'หมวด':<14} {label_a:>12} {label_b:>12} {'ผลต่าง':>12}",
            "-" * 54,
        ]

        total_a = 0.0
        total_b = 0.0
        for cat in all_cats:
            val_a = map_a.get(cat, 0)
            val_b = map_b.get(cat, 0)
            diff = val_b - val_a
            total_a += val_a
            total_b += val_b
            sign = "+" if diff > 0 else ""
            lines.append(f"{cat:<14} {val_a:>12,.2f} {val_b:>12,.2f} {sign}{diff:>11,.2f}")

        total_diff = total_b - total_a
        sign = "+" if total_diff > 0 else ""
        lines.append("-" * 54)
        lines.append(f"{'รวม':<14} {total_a:>12,.2f} {total_b:>12,.2f} {sign}{total_diff:>11,.2f}")

        # สรุป
        if total_a > 0:
            pct = total_diff / total_a * 100
            sign_pct = "+" if pct > 0 else ""
            direction = "มากกว่า" if total_diff > 0 else "น้อยกว่า"
            lines.append("")
            lines.append(f"สรุป: {label_b} ใช้{direction}{label_a} {abs(total_diff):,.2f} บาท ({sign_pct}{pct:.1f}%)")

        return "\n".join(lines)

    async def _handle_photo(self, user_id: str, raw_args: str) -> str:
        """รับรูปบิล/slip จาก Telegram → ใช้ Gemini Vision วิเคราะห์ → บันทึกรายจ่ายแยกรายการ"""
        # Parse __photo:<file_id> <caption>
        parts = raw_args.split(None, 1)
        file_id = parts[0].replace("__photo:", "")
        caption = parts[1] if len(parts) > 1 else ""

        # Download image from Telegram
        from interfaces.telegram_common import download_telegram_photo
        image_bytes = download_telegram_photo(file_id)
        if not image_bytes:
            return "❌ ไม่สามารถดาวน์โหลดรูปได้ กรุณาลองส่งใหม่"

        source_hash = self._compute_receipt_source_hash(image_bytes)

        from core.callback_handler import has_pending_expense_source
        if has_pending_expense_source(user_id, self.RECEIPT_SOURCE_TYPE, source_hash):
            return "ℹ️ ใบเสร็จรูปนี้กำลังรอการยืนยันอยู่แล้ว กรุณาเลือกบันทึกจากข้อความก่อนหน้า หรือยกเลิกแล้วส่งใหม่"

        existing_rows = db.get_expenses_by_source_hash(user_id, self.RECEIPT_SOURCE_TYPE, source_hash)
        if existing_rows:
            return self._build_duplicate_receipt_message(existing_rows)

        # Use Gemini Vision to analyze the receipt/slip
        extracted = await self._extract_expense_from_image(image_bytes, caption)

        if extracted == "NO_API_KEY":
            return "❌ ยังไม่ได้ตั้งค่า Gemini API key — ไม่สามารถวิเคราะห์รูปได้\nตั้งค่าด้วย: /setkey gemini <key>\nหรือพิมพ์เอง: /expense 104 ช็อปปิ้ง Villa Market"
        if extracted == "RATE_LIMITED":
            return "⏳ ระบบ Gemini ขัดข้องชั่วคราว (quota เต็ม / timeout / overload) กรุณารอสักครู่แล้วส่งใหม่ หรือพิมพ์เอง: /expense 104 ช็อปปิ้ง Villa Market"
        if isinstance(extracted, str) and extracted.startswith("API_ERROR:"):
            error_detail = extracted.replace("API_ERROR:", "")
            return f"❌ Gemini Vision เกิดข้อผิดพลาด: {error_detail}\nลองส่งรูปใหม่ หรือพิมพ์เอง: /expense 104 ช็อปปิ้ง Villa Market"
        if not extracted:
            return "❌ ไม่สามารถอ่านข้อมูลจากรูปได้ กรุณาลองถ่ายใหม่ให้ชัดขึ้น หรือพิมพ์เอง: /expense 120 อาหาร"

        # Normalize: ถ้า Gemini คืน dict เดียว ให้ wrap เป็น list
        items = extracted if isinstance(extracted, list) else [extracted]
        items = [it for it in items if isinstance(it, dict) and it.get("amount", 0) != 0]
        if not items or not any(it["amount"] > 0 for it in items):
            return "❌ ไม่สามารถอ่านข้อมูลจากรูปได้ กรุณาลองถ่ายใหม่ให้ชัดขึ้น หรือพิมพ์เอง: /expense 120 อาหาร"

        # ดึงชื่อร้านจาก item แรก (ถ้ามี) เพื่อใส่ใน note
        store = items[0].get("store", "")

        # receipt_date อยู่บนทุก item (เท่ากันเพราะมาจากใบเสร็จเดียวกัน).
        # ถ้า Gemini ไม่เห็นวันที่ในใบเสร็จ → ใช้วันที่ส่งข้อมูล (วันนี้) แทน
        # การปล่อยว่าง เพื่อให้ทั้ง pending flow และ message ที่ส่งกลับ user
        # ใช้วันที่เดียวกันชัดเจน
        receipt_date = items[0].get("receipt_date", "") if items else ""
        if not receipt_date:
            receipt_date = date.today().isoformat()
            for it in items:
                it["receipt_date"] = receipt_date

        # คำนวณ confidence metadata ระดับบิล (graceful default = high / ไม่ใช่ลายมือ)
        overall_confidence = self._compute_overall_confidence(items)
        is_handwritten = bool(items[0].get("is_handwritten", False))
        store_confidence = items[0].get("store_confidence", "high")
        store_raw_guess = items[0].get("store_raw_guess", "")
        grand_total = items[0].get("grand_total")
        total = sum(it["amount"] for it in items)
        sum_matches = (abs(total - grand_total) < 0.5) if grand_total else True
        low_conf_items = sum(1 for it in items if it.get("confidence") == "low")
        store_provided = bool(caption.strip())

        # รายการเดียว → auto-save เฉพาะที่ปลอดภัยจริง (Hybrid):
        # confidence สูง + ไม่ใช่ลายมือ + (ยอดตรงกับบิล หรือ OCR ไม่มี grand_total ให้เทียบ);
        # นอกนั้น (ลายมือ / ยอดไม่ตรง) ให้ confirm ก่อน
        # หมายเหตุ (decision): sum_matches = True เมื่อไม่มี grand_total — ตั้งใจถือว่าปลอดภัย
        # เพราะ slip โอน/บิลรายการเดียวมักไม่มีบรรทัดยอดรวม และตัวเลข high-confidence ที่พิมพ์เชื่อถือได้
        if len(items) == 1 and overall_confidence == "high" and not is_handwritten and sum_matches:
            item = items[0]
            amount = item["amount"]
            category = item.get("category", "ทั่วไป")
            note = self._build_receipt_note(store, item.get("note", ""), caption=caption)
            if caption and not note:
                note = caption
            expense_id = db.add_expense(
                user_id,
                amount=amount,
                category=category,
                note=note,
                expense_date=receipt_date,
                source_type=self.RECEIPT_SOURCE_TYPE,
                source_hash=source_hash,
            )
            telemetry_id = db.log_ocr_attempt(
                user_id,
                is_handwritten=is_handwritten,
                overall_confidence=overall_confidence,
                total_items=1,
                low_conf_items=low_conf_items,
                store_provided=store_provided,
                sum_matches_total=sum_matches,
            )
            db.update_ocr_action(telemetry_id, "split")
            return (
                f"📸 บันทึกรายจ่ายจากรูปแล้ว\n"
                f"  [#{expense_id}] {amount:,.2f} บาท — {category}"
                + (f": {note}" if note else "")
                + f"\n  วันที่: {receipt_date}"
            )

        # หลายรายการ หรือ confidence ไม่สูง → preview + inline keyboard ให้ user ตัดสินใจเอง
        from core.callback_handler import store_pending_expense
        from tools.response import InlineKeyboardResponse

        telemetry_id = db.log_ocr_attempt(
            user_id,
            is_handwritten=is_handwritten,
            overall_confidence=overall_confidence,
            total_items=len(items),
            low_conf_items=low_conf_items,
            store_provided=store_provided,
            sum_matches_total=sum_matches,
        )
        pending_id = store_pending_expense(
            user_id,
            items,
            store,
            source_type=self.RECEIPT_SOURCE_TYPE,
            source_hash=source_hash,
            overall_confidence=overall_confidence,
            is_handwritten=is_handwritten,
            store_confidence=store_confidence,
            store_raw_guess=store_raw_guess,
            telemetry_id=telemetry_id,
        )

        # ---- Header + ร้าน + meta ----
        conf_label = self._CONF_LABEL.get(overall_confidence, "สูง")
        hw_suffix = " (ลายมือ)" if is_handwritten else ""
        lines = [f"📸 อ่านบิลแล้ว — ความมั่นใจ: {conf_label}{hw_suffix}"]
        if store and store != "?":
            lines.append(f"ร้าน: {store}")
        elif store_raw_guess:
            lines.append(f'ร้าน: ? [เดา: "{store_raw_guess}"]')
        lines.append(f"วันที่: {receipt_date} | รวม {total:,.2f} บาท")
        lines.append("")
        lines.append(f"รายการ {len(items)} รายการ:")

        # ---- บรรทัดรายการ พร้อมไอคอน confidence ----
        for idx, item in enumerate(items, 1):
            icon = self._CONF_ICON.get(item.get("confidence", "high"), "[v]")
            amount = item["amount"]
            category = item.get("category", "ทั่วไป")
            note = item.get("note", "") or "?"
            line = f"{idx}. {icon} {note} — {amount:,.2f} ({category})"
            raw_guess = item.get("raw_guess", "")
            if item.get("confidence") == "low" and raw_guess:
                line += f' [เดา: "{raw_guess}"]'
            lines.append(line)

        # ---- หมายเหตุยอดรวม ----
        if grand_total:
            lines.append("")
            if sum_matches:
                lines.append(f"รวมรายการ {total:,.2f} — ตรงกับยอดในบิล")
            else:
                lines.append(f"⚠️ ยอดรวมรายการ {total:,.2f} ไม่ตรงกับยอดในบิล ({grand_total:,.2f})")

        lines.append("")
        lines.append("เลือกวิธีบันทึก:")
        preview_text = "\n".join(lines)

        # ---- ปุ่มตาม confidence (Option C) ----
        if overall_confidence == "high" and len(items) == 1:
            # high แต่ไม่เข้าเงื่อนไข auto-save (ลายมือ/ยอดไม่ตรง) → confirm ปุ่มเดี่ยว
            buttons = [
                [
                    {"text": "✅ บันทึก", "callback_data": f"exp_split:{pending_id}"},
                    {"text": "✏️ แก้รายการ", "callback_data": f"exp_edit:{pending_id}"},
                ],
                [{"text": "❌ ยกเลิก", "callback_data": f"exp_cancel:{pending_id}"}],
            ]
        elif overall_confidence == "high":
            buttons = [
                [
                    {"text": f"📋 แยก {len(items)} รายการ", "callback_data": f"exp_split:{pending_id}"},
                    {"text": "📦 รวม 1 รายการ", "callback_data": f"exp_combine:{pending_id}"},
                ],
                [
                    {"text": "✏️ แก้รายการ", "callback_data": f"exp_edit:{pending_id}"},
                    {"text": "❌ ยกเลิก", "callback_data": f"exp_cancel:{pending_id}"},
                ],
            ]
        else:
            buttons = [
                [{"text": "✏️ แก้รายการ", "callback_data": f"exp_edit:{pending_id}"}],
                [
                    {"text": "⌨️ พิมพ์เอง", "callback_data": f"exp_type_manually:{pending_id}"},
                    {"text": "❌ ยกเลิก", "callback_data": f"exp_cancel:{pending_id}"},
                ],
            ]

        return InlineKeyboardResponse(
            text=preview_text,
            buttons=buttons,
            memory_text=f"📸 อ่านจากรูป {len(items)} รายการ รวม {total:,.2f} บาท ความมั่นใจ {conf_label} (รอ user เลือก)",
        )

    async def _extract_expense_from_image(self, image_bytes: bytes, hint: str = "") -> list | str | None:
        """ใช้ Gemini Vision วิเคราะห์รูปบิล/slip → return list[dict], error string, หรือ None"""
        from core.config import GEMINI_API_KEY, GEMINI_MODEL_CHEAP, GEMINI_MODEL_MID

        if not GEMINI_API_KEY:
            log.warning("Gemini API key not configured, cannot analyze receipt image")
            return "NO_API_KEY"

        try:
            from google import genai
            from google.genai import types as genai_types

            client = genai.Client(api_key=GEMINI_API_KEY, http_options={"timeout": 60000})

            user_hint_block = f"ข้อมูลเพิ่มเติมจากผู้ใช้: {hint}" if hint else ""
            prompt = load_prompt(
                "internal/expense_vision_extract.md",
                user_hint=user_hint_block,
            )

            image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            text_part = genai_types.Part.from_text(text=prompt)
            contents = [genai_types.Content(role="user", parts=[image_part, text_part])]

            # Try cheap model first; on transient failures (429 quota, 5xx server-side
            # timeouts/overload) fall back to the mid model. Hard ClientErrors (400/401)
            # raise immediately so we don't burn quota on the bigger model for problems
            # the request itself can't solve. Models come from .env so per-model quotas
            # can be tuned without code changes.
            models_to_try = [GEMINI_MODEL_CHEAP]
            if GEMINI_MODEL_MID and GEMINI_MODEL_MID != GEMINI_MODEL_CHEAP:
                models_to_try.append(GEMINI_MODEL_MID)

            resp = None
            last_transient = None
            for idx, model in enumerate(models_to_try):
                try:
                    resp = await client.aio.models.generate_content(
                        model=model,
                        contents=contents,
                    )
                    if idx > 0:
                        log.info("Gemini Vision succeeded on fallback model %s after transient failure", model)
                    break
                except genai_errors.ClientError as e:
                    if e.code == 429:
                        last_transient = e
                        log.warning("Gemini Vision %s rate-limited (429), trying next model", model)
                        continue
                    raise
                except genai_errors.ServerError as e:
                    # 5xx — Gemini-side timeout/overload/internal. Worth trying the other model.
                    last_transient = e
                    log.warning("Gemini Vision %s server error (%s), trying next model", model, getattr(e, "code", "?"))
                    continue

            if resp is None:
                log.error("All Gemini models failed transiently for receipt image: %s", last_transient)
                return "RATE_LIMITED"

            if not resp.candidates or not resp.candidates[0].content:
                log.warning("Gemini Vision returned no candidates for receipt image")
                return None

            response_text = ""
            for part in resp.candidates[0].content.parts or []:
                if part.text:
                    response_text += part.text

            response_text = response_text.strip()
            log.info("Gemini Vision response received for receipt image: text_len=%s", len(response_text))

            if not response_text or response_text == "null":
                return None

            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if not json_match:
                # Try matching a bare array [...]
                array_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                if array_match:
                    data = json.loads(array_match.group())
                    if isinstance(data, list):
                        return [it for it in (self._normalize_item(d) for d in data if isinstance(d, dict)) if it]
                log.warning("Gemini Vision response has no JSON payload for receipt image: text_len=%s", len(response_text))
                return None

            data = json.loads(json_match.group())

            # Format: {"store": "...", "subtotal": ..., "grand_total": ..., "items": [...]}
            if "items" in data and isinstance(data["items"], list):
                store = data.get("store", "")
                receipt_date = self._normalize_receipt_date(data.get("receipt_date"))
                # Bill-level confidence metadata (Phase A) — attach to each item
                # (เหมือน store/receipt_date) เพื่อให้ผ่าน discount/ratio transforms ได้
                is_handwritten = bool(data.get("is_handwritten", False))
                store_confidence = self._normalize_confidence(data.get("store_confidence"))
                store_raw_guess = (data.get("store_raw_guess") or "").strip()
                grand_total = self._safe_grand_total(data.get("grand_total"))
                items = []
                for it in data["items"]:
                    if isinstance(it, dict):
                        normalized = self._normalize_item(it)
                        if normalized:
                            normalized["store"] = store
                            normalized["receipt_date"] = receipt_date
                            normalized["is_handwritten"] = is_handwritten
                            normalized["store_confidence"] = store_confidence
                            normalized["store_raw_guess"] = store_raw_guess
                            normalized["grand_total"] = grand_total
                            items.append(normalized)
                if not items:
                    return None

                # Adjust for service charge / VAT: distribute proportionally
                items = self._apply_grand_total_ratio(items, data)
                return items

            # Fallback: single item {"amount": ..., "category": ..., "note": ...}
            normalized = self._normalize_item(data)
            if normalized:
                normalized["receipt_date"] = self._normalize_receipt_date(data.get("receipt_date"))
                return [normalized]
            return None

        except Exception as e:
            log.error("Failed to extract expense from image: %s", e, exc_info=True)
            return f"API_ERROR:{e}"

    @staticmethod
    def _dedup_by_grand_total(items: list[dict], grand_total: float) -> list[dict]:
        """ถ้า items รวมมากกว่า grand_total → ลองตัดรายการซ้ำ (ราคาเท่ากันกับตัวก่อนหน้า) ทีละตัวจนยอดตรง"""
        if grand_total <= 0:
            return items

        changed = True
        while changed:
            changed = False
            items_sum = sum(it["amount"] for it in items)
            diff = items_sum - grand_total
            if diff < 0.5:
                break
            # หา candidate: รายการบวกที่ amount เท่ากับรายการก่อนหน้า แล้วตัดออกทำให้ diff ลดลง
            for i in range(len(items) - 1, 0, -1):
                if items[i]["amount"] > 0 and items[i]["amount"] == items[i - 1]["amount"]:
                    if abs(diff - items[i]["amount"]) < 0.5 or items[i]["amount"] <= diff:
                        items = items[:i] + items[i + 1:]
                        changed = True
                        break
        return items

    # Note "โปรโมชั่นราคาพิเศษ Xบ" / "ราคาพิเศษ X บาท" ที่ระบุ "ราคาหลังลด"
    # — ใช้สำหรับจับคู่ discount กับ item ที่ถูกต้อง (CJ More, 7-11)
    _SPECIAL_PRICE_PATTERN = re.compile(
        r"ราคาพิเศษ\s*([\d,]+(?:\.\d+)?)\s*(?:บ|บาท)",
    )

    @staticmethod
    def _extract_special_price(note: str) -> float | None:
        """ดึงราคา 'หลังลด' จาก note เช่น 'โปรโมชั่นราคาพิเศษ 102บ' → 102.0"""
        if not note:
            return None
        m = ExpenseTool._SPECIAL_PRICE_PATTERN.search(note)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _net_discounts(items: list[dict], grand_total: float = 0) -> list[dict]:
        """ตัดรายการซ้ำ แล้วหักส่วนลด (amount ติดลบ) เข้า item ที่ถูกต้อง.

        ใช้กลยุทธ์ 2 ชั้น:
        1. ถ้า note ของ discount มี 'ราคาพิเศษ X บ' → จับคู่กับ item ที่
           ราคาเดิม + discount ≈ X (รูปแบบ CJ More/7-11 ที่รวมส่วนลดท้ายใบ)
        2. ไม่ match → หักเข้า item ก่อนหน้า (รูปแบบ discount ติดทันทีหลัง item)
        """
        items = ExpenseTool._dedup_by_grand_total(items, grand_total)
        result: list[dict] = []
        for item in items:
            if item["amount"] >= 0:
                result.append(item)
                continue

            # discount: ลอง match จาก 'ราคาพิเศษ X บ' ก่อน
            target = ExpenseTool._extract_special_price(item.get("note", ""))
            matched_idx = None
            if target is not None:
                for i in range(len(result) - 1, -1, -1):
                    candidate = result[i]
                    if candidate["amount"] > 0 and abs((candidate["amount"] + item["amount"]) - target) < 0.5:
                        matched_idx = i
                        break

            if matched_idx is not None:
                result[matched_idx] = {
                    **result[matched_idx],
                    "amount": round(result[matched_idx]["amount"] + item["amount"], 2),
                }
            elif result and result[-1]["amount"] > 0:
                # Fallback: discount ติดหลัง item ใน column เดียวกัน
                result[-1] = {**result[-1], "amount": round(result[-1]["amount"] + item["amount"], 2)}
            else:
                result.append(item)
        # กรองรายการที่ amount <= 0 หลังหักส่วนลดออก
        return [it for it in result if it["amount"] > 0]

    @staticmethod
    def _apply_grand_total_ratio(items: list[dict], data: dict) -> list[dict]:
        """Net ส่วนลดเข้ารายการก่อนหน้า แล้ว reconcile กับ grand_total สำหรับ SC/VAT"""
        try:
            grand_total = float(data.get("grand_total") or 0)
            subtotal = float(data.get("subtotal") or 0)
        except (ValueError, TypeError):
            grand_total = 0
            subtotal = 0

        # ขั้น 1: ตัดรายการซ้ำ + หักส่วนลดเข้ารายการก่อนหน้า
        items = ExpenseTool._net_discounts(items, grand_total)
        if not items:
            return []

        if grand_total <= 0:
            return items

        # ขั้น 2: ปรับสัดส่วน SC/VAT เฉพาะเมื่อมี subtotal ที่ต่างจาก grand_total
        # (เช่น ร้านอาหารที่บวก SC 10% + VAT 7%)
        # ถ้าไม่มี subtotal หรือ subtotal == grand_total → ไม่ปรับ ratio
        if subtotal <= 0 or abs(subtotal - grand_total) < 0.5:
            return items

        ratio = grand_total / subtotal
        items_sum = sum(it["amount"] for it in items)

        # ถ้ายอดรวม items ตรงกับ grand_total อยู่แล้ว → ไม่ต้องปรับ
        if abs(items_sum - grand_total) < 0.5:
            return items

        adjusted = []
        running_total = 0.0
        for i, item in enumerate(items):
            if i < len(items) - 1:
                new_amount = round(item["amount"] * ratio, 2)
                running_total += new_amount
            else:
                new_amount = round(grand_total - running_total, 2)
            adjusted.append({**item, "amount": new_amount})
        return adjusted

    @staticmethod
    def _normalize_receipt_date(value) -> str:
        """Validate ค่า receipt_date จาก Gemini → คืน YYYY-MM-DD หรือ "" ถ้าไม่ถูกต้อง.

        Gemini ถูก prompt ให้คืนเป็น YYYY-MM-DD ค.ศ. แล้ว — ตรงนี้แค่ guard
        ป้องกัน hallucination/format แปลก (เช่น พ.ศ.หลุดมา) ด้วย date.fromisoformat.
        """
        if not value or not isinstance(value, str):
            return ""
        candidate = value.strip()
        if not candidate or candidate.lower() == "null":
            return ""
        try:
            parsed = date.fromisoformat(candidate)
        except ValueError:
            log.warning("Invalid receipt_date from Gemini: %r — falling back to today", value)
            return ""
        # Sanity check: ปี ค.ศ. ปกติอยู่ในช่วง 2000-2100 — กัน Gemini ส่ง พ.ศ. หลุดมา
        if parsed.year < 2000 or parsed.year > 2100:
            log.warning("receipt_date year out of range: %s — treating as invalid", parsed.year)
            return ""
        return parsed.isoformat()

    @staticmethod
    def _normalize_confidence(value) -> str:
        """Clamp confidence จาก Gemini → 'high'|'medium'|'low' (default high ถ้าไม่ถูกต้อง)"""
        if isinstance(value, str) and value.strip().lower() in ("high", "medium", "low"):
            return value.strip().lower()
        return "high"

    @staticmethod
    def _compute_overall_confidence(items: list[dict]) -> str:
        """สรุป confidence รวมทั้งบิลจาก per-item confidence (deterministic ไม่พึ่ง Gemini)"""
        n = len(items)
        if n == 0:
            return "high"
        low = sum(1 for it in items if it.get("confidence") == "low")
        med = sum(1 for it in items if it.get("confidence") == "medium")
        if low / n > 0.30:
            return "low"
        if (low + med) / n > 0.50:
            return "medium"
        return "high"

    @staticmethod
    def _safe_grand_total(value) -> float | None:
        """แปลง grand_total → float ที่ > 0 หรือ None"""
        try:
            gt = float(value)
        except (TypeError, ValueError):
            return None
        return gt if gt > 0 else None

    @staticmethod
    def _normalize_item(data: dict) -> dict | None:
        """Normalize a single expense item dict → {amount, category, note, confidence, raw_guess} or None"""
        try:
            amount = float(data.get("amount", 0))
        except (ValueError, TypeError):
            return None
        if amount == 0:
            return None
        return {
            "amount": amount,
            "category": data.get("category", "ทั่วไป"),
            "note": data.get("note", data.get("name", "")),
            "confidence": ExpenseTool._normalize_confidence(data.get("confidence")),
            "raw_guess": (data.get("raw_guess") or "").strip(),
        }

    def _usage(self) -> str:
        return (
            "ใช้: /expense 120 อาหาร ก๋วยเตี๋ยว\n"
            "/expense list — ดูรายจ่ายล่าสุด\n"
            "/expense delete <ลำดับ> — ลบรายจ่าย\n"
            "/expense edit <ลำดับ> <ราคาใหม่> — แก้ราคา\n"
            "/expense summary month — สรุปรายจ่ายเดือนนี้\n"
            "📸 หรือถ่ายรูปบิล/slip ส่งมา จะบันทึกอัตโนมัติ"
        )

    @staticmethod
    def _normalize_note(note: str) -> str:
        return re.sub(r"\s+", " ", (note or "").strip())

    def _build_receipt_note(self, store: str, note: str, *, caption: str = "") -> str:
        normalized_store = self._normalize_note(store)
        normalized_note = self._normalize_note(note)
        normalized_caption = self._normalize_note(caption)

        if normalized_store and normalized_note:
            combined = f"{normalized_store} — {normalized_note}"
        else:
            combined = normalized_store or normalized_note

        if normalized_caption and normalized_caption not in combined:
            combined = f"{combined} — {normalized_caption}" if combined else normalized_caption
        return combined

    @staticmethod
    def _compute_receipt_source_hash(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()

    def _build_duplicate_receipt_message(self, existing_rows: list[dict]) -> str:
        first_row = existing_rows[0]
        ids = ", ".join(f"#{row['id']}" for row in existing_rows[:5])
        note = self._normalize_note(first_row.get("note", ""))
        lines = ["ℹ️ ใบเสร็จรูปนี้เคยถูกบันทึกแล้ว จึงไม่บันทึกซ้ำ"]
        lines.append(f"- พบ {len(existing_rows)} รายการเดิม: {ids}")
        lines.append(f"- วันที่รายการ: {first_row['expense_date']}")
        if note:
            lines.append(f"- ตัวอย่างหมายเหตุ: {note}")
        lines.append("หากต้องการบันทึกแยกจริง ให้พิมพ์ /expense เองแทนการอัปโหลดรูปเดิมซ้ำ")
        return "\n".join(lines)

