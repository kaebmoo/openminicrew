"""Startup and health readiness checks shared by boot and /health."""

from __future__ import annotations

from pathlib import Path

from core import config


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"


def resolve_startup_policy(bot_mode: str | None = None, policy: str | None = None) -> str:
    selected_policy = (policy or config.STARTUP_READINESS_POLICY or "auto").strip().lower()
    if selected_policy not in {"auto", "strict", "warn"}:
        selected_policy = "auto"

    if selected_policy != "auto":
        return selected_policy

    return "strict" if (bot_mode or config.BOT_MODE).strip().lower() == "webhook" else "warn"


def _make_check(name: str, status: str, summary: str, *, required: bool = False,
                impacts: list[str] | None = None, detail: str = "") -> dict:
    return {
        "name": name,
        "status": status,
        "required": required,
        "summary": summary,
        "detail": detail,
        "impacts": impacts or [],
    }


def collect_startup_readiness(bot_mode: str | None = None, policy: str | None = None) -> dict:
    resolved_bot_mode = (bot_mode or config.BOT_MODE).strip().lower()
    resolved_policy = resolve_startup_policy(resolved_bot_mode, policy)
    strict_mode = resolved_policy == "strict"

    checks: list[dict] = []
    encryption_ready = bool(config.ENCRYPTION_KEY)
    encryption_status = STATUS_OK if encryption_ready else (STATUS_FAIL if strict_mode else STATUS_WARN)
    encryption_summary = "ENCRYPTION_KEY configured" if encryption_ready else "ENCRYPTION_KEY missing"
    encryption_detail = (
        "Encrypted Gmail token storage, private API key storage, and encrypted profile fields are ready"
        if encryption_ready
        else "Gmail OAuth token write, /setphone, /setid, and private per-user API key storage are unavailable"
    )
    impacts = [] if encryption_ready else ["gmail_oauth", "private_api_keys", "encrypted_profile_fields"]
    checks.append(
        _make_check(
            "encryption_key",
            encryption_status,
            encryption_summary,
            required=strict_mode,
            impacts=impacts,
            detail=encryption_detail,
        )
    )

    credentials_exists = config.GMAIL_CREDENTIALS_FILE.exists()
    checks.append(
        _make_check(
            "gmail_credentials_file",
            STATUS_OK if credentials_exists else STATUS_WARN,
            "credentials.json available" if credentials_exists else "credentials.json missing",
            impacts=[] if credentials_exists else ["gmail_oauth"],
            detail=str(config.GMAIL_CREDENTIALS_FILE),
        )
    )

    if resolved_bot_mode == "webhook":
        webhook_host_ready = bool(config.WEBHOOK_HOST)
        checks.append(
            _make_check(
                "webhook_host",
                STATUS_OK if webhook_host_ready else STATUS_FAIL,
                "WEBHOOK_HOST configured" if webhook_host_ready else "WEBHOOK_HOST missing",
                required=True,
                impacts=[] if webhook_host_ready else ["webhook"],
                detail="Required to publish Telegram webhook callback URL",
            )
        )

        secret_ready = bool(config.TELEGRAM_WEBHOOK_SECRET)
        checks.append(
            _make_check(
                "webhook_secret",
                STATUS_OK if secret_ready else STATUS_WARN,
                "Telegram webhook secret configured" if secret_ready else "Telegram webhook secret missing",
                impacts=[] if secret_ready else ["webhook_request_authentication"],
                detail="Recommended so Telegram requests are authenticated with X-Telegram-Bot-Api-Secret-Token",
            )
        )

    overall_status = STATUS_OK
    if any(check["status"] == STATUS_FAIL for check in checks):
        overall_status = STATUS_FAIL
    elif any(check["status"] == STATUS_WARN for check in checks):
        overall_status = "degraded"

    return {
        "bot_mode": resolved_bot_mode,
        "policy": resolved_policy,
        "status": overall_status,
        "should_fail_fast": overall_status == STATUS_FAIL,
        "checks": checks,
    }


def summarize_startup_readiness(report: dict) -> list[str]:
    lines: list[str] = []
    for check in report.get("checks", []):
        prefix = {
            STATUS_OK: "OK",
            STATUS_WARN: "WARN",
            STATUS_FAIL: "FAIL",
        }.get(check["status"], check["status"].upper())
        line = f"[{prefix}] {check['name']}: {check['summary']}"
        if check.get("detail"):
            line += f" - {check['detail']}"
        lines.append(line)
    return lines


def file_path_is_writable(path: Path) -> bool:
    parent = path.parent if path.suffix else path
    return parent.exists() and parent.is_dir() and parent.stat()