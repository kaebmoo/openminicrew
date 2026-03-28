# OpenMiniCrew — สร้าง AI Personal Assistant บน Telegram ด้วย Python ที่ใช้งานได้จริง

> เฟรมเวิร์ก open-source สำหรับสร้างผู้ช่วยส่วนตัว AI ผ่าน Telegram ที่ทำงานได้ตั้งแต่สรุปอีเมล ตรวจหวย บันทึกรายจ่ายจากรูปบิล ไปจนถึงเช็คสภาพจราจร — พร้อมระบบ privacy ที่คำนึงถึง PDPA ตั้งแต่แกนหลัก

---

## ทำไมถึงสร้าง OpenMiniCrew

เคยรู้สึกไหมว่าในแต่ละวัน เราทำงานซ้ำซากผ่านแอปหลายตัว — เช็คอีเมล, จดรายจ่าย, ดูสภาพจราจร, ค้นหาร้านอาหาร, แปลงหน่วย, ตรวจหวย — แต่ละอย่างต้องเปิดแอปคนละตัว คนละ workflow ถ้าเราสามารถทำทุกอย่างได้ในแชตเดียวล่ะ?

OpenMiniCrew เกิดจากแนวคิดที่ว่า **"แชทกับ AI แล้วได้ผลลัพธ์จริง ไม่ใช่แค่คำตอบ"** — เป็น AI assistant ที่ไม่ได้แค่ตอบคำถามทั่วไป แต่สามารถเรียกใช้เครื่องมือ (tools) ที่เชื่อมต่อกับ API จริง ทำงานจริง แล้วส่งผลลัพธ์กลับมาในแชต Telegram ของเรา

โปรเจกต์นี้เขียนด้วย Python ทั้งหมด ใช้ SQLite เป็น database (ไม่ต้อง setup Redis หรือ server อะไรซับซ้อน) และ deploy ได้บน VPS ราคาถูกหรือแม้แต่ Oracle Cloud Free Tier

<!-- [รูปที่ 1: Screenshot หน้าแชต Telegram กับ OpenMiniCrew — แสดงตัวอย่างการสั่งงานหลายแบบ เช่น สรุปอีเมล, สร้าง QR, เช็คเส้นทาง] -->

---

## OpenMiniCrew คืออะไร

OpenMiniCrew เป็น **framework สำหรับสร้าง AI personal assistant** ที่ทำงานผ่าน Telegram bot โดยมีคุณสมบัติหลักคือ:

**ใช้ LLM เป็นสมอง** — รองรับ Claude (Anthropic), Gemini (Google), และ Matcha (custom OpenAI-compatible endpoint) โดย user แต่ละคนสามารถเลือกใช้ LLM ที่ต้องการได้ และระบบจะ fallback อัตโนมัติถ้า provider หลักใช้ไม่ได้

**ใช้ Tools เป็นมือเท้า** — LLM ทำหน้าที่เข้าใจว่า user ต้องการอะไร แล้วเลือกเรียก tool ที่เหมาะสม tool แต่ละตัวเชื่อมต่อกับ API จริง ทำงานจริง แล้ว return ผลลัพธ์กลับให้ LLM สรุปเป็นภาษาธรรมชาติ

**เพิ่ม tool ใหม่ได้ง่ายมาก** — แค่สร้างไฟล์ Python ไฟล์เดียววางใน folder `tools/` ระบบจะ auto-discover และลงทะเบียนให้ทันที ไม่ต้องแก้ไขไฟล์ core ใด ๆ

**รองรับหลาย user** — แต่ละ user มี API keys, memory, preferences, OAuth credentials ของตัวเอง admin ไม่สามารถเข้าถึงข้อมูลส่วนตัวของ user คนอื่นได้ตาม design

---

## สถาปัตยกรรมที่เรียบง่ายแต่ยืดหยุ่น

หลักการออกแบบของ OpenMiniCrew คือ **"Deploy ง่าย ขยายง่าย ไม่ต้องพึ่ง infrastructure ซับซ้อน"**

### ภาพรวมระบบ

