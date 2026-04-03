# Why OpenMiniCrew

## The short version

OpenMiniCrew is a personal AI assistant that lives in your Telegram chat. You type a message or a command, an LLM figures out what you need, calls the right tool, and sends the result back. It handles email summaries, expense tracking, calendar, reminders, QR payments, web search, traffic, places, news, lottery, and unit conversion — all from one chat window.

It runs on a single VPS (Oracle Cloud Free Tier works fine), stores data in a single SQLite file, and costs almost nothing to operate. You own the server, you own the data, and you can add new tools by dropping a single Python file into a folder.

---

## Who is this for

OpenMiniCrew was built for a specific situation: you want an AI assistant that automates your daily tasks through a chat interface, but you also care about where your data goes and who can see it.

**Individual developers and tinkerers** who want a personal bot they fully control. You can read every line of code, modify any behavior, and host it wherever you want. No vendor lock-in, no subscription, no data leaving your infrastructure unless you explicitly connect an external API.

**Small teams or families** who want to share a single bot instance. Each user gets their own API keys, OAuth tokens, chat history, and expense records. The admin (server operator) cannot read other users' private data by design — not by policy, but by architecture. There is no admin command to view another user's emails, API keys, or chat history.

**People in Thailand** specifically. The tools understand Thai language input natively (the LLM handles this), support PromptPay QR generation with Thai national ID and phone number validation, use Thai land and gold weight units, connect to the Thai Meteorological Department API, check Thai lottery results, and comply with PDPA (Thailand's Personal Data Protection Act) through explicit consent flows and data deletion commands.

---

## What problem does it solve

Every day you open multiple apps to do small tasks: check email, log an expense, look up directions, check exchange rates, set reminders. Each app has its own interface, its own login, its own notifications. OpenMiniCrew consolidates these into a single conversational interface.

The key insight is that most personal automation tasks follow a simple pattern: understand the intent, call an API, format the result. You don't need a complex agent framework for this. You need a reliable dispatcher that routes requests to the right tool, a clean tool interface that's easy to extend, and sensible defaults that work without configuration.

---

## Design philosophy

**API-first, not browser-first.** OpenMiniCrew never opens a web browser. Every tool connects directly to APIs: Google Maps, Gmail, Tavily, Bank of Thailand, Open-Meteo, and others. This is a deliberate choice. Browser automation is fragile — websites change layouts, block bots, require CAPTCHAs, and break unpredictably. API calls are stable, fast, and predictable. The tradeoff is that OpenMiniCrew can only interact with services that expose APIs, but in practice this covers the vast majority of personal automation needs.

**Privacy by architecture, not by policy.** Multi-user isolation is enforced at the database query level. Every query filters by `user_id`. There is no function in the codebase that allows user A to read data belonging to user B, regardless of whether A is the admin. API keys are encrypted with Fernet symmetric encryption at rest. Gmail tokens are encrypted per-user. Sensitive messages (phone numbers, national IDs) are auto-deleted from Telegram after processing. The system supports explicit consent for Gmail access, location storage, and chat history — and provides `/delete_my_data confirm` for permanent hard deletion.

**Single-file simplicity.** The entire system runs in one Python process: FastAPI for the webhook, APScheduler for background jobs, SQLite in WAL mode for storage. No Redis, no Celery, no message queue, no microservices. This is not laziness — it is a deliberate choice for a personal assistant that serves a handful of users. Fewer moving parts means fewer things that break at 3 AM.

**Tools are the unit of extension.** Adding a new capability means creating one Python file in `tools/` that implements `execute()` and `get_tool_spec()`. The registry auto-discovers it on startup. The tool declares its commands, its description (which the LLM uses for routing), and its parameters. That's it. No plugin system to learn, no configuration files to edit, no deployment to redo.

**LLM as router, not as executor.** The LLM decides which tool to call and what arguments to pass. The tool executes deterministically — no LLM involved in the actual work. This separation keeps costs predictable (most requests need only one cheap LLM call) and behavior reproducible (the same tool input always produces the same output). A self-correction loop handles the occasional misroute: if the LLM picks a nonexistent tool or the tool errors out, the system feeds the error back and lets the LLM try again, up to 3 attempts.

---

## How it compares to full agent platforms

Platforms like OpenClaw (open-source, runs on Mac) represent a different approach to personal AI. They give you autonomous agents with persistent identities, proactive scheduling (the agent wakes up and does work without being asked), browser automation, and voice-first interaction. They are powerful and flexible.

OpenMiniCrew takes a different path:

**OpenClaw runs many agents for one person. OpenMiniCrew runs one bot for many people.** OpenClaw solves context overload by splitting work across specialized agents, each with their own "soul" and memory. OpenMiniCrew solves multi-tenancy by isolating user data at the database level. Different problems, different solutions.

**OpenClaw needs dedicated hardware. OpenMiniCrew runs on a free-tier VPS.** OpenClaw is designed to run on a Mac Mini (or similar always-on machine) with browser access. OpenMiniCrew runs on an ARM VM with 1 GB of RAM, no display, no browser, no GUI. Operating cost can be literally zero.

**OpenClaw is proactive. OpenMiniCrew is reactive (for now).** OpenClaw agents can wake up, check your CRM, draft emails, and message you with updates — all without being asked. OpenMiniCrew waits for you to send a message. It has a scheduler (`/schedule`) that can run tools on a cron schedule, but it does not yet have a "daily brief" that aggregates information proactively. This is on the roadmap.

**OpenClaw uses browser automation. OpenMiniCrew uses APIs.** This is the biggest practical difference. OpenClaw can interact with any website. OpenMiniCrew can only interact with services that have APIs. But APIs don't break when a website redesigns, don't get blocked by anti-bot systems, and don't need screenshots or DOM parsing. For the services OpenMiniCrew supports, the API approach is more reliable.

Neither approach is universally better. If you want an autonomous agent that can navigate arbitrary websites and work on your behalf while you sleep, look at OpenClaw. If you want a reliable, cheap, multi-user bot that handles structured daily tasks through stable API integrations with strong privacy guarantees, OpenMiniCrew is a better fit.

---

## Current strengths

**Multi-provider LLM support.** Claude, Gemini, and Matcha (any OpenAI-compatible endpoint) are supported out of the box. Users can switch providers per-user with `/model`. The system falls back automatically if a provider is unavailable. Matcha provides a zero-cost option for users who connect their own endpoint.

**Per-user API key management.** Services are classified into three tiers: shared (everyone uses the operator's key), shared-with-quota (operator provides a default, users can bring their own), and private-only (Gmail, Calendar, IMAP — never shared). The resolution logic is clean: check user key first, fall back to shared key, return nothing if private-only and no user key exists.

**Thai-specific tooling.** PromptPay QR generation with EMVCo payload, Thai national ID checksum validation, Thai phone number validation via `phonenumbers`, Thai land area units (rai/ngan/square wa), gold weight units (baht/salung/tamlung), exchange rates from Bank of Thailand, lottery results, and Thai language support across all LLM interactions.

**Expense tracking from photos.** Send a receipt photo in Telegram. Gemini Vision reads it, extracts the amount, date, and category, and logs the expense. No OCR library needed — the LLM handles Thai text natively.

**PDPA-compliant privacy controls.** Explicit consent model for Gmail, location, and chat history. Data retention limits enforced by scheduled cleanup jobs. Hard deletion via `/delete_my_data confirm`. Audit-ready consent records. Legal documentation (Terms of Service, Privacy Policy) in both Thai and English.

---

## Current limitations

These are honest constraints — some are by design, others are on the roadmap.

**No proactive behavior yet.** The bot only responds when you message it. It cannot wake up and tell you "you have a meeting in 30 minutes and traffic is heavy." The scheduler tool (`/schedule`) can run tasks on a timer, but there is no aggregated daily brief. This is the highest-priority roadmap item inspired by agent platforms.

**No voice input.** You must type or use Telegram's built-in voice-to-text. The bot does not process audio messages directly. Adding Gemini-based speech-to-text at the interface layer is straightforward but not yet implemented.

**No browser automation.** If a service does not have an API, OpenMiniCrew cannot interact with it. This means no scraping, no form filling, no interacting with web apps that lack APIs. This is by design (stability over flexibility) but it is a real limitation.

**Single-step tool calls only.** Each message can trigger one tool. If you ask "check my calendar for tomorrow and then look up traffic to the meeting location," the bot cannot chain calendar and traffic tools in sequence. You would need to send two messages. A multi-step dispatcher is designed and documented in the backlog but not yet implemented.

**No prompt injection defense in the system prompt (yet).** When the bot reads emails or web search results, the content is passed to the LLM for summarization. A malicious email could contain hidden instructions that the LLM might follow. Adding system prompt boundaries to reject instructions embedded in external content is planned and straightforward to implement, but it is not in the current codebase. This should be addressed before opening the bot to untrusted users.

**SQLite scaling ceiling.** SQLite in WAL mode handles concurrent reads well, but write contention becomes a factor beyond roughly 10-20 active users. For a personal or small-team bot this is fine. For larger deployments, the database layer would need to move to PostgreSQL.

**No web UI.** All interaction happens through Telegram. There is no dashboard, no analytics view, no settings page. Configuration is done through chat commands and environment variables. The operator manages the server through SSH and systemd.

**Onboarding is front-loaded.** New users see all available setup commands at once after `/start`. This can be overwhelming. A progressive approach — introducing features as users need them — would be better UX but is not yet implemented.

---

## What's on the roadmap

Based on real usage patterns and inspiration from agent platforms:

**Prompt injection defense** — adding system prompt boundaries to prevent the LLM from following instructions embedded in email content, web search results, or other external data. Low effort, high impact. Should be done before wider deployment.

**Progressive onboarding** — simplifying the `/start` flow to just register and say hello. Features are introduced when users first try to use them (e.g., "you need to run /setphone before generating a PromptPay QR").

**Daily brief** — a scheduled job that sends a morning summary: today's calendar events, overdue todos, email action items, and optionally weather. Uses the existing scheduler infrastructure and existing tools.

**Voice message support** — accepting Telegram voice messages, transcribing them with Gemini, and processing the text through the normal dispatcher. Change is limited to the interface layer.

**Weather tool (TMD + Open-Meteo)** — dual-API architecture using Thailand's official meteorological data for warnings and station observations, plus Open-Meteo for hourly forecasts, UV index, and air quality. Infrastructure preparation (API key management, location system) is already in place.

**Multi-step tool calling** — allowing the dispatcher to chain multiple tool calls in a single user message. Design is documented in `plan/backlog-multi-step-dispatcher.md` with a heuristic-based approach that preserves the current fast path for single-tool queries.

**User preferences** — language, timezone, notification style, default expense category. Stored per-user and injected into the system prompt for personalized LLM behavior.

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
