# OpenMiniCrew — Building a Real AI Personal Assistant on Telegram with Python

> An open-source framework for building an AI assistant on Telegram that actually does things: summarizes your email, tracks expenses from receipt photos, generates PromptPay QR codes, checks real-time traffic, and more — with PDPA-aware privacy baked in from day one.

---

## The Problem: AI That Talks vs. AI That Works

Most AI chatbots are great at conversation but terrible at doing anything. You can ask ChatGPT to summarize your email, but it can't actually read your inbox. You can ask it for traffic conditions, but it doesn't know where you are.

OpenMiniCrew was built to bridge that gap. It's a Python framework for building an AI personal assistant that runs on Telegram — one that doesn't just answer questions, but connects to real APIs, executes real tasks, and returns real results. All through a chat interface you already use every day.

The entire system runs on a single Python process with SQLite. No Redis. No Celery. No Kubernetes. It deploys comfortably on an Oracle Cloud Free Tier ARM VM.

<!-- [Image 1: Screenshot of a Telegram chat with OpenMiniCrew showing multiple interactions — email summary, QR code generation, traffic check] -->

---

## What OpenMiniCrew Actually Is

At its core, OpenMiniCrew is a **tool-calling AI framework** with three key components:

**An LLM brain** that understands what the user wants. It supports Claude (Anthropic), Gemini (Google), and Matcha (any OpenAI-compatible endpoint). Each user can pick their preferred provider, and the system falls back automatically if one is unavailable.

**A tool system** where each tool connects to a real API or service. The LLM decides which tool to call based on the user's message, the tool executes, and the result comes back — either directly or summarized by the LLM into natural language.

**A plug-and-play architecture** where adding a new tool means creating a single Python file in the `tools/` directory. No core modifications. No manual registration. The system auto-discovers everything on startup.

---

## Architecture: Simple Enough to Deploy, Flexible Enough to Extend

### The Dispatcher

Every message flows through the dispatcher, which makes a simple routing decision:

If the message starts with a `/command`, it routes directly to the matching tool — **no LLM call, zero token cost**. This is important for cost control; commands like `/expense 120 food noodles` or `/lotto` never touch the LLM API.

If the message is free-form text like "summarize my email" or "how's the traffic to Silom?", it goes to the LLM Router. The LLM sees the specifications of all available tools and decides whether to call one (via function calling) or respond as a general chatbot.

### Self-Correction Loop

The dispatcher includes an agentic retry mechanism. If the LLM picks a non-existent tool name (e.g., calling "lottery" instead of "lotto"), or if a tool throws an error, the system feeds the error back to the LLM and lets it try again — up to 3 rounds. If all retries fail, it escalates to a smarter (more expensive) LLM tier as a final fallback.

In the happy path where everything works on the first try, there's zero overhead from this mechanism.

### Multi-Provider LLM Support

Three providers are supported out of the box:

- **Claude** — Anthropic's native tool_use API. Strong at Thai language understanding.
- **Gemini** — Google's function declarations + Vision API for receipt OCR. Generous free tier.
- **Matcha** — Any OpenAI-compatible endpoint via `httpx`. Perfect for self-hosted models or corporate API gateways.

Each user selects their provider with `/model`. The system auto-falls-back through available providers if the preferred one fails. Adding a new provider is the same pattern as tools: create one Python file in `core/providers/` that inherits `BaseLLMProvider`, and it's auto-discovered.

<!-- [Image 2: Architecture diagram — Telegram → Dispatcher → LLM Router / Tool Registry → SQLite] -->

---

## The Tools: 19+ and Counting

### Email & Communication

**Gmail Summary** (`/email`) — Summarizes your Gmail using per-user OAuth. Uses a mid-tier LLM (Sonnet/Pro) for better comprehension. Supports time ranges like `/email 7d` for the past week.

**Work Email** (`/wm`) — Summarizes corporate email via IMAP with per-user credentials stored through `/setkey`. Supports subject/sender search and time filtering.

**Smart Inbox** (`/inbox`) — Analyzes recent Gmail to extract action items and can auto-create todos from emails with `/inbox mode auto`.

### Finance

**Expense Tracker** (`/expense`) — Records expenses by typing, e.g., `/expense 120 food noodles`. But the standout feature is **receipt photo scanning**: send a photo of a receipt or payment slip, and the system uses Gemini Vision to extract every line item, calculate proportional service charge and VAT distribution, and present an inline keyboard letting you choose to record items individually or as a combined total. It detects duplicate receipts via image hash to prevent double-recording.

