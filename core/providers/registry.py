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
        ถ้า preferred ไม่พร้อม → ลอง FALLBACK_LLM → ลอง provider อื่นที่พร้อม
        ถ้าไม่มีเลย → return None
        """
        # ลอง preferred ก่อน
        p = self.providers.get(preferred)
        if p:
            if user_id and p.is_available_for_user(user_id):
                return p
            elif p.is_configured():
                return p

        # ลอง configured fallback ก่อน
        from core.config import FALLBACK_LLM
        if FALLBACK_LLM and FALLBACK_LLM != preferred:
            fb = self.providers.get(FALLBACK_LLM)
            if fb and fb.is_configured():
                log.warning(f"Provider '{preferred}' not available, falling back to '{fb.name}'")
                return fb

        # fallback ไปตัวอื่นที่พร้อม
        for provider in self.providers.values():
            if provider.name != preferred and provider.is_configured():
                log.warning(f"Provider '{preferred}' not available, falling back to '{provider.name}'")
                return provider

        return None


# Singleton
provider_registry = ProviderRegistry()
