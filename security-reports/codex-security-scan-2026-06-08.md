# Codex Security Scan Report

Repository: `openminicrew`

Original scan date: 2026-06-08

Recreated durable copy: 2026-06-10

Original temporary report path was under `/tmp/codex-security-scans/...` and was lost when `/tmp` was cleaned. This file is the durable workspace copy for remediation.

## Summary

Reportable findings: 10

Severity mix:

- High: 4
- Medium: 5
- Low: 1

Validation notes:

- Static source tracing was used for all findings.
- Targeted pytest passed for provider fallback, `/setkey` dispatch, and `/health` readiness response.
- Gmail/Smart Inbox/Work Email runtime tests could not be collected in the prior environment because `googleapiclient` was missing, although it is declared in `requirements.txt`.

## High Findings

### 1. Webhook accepts forged Telegram updates when `TELEGRAM_WEBHOOK_SECRET` is unset

Severity: High

Affected code:

- `interfaces/telegram_webhook.py:101-105`
- `core/readiness.py:88-96`
- `interfaces/telegram_webhook.py:217-232`
- `interfaces/telegram_webhook.py:273-275`

Issue:

Webhook mode only verifies `X-Telegram-Bot-Api-Secret-Token` when `TELEGRAM_WEBHOOK_SECRET` is configured. Missing secret is a warning, not a startup blocker. A public webhook deployment with no secret can accept forged Telegram-shaped updates and dispatch them as the supplied `chat_id`.

Fix:

- Fail startup in webhook mode when `TELEGRAM_WEBHOOK_SECRET` is empty.
- Always reject webhook POSTs with missing or mismatched secret headers.
- Add tests for secret missing, wrong secret, and correct secret.

Suggested test:

- Instantiate webhook handler with webhook mode and empty secret, then assert startup/readiness fails.
- POST a fake update without the secret and assert 403.

### 2. `/remind fire <id>` reads and marks reminders without user ownership

Severity: High

Affected code:

- `tools/reminder.py:27-33`
- `core/db.py:1256-1264`
- `core/db.py:1277-1282`
- `tools/reminder.py:101-107`

Issue:

The `fire` branch calls `db.get_reminder(id)` and `db.mark_reminder_sent(id)` without passing `user_id`. Any registered user can enumerate reminder ids, read another user's reminder text, and mark it sent.

Fix:

- Pass `user_id` into the `fire` lookup and update.
- Consider splitting scheduler-only reminder firing from user-triggered `/remind fire`.
- Make `mark_reminder_sent` require `user_id` unless called from a clearly trusted scheduler path.

Suggested test:

- Create reminders for user A and user B.
- Assert user A cannot fire user B's reminder id.

### 3. Work Email disables IMAP TLS verification after certificate failure

Severity: High

Affected code:

- `tools/work_email.py:145-155`

Issue:

After `ssl.SSLCertVerificationError`, Work Email reconnects with `check_hostname=False` and `verify_mode=ssl.CERT_NONE`, then logs in with the user's IMAP credentials. A TLS MITM or malicious endpoint can capture credentials.

Fix:

- Remove the `CERT_NONE` fallback.
- Fail closed on certificate verification errors.
- If private CA support is required, add an explicit configured CA bundle path.

Suggested test:

- Mock `imaplib.IMAP4_SSL` to raise `SSLCertVerificationError`.
- Assert `conn.login` is never called.

### 4. API-key-bearing messages are persisted in logs and chat history before secure handling

Severity: High

Affected code:

- `dispatcher.py:389`
- `dispatcher.py:406`
- `dispatcher.py:238`
- `core/db.py:1641-1648`
- `core/logger.py:21-27`
- `tools/apikeys.py:40-66`

Issue:

The key tool stores API keys securely, but `process_message` logs and saves raw message text before dispatch. A user sending `/setkey tmd <secret>` can leave the secret in logs and `chat_history` before the Telegram message is deleted.

Fix:

- Detect secret-bearing commands before logging or saving chat history.
- Redact `/setkey` values and secret tool arguments.
- Skip memory persistence for known secret commands.
- Redact `tool_args` for tools with secret parameters.

Suggested test:

- Dispatch `/setkey tmd realistic-secret-token-12345`.
- Assert logs and `chat_history` do not contain the token.

## Medium Findings

### 5. Public `/health` exposes operational security metadata and raw provider network config

Severity: Medium

Affected code:

- `interfaces/telegram_webhook.py:155-195`
- `core/readiness.py:64-72`
- `core/readiness.py:88-96`
- `core/connectivity.py:97-139`
- `core/api_keys.py:273-280`
- `core/db.py:913-934`

Issue:

`GET /health` is unauthenticated and returns readiness, key hygiene, audit summaries, DB status, provider status, scheduler state, and raw provider connectivity fields such as URL and proxy.

Fix:

- Split public liveness from private diagnostics.
- Require authentication or trusted-network access for detailed health data.
- Redact provider URLs, proxy values, credential paths, key hygiene details, and audit counts from public responses.

Suggested test:

- Call `/health` without auth and assert only minimal public liveness fields are present.

### 6. Gmail consent revocation can be bypassed by stale token files

Severity: Medium

Affected code:

- `core/privacy_commands.py:177-187`
- `core/privacy_commands.py:238-247`
- `core/db.py:1079-1125`
- `core/security.py:266-290`
- `core/system_commands.py:37-44`
- `tools/gmail_summary.py:144`
- `tools/smart_inbox.py:44`
- `tools/calendar_tool.py:97`

Issue:

Revocation updates DB state and attempts to delete the Gmail token file, but later `get_gmail_credentials` returns credentials based only on token file existence and validity. If token deletion fails or a stale token remains, Gmail/Calendar access can continue after consent revocation.

Fix:

- Make `get_gmail_credentials` check current Gmail consent and `gmail_authorized`.
- Treat token deletion failure as a visible failure, not just a warning.
- Avoid re-authorizing Gmail in `/start` solely because a token file exists.

Suggested test:

- Create a valid token file but set Gmail consent revoked.
- Assert `get_gmail_credentials(user_id)` returns `None`.

### 7. LLM provider fallback bypasses per-user availability checks and can use shared provider keys

Severity: Medium

Affected code:

- `core/providers/registry.py:91-103`
- `core/llm.py:105-108`
- `core/providers/claude_provider.py:127-143`
- `core/providers/gemini_provider.py:40-55`

Issue:

Direct provider selection checks `is_available_for_user(user_id)`, but fallback selection uses provider-wide `is_configured()`. A non-owner user without a personal provider key can reach shared Claude/Gemini keys through fallback.

Fix:

- When `user_id` is present, fallback candidates must pass `is_available_for_user(user_id)`.
- Apply the same rule in auth-error retry fallback.
- Keep fallback quota as rate limiting, not authorization.

Suggested test:

- Non-owner without personal Gemini/Claude key should not fallback to shared Gemini/Claude.

### 8. Email LLM calls omit `user_id` and bypass per-user provider controls

Severity: Medium

Affected code:

- `tools/work_email.py:562-570`
- `tools/smart_inbox.py:131-138`
- `tools/gmail_summary.py:244-251`
- `core/llm.py:50-67`
- `core/providers/registry.py:54-58`

Issue:

Work Email and Smart Inbox send sensitive email content to `llm_router.chat` without `user_id`. With no `user_id`, provider selection uses shared configured providers instead of per-user provider controls. Gmail Summary passes `user_id` correctly and is the local counterexample.

Fix:

- Pass `user_id=user_id` in Work Email and Smart Inbox LLM calls.
- Add tests for every tool that sends user data to LLM to assert `user_id` is propagated.

Suggested test:

- Patch `llm_router.chat` and assert Work Email and Smart Inbox call it with `user_id`.

### 9. Work Email fetches and decodes attachments before enforcing size and parser limits

Severity: Medium

Affected code:

- `tools/work_email.py:407-414`
- `tools/work_email.py:323-341`
- `tools/work_email.py:266-306`

Issue:

Work Email fetches full IMAP messages and decodes attachment payloads into memory before enforcing the attachment size limit. Parser limits happen after allocation.

Fix:

- Fetch MIME structure first when possible.
- Enforce raw message and part-size limits before decoding.
- Cap decoded bytes and attachment counts.
- Avoid parser calls for oversized payloads.

Suggested test:

- Create a MIME message with an oversized attachment.
- Assert parser functions are not called and the attachment is skipped before full decode.

## Low Finding

### 10. Smart Inbox auto mode lets malicious email content create todo items without confirmation

Severity: Low

Affected code:

- `tools/smart_inbox.py:36-42`
- `tools/smart_inbox.py:55-62`
- `tools/smart_inbox.py:91-99`
- `tools/smart_inbox.py:116-138`
- `prompts/internal/smart_inbox_action_items.md:5-10`

Issue:

When Smart Inbox is in `auto` mode, external email bodies are passed to an LLM prompt and bullet-like output is inserted directly as todos. A malicious sender can influence todo creation when the victim runs `/inbox`.

Fix:

- Keep `confirm` mode as default.
- For auto mode, add confirmation for first-time senders or unusual action items.
- Separate quoted email content from instructions more structurally.
- Cap the number of auto-created todos.

Suggested test:

