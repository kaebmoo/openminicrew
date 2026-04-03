# ทำไมต้อง OpenMiniCrew

## สรุปสั้น

OpenMiniCrew คือผู้ช่วยส่วนตัว AI ที่อยู่ในแชท Telegram พิมพ์ข้อความหรือคำสั่งเข้าไป LLM จะเข้าใจว่าต้องการอะไร เลือกเรียก tool ที่ถูกต้อง แล้วส่งผลลัพธ์กลับมา ระบบจัดการได้ทั้งสรุปอีเมล บันทึกรายจ่าย ปฏิทิน เตือนความจำ สร้าง QR พร้อมเพย์ ค้นหาเว็บ เช็คจราจร ค้นหาสถานที่ ข่าว หวย และแปลงหน่วย -- ทั้งหมดจากหน้าแชทเดียว

รันบน VPS ลูกเดียว (Oracle Cloud Free Tier ก็พอ) เก็บข้อมูลใน SQLite ไฟล์เดียว ค่าใช้จ่ายเกือบเป็นศูนย์ เราเป็นเจ้าของเซิร์ฟเวอร์ เป็นเจ้าของข้อมูล และเพิ่มเครื่องมือใหม่ได้แค่วางไฟล์ Python ไฟล์เดียวลงใน folder

---

## เหมาะกับใคร

OpenMiniCrew สร้างมาสำหรับคนที่อยากได้ AI assistant ที่ทำงานจริงๆ ผ่านแชท แต่ยังสนใจว่าข้อมูลไปอยู่ที่ไหนและใครเข้าถึงได้บ้าง

**นักพัฒนาที่อยากคุมทุกอย่างเอง** อ่าน source code ได้ทุกบรรทัด แก้พฤติกรรมได้ทุกจุด host ที่ไหนก็ได้ ไม่ผูกกับ vendor ไม่มีค่า subscription ข้อมูลไม่หลุดออกจาก infrastructure ของเรา ยกเว้นที่เราเลือกเชื่อม API ภายนอกเอง

**ทีมเล็กหรือครอบครัว** ที่อยากแชร์ bot ตัวเดียว user แต่ละคนมี API key, OAuth token, ประวัติแชท, และบันทึกรายจ่ายแยกกัน admin (คนดูแลเซิร์ฟเวอร์) ไม่สามารถอ่านข้อมูลส่วนตัวของ user คนอื่นได้ -- ไม่ใช่แค่นโยบาย แต่เป็นข้อจำกัดทางสถาปัตยกรรม ไม่มีคำสั่ง admin ใดที่ดูอีเมล, API key, หรือประวัติแชทของคนอื่นได้

**คนไทยโดยเฉพาะ** เครื่องมือรองรับภาษาไทยโดยตรงผ่าน LLM, สร้าง QR พร้อมเพย์ด้วย EMVCo payload, ตรวจเลขบัตรประชาชนด้วย checksum, validate เบอร์มือถือไทย, แปลงหน่วยที่ดิน (ไร่/งาน/ตารางวา) และหน่วยทองคำ (สลึง/บาททอง/ตำลึง/ชั่ง), เช็คอัตราแลกเปลี่ยนจาก ธปท., ตรวจหวย, และปฏิบัติตาม พ.ร.บ.คุ้มครองข้อมูลส่วนบุคคล (PDPA) ด้วยระบบ consent และคำสั่งลบข้อมูล

---

## แก้ปัญหาอะไร

ทุกวันเราเปิดหลายแอปทำงานเล็กๆ ซ้ำๆ: เช็คอีเมล จดรายจ่าย ดูเส้นทาง เช็คอัตราแลกเปลี่ยน ตั้งเตือนความจำ แต่ละแอปมี interface ของตัวเอง login ของตัวเอง notification ของตัวเอง OpenMiniCrew รวมทุกอย่างเข้ามาในหน้าแชทเดียว

