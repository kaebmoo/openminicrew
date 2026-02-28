# OpenMiniCrew — Personal AI Assistant Framework
# Architecture v5 (Final) — Production Ready + Multi-tenant Ready

> 🇬🇧 [English version](docs/en/ARCHITECTURE.md)

## หลักการออกแบบ

```
1. Multi-tenant ready — deploy single-user ก่อน ขยายได้โดยไม่ต้อง refactor
2. เพิ่ม tool ได้ — สร้างไฟล์เดียว ไม่ต้องแก้ core
3. เพิ่ม LLM provider ได้ — สร้างไฟล์ใน core/providers/ (Provider Registry)
4. Webhook production-ready — ตอบ 200 ทันที, background task, error handling
5. Chat memory — LLM จำบริบทสนทนาได้ พร้อม auto-cleanup
6. เลือก LLM ได้ — Claude + Gemini + เพิ่มได้, per-user preference + auto-fallback
7. Cost control — command ตรงไม่เสีย token, จำกัด context window
8. Single-process deploy — APScheduler + SQLite + single worker
```

## สถาปัตยกรรม

```
┌─────────────────────────────────────────────────────────────┐
│                      INTERFACE LAYER                         │
│                                                               │
│  Telegram Bot                        Cron Scheduler          │
│  ┌─────────────────────────────┐     (APScheduler)           │
│  │  Mode A: Long Polling       │     - single-process        │
│  │  (script ธรรมดา)             │     - SQLite jobstore      │
│  │  เหมาะ: dev, เครื่องที่บ้าน   │     - per-user schedules   │
│  ├─────────────────────────────┤     - cleanup job daily     │
│  │  Mode B: Webhook (FastAPI)  │                             │
│  │  ตอบ 200 ทันที              │                             │
│  │  BackgroundTask + error handling                          │
│  │  /health endpoint           │                             │
│  │  secret_token verification  │                             │
│  │  เหมาะ: VPS, production     │                             │
│  └─────────────────────────────┘                             │
│                                                               │
│  เปลี่ยน mode แค่แก้ .env (BOT_MODE=polling | webhook)       │
└──────────────────────┬───────────────────┬──────────────────┘
                       │                   │
                       ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    USER MANAGER                              │
│                                                               │
│  chat_id → user_id mapping                                   │
│                                                               │
│  วันนี้:  owner คนเดียว ตั้งใน .env                          │
│  อนาคต:  /start → pending → owner approve → active          │
│                                                               │
│  แต่ละ user มี:                                               │
│  - telegram_chat_id, display_name, role                      │
│  - gmail_token (แยกกัน)                                      │
│  - preferences (default_llm, timezone)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                       DISPATCHER                             │
│                                                               │
│  รับ (user_id + message) จาก User Manager                    │
│                                                               │
│  /command     → เรียก tool ตรง (ไม่เสีย token)               │
│  ข้อความอิสระ  → Memory ดึง context → LLM Router ตัดสินใจ    │
│  ไม่ตรง tool  → LLM ตอบ general chat (มี context)           │
│                                                               │
│  ทุกกรณี → บันทึก Memory + tool_logs                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
┌────────────┐ ┌──────────────┐ ┌────────────────┐
│ LLM Router │ │ Tool Registry│ │ Memory Manager │
│            │ │              │ │                │
│ Provider   │ │ auto-discover│ │ บันทึก/ดึง chat│
│ Registry   │ │ importlib    │ │ per-user       │
│ ┌────────┐ │ │ scan tools/  │ │                │
│ │ Claude │ │ │              │ │ จำกัด N ล่าสุด │
│ │ Gemini │ │ │ ┌──────────┐ │ │ auto-cleanup   │
│ │(add more)│ │ │email_sum.│ │ │ ตาม retention  │
│ └────────┘ │ │ │(เพิ่มได้) │ │ │                │
│ auto-     │ │ └──────────┘ │ │                │
│ fallback  │ │              │ │                │
└────────────┘ └──────────────┘ └────────────────┘
       │               │               │
       ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                       SHARED CORE                            │
│                                                               │
│  config.py        โหลด .env + validate                      │
│  llm.py           LLM Router (thin wrapper)               │
│                   ใช้ Provider Registry + auto-fallback      │
│  providers/       LLM Provider Registry                    │
│    base.py        BaseLLMProvider abstract class           │
│    claude_provider.py   Claude API + retry                 │
│    gemini_provider.py   Gemini API + retry                 │
│    registry.py    auto-discover + fallback                 │
│  db.py            SQLite + WAL mode                        │
│  memory.py        chat context management                  │
│  security.py      token refresh, credential management     │
│  user_manager.py  user auth, preferences                   │
│  logger.py        structured logging                       │
└─────────────────────────────────────────────────────────────┘
```

