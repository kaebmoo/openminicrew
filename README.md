# OpenMiniCrew — Personal AI Assistant Framework

> 🇬🇧 [English version](docs/en/README.md)

ผู้ช่วยส่วนตัว AI สั่งงานผ่าน Telegram รองรับ Claude + Gemini
เพิ่ม tool ได้ง่าย รองรับหลาย Telegram account ด้วย API keys ชุดเดียวกัน

## คุณสมบัติ

- สั่งงานผ่าน Telegram ได้ทั้ง /command และพิมพ์อิสระ
- เลือก LLM ได้ (Claude / Gemini / เพิ่ม provider ได้ง่าย) เปลี่ยนได้ระหว่างใช้งาน
- เพิ่ม tool ใหม่ = สร้างไฟล์เดียว ไม่ต้องแก้ core
- เพิ่ม LLM provider ใหม่ = สร้างไฟล์ใน `core/providers/` (Provider Registry)
- Telegram Bot รองรับทั้ง long polling และ webhook
- จำบริบทสนทนาได้ (chat memory)
- ตั้ง cron job สรุปเมลทุกเช้าอัตโนมัติ
- สรุปอีเมลอัจฉริยะ — จัดกลุ่ม จัดลำดับความสำคัญ ค้นหาเรื่องที่สนใจได้
- Multi-user — เพิ่ม/ลบ user ผ่าน Telegram ได้ทันที
- Production ready — retry, error handling, rate limit, health check

## ติดตั้ง

```bash
# 1. Clone / copy โปรเจกต์
cd openminicrew

# 2. ติดตั้ง dependencies
pip install -r requirements.txt

# 3. Copy .env
cp .env.example .env
# แก้ค่าใน .env ตามขั้นตอนด้านล่าง
```

## ตั้งค่า

### 1. สร้าง Telegram Bot