The tool includes an **income intent guard** — if you type "receive 150 baht" (which is a PromptPay intent, not an expense), it refuses to record and redirects you to the correct tool.

**PromptPay QR** (`/pay`) — Generates QR codes for Thailand's PromptPay mobile payment system. Supports both phone numbers and national ID cards (13 digits with checksum validation). Uses the `phonenumbers` library for Thai mobile validation and `segno` for QR generation (zero dependency on Pillow). If you don't specify a number, it uses your saved data from `/setphone` or `/setid` automatically.

**Exchange Rate** (`/fx`) — Real-time rates from the Bank of Thailand API.

**Lottery** (`/lotto`) — Checks Thai government lottery results.

<!-- [Image 3: Screenshot of receipt photo scanning — showing the multi-item preview with inline keyboard buttons for "Split items" vs "Combine"] -->

<!-- [Image 4: Screenshot of a PromptPay QR code generated by /pay 500] -->

### Places & Navigation

**Places** (`/places`) — Searches locations via Google Places API (New). Detects Thai keywords like "nearby" to use the user's GPS as location bias, and "open now" to filter by current opening hours. Returns ratings, addresses, opening hours, and Google Maps links.

**Traffic** (`/traffic`) — Checks routes, distances, travel time, and real-time traffic via Google Maps. Supports four modes: driving, walking, transit, and motorcycle. Detects Thai-language mode keywords (e.g., "motorbike", "walk", "BTS"). Shows up to 3 alternative routes with clickable Google Maps URLs. Even supports "avoid tolls" in Thai.

### Tasks & Calendar

**Todo** (`/todo`) — Task management with priority levels and due dates.

**Reminder** (`/remind`) — One-time reminders at a specified datetime. Uses APScheduler with SQLite jobstore for persistence across restarts.

**Schedule** (`/schedule`) — Automated tool execution on a cron schedule, e.g., email summary every morning at 8 AM.

**Google Calendar** (`/cal`) — View, create, and delete events. Shares OAuth with Gmail.

### Information & Utilities

**Web Search** (`/search`) — Google Custom Search with LLM-powered result summarization.

**News Summary** (`/news`) — Pulls from Google News RSS, then uses LLM to categorize and summarize headlines with reference links. No API key required.

**Unit Converter** (`/convert`) — General conversions plus Thai-specific units (rai/ngan/square wah for land, baht weight for gold).

**QR Code Generator** (`/qr`) — General-purpose QR codes from text or URLs (separate from PromptPay).

---

## Two Ways to Interact

### Direct Commands — Zero LLM Cost

Type a command like `/expense 120 food` or `/traffic Siam to Silom` and the system routes directly to the tool. No LLM involved, no API cost, instant response.

### Free-Form Text — AI-Powered Routing

Type naturally: "What's the weather like?", "Any coffee shops nearby?", "Summarize my email" — the LLM understands your intent and picks the right tool via function calling.

What makes the routing accurate is a **structured tool_spec format** with three components:

1. **Positive scope** — what the tool does
2. **Negative boundary** — what it doesn't do, and which tool to use instead
3. **Examples** — sample inputs that should route here

For instance, the expense tool explicitly states: "Do not use for income/receiving money — if the user wants to receive money or generate a payment QR, use the promptpay tool instead." This prevents the LLM from confusing similar intents.

---

## Privacy Architecture: PDPA by Design

For a system handling personal data — names, phone numbers, national ID numbers, email content, GPS locations — privacy can't be an afterthought. OpenMiniCrew builds it into the architecture from the ground up.

### Explicit Consent

Three consent types, each independently controlled:

- **Gmail** — Requires actual OAuth authorization via `/authgmail`, not just a consent toggle. Revocable with `/disconnectgmail`.
- **Location** — Must be explicitly granted with `/consent location on`. Revoking deletes all stored location data immediately.
- **Chat history** — Must be explicitly granted. Revoking stops recording and deletes all existing conversation history.

New users start with all three set to `not_set`. Nothing is granted by default.

### Field-Level Encryption

High-risk data is encrypted at the field level using Fernet:

- Phone numbers and national ID numbers in the users table
- Expense notes (may contain sensitive merchant/payment info)
- Per-user API keys
- Gmail OAuth tokens and the app-level OAuth client secret

