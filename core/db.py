"""SQLite database — WAL mode, multi-tenant ready, thread-local connection pool"""

import hashlib
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
    phone_number      TEXT,
    status            TEXT DEFAULT 'active',
    role              TEXT DEFAULT 'user',
    default_llm       TEXT DEFAULT 'gemini',
    smart_inbox_mode  TEXT DEFAULT 'confirm',
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
    sender_domain     TEXT,
    has_subject       INTEGER DEFAULT 0,
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
    input_kind        TEXT DEFAULT '',
    input_ref         TEXT DEFAULT '',
    input_size        INTEGER DEFAULT 0,
    output_kind       TEXT DEFAULT '',
    output_ref        TEXT DEFAULT '',
    output_size       INTEGER DEFAULT 0,
    llm_model         TEXT,
    token_used        INTEGER,
    status            TEXT,
    error_message     TEXT,
    error_kind        TEXT DEFAULT '',
    error_code        TEXT DEFAULT '',
    error_safe_message TEXT DEFAULT '',
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
    state          TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    chat_id        TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    code_verifier  TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS user_consents (
    user_id      TEXT NOT NULL,
    consent_type TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'not_set',
    source       TEXT DEFAULT '',
    granted_at   TEXT,
    revoked_at   TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, consent_type),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS user_api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    service     TEXT NOT NULL,
    api_key     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(user_id, service),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    text         TEXT NOT NULL,
    remind_at    TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',
    schedule_id  INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS todos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    title        TEXT NOT NULL,
    notes        TEXT DEFAULT '',
    priority     TEXT DEFAULT 'medium',
    status       TEXT DEFAULT 'open',
    due_at       TEXT,
    source_type  TEXT DEFAULT '',
    source_ref   TEXT DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT NOT NULL,
    amount        REAL NOT NULL,
    currency      TEXT DEFAULT 'THB',
    category      TEXT DEFAULT 'ทั่วไป',
    note          TEXT DEFAULT '',
    source_type   TEXT DEFAULT '',
    source_hash   TEXT DEFAULT '',
    expense_date  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
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

PROFILE_SECRET_FIELDS = ("phone_number", "national_id")
EXPENSE_SECRET_FIELDS = ("note",)
CONSENT_GMAIL = "gmail_access"
CONSENT_LOCATION = "location_access"
CONSENT_CHAT_HISTORY = "chat_history"
CONSENT_TYPES = (CONSENT_GMAIL, CONSENT_LOCATION, CONSENT_CHAT_HISTORY)
CONSENT_STATUS_GRANTED = "granted"
CONSENT_STATUS_REVOKED = "revoked"
CONSENT_STATUS_NOT_SET = "not_set"

REDACTED_REF_PREFIX = "sha256:"


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


