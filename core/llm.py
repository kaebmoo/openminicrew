"""LLM Router — unified interface ที่ใช้ Provider Registry
   เพิ่ม provider ใหม่ = สร้างไฟล์ใน core/providers/ เท่านั้น
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import TIMEZONE
from core.providers.registry import provider_registry
from core.concurrency import llm_semaphore
from core.logger import get_logger

log = get_logger(__name__)


def _build_runtime_system_context() -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    current_date = now.date().isoformat()
    current_time = now.strftime("%H:%M")
    buddhist_year = now.year + 543
    return (
        f"วันและเวลาปัจจุบันคือ {current_date} {current_time} ({TIMEZONE}) "
        f"ซึ่งตรงกับปี ค.ศ. {now.year} / พ.ศ. {buddhist_year}. "
        "เมื่อคุณต้องตีความคำว่า วันนี้, ตอนนี้, ล่าสุด, วันพรุ่งนี้, เมื่อวาน, วันที่, เดือน, ปี "
        "ให้ยึดวันและเวลาปัจจุบันนี้เป็นหลักเสมอ. "
        "หากแหล่งข้อมูลมีปี พ.ศ. หรือ ค.ศ. ให้แปลงและตรวจสอบกับวันปัจจุบันก่อนสรุป "
        "และถ้าข้อมูลในแหล่งอ้างอิงดูเป็นวันในอนาคตหรือไม่สอดคล้องกับวันปัจจุบัน ให้ชี้แจงความกำกวมอย่างชัดเจน."
    )


def _merge_system_prompt(system: str) -> str:
    runtime_context = _build_runtime_system_context()
    if not system:
        return runtime_context
    return f"{runtime_context}\n\n{system}"


class LLMRouter:
    def __init__(self):
        # Auto-discover all providers
        provider_registry.discover()

    async def chat(
        self,
        messages: list[dict],
        provider: str = "claude",
        tier: str = "cheap",
        system: str = "",
        tools: list[dict] | None = None,
        user_id: str = None,
    ) -> dict:
        """
        Unified chat interface — routes to correct provider with auto-fallback.

        Args:
            user_id: สำหรับ resolve per-user API key

        Returns:
            {
                "content": str,
                "tool_call": dict | None,
                "model": str,
                "token_used": int,
            }
        """
        # หา provider ที่พร้อมใช้ (fallback อัตโนมัติ)
        p = provider_registry.get_fallback(provider, user_id=user_id)
        if not p:
            raise ValueError(
                "ไม่มี LLM provider ที่พร้อมใช้งาน — "
                "ตั้งค่า ANTHROPIC_API_KEY หรือ GEMINI_API_KEY ใน .env"
            )

        merged_system = _merge_system_prompt(system)

        try:
            async with llm_semaphore.acquire():
                return await p.chat(messages, tier, merged_system, tools, user_id=user_id)
        except Exception as e:
            error_str = str(e).lower()
            is_auth_error = (
                "authentication" in error_str
                or "401" in error_str
                or "invalid" in error_str and "api" in error_str
                or "unauthorized" in error_str
            )

            if is_auth_error:
                log.warning(f"Provider '{p.name}' auth failed, trying fallback...")
                # Mark provider as broken so fallback skips it
                p._auth_failed = True

                # ลอง configured fallback ก่อน
                from core.config import FALLBACK_LLM
                fallback_order = []
                if FALLBACK_LLM:
                    fb = provider_registry.get(FALLBACK_LLM)
                    if fb:
                        fallback_order.append(fb)
                # แล้วค่อยลองตัวอื่น
                for other in provider_registry.providers.values():
                    if other not in fallback_order:
                        fallback_order.append(other)

                for other in fallback_order:
                    if other.name != p.name and other.is_configured() and not getattr(other, '_auth_failed', False):
                        log.info(f"Falling back to '{other.name}'")
                        return await other.chat(messages, tier, merged_system, tools, user_id=user_id)

                # No fallback available
                raise ValueError(
                    f"❌ {p.name} API key ไม่ถูกต้อง และไม่มี provider อื่นที่ใช้ได้\n"
                    f"กรุณาตรวจสอบ API key ใน .env"
                ) from e
            else:
                raise

    def get_available_providers(self, user_id: str = None) -> list[str]:
        """Return list of provider names ที่ใช้ได้ (shared key หรือ per-user key)"""
        return provider_registry.get_available(user_id=user_id)

    def health_check(self) -> dict:
        """Health check — แสดงสถานะแต่ละ provider"""
        result = {}
        for name, p in provider_registry.providers.items():
            result[f"{name}_configured"] = p.is_configured()
        return result


# Singleton
llm_router = LLMRouter()
