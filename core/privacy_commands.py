"""Privacy & PDPA command handlers — แยกออกจาก dispatcher.py"""

from __future__ import annotations

from core.api_keys import get_plaintext_user_api_key_report, summarize_user_key_hygiene
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_consent_status(status: str) -> str:
    return {
        db.CONSENT_STATUS_GRANTED: "granted",
        db.CONSENT_STATUS_REVOKED: "revoked",
        db.CONSENT_STATUS_NOT_SET: "not set",
    }.get(status, status)


def _reload_scheduler_after_purge():
    from scheduler import reload_custom_schedules
    reload_custom_schedules()


def _parse_consent_command(args: str) -> tuple[str | None, bool | None]:
    parts = args.strip().lower().split()
    if len(parts) < 2:
        return None, None

    consent_map = {
        "gmail": db.CONSENT_GMAIL,
        "location": db.CONSENT_LOCATION,
        "chat": db.CONSENT_CHAT_HISTORY,
        "chat_history": db.CONSENT_CHAT_HISTORY,
    }
    action_map = {
        "on": True, "grant": True, "allow": True,
        "off": False, "revoke": False, "deny": False,
    }
    return consent_map.get(parts[0]), action_map.get(parts[1])


def has_pending_consent(consent_rows: dict[str, dict]) -> bool:
    return any(row["status"] == db.CONSENT_STATUS_NOT_SET for row in consent_rows.values())


def build_start_consent_block(consent_rows: dict[str, dict]) -> list[str]:
    lines = ["Consent setup:"]
    lines.append(
        "• Chat history: "
        f"{_format_consent_status(consent_rows[db.CONSENT_CHAT_HISTORY]['status'])} "
        "(/consent chat on|off)"
    )
    lines.append(
        "• Location: "
        f"{_format_consent_status(consent_rows[db.CONSENT_LOCATION]['status'])} "
        "(/consent location on|off)"
    )
    lines.append(
        "• Gmail: "
        f"{_format_consent_status(consent_rows[db.CONSENT_GMAIL]['status'])} "
        "(/authgmail, /consent gmail off)"
    )
    return lines