ระบบทำงานเป็น 4 ชั้นหลัก:

**Interface Layer** คือชั้นที่รับข้อความจาก Telegram สลับได้ระหว่าง polling mode (สำหรับพัฒนา) กับ webhook mode (สำหรับ production) ผ่านตัวแปร environment เดียว ทั้งสอง mode ใช้ shared logic ตัวเดียวกันในการ auth, แบ่งข้อความยาว, และ rate limiting

**Dispatcher** คือสมองกลางที่ตัดสินใจว่าจะทำอะไรกับข้อความแต่ละข้อความ ถ้าเป็น /command จะเรียก tool ตรง ๆ ไม่ผ่าน LLM (ประหยัด token) ถ้าเป็นข้อความอิสระจะส่งให้ LLM ตัดสินใจว่าควรเรียก tool ไหน หรือตอบเป็น general chat

**Tool Registry** คือระบบ auto-discover ที่ scan folder `tools/` ตอน startup แล้วลงทะเบียน tool ทุกตัวอัตโนมัติ tool แต่ละตัวประกาศ name, description, commands และ implement method `execute()` กับ `get_tool_spec()`

**Storage Layer** ใช้ SQLite ไฟล์เดียว ทำงานใน WAL mode ไม่ต้อง config อะไร ไม่ต้อง Redis ไม่ต้อง Celery

<!-- [รูปที่ 2: Diagram สถาปัตยกรรม — แสดง flow จาก Telegram → Dispatcher → LLM Router / Tool Registry → Storage Layer] -->

### Self-Correction Loop

จุดเด่นของ dispatcher คือ **agentic loop ที่มี self-correction** — ถ้า LLM เลือก tool ผิดชื่อ (เช่น เรียก "lottery" แทน "lotto") หรือ tool execute แล้ว error ระบบจะส่ง feedback กลับให้ LLM คิดใหม่ได้สูงสุด 3 รอบ ถ้ายังไม่สำเร็จจะ fallback ไปใช้ LLM tier ที่ฉลาดกว่า (เช่น จาก Flash ไป Sonnet) ก่อนจะยอมแพ้

flow ปกติที่ไม่มี error ยังคงทำงานเหมือนเดิมทุกประการ ไม่มี overhead เพิ่ม

### LLM Multi-Provider

ระบบรองรับ LLM provider 3 ตัว:

**Claude (Anthropic)** — ใช้ function calling แบบ native ของ Anthropic API ตอบภาษาไทยได้ดี เหมาะกับงานที่ต้องการความแม่นยำ

**Gemini (Google)** — ใช้ได้ทั้ง function declarations และ Gemini Vision สำหรับอ่านรูปบิล ฟรี tier เยอะ เหมาะสำหรับ personal use

**Matcha** — custom endpoint ที่ compatible กับ OpenAI API ใช้ `httpx` เชื่อมต่อ เหมาะสำหรับ self-hosted model หรือ API gateway ขององค์กร

user แต่ละคนเลือก provider ได้เองด้วยคำสั่ง `/model` และระบบจะ fallback อัตโนมัติถ้า provider ที่เลือกไว้ใช้ไม่ได้ (เช่น API key หมดอายุ)

การเพิ่ม LLM provider ใหม่ก็ง่ายเหมือนเพิ่ม tool — แค่สร้างไฟล์ Python ไฟล์เดียวใน `core/providers/` ที่ inherit `BaseLLMProvider` ระบบจะ auto-discover ให้

---

## เครื่องมือทั้งหมดที่มี

ปัจจุบัน OpenMiniCrew มี tools ใช้งานจริงมากกว่า 19 ตัว ครอบคลุมการใช้ชีวิตประจำวันหลายด้าน

### อีเมลและการสื่อสาร

**Gmail Summary** — สรุปอีเมล Gmail ด้วย AI โดยเชื่อมต่อผ่าน Google OAuth แบบ per-user (user แต่ละคน authorize Gmail ของตัวเอง) ใช้ LLM tier กลาง (Sonnet/Pro) สำหรับสรุปเพราะต้องเข้าใจเนื้อหาลึก สั่งได้ง่าย ๆ แค่ `/email` จะได้สรุปอีเมลวันนี้ หรือ `/email 7d` สำหรับย้อนหลัง 7 วัน

