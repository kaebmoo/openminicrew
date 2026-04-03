# Why OpenMiniCrew

## The short version

OpenMiniCrew is a personal AI assistant that lives in your Telegram chat. You type a message or a command, an LLM figures out what you need, calls the right tool, and sends the result back. It handles email summaries, expense tracking, calendar, reminders, QR payments, web search, traffic, places, news, lottery, and unit conversion — all from one chat window.

It runs on a single VPS (Oracle Cloud Free Tier works fine), stores data in a single SQLite file, and costs almost nothing to operate. You own the server, you own the data, and you can add new tools by dropping a single Python file into a folder.

---

## Who is this for

OpenMiniCrew was built for a specific situation: you want an AI assistant that automates your daily tasks through a chat interface, but you also care about where your data goes and who can see it.

**Individual developers and tinkerers** who want a personal bot they fully control. You can read every line of code, modify any behavior, and host it wherever you want. No vendor lock-in, no subscription.

**Small teams or families** who want to share a single bot instance. Each user gets their own API keys, OAuth tokens, chat history, and expense records. The admin cannot read other users' private data — enforced by architecture, not policy (see [Design philosophy](#design-philosophy) for details).

**People in Thailand** specifically. The bot includes extensive Thai-specific tooling and complies with PDPA (see [Current strengths](#current-strengths) for the full list).

---

## What problem does it solve

Every day you open multiple apps to do small tasks: check email, log an expense, look up directions, check exchange rates, set reminders. Each app has its own interface, its own login, its own notifications. OpenMiniCrew consolidates these into a single conversational interface.

The key insight is that most personal automation tasks follow a simple pattern: understand the intent, call an API, format the result. You don't need a complex agent framework for this. You need a reliable dispatcher that routes requests to the right tool, a clean tool interface that's easy to extend, and sensible defaults that work without configuration.

---

## Design philosophy

**API-first, not browser-first.** OpenMiniCrew never opens a web browser. Every tool connects directly to APIs: Google Maps, Gmail, Tavily, Bank of Thailand, Open-Meteo, and others. This is a deliberate choice. Browser automation is fragile — websites change layouts, block bots, require CAPTCHAs, and break unpredictably. API calls are stable, fast, and predictable. The tradeoff is that OpenMiniCrew can only interact with services that expose APIs, but in practice this covers the vast majority of personal automation needs.

**Privacy by architecture, not by policy.** Multi-user isolation is enforced at the database query level. Every query filters by `user_id`. There is no function in the codebase that allows user A to read data belonging to user B, regardless of whether A is the admin. API keys are encrypted with Fernet symmetric encryption at rest. Gmail tokens are encrypted per-user. Sensitive messages (phone numbers, national IDs) are auto-deleted from Telegram after processing.

**Single-file simplicity.** The entire system runs in one Python process: FastAPI for the webhook, APScheduler for background jobs, SQLite in WAL mode for storage. No Redis, no Celery, no message queue, no microservices. This is not laziness — it is a deliberate choice for a personal assistant that serves a handful of users. Fewer moving parts means fewer things that break at 3 AM.

**Tools are the unit of extension.** Adding a new capability means creating one Python file in `tools/` that implements `execute()` and `get_tool_spec()`. The registry auto-discovers it on startup. The tool declares its commands, its description (which the LLM uses for routing), and its parameters. That's it. No plugin system to learn, no configuration files to edit, no deployment to redo.

**LLM as router, not as executor.** The LLM decides which tool to call and what arguments to pass. The tool executes deterministically — no LLM involved in the actual work. This separation keeps costs predictable (most requests need only one cheap LLM call) and behavior reproducible (the same tool input always produces the same output). A self-correction loop handles the occasional misroute: if the LLM picks a nonexistent tool or the tool errors out, the system feeds the error back and lets the LLM try again, up to 3 attempts.

---

## How it compares to full agent platforms

Platforms like OpenClaw (open-source, runs on Mac) represent a different approach to personal AI. They give you autonomous agents with persistent identities, proactive scheduling, browser automation, and voice-first interaction. Powerful and flexible.

OpenMiniCrew takes a different path:

| | OpenClaw | OpenMiniCrew |
|---|---------|-------------|
| **Architecture** | Many agents for one person | One bot for many people |
| **Hardware** | Dedicated machine (Mac Mini+) with browser | Free-tier VPS, ARM VM, 1 GB RAM, no display, no GUI |
| **Behavior** | Proactive — agents wake up and work autonomously | Reactive — waits for user messages (has `/schedule` for cron) |
| **Service access** | Browser automation — interacts with any website | API only — more stable but limited to services with APIs |

Neither approach is universally better. If you want an autonomous agent that can navigate arbitrary websites and work on your behalf while you sleep, look at OpenClaw. If you want a reliable, cheap, multi-user bot that handles structured daily tasks through stable API integrations with strong privacy guarantees, OpenMiniCrew is a better fit.

---

## Current strengths

**Multi-provider LLM support.** Claude, Gemini, and Matcha (any OpenAI-compatible endpoint) are supported out of the box. Users can switch providers per-user with `/model`. The system falls back automatically if a provider is unavailable. Matcha provides a zero-cost option for users who connect their own endpoint.

**Per-user API key management.** Services are classified into three tiers: shared (everyone uses the operator's key), shared-with-quota (operator provides a default, users can bring their own), and private-only (Gmail, Calendar, IMAP — never shared). The resolution logic is clean: check user key first, fall back to shared key, return nothing if private-only and no user key exists.

**Thai-specific tooling.** PromptPay QR generation with EMVCo payload, Thai national ID checksum validation, Thai phone number validation via `phonenumbers`, Thai land area units (rai/ngan/square wa), gold weight units (baht/salung/tamlung), exchange rates from Bank of Thailand, lottery results, and Thai language support across all LLM interactions.

**Expense tracking from photos.** Send a receipt photo in Telegram. Gemini Vision reads it, extracts the amount, date, and category, and logs the expense. No OCR library needed — the LLM handles Thai text natively.

**PDPA-compliant privacy controls.** Explicit consent model for Gmail, location, and chat history. Data retention limits enforced by scheduled cleanup jobs. Hard deletion via `/delete_my_data confirm`. Audit-ready consent records. Legal documentation (Terms of Service, Privacy Policy) in both Thai and English.

---

## Limitations and roadmap

Honest constraints — some are by design, others are being addressed.

| Limitation | Details | Status |
|-----------|---------|--------|
| **No proactive behavior yet** | Bot only responds to messages. Has `/schedule` for cron but no aggregated daily brief. | Roadmap — highest priority. Planned as a morning summary job (calendar, todos, email, weather). |
| **No voice input** | Must type or use Telegram's built-in voice-to-text. | Roadmap — interface-layer change only. Transcribe with Gemini, then pass to normal dispatcher. |
| **Single-step tool calls only** | Each message triggers one tool. "Check calendar then look up traffic" requires two messages. | Roadmap — design documented in `plan/backlog-multi-step-dispatcher.md`. |
| **No prompt injection defense yet** | Email and web search content is passed to the LLM for summarization. Hidden instructions could be followed. | Roadmap — low effort, high impact. Should be done before wider deployment. |
| **SQLite scaling ceiling** | Write contention becomes a factor beyond 10-20 active users. | Migrate to PostgreSQL when needed. |
| **No web UI** | All interaction through Telegram. Config via chat commands and env vars. | No current plan — Telegram is sufficient for the target use case. |
| **Front-loaded onboarding** | New users see all setup commands at once after `/start`. | Roadmap — progressive onboarding, introducing features when users first need them. |

**Additional roadmap items (not fixing limitations):**

- **Weather tool (TMD + Open-Meteo)** — dual-API architecture using Thailand's official meteorological data for warnings plus Open-Meteo for hourly forecasts. Infrastructure (API key management, location system) is already in place.
- **User preferences** — language, timezone, notification style, default expense category. Stored per-user and injected into the system prompt for personalized LLM behavior.

---

## Getting started

```bash
git clone https://github.com/kaebmoo/openminicrew.git
cd openminicrew
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Telegram bot token and at least one LLM API key
python main.py
```

Open your Telegram bot, send `/start`, and you're running.

For production deployment on Oracle Cloud Free Tier with webhook mode, nginx, and systemd, see the main [README](../../README.md).

---

## License

OpenMiniCrew is dual-licensed under AGPL-3.0 (free for open-source use; network service deployments must release source code) and a commercial license for proprietary use. See [LICENSING.md](../../LICENSING.md) for details.
