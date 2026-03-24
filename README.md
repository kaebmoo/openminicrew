# OpenMiniCrew — Personal AI Assistant Framework

> 🇬🇧 [English version](docs/en/README.md)

ผู้ช่วยส่วนตัว AI ผ่าน Telegram สำหรับงานประจำวันและงาน automation ขนาดเล็ก
รองรับ Claude, Gemini และ Matcha พร้อมระบบ tools แบบ plug-and-play

## คุณสมบัติ

- ใช้งานผ่าน Telegram ได้ทั้ง /command และข้อความอิสระ
- รองรับ LLM หลายตัว: Claude, Gemini, Matcha และสลับ model ต่อ user ได้
- รองรับ per-user API key ผ่าน `/setkey` และใช้ shared key จาก `.env` ได้ใน service ที่อนุญาต
- รองรับ self-registration ผ่าน `/start` และ onboarding ในแชต
- รองรับ Gmail และ Google Calendar แบบ per-user authorization
- รองรับ media response เช่น QR และ PromptPay QR
- รองรับการส่งรูปบิลหรือสลิปเพื่อบันทึกรายจ่ายอัตโนมัติ
- เพิ่ม tool ใหม่ได้ด้วยการสร้างไฟล์เดียวใน `tools/`
- รองรับทั้ง long polling และ webhook
- มี memory, scheduler, retry, rate limiting, health check และ usage log พร้อมใช้งาน

## เครื่องมือที่มีอยู่ตอนนี้

ระบบมีเครื่องมือใช้งานจริงแล้วในหลายหมวด:

- อีเมล: Gmail summary, Work Email (IMAP), Smart Inbox
- สื่อ/QR: QR Code Generator, PromptPay QR
- เครื่องมือทั่วไป: Unit Converter, Web Search
- งานและนัดหมาย: Todo, Reminder, Google Calendar, Schedule
- การเงิน: Expense Tracker, Exchange Rate
- ข้อมูลและการเดินทาง: Places, Traffic, News, Lotto

> ดูคำสั่งทั้งหมดในแชตได้ด้วย `/help`

## ติดตั้ง

```bash
cd openminicrew
pip install -r requirements.txt
cp .env.example .env
```

## ตั้งค่า

### 1. สร้าง Telegram Bot