**Work Email** — สรุปอีเมลที่ทำงานผ่าน IMAP รองรับ search ด้วย subject, sender และช่วงเวลา credential เป็นแบบ per-user ผ่าน `/setkey` ใช้คำสั่ง `/wm` หรือ `/workmail`

**Smart Inbox** — วิเคราะห์อีเมลล่าสุดจาก Gmail แล้วหา action items ที่ต้องทำ สามารถสร้าง todo อัตโนมัติจากอีเมลได้ด้วย `/inbox mode auto`

<!-- [รูปที่ 3: Screenshot การใช้ /email สรุปอีเมล Gmail — แสดงผลสรุปที่ AI จัดหมวดหมู่ให้] -->

### การเงิน

**Expense Tracker** — บันทึกรายจ่ายด้วยการพิมพ์ เช่น `/expense 120 อาหาร ก๋วยเตี๋ยว` หรือ **ส่งรูปบิล/slip โดยตรง** ระบบจะใช้ Gemini Vision อ่านใบเสร็จ แยกรายการสินค้าทุกรายการ คำนวณ service charge และ VAT เฉลี่ยเข้าแต่ละรายการ แล้วให้เลือกบันทึกแบบแยกรายการหรือรวมเป็นรายการเดียว มีระบบตรวจ duplicate ด้วย hash ของรูป ป้องกันบันทึกซ้ำจากรูปเดียวกัน

ที่น่าสนใจคือมี **income guard** — ถ้า user พิมพ์ "รับเงิน 150 บาท" (ซึ่งเป็น intent ของ PromptPay ไม่ใช่ expense) ระบบจะปฏิเสธการบันทึกและแนะนำให้ใช้คำสั่งที่ถูกต้อง

**PromptPay QR** — สร้าง QR Code สำหรับรับเงินผ่านพร้อมเพย์ รองรับทั้งเบอร์มือถือและเลขบัตรประชาชน 13 หลัก มี checksum validation ครบ ใช้ `phonenumbers` library สำหรับ validate เบอร์ไทย และ `segno` สำหรับ generate QR (ไม่ต้องพึ่ง Pillow) ถ้าไม่ระบุเบอร์หรือเลขบัตร จะใช้ข้อมูลที่เคยบันทึกไว้จาก `/setphone` หรือ `/setid` โดยอัตโนมัติ

**Exchange Rate** — ตรวจอัตราแลกเปลี่ยนจาก Bank of Thailand API ฟรี

**Lotto** — ตรวจผลสลากกินแบ่งรัฐบาลล่าสุดจาก API ฟรี

<!-- [รูปที่ 4: Screenshot การส่งรูปบิลร้านอาหาร แล้วระบบอ่านและแสดง preview แยกรายการพร้อมปุ่ม Inline Keyboard ให้เลือกบันทึก] -->

<!-- [รูปที่ 5: Screenshot QR Code PromptPay ที่ generate จากคำสั่ง /pay 500] -->

### สถานที่และการเดินทาง

**Places** — ค้นหาสถานที่ผ่าน Google Places API (New) รองรับการค้นหาภาษาไทย ตรวจจับคำว่า "แถวนี้" เพื่อใช้ GPS ของ user เป็น location bias ตรวจจับ "เปิดอยู่" เพื่อกรองเฉพาะร้านที่เปิดอยู่ แสดง rating, ที่อยู่, เวลาเปิด-ปิด และ Google Maps link

**Traffic** — เช็คเส้นทาง ระยะทาง เวลาเดินทาง และสภาพจราจร real-time ผ่าน Google Maps รองรับ 4 โหมด: รถยนต์, เดินเท้า, ขนส่งสาธารณะ และมอเตอร์ไซค์ ตรวจจับภาษาไทยได้ เช่น "มอไซค์", "เดินเท้า", "BTS" แสดงเส้นทางทางเลือกสูงสุด 3 เส้นทาง พร้อม Google Maps URL ให้กดเปิดได้เลย ที่พิเศษคือรองรับ "ไม่ขึ้นทางด่วน" ได้ด้วย