หลักคิดคือ งาน automation ส่วนตัวส่วนใหญ่ทำตาม pattern เดียว: เข้าใจ intent, เรียก API, จัดรูปแบบผลลัพธ์ ไม่จำเป็นต้องใช้ agent framework ซับซ้อน แค่ต้องการ dispatcher ที่ route request ไปถูก tool, tool interface ที่ขยายง่าย, และ default ที่ทำงานได้โดยไม่ต้อง config อะไร

---

## หลักการออกแบบ

**ใช้ API ไม่ใช้ browser** OpenMiniCrew ไม่เปิด web browser เลยแม้แต่ครั้งเดียว ทุก tool เชื่อมตรงกับ API: Google Maps, Gmail, Tavily, ธนาคารแห่งประเทศไทย, Open-Meteo และอื่นๆ นี่เป็นการเลือกโดยตั้งใจ -- browser automation เปราะบาง เว็บเปลี่ยน layout, บล็อกบอท, ใส่ CAPTCHA, พังแบบคาดเดาไม่ได้ การเรียก API เสถียร เร็ว และคาดเดาได้ ข้อแลกคือ OpenMiniCrew ทำได้เฉพาะกับบริการที่มี API แต่ในทางปฏิบัติครอบคลุมงาน automation ส่วนตัวเกือบทั้งหมด

**Privacy จากสถาปัตยกรรม ไม่ใช่จากนโยบาย** การแยก user ทำที่ระดับ database query ทุก query filter ด้วย `user_id` ไม่มี function ใน codebase ที่ให้ user A อ่านข้อมูลของ user B ได้ ไม่ว่า A จะเป็น admin หรือไม่ API key เข้ารหัสด้วย Fernet symmetric encryption, Gmail token เข้ารหัสแยก user, ข้อความที่มีข้อมูลอ่อนไหว (เบอร์โทร, เลขบัตร) ถูกลบจาก Telegram อัตโนมัติหลังประมวลผล ระบบรองรับ consent แบบชัดแจ้งสำหรับ Gmail, ตำแหน่ง, และประวัติแชท -- และมี `/delete_my_data confirm` สำหรับลบข้อมูลถาวร

**เรียบง่ายด้วยไฟล์เดียว** ระบบทั้งหมดรันใน Python process เดียว: FastAPI สำหรับ webhook, APScheduler สำหรับงาน background, SQLite ใน WAL mode สำหรับ storage ไม่มี Redis ไม่มี Celery ไม่มี message queue ไม่มี microservices นี่ไม่ใช่ความขี้เกียจ แต่เป็นการเลือกโดยตั้งใจสำหรับ assistant ที่ serve user ไม่กี่คน -- ชิ้นส่วนน้อยลงเท่ากับสิ่งที่พังตอนตี 3 น้อยลง

**Tool คือหน่วยของการขยาย** เพิ่มความสามารถใหม่ = สร้างไฟล์ Python ไฟล์เดียวใน `tools/` ที่ implement `execute()` กับ `get_tool_spec()` ระบบ auto-discover ตอน startup tool ประกาศ command, description (ที่ LLM ใช้ตัดสินใจ route), และ parameter แค่นั้น ไม่ต้องเรียนรู้ plugin system ไม่ต้องแก้ config ไม่ต้อง deploy ใหม่

**LLM เป็น router ไม่ใช่ executor** LLM ตัดสินใจว่าจะเรียก tool ไหนด้วย argument อะไร ตัว tool ทำงานแบบ deterministic ไม่มี LLM เกี่ยวข้องกับการทำงานจริง การแยกนี้ทำให้ค่าใช้จ่ายคาดเดาได้ (request ส่วนใหญ่ใช้ LLM call ราคาถูกแค่ครั้งเดียว) และผลลัพธ์คงที่ (input เดียวกันได้ output เดียวกันเสมอ) มี self-correction loop จัดการกรณี LLM route ผิด: ถ้าเลือก tool ไม่มีจริง หรือ tool error ระบบส่ง feedback กลับให้ LLM ลองใหม่ได้สูงสุด 3 รอบ

