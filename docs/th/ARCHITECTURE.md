# OpenMiniCrew — สถาปัตยกรรม

> 🇬🇧 [English version](../en/ARCHITECTURE.md)

## OpenMiniCrew คืออะไร?

เฟรมเวิร์ก AI assistant ส่วนตัวที่ทำงานผ่าน Telegram bot — ผู้ใช้แชทตามปกติ แล้ว LLM จะเลือก tool ที่เหมาะสมให้เอง แค่วางไฟล์ Python ลงใน `tools/` ระบบจะ auto-discover ให้ทันที

## หลักการออกแบบ

| # | หลักการ | ทำไม |
|---|---------|------|
| 1 | **เพิ่ม tool = สร้างไฟล์เดียว** | ไม่ต้องแก้ core, ไม่ต้อง register, ไม่ต้อง import |
| 2 | **เพิ่ม LLM provider = สร้างไฟล์เดียว** | ไฟล์เดียวใน `core/providers/` พร้อม auto-fallback |
| 3 | **Per-user ทุกอย่าง** | แต่ละ user มี LLM preference, API keys, memory, credentials ของตัวเอง |
| 4 | **Direct command ไม่เสีย token** | `/email`, `/help` ฯลฯ ข้าม LLM ไปเลย — ไม่มีค่าใช้จ่าย |
| 5 | **Deploy process เดียว** | SQLite + APScheduler + worker เดียว ไม่ต้อง Redis, ไม่ต้อง Celery |
| 6 | **Production-ready ตั้งแต่วันแรก** | Webhook mode ตอบ 200 ทันที, ประมวลผล background |

## ภาพรวมระบบ

```
┌───────────────────────────────────────────────────┐
│                 INTERFACE LAYER                    │
│                                                   │
│   Telegram Bot              Scheduler             │
│   ┌───────────────────┐     (APScheduler)         │
│   │ Polling or Webhook │     cron jobs, cleanup    │
│   │ (สลับผ่าน .env)    │     per-user schedules    │
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
│   /command  ──→  เรียก Tool ตรง (ไม่เสีย token)   │
│   ข้อความอิสระ ──→  LLM Router ──→ tool หรือ chat │
│                                                   │
│   self-correction: ถ้า tool ผิดพลาด LLM ลองใหม่   │
│   โดยส่ง error feedback กลับ (สูงสุด N รอบ)       │
└──────┬────────────┬────────────┬──────────────────┘
       │            │            │
       ▼            ▼            ▼
 ┌──────────┐ ┌──────────┐ ┌──────────┐
 │LLM Router│ │  Tool    │ │ Memory   │
 │          │ │ Registry │ │ Manager  │
 │ Provider │ │          │ │          │
 │ Registry │ │ auto-    │ │ per-user │
 │          │ │ discover │ │ context  │
 │ fallback │ │ ตอน boot │ │ + cleanup│
 └──────────┘ └──────────┘ └──────────┘
       │            │            │
       ▼            ▼            ▼
┌───────────────────────────────────────────────────┐
│                 STORAGE LAYER                     │
│   SQLite (WAL mode) — ไฟล์เดียว, ไม่ต้อง config   │
│   tables: users, chat_history, tool_logs,         │
│           processed_emails, schedules,            │
│           user_api_keys, ...                      │
└───────────────────────────────────────────────────┘
```

## ระบบย่อยที่สำคัญ

### 1. Dispatcher — สมองของระบบ

Dispatcher รับทุกข้อความแล้วตัดสินใจว่าจะทำอะไร:

```
ข้อความเข้ามา
  │
  ├─ ขึ้นต้นด้วย /command? → ค้นหาใน Tool Registry → execute ตรง
  │
  ├─ ข้อความอิสระ? → สร้าง context (Memory) → เรียก LLM Router
  │   │
  │   ├─ LLM เลือก tool → execute tool → LLM สรุปผล
  │   └─ LLM ไม่เลือก tool → ตอบเป็น general chat
  │
  └─ ทุกกรณี → บันทึกลง Memory + tool_logs
```

**Self-correction loop**: ถ้า LLM เลือก tool ผิด หรือ tool error จะส่ง error กลับให้ LLM คิดใหม่ (กำหนด max rounds ได้)

### 2. LLM Router + Provider Registry

```
core/providers/
├── base.py              # BaseLLMProvider (abstract)
├── claude_provider.py   # provider ตัวหนึ่ง
├── gemini_provider.py   # อีกตัว
├── matcha_provider.py   # อีกตัว (OpenAI-compatible)
└── registry.py          # auto-discover + fallback
```

**ทำงานยังไง:**
- ตอน startup, `registry.py` scan `core/providers/` แล้ว instantiate ทุก class ที่ inherit `BaseLLMProvider`
- แต่ละ provider implement `is_configured()`, `chat()`, `convert_tool_spec()`
- Router ลอง provider ที่ user เลือกก่อน ถ้าไม่พร้อมก็ fallback ไปตัวถัดไป
- Per-user API keys: provider override `is_available_for_user(user_id)` ได้ เพื่อเช็ค key ระดับ user (จาก `/setkey`) ไม่ใช่แค่ shared key จาก `.env`

