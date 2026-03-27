# Admin Operations Runbook

> Thai version: [คู่มือผู้ดูแลระบบ](../th/ADMIN_RUNBOOK.md)

This runbook is for operators who run OpenMiniCrew in production. It focuses on practical steps for privacy/security governance, incident handling, and key management.

## 1. Scope and Audience

Use this runbook if you are responsible for any of these tasks:

- managing deployment secrets and `.env`
- rotating encryption keys and OAuth client secrets
- handling user data deletion and support requests
- investigating suspicious access or data exposure
- validating system health after sensitive changes

## 2. Critical Files and Data Paths

- Application DB: `data/openminicrew.db` (or `DB_PATH` override)
- App-level OAuth client secret: `credentials.json` (managed encrypted-at-rest when configured)
- Per-user Gmail tokens: `credentials/gmail_{user_id}.json`
- Runtime secret config: `.env`

Treat all of the above as sensitive data at rest.

## 3. Preflight Checks (Before Any Sensitive Operation)

1. Verify current deployment health:
	- `GET /health` in webhook mode
	- or run a smoke command via Telegram (`/privacy`, `/mykeys`)
2. Confirm `ENCRYPTION_KEY` is present and valid.
3. Confirm recent backup exists and restore path is known.
4. Ensure maintenance window is communicated if user-visible behavior may change.

## 4. Daily/Weekly Security Operations

Daily checks:

1. Check `/health` status and readiness warnings.
2. Review `/mykeys` advisory rotation results for overdue keys.
3. Watch logs for repeated auth failures, decryption warnings, or Gmail OAuth errors.

Weekly checks:

1. Verify cleanup jobs are running (retention jobs and scheduler heartbeat).
2. Review `security_audit_logs` volume and event patterns.
3. Validate file permissions for `credentials.json` and `credentials/` token artifacts.

## 5. Encryption Key Rotation Procedure

Use this when rotating `ENCRYPTION_KEY`.

1. Generate a new Fernet key and set it as `ENCRYPTION_KEY`.
2. Move the previous key into `ENCRYPTION_KEY_PREVIOUS` or append to `ENCRYPTION_KEY_PREVIOUS_LIST`.
3. Run artifact re-encryption:

```bash
python main.py --rotate-encryption
```

4. Verify system behavior:
	- `/health` is not failing
	- `/mykeys` can still read private keys
	- Gmail OAuth flow or Gmail tools still work for at least one test account
5. After stabilization, remove old keys from previous-key env vars.

Rollback note:

- If decryption errors appear, restore old key in previous-key env vars first, then re-run validation.

## 6. Gmail OAuth Client Secret Rotation

1. Download fresh OAuth client JSON from Google Cloud Console.
2. Import through the app command (do not hand-edit managed file):

```bash
python main.py --import-gmail-client-secrets /path/to/downloaded.json
```

3. Validate by running a Gmail auth/connect flow and checking logs.
4. Securely delete temporary plaintext download from admin machine.

## 7. User Data Deletion and Privacy Requests

For full user deletion, use in-chat hard purge command:

- `/delete_my_data confirm`

Operator validation checklist:

1. Confirm user receives success response.
2. Confirm user-linked data is removed from DB tables.
3. Confirm `credentials/gmail_{user_id}.json` is removed if present.
4. Confirm event exists in `security_audit_logs`.

Governance note:

- `security_audit_logs` is intentionally retained during hard purge; this is by design, not a deletion gap

Important:

- Deactivation alone is not a hard purge.
- Backup copies may still retain historical data outside the primary DB.

## 8. Incident Response (Suspected Exposure)

1. Contain: restrict operator access and pause non-essential automations.
2. Assess: inspect `security_audit_logs`, app logs, and infra logs for scope.
3. Revoke: disconnect impacted OAuth grants and remove compromised keys.
4. Rotate: perform encryption key and/or OAuth client secret rotation when required.
5. Eradicate and recover: purge affected user data if needed and restore normal operations.
6. Post-incident review: record root cause, impact, and preventive actions.

## 9. Backup and Export Handling

1. Encrypt backup/export storage at rest.
2. Restrict access by least privilege.
3. Apply retention and deletion schedules to backup/export copies.
4. Include restore tests in routine operational checks.

Hard purge requests are not fully complete from a policy standpoint if off-system backup/export copies are unmanaged.

## 10. Command Reference

Common admin commands:

```bash
python main.py --rotate-encryption
python main.py --import-gmail-client-secrets /path/to/client_secret.json
python main.py --auth-gmail <chat_id>
python main.py --list-gmail
python main.py --revoke-gmail <chat_id>
```

Common in-chat validation commands:

- `/privacy`
- `/mykeys`
- `/health` (webhook endpoint)

## 11. Change Log and Ownership

Recommended metadata to maintain in your operations process:

- runbook owner/team
- last review date
- last successful key rotation date
- last incident drill date
