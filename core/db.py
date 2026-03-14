"""SQLite database — WAL mode, multi-tenant ready, thread-local connection pool"""

import sqlite3
import threading
from datetime import datetime
from core.config import DB_FILE
from core.logger import get_logger

log = get_logger(__name__)

# Thread-local storage — แต่ละ thread reuse connection ของตัวเอง
_local = threading.local()

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
    conversation_id   TEXT,
    created_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_user_time
    ON chat_history(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    is_active       INTEGER DEFAULT 1,
    message_count   INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_user_time
    ON conversations(user_id, updated_at DESC);

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

CREATE TABLE IF NOT EXISTS user_locations (
    user_id           TEXT PRIMARY KEY,
    latitude          REAL NOT NULL,
    longitude         REAL NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    chat_id    TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    message     TEXT NOT NULL,
    source      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    ran_at       TEXT NOT NULL,
    status       TEXT DEFAULT 'success'
);

CREATE INDEX IF NOT EXISTS idx_job_runs_job_time
    ON job_runs(job_id, scheduled_at DESC);
"""


def get_conn() -> sqlite3.Connection:
    """Return thread-local connection — reuse ภายใน thread เดียวกัน"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")  # ตรวจว่า connection ยังใช้ได้
            return conn
        except sqlite3.ProgrammingError:
            # Connection ถูกปิดไปแล้ว → สร้างใหม่
            _local.conn = None

    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _local.conn = conn
    return conn


def init_db():
    """สร้างตารางทั้งหมด + migration สำหรับ column ใหม่"""
    with get_conn() as conn:
        conn.executescript(_CREATE_TABLES)

    # Migration: เพิ่ม conversation_id column ถ้ายังไม่มี (DB เดิมก่อนมี feature นี้)
    try:
        get_conn().execute("ALTER TABLE chat_history ADD COLUMN conversation_id TEXT")
        log.info("Migration: added conversation_id column to chat_history")
    except Exception:
        pass  # column exists already

    # สร้าง index หลัง migration เพื่อให้มั่นใจว่า column มีแล้ว
    with get_conn() as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_conversation ON chat_history(conversation_id, created_at DESC)")

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
                default_llm: str = None, timezone: str = None):
    from core.config import DEFAULT_LLM, TIMEZONE as DEFAULT_TIMEZONE
    default_llm = default_llm or DEFAULT_LLM
    timezone = timezone or DEFAULT_TIMEZONE
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


def get_all_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def deactivate_user(chat_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0, updated_at = ? WHERE telegram_chat_id = ?",
            (datetime.now().isoformat(), str(chat_id))
        )


def update_user_preference(user_id: str, key: str, value: str):
    allowed = {"default_llm", "timezone"}
    if key not in allowed:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {key} = ?, updated_at = ? WHERE user_id = ?",
            (value, datetime.now().isoformat(), user_id)
        )


# === Conversations ===

def create_conversation(user_id: str, title: str = None) -> str:
    """สร้าง conversation ใหม่ return conversation_id"""
    import uuid
    conv_id = str(uuid.uuid4())[:8]  # short ID เพียงพอสำหรับ Telegram
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)",
            (conv_id, user_id, title)
        )
    return conv_id


def get_active_conversation(user_id: str) -> str | None:
    """ดึง conversation ล่าสุดที่ active ของ user"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE user_id = ? AND is_active = 1 ORDER BY updated_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        return row[0] if row else None


def update_conversation(conv_id: str, title: str = None):
    """อัปเดต updated_at (และ title ถ้าส่งมา)"""
    with get_conn() as conn:
        if title:
            conn.execute(
                "UPDATE conversations SET updated_at = datetime('now'), title = ?, message_count = message_count + 1 WHERE id = ?",
                (title, conv_id)
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = datetime('now'), message_count = message_count + 1 WHERE id = ?",
                (conv_id,)
            )


def end_conversation(conv_id: str):
    """ปิด conversation (ใช้เมื่อ user สั่ง /new)"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET is_active = 0 WHERE id = ?",
            (conv_id,)
        )


def get_conversation_history(conv_id: str, limit: int = 20) -> list:
    """ดึง messages ของ conversation เฉพาะ"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, tool_used, created_at FROM chat_history WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
            (conv_id, limit)
        ).fetchall()
        return [{"role": r[0], "content": r[1], "tool_used": r[2], "created_at": r[3]} for r in reversed(rows)]


def list_conversations(user_id: str, limit: int = 10) -> list:
    """ดึงรายการ conversations ของ user"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, updated_at, message_count FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [{"id": r[0], "title": r[1], "updated_at": r[2], "message_count": r[3]} for r in rows]


def get_conversation_title(conv_id: str) -> str | None:
    """ดึง title ของ conversation"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?",
            (conv_id,)
        ).fetchone()
        return row[0] if row else None


def get_last_message_time(conv_id: str):
    """ดึงเวลา message ล่าสุดของ conversation"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT created_at FROM chat_history WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
            (conv_id,)
        ).fetchone()
        if row:
            return datetime.fromisoformat(row[0])
        return None


# === Chat history (Memory) ===

def save_chat(user_id: str, role: str, content: str,
              tool_used: str = None, llm_model: str = None, token_used: int = None,
              conversation_id: str = None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO chat_history (user_id, role, content, tool_used, llm_model, token_used, conversation_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, role, content, tool_used, llm_model, token_used,
              conversation_id, datetime.now().isoformat()))