<!-- [รูปที่ 6: Screenshot ผลค้นหา /places ร้านกาแฟแถวสยาม — แสดงชื่อร้าน rating ที่อยู่ ลิงก์ Google Maps] -->

### งานและนัดหมาย

**Todo** — จัดการรายการสิ่งที่ต้องทำ พร้อม priority (high/medium/low) และ due date สั่งได้ทั้งแบบสั้น `/todo ซื้อของ` หรือแบบเต็ม `/todo add ทำสไลด์ !high due:2026-03-30 18:00`

**Reminder** — ตั้งเตือนครั้งเดียวตามวันเวลาที่กำหนด เมื่อถึงเวลา bot จะส่งข้อความเตือนให้ ใช้ APScheduler กับ SQLite jobstore สำหรับ persistence (ไม่หายเมื่อ restart)

**Schedule** — ตั้งเวลาให้ tool ทำงานอัตโนมัติ เช่น สรุปอีเมลทุกเช้า 8 โมง หรือเช็คข่าวทุกวัน

**Google Calendar** — ดู เพิ่ม และลบนัดหมายใน Google Calendar ใช้ OAuth ชุดเดียวกับ Gmail

### ข้อมูลและเครื่องมือทั่วไป

**Web Search** — ค้นหาข้อมูลบนเว็บผ่าน Google Custom Search แล้วให้ LLM สรุปผลลัพธ์

**News Summary** — สรุปข่าวเด่นจาก Google News RSS ค้นหาตาม keyword ได้ ใช้ LLM สรุปเป็นภาษาที่อ่านง่าย พร้อมลิงก์อ้างอิงทุกข่าว

**Unit Converter** — แปลงหน่วยทั่วไป รวมถึงหน่วยไทย (ไร่, งาน, ตารางวา, บาททอง)

**QR Code Generator** — สร้าง QR Code จากข้อความหรือ URL ทั่วไป (แยกจาก PromptPay QR)

### ระบบจัดการตัวเอง

**Settings** — ตั้งค่าส่วนตัว ชื่อ, เบอร์โทร, เลขบัตรประชาชน

**API Keys** — จัดการ API key ส่วนตัวแบบ per-user ผ่าน `/setkey` เข้ารหัสด้วย Fernet

**Consent** — จัดการ consent สำหรับ Gmail, Location, Chat History แยกเป็นอิสระ

---

## สองทางในการสั่งงาน

OpenMiniCrew รองรับการสั่งงาน 2 แบบที่ทำงานคู่กัน:

### 1. /command — สั่งตรง ไม่เสีย token

พิมพ์ /command แล้วตามด้วย parameter เช่น `/expense 120 อาหาร` หรือ `/traffic สยาม ไป สีลม` ระบบจะเรียก tool ตรง ๆ โดยไม่ผ่าน LLM เลย ไม่เสียค่า API call ผลลัพธ์ได้เร็วกว่า

### 2. พิมพ์อิสระ — ให้ AI เลือก tool ให้

พิมพ์ตามปกติเหมือนแชทกับคน เช่น "อากาศวันนี้เป็นยังไง", "มีร้านกาแฟแถวนี้ไหม", "สรุปอีเมลให้หน่อย" — LLM จะเข้าใจ intent แล้วเลือก tool ที่เหมาะสมให้เอง ใช้ function calling ของแต่ละ provider (Claude tool_use, Gemini function_declarations)

สิ่งที่ทำให้ระบบเลือก tool ได้แม่นคือ **tool_spec** ที่เขียนอย่างมีโครงสร้าง ทุก tool มี description ที่ประกอบด้วย 3 ส่วน:
1. **Positive** — tool ทำอะไร
2. **Negative boundary** — tool ไม่ทำอะไร และควรไปใช้ tool ไหนแทน
3. **Examples** — ตัวอย่าง input ที่ควร route มา

