# OpenMiniCrew — Architecture

> 🇹🇭 [อ่านเป็นภาษาไทย](../th/ARCHITECTURE.md)

## What is OpenMiniCrew?

A personal AI assistant framework that runs as a Telegram bot. Users chat naturally — an LLM decides which tool to invoke. Drop a Python file in `tools/` and the system picks it up automatically.

## Design Principles

| # | Principle | Why |
|---|-----------|-----|
| 1 | **Plug-and-play tools** | One file = one tool. No core changes, no registration code. |
| 2 | **Plug-and-play LLM providers** | One file in `core/providers/`. Auto-fallback between providers. |
| 3 | **Per-user everything** | Each user has their own LLM preference, API keys, memory, and credentials. |
| 4 | **Zero-token direct commands** | `/email`, `/help` etc. bypass LLM entirely — no cost. |
| 5 | **Single-process deploy** | SQLite + APScheduler + one worker. No Redis, no Celery. |
| 6 | **Production-ready from day one** | Webhook mode responds 200 immediately, processes in background. |

## System Overview

```
┌───────────────────────────────────────────────────┐
│                 INTERFACE LAYER                    │
│                                                   │
│   Telegram Bot              Scheduler             │
│   ┌───────────────────┐     (APScheduler)         │
│   │ Polling or Webhook │     cron jobs, cleanup    │
│   │ (switch via .env)  │     per-user schedules    │
│   └────────┬──────────┘                           │
└────────────┼──────────────────────────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────┐
│              USER MANAGER                         │
│   telegram chat_id → user_id                      │
│   auth, roles, preferences, per-user API keys     │
└────────────┬──────────────────────────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────┐
│                DISPATCHER                         │
│                                                   │
│   /command  ──→  Tool directly (zero tokens)      │
│   free text ──→  LLM Router ──→ tool or chat      │
│                                                   │
│   self-correction: if tool fails, LLM retries     │
│   with error feedback (up to N rounds)            │
└──────┬────────────┬────────────┬──────────────────┘
       │            │            │
       ▼            ▼            ▼
 ┌──────────┐ ┌──────────┐ ┌──────────┐
 │LLM Router│ │  Tool    │ │ Memory   │
 │          │ │ Registry │ │ Manager  │
 │ Provider │ │          │ │          │
 │ Registry │ │ auto-    │ │ per-user │
 │          │ │ discover │ │ context  │
 │ fallback │ │ at boot  │ │ + cleanup│
 └──────────┘ └──────────┘ └──────────┘
       │            │            │
       ▼            ▼            ▼
┌───────────────────────────────────────────────────┐
│                 STORAGE LAYER                     │
│   SQLite (WAL mode) — single file, zero config    │
│   tables: users, chat_history, tool_logs,         │
│           processed_emails, schedules,            │
│           user_api_keys, ...                      │
└───────────────────────────────────────────────────┘
```

## Key Subsystems

### 1. Dispatcher — the brain

The dispatcher receives every message and decides what to do:

```
incoming message
  │
  ├─ starts with /command? → look up Tool Registry → execute directly
  │
  ├─ free text? → build context (Memory) → call LLM Router
  │   │
  │   ├─ LLM picks a tool → execute tool → LLM summarizes result
  │   └─ LLM picks no tool → respond as general chat
  │
  └─ all paths → save to Memory + tool_logs
```

**Self-correction loop**: If the LLM picks a wrong tool or the tool errors, the dispatcher feeds the error back to the LLM for another attempt (configurable max rounds).

### 2. LLM Router + Provider Registry

```
core/providers/
├── base.py              # BaseLLMProvider (abstract)
├── claude_provider.py   # one provider
├── gemini_provider.py   # another provider
├── matcha_provider.py   # another (OpenAI-compatible)
└── registry.py          # auto-discover + fallback
```

**How it works:**
- On startup, `registry.py` scans `core/providers/` and instantiates every class that inherits `BaseLLMProvider`.
- Each provider implements `is_configured()`, `chat()`, and `convert_tool_spec()`.
- The router tries the user's preferred provider first; if unavailable, falls back to the next configured one.
- Per-user API keys: providers can override `is_available_for_user(user_id)` to check user-level keys (set via `/setkey`), not just shared `.env` keys.

**Adding a new provider** = create one file. That's it.

### 3. Tool Registry

```
tools/
├── base.py       # BaseTool (abstract)
├── registry.py   # auto-discover at boot
└── *.py          # each file = one tool (auto-registered)
```

