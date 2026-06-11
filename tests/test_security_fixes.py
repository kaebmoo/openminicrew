"""Regression tests สำหรับ findings จาก security scan 2026-06-08

ครอบคลุม: reminder ownership, IMAP TLS fail-closed, secret redaction,
Gmail consent enforcement, LLM fallback authorization, user_id propagation,
attachment size limits, Smart Inbox auto-mode hardening
"""

import asyncio
import ssl
import sys
import types
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

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


def _setup_tmp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_FILE", db_path)
    db.close_thread_local_connection()
    db.init_db()


# ---------------------------------------------------------------------------
# Finding 2: reminder ownership
# ---------------------------------------------------------------------------

def test_user_cannot_fire_another_users_reminder(tmp_path, monkeypatch):
    from tools.reminder import ReminderTool

    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("user_a", "chat-a", "A")
    db.upsert_user("user_b", "chat-b", "B")

    reminder_id = db.add_reminder("user_a", "ความลับของ A", "2099-01-01T09:00:00")

    tool = ReminderTool()
    result = asyncio.run(tool.execute("user_b", f"fire {reminder_id}"))

    assert "ความลับของ A" not in result
    assert "ไม่พบ" in result
    # reminder ของ A ต้องยัง pending — B mark sent ไม่ได้
    reminder = db.get_reminder(reminder_id, "user_a")
    assert reminder["status"] == "pending"


def test_owner_can_fire_own_reminder(tmp_path, monkeypatch):
    from tools.reminder import ReminderTool

    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("user_a", "chat-a", "A")
    reminder_id = db.add_reminder("user_a", "ประชุมทีม", "2099-01-01T09:00:00")

    tool = ReminderTool()
    result = asyncio.run(tool.execute("user_a", f"fire {reminder_id}"))

    assert "ประชุมทีม" in result
    assert db.get_reminder(reminder_id, "user_a")["status"] == "sent"


def test_mark_reminder_sent_scoped_by_user(tmp_path, monkeypatch):
    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("user_a", "chat-a", "A")
    reminder_id = db.add_reminder("user_a", "x", "2099-01-01T09:00:00")

    db.mark_reminder_sent(reminder_id, "user_b")
    assert db.get_reminder(reminder_id)["status"] == "pending"

    db.mark_reminder_sent(reminder_id, "user_a")
    assert db.get_reminder(reminder_id)["status"] == "sent"


# ---------------------------------------------------------------------------
# Finding 3: IMAP TLS fail-closed
# ---------------------------------------------------------------------------

def test_imap_cert_failure_does_not_retry_with_cert_none(monkeypatch):
    import tools.work_email as work_email

    attempts = []

    def fake_imap(host, port, ssl_context=None):
        attempts.append(ssl_context)
        raise ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(work_email.imaplib, "IMAP4_SSL", fake_imap)

    tool = work_email.WorkEmailTool()
    with pytest.raises(ssl.SSLCertVerificationError):
        tool._connect_imap("imap.example.com", "user", "password")

    # ต้องลองครั้งเดียวด้วย default (verified) context — ห้าม retry ด้วย CERT_NONE
    assert attempts == [None]


# ---------------------------------------------------------------------------
# Finding 4: secret redaction
# ---------------------------------------------------------------------------

def test_redact_secret_text_masks_setkey_value():
    from core.api_keys import redact_secret_text

    assert redact_secret_text("/setkey tmd real-secret-123") == "/setkey tmd [REDACTED]"
    assert "real-secret" not in redact_secret_text("/setkey work_imap_password real-secret-123")
    # ข้อความปกติไม่ถูกแตะ
    assert redact_secret_text("สวัสดี อากาศวันนี้") == "สวัสดี อากาศวันนี้"
    assert redact_secret_text("/remind 2026-01-01 09:00 ประชุม") == "/remind 2026-01-01 09:00 ประชุม"


def test_redact_secret_tool_args_masks_apikeys_value():
    from core.api_keys import redact_secret_tool_args

    masked = redact_secret_tool_args("apikeys", {"action": "set", "service": "tmd", "value": "real-secret"})
    assert masked["value"] == "[REDACTED]"
    # tool อื่นไม่ถูกแตะ
    args = {"args": "today"}
    assert redact_secret_tool_args("weather", args) == args