### Data Minimization

The system actively minimizes what it stores:

- **Tool logs** no longer store raw input/output text. Instead, they store only the content kind, a reference hash, and payload size.
- **Processed email metadata** stores only the message ID (for dedup) and a boolean has-subject flag. No subject lines, sender addresses, or domains.

### Retention & Automatic Cleanup

Nothing is stored forever. Scheduled cleanup jobs delete data based on configurable retention periods for chat history, tool logs, email metadata, pending messages, and job runs. Location data has a separate TTL that expires automatically.

### Hard Purge

Users can execute `/delete_my_data confirm` to permanently delete all data tied to their account across 15+ database tables plus their Gmail token file. The only intentional exception is `security_audit_logs`, retained for governance and incident investigation.

### Security Audit Trail

The system logs security-relevant events — profile secret access, API key updates, hard purges, Gmail revocations — without storing raw secret payloads. This provides accountability without creating additional exposure.

### Privacy Dashboard

The `/privacy` command shows a complete summary: consent states, retention settings, location status, API key hygiene (including rotation advisories and weak key detection), and available data management actions.

<!-- [Image 5: Screenshot of /privacy command output showing consent status, retention settings, and key hygiene] -->

---

## Admin vs. User: Architectural Separation

OpenMiniCrew enforces admin/user separation **by architecture, not just policy**. The admin (owner) can manage user accounts and audit API key storage, but cannot:

- Read another user's chat history
- View another user's saved API keys
- Access another user's Gmail or Calendar
- Decrypt another user's phone number or national ID

The system also supports self-registration via `/start`, with configurable auto-approve or manual approval by the owner.

---

## Production Deployment

The project runs in production on Oracle Cloud Free Tier (ARM VM, Ubuntu 22.04) using webhook mode:

**FastAPI + uvicorn** behind **nginx** reverse proxy. The webhook endpoint uses a cryptographically random path (not `/webhook`) and verifies Telegram's `secret_token` header on every request. FastAPI returns HTTP 200 immediately and processes the message as a background task.

**Key rotation** is supported via a keyring model: deploy a new `ENCRYPTION_KEY`, move the old one to `ENCRYPTION_KEY_PREVIOUS`, run `--rotate-encryption` to re-encrypt all sensitive data, verify, then remove the old key.

A **systemd service file** is included for automatic restart and `journalctl` log access.

<!-- [Image 6: Deployment diagram — Telegram Cloud → nginx (HTTPS/Let's Encrypt) → FastAPI/uvicorn → SQLite] -->

---

## Adding a New Tool: One File, Zero Config

The design goal is **"add a tool = create one file"**. Here's the minimal structure:

```python
from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "What this tool does — the LLM reads this to decide routing"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        return f"Result: {args}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string", "description": "Describe the parameter"}
                },
            },
        }
```

Drop this file in `tools/`, restart the bot, and it's live — accessible both via `/mytool xxx` and free-form text.

Tools that need internal LLM calls can set `preferred_tier = "mid"` for a smarter model (Sonnet/Pro). Tools that return images (like QR codes) use a `MediaResponse` object that the framework automatically sends as a Telegram photo.

The tool spec format acts as a universal schema — each LLM provider's adapter converts it to the native format (Anthropic tool_use, Gemini function_declarations, OpenAI tools) automatically.

---

## What's Next

**Weather Tool** — A dual-API strategy combining TMD (Thai Meteorological Department) for official Thai forecasts and warnings with Open-Meteo for hourly data, UV index, and extended forecasts.

**Improved Intent Routing** — Refined tool_spec descriptions and input guards to further reduce misrouting between similar tools.

**Multi-Platform Support** — The architecture already separates the interface layer from core logic. Tools don't know about Telegram. Adding LINE or WhatsApp support is a matter of writing a new interface adapter.

---

## Try It

OpenMiniCrew is open-source under AGPL-3.0 with a commercial dual-license option.

- **Personal use, learning, research**: Free, no restrictions.
- **Deploy as a service**: Open-source your full system under AGPL-3.0, or contact for a commercial license.

Repository: [github.com/kaebmoo/openminicrew](https://github.com/kaebmoo/openminicrew)

---

*OpenMiniCrew is developed by kaebmoo. For commercial licensing inquiries: kaebmoo@gmail.com*