def close_thread_local_connection():
    """Close the current thread-local SQLite connection if it exists."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


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

    try:
        get_conn().execute("ALTER TABLE users ADD COLUMN phone_number TEXT")
        log.info("Migration: added phone_number column to users")
    except Exception:
        pass

    try:
        get_conn().execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
        log.info("Migration: added status column to users")
    except Exception:
        pass

    try:
        get_conn().execute("ALTER TABLE users ADD COLUMN smart_inbox_mode TEXT DEFAULT 'confirm'")
        log.info("Migration: added smart_inbox_mode column to users")
    except Exception:
        pass

    try:
        get_conn().execute("ALTER TABLE users ADD COLUMN national_id TEXT")
        log.info("Migration: added national_id column to users")
    except Exception:
        pass

    try:
        get_conn().execute("ALTER TABLE oauth_states ADD COLUMN code_verifier TEXT DEFAULT ''")
        log.info("Migration: added code_verifier column to oauth_states")
    except Exception:
        pass

    for statement, column_name in [
        ("ALTER TABLE processed_emails ADD COLUMN sender_domain TEXT", "sender_domain"),
        ("ALTER TABLE processed_emails ADD COLUMN has_subject INTEGER DEFAULT 0", "has_subject"),
        ("ALTER TABLE tool_logs ADD COLUMN input_kind TEXT DEFAULT ''", "input_kind"),
        ("ALTER TABLE tool_logs ADD COLUMN input_ref TEXT DEFAULT ''", "input_ref"),
        ("ALTER TABLE tool_logs ADD COLUMN input_size INTEGER DEFAULT 0", "input_size"),
        ("ALTER TABLE tool_logs ADD COLUMN output_kind TEXT DEFAULT ''", "output_kind"),
        ("ALTER TABLE tool_logs ADD COLUMN output_ref TEXT DEFAULT ''", "output_ref"),
        ("ALTER TABLE tool_logs ADD COLUMN output_size INTEGER DEFAULT 0", "output_size"),
        ("ALTER TABLE tool_logs ADD COLUMN error_kind TEXT DEFAULT ''", "error_kind"),
        ("ALTER TABLE tool_logs ADD COLUMN error_code TEXT DEFAULT ''", "error_code"),
        ("ALTER TABLE tool_logs ADD COLUMN error_safe_message TEXT DEFAULT ''", "error_safe_message"),
        ("ALTER TABLE expenses ADD COLUMN source_type TEXT DEFAULT ''", "expenses.source_type"),
        ("ALTER TABLE expenses ADD COLUMN source_hash TEXT DEFAULT ''", "expenses.source_hash"),
    ]:
        try:
            get_conn().execute(statement)
            log.info("Migration: added %s column", column_name)
        except Exception:
            pass

    # สร้าง index หลัง migration เพื่อให้มั่นใจว่า column มีแล้ว
    with get_conn() as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_conversation ON chat_history(conversation_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_source_hash ON expenses(user_id, source_type, source_hash)")

    # Migration: เพิ่ม UNIQUE index บน job_runs(job_id, scheduled_at) ป้องกัน duplicate catchup
    try:
        with get_conn() as conn:
            # ลบ duplicate rows ก่อน (เก็บ row ที่มี rowid ต่ำสุดไว้)
            conn.execute("""
                DELETE FROM job_runs
                WHERE rowid NOT IN (
                    SELECT MIN(rowid) FROM job_runs GROUP BY job_id, scheduled_at
                )
            """)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_runs_unique "
                "ON job_runs(job_id, scheduled_at)"
            )
    except Exception:
        pass  # index exists already or table empty

    # Migration: rename tool email_summary → gmail_summary ใน 3 ตาราง
    _rename_tool("email_summary", "gmail_summary")
    from core.api_keys import backfill_plaintext_user_api_keys
    _backfill_user_consents()
    backfill_plaintext_user_api_keys()
    _minimize_processed_email_legacy_rows()
    _minimize_tool_log_legacy_rows()

    log.info("Database initialized")


def _fingerprint_text(value: str) -> str:
    return REDACTED_REF_PREFIX + hashlib.sha256(value.encode()).hexdigest()[:12]


def _summarize_text_field(value: str) -> tuple[str, str, int]:
    if not value:
        return "empty", "", 0

    normalized = value.strip()
    if not normalized:
        return "empty", "", 0

    kind = "text"
    if normalized.isdigit():
        kind = "numeric"
    elif len(normalized) <= 80 and all(ch.isalnum() or ch in " _-:/.,()[]" for ch in normalized):
        kind = "label"
    elif normalized[:1].isdigit() and any(ch.isalpha() for ch in normalized):
        kind = "count"

    return kind, _fingerprint_text(normalized), len(normalized)


def _make_text_ref(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        if not value:
            return ""
        return REDACTED_REF_PREFIX + hashlib.sha256(value).hexdigest()[:12]
    normalized = value.strip()
    if not normalized:
        return ""
    return _fingerprint_text(normalized)


def make_log_field(prefix: str, value: str | bytes | None = None, *, kind: str,
                   ref_value: str | bytes | None = None, size: int | None = None) -> dict:
    if prefix not in {"input", "output"}:
        raise ValueError(f"Unsupported log prefix: {prefix}")

    if isinstance(value, bytes):
        resolved_size = len(value) if size is None else size
    else:
        normalized = (value or "").strip() if isinstance(value, str) else ""
        resolved_size = len(normalized) if size is None else size

    reference_source = ref_value if ref_value is not None else value
    return {
        f"{prefix}_kind": kind,
        f"{prefix}_ref": _make_text_ref(reference_source),
        f"{prefix}_size": resolved_size or 0,
    }


def make_error_fields(error_message: str = "", *, kind: str = "", code: str = "",
                      safe_message: str = "") -> dict:
    if kind or code or safe_message:
        return {
            "error_kind": kind,
            "error_code": code,
            "error_safe_message": safe_message,
        }

    error_kind, error_code, error_safe_message = _redact_error_model(error_message)
    return {
        "error_kind": error_kind,
        "error_code": error_code,
        "error_safe_message": error_safe_message,
    }


def _redact_error_model(error_message: str) -> tuple[str, str, str]:
    if not error_message:
        return "", "", ""

    message = error_message.strip()
    lower = message.lower()

    if "timeout" in lower or "timed out" in lower:
        return "runtime", "timeout", "Operation timed out"
    if "auth" in lower or "permission" in lower or "unauthorized" in lower or "forbidden" in lower:
        return "access", "auth_failed", "Authentication or authorization failed"
    if "ssl" in lower or "certificate" in lower:
        return "network", "tls_error", "TLS or certificate validation failed"
    if "connect" in lower or "connection" in lower or "network" in lower:
        return "network", "connection_error", "Network connection failed"
    if "missing" in lower or "required" in lower or "config" in lower or "encryption_key" in lower:
        return "configuration", "config_error", "Required configuration is missing or invalid"
    if "invalid" in lower or "checksum" in lower or "format" in lower:
        return "validation", "invalid_input", "Input validation failed"

    return "runtime", "unknown_error", "Runtime error"


def _minimize_processed_email_legacy_rows():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, subject, sender, sender_domain, has_subject FROM processed_emails"
        ).fetchall()
        for row in rows:
            has_subject = row["has_subject"] if row["has_subject"] is not None else 0
            if not has_subject:
                has_subject = 1 if (row["subject"] or "").strip() else 0
            conn.execute(
                """
                UPDATE processed_emails
                SET sender_domain = NULL, has_subject = ?, subject = NULL, sender = NULL
                WHERE id = ?
                """,
                (has_subject, row["id"]),
            )


def _minimize_tool_log_legacy_rows():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, input_summary, output_summary, error_message,
                   input_kind, input_ref, input_size,
                   output_kind, output_ref, output_size,
                   error_kind, error_code, error_safe_message
            FROM tool_logs
            """
        ).fetchall()
        for row in rows:
            input_kind, input_ref, input_size = (
                row["input_kind"], row["input_ref"], row["input_size"]
            ) if row["input_kind"] else _summarize_text_field(row["input_summary"] or "")
            output_kind, output_ref, output_size = (
                row["output_kind"], row["output_ref"], row["output_size"]
            ) if row["output_kind"] else _summarize_text_field(row["output_summary"] or "")
            if row["error_kind"] or row["error_code"] or row["error_safe_message"]:
                error_kind = row["error_kind"]
                error_code = row["error_code"]
                error_safe_message = row["error_safe_message"]
            else:
                error_kind, error_code, error_safe_message = _redact_error_model(row["error_message"] or "")

            conn.execute(
                """
                UPDATE tool_logs
                SET input_kind = ?, input_ref = ?, input_size = ?,
                    output_kind = ?, output_ref = ?, output_size = ?,
                    error_kind = ?, error_code = ?, error_safe_message = ?,
                    input_summary = NULL, output_summary = NULL, error_message = NULL
                WHERE id = ?
                """,
                (
                    input_kind,
                    input_ref,
                    input_size,
                    output_kind,
                    output_ref,
                    output_size,
                    error_kind,
                    error_code,
                    error_safe_message,
                    row["id"],
                ),
            )


