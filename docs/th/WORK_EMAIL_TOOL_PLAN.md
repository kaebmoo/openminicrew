# Work Email Tool (IMAP) — Implementation Plan

## 1. Scope

ทำ tool ใหม่ `tools/work_email.py` สำหรับอ่านเมลองค์กร (mail.ntplc.co.th) ผ่าน IMAP พร้อมความสามารถ 3 อย่าง:

1. **สรุปเมล** — เหมือน Gmail tool ที่มีอยู่ แต่ผ่าน IMAP
2. **สรุปไฟล์แนบ** — extract เนื้อหาจากไฟล์แนบแล้วรวมในการสรุป
3. **ค้นหาเมล** — ค้นจาก from, to, subject, body หรือคำค้นทั่วไป

---

## 2. ไฟล์ที่ต้องสร้าง/แก้ไข

| ไฟล์                | Action                       | รายละเอียด                  |
| ----------------------- | ---------------------------- | ------------------------------------- |
| `tools/work_email.py` | **สร้างใหม่** | Tool หลัก (~400-500 บรรทัด) |
| `core/config.py`      | **เพิ่ม**         | config ใหม่ 6 ตัว              |
| `.env.example`        | **เพิ่ม**         | ตัวอย่าง config               |
| `requirements.txt`    | **เพิ่ม**         | dependencies ใหม่ 3 ตัว        |

ไม่ต้องแก้: dispatcher.py, registry.py, db.py, หรือ core อื่นใด (registry auto-discover)

---

## 3. Config ที่ต้องเพิ่ม

### `.env`

```bash
# === Work Email (IMAP) ===
WORK_IMAP_HOST=mail.ntplc.co.th
WORK_IMAP_PORT=993
WORK_IMAP_USER=pornthep@ntplc.co.th
WORK_IMAP_PASSWORD=your-password-here
WORK_EMAIL_MAX_RESULTS=30
WORK_EMAIL_ATTACHMENT_MAX_MB=5
```

### `core/config.py` — เพิ่มท้ายไฟล์

```python
# === Work Email (IMAP) ===
WORK_IMAP_HOST = _optional("WORK_IMAP_HOST", "")
WORK_IMAP_PORT = int(_optional("WORK_IMAP_PORT", "993"))
WORK_IMAP_USER = _optional("WORK_IMAP_USER", "")
WORK_IMAP_PASSWORD = _optional("WORK_IMAP_PASSWORD", "")
WORK_EMAIL_MAX_RESULTS = int(_optional("WORK_EMAIL_MAX_RESULTS", "30"))
WORK_EMAIL_ATTACHMENT_MAX_MB = int(_optional("WORK_EMAIL_ATTACHMENT_MAX_MB", "5"))
```

---

## 4. Dependencies ที่ต้องเพิ่ม

```
pdfplumber>=0.10.0       # extract text จาก PDF
python-docx>=1.0.0       # extract text จาก Word
openpyxl>=3.1.0          # extract text จาก Excel
```

**ไม่ต้องเพิ่ม:** imaplib, email — มากับ Python standard library อยู่แล้ว

---

## 5. Commands และการใช้งาน

### 5.1 Command ตรง (ไม่เสีย LLM token)

| Command                               | ผลลัพธ์                                                |
| ------------------------------------- | ------------------------------------------------------------- |
| `/wm`                               | สรุปเมลยังไม่ได้อ่านวันนี้          |
| `/wm 3d`                            | ย้อนหลัง 3 วัน                                     |
| `/wm 7d`                            | ย้อนหลัง 7 วัน                                     |
| `/wm 30d`                           | ย้อนหลัง 30 วัน                                    |
| `/wm force`                         | สรุปใหม่ทั้งหมด (แม้เคยสรุปแล้ว) |
| `/wm from:somchai`                  | จากผู้ส่งชื่อ somchai                            |
| `/wm to:finance`                    | ส่งถึง finance                                          |
| `/wm subject:ประชุม`          | หัวข้อมีคำว่า ประชุม                       |
| `/wm body:งบประมาณ`         | เนื้อหามีคำว่า งบประมาณ                 |
| `/wm ประชุม`                  | ค้นทั้ง subject + from + body (TEXT search)            |
| `/wm from:boss subject:ด่วน 7d` | รวมหลาย filter                                         |
| `/wm force from:hr 7d`              | รวม force + filter + เวลา                              |

