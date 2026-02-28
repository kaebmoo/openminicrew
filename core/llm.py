"""LLM Router — unified interface ที่ใช้ Provider Registry
   เพิ่ม provider ใหม่ = สร้างไฟล์ใน core/providers/ เท่านั้น
"""

from core.providers.registry import provider_registry
from core.logger import get_logger

log = get_logger(__name__)


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
    ) -> dict:
        """
        Unified chat interface — routes to correct provider with auto-fallback.

        Returns:
            {
                "content": str,
                "tool_call": dict | None,
                "model": str,
                "token_used": int,
            }
        """
        # หา provider ที่พร้อมใช้ (fallback อัตโนมัติ)
        p = provider_registry.get_fallback(provider)
        if not p:
            raise ValueError(
                "ไม่มี LLM provider ที่พร้อมใช้งาน — "
                "ตั้งค่า ANTHROPIC_API_KEY หรือ GEMINI_API_KEY ใน .env"
            )

        try:
            return await p.chat(messages, tier, system, tools)
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

                # Try another provider
                for other in provider_registry.providers.values():
                    if other.name != p.name and other.is_configured() and not getattr(other, '_auth_failed', False):
                        log.info(f"Falling back to '{other.name}'")
                        return await other.chat(messages, tier, system, tools)

                # No fallback available
                raise ValueError(
                    f"❌ {p.name} API key ไม่ถูกต้อง และไม่มี provider อื่นที่ใช้ได้\n"
                    f"กรุณาตรวจสอบ API key ใน .env"
                ) from e
            else:
                raise

    def get_available_providers(self) -> list[str]:
        """Return list of provider names ที่ตั้งค่า API key แล้ว"""
        return provider_registry.get_available()

    def health_check(self) -> dict:
        """Health check — แสดงสถานะแต่ละ provider"""
        result = {}
        for name, p in provider_registry.providers.items():
            result[f"{name}_configured"] = p.is_configured()
        return result


# Singleton
llm_router = LLMRouter()