def test_process_message_does_not_persist_setkey_secret(tmp_path, monkeypatch):
    import dispatcher
    import interfaces.telegram_common as tg_common

    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("u1", "chat-1", "User One")

    class _NoopTyping:
        def __init__(self, chat_id):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tg_common, "send_message", lambda *a, **k: None)
    monkeypatch.setattr(tg_common, "send_tool_response", lambda *a, **k: None)
    monkeypatch.setattr(tg_common, "TypingIndicator", _NoopTyping)
    # ข้าม dedup state จากเทสต์อื่น
    dispatcher.request_dedup.remove("u1", "/setkey tmd realistic-secret-token-12345")

    user = db.get_user_by_id("u1")
    asyncio.run(
        dispatcher.process_message("u1", user, "chat-1", "/setkey tmd realistic-secret-token-12345")
    )

    with db.get_conn() as conn:
        history = [r["content"] for r in conn.execute("SELECT content FROM chat_history").fetchall()]
        tool_logs = [str(dict(r)) for r in conn.execute("SELECT * FROM tool_logs").fetchall()]
        conversations = [r["title"] for r in conn.execute("SELECT title FROM conversations").fetchall()]

    all_persisted = "\n".join(history + tool_logs + [t or "" for t in conversations])
    assert "realistic-secret-token-12345" not in all_persisted
    assert any("[REDACTED]" in m for m in history)


# ---------------------------------------------------------------------------
# Finding 6: Gmail consent enforcement
# ---------------------------------------------------------------------------

def test_get_gmail_credentials_refuses_when_consent_revoked(tmp_path, monkeypatch):
    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("u1", "chat-1", "User One")

    # สร้าง token file ค้างไว้ (จำลองกรณีลบไม่สำเร็จ)
    token_path = tmp_path / "token_u1.json"
    token_path.write_text("{}")
    monkeypatch.setattr(security, "get_gmail_token_path", lambda user_id: token_path)

    db.set_user_consent("u1", db.CONSENT_GMAIL, db.CONSENT_STATUS_REVOKED, source="test")

    assert security.get_gmail_credentials("u1") is None


def test_revoke_gmail_access_reports_token_delete_failure(tmp_path, monkeypatch):
    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("u1", "chat-1", "User One")

    token_path = tmp_path / "token_u1.json"
    token_path.write_text("{}")
    monkeypatch.setattr(security, "get_gmail_token_path", lambda user_id: token_path)

    def _fail_unlink(self):
        raise OSError("permission denied")

    monkeypatch.setattr(type(token_path), "unlink", _fail_unlink)

    summary = db.revoke_gmail_access("u1")
    assert summary["gmail_token_delete_failed"] is True
    assert summary["gmail_token_deleted"] is False


def test_start_does_not_reauthorize_gmail_from_stale_token(tmp_path, monkeypatch):
    from core.system_commands import handle_start

    _setup_tmp_db(tmp_path, monkeypatch)
    db.upsert_user("u1", "chat-1", "User One")
    db.set_user_consent("u1", db.CONSENT_GMAIL, db.CONSENT_STATUS_REVOKED, source="test")

    token_path = tmp_path / "token_u1.json"
    token_path.write_text("{}")
    monkeypatch.setattr(security, "get_gmail_token_path", lambda user_id: token_path)

    user = db.get_user_by_id("u1")
    asyncio.run(handle_start("u1", user, ""))

    refreshed = db.get_user_by_id("u1")
    assert not refreshed.get("gmail_authorized")


# ---------------------------------------------------------------------------
# Finding 7: LLM fallback authorization
# ---------------------------------------------------------------------------

