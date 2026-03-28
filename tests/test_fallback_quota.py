"""Tests for LLM provider fallback with daily quota."""

import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub google_auth_oauthlib before importing anything that touches it
fake_google_auth_oauthlib = types.ModuleType("google_auth_oauthlib")
fake_google_auth_oauthlib_flow = types.ModuleType("google_auth_oauthlib.flow")
fake_google_auth_oauthlib_flow.InstalledAppFlow = object
fake_google_auth_oauthlib_flow.Flow = object
sys.modules.setdefault("google_auth_oauthlib", fake_google_auth_oauthlib)
sys.modules.setdefault("google_auth_oauthlib.flow", fake_google_auth_oauthlib_flow)

from core import db
from core import security
from core.providers.base import BaseLLMProvider
from core.providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------

class FakeMatcha(BaseLLMProvider):
    name = "matcha"

    def __init__(self, configured=True, available_for_user=True):
        self._configured = configured
        self._available_for_user = available_for_user

    def is_configured(self):
        return self._configured

    def is_available_for_user(self, user_id: str):
        return self._available_for_user

    def get_model(self, tier="cheap"):
        return "matcha-test"

    async def chat(self, messages, tier="cheap", system="", tools=None, user_id=None):
        return {"content": "matcha response", "tool_call": None, "model": "matcha-test", "token_used": 10}

    def convert_tool_spec(self, spec):
        return spec


class FakeGemini(BaseLLMProvider):
    name = "gemini"

    def __init__(self, configured=True):
        self._configured = configured

    def is_configured(self):
        return self._configured

    def is_available_for_user(self, user_id: str):
        return self._configured

    def get_model(self, tier="cheap"):
        return "gemini-test"

    async def chat(self, messages, tier="cheap", system="", tools=None, user_id=None):
        return {"content": "gemini response", "tool_call": None, "model": "gemini-test", "token_used": 20}

    def convert_tool_spec(self, spec):
        return spec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(security.config, "ENCRYPTION_KEY", "")
    db.close_thread_local_connection()
    db.init_db()
    db.upsert_user("owner-1", "owner-1", "Owner", role="owner")
    db.upsert_user("user-1", "user-1", "User One", role="user")


def _make_registry(matcha_available=True, matcha_configured=True, gemini_configured=True):
    reg = ProviderRegistry()
    reg.providers["matcha"] = FakeMatcha(
        configured=matcha_configured,
        available_for_user=matcha_available,
    )
    reg.providers["gemini"] = FakeGemini(configured=gemini_configured)
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_preferred_available_no_fallback(tmp_path, monkeypatch):
    """ถ้า preferred provider ใช้ได้ → ไม่ fallback"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry()
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)

    result = reg.get_fallback("matcha", user_id="user-1")
    assert result is not None
    assert result.name == "matcha"

    # ไม่มี fallback log
    count = db.count_fallback_today("user-1")
    assert count == 0


def test_fallback_when_preferred_unavailable(tmp_path, monkeypatch):
    """ถ้า preferred ใช้ไม่ได้ → fallback ไป gemini + บันทึก log"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    result = reg.get_fallback("matcha", user_id="user-1")
    assert result is not None
    assert result.name == "gemini"

    # มี fallback log 1 ครั้ง
    count = db.count_fallback_today("user-1")
    assert count == 1


def test_fallback_logs_accumulate(tmp_path, monkeypatch):
    """fallback log สะสมเมื่อเรียกหลายครั้ง"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    for _ in range(5):
        reg.get_fallback("matcha", user_id="user-1")

    count = db.count_fallback_today("user-1")
    assert count == 5


def test_quota_blocks_when_exceeded(tmp_path, monkeypatch):
    """ถ้าเกินโควตา → return None (ไม่ให้ fallback)"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 3)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    # ใช้ 3 ครั้ง (เต็มโควตา)
    for _ in range(3):
        result = reg.get_fallback("matcha", user_id="user-1")
        assert result is not None
        assert result.name == "gemini"

    # ครั้งที่ 4 → ถูกบล็อก
    result = reg.get_fallback("matcha", user_id="user-1")
    assert result is None

    count = db.count_fallback_today("user-1")
    assert count == 3  # ไม่เพิ่มเพราะถูกบล็อก


