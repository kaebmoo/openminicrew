"""PromptPay QR tool — รองรับทั้งเบอร์มือถือและเลขบัตรประชาชน."""

import io
import re
from importlib import import_module

from core import db
from core.user_manager import get_user_by_id
from core.logger import get_logger
from tools.base import BaseTool
from tools.response import MediaResponse

log = get_logger(__name__)

# --- EMVCo sub-tag IDs ภายใน Tag 29 (PromptPay merchant info) ---
_SUBTAG_PHONE = "01"       # เบอร์มือถือ format 0066XXXXXXXXX
_SUBTAG_NATIONAL_ID = "02"  # เลขบัตรประชาชน/Tax ID 13 หลัก
_SUBTAG_EWALLET = "03"     # eWallet ID 15+ หลัก

# ประเภท ID สำหรับใช้ภายใน
ID_TYPE_PHONE = "phone"
ID_TYPE_NATIONAL_ID = "national_id"


# =====================================================================
# Low-level helpers
# =====================================================================

def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def _crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for char in data.encode("ascii"):
        crc ^= char << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


# =====================================================================
# Thai National ID validation
# =====================================================================

def _verify_thai_id_checksum(digits: str) -> bool:
    """ตรวจ checksum เลขบัตรประชาชน 13 หลัก (weighted sum mod 11).

    Algorithm:
        sum = d[0]*13 + d[1]*12 + ... + d[11]*2
        check_digit = (11 - sum%11) % 10
        ต้องตรงกับหลักที่ 13
    """
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(digits[i]) * (13 - i) for i in range(12))
    check = (11 - (total % 11)) % 10
    return check == int(digits[12])


def _validate_national_id(id_str: str) -> str:
    """Validate เลขบัตรประชาชนไทย — return 13 หลักที่ clean แล้ว.

    ตรวจ 3 ระดับ:
    1. ความยาว 13 หลัก (หลัง strip non-digits)
    2. หลักแรกต้องเป็น 1-8 (ประเภทบุคคลตามทะเบียนราษฎร์)
    3. Checksum ถูกต้อง (weighted sum mod 11)
    """
    cleaned = re.sub(r"[^0-9]", "", id_str)
    if len(cleaned) != 13:
        raise ValueError(f"เลขบัตรประชาชนต้อง 13 หลัก (ได้ {len(cleaned)} หลัก)")
    if cleaned[0] not in "12345678":
        raise ValueError(
            f"หลักแรกของเลขบัตรต้องเป็น 1-8 (ได้ '{cleaned[0]}')"
        )
    if not _verify_thai_id_checksum(cleaned):
        raise ValueError("เลขบัตรประชาชนไม่ผ่าน checksum — กรุณาตรวจสอบเลขอีกครั้ง")
    return cleaned


# =====================================================================
# Phone validation (เดิม — แก้ indentation bug)
# =====================================================================

def _normalize_phone(phone_number: str) -> str:
    """Validate เบอร์มือถือไทย — return format 0066XXXXXXXXX (13 chars)."""
    cleaned = re.sub(r"[^0-9+]", "", phone_number)
    try:
        import phonenumbers
        from phonenumbers import NumberParseException, PhoneNumberType

        parsed = (
            phonenumbers.parse(cleaned, "TH")
            if not cleaned.startswith("+")
            else phonenumbers.parse(cleaned)
        )
        if not phonenumbers.is_valid_number(parsed) or parsed.country_code != 66:
            raise ValueError("ไม่ใช่เบอร์ไทยที่ถูกต้อง")
        if phonenumbers.number_type(parsed) != PhoneNumberType.MOBILE:
            raise ValueError("PromptPay ต้องใช้เบอร์มือถือ")
        return "0066" + phonenumbers.national_significant_number(parsed)
    except ImportError as exc:
        # fallback ถ้าไม่มี phonenumbers library
        if cleaned.startswith("+66") and len(cleaned) == 12:
            cleaned = "0" + cleaned[3:]
        if not re.match(r"^0[689]\d{8}$", cleaned):
            raise ValueError("รูปแบบเบอร์ไม่ถูกต้อง") from exc
        return "0066" + cleaned[1:]
    except phonenumbers.NumberParseException as e:
        raise ValueError(f"parse เบอร์ไม่สำเร็จ: {e}") from e