## โครงสร้างไฟล์

```
openminicrew/
├── .env.example
├── .env                          # (ห้าม commit)
├── .gitignore
├── README.md
├── requirements.txt
│
├── core/
│   ├── __init__.py
│   ├── config.py                 # ENV loader + validation
│   ├── llm.py                    # LLM Router (thin wrapper, uses registry)
│   ├── providers/                # LLM Provider Registry
│   │   ├── __init__.py
│   │   ├── base.py               # BaseLLMProvider abstract class
│   │   ├── claude_provider.py    # Claude API + retry + tool spec
│   │   ├── gemini_provider.py    # Gemini API + retry + tool spec
│   │   └── registry.py           # Auto-discover + fallback
│   ├── db.py                     # SQLite + WAL mode
│   ├── memory.py                 # Chat context per user
│   ├── security.py               # Token refresh, credential mgmt
│   ├── user_manager.py           # User auth, preferences
│   └── logger.py                 # Structured logging
│
├── tools/
│   ├── __init__.py
│   ├── base.py                   # BaseTool abstract class
│   ├── registry.py               # Auto-discover (importlib + inspect)
│   └── email_summary.py          # สรุปเมล (tool ตัวแรก)
│
├── interfaces/
│   ├── __init__.py
│   ├── telegram_polling.py       # Mode A: long polling
│   ├── telegram_webhook.py       # Mode B: webhook + BackgroundTask
│   │                             #   + error handling + /health
│   │                             #   + secret_token verification
│   └── telegram_common.py        # shared: auth, send, split, rate limit
│
├── dispatcher.py                 # Command routing + LLM dispatch
├── scheduler.py                  # APScheduler (single-process, SQLite jobstore)
├── main.py                       # Entry point (auto Gmail auth + --auth-gmail)
│
├── credentials.json              # OAuth client secret (จาก Google Cloud)
├── credentials/                  # (ห้าม commit) Gmail tokens
│   └── gmail_{user_id}.json
│
└── data/
    └── openminicrew.db
```

## Database Schema

```sql
PRAGMA journal_mode=WAL;

-- =====================================================
-- USERS
-- =====================================================
CREATE TABLE users (
    user_id           TEXT PRIMARY KEY,
    telegram_chat_id  TEXT UNIQUE NOT NULL,
    display_name      TEXT,
    role              TEXT DEFAULT 'user',      -- owner | user
    default_llm       TEXT DEFAULT 'claude',    -- claude | gemini
    timezone          TEXT DEFAULT 'Asia/Bangkok',
    gmail_authorized  INTEGER DEFAULT 0,
    is_active         INTEGER DEFAULT 1,
    created_at        TEXT,
    updated_at        TEXT
);

-- =====================================================
-- CHAT HISTORY (Memory)
-- =====================================================
CREATE TABLE chat_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    role              TEXT NOT NULL,            -- user | assistant
    content           TEXT NOT NULL,
    tool_used         TEXT,
    llm_model         TEXT,
    token_used        INTEGER,
    created_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX idx_chat_user_time
    ON chat_history(user_id, created_at DESC);

-- =====================================================
-- PROCESSED EMAILS
-- =====================================================
CREATE TABLE processed_emails (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    message_id        TEXT NOT NULL,
    subject           TEXT,
    sender            TEXT,
    processed_at      TEXT,
    UNIQUE(user_id, message_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- =====================================================
-- TOOL LOGS
-- =====================================================
CREATE TABLE tool_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    tool_name         TEXT NOT NULL,
    input_summary     TEXT,
    output_summary    TEXT,
    llm_model         TEXT,
    token_used        INTEGER,
    status            TEXT,                     -- success | error
    error_message     TEXT,                     -- เก็บ error detail ถ้า fail
    created_at        TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- =====================================================
-- SCHEDULES
-- =====================================================
CREATE TABLE schedules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    tool_name         TEXT NOT NULL,
    cron_expr         TEXT NOT NULL,
    args              TEXT,                     -- JSON string
    is_active         INTEGER DEFAULT 1,
    last_run_at       TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

## Tool Spec Conversion (Provider Registry)

```
BaseTool.get_tool_spec() → format กลาง (dict)
        │
        ▼
