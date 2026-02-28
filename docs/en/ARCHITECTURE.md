# OpenMiniCrew — Architecture
# Architecture v5 (Final) — Production Ready + Multi-tenant Ready

> 🇹🇭 [อ่านเป็นภาษาไทย](../../ARCHITECTURE.md)

## Design Principles

```
1. Multi-tenant ready — deploy single-user first, scale without refactoring
2. Plug-and-play tools — create one file, no core changes needed
3. Plug-and-play LLM providers — create one file in core/providers/ (Provider Registry)
4. Webhook production-ready — respond 200 immediately, background task, error handling
5. Chat memory — LLM maintains conversation context with auto-cleanup
6. Multi-LLM — Claude + Gemini + add more, per-user preference + auto-fallback
7. Cost control — direct commands cost zero tokens, limited context window
8. Single-process deploy — APScheduler + SQLite + single worker
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      INTERFACE LAYER                         │
│                                                               │
│  Telegram Bot                        Cron Scheduler          │
│  ┌─────────────────────────────┐     (APScheduler)           │
│  │  Mode A: Long Polling       │     - single-process        │
│  │  (simple script)            │     - SQLite jobstore      │
│  │  Best for: dev, home        │     - per-user schedules   │
│  ├─────────────────────────────┤     - daily cleanup job    │
│  │  Mode B: Webhook (FastAPI)  │                             │
│  │  Responds 200 immediately   │                             │
│  │  BackgroundTask + error handling                          │
│  │  /health endpoint           │                             │
│  │  secret_token verification  │                             │
│  │  Best for: VPS, production  │                             │
│  └─────────────────────────────┘                             │
│                                                               │
│  Switch mode by editing .env (BOT_MODE=polling | webhook)    │
└──────────────────────┬───────────────────┬──────────────────┘
                       │                   │
                       ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    USER MANAGER                              │
│                                                               │
│  chat_id → user_id mapping                                   │
│                                                               │
│  Today:  single owner set in .env                            │
│  Future: /start → pending → owner approve → active           │
│                                                               │
│  Each user has:                                               │
│  - telegram_chat_id, display_name, role                      │
│  - gmail_token (separate per user)                           │
│  - preferences (default_llm, timezone)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                       DISPATCHER                             │
│                                                               │
│  Receives (user_id + message) from User Manager              │
│                                                               │
│  /command     → call tool directly (zero token cost)         │
│  free text    → Memory gets context → LLM Router decides    │
│  no tool match→ LLM responds as general chat (with context) │
│                                                               │
│  All cases → save Memory + tool_logs                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
┌────────────┐ ┌──────────────┐ ┌────────────────┐
│ LLM Router │ │ Tool Registry│ │ Memory Manager │
│            │ │              │ │                │
│ Provider   │ │ auto-discover│ │ save/get chat  │
│ Registry   │ │ importlib    │ │ per-user       │
│ ┌────────┐ │ │ scan tools/  │ │                │
│ │ Claude │ │ │              │ │ limit N latest │
│ │ Gemini │ │ │ ┌──────────┐ │ │ auto-cleanup   │
│ │(add more)│ │ │email_sum.│ │ │ by retention   │
│ └────────┘ │ │ │(add more)│ │ │                │
│ auto-     │ │ └──────────┘ │ │                │
│ fallback  │ │              │ │                │
└────────────┘ └──────────────┘ └────────────────┘
       │               │               │
       ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                       SHARED CORE                            │
│                                                               │
│  config.py        Load .env + validate                       │
│  llm.py           LLM Router (thin wrapper)                  │
│                   Uses Provider Registry + auto-fallback     │
│  providers/       LLM Provider Registry                      │
│    base.py        BaseLLMProvider abstract class             │
│    claude_provider.py   Claude API + retry                   │
│    gemini_provider.py   Gemini API + retry                   │
│    registry.py    Auto-discover + fallback                   │
│  db.py            SQLite + WAL mode                          │
│  memory.py        chat context management                    │
│  security.py      token refresh, credential management       │
│  user_manager.py  user auth, preferences                     │
│  logger.py        structured logging                         │
└─────────────────────────────────────────────────────────────┘
```

## File Structure