เช่น expense tool จะบอกชัดว่า "ห้ามใช้กับรายรับ เงินเข้า รับเงิน — ถ้า user ต้องการรับเงินหรือสร้าง QR รับโอน ให้ใช้ promptpay แทน" ทำให้ LLM แยกแยะ intent ที่คล้ายกันได้อย่างถูกต้อง

<!-- [รูปที่ 7: Screenshot เปรียบเทียบการใช้ /command ตรง vs พิมพ์อิสระ ที่ได้ผลลัพธ์เดียวกัน] -->

---

## ระบบ Privacy ที่คิดถึง PDPA ตั้งแต่แกน

ในฐานะโปรเจกต์ที่จัดการข้อมูลส่วนบุคคล (ชื่อ, เบอร์โทร, เลขบัตรประชาชน, อีเมล, ตำแหน่ง GPS) เรื่อง privacy ไม่ใช่สิ่งที่เพิ่มทีหลัง แต่ถูกออกแบบเข้าไปในสถาปัตยกรรมตั้งแต่ต้น

### Explicit Consent Model

ระบบเก็บ consent แบบ explicit 3 ประเภทในตาราง `user_consents`:

**Gmail access** — user ต้อง authorize ผ่าน OAuth จริง (`/authgmail`) ไม่ใช่แค่กดยอมรับ สามารถถอนได้ด้วย `/disconnectgmail` หรือ `/consent gmail off`

**Location** — ต้องเปิด consent ก่อนด้วย `/consent location on` ถ้าถอน consent จะลบ location ที่เคยบันทึกไว้ทันที

**Chat history** — ต้องเปิด consent ก่อนด้วย `/consent chat on` ถ้าถอน consent จะหยุดบันทึกและลบประวัติสนทนาเก่าทั้งหมด

user ใหม่ทุกคนเริ่มต้นด้วยสถานะ `not_set` ทั้ง 3 ประเภท ไม่มีการ grant อัตโนมัติ

### Field-Level Encryption

ข้อมูลที่มีความเสี่ยงสูงจะถูกเข้ารหัสแบบ field-level ด้วย Fernet encryption:

- **เบอร์โทร** (`users.phone_number`) — encrypt ทั้ง field
- **เลขบัตรประชาชน** (`users.national_id`) — encrypt ทั้ง field + พยายามลบข้อความ Telegram หลัง `/setid`
- **หมายเหตุรายจ่าย** (`expenses.note`) — encrypt เพราะอาจมีข้อมูลอ่อนไหว
- **API keys ส่วนตัว** (`user_api_keys.api_key`) — encrypt at rest
- **Gmail OAuth tokens** (`credentials/gmail_{user_id}.json`) — encrypt at rest
- **OAuth client secret** (`credentials.json`) — encrypt at rest แบบ managed

### Data Minimization

ระบบพยายามเก็บข้อมูลให้น้อยที่สุด:

**Tool logs** — ไม่เก็บ raw input/output อีกต่อไป เก็บเฉพาะ kind, reference hash, และ size แทน ผ่าน `db.make_log_field()` ที่ทำ minimization อัตโนมัติ

**Processed email metadata** — เก็บเฉพาะ message ID สำหรับ dedup กับ boolean has-subject flag ไม่เก็บ subject, sender address, หรือ sender domain อีกแล้ว

### Retention & Cleanup

ข้อมูลไม่ถูกเก็บตลอดไป ระบบมี scheduled cleanup ที่ลบข้อมูลตาม retention policy:

- Chat history, tool logs, email metadata, pending messages, job runs — แต่ละประเภทมี retention days ตั้งค่าได้
- Location มี TTL (time-to-live) หมดอายุอัตโนมัติ

### Hard Purge

user สามารถสั่ง `/delete_my_data confirm` เพื่อลบข้อมูลทั้งหมดที่ผูกกับบัญชีแบบถาวร ครอบคลุม users, chat_history, conversations, expenses, todos, reminders, schedules, tool_logs, user_api_keys, user_locations, oauth_states, processed_emails, pending_messages, job_runs และ Gmail token file

