"""Security — Gmail token management + refresh"""

import json
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from core import config
from core.config import CREDENTIALS_DIR, GMAIL_CREDENTIALS_FILE
from core.logger import get_logger

log = get_logger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

SENSITIVE_FIELD_PREFIX = "enc:"


def get_gmail_token_path(user_id: str) -> Path:
    return CREDENTIALS_DIR / f"gmail_{user_id}.json"


def secure_file_permissions(file_path: Path, *, strict: bool = True):
    try:
        current_mode = file_path.stat().st_mode & 0o777
    except OSError as err:
        if strict:
            raise RuntimeError(f"Failed to inspect permissions for {file_path.name}: {err}") from err
        log.warning("Failed to inspect permissions for %s: %s", file_path.name, err)
        return

    desired_mode = 0o600
    if current_mode == desired_mode:
        return

    try:
        os.chmod(file_path, desired_mode)
        log.info("Adjusted permissions for %s to 600", file_path.name)
    except OSError as err:
        if strict:
            raise RuntimeError(f"Failed to secure permissions for {file_path.name}: {err}") from err
        log.warning("Failed to secure permissions for %s: %s", file_path.name, err)


def ensure_gmail_credentials_file_secure() -> bool:
    if not GMAIL_CREDENTIALS_FILE.exists():
        log.error("Missing %s", GMAIL_CREDENTIALS_FILE)
        return False

    try:
        secure_file_permissions(GMAIL_CREDENTIALS_FILE, strict=False)
        return True
    except RuntimeError:
        return False


def _get_token_cipher() -> Fernet | None:
    if not config.ENCRYPTION_KEY:
        return None
    return Fernet(config.ENCRYPTION_KEY.encode())


def is_sensitive_field_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(SENSITIVE_FIELD_PREFIX)


def encrypt_sensitive_field(value: str, *, field_name: str = "sensitive field") -> str:
    cipher = _get_token_cipher()
    if cipher is None:
        raise RuntimeError(f"ENCRYPTION_KEY is required for {field_name} storage")
    return SENSITIVE_FIELD_PREFIX + cipher.encrypt(value.encode()).decode()


def decrypt_sensitive_field(value: str | None, *, field_name: str = "sensitive field") -> str | None:
    if not value:
        return value
    if not is_sensitive_field_encrypted(value):
        return value

    cipher = _get_token_cipher()
    if cipher is None:
        log.warning("ENCRYPTION_KEY not set while reading encrypted %s", field_name)
        return None

    try:
        return cipher.decrypt(value[len(SENSITIVE_FIELD_PREFIX):].encode()).decode()
    except InvalidToken:
        log.error("Failed to decrypt encrypted %s", field_name)
        return None


def _decrypt_token_payload(payload: str) -> str:
    cipher = _get_token_cipher()
    if cipher is None:
        return payload
    try:
        return cipher.decrypt(payload.encode()).decode()
    except InvalidToken:
        return payload


def _encrypt_token_payload(payload: str) -> str:
    cipher = _get_token_cipher()
    if cipher is None:
        raise RuntimeError("ENCRYPTION_KEY is required for Gmail token storage")
    return cipher.encrypt(payload.encode()).decode()


def _read_gmail_client_secrets_payload() -> tuple[str, bool]:
    raw_payload = GMAIL_CREDENTIALS_FILE.read_text(encoding="utf-8")

    if not config.ENCRYPTION_KEY:
        return raw_payload, False

    decrypted_payload = _decrypt_token_payload(raw_payload)
    stored_encrypted = decrypted_payload != raw_payload or not raw_payload.lstrip().startswith("{")
    return decrypted_payload, stored_encrypted


def _parse_gmail_client_config(payload: str) -> dict:
    client_config = json.loads(payload)
    if not isinstance(client_config, dict) or not any(key in client_config for key in ("installed", "web")):
        raise ValueError("Invalid Gmail client secrets JSON: expected top-level 'installed' or 'web'")
    return client_config


def write_gmail_client_secrets_payload(payload: str):
    encrypted_payload = _encrypt_token_payload(payload)
    GMAIL_CREDENTIALS_FILE.write_text(encrypted_payload, encoding="utf-8")
    secure_file_permissions(GMAIL_CREDENTIALS_FILE)


def _migrate_plaintext_gmail_client_secrets_if_needed(payload: str, stored_encrypted: bool):
    if stored_encrypted or not config.ENCRYPTION_KEY:
        return

    try:
        write_gmail_client_secrets_payload(payload)
        log.info("Migrated credentials.json to encrypted storage")
    except (OSError, ValueError, TypeError, RuntimeError) as err:
        log.warning("Failed to migrate credentials.json to encrypted storage: %s", err)