def _default_consent_status(consent_type: str, *, gmail_authorized: int = 0, has_location: bool = False) -> str:
    if consent_type == CONSENT_CHAT_HISTORY:
        return CONSENT_STATUS_GRANTED
    if consent_type == CONSENT_GMAIL:
        return CONSENT_STATUS_GRANTED if gmail_authorized else CONSENT_STATUS_NOT_SET
    if consent_type == CONSENT_LOCATION:
        return CONSENT_STATUS_GRANTED if has_location else CONSENT_STATUS_NOT_SET
    raise ValueError(f"Unknown consent type: {consent_type}")


def _backfill_user_consents():
    with get_conn() as conn:
        users = conn.execute("SELECT user_id, gmail_authorized FROM users").fetchall()
        location_users = {
            row["user_id"] for row in conn.execute("SELECT user_id FROM user_locations").fetchall()
        }

        for user in users:
            user_id = str(user["user_id"])
            for consent_type in CONSENT_TYPES:
                exists = conn.execute(
                    "SELECT 1 FROM user_consents WHERE user_id = ? AND consent_type = ?",
                    (user_id, consent_type),
                ).fetchone()
                if exists:
                    continue

                status = _default_consent_status(
                    consent_type,
                    gmail_authorized=int(user["gmail_authorized"] or 0),
                    has_location=user_id in location_users,
                )
                now = datetime.now().isoformat()
                granted_at = now if status == CONSENT_STATUS_GRANTED else None
                revoked_at = now if status == CONSENT_STATUS_REVOKED else None
                conn.execute(
                    """
                    INSERT INTO user_consents (user_id, consent_type, status, source, granted_at, revoked_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, consent_type, status, "migration", granted_at, revoked_at, now),
                )


def _ensure_default_user_consents(user_id: str):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT gmail_authorized FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if not user:
            return

        has_location = conn.execute(
            "SELECT 1 FROM user_locations WHERE user_id = ?",
            (str(user_id),),
        ).fetchone() is not None

        for consent_type in CONSENT_TYPES:
            exists = conn.execute(
                "SELECT 1 FROM user_consents WHERE user_id = ? AND consent_type = ?",
                (str(user_id), consent_type),
            ).fetchone()
            if exists:
                continue

            status = _default_consent_status(
                consent_type,
                gmail_authorized=int(user["gmail_authorized"] or 0),
                has_location=has_location,
            )
            now = datetime.now().isoformat()
            granted_at = now if status == CONSENT_STATUS_GRANTED else None
            revoked_at = now if status == CONSENT_STATUS_REVOKED else None
            conn.execute(
                """
                INSERT INTO user_consents (user_id, consent_type, status, source, granted_at, revoked_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(user_id), consent_type, status, "system_default", granted_at, revoked_at, now),
            )