def build_privacy_summary(user_id: str, user: dict) -> str:
    from core.config import (
        CHAT_HISTORY_RETENTION_DAYS,
        TOOL_LOG_RETENTION_DAYS,
        EMAIL_LOG_RETENTION_DAYS,
        PENDING_MSG_RETENTION_DAYS,
        JOB_RUN_RETENTION_DAYS,
        LOCATION_TTL_MINUTES,
    )
    from core.security import get_gmail_token_path

    gmail_connected = bool(user.get("gmail_authorized")) or get_gmail_token_path(user_id).exists()
    location = db.get_location(user_id, ttl_minutes=0)
    consent_rows = {row["consent_type"]: row for row in db.list_user_consents(user_id)}
    key_hygiene = summarize_user_key_hygiene(user_id)

    lines = ["🔐 Privacy summary"]
    lines.append(f"• Gmail access: {'เชื่อมอยู่' if gmail_connected else 'ไม่ได้เชื่อม'} (/authgmail, /disconnectgmail)")
    lines.append(f"• Saved location: {'มี' if location else 'ไม่มี'} (/clearlocation)")
    lines.append("• Location policy: explicit consent + plaintext short TTL, ยังไม่เข้ารหัสใน Phase 2")
    lines.append(
        "• Consent states: "
        f"gmail={_format_consent_status(consent_rows[db.CONSENT_GMAIL]['status'])}, "
        f"location={_format_consent_status(consent_rows[db.CONSENT_LOCATION]['status'])}, "
        f"chat={_format_consent_status(consent_rows[db.CONSENT_CHAT_HISTORY]['status'])}"
    )
    lines.append(f"• Chat history retention: {CHAT_HISTORY_RETENTION_DAYS} วัน")
    lines.append(f"• Tool logs retention: {TOOL_LOG_RETENTION_DAYS} วัน")
    lines.append(f"• Email metadata retention: {EMAIL_LOG_RETENTION_DAYS} วัน")
    lines.append(f"• Pending messages retention: {PENDING_MSG_RETENTION_DAYS} วัน")
    lines.append(f"• Job run retention: {JOB_RUN_RETENTION_DAYS} วัน")
    lines.append(
        "• Private API key hygiene: "
        f"{key_hygiene['total_keys']} saved, "
        f"{key_hygiene['rotation_due_count']} due for rotation, "
        f"{key_hygiene['weak_key_count']} weak legacy values"
    )
    if key_hygiene["rotation_due_services"]:
        lines.append(f"• API keys due for rotation: {', '.join(key_hygiene['rotation_due_services'])}")
    if key_hygiene["weak_key_services"]:
        lines.append(f"• Weak legacy API keys: {', '.join(key_hygiene['weak_key_services'])}")
    lines.append("• API key rotation policy is advisory only in current rollout; existing keys are not auto-blocked")
    if LOCATION_TTL_MINUTES > 0:
        lines.append(f"• Location retention: สูงสุด {LOCATION_TTL_MINUTES} นาที ก่อน cleanup")
    else:
        lines.append("• Location retention: ไม่หมดอายุอัตโนมัติ")
    lines.append("")
    lines.append("การจัดการข้อมูล:")
    lines.append("• consent controls: /consent, /consent chat off, /consent location off")
    lines.append("• revoke Gmail access: /disconnectgmail")
    lines.append("• ลบตำแหน่งล่าสุด: /clearlocation")
    lines.append("• ลบข้อมูลทั้งหมดถาวร: /delete_my_data confirm")
    lines.append("• deactivate account: คำสั่งฝั่ง owner เท่านั้น และไม่ใช่การ purge ข้อมูล")
    return "\n".join(lines)


def build_consent_summary(user_id: str) -> str:
    rows = {row["consent_type"]: row for row in db.list_user_consents(user_id)}
    lines = ["📋 Consent status"]
    lines.append(f"• Gmail: {_format_consent_status(rows[db.CONSENT_GMAIL]['status'])}")
    lines.append(f"• Location: {_format_consent_status(rows[db.CONSENT_LOCATION]['status'])}")
    lines.append(f"• Chat history: {_format_consent_status(rows[db.CONSENT_CHAT_HISTORY]['status'])}")
    lines.append("")
    lines.append("ตัวอย่าง:")
    lines.append("• /consent chat off")
    lines.append("• /consent chat on")
    lines.append("• /consent location off")
    lines.append("• /consent gmail off")
    lines.append("• /authgmail สำหรับเชื่อม Gmail ใหม่")
    return "\n".join(lines)