class _FakeProvider(BaseLLMProvider):
    def __init__(self, name, configured=True, available_for_user=True):
        self.name = name
        self._configured = configured
        self._available = available_for_user

    def is_configured(self):
        return self._configured

    def is_available_for_user(self, user_id):
        return self._available

    def get_model(self, tier="cheap"):
        return f"{self.name}-model"

    async def chat(self, messages, tier="cheap", system="", tools=None, user_id=None):
        return {"content": "ok", "tool_call": None, "model": self.get_model(), "token_used": 1}

    def convert_tool_spec(self, spec):
        return spec


def test_fallback_denies_user_without_per_user_access(monkeypatch):
    from core import config as core_config

    monkeypatch.setattr(core_config, "FALLBACK_LLM", "gemini")
    monkeypatch.setattr(core_config, "DEFAULT_LLM", "matcha")

    registry = ProviderRegistry()
    registry.providers = {
        "matcha": _FakeProvider("matcha", configured=False, available_for_user=False),
        # gemini configured ระดับ workspace แต่ user นี้ไม่มีสิทธิ์
        "gemini": _FakeProvider("gemini", configured=True, available_for_user=False),
        "claude": _FakeProvider("claude", configured=True, available_for_user=False),
    }

    assert registry.get_fallback("matcha", user_id="non-owner") is None


def test_fallback_allows_user_with_per_user_access(tmp_path, monkeypatch):
    from core import config as core_config

    _setup_tmp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(core_config, "FALLBACK_LLM", "gemini")
    monkeypatch.setattr(core_config, "DEFAULT_LLM", "matcha")
    monkeypatch.setattr(core_config, "FALLBACK_DAILY_QUOTA", 0)

    registry = ProviderRegistry()
    registry.providers = {
        "matcha": _FakeProvider("matcha", configured=False, available_for_user=False),
        "gemini": _FakeProvider("gemini", configured=True, available_for_user=True),
    }

    fallback = registry.get_fallback("matcha", user_id="u1")
    assert fallback is not None
    assert fallback.name == "gemini"


def test_fallback_without_user_id_still_uses_configured(monkeypatch):
    from core import config as core_config

    monkeypatch.setattr(core_config, "FALLBACK_LLM", "gemini")
    monkeypatch.setattr(core_config, "DEFAULT_LLM", "matcha")

    registry = ProviderRegistry()
    registry.providers = {
        "matcha": _FakeProvider("matcha", configured=False),
        "gemini": _FakeProvider("gemini", configured=True, available_for_user=False),
    }

    fallback = registry.get_fallback("matcha", user_id=None)
    assert fallback is not None
    assert fallback.name == "gemini"


# ---------------------------------------------------------------------------
# Finding 8: user_id propagation in email LLM calls
# ---------------------------------------------------------------------------

def test_smart_inbox_llm_call_passes_user_id():
    pytest.importorskip("googleapiclient")
    import tools.smart_inbox as smart_inbox

    tool = smart_inbox.SmartInboxTool()
    fake_chat = AsyncMock(return_value={"content": "- ทำรายงาน"})

    with patch.object(smart_inbox.llm_router, "chat", fake_chat):
        asyncio.run(tool._extract_action_items(
            [{"from": "a@b.com", "subject": "s", "date": "d", "body": "b"}],
            "u1",
        ))

    assert fake_chat.call_args.kwargs.get("user_id") == "u1"


def test_work_email_llm_call_passes_user_id(monkeypatch):
    import tools.work_email as work_email

    tool = work_email.WorkEmailTool()
    fake_chat = AsyncMock(return_value={"content": "สรุป", "model": "m", "token_used": 1})

    email_data = work_email.EmailData(
        message_id="m1", subject="s", sender="a@b.com", date="d", body="b", attachments=[]
    )

    monkeypatch.setattr(tool, "_resolve_imap_credentials", lambda user_id: ("h", "u", "p"))
    monkeypatch.setattr(tool, "_sync_fetch_all", lambda user_id, parsed, creds: ([email_data], 0))
    monkeypatch.setattr(work_email.db, "mark_email_processed", lambda *a, **k: None)
    monkeypatch.setattr(work_email.db, "log_tool_usage", lambda *a, **k: None)
    monkeypatch.setattr(work_email, "get_user_by_id", lambda user_id: {"user_id": user_id})
    monkeypatch.setattr(work_email, "get_preference", lambda user, key: "gemini")

    with patch.object(work_email.llm_router, "chat", fake_chat):
        asyncio.run(tool.execute("u1", "today"))

    assert fake_chat.call_args.kwargs.get("user_id") == "u1"