---

## เปรียบเทียบกับ agent platform เต็มรูปแบบ

แพลตฟอร์มอย่าง OpenClaw (open-source, รันบน Mac) เป็นแนวทางที่ต่างออกไปสำหรับ personal AI ให้ agent ที่ทำงานอัตโนมัติ มีตัวตนถาวร มี scheduling แบบ proactive (agent ตื่นขึ้นมาทำงานโดย user ไม่ต้องสั่ง) ใช้ browser automation และรับ voice input ได้ ทรงพลังและยืดหยุ่น

OpenMiniCrew เลือกเส้นทางที่ต่างออกไป:

**OpenClaw รันหลาย agent ให้คนเดียว OpenMiniCrew รัน bot เดียวให้หลายคน** OpenClaw แก้ปัญหา context overload ด้วยการแยก agent เฉพาะทาง แต่ละตัวมี "soul" และ memory ของตัวเอง OpenMiniCrew แก้ปัญหา multi-tenancy ด้วยการแยกข้อมูล user ที่ระดับ database คนละปัญหา คนละทางออก

**OpenClaw ต้องมีเครื่องเฉพาะ OpenMiniCrew รันบน VPS ฟรี** OpenClaw ออกแบบให้รันบน Mac Mini (หรือเครื่องที่เปิดตลอด) พร้อม browser OpenMiniCrew รันบน ARM VM RAM 1 GB ไม่มีจอ ไม่มี browser ไม่มี GUI ค่าใช้จ่ายเป็นศูนยได้

**OpenClaw ทำงานเชิงรุก OpenMiniCrew ทำงานเมื่อถูกสั่ง (ตอนนี้)** OpenClaw agent ตื่นขึ้นมาเช็ค CRM ร่าง email แล้วส่งข้อความอัพเดทให้ ทั้งหมดโดยไม่ต้องถูกสั่ง OpenMiniCrew รอให้ user ส่งข้อความก่อน มี schedule tool (`/schedule`) ที่รัน tool ตาม cron ได้ แต่ยังไม่มี "daily brief" ที่รวบรวมข้อมูลส่งให้อัตโนมัติ สิ่งนี้อยู่ใน roadmap

**OpenClaw ใช้ browser automation OpenMiniCrew ใช้ API** นี่คือความแตกต่างที่ใหญ่ที่สุดในทางปฏิบัติ OpenClaw โต้ตอบกับเว็บไซต์ได้ทุกอย่าง OpenMiniCrew ทำได้เฉพาะบริการที่มี API แต่ API ไม่พังเมื่อเว็บเปลี่ยนหน้าตา ไม่โดนบล็อกจากระบบป้องกันบอท ไม่ต้อง screenshot หรือ parse DOM สำหรับบริการที่ OpenMiniCrew รองรับ แนวทาง API เสถียรกว่า

ไม่มีแนวทางไหนดีกว่าในทุกสถานการณ์ ถ้าอยากได้ agent อัตโนมัติที่ใช้เว็บไซต์อะไรก็ได้และทำงานให้ตอนหลับ ลอง OpenClaw ถ้าอยากได้ bot ที่เสถียร ถูก serve ได้หลายคน จัดการงานประจำวันผ่าน API ที่เสถียร พร้อม privacy ที่แข็งแรง OpenMiniCrew เหมาะกว่า

---

## จุดแข็งตอนนี้

**รองรับ LLM หลาย provider** Claude, Gemini, และ Matcha (OpenAI-compatible endpoint ใดก็ได้) ใช้ได้ทันที user เปลี่ยน provider ได้ด้วย `/model` ระบบ fallback อัตโนมัติถ้า provider ใดไม่พร้อม Matcha ให้ทางเลือกค่าใช้จ่ายเป็นศูนย์สำหรับ user ที่เชื่อม endpoint ของตัวเอง

