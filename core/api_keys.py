"""API key resolution helpers with shared/private fallback rules."""

from __future__ import annotations

from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from core import db
from core import config
from core.logger import get_logger
from core.security import get_encryption_keyring

log = get_logger(__name__)

PRIVATE_ONLY_SERVICES = {
    "gmail",
    "calendar",
    "work_imap_host",
    "work_imap_user",
    "work_imap_password",
}

ENV_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google_maps": "GOOGLE_MAPS_API_KEY",
    "matcha": "MATCHA_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "tmd": "TMD_API_KEY",
}

_PLACEHOLDER_MARKERS = {
    "changeme",
    "your-api-key",
    "your_api_key",
    "api-key-here",
    "replace-me",
    "replace_with_real_key",
    "dummy",
    "example",
    "sample",
    "test",
    "testkey",
    "abc123",
    "password",
    "secret",
}


def normalize_service(service: str) -> str:
    return service.strip().lower()


def _get_fernet() -> Fernet | None:
    primary, _ = get_encryption_keyring()
    return primary


def _get_fernet_chain() -> list[Fernet]:
    _, chain = get_encryption_keyring()
    return chain


def _require_encryption_key():
    if not config.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is required for private key storage")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_rotation_period_days(service: str) -> int:
    normalized_service = normalize_service(service)
    overrides = {
        "work_imap_password": config.WORK_IMAP_PASSWORD_ROTATION_DAYS,
        "work_imap_user": config.WORK_IMAP_USER_ROTATION_DAYS,
        "work_imap_host": config.WORK_IMAP_HOST_ROTATION_DAYS,
    }
    return overrides.get(normalized_service, config.API_KEY_ROTATION_DAYS_DEFAULT)


def inspect_api_key_value(service: str, api_key: str, *, updated_at: str | None = None) -> dict:
    normalized_service = normalize_service(service)
    candidate = (api_key or "").strip()
    lowered = candidate.lower()
    weak_reasons: list[str] = []

    if not candidate:
        weak_reasons.append("empty value")
    if lowered in _PLACEHOLDER_MARKERS:
        weak_reasons.append("placeholder value")
    if any(marker in lowered for marker in ("your-", "replace", "dummy", "example", "sample", "test")):
        weak_reasons.append("placeholder-like text")
    if len(candidate) < 8 and normalized_service not in {"work_imap_host", "work_imap_user", "work_imap_password"}:
        weak_reasons.append("too short for secret storage")
    if len(set(candidate)) == 1 and len(candidate) >= 4:
        weak_reasons.append("repeated single character pattern")
    if " " in candidate and normalized_service not in {"work_imap_user"}:
        weak_reasons.append("contains spaces")

    if normalized_service == "work_imap_host":
        if "." not in candidate and ":" not in candidate:
            weak_reasons.append("host should look like a hostname")
    elif normalized_service == "work_imap_user":
        if "@" not in candidate and len(candidate) < 6:
            weak_reasons.append("username looks incomplete")
    elif normalized_service == "work_imap_password":
        pass  # รหัสผ่านจริงของ user — ไม่ block ไม่ว่าจะสั้นแค่ไหน

    rotation_days = get_rotation_period_days(normalized_service)
    updated_dt = _parse_iso_datetime(updated_at)
    age_days = None
    rotation_due = False
    if updated_dt is not None:
        age_days = max((_utc_now() - updated_dt).days, 0)
        rotation_due = age_days >= rotation_days

    deduped_reasons = list(dict.fromkeys(weak_reasons))
    return {
        "service": normalized_service,
        "is_weak": bool(deduped_reasons),
        "weak_reasons": deduped_reasons,
        "rotation_days": rotation_days,
        "age_days": age_days,
        "rotation_due": rotation_due,
    }


def get_api_key(user_id: str, service: str) -> str | None:
    normalized_service = normalize_service(service)

    user_key = db.get_user_api_key(user_id, normalized_service)
    if user_key:
        decrypted_value = _decrypt(user_key)
        if decrypted_value is None:
            log.warning(
                "Stored private key for service %s is unavailable because it could not be decrypted",
                normalized_service,
            )
            _log_security_audit_best_effort(
                actor_user_id=str(user_id),
                target_user_id=str(user_id),
                action="read_private_api_key",
                resource_type="user_api_keys",
                resource_id=normalized_service,
                outcome="denied",
                detail="decryption_unavailable",
            )
            return None
        _log_security_audit_best_effort(
            actor_user_id=str(user_id),
            target_user_id=str(user_id),
            action="read_private_api_key",
            resource_type="user_api_keys",
            resource_id=normalized_service,
            outcome="success",
            detail="user_scope",
        )
        return decrypted_value

    if normalized_service in PRIVATE_ONLY_SERVICES:
        return None

    env_name = ENV_KEY_MAP.get(normalized_service)
    if not env_name:
        return None

    return getattr(config, env_name, None) or None