def build_keyaudit_summary() -> str:
    report = get_plaintext_user_api_key_report()
    lines = ["🔐 API key storage audit"]
    lines.append(f"• ENCRYPTION_KEY configured: {'yes' if report['encryption_key_configured'] else 'no'}")
    lines.append(f"• Total rows: {report['total_keys']}")
    lines.append(f"• Encrypted rows: {report['encrypted_count']}")
    lines.append(f"• Plaintext rows: {report['plaintext_count']}")

    if not report["items"]:
        lines.append("")
        lines.append("ไม่พบ plaintext rows ใน user_api_keys")
        return "\n".join(lines)

    lines.append("")
    lines.append("Plaintext rows:")
    for item in report["items"]:
        updated = (item.get("updated_at") or "-")[:16]
        lines.append(
            f"• user={item['user_id']} service={item['service']} updated={updated} len={item['value_length']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command handlers — signature: async handle_X(user_id, user, args, **kw) -> tuple
# ---------------------------------------------------------------------------

_RESULT = tuple[str, None, None, int]


def _ok(text: str) -> _RESULT:
    return text, None, None, 0


async def handle_consent(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    consent_type, granted = _parse_consent_command(args)
    if consent_type is None or granted is None:
        return _ok(build_consent_summary(user_id))

    result = db.apply_user_consent(user_id, consent_type, granted, source="user_command")

    if consent_type == db.CONSENT_GMAIL and granted:
        return _ok("ℹ️ การให้สิทธิ์ Gmail ต้องทำผ่าน OAuth จริง ใช้ /authgmail เพื่อเชื่อมใหม่")
    if consent_type == db.CONSENT_GMAIL:
        return _ok("✅ อัปเดต consent Gmail แล้ว และยกเลิกการเชื่อมต่อเรียบร้อย")
    if consent_type == db.CONSENT_LOCATION:
        suffix = " พร้อมลบตำแหน่งที่เคยบันทึกไว้" if result.get("location_deleted") else ""
        return _ok(f"✅ consent location = {_format_consent_status(result['status'])}{suffix}")

    extra = ""
    if not granted:
        extra = (
            f"\n- deleted chat_history: {result.get('chat_history_deleted', 0)}"
            f"\n- deleted conversations: {result.get('conversations_deleted', 0)}"
        )
    return _ok(f"✅ consent chat history = {_format_consent_status(result['status'])}{extra}")


async def handle_privacy(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    return _ok(build_privacy_summary(user_id, user))


async def handle_delete_my_data(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    if args.strip().lower() != "confirm":
        return _ok(
            "⚠️ คำสั่งนี้จะลบข้อมูลของคุณแบบถาวร รวมถึงประวัติแชต, schedules, logs, API keys, "
            "ตำแหน่งล่าสุด และ Gmail token\n\n"
            "หากต้องการดำเนินการจริง ให้ใช้: /delete_my_data confirm"
        )

    summary = db.purge_user_data(user_id)
    try:
        _reload_scheduler_after_purge()
    except ImportError as err:
        log.warning("Failed to reload schedules after user purge: %s", err)

    if not summary.get("user_found"):
        return _ok("ℹ️ ไม่พบข้อมูลผู้ใช้หรือข้อมูลถูกลบไปแล้ว")

    total_rows = sum(
        value for key, value in summary.items()
        if key not in {"user_found", "gmail_token_deleted"} and isinstance(value, int)
    )
    token_status = "ลบแล้ว" if summary.get("gmail_token_deleted") else "ไม่มีหรือไม่ได้ลบ"
    log.info("User %s purged their data (rows=%s, gmail_token=%s)", user_id, total_rows, token_status)
    return _ok(
        "✅ ลบข้อมูลของคุณแบบถาวรแล้ว\n"
        f"- rows affected: {total_rows}\n"
        f"- Gmail token: {token_status}\n"
        "หากต้องการใช้งานอีกครั้ง อาจต้องลงทะเบียน/ตั้งค่าใหม่บางส่วน"
    )


async def handle_disconnectgmail(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    summary = db.revoke_gmail_access(user_id)
    if not summary.get("user_updated") and not summary.get("gmail_token_deleted") and summary.get("oauth_states", 0) == 0:
        return _ok("ℹ️ ไม่พบการเชื่อมต่อ Gmail ที่ต้องยกเลิก")

    token_status = "ลบ token แล้ว" if summary.get("gmail_token_deleted") else "ไม่พบ token ในดิสก์"
    return _ok(
        "✅ ยกเลิกการเชื่อมต่อ Gmail แล้ว\n"
        f"- {token_status}\n"
        "ข้อมูลอีเมลที่เคยสรุปไว้จะยังคงอยู่จนกว่าจะหมด retention หรือคุณใช้ /delete_my_data confirm"
    )


async def handle_clearlocation(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    deleted = db.delete_location(user_id)
    if not deleted:
        return _ok("ℹ️ ไม่มีตำแหน่งที่บันทึกไว้")
    return _ok("✅ ลบตำแหน่งล่าสุดที่บันทึกไว้แล้ว")