### 5.2 พิมพ์อิสระ (LLM function calling)

```
"สรุปเมลที่ทำงานให้หน่อย"
"มีเมลอะไรจากฝ่ายบัญชีบ้าง"
"หาเมลเรื่องประชุมบอร์ดย้อนหลัง 7 วัน"
"เมลจาก boss เมื่อวานมีอะไรบ้าง"
```

---

## 6. Architecture ภายใน Tool

### 6.1 Class Structure

```
WorkEmailTool(BaseTool)
│
├── Properties
│   ├── name = "work_email"
│   ├── description = "สรุปอีเมลที่ทำงาน (IMAP) พร้อมอ่านไฟล์แนบ ค้นหาได้"
│   └── commands = ["/wm", "/workmail"]
│
├── Public Methods
│   ├── execute(user_id, args) → str       # entry point
│   └── get_tool_spec() → dict             # สำหรับ LLM function calling
│
└── Private Methods
    ├── _parse_args(args) → ParsedArgs      # แยก time_range, filters, force
    ├── _connect_imap() → IMAP4_SSL         # connect + login
    ├── _build_search_criteria(parsed) → str # สร้าง IMAP SEARCH string
    ├── _fetch_emails(conn, criteria, max_results) → list[EmailData]
    │   ├── _decode_header(raw) → str       # จัดการ encoding ภาษาไทย
    │   ├── _extract_body(msg) → str        # ดึง text จาก multipart
    │   └── _process_attachments(msg) → list[AttachmentData]
    │       ├── _extract_pdf(data) → str
    │       ├── _extract_docx(data) → str
    │       ├── _extract_xlsx(data) → str
    │       └── _extract_text_file(data, charset) → str
    └── _summarize_with_llm(emails_data, user_id) → str
```

### 6.2 Data Classes (ใช้ dataclass หรือ dict ธรรมดา)

```python
ParsedArgs:
    time_range: str       # "today" | "3d" | "7d" | "30d"
    force: bool           # สรุปใหม่ทั้งหมด
    filters: dict         # {"from": "somchai", "subject": "ประชุม", ...}
    search_text: str      # คำค้นทั่วไป (ไม่มี prefix)

EmailData:
    message_id: str
    subject: str
    sender: str
    date: str
    body: str             # ตัดที่ 2,000 chars
    attachments: list[AttachmentData]

AttachmentData:
    filename: str
    size_bytes: int
    mime_type: str
    content: str | None   # extracted text (ตัดที่ 3,000 chars) หรือ None ถ้าอ่านไม่ได้
    status: str           # "extracted" | "too_large" | "unsupported" | "error"
```

---

## 7. Flow การทำงาน

### 7.1 Main Flow

```
execute(user_id, args)
    │
    ├── [1] ตรวจว่า config ครบ (WORK_IMAP_HOST, USER, PASSWORD)
    │       ไม่ครบ → return error message
    │
    ├── [2] _parse_args(args)
    │       แยก: time_range, force, filters, search_text
    │
    ├── [3] run_in_executor:  ← ทั้ง block นี้รันใน thread pool
    │   │
    │   ├── [3a] _connect_imap()
    │   │       IMAP4_SSL(host, port) → login(user, password)
    │   │
    │   ├── [3b] _build_search_criteria(parsed)
    │   │       สร้าง IMAP SEARCH string จาก filters
    │   │
    │   ├── [3c] _fetch_emails(conn, criteria, max_results)
    │   │       SELECT INBOX → SEARCH → FETCH ทีละฉบับ
    │   │       กรอง processed emails (ถ้าไม่ force)
    │   │       ดึง body + attachments
    │   │
    │   └── [3d] conn.logout()
    │
    ├── [4] ตรวจจำนวนเมล
    │       ไม่มีเมลใหม่ → return "ไม่มีอีเมลใหม่"
    │
    ├── [5] _summarize_with_llm(emails_data, user_id)
    │       เตรียม text (เมล + ไฟล์แนบ) → ส่ง LLM สรุป
    │
    ├── [6] บันทึก processed emails ลง DB
    │
    ├── [7] บันทึก tool_logs ลง DB
    │
    └── [8] return ผลสรุป
```

