# ทำไมต้อง OpenMiniCrew

## สรุปสั้น

OpenMiniCrew คือผู้ช่วยส่วนตัว AI ที่อยู่ในแชท Telegram พิมพ์ข้อความหรือคำสั่งเข้าไป LLM จะเข้าใจว่าต้องการอะไร เลือกเรียก tool ที่ถูกต้อง แล้วส่งผลลัพธ์กลับมา ระบบจัดการได้ทั้งสรุปอีเมล บันทึกรายจ่าย ปฏิทิน เตือนความจำ สร้าง QR พร้อมเพย์ ค้นหาเว็บ เช็คจราจร ค้นหาสถานที่ ข่าว หวย และแปลงหน่วย -- ทั้งหมดจากหน้าแชทเดียว

รันบน VPS ลูกเดียว (Oracle Cloud Free Tier ก็พอ) เก็บข้อมูลใน SQLite ไฟล์เดียว ค่าใช้จ่ายเกือบเป็นศูนย์ เราเป็นเจ้าของเซิร์ฟเวอร์ เป็นเจ้าของข้อมูล และเพิ่มเครื่องมือใหม่ได้แค่วางไฟล์ Python ไฟล์เดียวลงใน folder

---

## เหมาะกับใคร

OpenMiniCrew สร้างมาสำหรับคนที่อยากได้ AI assistant ที่ทำงานจริงๆ ผ่านแชท แต่ยังสนใจว่าข้อมูลไปอยู่ที่ไหนและใครเข้าถึงได้บ้าง

**นักพัฒนาที่อยากคุมทุกอย่างเอง** อ่าน source code ได้ทุกบรรทัด แก้พฤติกรรมได้ทุกจุด host ที่ไหนก็ได้ ไม่ผูกกับ vendor ไม่มีค่า subscription

