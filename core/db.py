"""SQLite database — WAL mode, multi-tenant ready"""

import sqlite3
from datetime import datetime
from core.config import DB_FILE
from core.logger import get_logger

log = get_logger(__name__)

_CREATE_TABLES = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id           TEXT PRIMARY KEY,
    telegram_chat_id  TEXT UNIQUE NOT NULL,
    display_name      TEXT,
    role              TEXT DEFAULT 'user',
    default_llm       TEXT DEFAULT 'claude',
    timezone          TEXT DEFAULT 'Asia/Bangkok',
    gmail_authorized  INTEGER DEFAULT 0,
    is_active         INTEGER DEFAULT 1,
    created_at        TEXT,
    updated_at        TEXT
);

CREATE TABLE IF NOT EXISTS chat_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    role              TEXT NOT NULL,
    content           TEXT NOT NULL,
    tool_used         TEXT,
    llm_model         TEXT,
    token_used        INTEGER,
    created_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_user_time
    ON chat_history(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS processed_emails (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    message_id        TEXT NOT NULL,
    subject           TEXT,
    sender            TEXT,
    processed_at      TEXT,
    UNIQUE(user_id, message_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS tool_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    tool_name         TEXT NOT NULL,
    input_summary     TEXT,
    output_summary    TEXT,
    llm_model         TEXT,
    token_used        INTEGER,
    status            TEXT,
    error_message     TEXT,
    created_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS schedules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    tool_name         TEXT NOT NULL,
    cron_expr         TEXT NOT NULL,
    args              TEXT,
    is_active         INTEGER DEFAULT 1,
    last_run_at       TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """สร้างตารางทั้งหมด"""
    with get_conn() as conn:
        conn.executescript(_CREATE_TABLES)
    log.info("Database initialized")


def check_health() -> dict:
    """ตรวจสถานะ DB สำหรับ /health"""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return {"db": "ok"}
    except Exception as e:
        return {"db": f"error: {e}"}


# === User operations ===

def get_user_by_chat_id(chat_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_chat_id = ? AND is_active = 1",
            (str(chat_id),)
        ).fetchone()
        return dict(row) if row else None


def upsert_user(user_id: str, chat_id: str, display_name: str, role: str = "user",
                default_llm: str = "claude", timezone: str = "Asia/Bangkok"):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, telegram_chat_id, display_name, role,
                             default_llm, timezone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name,
                updated_at=?
        """, (user_id, str(chat_id), display_name, role,
              default_llm, timezone, now, now, now))


def update_user_preference(user_id: str, key: str, value: str):
    allowed = {"default_llm", "timezone"}
    if key not in allowed:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {key} = ?, updated_at = ? WHERE user_id = ?",
            (value, datetime.now().isoformat(), user_id)
        )


# === Chat history (Memory) ===

def save_chat(user_id: str, role: str, content: str,
              tool_used: str = None, llm_model: str = None, token_used: int = None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO chat_history (user_id, role, content, tool_used, llm_model, token_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, role, content, tool_used, llm_model, token_used,
              datetime.now().isoformat()))


def get_chat_context(user_id: str, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT role, content, tool_used FROM chat_history
            WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]


def cleanup_old_chats(days: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM chat_history WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )


# === Processed emails ===

def is_email_processed(user_id: str, message_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_emails WHERE user_id = ? AND message_id = ?",
            (user_id, message_id)
        ).fetchone()
        return row is not None


def mark_email_processed(user_id: str, message_id: str, subject: str, sender: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO processed_emails (user_id, message_id, subject, sender, processed_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, message_id, subject, sender, datetime.now().isoformat()))


def cleanup_old_emails(days: int = 90):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM processed_emails WHERE processed_at < datetime('now', ?)",
            (f"-{days} days",)
        )


# === Tool logs (doubles as dead letter queue) ===

def log_tool_usage(user_id: str, tool_name: str, input_summary: str = "",
                   output_summary: str = "", llm_model: str = "",
                   token_used: int = 0, status: str = "success",
                   error_message: str = ""):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO tool_logs (user_id, tool_name, input_summary, output_summary,
                                  llm_model, token_used, status, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, tool_name, input_summary[:500], output_summary[:500],
              llm_model, token_used, status, error_message[:1000],
              datetime.now().isoformat()))


def cleanup_old_logs(days: int = 90):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM tool_logs WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )


# === Schedules ===

def get_active_schedules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE is_active = 1"
        ).fetchall()
        return [dict(r) for r in rows]


def update_schedule_last_run(schedule_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE schedules SET last_run_at = ? WHERE id = ?",
            (datetime.now().isoformat(), schedule_id)
        )


def get_last_scheduler_run() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(last_run_at) as last FROM schedules"
        ).fetchone()
        return row["last"] if row else None
