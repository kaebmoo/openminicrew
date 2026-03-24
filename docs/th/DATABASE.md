# Database Reference

> 🇬🇧 [English version](../en/DATABASE.md)

OpenMiniCrew ใช้ **SQLite** + WAL mode ไฟล์เดียว ไม่ต้อง config อะไร

**ตำแหน่ง:** `data/openminicrew.db`

## Connection Model

- Thread-local connections ผ่าน `threading.local()`
- แต่ละ thread reuse connection ของตัวเอง (ไม่ต้องมี pool manager)
- WAL mode ทำให้อ่านพร้อมกันได้ + เขียนทีละคน
- ทุก table สร้างอัตโนมัติตอนเปิดครั้งแรก (`CREATE TABLE IF NOT EXISTS`)

## ตาราง

### users

ตารางหลัก ผู้ใช้ Telegram แต่ละคน = 1 แถว

| Column | Type | Default | คำอธิบาย |
|--------|------|---------|----------|
| user_id | TEXT PK | | UUID |
| telegram_chat_id | TEXT UNIQUE | | Telegram chat ID |
| display_name | TEXT | | ชื่อที่แสดง |
| phone_number | TEXT | | เบอร์โทร |
| status | TEXT | `'active'` | สถานะบัญชี |
| role | TEXT | `'user'` | `owner` หรือ `user` |
| default_llm | TEXT | `'claude'` | LLM ที่เลือกใช้ |
| smart_inbox_mode | TEXT | `'confirm'` | โหมด smart inbox |
| timezone | TEXT | `'Asia/Bangkok'` | timezone ของ user |
| gmail_authorized | INTEGER | `0` | ผ่าน Gmail OAuth แล้ว? |
| is_active | INTEGER | `1` | soft delete flag |
| created_at | TEXT | | ISO datetime |
| updated_at | TEXT | | ISO datetime |

### chat_history

ความจำแชท สำหรับส่งเป็น context ให้ LLM

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| role | TEXT | `user` หรือ `assistant` |
| content | TEXT | ข้อความ |
| tool_used | TEXT | ชื่อ tool (ถ้ามี) |
| llm_model | TEXT | model ที่ใช้ |
| token_used | INTEGER | จำนวน token |
| conversation_id | TEXT | จัดกลุ่มข้อความเป็นบทสนทนา |
| created_at | TEXT | ISO datetime |

**Index:** `idx_chat_user_time` on `(user_id, created_at DESC)`

### conversations

session บทสนทนา สำหรับ `/new` และ `/history`

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | TEXT PK | UUID |
| user_id | TEXT FK | → users |
| title | TEXT | หัวข้อ (สร้างอัตโนมัติ) |
| is_active | INTEGER | เป็นบทสนทนาปัจจุบัน? |
| message_count | INTEGER | นับจำนวนข้อความ |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

**Index:** `idx_conv_user_time` on `(user_id, updated_at DESC)`

### user_api_keys

API key ส่วนตัว เข้ารหัส (ตั้งผ่าน `/setkey`)

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| service | TEXT | ชื่อ service (เช่น `matcha`, `tavily`) |
| api_key | TEXT | key ที่เข้ารหัสด้วย Fernet |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

**Unique constraint:** `(user_id, service)`

### tool_logs

บันทึกการใช้งาน tool ทุกครั้ง

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| tool_name | TEXT | tool ที่เรียก |
| input_summary | TEXT | arguments |
| output_summary | TEXT | สรุปผลลัพธ์ |
| llm_model | TEXT | model ที่ใช้ |
| token_used | INTEGER | จำนวน token |
| status | TEXT | `success` หรือ `error` |
| error_message | TEXT | รายละเอียด error ถ้า fail |
| created_at | TEXT | ISO datetime |

### processed_emails

ป้องกันสรุปอีเมลซ้ำ

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| message_id | TEXT | Gmail/IMAP message ID |
| subject | TEXT | หัวข้ออีเมล |
| sender | TEXT | ผู้ส่ง |
| processed_at | TEXT | ISO datetime |

**Unique constraint:** `(user_id, message_id)`

### schedules

Cron job ของแต่ละ user

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| tool_name | TEXT | tool ที่จะเรียก |
| cron_expr | TEXT | cron expression |
| args | TEXT | arguments เป็น JSON |
| is_active | INTEGER | เปิดใช้? |
| last_run_at | TEXT | เวลาที่ทำงานล่าสุด |

### reminders

การแจ้งเตือนตามเวลา

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| text | TEXT | ข้อความแจ้งเตือน |
| remind_at | TEXT | เวลาที่จะแจ้ง |
| status | TEXT | `pending`, `done`, `cancelled` |
| schedule_id | INTEGER | อ้างอิง APScheduler job |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

### todos

รายการสิ่งที่ต้องทำ

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| title | TEXT | หัวข้อ |
| notes | TEXT | รายละเอียดเพิ่มเติม |
| priority | TEXT | `low`, `medium`, `high` |
| status | TEXT | `open`, `done` |
| due_at | TEXT | กำหนดส่ง |
| source_type | TEXT | แหล่งที่มา (เช่น `email`) |
| source_ref | TEXT | reference ID |
| created_at | TEXT | ISO datetime |
| updated_at | TEXT | ISO datetime |

### expenses

บันทึกรายจ่าย

| Column | Type | คำอธิบาย |
|--------|------|----------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT FK | → users |
| amount | REAL | จำนวนเงิน |
| currency | TEXT | default `THB` |
| category | TEXT | หมวดหมู่ |
| note | TEXT | รายละเอียด |
| expense_date | TEXT | วันที่ใช้จ่าย |
| created_at | TEXT | ISO datetime |

### ตารางสนับสนุน

| ตาราง | หน้าที่ |
|-------|---------|
| **user_locations** | ตำแหน่ง GPS ล่าสุด per user (มี TTL) |
| **oauth_states** | state token ชั่วคราวสำหรับ Gmail OAuth |
| **pending_messages** | ข้อความที่ค้างเมื่อ user ยังไม่ลงทะเบียน |
| **job_runs** | บันทึกการทำงานของ cron job (dedup + audit) |

## Retention & Cleanup

Scheduler รัน cleanup job ทุกวัน ลบข้อมูลเก่า:

| ตาราง | เก็บนาน | ค่า config |
|-------|---------|-----------|
| chat_history | 30 วัน | `CHAT_HISTORY_RETENTION_DAYS` |
| tool_logs | 90 วัน | `TOOL_LOG_RETENTION_DAYS` |
| processed_emails | 90 วัน | `EMAIL_LOG_RETENTION_DAYS` |
| pending_messages | 7 วัน | `PENDING_MSG_RETENTION_DAYS` |
| job_runs | 30 วัน | `JOB_RUN_RETENTION_DAYS` |