def initialize_explicit_consents_for_new_user(user_id: str, source: str = "registration"):
    """Create explicit not-set consents for newly onboarded users.

    This prevents implicit grants for new users while keeping deterministic
    backfill behavior for legacy users.
    """
    now = datetime.now().isoformat()
    with get_conn() as conn:
        user = conn.execute(
            "SELECT 1 FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if not user:
            return

        for consent_type in CONSENT_TYPES:
            conn.execute(
                """
                INSERT INTO user_consents (user_id, consent_type, status, source, granted_at, revoked_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, consent_type) DO NOTHING
                """,
                (str(user_id), consent_type, CONSENT_STATUS_NOT_SET, source, None, None, now),
            )


def _normalize_consent_type(consent_type: str) -> str:
    consent_type = consent_type.strip().lower()
    if consent_type not in CONSENT_TYPES:
        raise ValueError(f"Unsupported consent type: {consent_type}")
    return consent_type


def _normalize_consent_status(status: str) -> str:
    status = status.strip().lower()
    allowed = {CONSENT_STATUS_GRANTED, CONSENT_STATUS_REVOKED, CONSENT_STATUS_NOT_SET}
    if status not in allowed:
        raise ValueError(f"Unsupported consent status: {status}")
    return status


def set_user_consent(user_id: str, consent_type: str, status: str, source: str = "system"):
    consent_type = _normalize_consent_type(consent_type)
    status = _normalize_consent_status(status)
    _ensure_default_user_consents(str(user_id))

    now = datetime.now().isoformat()
    granted_at = now if status == CONSENT_STATUS_GRANTED else None
    revoked_at = now if status == CONSENT_STATUS_REVOKED else None

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT granted_at FROM user_consents WHERE user_id = ? AND consent_type = ?",
            (str(user_id), consent_type),
        ).fetchone()
        preserved_granted_at = existing["granted_at"] if existing and existing["granted_at"] else granted_at

        conn.execute(
            """
            INSERT INTO user_consents (user_id, consent_type, status, source, granted_at, revoked_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, consent_type) DO UPDATE SET
                status=excluded.status,
                source=excluded.source,
                granted_at=excluded.granted_at,
                revoked_at=excluded.revoked_at,
                updated_at=excluded.updated_at
            """,
            (
                str(user_id),
                consent_type,
                status,
                source,
                preserved_granted_at if status == CONSENT_STATUS_GRANTED else None,
                revoked_at,
                now,
            ),
        )


def get_user_consent(user_id: str, consent_type: str) -> dict | None:
    _ensure_default_user_consents(str(user_id))
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_consents WHERE user_id = ? AND consent_type = ?",
            (str(user_id), _normalize_consent_type(consent_type)),
        ).fetchone()
        return dict(row) if row else None


def list_user_consents(user_id: str) -> list[dict]:
    _ensure_default_user_consents(str(user_id))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM user_consents WHERE user_id = ? ORDER BY consent_type",
            (str(user_id),),
        ).fetchall()
        return [dict(row) for row in rows]


def has_user_consent(user_id: str, consent_type: str, default: bool = False) -> bool:
    row = get_user_consent(user_id, consent_type)
    if not row:
        return default
    return row["status"] == CONSENT_STATUS_GRANTED


def apply_user_consent(user_id: str, consent_type: str, granted: bool, source: str = "user_command") -> dict:
    consent_type = _normalize_consent_type(consent_type)
    status = CONSENT_STATUS_GRANTED if granted else CONSENT_STATUS_REVOKED

    if consent_type == CONSENT_GMAIL:
        if granted:
            set_user_consent(user_id, consent_type, CONSENT_STATUS_NOT_SET, source=source)
            return {"consent_type": consent_type, "status": CONSENT_STATUS_NOT_SET}
        revoke_summary = revoke_gmail_access(user_id)
        return {"consent_type": consent_type, "status": CONSENT_STATUS_REVOKED, **revoke_summary}

    if consent_type == CONSENT_LOCATION:
        deleted = delete_location(user_id) if not granted else False
        set_user_consent(user_id, consent_type, status, source=source)
        return {"consent_type": consent_type, "status": status, "location_deleted": deleted}

    if consent_type == CONSENT_CHAT_HISTORY:
        deleted_history = 0
        deleted_conversations = 0
        with get_conn() as conn:
            if not granted:
                deleted_history = conn.execute(
                    "DELETE FROM chat_history WHERE user_id = ?",
                    (str(user_id),),
                ).rowcount
                deleted_conversations = conn.execute(
                    "DELETE FROM conversations WHERE user_id = ?",
                    (str(user_id),),
                ).rowcount
        set_user_consent(user_id, consent_type, status, source=source)
        return {
            "consent_type": consent_type,
            "status": status,
            "chat_history_deleted": deleted_history,
            "conversations_deleted": deleted_conversations,
        }

    raise ValueError(f"Unsupported consent type: {consent_type}")


