# Privacy, Consent, and Security

> 🇹🇭 [อ่านเป็นภาษาไทย](../th/PRIVACY_SECURITY.md)

This document explains how OpenMiniCrew currently handles privacy, consent, and security.
It is written as an implementation guide for operators and contributors, not as formal legal advice.

## Scope

OpenMiniCrew handles several classes of sensitive or private data:

- user profile data such as display name, phone number, and Thai national ID
- conversation history and conversation titles
- location data sent from Telegram
- Gmail and Google Calendar OAuth credentials
- per-user API keys and work email credentials
- derived metadata such as processed email state, tool logs, and job history

The system does not treat every field the same way. Protection depends on how the data is used at runtime.

## Privacy Principles

The current rollout follows these principles:

1. Collect only what is needed for the feature.
2. Use explicit consent for features with higher privacy impact.
3. Encrypt high-risk secrets and identifiers when the runtime does not need plaintext lookup.
4. Prefer minimization and retention limits for high-volume operational data.
5. Support revoke, delete, and hard-purge flows instead of treating deactivate as deletion.

## Consent Model

OpenMiniCrew currently tracks three explicit consent types in `user_consents`:

| Consent area | Internal type | New user default | How to grant | How to revoke | Current effect |
| --- | --- | --- | --- | --- | --- |
| Gmail | `gmail_access` | `not_set` | `/authgmail` OAuth flow | `/disconnectgmail` or `/consent gmail off` | Revoking removes Gmail token access and clears OAuth state |
| Location | `location_access` | `not_set` | `/consent location on` | `/consent location off` | Revoking deletes the saved location |
| Chat history | `chat_history` | `not_set` for newly onboarded users | `/consent chat on` | `/consent chat off` | Revoking stops future history writes and deletes saved chat history and conversations |

Important behavior:

- `/consent gmail on` does not directly grant Gmail access. Users must complete the real OAuth flow through `/authgmail`.
- Existing legacy users may have migrated consent states based on previously stored data.
- New users are initialized with explicit `not_set` consent records during onboarding.

## User-Facing Privacy Commands

The main privacy controls exposed to users are:

| Command | Purpose |
| --- | --- |
| `/privacy` | Show a summary of consent state, retention settings, location state, and API key hygiene |
| `/consent [gmail\|location\|chat] [on\|off]` | View or change explicit consent state |
| `/disconnectgmail` | Revoke Gmail access without purging all other user data |
| `/clearlocation` | Delete the last saved location |
| `/delete_my_data confirm` | Hard-purge user-linked data and credential artifacts |
| `/mykeys` | Review saved private keys and advisory rotation status |

## Current Data Protection Model

The table below reflects the current implementation.

| Data area | Current protection | Notes |
| --- | --- | --- |
| `users.phone_number` | Field-level encryption | Decrypt on read; legacy plaintext can migrate on read when `ENCRYPTION_KEY` is present |
| `users.national_id` | Field-level encryption | Decrypt on read; Telegram message deletion is attempted after `/setid` |
| `expenses.note` | Field-level encryption | Used for short expense notes; decrypted only when showing data back to the user |
| `user_api_keys.api_key` | Encrypted at rest | Private key storage requires `ENCRYPTION_KEY`; weak or placeholder-like values are rejected |
| `credentials/gmail_{user_id}.json` | Encrypted at rest | Per-user Gmail token files; plaintext legacy files auto-migrate when possible |
| `credentials.json` | Encrypted at rest managed storage | App-level Google OAuth client secret; runtime decrypts in memory and uses `from_client_config(...)` |
| Work email credentials stored through `/setkey` | Encrypted at rest | Includes `work_imap_host`, `work_imap_user`, and `work_imap_password` |
| `user_locations.latitude`, `user_locations.longitude` | Plaintext with consent and TTL controls | Location is operational data with explicit consent, cleanup, and manual delete support |
| `chat_history.content` and `conversations.title` | Plaintext with consent and retention controls | High-volume app data; protected through consent gating, retention, and purge semantics |
| `users.telegram_chat_id` | Plaintext operational identifier | Kept plaintext because it is the primary Telegram lookup key |
| Tool logs | Minimized structured metadata | New flows store kind, fingerprint hash, and size instead of raw input/output text; retention cleanup still applies |
| Processed email metadata | Minimized to message ID and has-subject flag | Subject, sender address, and sender domain are not stored; only a deduplication message ID and boolean has-subject flag are retained |

## Shared Keys vs Per-User Secrets

OpenMiniCrew supports two credential models:

1. Shared environment keys in `.env`
2. Per-user private keys stored through `/setkey`

Shared keys are used for services such as:

- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `TAVILY_API_KEY`
- `TMD_API_KEY`

Per-user private-only services include:

- `gmail`
- `calendar`
- `work_imap_host`
- `work_imap_user`
- `work_imap_password`

Security notes:

- private key storage requires `ENCRYPTION_KEY`
- weak and obviously placeholder-like secret values are rejected during `/setkey`
- API key rotation reporting is advisory in the current rollout; overdue keys are not blocked automatically

## Retention and Cleanup

Retention is enforced mainly by scheduled cleanup jobs and user-triggered deletion flows.

Current operator-visible retention settings include:

- chat history retention: `CHAT_HISTORY_RETENTION_DAYS`
- tool log retention: `TOOL_LOG_RETENTION_DAYS`
- email metadata retention: `EMAIL_LOG_RETENTION_DAYS`
- pending message retention: `PENDING_MSG_RETENTION_DAYS`
- job run retention: `JOB_RUN_RETENTION_DAYS`
- location TTL: `LOCATION_TTL_MINUTES`

Practical meaning:

- location can expire automatically based on TTL
- chat history and operational records are not kept forever by default
- users can also explicitly revoke consent or request a hard purge

## Revoke, Delete, and Purge Semantics

These actions are intentionally different:

| Action | What it means | What it does not mean |
| --- | --- | --- |
| Deactivate user | Marks the account inactive or deleted from an operator perspective | It is not a hard purge of all linked data |
| `/disconnectgmail` | Removes Gmail authorization state and deletes the Gmail token file when present | It does not purge all other user data |
| `/consent location off` | Revokes location consent and deletes the saved location | It does not purge unrelated history |
| `/consent chat off` | Revokes chat-history consent, stops future memory writes, and deletes saved chat history and conversations | It does not purge reminders, todos, expenses, or API keys |
| `/delete_my_data confirm` | Hard-purges user-linked records across multiple tables and deletes the Gmail token file | It is the only user-facing full purge command |

Current hard-purge coverage includes user-linked records in:

- `users`
- `chat_history`
- `conversations`
- `processed_emails`
- `tool_logs`
- `reminders`
- `todos`
- `expenses`
- `user_locations`
- `oauth_states`
- `user_consents`
- `user_api_keys`
- `pending_messages`
- `schedules`
- `job_runs` for the user-owned schedules
- Gmail token file under `credentials/gmail_{user_id}.json`

## Gmail and Google OAuth Security

The Gmail and Calendar integration uses two different secret classes:

1. App-level OAuth client secret in `credentials.json`
2. Per-user OAuth token files in `credentials/gmail_{user_id}.json`

Current design:

- the app-level client secret is stored as a managed encrypted-at-rest file when `ENCRYPTION_KEY` is configured
- legacy plaintext `credentials.json` can auto-migrate on first use
- operators should import a fresh plaintext OAuth client JSON through `python main.py --import-gmail-client-secrets /path/to/downloaded.json`
- per-user Gmail token files are encrypted at rest and auto-migrate from plaintext legacy files when possible
- secure file permissions are also applied to the managed files

## Logging and Minimization

The project is moving away from storing raw sensitive payloads in operational logs.

Current direction:

- structured log fields such as kind, reference hash, and payload size are preferred over raw text
- processed email storage has been minimized to only a deduplication message ID and a boolean has-subject flag; subject, sender address, and sender domain are no longer stored
- tool log safety fields avoid retaining raw input and output when a safer representation is sufficient

This does not mean the system stores no sensitive operational data. It means the default direction is to reduce storage wherever the feature does not require the full payload.

## Known Limitations

The current rollout still has important limitations:

- location data is still stored plaintext in the application database, with consent, TTL, and delete controls used as the primary mitigation
- chat history remains plaintext in the application database when consent is enabled
- `telegram_chat_id` remains plaintext because it is required for normal Telegram routing and lookup
- API key rotation is advisory only in the current rollout
- operators are still responsible for protecting the host, backups, `.env`, and deployment environment

## Operator Responsibilities

Operators should treat the following as mandatory operational controls:

1. Keep `.env`, database files, and credential files out of version control.
2. Configure `ENCRYPTION_KEY` before enabling private key storage or Gmail OAuth secret import.
3. Use the import flow for Gmail client secrets instead of editing the managed file by hand.
4. Protect the deployment host, filesystem permissions, and backups.
5. Review `/privacy`, `/mykeys`, and `/health` during support or security checks.
6. Use hard purge when a user requests full deletion instead of relying on deactivation alone.

## Summary

OpenMiniCrew currently uses a mixed model:

- encryption for high-risk secrets and selected direct identifiers
- explicit consent for Gmail, location, and chat history
- retention and purge flows for operational data
- minimization for logs and processed email metadata

That model is intentionally pragmatic. It protects the highest-risk data first while keeping Telegram routing, chat workflows, and tool execution usable in the current architecture.