def get_gmail_client_config() -> dict | None:
    if not GMAIL_CREDENTIALS_FILE.exists():
        log.error("Missing %s", GMAIL_CREDENTIALS_FILE)
        return None

    if not ensure_gmail_credentials_file_secure():
        return None

    try:
        payload, stored_encrypted = _read_gmail_client_secrets_payload()

        if not config.ENCRYPTION_KEY and not payload.lstrip().startswith("{"):
            log.error("Encrypted credentials.json cannot be read without ENCRYPTION_KEY")
            return None

        client_config = _parse_gmail_client_config(payload)
        _migrate_plaintext_gmail_client_secrets_if_needed(payload, stored_encrypted)
        return client_config
    except (OSError, ValueError, TypeError) as err:
        log.error("Failed to load Gmail client secrets: %s", err)
        return None


def import_gmail_client_secrets(source_path: str | Path):
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Gmail client secrets file not found: {source}")
    if not config.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is required for Gmail client secret storage")

    payload = source.read_text(encoding="utf-8")
    _parse_gmail_client_config(payload)
    write_gmail_client_secrets_payload(payload)
    return GMAIL_CREDENTIALS_FILE


def _read_token_payload(token_path: Path) -> tuple[str, bool]:
    raw_payload = token_path.read_text()

    if not config.ENCRYPTION_KEY:
        return raw_payload, False

    decrypted_payload = _decrypt_token_payload(raw_payload)
    stored_encrypted = decrypted_payload != raw_payload or not raw_payload.lstrip().startswith("{")
    return decrypted_payload, stored_encrypted


def write_gmail_token_payload(token_path: Path, payload: str):
    token_path.write_text(_encrypt_token_payload(payload))
    secure_file_permissions(token_path)


def _migrate_plaintext_token_if_needed(token_path: Path, payload: str, stored_encrypted: bool):
    if stored_encrypted or not config.ENCRYPTION_KEY:
        return

    try:
        write_gmail_token_payload(token_path, payload)
        log.info("Migrated Gmail token file to encrypted storage: %s", token_path.name)
    except (OSError, ValueError, TypeError) as err:
        log.warning("Failed to migrate Gmail token file %s: %s", token_path.name, err)


def get_gmail_credentials(user_id: str) -> Credentials | None:
    """
    ดึง Gmail credentials สำหรับ user
    - ถ้า token มีอยู่ + valid → ใช้เลย
    - ถ้า token expired → auto-refresh
    - ถ้าไม่มี token → return None (ห้าม fallback ข้าม user)
    """
    token_path = get_gmail_token_path(user_id)

    if not token_path.exists():
        log.warning("No Gmail token for user %s - run authorize_gmail_interactive()", user_id)
        return None

    try:
        token_payload, stored_encrypted = _read_token_payload(token_path)

        if not config.ENCRYPTION_KEY and not token_payload.lstrip().startswith("{"):
            log.error("Encrypted Gmail token for user %s cannot be read without ENCRYPTION_KEY", user_id)
            return None

        creds = Credentials.from_authorized_user_info(json.loads(token_payload), GMAIL_SCOPES)

        if creds and creds.valid:
            _migrate_plaintext_token_if_needed(token_path, creds.to_json(), stored_encrypted)
            return creds

        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing Gmail token for user %s", user_id)
            try:
                creds.refresh(Request())
                write_gmail_token_payload(token_path, creds.to_json())
                return creds
            except (RefreshError, GoogleAuthError, OSError, ValueError, TypeError, RuntimeError) as refresh_err:
                log.error("Gmail token refresh failed for user %s: %s", user_id, refresh_err)
                return None

        log.warning("Gmail token invalid for user %s, re-auth needed", user_id)
        return None

    except (OSError, ValueError, TypeError, GoogleAuthError) as err:
        log.error("Gmail credential error for user %s: %s", user_id, err)
        return None


def authorize_gmail_interactive(user_id: str) -> bool:
    """
    Interactive OAuth flow — ใช้ตอน setup ครั้งแรกบนเครื่อง owner
    เปิด browser ให้ login + authorize
    """
    if not config.ENCRYPTION_KEY:
        log.error("ENCRYPTION_KEY is required before authorizing Gmail tokens")
        return False

    try:
        client_config = get_gmail_client_config()
        if client_config is None:
            return False

        flow = InstalledAppFlow.from_client_config(client_config, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)

        token_path = get_gmail_token_path(user_id)
        write_gmail_token_payload(token_path, creds.to_json())
        log.info("Gmail authorized for user %s", user_id)

        # อัปเดต DB ให้ gmail_authorized = 1
        try:
            from core.db import get_conn
            from datetime import datetime
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET gmail_authorized = 1, updated_at = ? WHERE user_id = ?",
                    (datetime.now().isoformat(), str(user_id)),
                )
            from core import db
            db.set_user_consent(user_id, db.CONSENT_GMAIL, db.CONSENT_STATUS_GRANTED, source="gmail_oauth_interactive")
        except sqlite3.Error as db_err:
            log.warning("Failed to update gmail_authorized in DB: %s", db_err)

        return True

    except (OSError, ValueError, TypeError, GoogleAuthError, RuntimeError) as err:
        log.error("Gmail authorization failed: %s", err)
        return False