ข้อยกเว้นเดียวที่ตั้งใจไว้คือ `security_audit_logs` ที่เก็บไว้เพื่อ governance และ incident investigation

### Security Audit Trail

ระบบมี audit trail สำหรับเหตุการณ์ด้าน security เช่น การอ่าน profile secrets, การอัปเดต private API keys, การ hard purge, และการ revoke Gmail โดยไม่เก็บ secret payload ดิบใน audit records

### Privacy Dashboard

user ดูสถานะ privacy ได้ตลอดเวลาด้วย `/privacy` ซึ่งจะแสดงสรุป consent states, retention settings, location state, API key hygiene, และวิธีจัดการข้อมูลของตัวเอง

<!-- [รูปที่ 8: Screenshot ผลลัพธ์คำสั่ง /privacy — แสดง consent status, retention settings, API key hygiene] -->

---

## Admin กับ User — แยกสิทธิ์ชัดเจน

OpenMiniCrew ออกแบบให้ **admin ไม่สามารถเข้าถึงข้อมูลส่วนตัวของ user คนอื่นได้ตาม architecture** ไม่ใช่แค่ policy

admin (owner) ทำได้เฉพาะ:
- เพิ่ม/ลบ user (`/adduser`, `/removeuser`)
- ดูรายชื่อ user (`/listusers`)
- ตรวจ API key storage audit (`/keyaudit`)
- จัดการ Gmail client secrets ระดับ app

สิ่งที่ admin ทำไม่ได้:
- อ่าน chat history ของ user คนอื่น
- ดู API keys ที่ user บันทึกไว้
- เข้าถึง Gmail/Calendar ของ user คนอื่น
- ดูเบอร์โทรหรือเลขบัตรประชาชนที่ encrypt ไว้

ระบบยังรองรับ self-registration ผ่าน `/start` ให้ user ใหม่สามารถลงทะเบียนเองได้ โดย admin สามารถตั้งค่าให้ auto-approve หรือต้อง approve ด้วยมือ

---

## การ Deploy บน Production

OpenMiniCrew ออกแบบมาให้ deploy ได้ง่ายบน VPS ทั่วไป โปรเจกต์นี้ run จริงอยู่บน Oracle Cloud Free Tier (ARM VM, Ubuntu 22.04)

### Architecture สำหรับ Production

ใช้ **webhook mode** ผ่าน FastAPI + uvicorn ทำงานเบื้องหลัง nginx reverse proxy:

- Telegram ส่ง webhook มาที่ nginx
- nginx forward ไปที่ FastAPI (port 8443)
- FastAPI ตอบ 200 ทันที แล้วประมวลผลเป็น BackgroundTask
- ผลลัพธ์ส่งกลับ user ผ่าน Telegram Bot API

### Security ของ Production

- **Webhook path สุ่ม** — ไม่ใช่ `/webhook` แบบเดาง่าย ใช้ `secrets.token_urlsafe(16)` generate
- **Secret token verification** — Telegram ส่ง secret_token ใน header มาด้วย ถ้าไม่ตรงจะ reject
- **HTTPS** — ผ่าน nginx + Let's Encrypt
- **Encryption key** — Fernet key สำหรับเข้ารหัสข้อมูลทุกอย่าง

### Key Rotation

ระบบรองรับ keyring model สำหรับ rotation:
- `ENCRYPTION_KEY` เป็น primary key สำหรับเข้ารหัสใหม่
- `ENCRYPTION_KEY_PREVIOUS` สำหรับ decrypt ข้อมูลเก่าระหว่าง migration
- คำสั่ง `--rotate-encryption` สำหรับ re-encrypt ข้อมูลทั้งหมดด้วย key ใหม่

### Systemd Service

มี service file พร้อมใช้ รัน `systemctl enable openminicrew` แล้วจบ restart อัตโนมัติเมื่อ crash มี health check endpoint สำหรับ monitoring

<!-- [รูปที่ 9: Diagram deployment — Telegram Cloud → nginx (HTTPS) → FastAPI/uvicorn → SQLite] -->

---