# =====================================================================
# Unified ID detection & resolution
# =====================================================================

def _looks_like_national_id(raw: str) -> bool:
    """Quick check ว่า input น่าจะเป็นเลขบัตรประชาชน (ก่อน full validation).

    ตรวจ: 13 หลัก, หลักแรก 1-8, ผ่าน checksum.
    ใช้สำหรับ token parsing เท่านั้น — ไม่ raise error.
    """
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) != 13:
        return False
    if digits[0] not in "12345678":
        return False
    return _verify_thai_id_checksum(digits)


def _looks_like_phone(raw: str) -> bool:
    """Quick check ว่า input น่าจะเป็นเบอร์โทร."""
    cleaned = re.sub(r"[^0-9+]", "", raw)
    if cleaned.startswith("+"):
        return True
    if cleaned.startswith("0") and len(cleaned) >= 9:
        return True
    return False


def _resolve_promptpay_input(input_str: str) -> tuple[str, str]:
    """ตรวจว่า input เป็นเบอร์โทรหรือเลขบัตร แล้ว normalize.

    Returns:
        (promptpay_id, id_type) โดย:
        - phone:       promptpay_id = "0066XXXXXXXXX", id_type = "phone"
        - national_id: promptpay_id = "XXXXXXXXXXXXX", id_type = "national_id"

    Raises:
        ValueError: ถ้า validate ไม่ผ่าน
    """
    # ลอง national ID ก่อน — เพราะ 13 หลักที่ผ่าน checksum มีโอกาสเป็นอย่างอื่นต่ำมาก
    digits_only = re.sub(r"[^0-9]", "", input_str)
    if len(digits_only) == 13 and not input_str.strip().startswith("+"):
        # ลอง validate เป็น national ID
        try:
            valid_id = _validate_national_id(input_str)
            return valid_id, ID_TYPE_NATIONAL_ID
        except ValueError:
            pass  # ไม่ใช่ national ID ที่ถูกต้อง — ลองเป็นเบอร์โทร

    # ลอง phone
    promptpay_id = _normalize_phone(input_str)
    return promptpay_id, ID_TYPE_PHONE


# =====================================================================
# QR Payload generation
# =====================================================================

def _build_promptpay_payload(
    promptpay_id: str,
    id_type: str = ID_TYPE_PHONE,
    amount: float | None = None,
) -> str:
    """สร้าง EMVCo TLV payload สำหรับ PromptPay.

    Sub-tag ใน merchant info (tag 29) แตกต่างตามประเภท ID:
    - phone:       sub-tag "01"
    - national_id: sub-tag "02"
    """
    if id_type == ID_TYPE_NATIONAL_ID:
        subtag = _SUBTAG_NATIONAL_ID
    else:
        subtag = _SUBTAG_PHONE

    merchant_info = _tlv("00", "A000000677010111") + _tlv(subtag, promptpay_id)

    payload = ""
    payload += _tlv("00", "01")                                  # Payload format
    payload += _tlv("01", "12" if amount is not None else "11")  # Static/Dynamic
    payload += _tlv("29", merchant_info)                         # PromptPay merchant
    payload += _tlv("58", "TH")                                  # Country
    payload += _tlv("53", "764")                                 # Currency THB
    if amount is not None:
        payload += _tlv("54", f"{amount:.2f}")
    payload += _tlv("59", "PromptPay")                           # Merchant name
    payload += _tlv("60", "Bangkok")                             # Merchant city
    payload += "6304"
    return payload + _crc16_ccitt(payload)


# =====================================================================
# Tool class
# =====================================================================

