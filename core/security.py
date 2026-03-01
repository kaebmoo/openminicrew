"""Security — Gmail token management + refresh"""

from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from core.config import CREDENTIALS_DIR, GMAIL_CREDENTIALS_FILE
from core.logger import get_logger

log = get_logger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_token_path(user_id: str) -> Path:
    return CREDENTIALS_DIR / f"gmail_{user_id}.json"


def get_gmail_credentials(user_id: str) -> Credentials | None:
    """
    ดึง Gmail credentials สำหรับ user
    - ถ้า token มีอยู่ + valid → ใช้เลย
    - ถ้า token expired → auto-refresh
    - ถ้าไม่มี token → fallback ใช้ token ของ owner (ถ้ามี)
    """
    from core.config import OWNER_TELEGRAM_CHAT_ID

    token_path = get_gmail_token_path(user_id)

    if not token_path.exists():
        if user_id != OWNER_TELEGRAM_CHAT_ID:
            log.debug(f"No Gmail token for user {user_id}, falling back to owner token")
            return get_gmail_credentials(OWNER_TELEGRAM_CHAT_ID)
        log.warning(f"No Gmail token for owner {user_id} — run authorize_gmail_interactive()")
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            log.info(f"Refreshing Gmail token for user {user_id}")
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
                return creds
            except Exception as refresh_err:
                log.error(f"Gmail token refresh failed for user {user_id}: {refresh_err}")
                return None

        log.warning(f"Gmail token invalid for user {user_id}, re-auth needed")
        return None

    except Exception as e:
        log.error(f"Gmail credential error for user {user_id}: {e}")
        return None


def authorize_gmail_interactive(user_id: str) -> bool:
    """
    Interactive OAuth flow — ใช้ตอน setup ครั้งแรกบนเครื่อง owner
    เปิด browser ให้ login + authorize
    """
    if not GMAIL_CREDENTIALS_FILE.exists():
        log.error(f"Missing {GMAIL_CREDENTIALS_FILE}")
        return False

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(GMAIL_CREDENTIALS_FILE), GMAIL_SCOPES
        )
        creds = flow.run_local_server(port=0)

        token_path = get_gmail_token_path(user_id)
        token_path.write_text(creds.to_json())
        log.info(f"Gmail authorized for user {user_id}")
        return True

    except Exception as e:
        log.error(f"Gmail authorization failed: {e}")
        return False