### 7.2 Args Parsing Flow

```
_parse_args("force from:boss subject:ด่วน 7d ค้นหาอะไร")
    │
    ├── แยก force → True (ลบออกจาก args)
    ├── แยก time_range → "7d" (match regex: \d+d)
    ├── แยก filters:
    │   ├── from:boss → {"from": "boss"}
    │   └── subject:ด่วน → {"subject": "ด่วน"}
    └── ที่เหลือ → search_text = "ค้นหาอะไร"

ผลลัพธ์:
    ParsedArgs(
        time_range="7d",
        force=True,
        filters={"from": "boss", "subject": "ด่วน"},
        search_text="ค้นหาอะไร"
    )
```

### 7.3 IMAP Search Criteria Building

```
_build_search_criteria(parsed)

กรณี: time_range="7d", filters={"from": "boss", "subject": "ด่วน"}
    │
    ├── SINCE 23-Feb-2026              ← จาก time_range
    ├── FROM "boss"                     ← จาก filters["from"]
    ├── SUBJECT "ด่วน"                  ← จาก filters["subject"]
    └── UNSEEN                          ← default (ถ้าไม่ force)

ผลลัพธ์: '(UNSEEN SINCE 23-Feb-2026 FROM "boss" SUBJECT "ด่วน")'

กรณี: search_text="ประชุม" (ไม่มี filter เฉพาะ)
ผลลัพธ์: '(UNSEEN SINCE 02-Mar-2026 TEXT "ประชุม")'

กรณี: force=True, time_range="today"
ผลลัพธ์: '(SINCE 02-Mar-2026)'    ← ไม่มี UNSEEN เพราะ force
```

### 7.4 Attachment Processing Flow

```
_process_attachments(email_message)
    │
    ├── วน loop หา parts ที่เป็น attachment
    │   (Content-Disposition: attachment หรือ inline ที่มีชื่อไฟล์)
    │
    ├── ไฟล์ที่ 1, 2, 3: process ปกติ
    │   ├── ขนาด > 5 MB?
    │   │   └── YES → status="too_large", content=None
    │   │
    │   ├── ประเภทไฟล์:
    │   │   ├── application/pdf → _extract_pdf(data)
    │   │   │   └── pdfplumber → extract text → ตัดที่ 3,000 chars
    │   │   │
    │   │   ├── application/vnd.openxmlformats...wordprocessing → _extract_docx(data)
    │   │   │   └── python-docx → extract paragraphs → ตัดที่ 3,000 chars
    │   │   │
    │   │   ├── application/vnd.openxmlformats...spreadsheet → _extract_xlsx(data)
    │   │   │   └── openpyxl → อ่าน sheet แรก → แปลงเป็น text table → ตัดที่ 3,000 chars
    │   │   │
    │   │   ├── text/* หรือ .csv → _extract_text_file(data, charset)
    │   │   │   └── decode → ตัดที่ 3,000 chars
    │   │   │
    │   │   ├── image/* → status="image", content=None
    │   │   │   (บันทึกแค่ชื่อ + ขนาด)
    │   │   │
    │   │   └── อื่นๆ → status="unsupported", content=None
    │   │       (บันทึกแค่ชื่อ + ขนาด)
    │   │
    │   └── error ระหว่าง extract → status="error", content=None
    │
    └── ไฟล์ที่ 4+ → บันทึกแค่ชื่อ + ขนาด + "(ข้ามเพราะเกิน 3 ไฟล์)"
```

---

## 8. ข้อจำกัด (Limits)

