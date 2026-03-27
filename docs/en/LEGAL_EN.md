# OpenMiniCrew — Terms of Service, Privacy Policy, and Consent

**Effective Date:** March 25, 2026
**Last Updated:** March 25, 2026

---

## Part 1: Terms of Service

### 1.1 Definitions

- **"Service"** means the OpenMiniCrew Telegram Bot, including all features, tools, and related systems.
- **"Operator"** means the individual or team that develops and operates OpenMiniCrew.
- **"User"** means any individual who uses the Service through Telegram.
- **"Personal Data"** means any information relating to an identified or identifiable natural person, as defined by Thailand's Personal Data Protection Act B.E. 2562 (2019) ("PDPA").
- **"AI/LLM"** means large language models used to process text, such as Claude (Anthropic) and Gemini (Google).

### 1.2 Nature of the Service

OpenMiniCrew is a personal AI assistant delivered via Telegram Bot. It uses AI to process user messages and route them to various tools, including:

- Gmail and work email summarization
- Google Calendar management
- Exchange rates (Bank of Thailand)
- PromptPay QR code generation
- Thai Government Lottery results
- Place search, maps, and traffic
- Weather information
- Web search and news summary
- Expense tracking, to-do lists, and reminders
- Unit conversion
- Automated scheduling

### 1.3 Acceptance of Terms

By initiating the Service (sending the /start command), you agree to all terms in this document. If you do not agree, stop using the Service immediately.

### 1.4 Conditions of Use

1. **You must be at least 18 years old** or have consent from a legal guardian.
2. You must use the Service in compliance with Thai law and all applicable laws.
3. You must not use the Service for illegal activities, fraud, rights infringement, or spam.
4. You must not attempt to access other users' data or attack the system.
5. You are responsible for the accuracy of data you provide to the system.

### 1.5 Limitation of Liability

1. **This Service is a personal project**, not a commercial offering. It is provided "AS-IS" without any warranties of any kind, express or implied.
2. **AI outputs may be incorrect.** AI/LLM can generate inaccurate, outdated, or inappropriate information. You must always independently verify results.
3. **This is not professional advice.** Information provided by the Service is general-purpose only and does not constitute financial, legal, or medical advice.
4. The Operator is not liable for any direct or indirect damages arising from use of the Service, including but not limited to financial loss, data loss, or any other damages.
5. The Operator is not liable for service interruptions, delays, or technical errors.
6. **Exchange rates, lottery results, weather data**, and other third-party API data originate from external sources. The Operator makes no guarantees regarding the accuracy or timeliness of such data.

### 1.6 Suspension and Termination

1. The Operator reserves the right to suspend or terminate any user's access at any time, with or without cause.
2. Users may stop using the Service at any time and may use `/delete_my_data confirm` to permanently delete their user-linked operational data. Minimal governance audit records may be retained for accountability and incident investigation.
3. The Operator reserves the right to modify features or discontinue the Service entirely without prior notice.

### 1.7 Changes to Terms

The Operator may update these terms from time to time. Continued use of the Service after changes constitutes acceptance of the updated terms.

---

## Part 2: Privacy Policy

This policy is designed in accordance with Thailand's Personal Data Protection Act B.E. 2562 (2019) ("PDPA").

### 2.1 Data We Collect

#### 2.1.1 Data You Provide Directly

| Data | Purpose | Storage |
|------|---------|---------|
| Telegram Chat ID, display name | User identification within the system | Plaintext (used as primary lookup key) |
| Phone number | PromptPay QR generation, profile display | Encrypted (field-level encryption) |
| National ID number | PromptPay QR generation | Encrypted (field-level encryption) |
| Chat messages | AI processing, conversation context | Auto-deleted per retention policy (default 30 days) |
| Expense data (expense notes) | Expense tracking | Notes: encrypted (field-level encryption); retained until user deletes |
| To-dos, reminders | Personal task management features | Retained until user deletes them |

#### 2.1.2 Data Collected Automatically

