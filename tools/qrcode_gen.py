"""QR Code generator tool."""

import io
from importlib import import_module

from core import db
from core.logger import get_logger
from tools.base import BaseTool
from tools.response import MediaResponse

log = get_logger(__name__)


class QRCodeGenTool(BaseTool):
    name = "qrcode_gen"
    description = "สร้าง QR Code จากข้อความหรือลิงก์ แล้วส่งกลับเป็นรูปภาพ"
    commands = ["/qr"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs):
        payload = (args or "").strip()
        if not payload:
            return "❌ ใช้: /qr <ข้อความหรือ URL>"

        try:
            segno = import_module("segno")

            qr = segno.make(payload, error="M")
            buf = io.BytesIO()
            qr.save(buf, kind="png", scale=8, border=2)
            image_bytes = buf.getvalue()

            result = MediaResponse(
                text=f"🔳 QR Code สำหรับ: {payload}",
                image=image_bytes,
                image_caption="🔳 QR Code",
            )
            db.log_tool_usage(
                user_id,
                self.name,
                status="success",
                **db.make_log_field("input", payload, kind="qr_payload"),
                **db.make_log_field("output", "png", kind="media_image", size=len(image_bytes)),
            )
            return result
        except (ImportError, ValueError, RuntimeError) as e:
            log.error("QR tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id,
                self.name,
                status="failed",
                **db.make_log_field("input", payload, kind="qr_payload"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ สร้าง QR Code ไม่สำเร็จ: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "สร้าง QR Code จากข้อความหรือ URL ทั่วไป (ไม่ใช่ PromptPay). "
                "ถ้า user ต้องการ QR รับเงิน/พร้อมเพย์ ให้ใช้ promptpay แทน. "
                "เช่น '/qr https://example.com', '/qr hello world', '/qr WiFi:mynetwork'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string", "description": "ข้อความหรือ URL ที่จะนำไปสร้าง QR Code"}
                },
                "required": ["args"],
            },
        }