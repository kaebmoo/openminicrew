"""Dictionary tool — EN↔TH word lookup powered by LLM knowledge."""

from core import db
from core.llm import llm_router
from core.user_manager import get_user_by_id, get_preference
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)


class DictionaryTool(BaseTool):
    name = "dictionary"
    description = "ค้นหาคำแปลและความหมายของคำศัพท์ EN↔TH"
    commands = ["/dict", "/define"]
    preferred_tier = "cheap"

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        word = (args or "").strip()
        if not word:
            return "กรุณาระบุคำศัพท์ เช่น /dict managerial"

        try:
            user = get_user_by_id(user_id) or {}
            provider = get_preference(user, "default_llm")

            prompt = (
                f"ให้ข้อมูลคำศัพท์ '{word}':\n"
                "- คำแปล EN↔TH\n"
                "- ประเภทคำ (noun/verb/adj/adv ฯลฯ)\n"
                "- ตัวอย่างประโยค 1-2 ประโยค\n"
                "ตอบกระชับ เป็นภาษาไทย"
            )

            resp = await llm_router.chat(
                messages=[{"role": "user", "content": prompt}],
                provider=provider,
                tier=self.preferred_tier,
            )

            result = resp.get("content", "").strip()
            if not result:
                return f"❌ ไม่สามารถค้นหาคำว่า '{word}' ได้"

            db.log_tool_usage(
                user_id,
                self.name,
                llm_model=resp.get("model"),
                token_used=resp.get("token_used", 0),
                status="success",
                **db.make_log_field("input", word, kind="dictionary_query"),
            )
            return f"📖 **{word}**\n\n{result}"
        except Exception as e:
            log.error("Dictionary tool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id,
                self.name,
                status="failed",
                **db.make_log_field("input", word, kind="dictionary_query"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ ค้นหาคำศัพท์ไม่สำเร็จ: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ค้นหาคำแปลและความหมายของคำศัพท์ภาษาอังกฤษ-ไทย (EN↔TH). "
                "ใช้เมื่อ user ถาม 'X แปลว่า', 'ความหมายของ X', 'คำว่า X แปลเป็นอังกฤษ', "
                "'define X', 'X meaning', 'X คือคำอะไร'. "
                "ไม่ใช่สำหรับค้นหาข้อมูลทั่วไปบนเว็บ (ใช้ web_search). "
                "เฉพาะคำศัพท์หรือวลีสั้นเท่านั้น ไม่ใช่สำหรับแปลประโยคยาวหรือเอกสาร"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "คำศัพท์หรือวลีที่ต้องการค้นหาความหมาย เช่น 'managerial' หรือ 'ประชาธิปไตย'",
                    }
                },
                "required": ["args"],
            },
        }