def set_api_key(user_id: str, service: str, api_key: str):
    normalized_service = normalize_service(service)
    if normalized_service not in get_supported_services():
        raise ValueError(f"Unsupported service: {normalized_service}")

    _require_encryption_key()

    inspection = inspect_api_key_value(normalized_service, api_key)
    if inspection["is_weak"]:
        reasons = ", ".join(inspection["weak_reasons"])
        raise ValueError(f"API key/value for {normalized_service} looks weak or placeholder-like: {reasons}")

    db.upsert_user_api_key(user_id, normalized_service, _encrypt(api_key.strip()))
    _log_security_audit_best_effort(
        actor_user_id=str(user_id),
        target_user_id=str(user_id),
        action="update_private_api_key",
        resource_type="user_api_keys",
        resource_id=normalized_service,
        outcome="success",
        detail="set_api_key",
    )


def remove_api_key(user_id: str, service: str) -> bool:
    return db.delete_user_api_key(user_id, normalize_service(service))


def list_user_keys(user_id: str) -> list[dict]:
    items = db.get_user_api_keys(user_id)
    enriched = []
    for item in items:
        inspection = _inspect_stored_key_record(
            item["service"],
            item.get("api_key", ""),
            updated_at=item.get("updated_at"),
        )
        enriched.append({
            "service": item["service"],
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "rotation_days": inspection["rotation_days"],
            "age_days": inspection["age_days"],
            "rotation_due": inspection["rotation_due"],
            "is_weak": inspection["is_weak"],
            "weak_reasons": inspection["weak_reasons"],
            "value_available": inspection["value_available"],
        })
    return enriched


def summarize_user_key_hygiene(user_id: str) -> dict:
    items = list_user_keys(user_id)
    rotation_due = [item for item in items if item["rotation_due"]]
    weak_items = [item for item in items if item["is_weak"]]
    return {
        "total_keys": len(items),
        "rotation_due_count": len(rotation_due),
        "weak_key_count": len(weak_items),
        "rotation_due_services": [item["service"] for item in rotation_due],
        "weak_key_services": [item["service"] for item in weak_items],
        "advisory_only": True,
        "items": items,
        "status": "warn" if rotation_due or weak_items else "ok",
    }


def summarize_workspace_key_hygiene() -> dict:
    items = db.get_all_user_api_keys()
    total_keys = 0
    rotation_due_count = 0
    weak_key_count = 0
    impacted_users: set[str] = set()

    for item in items:
        total_keys += 1
        inspection = _inspect_stored_key_record(
            item["service"],
            item.get("api_key", ""),
            updated_at=item.get("updated_at"),
        )
        if inspection["rotation_due"] or inspection["is_weak"]:
            impacted_users.add(str(item["user_id"]))
        if inspection["rotation_due"]:
            rotation_due_count += 1
        if inspection["is_weak"]:
            weak_key_count += 1

    return {
        "total_keys": total_keys,
        "rotation_due_count": rotation_due_count,
        "weak_key_count": weak_key_count,
        "impacted_user_count": len(impacted_users),
        "advisory_only": True,
        "status": "warn" if rotation_due_count or weak_key_count else "ok",
    }


def backfill_plaintext_user_api_keys() -> dict:
    items = db.get_all_user_api_keys()
    plaintext_items = [item for item in items if not is_encrypted_api_key_value(item.get("api_key", "")) and (item.get("api_key") or "").strip()]

    if not config.ENCRYPTION_KEY:
        if plaintext_items:
            log.warning(
                "ENCRYPTION_KEY not set; skipped user_api_keys backfill for %s plaintext rows",
                len(plaintext_items),
            )
        return {
            "status": "skipped",
            "total_keys": len(items),
            "plaintext_rows": len(plaintext_items),
            "migrated_rows": 0,
        }

    migrated_rows = 0
    with db.get_conn() as conn:
        for item in plaintext_items:
            conn.execute(
                "UPDATE user_api_keys SET api_key = ? WHERE user_id = ? AND service = ?",
                (_encrypt(item["api_key"].strip()), str(item["user_id"]), item["service"]),
            )
            migrated_rows += 1

    if migrated_rows:
        log.info("Migration: encrypted %s legacy plaintext rows in user_api_keys", migrated_rows)

    return {
        "status": "ok",
        "total_keys": len(items),
        "plaintext_rows": len(plaintext_items),
        "migrated_rows": migrated_rows,
    }