| Data | Purpose | Storage |
|------|---------|---------|
| GPS location (if shared by user) | Place search, weather, traffic | Requires explicit consent; auto-deleted per TTL |
| Email metadata | Prevent duplicate email summarization | Only message ID (for dedup) and a has-subject boolean flag are stored; no content, sender address, or sender domain is retained |
| Tool usage logs | System monitoring, debugging | Only type, fingerprint, and size stored (no actual content); auto-deleted after 90 days |

#### 2.1.3 Credentials

| Data | Purpose | Storage |
|------|---------|---------|
| Gmail OAuth Token | Access Gmail/Calendar as authorized by user | Encrypted on disk + file permissions restricted (600) |
| App-level OAuth Client Secret | Authenticate the app with Google | Encrypted on disk (managed encrypted-at-rest storage) |
| User-stored API Keys | Call external services on user's behalf | Encrypted (field-level encryption) |

### 2.2 Legal Basis for Processing

| Data | Legal Basis (PDPA) |
|------|-------------------|
| Telegram Chat ID, display name | Contract (necessary for service delivery) |
| Phone number, National ID | Consent (user provides voluntarily for PromptPay) |
| Chat messages | Consent (controlled via /consent chat on/off) |
| GPS location | Explicit consent (requires /consent location on) |
| Gmail OAuth Token | Explicit consent (via OAuth flow + /authgmail) |
| Tool usage logs | Legitimate interest (system monitoring and debugging) |

### 2.3 Third-Party Data Sharing

User data may be transmitted to the following external services for processing:

| Service | Data Sent | Purpose |
|---------|-----------|---------|
| Anthropic (Claude AI) | Chat messages and conversation context | Natural language processing |
| Google (Gemini AI) | Chat messages and conversation context | Natural language processing (fallback) |
| Telegram Bot API | Response messages, QR images | Deliver results to user |
| Google Gmail API | User's OAuth token | Read emails as authorized by user |
| Google Calendar API | User's OAuth token | Manage calendar as authorized by user |
| Google Maps API | Search queries | Place search |
| Open-Meteo API | GPS coordinates (non-identifying) | Weather data |
| Bank of Thailand API | No personal data | Exchange rates, holidays |
| Tavily Search API | Search queries | Web search |
| Thai Meteorological Department API | GPS coordinates (non-identifying) | Thai weather data |

**Important:** When you send a message, it is transmitted to an AI provider (Anthropic or Google) for processing. You should exercise caution when sharing highly sensitive information through regular conversation.

### 2.4 Data Retention Periods

| Data | Retention | Deletion Method |
|------|-----------|----------------|
| Chat history | 30 days (default) | Auto-deleted, or /consent chat off, or /delete_my_data confirm |
| Tool usage logs | 90 days | Auto-deleted, or /delete_my_data confirm |
| Email metadata | 90 days | Auto-deleted, or /delete_my_data confirm |
| Pending messages | 7 days | Auto-deleted, or /delete_my_data confirm |
| Job run records | 30 days | Auto-deleted, or /delete_my_data confirm |
| GPS location | Per configured TTL (default 60 minutes) | Auto-deleted, or /clearlocation, or /delete_my_data confirm |
| Profile data (name, phone, ID) | Until deleted | /delete_my_data confirm |
| Expenses, to-dos, reminders | Until deleted | /delete_my_data confirm |
| Gmail OAuth Token | Until revoked | /disconnectgmail, or /delete_my_data confirm |
| API Keys | Until deleted | /removekey, or /delete_my_data confirm |

### 2.5 Data Subject Rights (under PDPA)

You may exercise the following rights directly through bot commands:

| Right | Command | Effect |
|-------|---------|--------|
| **Right of access** | `/privacy`, `/start`, `/mykeys` | View stored data, consent status, retention periods, and saved API keys |
| **Right to withdraw consent** | `/consent chat off`, `/consent location off`, `/consent gmail off`, `/disconnectgmail` | Stop collection of that data type and delete associated data |
| **Right to erasure (right to be forgotten)** | `/delete_my_data confirm` | Permanently delete all data across all tables + Gmail token file |
| **Right to rectification** | `/setname`, `/setphone`, `/setid` | Directly update personal information |
| **Right to object** | Stop using service + `/delete_my_data confirm` | Delete all data and cease processing |