**ระบบจัดการ API key แยก user** บริการแบ่งเป็น 3 ระดับ: shared (ทุกคนใช้ key ของ operator), shared-with-quota (operator ตั้ง default, user ใส่ key ตัวเองได้), และ private-only (Gmail, Calendar, IMAP ไม่ share เด็ดขาด) logic การหา key ชัดเจน: เช็ค key ของ user ก่อน, ถ้าไม่มีใช้ shared key, ถ้าเป็น private-only และ user ไม่มี key ก็ return ว่างไม่ fallback

**เครื่องมือเฉพาะคนไทย** สร้าง QR พร้อมเพย์ด้วย EMVCo payload, ตรวจเลขบัตรประชาชนด้วย checksum, validate เบอร์มือถือผ่าน `phonenumbers`, หน่วยที่ดินไทย (ไร่/งาน/ตารางวา), หน่วยทองคำ (สลึง/บาททอง/ตำลึง/ชั่ง), อัตราแลกเปลี่ยนจาก ธปท., ตรวจหวย, และรองรับภาษาไทยในทุกการใช้งาน LLM

**บันทึกรายจ่ายจากรูปถ่าย** ส่งรูปบิลใน Telegram, Gemini Vision อ่านแล้ว extract จำนวนเงิน วันที่ หมวดหมู่ แล้วบันทึกรายจ่ายให้ ไม่ต้อง OCR library -- LLM อ่านภาษาไทยได้โดยตรง

**ปฏิบัติตาม PDPA** ระบบ consent แบบชัดแจ้งสำหรับ Gmail, ตำแหน่ง, และประวัติแชท retention limit บังคับด้วย scheduled cleanup jobs, ลบข้อมูลถาวรด้วย `/delete_my_data confirm`, บันทึก consent พร้อมตรวจสอบ, เอกสารกฎหมาย (Terms of Service, Privacy Policy) ทั้งภาษาไทยและอังกฤษ

---

## ข้อจำกัดในปัจจุบัน

บอกตรงๆ -- บางอย่างเป็นโดย design บางอย่างอยู่ใน roadmap

**ยังไม่ทำงานเชิงรุก** Bot ตอบเมื่อ user ส่งข้อความเท่านั้น ยังไม่สามารถตื่นขึ้นมาบอกว่า "อีก 30 นาทีมีประชุม และวันนี้รถติดกว่าปกติ" มี schedule tool (`/schedule`) ที่ตั้งเวลารัน tool ได้ แต่ยังไม่มี daily brief ที่รวบรวมข้อมูลหลายแหล่งส่งให้อัตโนมัติ นี่คือสิ่งที่มี priority สูงสุดใน roadmap

**ยังไม่รับ voice** ต้องพิมพ์ หรือใช้ voice-to-text ของ Telegram เอง bot ยังไม่ประมวลผล audio message โดยตรง การเพิ่ม speech-to-text ผ่าน Gemini ที่ interface layer ทำได้ไม่ยากแต่ยังไม่ได้ทำ

**ไม่มี browser automation** ถ้าบริการไม่มี API ก็ใช้ไม่ได้ ไม่มีการ scrape, กรอกฟอร์ม, หรือใช้เว็บที่ไม่มี API นี่เป็นโดย design (เสถียรกว่ายืดหยุ่น) แต่เป็นข้อจำกัดจริง

**เรียก tool ได้ทีละตัว** แต่ละข้อความ trigger ได้ 1 tool ถ้าถามว่า "เช็คนัด calendar พรุ่งนี้แล้วดูจราจรว่าต้องออกกี่โมง" bot ยังเรียก calendar แล้ว traffic ต่อเนื่องไม่ได้ ต้องส่ง 2 ข้อความ multi-step dispatcher ออกแบบและเขียน spec ไว้แล้ว แต่ยังไม่ได้ implement

