import asyncio
import concurrent.futures
import types
from unittest.mock import patch

from interfaces import telegram_polling


def setup_function():
    telegram_polling.stop_shared_async_loop()


def teardown_function():
    telegram_polling.stop_shared_async_loop()


def test_shared_runtime_reuses_loop_until_stop():
    loop1 = telegram_polling.ensure_shared_async_loop()
    loop2 = telegram_polling.ensure_shared_async_loop()

    assert loop1 is loop2
    assert not loop1.is_closed()


def test_shared_runtime_recreates_loop_after_stop():
    loop1 = telegram_polling.ensure_shared_async_loop()
    telegram_polling.stop_shared_async_loop()

    loop2 = telegram_polling.ensure_shared_async_loop()

    assert loop1 is not loop2
    assert not loop2.is_closed()


def test_shared_runtime_executes_coroutine_threadsafe():
    loop = telegram_polling.ensure_shared_async_loop()

    async def sample():
        await asyncio.sleep(0)
        return "ok"

    future = asyncio.run_coroutine_threadsafe(sample(), loop)

    assert future.result(timeout=2) == "ok"


def test_handle_update_dispatches_via_shared_loop():
    calls = []

    async def fake_process_message(user_id, user, chat_id, text):
        calls.append((user_id, user, chat_id, text))

    fake_dispatcher = types.SimpleNamespace(process_message=fake_process_message)
    update = {
        "message": {
            "chat": {"id": 12345},
            "text": "ข่าวอิหร่าน",
        }
    }
    user = {"user_id": "u-123", "telegram_chat_id": "12345"}

    with patch("interfaces.telegram_polling.get_user", return_value=user), \
         patch.dict("sys.modules", {"dispatcher": fake_dispatcher}):
        telegram_polling.handle_update(update)

    assert calls == [("u-123", user, 12345, "ข่าวอิหร่าน")]


def test_expected_dispatch_failure_is_not_noisy():
    future_error = concurrent.futures.CancelledError()

    class FakeFuture:
        def result(self):
            raise future_error

    update = {
        "message": {
            "chat": {"id": 12345},
            "text": "ทดสอบ",
        }
    }
    user = {"user_id": "u-123", "telegram_chat_id": "12345"}

    with patch("interfaces.telegram_polling.get_user", return_value=user), \
         patch("interfaces.telegram_polling.asyncio.run_coroutine_threadsafe", return_value=FakeFuture()), \
         patch("interfaces.telegram_polling.log.warning") as mock_warning, \
         patch("interfaces.telegram_polling.log.exception") as mock_exception, \
         patch.dict("sys.modules", {"dispatcher": types.SimpleNamespace(process_message=lambda *args, **kwargs: None)}):
        telegram_polling.handle_update(update)

    assert mock_warning.called
    mock_exception.assert_not_called()