def get_chat_context(user_id: str, limit: int = 10, conversation_id: str = None) -> list[dict]:
    with get_conn() as conn:
        if conversation_id:
            # ใช้ conversation_id filter — ได้เฉพาะ context ของ conversation นั้น
            rows = conn.execute("""
                SELECT role, content, tool_used FROM chat_history
                WHERE user_id = ? AND conversation_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (user_id, conversation_id, limit)).fetchall()
        else:
            # fallback: ดึงจาก user ทั้งหมด (backward compatible)
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


def add_schedule(user_id: str, tool_name: str, cron_expr: str, args: str = "") -> int:
    """เพิ่ม schedule ใหม่ → return id"""
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO schedules (user_id, tool_name, cron_expr, args, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            (user_id, tool_name, cron_expr, args),
        )
        return cursor.lastrowid


def remove_schedule(schedule_id: int, user_id: str) -> bool:
    """Soft-delete schedule (is_active=0). user_id filter ป้องกันลบของคนอื่น"""
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE schedules SET is_active = 0 WHERE id = ? AND user_id = ?",
            (schedule_id, user_id),
        )
        return cursor.rowcount > 0


def get_user_schedules(user_id: str) -> list[dict]:
    """ดึง active schedules ของ user คนเดียว"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedules WHERE user_id = ? AND is_active = 1 ORDER BY id",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_schedule_by_id(schedule_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,),
        ).fetchone()
        return dict(row) if row else None


def schedule_exists(user_id: str, tool_name: str, cron_expr: str) -> bool:
    """ตรวจว่ามี schedule เหมือนกันอยู่แล้วหรือไม่"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM schedules "
            "WHERE user_id = ? AND tool_name = ? AND cron_expr = ? AND is_active = 1",
            (user_id, tool_name, cron_expr),
        ).fetchone()
        return row is not None


# === User locations ===

def save_location(user_id: str, lat: float, lng: float):
    """บันทึกตำแหน่ง GPS ล่าสุดของ user (upsert)"""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_locations (user_id, latitude, longitude, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                updated_at=excluded.updated_at
        """, (str(user_id), lat, lng, now))


def save_oauth_state(state: str, user_id: str, chat_id: str, expires_at: str):
    """บันทึก OAuth state สำหรับ Gmail callback"""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_states (state, user_id, chat_id, expires_at) VALUES (?, ?, ?, ?)",
            (state, user_id, chat_id, expires_at)
        )


def get_oauth_state(state: str) -> dict | None:
    """ดึง + ลบ OAuth state (single-use) — return None ถ้าหมดอายุหรือไม่มี"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM oauth_states WHERE state = ? AND expires_at > datetime('now')",
            (state,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            return dict(row)
        return None


def get_location(user_id: str, ttl_minutes: int = 60) -> dict | None:
    """ดึงตำแหน่งล่าสุด — return None ถ้าไม่มีหรือหมดอายุ
    ttl_minutes=0 หมายถึงไม่หมดอายุ
    """
    with get_conn() as conn:
        if ttl_minutes > 0:
            row = conn.execute("""
                SELECT latitude, longitude, updated_at FROM user_locations
                WHERE user_id = ?
                  AND updated_at > datetime('now', ?)
            """, (str(user_id), f"-{ttl_minutes} minutes")).fetchone()
        else:
            row = conn.execute("""
                SELECT latitude, longitude, updated_at FROM user_locations
                WHERE user_id = ?
            """, (str(user_id),)).fetchone()

        if not row:
            return None
        return {"lat": row["latitude"], "lng": row["longitude"], "updated_at": row["updated_at"]}


# === Pending messages (สำหรับ scheduled jobs ที่ส่งไม่ได้) ===

def save_pending_message(chat_id: str, message: str, source: str = ""):
    """เก็บข้อความที่ส่งไม่ได้ไว้ส่งทีหลัง"""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO pending_messages (chat_id, message, source, created_at)
            VALUES (?, ?, ?, ?)
        """, (str(chat_id), message[:4000], source, datetime.now().isoformat()))


def get_pending_messages(chat_id: str) -> list[dict]:
    """ดึงข้อความค้างส่งสำหรับ chat_id นี้"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_messages WHERE chat_id = ? ORDER BY created_at",
            (str(chat_id),)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_pending_message(msg_id: int):
    """ลบข้อความค้างส่งที่ส่งสำเร็จแล้ว"""
    with get_conn() as conn:
        conn.execute("DELETE FROM pending_messages WHERE id = ?", (msg_id,))


def cleanup_old_pending(days: int = 7):
    """ลบข้อความค้างส่งที่เก่าเกิน N วัน"""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM pending_messages WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )


# === Job runs (สำหรับ catchup logic) ===

def log_job_run(job_id: str, scheduled_at: str, status: str = "success"):
    """บันทึกว่า scheduled job รันแล้ว"""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO job_runs (job_id, scheduled_at, ran_at, status)
            VALUES (?, ?, ?, ?)
        """, (job_id, scheduled_at, datetime.now().isoformat(), status))


def get_last_job_run(job_id: str) -> dict | None:
    """ดึง record การรันล่าสุดของ job_id นี้"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM job_runs
            WHERE job_id = ? AND status = 'success'
            ORDER BY scheduled_at DESC LIMIT 1
        """, (job_id,)).fetchone()
        return dict(row) if row else None


def cleanup_old_job_runs(days: int = 30):
    """ลบ job run records ที่เก่าเกิน N วัน"""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM job_runs WHERE ran_at < datetime('now', ?)",
            (f"-{days} days",)
        )
