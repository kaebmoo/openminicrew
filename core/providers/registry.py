"""Provider Registry — auto-discover LLM providers จาก core/providers/ directory"""

import importlib
import inspect
import pkgutil
from pathlib import Path

from core.providers.base import BaseLLMProvider
from core.logger import get_logger

log = get_logger(__name__)


class ProviderRegistry:
    def __init__(self):
        self.providers: dict[str, BaseLLMProvider] = {}

    def discover(self):
        """Scan core/providers/ directory หา class ที่ inherit BaseLLMProvider"""
        providers_dir = Path(__file__).parent

        for finder, module_name, _ in pkgutil.iter_modules([str(providers_dir)]):
            if module_name in ("base", "registry", "__init__"):
                continue

            try:
                module = importlib.import_module(f"core.providers.{module_name}")

                for attr_name, attr in inspect.getmembers(module, inspect.isclass):
                    if issubclass(attr, BaseLLMProvider) and attr is not BaseLLMProvider:
                        instance = attr()
                        self._register(instance)

            except Exception as e:
                log.error(f"Failed to load provider module '{module_name}': {e}", exc_info=True)

        configured = [n for n, p in self.providers.items() if p.is_configured()]
        log.info(
            f"Discovered {len(self.providers)} providers: {list(self.providers.keys())} "
            f"(configured: {configured})"
        )

    def _register(self, provider: BaseLLMProvider):
        if not provider.name:
            log.warning(f"Skipping provider with empty name: {type(provider)}")
            return
        self.providers[provider.name] = provider
        log.info(f"Registered provider: {provider.name} (configured: {provider.is_configured()})")

    def get(self, name: str) -> BaseLLMProvider | None:
        """Get provider by name"""
        return self.providers.get(name)

    def get_available(self, user_id: str = None) -> list[str]:
        """Return list of provider names ที่ใช้ได้ (shared key หรือ per-user key)"""
        if user_id:
            return [name for name, p in self.providers.items() if p.is_available_for_user(user_id)]
        return [name for name, p in self.providers.items() if p.is_configured()]

    def get_fallback(self, preferred: str, user_id: str = None) -> BaseLLMProvider | None:
        """
        ถ้า preferred ไม่พร้อมสำหรับ user → ลอง FALLBACK_LLM → ลอง provider อื่นที่พร้อม
        ถ้าไม่มีเลย → return None

        สำคัญ: preferred ต้องผ่าน is_available_for_user() ถ้ามี user_id
        เพื่อป้องกัน user ใช้ shared key ของ provider ที่ไม่มีสิทธิ์

        Fallback มีโควตาต่อวัน (FALLBACK_DAILY_QUOTA) — owner ไม่จำกัด
        """
        # ลอง preferred ก่อน — ตรวจสิทธิ์ user
        p = self.providers.get(preferred)
        if p:
            if user_id:
                if p.is_available_for_user(user_id):
                    return p
                log.info(f"Provider '{preferred}' not available for user {user_id}, trying fallback")
            elif p.is_configured():
                return p

        # ลอง configured fallback
        from core.config import FALLBACK_LLM
        fallback_provider = None
        if FALLBACK_LLM and FALLBACK_LLM != preferred:
            fb = self.providers.get(FALLBACK_LLM)
            if fb and fb.is_configured():
                fallback_provider = fb

        if not fallback_provider:
            for provider in self.providers.values():
                if provider.name != preferred and provider.is_configured():
                    fallback_provider = provider
                    break

        if not fallback_provider:
            return None

        # ตรวจโควตา fallback (owner ไม่จำกัด)
        if user_id and not self._is_owner(user_id):
            from core.config import FALLBACK_DAILY_QUOTA
            if FALLBACK_DAILY_QUOTA > 0:
                from core.db import count_fallback_today
                used = count_fallback_today(user_id)
                if used >= FALLBACK_DAILY_QUOTA:
                    log.warning(
                        f"User {user_id} exceeded fallback quota "
                        f"({used}/{FALLBACK_DAILY_QUOTA}), denying fallback"
                    )
                    return None

        # บันทึก fallback usage
        if user_id:
            try:
                from core.db import log_fallback_usage
                log_fallback_usage(user_id, preferred, fallback_provider.name)
            except Exception as e:
                log.warning(f"Failed to log fallback usage: {e}")

        log.info(
            f"Provider '{preferred}' not available for user {user_id}, "
            f"using fallback '{fallback_provider.name}'"
        )
        return fallback_provider

    @staticmethod
    def _is_owner(user_id: str) -> bool:
        """ตรวจว่า user เป็น owner หรือไม่ — ใช้สำหรับ bypass โควตา"""
        try:
            from core.config import OWNER_TELEGRAM_CHAT_ID
            return str(user_id) == str(OWNER_TELEGRAM_CHAT_ID)
        except Exception:
            return False


# Singleton
provider_registry = ProviderRegistry()