| รายการ                                       | Limit                       | เหตุผล                    |
| -------------------------------------------------- | --------------------------- | ------------------------------- |
| ขนาดไฟล์แนบต่อไฟล์               | 5 MB                        | ป้องกัน memory spike     |
| เนื้อหาที่ extract ต่อไฟล์        | 3,000 chars                 | ประหยัด LLM token        |
| จำนวนไฟล์แนบที่อ่านต่อเมล | 3 ไฟล์                  | ประหยัด token + เวลา |
| เนื้อหา body ต่อเมล                   | 2,000 chars                 | เหมือน Gmail tool         |
| จำนวนเมลสูงสุด                       | 30 ฉบับ (config ได้) | ป้องกัน timeout          |

---

## 9. Encoding / ภาษาไทย

เมลองค์กรไทยมีปัญหา encoding เยอะ ต้อง handle หลาย layer:

### 9.1 Subject Header

```python
# Subject อาจมาในรูปแบบ:
# =?TIS-620?B?...base64...?=
# =?UTF-8?B?...base64...?=
# =?Windows-874?Q?...quoted-printable...?=

from email.header import decode_header

def _decode_header(raw: str) -> str:
    parts = decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            charset = charset or "utf-8"
            # fallback chain
            for enc in [charset, "utf-8", "tis-620", "windows-874"]:
                try:
                    decoded.append(data.decode(enc))
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                decoded.append(data.decode("utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)
```

### 9.2 Body

```python
# Body encoding มาจาก Content-Type header:
# Content-Type: text/plain; charset="TIS-620"
# Content-Type: text/html; charset="windows-874"

# ใช้ fallback chain เดียวกัน
```

### 9.3 ชื่อไฟล์แนบ

```python
# ชื่อไฟล์อาจมาในรูปแบบ:
# Content-Disposition: attachment; filename="=?UTF-8?B?...?="
# Content-Disposition: attachment; filename*=UTF-8''%E0%B8%AA%E0%B8%A3%E0%B8%B8%E0%B8%9B.pdf

# ใช้ email.utils + urllib.parse จัดการ
```

---

## 10. IMAP Connection Strategy

```
Strategy: Connect-once, fetch-all, disconnect

เหตุผล:
- IMAP server จำกัดจำนวน connection
- connect/login ใช้เวลา (TCP handshake + TLS + auth)
- ลด overhead โดย fetch ทุกเมลใน connection เดียว

Flow:
  conn = IMAP4_SSL(host, port)
  conn.login(user, password)
  conn.select("INBOX")
  
  # search + fetch ทั้งหมดตรงนี้
  
  conn.close()
  conn.logout()

ทั้ง block นี้รันใน:
  asyncio.get_event_loop().run_in_executor(None, _sync_fetch_all)

เพราะ imaplib เป็น synchronous ทั้งหมด
```

---

## 11. LLM Prompt Design

### 11.1 System Prompt

```
คุณเป็นผู้ช่วยสรุปอีเมลที่ทำงาน สรุปให้กระชับ เข้าใจง่าย เป็นภาษาไทย

รูปแบบการสรุป:
- ภาพรวม: สรุปสั้นๆ ว่ามีกี่ฉบับ เรื่องอะไรบ้าง
- ต้องดำเนินการ: เมลที่ต้องทำอะไร (ตอบกลับ, อนุมัติ, ตรวจสอบ)
- จัดกลุ่มตามประเภท: งาน, การเงิน, HR, IT, อื่นๆ
- ไฟล์แนบสำคัญ: สรุปเนื้อหาไฟล์แนบที่สำคัญ
- สรุปท้าย: สิ่งที่ควรให้ความสำคัญก่อน
```

### 11.2 Email Data Format ที่ส่งให้ LLM