- Feed adversarial email content and assert auto-created todos are either blocked, capped, or require confirmation.

## Deferred / Suppressed Candidates

### OMC-011. Matcha HTTP error logging may persist provider-echoed prompt fragments

Status: Deferred

Reason:

`core/providers/matcha_provider.py:144-150` logs raw HTTP error response body. The code proves raw error-body logging, but the scan did not prove the real Matcha gateway echoes prompt content.

Follow-up:

- Send a harmless unique marker to the real gateway.
- Force an HTTP status error.
- Check whether the marker appears in `logs/agent_YYYYMM.log`.

### OMC-012. Stored external-content summaries may influence later side-effecting tool calls

Status: Suppressed for this scan

Reason:

The stored-context path is plausible, but immediate same-cycle tool summaries do not pass tools, and no dynamic reproduction showed a later side effect.

Follow-up:

- Treat as hardening context for LLM/tool design.
- Add confirmation gates for side-effecting tool calls if prompt-injection risk is a priority.

## Recommended Fix Order

1. Fix webhook secret enforcement.
2. Fix reminder ownership checks.
3. Remove IMAP TLS fail-open.
4. Redact or skip secret-bearing logs and chat history.
5. Lock down `/health`.
6. Add consent checks to Gmail credential reads.
7. Fix LLM provider fallback authorization.
8. Propagate `user_id` in Work Email and Smart Inbox LLM calls.
9. Add Work Email attachment size controls.
10. Harden Smart Inbox auto mode.

## Suggested Verification Commands

After dependencies are installed:

```bash
python3 -m pytest tests/test_fallback_quota.py tests/test_api_key_management.py tests/test_phase2_privacy.py
python3 -m pytest tests/test_tool_user_lookup.py tests/test_tool_parsing_regressions.py tests/test_new_tools.py
```

Add focused regression tests while fixing each item, then run the full test suite.

## Remediation Status (2026-06-10)

All 10 findings verified against source and fixed. Regression tests in `tests/test_security_fixes.py` + updated `tests/test_webhook.py`.

1. **Fixed** — webhook secret: `core/readiness.py` makes `webhook_secret` a required FAIL check in webhook mode (fail-fast at boot); `interfaces/telegram_webhook.py` rejects all POSTs with 403 unless the header matches a configured secret (constant-time compare). Docs/.env.example updated.
2. **Fixed** — `/remind fire <id>` now passes `user_id` to `db.get_reminder` and `db.mark_reminder_sent` (new optional `user_id` filter). Scheduler path unaffected (executes as schedule owner).
3. **Fixed** — removed `CERT_NONE` fallback in `tools/work_email.py:_connect_imap`; cert failures now fail closed before login.
4. **Fixed** — `core/api_keys.py` adds `redact_secret_text` / `redact_secret_tool_args`; applied in `dispatcher.process_message` (log + chat_history + conversation title), dispatcher tool-failure logs, LLM tool-call arg logs/feedback, webhook dead-letter log, polling log.
5. **Fixed** — `/health` returns only `status`, `bot_mode`, `uptime_seconds`, `timestamp` publicly; full diagnostics require `X-Health-Token` matching new `HEALTH_DETAIL_TOKEN` env (unset = disabled).
6. **Fixed** — `get_gmail_credentials` refuses when Gmail consent is revoked (stale token files no longer bypass revocation); `revoke_gmail_access` reports `gmail_token_delete_failed` and `/disconnectgmail` surfaces it; `/start` no longer re-authorizes from a token file when consent is revoked.
7. **Fixed** — `ProviderRegistry.get_fallback` candidates must pass `is_available_for_user(user_id)` when `user_id` present; same rule applied to the auth-error retry fallback in `core/llm.py`.
8. **Fixed** — Work Email and Smart Inbox LLM calls now pass `user_id=user_id`.
9. **Fixed** — `_process_attachments` checks encoded-payload size before base64 decode, caps report count (5) before any work, keeps 3-extraction cap; oversized parts never reach parsers.
10. **Hardened** — Smart Inbox: `confirm` remains default; auto-created todos capped via `MAX_AUTO_TODOS`; prompt now wraps email content in `<emails>` tags and instructs the model to treat email bodies as data, not instructions.

Verification: `python3 -m pytest tests/ --ignore=tests/test_lotto.py` → 288 passed. Remaining failures are pre-existing and unrelated: `tests/test_lotto.py` (stale import after Sanook migration) and `tests/test_tool_user_lookup.py::test_gmail_summary_uses_user_id_for_preference_lookup` (mock creds lacks `.valid`).

Deployment note: webhook deployments without `TELEGRAM_WEBHOOK_SECRET` will now fail at startup by design — set the secret before upgrading.