1. คุยกับ [@BotFather](https://t.me/BotFather) บน Telegram
2. ส่ง `/newbot` แล้วตั้งชื่อ
3. ได้ Bot Token → ใส่ใน `TELEGRAM_BOT_TOKEN`
4. คุยกับ [@userinfobot](https://t.me/userinfobot) เพื่อดู Chat ID ของตัวเอง
5. ใส่ Chat ID ใน `OWNER_TELEGRAM_CHAT_ID`

### 2. ตั้งค่า LLM

**Claude:**
1. สมัคร API key ที่ [console.anthropic.com](https://console.anthropic.com)
2. ใส่ใน `ANTHROPIC_API_KEY`

**Gemini:**
1. สมัคร API key ที่ [aistudio.google.com](https://aistudio.google.com)
2. ใส่ใน `GEMINI_API_KEY`

> **หมายเหตุ:** ตั้ง `DEFAULT_LLM` ใน `.env` เป็น `claude` หรือ `gemini` ตาม API key ที่มี

### 3. ตั้งค่า Gmail (สำหรับ email summary tool)

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com)
2. สร้าง Project ใหม่ (หรือใช้ project ที่มีอยู่)
3. เปิดใช้ Gmail API
4. สร้าง OAuth 2.0 Client ID (เลือกประเภท **Desktop App**)
5. ดาวน์โหลด `credentials.json` วางที่ root ของโปรเจกต์

> **สำคัญ:** ตรวจสอบว่า download credentials.json มาจาก project ที่ถูกต้อง — ชื่อ project ที่ตั้งไว้ใน Google Cloud Console จะแสดงบนหน้า consent screen ตอน authorize

### 4. รัน

```bash
# รันปกติ — ระบบจะ auto-detect Gmail auth
# ถ้ายังไม่เคย authorize จะเปิด browser ให้อัตโนมัติ
python main.py

# หรือ authorize Gmail แยก แล้วค่อยรัน
python main.py --auth-gmail
python main.py
```

```bash
# Mode A: Long Polling (เหมาะทดสอบ / เครื่องที่บ้าน)
BOT_MODE=polling python main.py

# Mode B: Webhook (เหมาะ VPS / production)
BOT_MODE=webhook python main.py
```

### Startup Flow

```
python main.py
  │
  ├── [1/6] Init database (SQLite + WAL)
  ├── [2/6] Init owner user
  ├── [3/6] Gmail auth check
  │         ├── มี token → OK
  │         └── ไม่มี token → เปิด browser ให้ authorize อัตโนมัติ
  ├── [4/6] Discover tools
  ├── [5/6] Start scheduler
  └── [6/6] Start bot (polling / webhook)
```

## การใช้งาน

### คำสั่งพื้นฐาน

| คำสั่ง | คำอธิบาย |
|---|---|
| `/email` | สรุปอีเมลที่ยังไม่ได้อ่าน (วันนี้) |
| `/traffic สยาม ไป สีลม` | เช็คเส้นทาง + สภาพจราจร |
| `/places ร้านกาแฟแถวนี้` | ค้นหาสถานที่ใกล้เคียง |
| `/news` | สรุปข่าวเทคโนโลยีล่าสุด |
| `/news tech` | สรุปข่าวตามหมวด |
| `/model` | แสดง LLM ที่ใช้ได้ |
| `/model claude` | เปลี่ยนไปใช้ Claude |
| `/model gemini` | เปลี่ยนไปใช้ Gemini |
| `/help` | แสดงคำสั่งทั้งหมด |
| พิมพ์อิสระ | AI จะเลือก tool หรือตอบเอง |

### Email Summary — ตัวเลือกขั้นสูง

| คำสั่ง | คำอธิบาย |
|---|---|
| `/email` | สรุปอีเมลวันนี้ (default) |
| `/email today` | เหมือน `/email` |
| `/email 3d` | สรุปอีเมลย้อนหลัง 3 วัน |
| `/email 7d` | สรุปอีเมลย้อนหลัง 7 วัน |
| `/email 30d` | สรุปอีเมลย้อนหลัง 30 วัน |
| `/email force` | สรุปใหม่ทั้งหมด (แม้เคยสรุปแล้ว) |
| `/email บัตรเครดิต` | ค้นหาเฉพาะเรื่องบัตรเครดิต |
| `/email from:ktc.co.th` | ค้นหาจากผู้ส่ง KTC |
| `/email from:grab.com 7d` | อีเมลจาก Grab ย้อนหลัง 7 วัน |
| `/email force บัตรเครดิต 7d` | รวมทุก option ได้ |

**รูปแบบผลสรุป:**
- 📋 ภาพรวม — สรุปสั้นๆ ว่ามีอีเมลอะไรบ้าง
- 🔴 ต้องดำเนินการ — อีเมลที่ต้องทำอะไร (ตรวจสอบธุรกรรม, ตอบกลับ ฯลฯ)
- จัดกลุ่มตามประเภท — 💰 การเงิน, 💼 งาน, 📊 ลงทุน, 🛒 โปรโมชั่น ฯลฯ
- 🎯 สรุปท้าย — สิ่งที่ควรให้ความสำคัญก่อน

### Traffic — โหมดการเดินทาง

| โหมด | ตัวอย่าง |
|---|---|
| 🚗 รถยนต์ (default) | `/traffic สยาม ไป สีลม` |
| 🚶 เดินเท้า | "จากสยาม เดินเท้า ไป MBK" |
| 🚌 ขนส่งสาธารณะ | "นั่งรถไฟฟ้าจากอโศกไปสยามใช้เวลาเท่าไหร่" |
| 🏍 มอเตอร์ไซค์ | "มอเตอร์ไซค์จากบ้านไปออฟฟิศ" |

พิมพ์อิสระ LLM จะเลือกโหมดให้อัตโนมัติตามบริบท

## Multi-user Management

ระบบรองรับหลาย Telegram account โดยใช้ API keys ชุดเดียวกัน owner เป็นคนอนุมัติ user ใหม่ผ่าน Telegram:

| คำสั่ง | คำอธิบาย |
|---|---|
| `/adduser <chat_id> [ชื่อ]` | เพิ่ม user ใหม่ (owner only) |
| `/removeuser <chat_id>` | ปิดการใช้งาน user (owner only) |
| `/listusers` | ดูรายชื่อ users ทั้งหมด (owner only) |

**ขั้นตอน:**
1. user ใหม่ใช้ [@userinfobot](https://t.me/userinfobot) เพื่อดู chat_id ของตัวเอง
2. บอก chat_id ให้ owner
3. owner ส่ง `/adduser <chat_id> ชื่อ` → user สามารถใช้งาน bot ได้ทันที

## Gmail Per-User

แต่ละ user สามารถ authorize Gmail ของตัวเองได้ (ไม่ต้องใช้ Gmail ของ owner)

**Webhook mode** (แนะนำสำหรับ production):
```
ส่ง /authgmail ใน Telegram → รับ link → เปิด browser → authorize
```

**Polling mode** (เครื่อง local):
```bash
# authorize Gmail สำหรับ user ที่ระบุ
python main.py --auth-gmail <chat_id>

# ดูรายชื่อ users ที่มี Gmail token แล้ว
python main.py --list-gmail

# ลบ Gmail token ของ user
python main.py --revoke-gmail <chat_id>
```

> **หมายเหตุ:** ถ้า user ไม่มี Gmail token ของตัวเอง ระบบจะ fallback ไปใช้ Gmail ของ owner อัตโนมัติ

## เพิ่ม Tool ใหม่

สร้างไฟล์ใน `tools/` — registry จะ auto-discover:

```python
# tools/my_tool.py

from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "อธิบายว่า tool นี้ทำอะไร"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        # ทำงานหลัก
        return "ผลลัพธ์"

    def get_tool_spec(self) -> dict:
        return {
            "name": "my_tool",
            "description": "อธิบายว่า tool นี้ทำอะไร",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        }
```

แค่นี้ใช้ได้ทั้ง `/mytool` command และพิมพ์อิสระ

## โครงสร้างโปรเจกต์

```
openminicrew/
├── core/              Shared modules
│   ├── config.py      โหลด .env + validate
│   ├── llm.py         LLM Router (thin wrapper)
│   ├── providers/     LLM Provider Registry
│   │   ├── base.py    BaseLLMProvider abstract class
│   │   ├── claude_provider.py
│   │   ├── gemini_provider.py
│   │   └── registry.py   Auto-discover providers
│   ├── db.py          SQLite + WAL mode
│   ├── memory.py      Chat context
│   ├── security.py    Token management + Gmail credentials
│   ├── gmail_oauth.py Gmail OAuth flow (per-user, webhook mode)
│   ├── user_manager.py  User auth + multi-user management
│   └── logger.py      Logging
├── tools/             Tool system
│   ├── base.py        BaseTool abstract class
│   ├── registry.py    Auto-discover tools
│   ├── email_summary.py  Email summary (time range + search + force)
│   ├── traffic.py     Traffic + route (Google Maps, multi-mode)
│   ├── places.py      Nearby place search (Foursquare)
│   └── news_summary.py   News summary (RSS + LLM)
├── interfaces/        Telegram interface
│   ├── telegram_polling.py   Long polling
│   ├── telegram_webhook.py   Webhook + FastAPI + Gmail OAuth callback
│   └── telegram_common.py    Shared logic
├── dispatcher.py      Command routing + LLM dispatch
├── scheduler.py       Cron jobs (APScheduler)
├── main.py            Entry point (Gmail CLI management)
├── credentials.json   OAuth client secret (จาก Google Cloud)
├── credentials/       Gmail tokens per user (auto-generated)
└── data/              SQLite database
```

## Production Deployment (Webhook Mode)

```bash
# ต้องมี domain + HTTPS
# ตั้งค่าใน .env:
BOT_MODE=webhook
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PORT=8443
TELEGRAM_WEBHOOK_SECRET=random-secret-string

# รัน
python main.py

# Health check
curl https://your-domain.com/health
```

**Webhook mode เพิ่มเติม:**
- Gmail OAuth callback: `GET /gmail-callback` — รองรับ per-user Gmail authorization ผ่าน `/authgmail`
- Health check: `GET /health` — แสดงสถานะ bot, DB, LLM, scheduler
