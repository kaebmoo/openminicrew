# Configuration Reference

> 🇬🇧 [English version](../en/CONFIGURATION.md)

ทุก config ตั้งผ่าน environment variables ใน `.env` — copy จาก `.env.example` เพื่อเริ่มต้น

## ตัวแปรที่ต้องตั้ง (Required)

ถ้าไม่ตั้ง app จะไม่ยอมเริ่ม

| ตัวแปร | ตัวอย่าง | คำอธิบาย |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | `123:ABCxxx` | จาก @BotFather |
| `OWNER_TELEGRAM_CHAT_ID` | `123456789` | Telegram chat ID ของคุณ |
| `BOT_API_EXCHANGE_TOKEN` | `...` | API อัตราแลกเปลี่ยน ธปท. |
| `BOT_API_HOLIDAY_TOKEN` | `...` | API วันหยุด ธปท. |

## Bot Mode

| ตัวแปร | Default | ตัวเลือก | คำอธิบาย |
| --- | --- | --- | --- |
| `BOT_MODE` | `polling` | `polling`, `webhook` | วิธีรับ update จาก Telegram |
| `STARTUP_READINESS_POLICY` | `auto` | `auto`, `strict`, `warn` | นโยบาย startup readiness โดย `auto` จะตีความเป็น `strict` ใน webhook mode และ `warn` ใน polling mode |

### Webhook (เฉพาะ mode webhook)

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `WEBHOOK_HOST` | `(none)` | domain (เช่น `https://bot.example.com`) |
| `WEBHOOK_PORT` | `8443` | port สำหรับ FastAPI |
| `WEBHOOK_PATH` | `/bot/webhook` | URL path |
| `TELEGRAM_WEBHOOK_SECRET` | `(none)` | secret token สำหรับตรวจ header |

### Health endpoint และพฤติกรรม readiness

เมื่อ `BOT_MODE=webhook` ระบบจะเปิด `GET /health` สำหรับ operator, reverse proxy และ uptime monitor

`/health` จะรายงาน:

- สถานะรวมของระบบ
- startup readiness checks รวมถึง `ENCRYPTION_KEY` readiness
- สรุป API key hygiene
- สุขภาพของ database และ LLM
- ข้อมูล scheduler run ล่าสุด

ความหมายของ status:

- `ok`: readiness ผ่าน และ DB health ปกติ
- `degraded`: มี readiness warning อย่างน้อยหนึ่งรายการ หรือมี advisory warning ด้าน API key hygiene
- `fail`: readiness ที่จำเป็นล้มเหลว หรือ DB health ไม่ปกติ

พฤติกรรมตอน boot ใช้ readiness model เดียวกับ `/health`:

- `BOT_MODE=webhook` และ `STARTUP_READINESS_POLICY=auto` จะ fail-fast ถ้า readiness สำคัญไม่พร้อม
- `BOT_MODE=polling` และ `STARTUP_READINESS_POLICY=auto` จะเตือนเป็นหลัก เพื่อไม่ให้ local/dev ใช้งานยากเกินไป
- `STARTUP_READINESS_POLICY=strict` จะบังคับ fail-fast ทุก mode
- `STARTUP_READINESS_POLICY=warn` จะคงเป็น warning-only แม้ readiness ยังไม่ครบ

## LLM Providers

ต้องตั้ง API key อย่างน้อย 1 provider

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `DEFAULT_LLM` | `claude` | provider เริ่มต้นสำหรับ user ใหม่ |
| `ANTHROPIC_API_KEY` | `(none)` | Claude API key |
| `GEMINI_API_KEY` | `(none)` | Google Gemini API key |
| `MATCHA_API_KEY` | `(none)` | Matcha/Typhoon API key (หรือตั้ง per-user ผ่าน `/setkey`) |
| `MATCHA_BASE_URL` | `(none)` | OpenAI-compatible base URL |

### เลือก Model

แต่ละ provider มี tier "cheap" (เร็ว/ถูก) และ "mid" (ฉลาด/แพง)