**เพิ่ม provider ใหม่** = สร้างไฟล์เดียว จบ

### 3. Tool Registry

```
tools/
├── base.py       # BaseTool (abstract)
├── registry.py   # auto-discover ตอน boot
└── *.py          # แต่ละไฟล์ = tool หนึ่งตัว (auto-registered)
```

**ทำงานยังไง:**
- ตอน startup, `registry.py` scan `tools/` ด้วย `importlib` + `inspect`
- ทุก class ที่ inherit `BaseTool` จะถูก instantiate และ register
- แต่ละ tool ประกาศ `name`, `description`, `commands` และ implement `execute()` + `get_tool_spec()`
- Tool spec เป็น **dict กลาง** — แต่ละ LLM provider แปลงเป็น format ของตัวเอง (Anthropic tool_use, Gemini function_declarations, OpenAI tools ฯลฯ)

**เพิ่ม tool ใหม่** = สร้างไฟล์เดียว ไม่ต้อง import, ไม่ต้องแก้ config

### 4. Memory Manager

- เก็บ chat history per user ใน SQLite
- ส่ง N messages ล่าสุดเป็น context ให้ LLM
- Auto-cleanup ตาม retention policy ที่ตั้งไว้
- รองรับ `/new` (ล้าง context) และ `/history` (ดูประวัติ)

### 5. Interface Layer

สอง mode สลับได้ผ่าน `BOT_MODE` ใน `.env`:

| Mode | วิธี | เหมาะกับ |
|------|------|---------|
| **Polling** | Long-poll loop ใน background thread | Dev, เครื่องที่บ้าน |
| **Webhook** | FastAPI, ตอบ 200 ทันที, `BackgroundTask` | VPS, production |

ทั้งสอง mode ใช้ `telegram_common.py` ร่วมกัน: auth, แบ่งข้อความยาว, rate limiting

### 6. Scheduler

- APScheduler + SQLite jobstore (process เดียว, ไม่ต้อง Redis)
- Per-user cron schedules (เช่น สรุปอีเมลเช้า)
- Daily cleanup job: ลบ chat history, tool logs, processed emails เก่า

## โครงสร้างโปรเจกต์

```
openminicrew/
├── main.py                  # entry point
├── dispatcher.py            # command routing + LLM dispatch
├── scheduler.py             # APScheduler setup
│
├── core/                    # โครงสร้างพื้นฐาน
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
│   └── *.py                 # ไฟล์ละตัว
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

## Data Flow: ข้อความอิสระ

```
User ส่ง: "สรุปอีเมลวันนี้ให้หน่อย"
    │
    ▼
[telegram] → [user_manager: auth] → [memory: save + get context]
    │
    ▼
[dispatcher: ไม่ใช่ /command → เรียก LLM Router]
    │
    ▼
[LLM Router → user เลือก "claude" → ClaudeProvider.chat()]
    │  system prompt + context + tool specs
    ▼
[Claude return tool_call: {name: "gmail_summary", args: "today"}]
    │
    ▼
[dispatcher → ToolRegistry.get("gmail_summary").execute(user_id, "today")]
    │
    ▼
[tool return ผลดิบ → LLM สรุปเป็นภาษาธรรมชาติ]
    │
    ▼
[memory: save response] → [telegram: ส่งกลับ user]
```

## Security Model

| ชั้น | กลไก |
|------|------|
| **Transport** | Webhook: HTTPS + ตรวจ secret_token header |
| **Identity** | telegram chat_id → user_id, role-based (owner/user) |
| **Credentials** | Per-user OAuth tokens, encrypted per-user API keys |
| **API keys** | User keys เข้ารหัสด้วย Fernet; shared keys อยู่ใน `.env` (ไม่ commit) |
| **LLM** | ไม่มี shell exec — tool ทำได้แค่ที่โค้ดเขียนไว้ |
| **Data** | SQLite WAL mode; auto-cleanup ตาม retention policy |
| **Rate limiting** | Token bucket สำหรับ Telegram API; semaphore สำหรับ LLM calls |

## สรุปความยืดหยุ่น

| อยากจะ... | ทำแค่นี้ |
|-----------|---------|
| เพิ่ม tool ใหม่ | สร้าง `tools/my_tool.py` inherit `BaseTool` |
| เพิ่ม LLM provider | สร้าง `core/providers/my_provider.py` inherit `BaseLLMProvider` |
| เพิ่ม interface ใหม่ | สร้าง `interfaces/my_interface.py` (เช่น LINE, Discord) |
| เปลี่ยน LLM per user | `/model <provider>` หรือแก้ `default_llm` ใน DB |
| เพิ่ม API key per user | `/setkey <service> <key>` — เข้ารหัส, แยก per-user |