def _hydrate_user_row(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None

    data = dict(row)

    try:
        from core import config
        from core.security import decrypt_sensitive_field, encrypt_sensitive_field, is_sensitive_field_encrypted
    except Exception:
        return data

    migrated_fields: dict[str, str] = {}
    for field_name in PROFILE_SECRET_FIELDS:
        raw_value = data.get(field_name)
        if not raw_value:
            continue

        if is_sensitive_field_encrypted(raw_value):
            data[field_name] = decrypt_sensitive_field(raw_value, field_name=field_name)
            continue

        data[field_name] = raw_value
        if config.ENCRYPTION_KEY:
            try:
                migrated_fields[field_name] = encrypt_sensitive_field(raw_value, field_name=field_name)
            except RuntimeError as err:
                log.warning("Failed to encrypt legacy %s during migration: %s", field_name, err)

    if migrated_fields:
        assignments = ", ".join(f"{field_name} = ?" for field_name in migrated_fields)
        conn.execute(
            f"UPDATE users SET {assignments}, updated_at = ? WHERE user_id = ?",
            [*migrated_fields.values(), datetime.now().isoformat(), data["user_id"]],
        )

    return data


def _hydrate_expense_row(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None

    data = dict(row)

    try:
        from core import config
        from core.security import decrypt_sensitive_field, encrypt_sensitive_field, is_sensitive_field_encrypted
    except Exception:
        return data

    migrated_fields: dict[str, str] = {}
    for field_name in EXPENSE_SECRET_FIELDS:
        raw_value = data.get(field_name)
        if raw_value is None or raw_value == "":
            continue

        if is_sensitive_field_encrypted(raw_value):
            decrypted = decrypt_sensitive_field(raw_value, field_name=f"expense_{field_name}")
            data[field_name] = decrypted or ""
            continue

        data[field_name] = raw_value
        if config.ENCRYPTION_KEY:
            try:
                migrated_fields[field_name] = encrypt_sensitive_field(raw_value, field_name=f"expense_{field_name}")
            except RuntimeError as err:
                log.warning("Failed to encrypt legacy expense %s during migration: %s", field_name, err)

    if migrated_fields:
        assignments = ", ".join(f"{field_name} = ?" for field_name in migrated_fields)
        conn.execute(
            f"UPDATE expenses SET {assignments} WHERE id = ?",
            [*migrated_fields.values(), data["id"]],
        )

    return data


def _rename_tool(old_name: str, new_name: str):
    """Rename tool name in tool_logs, schedules, chat_history"""
    try:
        with get_conn() as conn:
            for table, col in [
                ("tool_logs", "tool_name"),
                ("schedules", "tool_name"),
                ("chat_history", "tool_used"),
            ]:
                cur = conn.execute(
                    f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                    (new_name, old_name),
                )
                if cur.rowcount:
                    log.info(f"Migration: renamed '{old_name}' → '{new_name}' in {table} ({cur.rowcount} rows)")
    except Exception as e:
        log.warning(f"Migration rename tool failed: {e}")


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
            "SELECT * FROM users WHERE telegram_chat_id = ? AND is_active = 1 AND status = 'active'",
            (str(chat_id),)
        ).fetchone()
        return _hydrate_user_row(conn, row)


def get_user_by_id(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND is_active = 1",
            (str(user_id),),
        ).fetchone()
        return _hydrate_user_row(conn, row)


def upsert_user(user_id: str, chat_id: str, display_name: str, role: str = "user",
                default_llm: str = None, timezone: str = None,
                ensure_default_consents: bool = True):
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
                is_active=1,
                status='active',
                updated_at=?
        """, (user_id, str(chat_id), display_name, role,
              default_llm, timezone, now, now, now))
    if ensure_default_consents:
        _ensure_default_user_consents(user_id)


def get_all_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def deactivate_user(chat_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0, status = 'deleted', updated_at = ? WHERE telegram_chat_id = ?",
            (datetime.now().isoformat(), str(chat_id))
        )


def purge_user_data(user_id: str) -> dict:
    """Hard-delete all user-linked data for right-to-be-forgotten flows.

    Returns a summary dictionary with deleted row counts and whether a Gmail token
    file was removed from disk.
    """
    user_id = str(user_id)
    with get_conn() as conn:
        user_row = conn.execute(
            "SELECT user_id, telegram_chat_id FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if not user_row:
            return {"user_found": False, "gmail_token_deleted": False}

        chat_id = str(user_row["telegram_chat_id"])
        schedule_rows = conn.execute(
            "SELECT id FROM schedules WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        schedule_job_ids = [f"custom_{row['id']}" for row in schedule_rows]

        summary = {
            "user_found": True,
            "chat_history": conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,)).rowcount,
            "conversations": conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,)).rowcount,
            "processed_emails": conn.execute("DELETE FROM processed_emails WHERE user_id = ?", (user_id,)).rowcount,
            "tool_logs": conn.execute("DELETE FROM tool_logs WHERE user_id = ?", (user_id,)).rowcount,
            "reminders": conn.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,)).rowcount,
            "todos": conn.execute("DELETE FROM todos WHERE user_id = ?", (user_id,)).rowcount,
            "expenses": conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,)).rowcount,
            "user_locations": conn.execute("DELETE FROM user_locations WHERE user_id = ?", (user_id,)).rowcount,
            "oauth_states": conn.execute(
                "DELETE FROM oauth_states WHERE user_id = ? OR chat_id = ?",
                (user_id, chat_id),
            ).rowcount,
            "user_consents": conn.execute("DELETE FROM user_consents WHERE user_id = ?", (user_id,)).rowcount,
            "user_api_keys": conn.execute("DELETE FROM user_api_keys WHERE user_id = ?", (user_id,)).rowcount,
            "pending_messages": conn.execute("DELETE FROM pending_messages WHERE chat_id = ?", (chat_id,)).rowcount,
            "schedules": conn.execute("DELETE FROM schedules WHERE user_id = ?", (user_id,)).rowcount,
        }

        job_runs_deleted = 0
        for job_id in schedule_job_ids:
            job_runs_deleted += conn.execute(
                "DELETE FROM job_runs WHERE job_id = ?",
                (job_id,),
            ).rowcount
        summary["job_runs"] = job_runs_deleted

        summary["users"] = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,)).rowcount

    from core.security import get_gmail_token_path

    token_path = get_gmail_token_path(user_id)
    token_deleted = False
    if token_path.exists():
        try:
            token_path.unlink()
            token_deleted = True
        except OSError as err:
            log.warning("Failed to delete Gmail token for user %s: %s", user_id, err)

    summary["gmail_token_deleted"] = token_deleted
    return summary


def revoke_gmail_access(user_id: str) -> dict:
    """Revoke Gmail access for a user without purging other data."""
    user_id = str(user_id)
    with get_conn() as conn:
        user_row = conn.execute(
            "SELECT telegram_chat_id FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        chat_id = str(user_row["telegram_chat_id"]) if user_row else None
        oauth_states_deleted = conn.execute(
            "DELETE FROM oauth_states WHERE user_id = ?" + (" OR chat_id = ?" if chat_id else ""),
            (user_id, chat_id) if chat_id else (user_id,),
        ).rowcount
        user_updated = conn.execute(
            "UPDATE users SET gmail_authorized = 0, updated_at = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id),
        ).rowcount > 0

    set_user_consent(user_id, CONSENT_GMAIL, CONSENT_STATUS_REVOKED, source="gmail_disconnect")

    from core.security import get_gmail_token_path

    token_path = get_gmail_token_path(user_id)
    token_deleted = False
    if token_path.exists():
        try:
            token_path.unlink()
            token_deleted = True
        except OSError as err:
            log.warning("Failed to delete Gmail token during revoke for user %s: %s", user_id, err)

    return {
        "user_updated": user_updated,
        "oauth_states": oauth_states_deleted,
        "gmail_token_deleted": token_deleted,
    }


def update_user_preference(user_id: str, key: str, value: str):
    allowed = {"default_llm", "timezone", "smart_inbox_mode"}
    if key not in allowed:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {key} = ?, updated_at = ? WHERE user_id = ?",
            (value, datetime.now().isoformat(), user_id)
        )


def update_user_profile(user_id: str, display_name: str | None = None,
                        phone_number: str | None = None, national_id: str | None = None):
    from core.security import encrypt_sensitive_field

    fields = []
    values = []

    if display_name is not None:
        fields.append("display_name = ?")
        values.append(display_name)
    if phone_number is not None:
        fields.append("phone_number = ?")
        values.append(encrypt_sensitive_field(phone_number, field_name="phone_number") if phone_number else phone_number)
    if national_id is not None:
        fields.append("national_id = ?")
        values.append(encrypt_sensitive_field(national_id, field_name="national_id") if national_id else national_id)

    if not fields:
        return

    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(str(user_id))

    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?",
            values,
        )


def update_user_status(user_id: str, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET status = ?, is_active = ?, updated_at = ? WHERE user_id = ?",
            (status, 1 if status == 'active' else 0, datetime.now().isoformat(), str(user_id)),
        )


def upsert_user_api_key(user_id: str, service: str, api_key: str):
    now = datetime.now().isoformat()
    normalized_service = service.strip().lower()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_api_keys (user_id, service, api_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, service) DO UPDATE SET
                api_key=excluded.api_key,
                updated_at=excluded.updated_at
        """, (str(user_id), normalized_service, api_key, now, now))


