import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import interfaces.telegram_webhook as telegram_webhook


class _Request:
    def __init__(self, secret_header=None, payload_error=False):
        self.headers = {}
        if secret_header is not None:
            self.headers["X-Telegram-Bot-Api-Secret-Token"] = secret_header
        self._payload_error = payload_error

    async def json(self):
        if self._payload_error:
            raise ValueError("bad json")
        return {}


def test_webhook_handler_rejects_invalid_json_payload(monkeypatch):
    monkeypatch.setattr(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            telegram_webhook.webhook_handler(
                _Request(secret_header="test-secret", payload_error=True),
                BackgroundTasks(),
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid JSON payload"


def test_webhook_handler_rejects_missing_secret_header(monkeypatch):
    monkeypatch.setattr(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(telegram_webhook.webhook_handler(_Request(), BackgroundTasks()))

    assert exc_info.value.status_code == 403


def test_webhook_handler_rejects_wrong_secret_header(monkeypatch):
    monkeypatch.setattr(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            telegram_webhook.webhook_handler(_Request(secret_header="wrong"), BackgroundTasks())
        )

    assert exc_info.value.status_code == 403


def test_webhook_handler_rejects_all_requests_when_secret_unset(monkeypatch):
    """fail closed: ไม่ตั้ง TELEGRAM_WEBHOOK_SECRET = ปฏิเสธทุก request (ไม่เปิดรับ forged update)"""
    monkeypatch.setattr(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            telegram_webhook.webhook_handler(_Request(secret_header=""), BackgroundTasks())
        )

    assert exc_info.value.status_code == 403


def test_webhook_handler_accepts_correct_secret(monkeypatch):
    monkeypatch.setattr(telegram_webhook, "TELEGRAM_WEBHOOK_SECRET", "test-secret")

    result = asyncio.run(
        telegram_webhook.webhook_handler(_Request(secret_header="test-secret"), BackgroundTasks())
    )

    assert result == {"ok": True}


def test_readiness_fails_fast_when_webhook_secret_missing(monkeypatch):
    from core import config as core_config
    from core.readiness import collect_startup_readiness

    monkeypatch.setattr(core_config, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(core_config, "WEBHOOK_HOST", "https://example.com")

    report = collect_startup_readiness(bot_mode="webhook")

    secret_check = next(c for c in report["checks"] if c["name"] == "webhook_secret")
    assert secret_check["status"] == "fail"
    assert secret_check["required"] is True
    assert report["should_fail_fast"] is True


def test_readiness_ok_when_webhook_secret_configured(monkeypatch):
    from core import config as core_config
    from core.readiness import collect_startup_readiness

    monkeypatch.setattr(core_config, "TELEGRAM_WEBHOOK_SECRET", "some-secret")
    monkeypatch.setattr(core_config, "WEBHOOK_HOST", "https://example.com")

    report = collect_startup_readiness(bot_mode="webhook")

    secret_check = next(c for c in report["checks"] if c["name"] == "webhook_secret")
    assert secret_check["status"] == "ok"