class PromptPayTool(BaseTool):
    name = "promptpay"
    description = (
        "สร้าง PromptPay QR จากเบอร์มือถือไทยหรือเลขบัตรประชาชน"
        " หรือใช้ข้อมูลที่บันทึกไว้"
    )
    commands = ["/pay", "/promptpay"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs):
        tokens = (args or "").strip().split()
        amount = None
        promptpay_input = None  # เบอร์โทร หรือ เลขบัตร

        # --- Token parsing: แยก amount vs PromptPay ID ---
        for token in tokens:
            candidate = token.replace(",", "")

            # ตรวจ national ID ก่อน (13 หลักที่ผ่าน checksum)
            if _looks_like_national_id(candidate):
                promptpay_input = token
            # ตรวจ phone (ขึ้นต้น 0 หรือ +)
            elif _looks_like_phone(candidate):
                promptpay_input = token
            # ที่เหลือลองเป็นจำนวนเงิน
            elif re.match(r"^\d+(\.\d{1,2})?$", candidate) and amount is None:
                amount = float(candidate)
            else:
                # fallback — ให้ validation จัดการ
                promptpay_input = token

        # ถ้าไม่ได้ระบุ ID → ใช้ข้อมูลที่บันทึกไว้
        if not promptpay_input:
            user = get_user_by_id(user_id) or {}
            # ลอง national_id ก่อน, แล้ว phone_number
            promptpay_input = (
                user.get("national_id", "")
                or user.get("phone_number", "")
            )

        if not promptpay_input:
            return (
                "ไม่พบเบอร์โทรหรือเลขบัตรประชาชน\n"
                "ใช้ /pay <จำนวนเงิน> <เบอร์หรือเลขบัตร>\n"
                "หรือบันทึกเบอร์ด้วย /setphone หรือเลขบัตรด้วย /setid ก่อน"
            )

        try:
            segno = import_module("segno")

            promptpay_id, id_type = _resolve_promptpay_input(promptpay_input)
            payload = _build_promptpay_payload(promptpay_id, id_type, amount)
            qr = segno.make(payload, error="M")
            buf = io.BytesIO()
            qr.save(buf, kind="png", scale=8, border=2)

            amount_text = (
                f"{amount:,.2f} บาท" if amount is not None
                else "ไม่ระบุจำนวนเงิน"
            )
            if id_type == ID_TYPE_NATIONAL_ID:
                # mask เลขบัตร เหลือ 4 หลักท้าย
                masked = "X" * 9 + promptpay_input[-4:]
                id_label = f"เลขบัตร: {masked}"
            else:
                id_label = f"เบอร์: {promptpay_input}"

            result = MediaResponse(
                text=f"PromptPay QR\n{id_label}\nจำนวนเงิน: {amount_text}",
                image=buf.getvalue(),
                image_caption=f"PromptPay {amount_text}",
            )
            db.log_tool_usage(
                user_id, self.name,
                input_summary=(args or promptpay_input)[:100],
                output_summary=f"PromptPay QR ({id_type})",
                status="success",
            )
            return result

        except (ImportError, ValueError, RuntimeError) as e:
            log.error("PromptPay tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id, self.name,
                input_summary=(args or "")[:100],
                status="failed", error_message=str(e),
            )
            return f"สร้าง PromptPay QR ไม่สำเร็จ: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "สร้าง PromptPay QR จากเบอร์มือถือไทยหรือเลขบัตรประชาชน"
                " เช่น '/pay 120 0812345678' หรือ '/pay 500 1234567890121'"
                " หรือ '/promptpay 0812345678'"
                " ถ้าไม่ระบุจะใช้ข้อมูลจาก /setphone หรือ /setid"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "จำนวนเงินและ/หรือเบอร์โทร/เลขบัตรประชาชน"
                            " เช่น '120 0812345678' หรือ '500 1-2345-67890-12-1'"
                        ),
                    }
                },
                "required": [],
            },
        }