```
--- Email #1 ---
From: somchai.w@ntplc.co.th
Date: 2 Mar 2026, 09:15
Subject: สรุปงบประมาณ Q1/2026
Content: ส่งสรุปงบประมาณไตรมาสแรกตามแนบครับ ขอให้ review...

Attachments:
  1. [PDF] งบประมาณ_Q1.pdf (145 KB) — extracted:
     รายรับรวม 120 ล้านบาท รายจ่ายดำเนินงาน 85 ล้านบาท
     กำไรสุทธิ 35 ล้านบาท เพิ่มขึ้น 12% จากปีก่อน...

  2. [XLSX] detail_Q1.xlsx (52 KB) — extracted:
     | หมวด | งบ | ใช้จริง | คงเหลือ |
     | บุคลากร | 45M | 42M | 3M |
     | วัสดุ | 20M | 18.5M | 1.5M |
     ...

  3. [JPG] chart.jpg (230 KB) — รูปภาพ (ไม่สามารถอ่านเนื้อหา)

--- Email #2 ---
From: hr@ntplc.co.th
Date: 2 Mar 2026, 10:30
Subject: แจ้งวันหยุดเดือนมีนาคม
Content: แจ้งวันหยุดประจำเดือนมีนาคม...
Attachments: ไม่มี
```

---

## 12. Error Handling Strategy

| สถานการณ์          | การจัดการ | Message ที่ user เห็น                                                        |
| --------------------------- | ------------------ | ----------------------------------------------------------------------------------- |
| Config ไม่ครบ         | return ทันที  | "ยังไม่ได้ตั้งค่า IMAP (ตั้งค่าใน .env)"                   |
| Connect ไม่ได้        | catch + log        | "เชื่อมต่อ mail server ไม่ได้ ตรวจสอบ host/port"              |
| Login ไม่ผ่าน        | catch + log        | "Login ไม่ผ่าน ตรวจสอบ username/password ใน .env"                   |
| SSL certificate error       | catch + log        | "SSL error: ตรวจสอบ certificate ของ mail server"                          |
| Search ไม่พบเมล     | return ปกติ    | "ไม่พบอีเมลตามเงื่อนไขที่ระบุ"                          |
| Fetch เมลบาง msg fail | skip + log         | ข้ามเมลที่ fail สรุปเท่าที่ได้                              |
| Extract ไฟล์แนบ fail | skip + log         | แสดงชื่อไฟล์ + "ไม่สามารถอ่านเนื้อหา"               |
| LLM call fail               | catch + log        | "สรุปเมลไม่ได้ กรุณาลองใหม่"                               |
| Timeout (เมลเยอะ)    | timeout 60s        | "ใช้เวลานานเกินไป ลองจำกัดช่วงเวลาให้แคบลง" |

---

## 13. SSL/TLS Consideration

```python
# mail.ntplc.co.th อาจใช้:
# 1. Valid certificate จาก CA → ใช้ IMAP4_SSL ปกติ
# 2. Self-signed certificate → ต้อง custom ssl context

import ssl

# ลอง default ก่อน
try:
    conn = imaplib.IMAP4_SSL(host, port)
except ssl.SSLCertVerificationError:
    # fallback: skip verification (ใส่ warning ใน log)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    log.warning("IMAP SSL: certificate verification disabled")
```

---

## 14. Memory Management

```
ปัญหา: ไฟล์แนบ 5 MB x 3 ไฟล์ x 30 เมล = worst case ~450 MB

แก้ไข: Process ทีละฉบับ ไม่เก็บ raw attachment data ใน memory

Flow:
  for msg_id in matched_ids:
      msg = fetch(msg_id)
      email_data = extract(msg)       # extract text + attachments
      results.append(email_data)      # เก็บแค่ text ที่ extract แล้ว
      del msg                         # ปล่อย raw data

  # ตรงนี้ results เก็บแค่ text ไม่เก็บ binary
```

---

## 15. Security Considerations

| ประเด็น           | สถานะ           | หมายเหตุ                                                  |
| ------------------------ | -------------------- | ----------------------------------------------------------------- |
| Password ใน .env       | ต้องระวัง   | .env ห้าม commit (.gitignore มีอยู่แล้ว)            |
| IMAP connection          | SSL/TLS              | Port 993 = encrypted by default                                   |
| ไม่มี shell exec    | ปลอดภัย       | tool ทำแค่ IMAP + file parse                                 |
| ไฟล์แนบ malicious | จำกัด           | อ่านแค่ text ไม่ execute อะไร                       |
| Token vs Password        | ต่างจาก Gmail | Gmail ใช้ OAuth (revokable) แต่ IMAP ใช้ password ตรง |