### 2.6 Consent Management

#### Consent System

The Service uses an explicit consent system for three data categories:

1. **Chat History (chat_history)**
   - Existing users: defaults to granted (for continuity)
   - New users: defaults to not_set (must grant explicitly)
   - When revoked: all chat history is immediately deleted; no new data is stored
   - The bot continues to function but without prior conversation context

2. **GPS Location (location_access)**
   - Defaults to not_set (must grant before use)
   - When revoked: stored location is immediately deleted
   - Tools requiring location (weather, places) will not function until granted

3. **Gmail/Calendar (gmail_access)**
   - Defaults to not_set
   - Granting requires completing the OAuth flow (/authgmail)
   - When revoked (/disconnectgmail): OAuth token is deleted and connection is terminated immediately

#### How to Manage Consent

- View status: `/consent`
- Toggle: `/consent [chat|location|gmail] [on|off]`
- Full overview: `/privacy`

### 2.7 Security Measures

Details are provided in Part 3 (Security Policy) of this document.

### 2.8 Children's Data

This Service is not designed for children under 18 years of age. If the Operator becomes aware that a child is using the Service, the account may be suspended.

### 2.9 Breach Notification

In the event of a high-impact data breach, the Operator will notify affected users as promptly as practicable via Telegram.

---

## Part 3: Security Policy

### 3.1 Encryption

| Data Type | Protection Method |
|-----------|------------------|
| Phone number, National ID | Fernet encryption (AES-128-CBC) at field level before database storage |
| Expense notes (expenses.note) | Fernet encryption at field level before database storage |
| Gmail OAuth Token | Fernet encryption before writing to disk |
| App-level OAuth Client Secret (credentials.json) | Fernet encryption on disk (managed encrypted-at-rest storage) |
| User API Keys | Fernet encryption at field level before database storage |
| Token files on disk | File permissions set to 600 (owner-only access) |
| Chat messages | Plaintext in SQLite + deletion per retention schedule |
| GPS location | Plaintext in SQLite + deletion per TTL |

### 3.2 Data Minimization

- **Emails:** The system does not store email content, subjects, sender addresses, or sender domains. Only the message ID (for deduplication) and a boolean flag indicating whether a subject existed are retained.
- **Tool usage logs:** No actual input/output content is stored. Only metadata is retained: type classification (text/numeric/label), a truncated SHA-256 fingerprint for deduplication, and byte length.
- **Error messages:** Raw error messages are not stored. Only the error category (timeout/auth/network), a generic error code, and a sanitized message free of sensitive data are retained.
- **Sensitive Telegram messages:** When a user submits a National ID or phone number via /setid or /setphone, the system attempts to automatically delete the original Telegram message containing that data.

### 3.3 Permanent Deletion (Hard Purge)

The `/delete_my_data confirm` command permanently deletes data from user-linked operational tables: users, chat_history, conversations, processed_emails, tool_logs, reminders, todos, expenses, user_locations, oauth_states, user_consents, user_api_keys, pending_messages, schedules, and job_runs. It also deletes the Gmail token file from disk.

Minimal records in `security_audit_logs` are intentionally retained for governance, accountability, and incident investigation.

This deletion is permanent and irreversible.

### 3.4 Known Limitations

1. **Chat messages and GPS location** are currently stored as plaintext in the SQLite database. Database-level encryption is under evaluation for a future phase.
2. **Telegram Chat ID** serves as the system's primary lookup key and cannot currently be encrypted.
3. **Data sent to AI providers** is subject to those providers' own privacy policies (Anthropic, Google).
4. **Backup data** created prior to deletion may persist in backup files until those backups are rotated.
5. The system runs on the Operator's infrastructure. Physical security depends on the deployment environment.

---

## Part 4: Contact

For questions regarding these terms and policies, or to exercise rights under the PDPA, contact the Operator via:

- GitHub: https://github.com/kaebmoo/openminicrew

---

## Part 5: Governing Law

These terms are governed by the laws of Thailand, including the Personal Data Protection Act B.E. 2562 (2019), the Computer Crime Act B.E. 2550 (as amended), and other applicable legislation.