1. คุยกับ [@BotFather](https://t.me/BotFather) บน Telegram
2. ส่ง `/newbot` แล้วตั้งชื่อ
3. ได้ Bot Token → ใส่ใน `TELEGRAM_BOT_TOKEN`
4. คุยกับ [@userinfobot](https://t.me/userinfobot) เพื่อดู Chat ID ของ owner
5. ใส่ Chat ID ใน `OWNER_TELEGRAM_CHAT_ID`

### 2. ตั้งค่า LLM

รองรับ 3 provider หลัก:

- Claude → `ANTHROPIC_API_KEY`
- Gemini → `GEMINI_API_KEY`
- Matcha → `MATCHA_API_KEY`

ตัวอย่างใน `.env`:

```bash
DEFAULT_LLM=claude

ANTHROPIC_API_KEY=
GEMINI_API_KEY=

MATCHA_API_KEY=
MATCHA_BASE_URL=
MATCHA_MODEL_CHEAP=
MATCHA_MODEL_MID=
```

หมายเหตุ:

- ถ้าตั้ง shared key ใน `.env` ทุก user ที่ได้รับอนุญาตจะใช้ได้
- บาง provider รองรับ per-user key ผ่าน `/setkey` เช่น `anthropic`, `gemini`, `matcha`, `tavily`, `tmd`
- ใช้ `/model` เพื่อดู provider ที่ user คนนั้นใช้ได้จริง

### 3. ตั้งค่า Gmail และ Google Calendar

Gmail และ Calendar ใช้ Google OAuth ชุดเดียวกันแบบ per-user

1. ไปที่ [Google Cloud Console](https://console.cloud.google.com)
2. สร้าง Project ใหม่หรือใช้ project เดิม
3. เปิด Gmail API และ Google Calendar API
4. สร้าง OAuth 2.0 Client ID แบบ Desktop App
5. ดาวน์โหลด `credentials.json` มาไว้ที่ root ของโปรเจกต์

ถ้าใช้ webhook mode:

- ตั้ง `WEBHOOK_HOST` ให้เป็น public HTTPS URL
- user แต่ละคนส่ง `/authgmail` เพื่อ authorize Gmail/Calendar ของตัวเอง

ถ้าใช้ polling mode บนเครื่อง local:

```bash
python main.py --auth-gmail <chat_id>
python main.py --list-gmail
python main.py --revoke-gmail <chat_id>
```

หมายเหตุ:

- ตอนนี้ไม่มีการ fallback ไปใช้ Gmail token ของ owner ข้าม user แล้ว
- ถ้า user ยังไม่ authorize, tool ที่ใช้ Gmail/Calendar จะขอให้เชื่อมต่อใหม่ด้วย `/authgmail`

### 4. ตั้งค่า Work Email / IMAP

Work Email ใช้ credential แบบ per-user ผ่าน `/setkey`

service ที่เกี่ยวข้อง:

- `work_imap_host`
- `work_imap_user`
- `work_imap_password`

ตัวอย่างใน Telegram:

```text
/setkey work_imap_host mail.company.co.th
/setkey work_imap_user yourname@company.co.th
/setkey work_imap_password yourpassword
```

ค่าที่ตั้งผ่าน `.env` ยังมีเฉพาะพวก setting กลาง เช่น:

```bash
WORK_IMAP_PORT=993
WORK_EMAIL_MAX_RESULTS=30
WORK_EMAIL_ATTACHMENT_MAX_MB=5
```

### 5. ตั้งค่า API อื่น ๆ

service ที่รองรับผ่าน `.env` หรือ `/setkey` ขึ้นกับประเภท service:

- `anthropic`
- `gemini`
- `matcha`
- `google_maps`
- `tavily`
- `tmd`

service ที่เป็น private-only ต่อ user:

- `gmail`
- `calendar`
- `work_imap_host`
- `work_imap_user`
- `work_imap_password`

ตัวอย่าง:

```text
/setkey tmd <key>
/setkey tavily <key>
/setkey matcha <key>
```

### 6. รันระบบ

```bash
python main.py

BOT_MODE=polling python main.py
BOT_MODE=webhook python main.py
```

## เริ่มใช้งานครั้งแรก

### ผู้ใช้ใหม่

1. เปิดแชตกับบอท
2. ส่ง `/start`
3. ตั้งค่าเพิ่มเติมถ้าต้องการ:
   - `/setname ชื่อที่ต้องการ`
   - `/setphone 08XXXXXXXX`
   - `/setid <เลขบัตรประชาชน 13 หลัก>`
   - `/authgmail`
   - `/setkey tmd <key>`

### คำสั่งระบบที่ใช้บ่อย

| คำสั่ง | คำอธิบาย |
| --- | --- |
| `/start` | ลงทะเบียนและแสดง onboarding |
| `/help` | แสดงคำสั่งทั้งหมด |
| `/model` | ดูหรือเปลี่ยน LLM ที่ใช้ได้ของ user |
| `/setname` | ตั้งชื่อที่แสดง |
| `/setphone` | บันทึกเบอร์โทร |
| `/setid` | บันทึกเลขบัตรประชาชน 13 หลัก |
| `/authgmail` | เชื่อมต่อ Gmail และ Calendar |
| `/setkey <service> <value>` | บันทึก API key ของตัวเอง |
| `/mykeys` | ดูรายการ key ที่บันทึกไว้ |
| `/removekey <service>` | ลบ key ที่บันทึกไว้ |
| `/new` | เริ่มบทสนทนาใหม่ |
| `/history` | ดูประวัติสนทนา |

## ตัวอย่างการใช้งาน

### อีเมล

| คำสั่ง | คำอธิบาย |
| --- | --- |
| `/email` | สรุปอีเมล Gmail วันนี้ |
| `/email 7d` | สรุปอีเมลย้อนหลัง 7 วัน |
| `/email force` | สรุปใหม่ทั้งหมด |
| `/wm` | สรุปอีเมลองค์กรผ่าน IMAP |
| `/wm subject:ประชุม 7d` | ค้นหาเมลงานย้อนหลัง |
| `/inbox` | วิเคราะห์อีเมลล่าสุด หา action items |
| `/inbox mode auto` | เปิดโหมดสร้าง todo อัตโนมัติจากอีเมล |

### งานและนัดหมาย

| คำสั่ง | คำอธิบาย |
| --- | --- |
| `/todo ซื้อของ` | เพิ่ม todo |
| `/todo add ทำสไลด์ !high due:2026-03-30 18:00` | เพิ่ม todo พร้อม priority/due date |
| `/todo list` | ดู todo |
| `/todo done 1` | ปิดงาน |
| `/remind 2026-03-30 09:00 ประชุมทีม` | ตั้งเตือนครั้งเดียว |
| `/remind list` | ดู reminder |
| `/calendar list` | ดูนัดหมายใน Google Calendar |
| `/calendar add 2026-03-30 09:00 10:00 ประชุมทีม` | เพิ่มนัดหมาย |

### การเงินและเครื่องมือทั่วไป

| คำสั่ง | คำอธิบาย |
| --- | --- |
| `/expense 120 อาหาร ก๋วยเตี๋ยว` | บันทึกรายจ่าย |
| `/expense list` | ดูรายจ่ายล่าสุด |
| `/expense summary month` | สรุปรายจ่ายเดือนนี้ |
| ส่งรูปบิลหรือสลิป | ให้ระบบอ่านรูปและบันทึกรายจ่ายอัตโนมัติ |
| `/pay 120 0812345678` | สร้าง PromptPay QR จากเบอร์มือถือ |
| `/pay 500 1234567890121` | สร้าง PromptPay QR จากเลขบัตรประชาชน |
| `/qr https://example.com` | สร้าง QR Code |
| `/convert 10 km to mi` | แปลงหน่วย |
| `/search ราคาน้ำมันวันนี้` | ค้นหาข้อมูลเว็บ |
| `/fx` | ตรวจอัตราแลกเปลี่ยน |

### สถานที่ ข่าว และข้อมูลอื่น

| คำสั่ง | คำอธิบาย |
| --- | --- |
| `/places ร้านกาแฟแถวนี้` | ค้นหาสถานที่จริงบนแผนที่ |
| `/traffic สยาม ไป สีลม` | เช็คเส้นทางและสภาพจราจร |
| `/news` | สรุปข่าวล่าสุด |
| `/lotto` | ตรวจหวยล่าสุด |

## หมายเหตุเรื่องรูปและไฟล์

tool บางตัวส่งผลลัพธ์เป็น media ได้ เช่น:

- `/qr` ส่งรูป QR Code
- `/pay` ส่งรูป PromptPay QR
- Expense รับรูปบิล/slip ที่ส่งเข้ามาทาง Telegram

tool ไม่ต้องรู้จัก Telegram โดยตรง ระบบจะส่งผลลัพธ์ข้อความ รูป หรือไฟล์ผ่าน interface กลางให้อัตโนมัติ

## การจัดการหลายผู้ใช้

รองรับทั้ง 2 แบบ:

- self-registration ผ่าน `/start`
- owner จัดการผ่าน `/adduser`, `/removeuser`, `/listusers`

คำสั่ง owner:

| คำสั่ง | คำอธิบาย |
| --- | --- |
| `/adduser <chat_id> [ชื่อ]` | เพิ่มผู้ใช้ |
| `/removeuser <chat_id>` | ปิดการใช้งานผู้ใช้ |
| `/listusers` | ดูรายการผู้ใช้ทั้งหมด |

## เพิ่ม Tool ใหม่

สร้างไฟล์ใน `tools/` แล้ว registry จะ auto-discover ให้ทันที

```python
from tools.base import BaseTool


class MyTool(BaseTool):
    name = "my_tool"
    description = "อธิบายว่า tool นี้ทำอะไร"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        return "ผลลัพธ์"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string"}
                },
                "required": [],
            },
        }
```

## โครงสร้างโปรเจกต์

```text
openminicrew/
├── core/
│   ├── config.py
│   ├── llm.py
│   ├── api_keys.py
│   ├── db.py
│   ├── memory.py
│   ├── security.py
│   ├── gmail_oauth.py
│   ├── user_manager.py
│   └── providers/
│       ├── claude_provider.py
│       ├── gemini_provider.py
│       ├── matcha_provider.py
│       └── registry.py
├── tools/
│   ├── registry.py
│   ├── response.py
│   ├── gmail_summary.py
│   ├── work_email.py
│   ├── smart_inbox.py
│   ├── qrcode_gen.py
│   ├── promptpay.py
│   ├── unit_converter.py
│   ├── web_search.py
│   ├── reminder.py
│   ├── todo.py
│   ├── calendar_tool.py
│   ├── expense.py
│   ├── places.py
│   ├── traffic.py
│   ├── news_summary.py
│   ├── lotto.py
│   └── exchange_rate.py
├── interfaces/
├── dispatcher.py
├── scheduler.py
├── main.py
└── requirements.txt
```

## Webhook / Production

Webhook mode เหมาะกับ VPS หรือ production ที่มี HTTPS

```bash
BOT_MODE=webhook
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PORT=8443
TELEGRAM_WEBHOOK_SECRET=random-secret-string

python main.py
curl https://your-domain.com/health
```

รายละเอียดเชิงลึกของ webhook, nginx, และ deployment ดูใน docs ที่เกี่ยวข้องได้ภายหลัง