---

## 16. ความแตกต่างจาก Gmail Tool (gmail_summary.py)

| Feature        | Gmail Tool                        | Work Email Tool                                               |
| -------------- | --------------------------------- | ------------------------------------------------------------- |
| Protocol       | REST API (async)                  | IMAP (sync, run_in_executor)                                  |
| Auth           | OAuth token (auto-refresh)        | username + password                                           |
| Search         | Gmail query syntax                | IMAP SEARCH commands                                          |
| ไฟล์แนบ | ไม่อ่าน                    | อ่าน PDF, DOCX, XLSX, TXT                                 |
| Encoding       | Gmail จัดการให้          | ต้อง decode เอง (TIS-620, UTF-8)                       |
| Args parsing   | basic (email tool v1)             | advanced (from:, subject:, body:, time)                       |
| Commands       | `/email`                        | `/wm`, `/workmail`                                        |
| DB table       | processed_emails (ใช้ร่วม) | processed_emails (ใช้ร่วม, แยกด้วย tool source) |

---

## 17. DB Impact

ใช้ table `processed_emails` ที่มีอยู่แล้ว ไม่ต้องสร้างใหม่

แต่ต้องแยก Gmail vs IMAP ได้ ทำได้ 2 วิธี:

**วิธี A: ใช้ message_id ที่ต่างกันอยู่แล้ว**

- Gmail message_id format: `18e2a3b4c5d6e7f8`
- IMAP message_id format: `<CAB+OWHVp...@mail.gmail.com>` หรือ IMAP UID

ทำให้ไม่ชนกัน ไม่ต้องแก้ schema

**วิธี B (optional): เพิ่ม column `source`**

- ถ้าอยากให้ชัดเจนกว่านี้ เพิ่ม `source TEXT DEFAULT 'gmail'`
- แต่ไม่จำเป็นสำหรับ v1

แนะนำ: **ใช้วิธี A** — ไม่ต้องแก้ DB schema เลย

---

## 18. ลำดับการทำงาน (Implementation Order)

### Phase 1: พื้นฐาน (ทำก่อน)

1. เพิ่ม config ใน `core/config.py` + `.env.example`
2. เพิ่ม dependencies ใน `requirements.txt`
3. สร้าง `tools/work_email.py` — โครงสร้าง class + `_parse_args` + `_connect_imap`
4. ทำ `_build_search_criteria` — สร้าง IMAP SEARCH string
5. ทำ `_fetch_emails` — ดึงเมล + decode header/body (ยังไม่ทำไฟล์แนบ)
6. ทำ `_summarize_with_llm` — ส่ง LLM สรุป
7. ทดสอบ `/wm` basic flow

### Phase 2: ไฟล์แนบ

8. ทำ `_process_attachments` — detect + extract
9. ทำ `_extract_pdf` (pdfplumber)
10. ทำ `_extract_docx` (python-docx)
11. ทำ `_extract_xlsx` (openpyxl)
12. ทำ `_extract_text_file`
13. ปรับ LLM prompt ให้รวมข้อมูลไฟล์แนบ
14. ทดสอบกับเมลที่มีไฟล์แนบจริง

### Phase 3: Polish

15. ทดสอบ encoding ภาษาไทย (TIS-620, Windows-874)
16. ทดสอบ SSL certificate
17. ทดสอบ search filters ทุก combination
18. ทำ error handling ให้ครบทุก case
19. ทดสอบ memory usage กับเมลจำนวนมาก

---

## 19. Estimated Size

| Component                              | Lines (est.)         |
| -------------------------------------- | -------------------- |
| Class shell + properties               | ~20                  |
| `_parse_args`                        | ~40                  |
| `_connect_imap`                      | ~25                  |
| `_build_search_criteria`             | ~50                  |
| `_decode_header` + `_extract_body` | ~60                  |
| `_fetch_emails` (main loop)          | ~80                  |
| `_process_attachments` + extractors  | ~100                 |
| `_summarize_with_llm`                | ~40                  |
| `execute` (orchestrator)             | ~60                  |
| `get_tool_spec`                      | ~30                  |
| **Total**                        | **~500 lines** |