LLM Router → ส่งให้ Provider
        │
        ▼
แต่ละ Provider แปลงเอง (convert_tool_spec):

  ClaudeProvider:
        │
        ├── Claude API → Anthropic tool_use format
        │   {
        │     "name": "email_summary",
        │     "description": "...",
        │     "input_schema": {
        │       "type": "object",
        │       "properties": { ... },
        │       "required": [ ... ]
        │     }
        │   }

  GeminiProvider:
        │
        └── Gemini API → Google function_declarations format
            {
              "name": "email_summary",
              "description": "...",
              "parameters": {
                "type": "OBJECT",
                "properties": { ... },
                "required": [ ... ]
              }
            }

เพิ่ม Provider ใหม่ = สร้างไฟล์ใน core/providers/
Tool เขียน spec ครั้งเดียว → ใช้ได้กับทุก LLM provider
```

## Webhook Flow (Production Ready)

```
[Telegram POST → /bot/webhook]
        │
        ▼
[FastAPI endpoint]
  │
  ├── 1. ตรวจ X-Telegram-Bot-Api-Secret-Token header
  │      ไม่ตรง → 403 Forbidden
  │
  ├── 2. ตอบ HTTP 200 OK ทันที
  │
  └── 3. โยนงานไป BackgroundTask:
          │
          ├── try:
          │     User Manager → Dispatcher → Tool/LLM
          │     → ส่ง Telegram กลับ
          │
          └── except:
                Log error
                → ส่ง error message กลับไปบอก user ผ่าน Telegram
                  "เกิดข้อผิดพลาด: [สรุปสั้นๆ] กรุณาลองใหม่"

[GET /health]
  → {"status": "ok", "bot_mode": "webhook", "uptime": "..."}
```

## Rate Limiting (telegram_common.py)

```
Telegram API limits:
  - 30 msg/sec ถึง chat เดียว
  - 20 msg/min ถึง group

telegram_common.py:
  - simple token bucket rate limiter
  - ถ้าเกิน limit → queue แล้วส่งทีหลัง
  - ป้องกัน burst เมื่อ cron job หลายตัวทำงานพร้อมกัน
```

## Auto-discover Tools (registry.py)

```
เมื่อ app startup:

1. scan tools/ directory หา *.py ที่ไม่ใช่ __init__, base, registry
2. importlib.import_module() แต่ละไฟล์
3. inspect หา class ที่ inherit BaseTool
4. สร้าง instance + register

ผลลัพธ์:
  registry.tools = {
      "email_summary": EmailSummaryTool(),
      # tool ใหม่จะปรากฏที่นี่อัตโนมัติ
  }
  registry.command_map = {
      "/email": EmailSummaryTool(),
      # command ใหม่จะปรากฏที่นี่อัตโนมัติ
  }
```

## Config (.env)

```bash
# === Bot Mode ===
BOT_MODE=polling                     # polling | webhook

# === Webhook (เฉพาะ mode webhook) ===
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PORT=8443
WEBHOOK_PATH=/bot/webhook
TELEGRAM_WEBHOOK_SECRET=your-random-secret-string-here

# === Owner (single-user mode) ===
OWNER_TELEGRAM_CHAT_ID=123456789
OWNER_DISPLAY_NAME=Pornthep

# === LLM ===
DEFAULT_LLM=claude                   # claude | gemini
ANTHROPIC_API_KEY=sk-ant-xxx
GEMINI_API_KEY=AIzaSyXxx

CLAUDE_MODEL_CHEAP=claude-haiku-4-5-20251001
CLAUDE_MODEL_MID=claude-sonnet-4-5-20250929

GEMINI_MODEL_CHEAP=gemini-2.5-flash
GEMINI_MODEL_MID=gemini-2.5-pro

# === Telegram ===
TELEGRAM_BOT_TOKEN=123:ABCxxx

# === Gmail ===
GMAIL_MAX_RESULTS=30