| ตัวแปร | Default |
| --- | --- |
| `CLAUDE_MODEL_CHEAP` | `claude-haiku-4-5-20251001` |
| `CLAUDE_MODEL_MID` | `claude-sonnet-4-5-20250929` |
| `GEMINI_MODEL_CHEAP` | `gemini-2.5-flash` |
| `GEMINI_MODEL_MID` | `gemini-2.5-pro` |
| `MATCHA_MODEL_CHEAP` | `typhoon-v2-70b-instruct` |
| `MATCHA_MODEL_MID` | `typhoon-v2-70b-instruct` |

## External APIs

ทั้งหมด optional — tool ที่ต้องใช้จะแสดง error ที่เข้าใจง่ายถ้ายังไม่ตั้ง

| ตัวแปร | ใช้โดย |
| --- | --- |
| `GOOGLE_MAPS_API_KEY` | Traffic/เส้นทาง |
| `FOURSQUARE_API_KEY` | ค้นหาสถานที่ใกล้เคียง |
| `TMD_API_KEY` | ข้อมูลอากาศไทย |
| `TAVILY_API_KEY` | Web search |

## Gmail

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `GMAIL_MAX_RESULTS` | `30` | จำนวนอีเมลสูงสุดต่อ query |

Gmail OAuth ใช้ไฟล์ managed `credentials.json` ที่ project root สำหรับ app-level Google OAuth client configuration

flow ปัจจุบัน:

- ดาวน์โหลด OAuth client JSON แบบ plaintext จาก Google Cloud Console
- import เข้าระบบด้วย `python main.py --import-gmail-client-secrets /path/to/downloaded.json`
- เมื่อมี `ENCRYPTION_KEY` ระบบจะเก็บ managed `credentials.json` แบบ encrypted-at-rest
- ถ้ายังมี `credentials.json` แบบ plaintext เดิมอยู่ ระบบจะ auto-migrate เป็น encrypted storage เมื่อมีการใช้ Gmail OAuth ครั้งแรกและมี `ENCRYPTION_KEY`
- token ของแต่ละ user จะเก็บแยกใน `credentials/gmail_{user_id}.json` และยังเป็น encrypted-at-rest เช่นเดิม

ข้อควรปฏิบัติ:

- ไม่ควรแก้ไข managed `credentials.json` ที่ถูกเข้ารหัสแล้วด้วยมือ ถ้าต้องเปลี่ยนให้ import ไฟล์ plaintext ใหม่เข้าไปแทน

### Operator Runbook: Rotate Gmail Client Secrets

ลำดับที่แนะนำสำหรับ production-safe rotation:

1. ดาวน์โหลด OAuth client JSON ชุดใหม่จาก Google Cloud Console ไปยัง path ชั่วคราวแบบ plaintext บนเครื่อง admin
2. ตรวจว่า deployment เป้าหมายมี `ENCRYPTION_KEY` พร้อมก่อน import
3. รัน `python main.py --import-gmail-client-secrets /path/to/downloaded.json` บน deployment เป้าหมาย
4. ตรวจว่า import สำเร็จ แล้วทดสอบ Gmail OAuth สักหนึ่ง flow เช่น `/authgmail` หรือ owner auth flow เพื่อยืนยันว่า runtime ยังโหลดได้ปกติ
5. ลบไฟล์ plaintext ชั่วคราวจากเครื่อง admin หลังยืนยันผลแล้ว

หมายเหตุสำหรับ production:

- ไม่ควรแก้ managed `credentials.json` ที่เข้ารหัสแล้วด้วยมือ
- ถ้ายังมีไฟล์ managed แบบ plaintext รุ่นเก่าอยู่ การใช้งาน Gmail OAuth ครั้งแรกจะ auto-migrate ให้เมื่อมี `ENCRYPTION_KEY`
- ไฟล์ token ของแต่ละ user ใน `credentials/gmail_{user_id}.json` ไม่จำเป็นต้อง rotate ตามการเปลี่ยน client secret เว้นแต่ต้องการ revoke สิทธิ์ของ user แยกต่างหาก