---

## 20. Risks & Mitigations

| Risk                                                     | Impact                                      | Mitigation                                                                       |
| -------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| mail.ntplc.co.th ไม่รองรับ SEARCH บาง syntax | ค้นหาไม่ได้บาง filter         | Fallback: ดึงเมลมาแล้ว filter ฝั่ง Python                        |
| Self-signed SSL cert                                     | Connect ไม่ได้                        | Auto-fallback: skip verification + log warning                                   |
| เมลภาษาไทย encoding ผิด                     | หัวข้อ/เนื้อหาเป็น garbage | Fallback chain: charset → UTF-8 → TIS-620 → replace                           |
| ไฟล์แนบ PDF เป็น scanned image                | extract ได้ text ว่าง                | บอก user: "PDF เป็นรูปภาพ ไม่สามารถอ่านข้อความ" |
| IMAP timeout เพราะเมลเยอะ                    | Tool fail                                   | จำกัด max_results + timeout 60s                                             |
| Password เปลี่ยนแล้วลืมแก้ .env         | Login fail                                  | Error message ชัดเจน + log                                                 |

# การพัฒนาและปรับปรุงเพิ่มเติม (Implementation &  Improvements)

เอกสารส่วนนี้ระบุเกี่ยวกับเครื่องมืออ่านอีเมลองค์กรผ่าน IMAP (`tools/work_email.py`) พร้อมอ่านไฟล์แนบ

## สิ่งที่ต้องพัฒนา (Implementation)

1. ติดต่อ IMAP Server เพื่อดึงอีเมลที่ยังไม่ได้อ่าน
2. โหลด Config ผ่านตัวแปร `WORK_IMAP_HOST`, `WORK_IMAP_PORT`, `WORK_IMAP_USER`, `WORK_IMAP_PASSWORD`
3. ประมวลผลและแปลงไฟล์แนบประเภท `PDF`, `DOCX`, `XLSX` และไฟล์ `Text` ไปรวมเป็นข้อความ
4. ค้นหาแบบธรรมดา (Subject, Body, From, To) และมีระบบ Filter ช่วงเวลา
5. ส่งให้ LLM เป็นผู้คอยสรุปและบอก Action Required

---

## ข้อเสนอแนะและสิ่งที่ควรปรับปรุง (Improvements)

เพิ่ม/แก้ไข ฟีเจอร์เหล่านี้เพื่อเพิ่มประสิทธิภาพและความเสถียร

### 1. การโหลด Dependencies แบบ Lazy Import (Optional Dependencies)

ปัจจุบัน `pdfplumber`, `python-docx` และ `openpyxl` ถูกเรียกโหลด (import) ไว้ที่ส่วนหัวสุดของไฟล์ `tools/work_email.py`
**ปัญหา:** ผู้ใช้งานที่ไม่ต้องการใช้งานระบบ Work Email จะต้องติดตั้ง dependencies เหล่านี้ด้วย ไม่เช่นนั้นเมื่อ Bot เริ่มทำงานจะค้างตรงจังหวะ Auto-discover หรือเกิดเปัญหาแอปพลิเคชันพัง (Crash)
**วิธีแก้:** ควรย้ายคำสั่ง import ไปไว้ภายใน function (เช่น ใน `_extract_pdf` ให้มีคำสั่ง `import pdfplumber` ข้างใน) โหลดเฉพาะเวลาที่มีการดึงไฟล์รูปแบบนั้นๆ จริงๆ เท่านั้น

### 2. การควบคุมความยาวของข้อความทั้งหมด (Global Token Limit Prevention)