**How it works:**
- On startup, `registry.py` scans `tools/` with `importlib` + `inspect`.
- Every class inheriting `BaseTool` is instantiated and registered.
- Each tool declares `name`, `description`, `commands`, and implements `execute()` + `get_tool_spec()`.
- The tool spec is a **generic dict** — each LLM provider converts it to its own format (Anthropic tool_use, Gemini function_declarations, OpenAI tools, etc.).

**Adding a new tool** = create one file. No imports to add, no config to update.

### 4. Memory Manager

- Stores chat history per user in SQLite.
- Feeds the N most recent messages as context to the LLM.
- Auto-cleanup by configurable retention policy.
- Supports `/new` (clear context) and `/history` (view past conversations).

### 5. Interface Layer

Two modes, switchable via `BOT_MODE` in `.env`:

| Mode | How | Best for |
|------|-----|----------|
| **Polling** | Long-poll loop in a background thread | Dev, home server |
| **Webhook** | FastAPI, responds 200 immediately, `BackgroundTask` | VPS, production |

Both share `telegram_common.py`: auth checks, message splitting, rate limiting.

### 6. Scheduler

- APScheduler with SQLite jobstore (single-process, no Redis).
- Per-user cron schedules (e.g. morning email briefing).
- Daily cleanup job: prune old chat history, tool logs, processed emails.

## Project Structure

```
openminicrew/
├── main.py                  # entry point
├── dispatcher.py            # command routing + LLM dispatch
├── scheduler.py             # APScheduler setup
│
├── core/                    # shared infrastructure
│   ├── config.py            # .env loader + validation
│   ├── llm.py               # LLM Router (thin wrapper)
│   ├── providers/           # LLM providers (auto-discovered)
│   ├── db.py                # SQLite + WAL + migrations
│   ├── memory.py            # chat context per user
│   ├── api_keys.py          # per-user key resolution (user key → shared key)
│   ├── user_manager.py      # auth, preferences, onboarding
│   ├── security.py          # OAuth token refresh
│   ├── concurrency.py       # semaphores, rate limiting
│   └── logger.py            # structured logging
│
├── tools/                   # tools (auto-discovered)
│   ├── base.py              # BaseTool abstract class
│   ├── registry.py          # auto-discover + help text
│   └── *.py                 # one file per tool
│
├── interfaces/              # Telegram interface
│   ├── telegram_polling.py  # Mode A
│   ├── telegram_webhook.py  # Mode B
│   └── telegram_common.py   # shared: send, split, rate limit
│
├── data/
│   └── openminicrew.db      # SQLite database
└── credentials/             # per-user OAuth tokens (gitignored)
```

## Data Flow: Free Text Message

```
User sends: "สรุปอีเมลวันนี้ให้หน่อย"
    │
    ▼
[telegram] → [user_manager: auth] → [memory: save + get context]
    │
    ▼
[dispatcher: no /command → call LLM Router]
    │
    ▼
[LLM Router → user prefers "claude" → ClaudeProvider.chat()]
    │  system prompt + context + tool specs
    ▼
[Claude returns tool_call: {name: "gmail_summary", args: "today"}]
    │
    ▼
[dispatcher → ToolRegistry.get("gmail_summary").execute(user_id, "today")]
    │
    ▼
[tool returns raw result → LLM summarizes in natural language]
    │
    ▼
[memory: save response] → [telegram: send to user]
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| **Transport** | Webhook: HTTPS + secret_token header verification |
| **Identity** | telegram chat_id → user_id mapping, role-based (owner/user) |
| **Credentials** | Per-user OAuth tokens, encrypted per-user API keys |
| **API keys** | User keys encrypted with Fernet; shared keys in `.env` (never committed) |
| **LLM** | No shell exec — tools only do what their code says |
| **Data** | SQLite WAL mode; auto-cleanup by retention policy |
| **Rate limiting** | Token bucket for Telegram API; semaphore for LLM calls |

## Extensibility Summary

| Want to... | Do this |
|------------|---------|
| Add a new tool | Create `tools/my_tool.py` inheriting `BaseTool` |
| Add a new LLM provider | Create `core/providers/my_provider.py` inheriting `BaseLLMProvider` |
| Add a new interface | Create `interfaces/my_interface.py` (e.g. LINE, Discord) |
| Change LLM per user | `/model <provider>` or update `default_llm` in DB |
| Add user API keys | `/setkey <service> <key>` — encrypted, per-user |
