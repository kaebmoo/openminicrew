import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zoneinfo import ZoneInfo

import scheduler


def test_load_custom_schedules_resolves_user_id_first(monkeypatch):
    add_job = MagicMock()

    monkeypatch.setattr(
        scheduler.db,
        "get_active_schedules",
        lambda: [{"id": 7, "user_id": "u1", "tool_name": "reminder", "cron_expr": "0 9 * * *", "args": "soon"}],
    )
    monkeypatch.setattr(
        scheduler.db,
        "get_user_by_id",
        lambda user_id: {"user_id": user_id, "telegram_chat_id": "chat-1"} if user_id == "u1" else None,
    )
    get_user_by_chat_id = MagicMock(return_value=None)
    monkeypatch.setattr(scheduler.db, "get_user_by_chat_id", get_user_by_chat_id)
    monkeypatch.setattr(scheduler, "_make_trigger", lambda cron_expr: ("trigger", cron_expr))
    monkeypatch.setattr(scheduler.scheduler, "add_job", add_job)

    loaded = getattr(scheduler, "_load_custom_schedules")()

    assert loaded == 1
    add_job.assert_called_once()
    _, kwargs = add_job.call_args
    assert kwargs["args"] == ["u1", "chat-1", "reminder", "soon"]
    get_user_by_chat_id.assert_not_called()


def test_check_missed_jobs_resolves_user_id_first(monkeypatch):
    now = datetime.now(ZoneInfo(scheduler.TIMEZONE))
    scheduled = now - timedelta(minutes=1)
    cron_expr = f"{scheduled.minute} {scheduled.hour} * * *"
    run_tool = MagicMock()

    monkeypatch.setattr(
        scheduler.db,
        "get_active_schedules",
        lambda: [{"id": 9, "user_id": "u2", "tool_name": "news_summary", "cron_expr": cron_expr, "args": ""}],
    )
    monkeypatch.setattr(scheduler.db, "get_last_job_run", lambda job_id: None)
    monkeypatch.setattr(
        scheduler.db,
        "get_user_by_id",
        lambda user_id: {"user_id": user_id, "telegram_chat_id": "chat-9"} if user_id == "u2" else None,
    )
    get_user_by_chat_id = MagicMock(return_value=None)
    monkeypatch.setattr(scheduler.db, "get_user_by_chat_id", get_user_by_chat_id)
    monkeypatch.setattr(scheduler, "_run_tool_for_user", run_tool)

    scheduler.check_missed_jobs()

    run_tool.assert_called_once()
    args, kwargs = run_tool.call_args
    assert args[:4] == ("u2", "chat-9", "news_summary", "")
    assert kwargs["job_id"] == "custom_9"
    get_user_by_chat_id.assert_not_called()


def test_run_tool_for_user_logs_run_when_scheduler_does_not_pass_scheduled_at(monkeypatch):
    log_job_run = MagicMock()

    monkeypatch.setattr(scheduler, "_run_tool_for_user_inner", lambda *args, **kwargs: True)
    monkeypatch.setattr(scheduler.db, "log_job_run", log_job_run)
    monkeypatch.setattr(scheduler.db, "update_schedule_last_run", MagicMock())

    getattr(scheduler, "_run_tool_for_user")("u3", "chat-3", "lotto", job_id="custom_3")

    log_job_run.assert_called_once()
    args, kwargs = log_job_run.call_args
    assert args[0] == "custom_3"
    datetime.fromisoformat(args[1])
    assert kwargs["status"] == "success"


def test_run_tool_for_user_updates_schedule_last_run(monkeypatch):
    update_schedule_last_run = MagicMock()

    monkeypatch.setattr(scheduler, "_run_tool_for_user_inner", lambda *args, **kwargs: False)
    monkeypatch.setattr(scheduler.db, "log_job_run", MagicMock())
    monkeypatch.setattr(scheduler.db, "update_schedule_last_run", update_schedule_last_run)

    getattr(scheduler, "_run_tool_for_user")(
        "u4", "chat-4", "news_summary", job_id="custom_4", schedule_id=4
    )

    update_schedule_last_run.assert_called_once_with(4)