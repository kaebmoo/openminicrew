"""Gmail OAuth — per-user authorization flow via webhook callback"""

import secrets
from datetime import datetime, timedelta

from google.auth.exceptions import GoogleAuthError
from google_auth_oauthlib.flow import Flow

from core.config import GMAIL_CREDENTIALS_FILE, WEBHOOK_HOST
from core.security import (
    GMAIL_SCOPES,
    ensure_gmail_credentials_file_secure,
    get_gmail_token_path,
    write_gmail_token_payload,
)
from core import db
from core.logger import get_logger

log = get_logger(__name__)

CALLBACK_PATH = "/gmail-callback"


def get_redirect_uri() -> str:
    return f"{WEBHOOK_HOST}{CALLBACK_PATH}"


def generate_auth_url(user_id: str, chat_id: str) -> str | None:
    """
    สร้าง OAuth URL สำหรับ user ที่ต้องการ authorize Gmail
    - return URL string ถ้าสำเร็จ
    - return None ถ้า credentials.json ไม่มีหรือไม่ได้ตั้งค่า WEBHOOK_HOST
    """
    if not ensure_gmail_credentials_file_secure():
        return None
    if not WEBHOOK_HOST:
        log.warning("WEBHOOK_HOST not configured")
        return None

    state = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(minutes=15)).isoformat()
    db.save_oauth_state(state, user_id, str(chat_id), expires_at)

    flow = Flow.from_client_secrets_file(
        str(GMAIL_CREDENTIALS_FILE),
        scopes=GMAIL_SCOPES,
        redirect_uri=get_redirect_uri(),
    )
    auth_url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        prompt="consent",
    )
    return auth_url


def complete_oauth(code: str, state: str) -> tuple[str, str] | None:
    """
    แลก authorization code เป็น token แล้วบันทึก
    - return (user_id, chat_id) เพื่อแจ้งผู้ใช้
    - return None ถ้า state หมดอายุหรือ token exchange ล้มเหลว
    """
    record = db.get_oauth_state(state)
    if not record:
        log.warning("OAuth state not found or expired: %s...", state[:8])
        return None

    user_id = record["user_id"]
    chat_id = record["chat_id"]

    try:
        flow = Flow.from_client_secrets_file(
            str(GMAIL_CREDENTIALS_FILE),
            scopes=GMAIL_SCOPES,
            redirect_uri=get_redirect_uri(),
            state=state,
        )
        flow.fetch_token(code=code)

        token_path = get_gmail_token_path(user_id)
        write_gmail_token_payload(token_path, flow.credentials.to_json())
        log.info("Gmail OAuth completed for user %s", user_id)
        return user_id, chat_id

    except (OSError, ValueError, TypeError, GoogleAuthError, RuntimeError) as err:
        log.error("OAuth token exchange failed for user %s: %s", user_id, err)
        return None