**ยังไม่มี prompt injection defense ใน system prompt** เมื่อ bot อ่านอีเมลหรือผล web search เนื้อหาจะถูกส่งให้ LLM สรุป อีเมลที่มีคำสั่งซ่อนอยู่อาจทำให้ LLM ทำตาม การเพิ่ม boundary ใน system prompt เพื่อปฏิเสธคำสั่งที่ฝังในเนื้อหาภายนอกนั้นวางแผนไว้แล้ว ควรทำก่อนเปิดให้คนที่ไม่ไว้ใจใช้

**SQLite มีเพดาน** SQLite ใน WAL mode รับ concurrent reads ได้ดี แต่ write contention จะเป็นปัญหาเมื่อมีผู้ใช้งานพร้อมกันเกิน 10-20 คน สำหรับ bot ส่วนตัวหรือทีมเล็กไม่มีปัญหา ถ้า deploy ใหญ่ขึ้นต้องย้าย database layer ไป PostgreSQL

**ไม่มี web UI** ทุกอย่างผ่าน Telegram ไม่มี dashboard ไม่มีหน้าตั้งค่า config ทำผ่านคำสั่งในแชทและ environment variables operator จัดการเซิร์ฟเวอร์ผ่าน SSH กับ systemd

**Onboarding ให้ข้อมูลเยอะเกินตอนเริ่ม** user ใหม่เห็นคำสั่งตั้งค่าทั้งหมดทันทีหลัง `/start` ซึ่งอาจมากเกินไป แนวทาง progressive -- แนะนำ feature เมื่อ user ต้องการใช้จริง -- จะเป็น UX ที่ดีกว่าแต่ยังไม่ได้ทำ

---

## สิ่งที่อยู่ใน Roadmap

จากรูปแบบการใช้งานจริง และแรงบันดาลใจจาก agent platform อื่น:

**Prompt injection defense** -- เพิ่ม boundary ใน system prompt เพื่อป้องกัน LLM ทำตามคำสั่งที่ฝังอยู่ในเนื้ออีเมล ผล web search หรือข้อมูลจากภายนอก effort ต่ำ impact สูง ควรทำก่อนเปิดให้ใช้กว้าง

**Progressive onboarding** -- ลดขั้นตอนตอน `/start` ให้เหลือแค่ลงทะเบียนแล้วพร้อมใช้ feature ต่างๆ ถูกแนะนำเมื่อ user ลองใช้ครั้งแรก (เช่น "ต้อง /setphone ก่อนสร้าง PromptPay QR")

**Daily brief** -- scheduled job ที่ส่งสรุปตอนเช้า: นัดวันนี้จาก calendar, todo ที่ due, action items จากอีเมล, และอาจรวมสภาพอากาศ ใช้ scheduler infrastructure และ tools ที่มีอยู่แล้ว

**รับ voice message** -- รับ voice message จาก Telegram, ถอดเสียงด้วย Gemini, แล้วประมวลผลผ่าน dispatcher ปกติ แก้เฉพาะ interface layer

**Weather tool (TMD + Open-Meteo)** -- สถาปัตยกรรม dual-API ใช้ข้อมูลกรมอุตุนิยมวิทยาสำหรับเตือนภัยและข้อมูลสถานีจริง บวก Open-Meteo สำหรับพยากรณ์รายชั่วโมง ดัชนี UV และคุณภาพอากาศ โครงสร้างพื้นฐาน (ระบบ API key, ระบบตำแหน่ง) พร้อมแล้ว

**Multi-step tool calling** -- ให้ dispatcher เรียก tool หลายตัวต่อเนื่องในข้อความเดียว มี design document อยู่ใน `plan/backlog-multi-step-dispatcher.md` ใช้ heuristic ที่ไม่กระทบ fast path ของ query แบบ single-tool

**User preferences** -- ภาษา, timezone, รูปแบบ notification, หมวดรายจ่าย default เก็บแยก user แล้ว inject เข้า system prompt เพื่อ LLM ปรับพฤติกรรมตาม

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
