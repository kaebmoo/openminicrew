import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import interfaces.telegram_webhook as telegram_webhook


class _BadJsonRequest:
    headers = {"X-Telegram-Bot-Api-Secret-Token": telegram_webhook.TELEGRAM_WEBHOOK_SECRET}

    async def json(self):
        raise ValueError("bad json")


def test_webhook_handler_rejects_invalid_json_payload():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            telegram_webhook.webhook_handler(_BadJsonRequest(), BackgroundTasks())
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid JSON payload"