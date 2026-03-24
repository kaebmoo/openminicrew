# Configuration Reference

> 🇬🇧 [English version](../en/CONFIGURATION.md)

ทุก config ตั้งผ่าน environment variables ใน `.env` — copy จาก `.env.example` เพื่อเริ่มต้น

## ตัวแปรที่ต้องตั้ง (Required)

ถ้าไม่ตั้ง app จะไม่ยอมเริ่ม

| ตัวแปร | ตัวอย่าง | คำอธิบาย |
|--------|---------|----------|
| `TELEGRAM_BOT_TOKEN` | `123:ABCxxx` | จาก @BotFather |
| `OWNER_TELEGRAM_CHAT_ID` | `123456789` | Telegram chat ID ของคุณ |
| `BOT_API_EXCHANGE_TOKEN` | `...` | API อัตราแลกเปลี่ยน ธปท. |
| `BOT_API_HOLIDAY_TOKEN` | `...` | API วันหยุด ธปท. |

## Bot Mode

| ตัวแปร | Default | ตัวเลือก | คำอธิบาย |
|--------|---------|---------|----------|
| `BOT_MODE` | `polling` | `polling`, `webhook` | วิธีรับ update จาก Telegram |

### Webhook (เฉพาะ mode webhook)

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `WEBHOOK_HOST` | | domain (เช่น `https://bot.example.com`) |
| `WEBHOOK_PORT` | `8443` | port สำหรับ FastAPI |
| `WEBHOOK_PATH` | `/bot/webhook` | URL path |
| `TELEGRAM_WEBHOOK_SECRET` | | secret token สำหรับตรวจ header |

## LLM Providers

ต้องตั้ง API key อย่างน้อย 1 provider

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `DEFAULT_LLM` | `claude` | provider เริ่มต้นสำหรับ user ใหม่ |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `GEMINI_API_KEY` | | Google Gemini API key |
| `MATCHA_API_KEY` | | Matcha/Typhoon API key (หรือตั้ง per-user ผ่าน `/setkey`) |
| `MATCHA_BASE_URL` | | OpenAI-compatible base URL |

### เลือก Model

แต่ละ provider มี tier "cheap" (เร็ว/ถูก) และ "mid" (ฉลาด/แพง)

| ตัวแปร | Default |
|--------|---------|
| `CLAUDE_MODEL_CHEAP` | `claude-haiku-4-5-20251001` |
| `CLAUDE_MODEL_MID` | `claude-sonnet-4-5-20250929` |
| `GEMINI_MODEL_CHEAP` | `gemini-2.5-flash` |
| `GEMINI_MODEL_MID` | `gemini-2.5-pro` |
| `MATCHA_MODEL_CHEAP` | `typhoon-v2-70b-instruct` |
| `MATCHA_MODEL_MID` | `typhoon-v2-70b-instruct` |

## External APIs

ทั้งหมด optional — tool ที่ต้องใช้จะแสดง error ที่เข้าใจง่ายถ้ายังไม่ตั้ง

| ตัวแปร | ใช้โดย |
|--------|--------|
| `GOOGLE_MAPS_API_KEY` | Traffic/เส้นทาง |
| `FOURSQUARE_API_KEY` | ค้นหาสถานที่ใกล้เคียง |
| `TMD_API_KEY` | ข้อมูลอากาศไทย |
| `TAVILY_API_KEY` | Web search |

## Gmail

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `GMAIL_MAX_RESULTS` | `30` | จำนวนอีเมลสูงสุดต่อ query |

Gmail OAuth ต้องมี `credentials.json` จาก Google Cloud Console — token ของแต่ละ user เก็บใน `credentials/gmail_{user_id}.json`

## Work Email (IMAP)

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `WORK_IMAP_HOST` | | IMAP server (เช่น `mail.company.co.th`) |
| `WORK_IMAP_PORT` | `993` | IMAP port |
| `WORK_IMAP_USER` | | ที่อยู่อีเมล |
| `WORK_IMAP_PASSWORD` | | รหัสผ่าน |
| `WORK_EMAIL_MAX_RESULTS` | `30` | อีเมลสูงสุดต่อ query |
| `WORK_EMAIL_ATTACHMENT_MAX_MB` | `5` | ขนาดไฟล์แนบสูงสุดที่ประมวลผล |

## Memory & Chat

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `MAX_CONTEXT_MESSAGES` | `10` | จำนวนข้อความที่ส่งเป็น context ให้ LLM |
| `CHAT_HISTORY_RETENTION_DAYS` | `30` | จำนวนวันก่อน auto-cleanup |

## Scheduling

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `TIMEZONE` | `Asia/Bangkok` | timezone ของระบบ |
| `MORNING_BRIEFING_TIME` | `07:00` | เวลาสรุปเช้า |
| `MORNING_BRIEFING_TOOL` | `gmail_summary` | tool ที่ใช้สรุปเช้า |

## Timeouts

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `DISPATCH_TIMEOUT` | `120` | วินาทีสูงสุดสำหรับ dispatch รอบเดียว |
| `TOOL_EXEC_TIMEOUT` | `120` | วินาทีสูงสุดสำหรับ execute tool เดียว |
| `POLLING_TIMEOUT` | `30` | long-poll timeout (วินาที) |
| `POLLING_REQUEST_TIMEOUT` | `35` | HTTP request timeout สำหรับ polling |

## Data Retention

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `TOOL_LOG_RETENTION_DAYS` | `90` | ลบ tool logs เก่า |
| `EMAIL_LOG_RETENTION_DAYS` | `90` | ลบ processed emails เก่า |
| `PENDING_MSG_RETENTION_DAYS` | `7` | ลบ pending messages เก่า |
| `JOB_RUN_RETENTION_DAYS` | `30` | ลบ cron job runs เก่า |

## อื่นๆ

| ตัวแปร | Default | คำอธิบาย |
|--------|---------|----------|
| `OWNER_DISPLAY_NAME` | `Owner` | ชื่อที่แสดงของ owner |
| `LOCATION_TTL_MINUTES` | `60` | GPS location cache TTL (0 = ไม่หมดอายุ) |
| `ENCRYPTION_KEY` | | Fernet key สำหรับเข้ารหัส per-user API keys |
| `MISSED_JOB_WINDOW_HOURS` | `12` | ช่วงเวลาตรวจจับ cron job ที่พลาด |
| `HEARTBEAT_INTERVAL_MINUTES` | `30` | ระยะ heartbeat ของ scheduler |
| `DB_PATH` | `data/openminicrew.db` | กำหนดตำแหน่ง database file |