def test_owner_bypasses_quota(tmp_path, monkeypatch):
    """Owner ไม่จำกัดโควตา"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 2)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    # Owner ใช้ 5 ครั้ง → ไม่ถูกบล็อก
    for _ in range(5):
        result = reg.get_fallback("matcha", user_id="owner-1")
        assert result is not None
        assert result.name == "gemini"

    count = db.count_fallback_today("owner-1")
    assert count == 5


def test_quota_zero_means_unlimited(tmp_path, monkeypatch):
    """FALLBACK_DAILY_QUOTA=0 → ไม่จำกัด"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    for _ in range(100):
        result = reg.get_fallback("matcha", user_id="user-1")
        assert result is not None

    count = db.count_fallback_today("user-1")
    assert count == 100


def test_no_fallback_provider_returns_none(tmp_path, monkeypatch):
    """ไม่มี fallback provider → return None"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False, gemini_configured=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    result = reg.get_fallback("matcha", user_id="user-1")
    assert result is None


def test_fallback_prefers_default_llm_when_fallback_equals_preferred(tmp_path, monkeypatch):
    """ถ้า FALLBACK_LLM == preferred (ทั้งคู่ gemini) → ควร fallback ไป DEFAULT_LLM (matcha) ไม่ใช่ claude"""
    _init_db(tmp_path, monkeypatch)

    # สร้าง registry ที่มี 3 providers: gemini (unavailable), claude, matcha
    reg = ProviderRegistry()
    reg.providers["claude"] = FakeGemini(configured=True)  # reuse FakeGemini for simplicity
    reg.providers["claude"].name = "claude"
    reg.providers["gemini"] = FakeGemini(configured=True)
    reg.providers["gemini"].name = "gemini"
    # Override is_available_for_user to return False for non-owner
    reg.providers["gemini"].is_available_for_user = lambda uid: False
    reg.providers["matcha"] = FakeMatcha(configured=True, available_for_user=True)

    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")  # same as preferred
    monkeypatch.setattr("core.config.DEFAULT_LLM", "matcha")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    result = reg.get_fallback("gemini", user_id="user-1")
    assert result is not None
    assert result.name == "matcha"  # NOT claude


def test_fallback_uses_fallback_llm_before_default_llm(tmp_path, monkeypatch):
    """FALLBACK_LLM ควรถูกลองก่อน DEFAULT_LLM"""
    _init_db(tmp_path, monkeypatch)
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.DEFAULT_LLM", "matcha")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 0)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    # preferred=matcha (unavailable) → FALLBACK_LLM=gemini → should use gemini
    result = reg.get_fallback("matcha", user_id="user-1")
    assert result is not None
    assert result.name == "gemini"


def test_different_users_have_separate_quotas(tmp_path, monkeypatch):
    """user คนละคนมีโควตาแยกกัน"""
    _init_db(tmp_path, monkeypatch)
    db.upsert_user("user-2", "user-2", "User Two", role="user")
    reg = _make_registry(matcha_available=False)
    monkeypatch.setattr("core.config.FALLBACK_LLM", "gemini")
    monkeypatch.setattr("core.config.FALLBACK_DAILY_QUOTA", 2)
    monkeypatch.setattr("core.config.OWNER_TELEGRAM_CHAT_ID", "owner-1")

    # user-1 ใช้ 2 ครั้ง (เต็ม)
    for _ in range(2):
        reg.get_fallback("matcha", user_id="user-1")

    # user-1 ถูกบล็อก
    assert reg.get_fallback("matcha", user_id="user-1") is None

    # user-2 ยังใช้ได้
    result = reg.get_fallback("matcha", user_id="user-2")
    assert result is not None
    assert result.name == "gemini"