# ---------------------------------------------------------------------------
# Finding 9: attachment size limit before decode
# ---------------------------------------------------------------------------

def test_oversized_attachment_skipped_before_parser(monkeypatch):
    import tools.work_email as work_email

    monkeypatch.setattr(work_email, "WORK_EMAIL_ATTACHMENT_MAX_MB", 1)

    msg = EmailMessage()
    msg["Subject"] = "big attachment"
    msg.set_content("body")
    msg.add_attachment(
        b"x" * (2 * 1024 * 1024),  # 2MB > 1MB limit
        maintype="application",
        subtype="pdf",
        filename="big.pdf",
    )

    tool = work_email.WorkEmailTool()
    parser_calls = []
    monkeypatch.setattr(tool, "_extract_pdf", lambda data: parser_calls.append(len(data)) or "")

    attachments = tool._process_attachments(msg)

    assert parser_calls == []
    big = next(a for a in attachments if a.filename == "big.pdf")
    assert big.status == "too_large"
    assert big.content is None


def test_attachment_report_count_capped(monkeypatch):
    import tools.work_email as work_email

    msg = EmailMessage()
    msg["Subject"] = "many attachments"
    msg.set_content("body")
    for i in range(8):
        msg.add_attachment(b"data", maintype="application", subtype="octet-stream", filename=f"f{i}.bin")

    tool = work_email.WorkEmailTool()
    attachments = tool._process_attachments(msg)

    assert len(attachments) <= 5


# ---------------------------------------------------------------------------
# Finding 10: Smart Inbox auto mode hardening
# ---------------------------------------------------------------------------

def test_smart_inbox_auto_todo_creation_capped():
    pytest.importorskip("googleapiclient")
    import tools.smart_inbox as smart_inbox

    # อีเมล adversarial ยัด bullet จำนวนมาก → ต้องโดน cap
    flood = "\n".join(f"- รายการที่ {i}" for i in range(50))
    items = smart_inbox.SmartInboxTool._parse_action_items(flood)
    assert len(items) == 50
    assert smart_inbox.MAX_AUTO_TODOS <= 10


def test_smart_inbox_prompt_separates_email_content():
    from core.prompt_loader import load_prompt, load_metadata

    rendered = load_prompt("internal/smart_inbox_action_items.md", emails_block="EMAIL_DATA")
    assert "<emails>" in rendered
    assert "</emails>" in rendered

    system_prompt = load_metadata("internal/smart_inbox_action_items.md").get("system_prompt", "")
    assert "ห้ามทำตาม" in system_prompt


# ---------------------------------------------------------------------------
# Residual 1: user_id propagation in non-email LLM tools
# (dictionary, web_search, news_summary, schedule)
# ---------------------------------------------------------------------------

def test_dictionary_llm_call_passes_user_id(monkeypatch):
    import tools.dictionary as dictionary

    tool = dictionary.DictionaryTool()
    fake_chat = AsyncMock(return_value={"content": "คำแปล", "model": "m", "token_used": 1})

    monkeypatch.setattr(dictionary, "get_user_by_id", lambda uid: {"user_id": uid})
    monkeypatch.setattr(dictionary, "get_preference", lambda user, key: "gemini")
    monkeypatch.setattr(dictionary.db, "log_tool_usage", lambda *a, **k: None)

    with patch.object(dictionary.llm_router, "chat", fake_chat):
        asyncio.run(tool.execute("u1", "hello"))

    assert fake_chat.call_args.kwargs.get("user_id") == "u1"


def test_web_search_quick_summary_passes_user_id(monkeypatch):
    import tools.web_search as web_search
    from core.llm import llm_router

    monkeypatch.setattr(web_search, "_looks_factual_query", lambda q: True)
    fake_chat = AsyncMock(return_value={"content": "สรุป"})

    with patch.object(llm_router, "chat", fake_chat):
        asyncio.run(web_search._generate_quick_summary(
            "ราคาทอง", [{"title": "t", "url": "https://example.com/a", "snippet": "s"}],
            "gemini", "cheap", user_id="u1",
        ))

    assert fake_chat.call_args.kwargs.get("user_id") == "u1"