def get_plaintext_user_api_key_report() -> dict:
    items = db.get_all_user_api_keys()
    plaintext_items = []
    encrypted_count = 0

    for item in items:
        stored_value = (item.get("api_key") or "").strip()
        if is_encrypted_api_key_value(stored_value):
            encrypted_count += 1
            continue
        if not stored_value:
            continue
        plaintext_items.append({
            "user_id": str(item["user_id"]),
            "service": item["service"],
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "value_length": len(stored_value),
        })

    return {
        "total_keys": len(items),
        "encrypted_count": encrypted_count,
        "plaintext_count": len(plaintext_items),
        "items": plaintext_items,
        "encryption_key_configured": bool(config.ENCRYPTION_KEY),
    }


def get_supported_services() -> list[str]:
    services = set(PRIVATE_ONLY_SERVICES)
    services.update(ENV_KEY_MAP.keys())
    return sorted(services)


def _encrypt(value: str) -> str:
    fernet = _get_fernet()
    if fernet is None:
        raise RuntimeError("ENCRYPTION_KEY is required for private key storage")
    return fernet.encrypt(value.encode()).decode()


def _looks_encrypted(value: str) -> bool:
    return (value or "").strip().startswith("gAAAA")


def is_encrypted_api_key_value(value: str) -> bool:
    return _looks_encrypted(value)


def _inspect_stored_key_record(service: str, stored_value: str, *, updated_at: str | None = None) -> dict:
    decrypted_value = _decrypt(stored_value)
    if decrypted_value is None:
        rotation_days = get_rotation_period_days(service)
        updated_dt = _parse_iso_datetime(updated_at)
        age_days = None
        rotation_due = False
        if updated_dt is not None:
            age_days = max((_utc_now() - updated_dt).days, 0)
            rotation_due = age_days >= rotation_days
        return {
            "service": normalize_service(service),
            "is_weak": False,
            "weak_reasons": [],
            "rotation_days": rotation_days,
            "age_days": age_days,
            "rotation_due": rotation_due,
            "value_available": False,
        }

    inspection = inspect_api_key_value(
        service,
        decrypted_value,
        updated_at=updated_at,
    )
    inspection["value_available"] = True
    return inspection


def _decrypt(value: str) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return ""

    fernet_chain = _get_fernet_chain()
    if not fernet_chain:
        if _looks_encrypted(normalized):
            log.warning("ENCRYPTION_KEY not set while reading encrypted stored private key")
            return None
        return normalized

    for fernet in fernet_chain:
        try:
            return fernet.decrypt(normalized.encode()).decode()
        except InvalidToken:
            continue

    if _looks_encrypted(normalized):
        log.warning("Stored private key could not be decrypted with configured encryption keyring")
        return None
    return normalized


def _log_security_audit_best_effort(**kwargs):
    try:
        db.log_security_audit(**kwargs)
    except Exception:
        # Do not block auth/runtime flows if audit write fails.
        pass


def rotate_user_api_key_encryption() -> dict:
    """Re-encrypt all private API key rows using the current primary ENCRYPTION_KEY."""
    primary = _get_fernet()
    if primary is None:
        raise RuntimeError("ENCRYPTION_KEY is required for private key rotation")

    items = db.get_all_user_api_keys()
    rotated_rows = 0
    skipped_rows = 0

    with db.get_conn() as conn:
        for item in items:
            stored = (item.get("api_key") or "").strip()
            if not stored:
                skipped_rows += 1
                continue

            plain = _decrypt(stored)
            if plain is None:
                skipped_rows += 1
                continue

            new_cipher = _encrypt(plain)
            if new_cipher == stored:
                skipped_rows += 1
                continue

            conn.execute(
                "UPDATE user_api_keys SET api_key = ?, updated_at = ? WHERE user_id = ? AND service = ?",
                (new_cipher, datetime.now().isoformat(), str(item["user_id"]), item["service"]),
            )
            rotated_rows += 1

    return {
        "total_rows": len(items),
        "rotated_rows": rotated_rows,
        "skipped_rows": skipped_rows,
    }