def get_user_api_key(user_id: str, service: str) -> str | None:
    normalized_service = service.strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT api_key FROM user_api_keys WHERE user_id = ? AND service = ?",
            (str(user_id), normalized_service),
        ).fetchone()
        return row["api_key"] if row else None


def get_user_api_key_record(user_id: str, service: str) -> dict | None:
    normalized_service = service.strip().lower()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT service, api_key, created_at, updated_at FROM user_api_keys WHERE user_id = ? AND service = ?",
            (str(user_id), normalized_service),
        ).fetchone()
        return dict(row) if row else None


def get_user_api_keys(user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT service, api_key, created_at, updated_at FROM user_api_keys WHERE user_id = ? ORDER BY service",
            (str(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_user_api_keys() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, service, api_key, created_at, updated_at FROM user_api_keys ORDER BY user_id, service",
        ).fetchall()
        return [dict(r) for r in rows]


def delete_user_api_key(user_id: str, service: str) -> bool:
    normalized_service = service.strip().lower()
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM user_api_keys WHERE user_id = ? AND service = ?",
            (str(user_id), normalized_service),
        )
        return cursor.rowcount > 0


def add_reminder(user_id: str, text: str, remind_at: str, schedule_id: int | None = None) -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO reminders (user_id, text, remind_at, schedule_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(user_id), text, remind_at, schedule_id, now, now),
        )
        return cursor.lastrowid