ถึงแม้โค้ดปัจจุบันมีการตัดตัวอักษรของ Text ในส่วนของอีเมลไว้ที่ 2,000 และไฟล์แนบไว้ที่ 3,000 ถ้าระบบเจอผลลัพธ์เป็นเมล 30 ฉบับ แต่ละฉบับมีไฟล์ประกอบ 3 ไฟล์ (Maximum Capacity)
ตัวเลขความยาว Text ทั้งหมดใน Prompt สามารถไปได้ถึง `(2000 + 3 * 3000) * 30 = 330,000 Characters`
**ปัญหา:** โมเดลบางตัวจะประมวลผลไม่ไหว (ทะลุ Context Window Limit) ทำให้เกิด Error ฝั่ง LLM Provider
**วิธีแก้:** ควรจะตรวจสอบผลรวมความยาว (Characters Length Sum) ก่อนสร้าง Prompt แล้วพิจารณาตัดอีเมลท้ายๆ ทิ้งถ้าความยาวเกิน `MAX_PROMPT_LENGTH` ให้สอดคล้องกับ LLM ปลายทาง

### 3. ประสิทธิภาพการค้นหาภาษาไทยบน IMAP (Thai IMAP Search Limitation)

การสร้างคำสั่งให้ IMAP Server ใช้เช่น `TEXT "ประชุม"` มักจะเจอข้อจำกัดที่ Server มองไม่เห็นภาษาไทยหรือตัดคำผิด ทำให้คืนค่าว่าไม่เกิดผลลัพธ์บางฉบับ
**ปัญหา:** ไม่สามารถหางานที่ค้นหาภาษาไทยได้ครบ 100%
**วิธีแก้:** ใช้แบบ Hybrid โดยเรียก `SINCE <time>` ดึงอีเมลทุกฉบับมาใน Memory หรือดึงมาเฉพาะ Headers/Metadata แล้วให้ใช้กลไก Regex และ `String Search` ในโปรแกรมไพธอนกวาดหาอีกทีจะเสถียรกว่า

### 4. การจัดการโครงสร้างตาราง HTML ของ Body (HTML Table Extraction)

ในอีเมลธุรกิจมักมีการใช้ HTML Tables สำหรับส่งรายละเอียด ตัวกรอง Tag `<br>` และ `<tr>` ควรอัพเกรดเพิ่มเติม
**ปัญหา:** เมื่อเอาคำสั่งลบ HTML tags `re.sub(r"<[^>]+>", " ", html_str)` ไปวางตรงตัวข้อมูลในตารางจะต่อกับความติดกันเป็นพืดจนไม่สามารถเข้าใจได้
**วิธีแก้:** ใช้โมดูลอย่าง `BeautifulSoup` หรือมีกลไกที่แปลง `<tr>`, `<br>`, `<p>` เป็นการเบรคบรรทัด (`\n`) ส่วน `<td>` เปลี่ยนเป็น เว้นระยะ หรือขีดคั่น `|` จะทำให้เมื่อส่งไป LLM จะสามารถให้ LLM ดูโครงสร้างที่ถูกต้องออก

### 5. ข้อจำกัดของ Unique ID และการบันทึกประวัติลบ

**ปัญหา:** `Message-ID` ใน IMAP นั้นบางครั้งไม่ได้ตั้งมาจากต้นทาง ทำให้ระบบต้องพึ่งพา IMAP `uid` ในการตัดสิน หาก Server ถูกย้าย ถังเก็บถูกกู้ หรือถูกย้ายโฟลเดอร์ `uid` เหล่านี้จะเปลี่ยน ทำให้อีเมลเดียวกันถูกประมวลผลซ้ำได้
**วิธีแก้:** สามารถสร้างการรวบรวม Hashing จาก `Subject` ควบคู่ไปกับ `Date` และ `Sender` เป็น UUID ในการอ้างอิงและบันทึกลงฐานข้อมูล

### 6. โฟลเดอร์อื่นๆ (Folder Selection)

**ปัญหา:** ระบบอ่านจากกล่องข้อความที่มีชื่อว่า `INBOX` เท่านั้น หากผู้ใช้งานมี Filter ในอีเมลองค์กรเด้งไปโฟลเดอร์ลูก (เช่น `INBOX/Projects`) ก็จะมองไม่เห็น
**วิธีแก้:** เพิ่มการรองรับ Argument เช่น `/wm folder:projects` และใช้คำสั่ง `conn.select("INBOX/Projects")`