## เพิ่ม Tool ใหม่ — สร้างไฟล์เดียวจบ

หนึ่งใน design goal ของ OpenMiniCrew คือ **"เพิ่ม tool = สร้างไฟล์เดียว"** ไม่ต้องแก้ core, ไม่ต้อง register, ไม่ต้อง import

ขั้นตอนคือ:

1. สร้างไฟล์ `.py` ใน folder `tools/`
2. เขียน class ที่ inherit `BaseTool`
3. ตั้ง `name`, `description`, `commands`
4. implement `execute()` กับ `get_tool_spec()`
5. restart bot — tool พร้อมใช้งานทันที

ตัวอย่างโครงสร้างง่ายที่สุดของ tool:

```python
from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "คำอธิบายที่ LLM จะใช้ตัดสินใจ"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        return f"ผลลัพธ์: {args}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string", "description": "อธิบาย parameter"}
                },
            },
        }
```

วางไฟล์นี้ใน `tools/` แล้ว restart — เสร็จ ใช้ได้ทั้งแบบ `/mytool xxx` และพิมพ์อิสระ

tool ที่ต้องเรียก LLM ข้างในสามารถตั้ง `preferred_tier = "mid"` เพื่อใช้โมเดลตัวฉลาด (Sonnet/Pro) แทน tier ถูก (Haiku/Flash) ได้ และ tool ที่ต้อง return รูปภาพ (เช่น QR Code) ใช้ `MediaResponse` object ที่ระบบจะส่งเป็นรูปผ่าน Telegram ให้อัตโนมัติ

---

## License: AGPL-3.0 + Commercial Dual License

OpenMiniCrew ใช้ dual licensing:

**AGPL-3.0** — ใช้ฟรีสำหรับ open-source ถ้า deploy เป็น network service ต้องเปิด source code ทั้งหมดภายใต้ AGPL-3.0

**Commercial License** — สำหรับการใช้งานแบบ closed-source หรือ proprietary service ติดต่อที่ kaebmoo@gmail.com

กล่าวง่าย ๆ: ใช้ส่วนตัว เรียนรู้ วิจัย ฟรีหมด ถ้าจะ deploy เป็น service ให้คนอื่นใช้ ต้อง open-source ด้วย หรือซื้อ commercial license

---

## สิ่งที่กำลังพัฒนา

OpenMiniCrew ยังมี roadmap ที่น่าตื่นเต้นอีกหลายเรื่อง:

**Weather Tool** — พยากรณ์อากาศจาก TMD (กรมอุตุนิยมวิทยา) + Open-Meteo สำหรับข้อมูล hourly และ UV index ใช้ dual-API strategy เพื่อได้ทั้งข้อมูล official ของไทยและข้อมูลเชิงลึกจาก global model

**Intent Disambiguation** — ปรับปรุง tool routing ให้แม่นขึ้น ลดการ misroute ระหว่าง tool คู่ที่คล้ายกัน

**Multi-Platform** — สถาปัตยกรรมปัจจุบันแยก interface layer ออกจาก core อยู่แล้ว ทำให้เพิ่มรองรับ LINE หรือ WhatsApp ได้ในอนาคต โดย tool ทุกตัวไม่ต้องรู้จัก platform ที่ใช้อยู่

---

## สรุป

OpenMiniCrew ไม่ใช่แค่ Telegram bot ที่ตอบคำถาม แต่เป็น framework สำหรับสร้าง AI assistant ที่ทำงานจริงได้ ด้วยสถาปัตยกรรมที่เรียบง่าย (Python + SQLite + single process), ขยายง่าย (เพิ่ม tool = สร้างไฟล์เดียว), รองรับหลาย LLM provider, คำนึงถึง privacy ตั้งแต่แกนหลัก (encryption, consent, retention, hard purge), และ deploy ได้จริงบน production

ลองใช้ดูได้ที่ [github.com/kaebmoo/openminicrew](https://github.com/kaebmoo/openminicrew)

---

*OpenMiniCrew เป็นโปรเจกต์ open-source ภายใต้ AGPL-3.0 license พัฒนาโดย kaebmoo*