def update_reminder_schedule(reminder_id: int, schedule_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET schedule_id = ?, updated_at = ? WHERE id = ?",
            (schedule_id, datetime.now().isoformat(), reminder_id),
        )


def get_reminder(reminder_id: int, user_id: str | None = None) -> dict | None:
    query = "SELECT * FROM reminders WHERE id = ?"
    params: list = [reminder_id]
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(str(user_id))
    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def list_user_reminders(user_id: str, include_done: bool = False) -> list[dict]:
    query = "SELECT * FROM reminders WHERE user_id = ?"
    if not include_done:
        query += " AND status = 'pending'"
    query += " ORDER BY remind_at"
    with get_conn() as conn:
        rows = conn.execute(query, (str(user_id),)).fetchall()
        return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET status = 'sent', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), reminder_id),
        )


def remove_reminder(reminder_id: int, user_id: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE reminders SET status = 'cancelled', updated_at = ? WHERE id = ? AND user_id = ? AND status = 'pending'",
            (datetime.now().isoformat(), reminder_id, str(user_id)),
        )
        return cursor.rowcount > 0


def add_todo(user_id: str, title: str, notes: str = "", priority: str = "medium", due_at: str = "", source_type: str = "", source_ref: str = "") -> int:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO todos (user_id, title, notes, priority, due_at, source_type, source_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(user_id), title, notes, priority, due_at or None, source_type, source_ref, now, now),
        )
        return cursor.lastrowid


def list_todos(user_id: str, status: str | None = None) -> list[dict]:
    query = "SELECT * FROM todos WHERE user_id = ?"
    params: list = [str(user_id)]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, COALESCE(due_at, '9999-12-31T23:59:59'), id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_todo(todo_id: int, user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM todos WHERE id = ? AND user_id = ?",
            (todo_id, str(user_id)),
        ).fetchone()
        return dict(row) if row else None


def update_todo_status(todo_id: int, user_id: str, status: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "UPDATE todos SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (status, datetime.now().isoformat(), todo_id, str(user_id)),
        )
        return cursor.rowcount > 0


def remove_todo(todo_id: int, user_id: str) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM todos WHERE id = ? AND user_id = ?",
            (todo_id, str(user_id)),
        )
        return cursor.rowcount > 0


def add_expense(user_id: str, amount: float, category: str, note: str = "", expense_date: str = "",
                currency: str = "THB", source_type: str = "", source_hash: str = "") -> int:
    from core.security import encrypt_sensitive_field

    date_value = expense_date or datetime.now().date().isoformat()
    created_at = datetime.now().isoformat()
    normalized_note = (note or "").strip()
    encrypted_note = ""
    if normalized_note:
        encrypted_note = encrypt_sensitive_field(normalized_note, field_name="expense_note")

    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO expenses (user_id, amount, currency, category, note, source_type, source_hash, expense_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(user_id),
                amount,
                currency,
                category,
                encrypted_note,
                (source_type or "").strip(),
                (source_hash or "").strip(),
                date_value,
                created_at,
            ),
        )
        return cursor.lastrowid


def list_expenses(user_id: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? ORDER BY expense_date DESC, id DESC LIMIT ?",
            (str(user_id), limit),
        ).fetchall()
        return [_hydrate_expense_row(conn, row) for row in rows]