```
openminicrew/
├── .env.example
├── .env                          # (do not commit)
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
│   └── email_summary.py          # Email summary (time range + search + force)
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
├── credentials.json              # OAuth client secret (from Google Cloud)
├── credentials/                  # (do not commit) Gmail tokens
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
    error_message     TEXT,                     -- store error detail if failed
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

## Tool Spec Conversion (LLM Router)

```
BaseTool.get_tool_spec() → generic format (dict)
        │
        ▼
LLM Router converts per provider:
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

Tool writes spec once → works with all LLM providers
```

## Webhook Flow (Production Ready)

```
[Telegram POST → /bot/webhook]
        │
        ▼
[FastAPI endpoint]
  │
  ├── 1. Verify X-Telegram-Bot-Api-Secret-Token header
  │      Mismatch → 403 Forbidden
  │
  ├── 2. Respond HTTP 200 OK immediately
  │
  └── 3. Pass work to BackgroundTask:
          │
          ├── try:
          │     User Manager → Dispatcher → Tool/LLM
          │     → Send Telegram response
          │
          └── except:
                Log error
                → Send error message to user via Telegram
                  "An error occurred: [brief summary]. Please try again."

[GET /health]
  → {"status": "ok", "bot_mode": "webhook", "uptime": "..."}
```

## Dispatcher Flow (Complete)

```
[Message from chat_id: 123456]
        │
        ▼
[User Manager: chat_id → user_id, check authorized]
        │ Not authorized → ignore (no response)
        │ Authorized
        ▼
[Memory: save user message]
        │
        ▼
[Dispatcher]
        │
        ├── /email             → EmailSummaryTool.execute(user_id)
        │                        Zero LLM token cost
        │
        ├── /help              → Show commands + descriptions from registry
        │
        ├── /model claude      → Update user preference in DB
        ├── /model gemini      → Update user preference in DB
        │
        ├── Free text          → Memory fetches N latest messages
        │                        → LLM Router (model per user preference)
        │                        → LLM selects tool (function calling)
        │                        → Tool.execute(user_id) if needed
        │                        → LLM summarizes result in natural language
        │
        └── No tool match     → LLM responds as general chat (with context)
                │
                ▼
[Memory: save assistant response + tool_used + token_used]
        │
        ▼
[tool_logs: log usage (if tool was called)]
        │
        ▼
[telegram_common: send response (rate limited) + split if long]
```

## BaseTool Interface

```python
# tools/base.py

class BaseTool(ABC):
    name: str
    description: str
    commands: list[str]

    @abstractmethod
    async def execute(self, user_id: str, args: str = "") -> str:
        """Main logic — always receives user_id"""
        ...

    def get_tool_spec(self) -> dict:
        """
        Return generic format — LLM Router converts to match provider

        return {
            "name": "email_summary",
            "description": "Summarize emails from Gmail with time range and search",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "today, 3d, 7d, force, search terms"
                    }
                },
                "required": []
            }
        }
        """
        ...
```

## Auto-discover Tools (registry.py)

```
On app startup:

1. Scan tools/ directory for *.py (excluding __init__, base, registry)
2. importlib.import_module() each file
3. Inspect for classes that inherit BaseTool
4. Create instance + register

Result:
  registry.tools = {
      "email_summary": EmailSummaryTool(),
      # new tools appear here automatically
  }
  registry.command_map = {
      "/email": EmailSummaryTool(),
      # new commands appear here automatically
  }
```

## Config (.env)

```bash
# === Bot Mode ===
BOT_MODE=polling                     # polling | webhook

# === Webhook (webhook mode only) ===
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

## Multi-user Expansion (Future)

```
What to add:
  /start, /approve, /authorize_gmail
  OAuth callback endpoint (GET /auth/gmail/callback)
  Admin commands (/users, /usage, /disable)

What doesn't need changes:
  ✅ all tools
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
✅  Gmail token separate per user
✅  Token auto-refresh (security.py)
✅  No shell exec (tools only do what's written)
✅  Webhook secret_token verification
✅  HTTPS only (webhook mode)
✅  API keys in .env, never hardcoded
✅  Gmail readonly scope
✅  SQLite WAL mode
✅  Rate limiting (Telegram API)
✅  Usage logging per user + token count
✅  Error logging + user notification on failure
✅  Memory auto-cleanup by retention policy
✅  Health check endpoint (/health)
```
