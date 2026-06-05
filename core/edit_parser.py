"""Free-text edit intent parser (Phase A)

แปลงข้อความแก้รายการของ user → operations JSON ผ่าน LLM (Gemini preferred, มี fallback)
ทุก failure path คืน dict ที่ปลอดภัย (operations ว่าง) ไม่ raise — ให้ caller fallback ไป guided
"""

import json
import re

from core.llm import llm_router
from core.logger import get_logger
from core.prompt_loader import load_prompt

log = get_logger(__name__)

# หมวดหมู่ที่อนุญาต — ตรงกับ _KNOWN_CATEGORIES ใน tools/expense.py (Thai labels)
_KNOWN_CATEGORIES = {
    "อาหาร", "เครื่องดื่ม", "เดินทาง", "ช็อปปิ้ง", "ของใช้",
    "สาธารณูปโภค", "สุขภาพ", "บันเทิง", "การศึกษา", "โอนเงิน", "ทั่วไป",
}

_FAIL = {"operations": [], "confidence": "low"}


def _extract_json(text: str) -> dict | None:
    """ดึง JSON object ก้อนแรกจากข้อความ (รองรับ markdown code block)"""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _validate_operations(raw_ops, n: int) -> list[dict]:
    """กรอง operations ที่ไม่ถูกต้องทิ้ง (line นอกช่วง, amount <= 0, category ไม่รู้จัก)"""
    valid: list[dict] = []
    if not isinstance(raw_ops, list):
        return valid

    for op in raw_ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if kind not in ("edit", "delete", "add"):
            continue

        cleaned: dict = {"op": kind}

        if kind in ("edit", "delete"):
            line = op.get("line")
            if not isinstance(line, int) or not (1 <= line <= n):
                continue
            cleaned["line"] = line

        note = op.get("note")
        if isinstance(note, str) and note.strip():
            cleaned["note"] = note.strip()

        if op.get("amount") is not None:
            try:
                amt = float(op["amount"])
            except (TypeError, ValueError):
                amt = None
            if amt is not None and amt > 0:
                cleaned["amount"] = amt

        cat = op.get("category")
        if isinstance(cat, str) and cat.strip() in _KNOWN_CATEGORIES:
            cleaned["category"] = cat.strip()

        if kind == "add":
            # add ต้องมี amount > 0 ถึงจะ valid
            if "amount" not in cleaned:
                continue
            cleaned.setdefault("note", "")
            cleaned.setdefault("category", "ทั่วไป")
        elif kind == "edit":
            # edit ต้องเปลี่ยนอย่างน้อยหนึ่งอย่าง
            if not any(k in cleaned for k in ("note", "amount", "category")):
                continue

        valid.append(cleaned)

    return valid


async def parse_edit_intent(items: list[dict], user_message: str, user_id: str = None) -> dict:
    """Parse คำสั่งแก้ free-text → {"operations": [...], "confidence": "high"|"low"}

    ไม่ raise — ทุก error path คืน operations ว่าง + confidence low
    """
    n = len(items)
    bill_lines = [
        {
            "line": i,
            "note": it.get("note", ""),
            "amount": it.get("amount"),
            "category": it.get("category", ""),
        }
        for i, it in enumerate(items, 1)
    ]
    bill_state = json.dumps(bill_lines, ensure_ascii=False)

    try:
        prompt = load_prompt(
            "internal/expense_edit_parse.md",
            bill_state=bill_state,
            user_message=user_message,
        )
    except Exception as e:  # prompt missing / template error
        log.error("edit_parse prompt load failed: %s", e)
        return {**_FAIL, "error": "prompt_load_failed"}

    try:
        resp = await llm_router.chat(
            messages=[{"role": "user", "content": prompt}],
            provider="gemini",
            tier="cheap",
            user_id=user_id,
        )
    except Exception as e:
        log.warning("edit_parse LLM call failed: %s", e)
        return {**_FAIL, "error": "llm_failed"}

    data = _extract_json((resp or {}).get("content", ""))
    if data is None:
        log.info("edit_parse: no JSON in LLM response")
        return {**_FAIL, "error": "parse_failed"}

    confidence = data.get("confidence")
    if confidence not in ("high", "low"):
        confidence = "low"

    operations = _validate_operations(data.get("operations"), n)
    return {"operations": operations, "confidence": confidence}