def get_expenses_by_source_hash(user_id: str, source_type: str, source_hash: str) -> list[dict]:
    normalized_source_type = (source_type or "").strip()
    normalized_source_hash = (source_hash or "").strip()
    if not normalized_source_type or not normalized_source_hash:
        return []

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM expenses
            WHERE user_id = ? AND source_type = ? AND source_hash = ?
            ORDER BY id ASC
            """,
            (str(user_id), normalized_source_type, normalized_source_hash),
        ).fetchall()
        return [_hydrate_expense_row(conn, row) for row in rows]


def summarize_expenses(user_id: str, start_date: str, end_date: str, category: str = "", keyword: str = "") -> list[dict]:
    with get_conn() as conn:
        sql = "SELECT category, SUM(amount) AS total, COUNT(*) AS count FROM expenses WHERE user_id = ? AND expense_date BETWEEN ? AND ?"
        params: list = [str(user_id), start_date, end_date]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if keyword:
            sql += " AND (note LIKE ? OR category LIKE ?)"
            params.append(f"%{keyword}%")
            params.append(f"%{keyword}%")
        sql += " GROUP BY category ORDER BY total DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


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
    if not has_user_consent(user_id, CONSENT_CHAT_HISTORY, default=True):
        return
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO chat_history (user_id, role, content, tool_used, llm_model, token_used, conversation_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, role, content, tool_used, llm_model, token_used,
              conversation_id, datetime.now().isoformat()))


def get_chat_context(user_id: str, limit: int = 10, conversation_id: str = None) -> list[dict]:
    if not has_user_consent(user_id, CONSENT_CHAT_HISTORY, default=True):
        return []
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
    _ = sender
    has_subject = 1 if (subject or "").strip() else 0
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO processed_emails (user_id, message_id, subject, sender, sender_domain, has_subject, processed_at)
            VALUES (?, ?, NULL, NULL, ?, ?, ?)
        """, (user_id, message_id, None, has_subject, datetime.now().isoformat()))


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
                   error_message: str = "", input_kind: str = "",
                   input_ref: str = "", input_size: int | None = None,
                   output_kind: str = "", output_ref: str = "",
                   output_size: int | None = None, error_kind: str = "",
                   error_code: str = "", error_safe_message: str = ""):
    if input_kind or input_ref or input_size is not None:
        final_input_kind = input_kind or "text"
        final_input_ref = input_ref
        final_input_size = input_size or 0
    else:
        final_input_kind, final_input_ref, final_input_size = _summarize_text_field(input_summary)

    if output_kind or output_ref or output_size is not None:
        final_output_kind = output_kind or "text"
        final_output_ref = output_ref
        final_output_size = output_size or 0
    else:
        final_output_kind, final_output_ref, final_output_size = _summarize_text_field(output_summary)

    if error_kind or error_code or error_safe_message:
        final_error_kind = error_kind
        final_error_code = error_code
        final_error_safe_message = error_safe_message
    else:
        final_error_kind, final_error_code, final_error_safe_message = _redact_error_model(error_message)

    with get_conn() as conn:
        conn.execute("""
            INSERT INTO tool_logs (
                user_id, tool_name, input_summary, output_summary,
                input_kind, input_ref, input_size,
                output_kind, output_ref, output_size,
                llm_model, token_used, status,
                error_message, error_kind, error_code, error_safe_message,
                created_at
            )
            VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """, (
            user_id,
            tool_name,
            final_input_kind,
            final_input_ref[:128],
            final_input_size,
            final_output_kind,
            final_output_ref[:128],
            final_output_size,
            llm_model,
            token_used,
            status,
            final_error_kind,
            final_error_code[:64],
            final_error_safe_message[:255],
            datetime.now().isoformat(),
        ))


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
    if not has_user_consent(user_id, CONSENT_LOCATION, default=False):
        return False

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO user_locations (user_id, latitude, longitude, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                updated_at=excluded.updated_at
        """, (str(user_id), lat, lng, now))
    return True


def save_oauth_state(state: str, user_id: str, chat_id: str, expires_at: str, code_verifier: str = ""):
    """บันทึก OAuth state + PKCE code_verifier สำหรับ Gmail callback"""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_states (state, user_id, chat_id, expires_at, code_verifier) VALUES (?, ?, ?, ?, ?)",
            (state, user_id, chat_id, expires_at, code_verifier)
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
    if not has_user_consent(user_id, CONSENT_LOCATION, default=False):
        return None
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


def delete_location(user_id: str) -> bool:
    """Delete the user's last stored location."""
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM user_locations WHERE user_id = ?",
            (str(user_id),),
        )
        return cursor.rowcount > 0


def cleanup_stale_locations(ttl_minutes: int = 60):
    """Delete stored locations older than the configured TTL.

    ttl_minutes=0 keeps locations indefinitely.
    """
    if ttl_minutes <= 0:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM user_locations WHERE updated_at < datetime('now', ?)",
            (f"-{ttl_minutes} minutes",),
        )


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
            INSERT OR IGNORE INTO job_runs (job_id, scheduled_at, ran_at, status)
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