# === Memory ===
MAX_CONTEXT_MESSAGES=10
CHAT_HISTORY_RETENTION_DAYS=30

# === Schedule ===
TIMEZONE=Asia/Bangkok
MORNING_BRIEFING_TIME=07:00
```

## Dispatcher Flow (สมบูรณ์)

```
[Message จาก chat_id: 123456]
        │
        ▼
[User Manager: chat_id → user_id, ตรวจ authorized]
        │ ไม่ผ่าน → ignore (ไม่ตอบ)
        │ ผ่าน
        ▼
[Memory: บันทึก user message]
        │
        ▼
[Dispatcher]
        │
        ├── /email             → EmailSummaryTool.execute(user_id)
        │                        ไม่เสีย LLM token
        │
        ├── /help              → แสดง commands + descriptions จาก registry
        │
        ├── /model claude      → อัปเดต user preference ใน DB
        ├── /model gemini      → อัปเดต user preference ใน DB
        │
        ├── ข้อความอิสระ        → Memory ดึง N messages ล่าสุด
        │                        → LLM Router (model ตาม user preference)
        │                        → LLM เลือก tool (function calling)
        │                        → Tool.execute(user_id) ถ้าจำเป็น
        │                        → LLM สรุปผลเป็นภาษาธรรมชาติ
        │
        └── ไม่ตรง tool ไหน    → LLM ตอบ general chat (มี context)
                │
                ▼
[Memory: บันทึก assistant response + tool_used + token_used]
        │
        ▼
[tool_logs: บันทึก usage (ถ้าเรียก tool)]
        │
        ▼
[telegram_common: ส่งกลับ (rate limited) + split ถ้ายาว]
```

## BaseTool Interface

```python
# tools/base.py (concept)

class BaseTool(ABC):
    name: str
    description: str
    commands: list[str]

    @abstractmethod
    async def execute(self, user_id: str, args: str = "") -> str:
        """ทำงานหลัก — รับ user_id เสมอ"""
        ...

    def get_tool_spec(self) -> dict:
        """
        Return format กลาง — LLM Router แปลงให้ตรง provider เอง

        return {
            "name": "email_summary",
            "description": "สรุปอีเมลจาก Gmail ระบุช่วงเวลา ค้นหา...",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "today, 3d, 7d, force, คำค้นหา"
                    }
                },
                "required": []
            }
        }
        """
        ...
```

## เพิ่ม Tool ใหม่

สร้างไฟล์เดียวใน tools/ — registry auto-discover ให้:

```python
# tools/email_attachment.py (ตัวอย่าง concept)

class EmailAttachmentTool(BaseTool):
    name = "email_attachment"
    description = "อ่านและสรุปไฟล์แนบจากอีเมล (PDF, Excel, Word, รูปภาพ)"
    commands = ["/attachment"]

    async def execute(self, user_id: str, args: str = "") -> str:
        ...

    def get_tool_spec(self) -> dict:
        return {
            "name": "email_attachment",
            "description": "อ่านและสรุปไฟล์แนบจากอีเมล",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_filter": {
                        "type": "string",
                        "description": "กรอง email ของผู้ส่ง (optional)"
                    }
                },
                "required": []
            }
        }
```

## Multi-user Expansion (อนาคต)

```
สิ่งที่เพิ่ม:
  /start, /approve, /authorize_gmail
  OAuth callback endpoint (GET /auth/gmail/callback)
  Admin commands (/users, /usage, /disable)

สิ่งที่ไม่ต้องแก้:
  ✅ tools ทั้งหมด
  ✅ dispatcher
  ✅ LLM router
  ✅ memory
  ✅ DB schema
  ✅ scheduler
  ✅ security
```

## Security Checklist

```
✅  User authorization (chat_id → user_id → is_active)
✅  Role-based access (owner vs user)
✅  Gmail token แยก per user
✅  Token auto-refresh (security.py)
✅  ไม่มี shell exec (tool ทำแค่ที่เขียน)
✅  Webhook secret_token verification
✅  HTTPS only (webhook mode)
✅  API keys ใน .env ไม่ hardcode
✅  Gmail readonly scope
✅  SQLite WAL mode
✅  Rate limiting (Telegram API)
✅  Usage logging per user + token count
✅  Error logging + user notification on failure
✅  Memory auto-cleanup ตาม retention policy
✅  Health check endpoint (/health)
```