**ทีมเล็กหรือครอบครัว** ที่อยากแชร์ bot ตัวเดียว user แต่ละคนมี API key, OAuth token, ประวัติแชท และบันทึกรายจ่ายแยกกัน admin ไม่สามารถอ่านข้อมูลส่วนตัวของ user อื่นได้ (ดูรายละเอียดในหัวข้อ [Privacy จากสถาปัตยกรรม](#หลักการออกแบบ))

**คนไทยโดยเฉพาะ** รองรับฟีเจอร์เฉพาะคนไทยหลายตัวตั้งแต่ PromptPay QR จนถึงตรวจหวย และปฏิบัติตาม PDPA (ดูรายละเอียดในหัวข้อ [จุดแข็ง](#จุดแข็งตอนนี้))

---

## แก้ปัญหาอะไร

ทุกวันเราเปิดหลายแอปทำงานเล็กๆ ซ้ำๆ: เช็คอีเมล จดรายจ่าย ดูเส้นทาง เช็คอัตราแลกเปลี่ยน ตั้งเตือนความจำ แต่ละแอปมี interface ของตัวเอง login ของตัวเอง notification ของตัวเอง OpenMiniCrew รวมทุกอย่างเข้ามาในหน้าแชทเดียว

หลักคิดคือ งาน automation ส่วนตัวส่วนใหญ่ทำตาม pattern เดียว: เข้าใจ intent, เรียก API, จัดรูปแบบผลลัพธ์ ไม่จำเป็นต้องใช้ agent framework ซับซ้อน แค่ต้องการ dispatcher ที่ route request ไปถูก tool, tool interface ที่ขยายง่าย, และ default ที่ทำงานได้โดยไม่ต้อง config อะไร

---

## หลักการออกแบบ

**ใช้ API ไม่ใช้ browser** OpenMiniCrew ไม่เปิด web browser เลยแม้แต่ครั้งเดียว ทุก tool เชื่อมตรงกับ API: Google Maps, Gmail, Tavily, ธนาคารแห่งประเทศไทย, Open-Meteo และอื่นๆ นี่เป็นการเลือกโดยตั้งใจ -- browser automation เปราะบาง เว็บเปลี่ยน layout, บล็อกบอท, ใส่ CAPTCHA, พังแบบคาดเดาไม่ได้ การเรียก API เสถียร เร็ว และคาดเดาได้ ข้อแลกคือทำได้เฉพาะกับบริการที่มี API แต่ในทางปฏิบัติครอบคลุมงาน automation ส่วนตัวเกือบทั้งหมด

**Privacy จากสถาปัตยกรรม ไม่ใช่จากนโยบาย** การแยก user ทำที่ระดับ database query ทุก query filter ด้วย `user_id` ไม่มี function ใน codebase ที่ให้ user A อ่านข้อมูลของ user B ได้ ไม่ว่า A จะเป็น admin หรือไม่ API key เข้ารหัสด้วย Fernet symmetric encryption, Gmail token เข้ารหัสแยก user, ข้อความที่มีข้อมูลอ่อนไหว (เบอร์โทร, เลขบัตร) ถูกลบจาก Telegram อัตโนมัติหลังประมวลผล

**เรียบง่ายด้วยไฟล์เดียว** ระบบทั้งหมดรันใน Python process เดียว: FastAPI สำหรับ webhook, APScheduler สำหรับงาน background, SQLite ใน WAL mode สำหรับ storage ไม่มี Redis ไม่มี Celery ไม่มี message queue ไม่มี microservices นี่ไม่ใช่ความขี้เกียจ แต่เป็นการเลือกโดยตั้งใจสำหรับ assistant ที่ serve user ไม่กี่คน -- ชิ้นส่วนน้อยลงเท่ากับสิ่งที่พังตอนตี 3 น้อยลง

**Tool คือหน่วยของการขยาย** เพิ่มความสามารถใหม่ = สร้างไฟล์ Python ไฟล์เดียวใน `tools/` ที่ implement `execute()` กับ `get_tool_spec()` ระบบ auto-discover ตอน startup tool ประกาศ command, description (ที่ LLM ใช้ตัดสินใจ route), และ parameter แค่นั้น ไม่ต้องเรียนรู้ plugin system ไม่ต้องแก้ config ไม่ต้อง deploy ใหม่

**LLM เป็น router ไม่ใช่ executor** LLM ตัดสินใจว่าจะเรียก tool ไหนด้วย argument อะไร ตัว tool ทำงานแบบ deterministic ไม่มี LLM เกี่ยวข้องกับการทำงานจริง การแยกนี้ทำให้ค่าใช้จ่ายคาดเดาได้ (request ส่วนใหญ่ใช้ LLM call ราคาถูกแค่ครั้งเดียว) และผลลัพธ์คงที่ (input เดียวกันได้ output เดียวกันเสมอ) มี self-correction loop จัดการกรณี LLM route ผิด: ถ้าเลือก tool ไม่มีจริง หรือ tool error ระบบส่ง feedback กลับให้ LLM ลองใหม่ได้สูงสุด 3 รอบ

---

## เปรียบเทียบกับ agent platform เต็มรูปแบบ

แพลตฟอร์มอย่าง OpenClaw (open-source, รันบน Mac) เป็นแนวทางที่ต่างออกไปสำหรับ personal AI ให้ agent ที่ทำงานอัตโนมัติ มีตัวตนถาวร มี scheduling แบบ proactive ใช้ browser automation และรับ voice input ได้ ทรงพลังและยืดหยุ่น

OpenMiniCrew เลือกเส้นทางที่ต่างออกไป:

| | OpenClaw | OpenMiniCrew |
|---|---------|-------------|
| **สถาปัตยกรรม** | หลาย agent ให้คนเดียว | bot เดียวให้หลายคน |
| **ฮาร์ดแวร์** | ต้องมีเครื่องเฉพาะ (Mac Mini+) พร้อม browser | VPS ฟรี ARM VM RAM 1 GB ไม่มีจอ ไม่มี GUI |
| **พฤติกรรม** | เชิงรุก -- agent ตื่นขึ้นมาทำงานโดยไม่ต้องถูกสั่ง | เชิงรับ -- รอ user ส่งข้อความก่อน (มี `/schedule` สำหรับ cron) |
| **การเข้าถึงบริการ** | browser automation -- โต้ตอบกับเว็บไซต์ได้ทุกอย่าง | API เท่านั้น -- เสถียรกว่าแต่ทำได้เฉพาะบริการที่มี API |

ไม่มีแนวทางไหนดีกว่าในทุกสถานการณ์ ถ้าอยากได้ agent อัตโนมัติที่ใช้เว็บไซต์อะไรก็ได้และทำงานให้ตอนหลับ ลอง OpenClaw ถ้าอยากได้ bot ที่เสถียร ถูก serve ได้หลายคน จัดการงานประจำวันผ่าน API ที่เสถียร พร้อม privacy ที่แข็งแรง OpenMiniCrew เหมาะกว่า

---

## จุดแข็งตอนนี้

**รองรับ LLM หลาย provider** Claude, Gemini, และ Matcha (OpenAI-compatible endpoint ใดก็ได้) ใช้ได้ทันที user เปลี่ยน provider ได้ด้วย `/model` ระบบ fallback อัตโนมัติถ้า provider ใดไม่พร้อม Matcha ให้ทางเลือกค่าใช้จ่ายเป็นศูนย์สำหรับ user ที่เชื่อม endpoint ของตัวเอง

**ระบบจัดการ API key แยก user** บริการแบ่งเป็น 3 ระดับ: shared (ทุกคนใช้ key ของ operator), shared-with-quota (operator ตั้ง default, user ใส่ key ตัวเองได้), และ private-only (Gmail, Calendar, IMAP ไม่ share เด็ดขาด) logic การหา key ชัดเจน: เช็ค key ของ user ก่อน, ถ้าไม่มีใช้ shared key, ถ้าเป็น private-only และ user ไม่มี key ก็ return ว่างไม่ fallback

**เครื่องมือเฉพาะคนไทย** สร้าง QR พร้อมเพย์ด้วย EMVCo payload, ตรวจเลขบัตรประชาชนด้วย checksum, validate เบอร์มือถือผ่าน `phonenumbers`, หน่วยที่ดินไทย (ไร่/งาน/ตารางวา), หน่วยทองคำ (สลึง/บาททอง/ตำลึง/ชั่ง), อัตราแลกเปลี่ยนจาก ธปท., ตรวจหวย, และรองรับภาษาไทยในทุกการใช้งาน LLM

**บันทึกรายจ่ายจากรูปถ่าย** ส่งรูปบิลใน Telegram, Gemini Vision อ่านแล้ว extract จำนวนเงิน วันที่ หมวดหมู่ แล้วบันทึกรายจ่ายให้ ไม่ต้อง OCR library -- LLM อ่านภาษาไทยได้โดยตรง

**ปฏิบัติตาม PDPA** ระบบ consent แบบชัดแจ้งสำหรับ Gmail, ตำแหน่ง, และประวัติแชท retention limit บังคับด้วย scheduled cleanup jobs, ลบข้อมูลถาวรด้วย `/delete_my_data confirm`, บันทึก consent พร้อมตรวจสอบ, เอกสารกฎหมาย (Terms of Service, Privacy Policy) ทั้งภาษาไทยและอังกฤษ

---

## ข้อจำกัดและ Roadmap

บอกตรงๆ -- บางอย่างเป็นโดย design บางอย่างอยู่ใน roadmap

| ข้อจำกัด | รายละเอียด | สถานะ |
|----------|-----------|------|
| **ยังไม่ทำงานเชิงรุก** | Bot ตอบเมื่อ user ส่งข้อความเท่านั้น มี `/schedule` สำหรับ cron แต่ยังไม่มี daily brief ที่รวบรวมข้อมูลหลายแหล่งส่งให้อัตโนมัติ | Roadmap -- priority สูงสุด วางแผนเป็น scheduled job สรุปตอนเช้า (นัด, todo, อีเมล, อากาศ) |
| **ยังไม่รับ voice** | ต้องพิมพ์หรือใช้ voice-to-text ของ Telegram เอง | Roadmap -- แก้เฉพาะ interface layer ถอดเสียงด้วย Gemini แล้วส่งเข้า dispatcher ปกติ |
| **เรียก tool ได้ทีละตัว** | แต่ละข้อความ trigger ได้ 1 tool เช่น "เช็ค calendar แล้วดูจราจร" ต้องส่ง 2 ข้อความ | Roadmap -- design document อยู่ใน `plan/backlog-multi-step-dispatcher.md` |
| **ยังไม่มี prompt injection defense** | เนื้อหาจากอีเมลหรือ web search ถูกส่งให้ LLM สรุป อาจมีคำสั่งซ่อนอยู่ | Roadmap -- effort ต่ำ impact สูง ควรทำก่อนเปิดให้ใช้กว้าง |
| **SQLite มีเพดาน** | write contention เป็นปัญหาเมื่อ active users เกิน 10-20 คน | ย้ายไป PostgreSQL เมื่อต้อง scale |
| **ไม่มี web UI** | ทุกอย่างผ่าน Telegram config ผ่านคำสั่งแชทและ env vars | ยังไม่มีแผน -- Telegram เพียงพอสำหรับ use case ปัจจุบัน |
| **Onboarding หนักเกินไป** | user ใหม่เห็นคำสั่งตั้งค่าทั้งหมดทันทีหลัง `/start` | Roadmap -- progressive onboarding แนะนำ feature เมื่อ user ต้องการใช้จริง |

**Roadmap เพิ่มเติมที่ไม่ใช่การแก้ข้อจำกัด:**

- **Weather tool (TMD + Open-Meteo)** -- สถาปัตยกรรม dual-API ใช้ข้อมูลกรมอุตุฯ สำหรับเตือนภัย บวก Open-Meteo สำหรับพยากรณ์รายชั่วโมง โครงสร้างพื้นฐาน (ระบบ API key, ระบบตำแหน่ง) พร้อมแล้ว
- **User preferences** -- ภาษา, timezone, รูปแบบ notification, หมวดรายจ่าย default เก็บแยก user แล้ว inject เข้า system prompt

---

## เริ่มใช้งาน

```bash
git clone https://github.com/kaebmoo/openminicrew.git
cd openminicrew
pip install -r requirements.txt
cp .env.example .env
# แก้ .env ใส่ Telegram bot token และ LLM API key อย่างน้อย 1 ตัว
python main.py
```

เปิดแชทกับ bot บน Telegram ส่ง `/start` แค่นี้ก็พร้อมใช้

สำหรับ production deployment บน Oracle Cloud Free Tier พร้อม webhook mode, nginx, และ systemd ดูรายละเอียดใน [README](../../README.md) หลัก

---

## License

OpenMiniCrew ใช้ dual license: AGPL-3.0 (ฟรีสำหรับ open-source; ถ้า deploy เป็น network service ต้องเปิด source code) และ commercial license สำหรับใช้แบบ proprietary ดูรายละเอียดใน [LICENSING.md](../../LICENSING.md)