## Work Email (IMAP)

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `WORK_IMAP_HOST` | `(none)` | IMAP server (เช่น `mail.company.co.th`) |
| `WORK_IMAP_PORT` | `993` | IMAP port |
| `WORK_IMAP_USER` | `(none)` | ที่อยู่อีเมล |
| `WORK_IMAP_PASSWORD` | `(none)` | รหัสผ่าน |
| `WORK_EMAIL_MAX_RESULTS` | `30` | อีเมลสูงสุดต่อ query |
| `WORK_EMAIL_ATTACHMENT_MAX_MB` | `5` | ขนาดไฟล์แนบสูงสุดที่ประมวลผล |

## Memory & Chat

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `MAX_CONTEXT_MESSAGES` | `10` | จำนวนข้อความที่ส่งเป็น context ให้ LLM |
| `CHAT_HISTORY_RETENTION_DAYS` | `30` | จำนวนวันก่อน auto-cleanup |

## Scheduling

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `TIMEZONE` | `Asia/Bangkok` | timezone ของระบบ |
| `MORNING_BRIEFING_TIME` | `07:00` | เวลาสรุปเช้า |
| `MORNING_BRIEFING_TOOL` | `gmail_summary` | tool ที่ใช้สรุปเช้า |

## Timeouts

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `DISPATCH_TIMEOUT` | `120` | วินาทีสูงสุดสำหรับ dispatch รอบเดียว |
| `TOOL_EXEC_TIMEOUT` | `120` | วินาทีสูงสุดสำหรับ execute tool เดียว |
| `POLLING_TIMEOUT` | `30` | long-poll timeout (วินาที) |
| `POLLING_REQUEST_TIMEOUT` | `35` | HTTP request timeout สำหรับ polling |

## Data Retention

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `TOOL_LOG_RETENTION_DAYS` | `90` | ลบ tool logs เก่า |
| `EMAIL_LOG_RETENTION_DAYS` | `90` | ลบ processed emails เก่า |
| `PENDING_MSG_RETENTION_DAYS` | `7` | ลบ pending messages เก่า |
| `JOB_RUN_RETENTION_DAYS` | `30` | ลบ cron job runs เก่า |

## อื่นๆ

| ตัวแปร | Default | คำอธิบาย |
| --- | --- | --- |
| `OWNER_DISPLAY_NAME` | `Owner` | ชื่อที่แสดงของ owner |
| `LOCATION_TTL_MINUTES` | `60` | GPS location cache TTL (0 = ไม่หมดอายุ) |
| `ENCRYPTION_KEY` | `(none)` | Fernet key สำหรับเข้ารหัส per-user API keys |
| `API_KEY_ROTATION_DAYS_DEFAULT` | `180` | รอบ rotate เชิงแนะนำสำหรับ per-user API keys ทั่วไป |
| `WORK_IMAP_PASSWORD_ROTATION_DAYS` | `90` | รอบ rotate เชิงแนะนำสำหรับ IMAP password ที่บันทึกไว้ |
| `WORK_IMAP_USER_ROTATION_DAYS` | `180` | รอบ rotate เชิงแนะนำสำหรับ IMAP username ที่บันทึกไว้ |
| `WORK_IMAP_HOST_ROTATION_DAYS` | `365` | รอบ rotate เชิงแนะนำสำหรับ IMAP host ที่บันทึกไว้ |
| `MISSED_JOB_WINDOW_HOURS` | `12` | ช่วงเวลาตรวจจับ cron job ที่พลาด |
| `HEARTBEAT_INTERVAL_MINUTES` | `30` | ระยะ heartbeat ของ scheduler |
| `DB_PATH` | `data/openminicrew.db` | กำหนดตำแหน่ง database file |

การรายงานเรื่อง rotation ของ API key ใน rollout ปัจจุบันเป็น advisory only เท่านั้น: ระบบจะแจ้งใน `/mykeys`, `/privacy`, และ `/health` แต่ยังไม่ block key เดิมอัตโนมัติ
