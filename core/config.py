"""โหลด configuration จาก .env — validate ทุกค่าที่จำเป็น"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        print(f"[ERROR] Missing required env: {key}")
        print(f"        ตั้งค่าใน {BASE_DIR / '.env'}")
        sys.exit(1)
    return val


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# === Bot Mode ===
BOT_MODE = _optional("BOT_MODE", "polling")  # polling | webhook

# === Webhook ===
WEBHOOK_HOST = _optional("WEBHOOK_HOST", "")
WEBHOOK_PORT = int(_optional("WEBHOOK_PORT", "8443"))
WEBHOOK_PATH = _optional("WEBHOOK_PATH", "/bot/webhook")
TELEGRAM_WEBHOOK_SECRET = _optional("TELEGRAM_WEBHOOK_SECRET", "")

# === Owner ===
OWNER_TELEGRAM_CHAT_ID = _require("OWNER_TELEGRAM_CHAT_ID")
OWNER_DISPLAY_NAME = _optional("OWNER_DISPLAY_NAME", "Owner")

# === LLM ===
DEFAULT_LLM = _optional("DEFAULT_LLM", "claude")
ANTHROPIC_API_KEY = _optional("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = _optional("GEMINI_API_KEY", "")

CLAUDE_MODEL_CHEAP = _optional("CLAUDE_MODEL_CHEAP", "claude-haiku-4-5-20251001")
CLAUDE_MODEL_MID = _optional("CLAUDE_MODEL_MID", "claude-sonnet-4-5-20250929")

GEMINI_MODEL_CHEAP = _optional("GEMINI_MODEL_CHEAP", "gemini-2.5-flash")
GEMINI_MODEL_MID = _optional("GEMINI_MODEL_MID", "gemini-2.5-pro")

# === Telegram ===
TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")

# === Gmail ===
GMAIL_MAX_RESULTS = int(_optional("GMAIL_MAX_RESULTS", "30"))

# === Memory ===
MAX_CONTEXT_MESSAGES = int(_optional("MAX_CONTEXT_MESSAGES", "10"))
CHAT_HISTORY_RETENTION_DAYS = int(_optional("CHAT_HISTORY_RETENTION_DAYS", "30"))

# === Schedule ===
TIMEZONE = _optional("TIMEZONE", "Asia/Bangkok")
MORNING_BRIEFING_TIME = _optional("MORNING_BRIEFING_TIME", "07:00")

# === Paths ===
CREDENTIALS_DIR = BASE_DIR / "credentials"
CREDENTIALS_DIR.mkdir(exist_ok=True)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
DB_FILE = DATA_DIR / "openminicrew.db"
GMAIL_CREDENTIALS_FILE = BASE_DIR / "credentials.json"  # OAuth client secret