def test_news_summary_llm_call_passes_user_id():
    import tools.news_summary as news_summary

    rss = (
        "<rss><channel>"
        "<item><title>News One - Source A</title><link>https://example.com/a</link></item>"
        "</channel></rss>"
    ).encode("utf-8")

    class _FakeResponse:
        content = rss

        def raise_for_status(self):
            return None

    fake_chat = AsyncMock(return_value={"content": "สรุปข่าว", "model": "m", "token_used": 1})

    with patch("tools.news_summary.requests.get", return_value=_FakeResponse()), \
         patch("tools.news_summary.get_user_by_id", return_value={"user_id": "u1", "default_llm": "gemini"}), \
         patch.object(news_summary.llm_router, "chat", fake_chat):
        asyncio.run(news_summary.NewsSummaryTool().execute("u1", "เศรษฐกิจ"))

    assert fake_chat.call_args.kwargs.get("user_id") == "u1"


def test_schedule_llm_tool_resolver_passes_user_id():
    import tools.schedule as schedule
    from core.llm import llm_router
    from tools.registry import registry

    if not registry.get_all():
        registry.discover()

    fake_chat = AsyncMock(return_value={"content": "NONE"})

    with patch.object(llm_router, "chat", fake_chat):
        asyncio.run(schedule._resolve_tool_via_llm("สรุปเมลทำงาน", user_id="u1"))

    assert fake_chat.call_args.kwargs.get("user_id") == "u1"


# ---------------------------------------------------------------------------
# Residual 2: Work Email raw message / body part size caps
# ---------------------------------------------------------------------------

def test_oversized_raw_message_skipped_before_parse(monkeypatch):
    import tools.work_email as work_email
    from unittest.mock import MagicMock

    monkeypatch.setattr(work_email, "WORK_EMAIL_MAX_RAW_MB", 1)

    big_raw = b"x" * (2 * 1024 * 1024)  # 2MB > 1MB cap
    conn = MagicMock()
    conn.select.return_value = ("OK", None)
    conn.search.return_value = ("OK", [b"1"])
    conn.fetch.return_value = ("OK", [(b"1 (BODY[] {2097152})", big_raw)])

    monkeypatch.setattr(work_email.WorkEmailTool, "_connect_imap", lambda self, h, u, p: conn)

    parse_calls = []
    monkeypatch.setattr(
        work_email.email, "message_from_bytes",
        lambda raw: parse_calls.append(len(raw)),
    )

    tool = work_email.WorkEmailTool()
    emails, _skipped = tool._sync_fetch_all("u1", work_email.ParsedArgs(), ("h", "u", "p"))

    # message ใหญ่เกิน cap ต้องถูกข้ามก่อนเรียก email.message_from_bytes
    assert parse_calls == []
    assert emails == []


def test_oversized_body_part_skipped_before_decode(monkeypatch):
    import tools.work_email as work_email

    monkeypatch.setattr(work_email, "_BODY_PART_MAX_BYTES", 1024)

    msg = EmailMessage()
    msg["Subject"] = "big body"
    msg.set_content("x" * 4096, cte="base64")  # encoded ~5.5KB > 1KB cap

    tool = work_email.WorkEmailTool()
    decode_calls = []
    monkeypatch.setattr(tool, "_decode_bytes", lambda data, charset: decode_calls.append(len(data)) or "")

    body = tool._extract_body(msg)

    assert body == ""
    assert decode_calls == []


def test_normal_body_still_extracted():
    import tools.work_email as work_email

    msg = EmailMessage()
    msg["Subject"] = "normal"
    msg.set_content("สวัสดีครับ ประชุมพรุ่งนี้ 9 โมง")

    tool = work_email.WorkEmailTool()
    assert "ประชุมพรุ่งนี้" in tool._extract_body(msg)
