# Privacy, Consent, and Security

> 🇬🇧 [English version](../en/PRIVACY_SECURITY.md)

เอกสารนี้อธิบายว่า OpenMiniCrew จัดการเรื่อง privacy, consent และ security อย่างไรใน implementation ปัจจุบัน
เอกสารนี้เป็นคู่มือเชิงเทคนิคสำหรับ operator และ contributor ไม่ใช่คำวินิจฉัยทางกฎหมาย

## ขอบเขต

OpenMiniCrew มีการจัดการข้อมูลที่อาจเป็นข้อมูลส่วนบุคคลหรือข้อมูลอ่อนไหวหลายกลุ่ม เช่น

- ข้อมูล profile ของผู้ใช้ เช่น ชื่อ เบอร์โทร และเลขบัตรประชาชน
- ประวัติแชตและชื่อ conversation
- location ที่ผู้ใช้ส่งจาก Telegram
- OAuth credentials ของ Gmail และ Google Calendar
- API keys รายผู้ใช้ และข้อมูล work email
- metadata ที่ derive จากระบบ เช่น processed email state, tool logs และ job history

ระบบไม่ได้ใช้มาตรการเดียวกับทุก field แต่จะเลือกตามความจำเป็นของ runtime และความเสี่ยงของข้อมูล

## หลักการด้าน Privacy

rollout ปัจจุบันยึดหลักดังนี้

1. เก็บข้อมูลเท่าที่จำเป็นต่อ feature
2. ใช้ explicit consent กับ feature ที่กระทบความเป็นส่วนตัวสูง
3. เข้ารหัส secrets และ identifiers ที่มีความเสี่ยงสูงเมื่อระบบไม่จำเป็นต้อง lookup แบบ plaintext
4. ใช้ minimization และ retention limits กับข้อมูล operational ปริมาณมาก
5. แยก revoke, delete และ hard purge ออกจาก deactivate ให้ชัด

## Consent Model

ปัจจุบัน OpenMiniCrew เก็บ consent แบบ explicit ไว้ในตาราง `user_consents` 3 ประเภท

| ด้านที่ขอ consent | internal type | ค่าเริ่มต้นของผู้ใช้ใหม่ | วิธีให้สิทธิ์ | วิธีถอนสิทธิ์ | ผลที่เกิดขึ้นตอนปิด |
| --- | --- | --- | --- | --- | --- |
| Gmail | `gmail_access` | `not_set` | `/authgmail` ผ่าน OAuth | `/disconnectgmail` หรือ `/consent gmail off` | ถอนสิทธิ์แล้วจะยกเลิก token access และล้าง OAuth state |
| Location | `location_access` | `not_set` | `/consent location on` | `/consent location off` | ถอนสิทธิ์แล้วลบ location ที่เคยบันทึกไว้ |
| Chat history | `chat_history` | `not_set` สำหรับผู้ใช้ใหม่ | `/consent chat on` | `/consent chat off` | ถอนสิทธิ์แล้วหยุดบันทึก history ต่อ และลบ chat history กับ conversations เดิม |

พฤติกรรมสำคัญ:

- `/consent gmail on` ไม่ได้ grant Gmail access ทันที ผู้ใช้ต้องทำ OAuth จริงผ่าน `/authgmail`
- ผู้ใช้ legacy บางรายอาจถูก backfill consent ตามสภาพข้อมูลเดิมที่มีอยู่ก่อนหน้า
- ผู้ใช้ใหม่จะถูกสร้าง explicit consent records แบบ `not_set` ตั้งแต่ onboarding

## คำสั่งด้าน Privacy ที่ผู้ใช้ใช้ได้

| คำสั่ง | หน้าที่ |
| --- | --- |
| `/privacy` | ดูสรุป consent, retention, location state และ API key hygiene |
| `/consent [gmail\|location\|chat] [on\|off]` | ดูหรือเปลี่ยน explicit consent |
| `/disconnectgmail` | ยกเลิกการเชื่อม Gmail โดยไม่ purge ข้อมูลทั้งหมด |
| `/clearlocation` | ลบ location ล่าสุดที่บันทึกไว้ |
| `/delete_my_data confirm` | hard-purge ข้อมูลที่ผูกกับ user และ credential artifacts |
| `/mykeys` | ดู private keys ที่บันทึกไว้และสถานะ rotation แบบ advisory |

## โมเดลการปกป้องข้อมูลปัจจุบัน

ตารางนี้อิงตาม implementation ปัจจุบันของระบบ

| กลุ่มข้อมูล | การปกป้องปัจจุบัน | หมายเหตุ |
| --- | --- | --- |
| `users.phone_number` | field-level encryption | decrypt ตอน read และ migrate plaintext legacy ได้เมื่อมี `ENCRYPTION_KEY` |
| `users.national_id` | field-level encryption | decrypt ตอน read และระบบพยายามลบข้อความ Telegram หลัง `/setid` |
| `expenses.note` | field-level encryption | ใช้กับ note รายจ่ายแบบสั้น และ decrypt เฉพาะตอนแสดงผลกลับให้ผู้ใช้ |
| `user_api_keys.api_key` | encrypted at rest | private key storage ต้องมี `ENCRYPTION_KEY`; ระบบ reject ค่าอ่อนหรือ placeholder |
| `credentials/gmail_{user_id}.json` | encrypted at rest | เป็น Gmail token file ของแต่ละ user และ migrate จาก plaintext legacy ได้ |
| `credentials.json` | encrypted-at-rest managed storage | เป็น app-level Google OAuth client secret; runtime จะ decrypt ใน memory แล้วใช้ `from_client_config(...)` |
| work email credentials ที่เก็บผ่าน `/setkey` | encrypted at rest | ครอบคลุม `work_imap_host`, `work_imap_user`, `work_imap_password` |
| `user_locations.latitude`, `user_locations.longitude` | plaintext แต่มี consent และ TTL | เป็น operational data ที่ใช้ consent, cleanup และ manual delete เป็น mitigation หลัก |
| `chat_history.content` และ `conversations.title` | plaintext แต่มี consent และ retention | เป็นข้อมูลแอปปริมาณสูง จัดการผ่าน consent gate, retention และ purge semantics |
| `users.telegram_chat_id` | plaintext operational identifier | ต้องคง plaintext เพราะเป็น lookup หลักของ Telegram flow |
| Tool logs | minimized structured metadata | flow ใหม่เก็บเฉพาะ kind, fingerprint hash และ size แทน raw input/output text; retention cleanup ยังใช้อยู่ |
| Processed email metadata | minimized เหลือเฉพาะ message ID และ has-subject flag | ไม่เก็บ subject, sender address หรือ sender domain แล้ว; เก็บเฉพาะ message ID สำหรับ dedup และ boolean has-subject flag |

## Shared Keys กับ Per-User Secrets

OpenMiniCrew รองรับ credentials 2 รูปแบบ

1. shared environment keys ใน `.env`
2. per-user private keys ที่ผู้ใช้บันทึกผ่าน `/setkey`

shared keys ใช้กับบริการเช่น

- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `GOOGLE_MAPS_API_KEY`
- `TAVILY_API_KEY`
- `TMD_API_KEY`

บริการที่เป็น private-only แบบรายผู้ใช้ ได้แก่

- `gmail`
- `calendar`
- `work_imap_host`
- `work_imap_user`
- `work_imap_password`

ข้อสังเกตด้าน security:

- private key storage ต้องมี `ENCRYPTION_KEY`
- `/setkey` จะปฏิเสธ secret ที่ดูเป็น placeholder หรืออ่อนเกินไป
- API key rotation ใน rollout ปัจจุบันยังเป็น advisory only ยังไม่ block key อัตโนมัติ

## Retention และ Cleanup

การควบคุม retention ปัจจุบันอาศัย scheduled cleanup และ user-triggered deletion เป็นหลัก

ค่า retention ที่ operator มองเห็นได้ ได้แก่

- chat history retention: `CHAT_HISTORY_RETENTION_DAYS`
- tool log retention: `TOOL_LOG_RETENTION_DAYS`
- email metadata retention: `EMAIL_LOG_RETENTION_DAYS`
- pending message retention: `PENDING_MSG_RETENTION_DAYS`
- job run retention: `JOB_RUN_RETENTION_DAYS`
- location TTL: `LOCATION_TTL_MINUTES`

ความหมายเชิงปฏิบัติ:

- location อาจหมดอายุอัตโนมัติได้ตาม TTL
- chat history และ operational records ไม่ได้ถูกเก็บตลอดไปโดย default
- ผู้ใช้ยังสามารถ revoke consent หรือสั่ง hard purge เองได้

## ความหมายของ Revoke, Delete และ Purge

แต่ละ action มีความหมายต่างกันโดยตั้งใจ

| Action | ความหมาย | สิ่งที่ไม่ได้หมายความว่า |
| --- | --- | --- |
| Deactivate user | ปิดสถานะบัญชีจากมุมมอง operator | ไม่ใช่ hard purge ของข้อมูลทั้งหมด |
| `/disconnectgmail` | ยกเลิก Gmail authorization state และลบ Gmail token file ถ้ามี | ไม่ได้ purge ข้อมูลอื่นทั้งหมดของ user |
| `/consent location off` | ถอน consent ของ location และลบ location ที่เก็บอยู่ | ไม่ได้ purge ข้อมูลอื่น |
| `/consent chat off` | ถอน consent ของ chat history, หยุดบันทึกต่อ, และลบ chat history กับ conversations เดิม | ไม่ได้ purge reminders, todos, expenses หรือ API keys |
| `/delete_my_data confirm` | hard-purge ข้อมูลที่ผูกกับ user ข้ามหลายตาราง และลบ Gmail token file | เป็นคำสั่งฝั่งผู้ใช้ที่ purge ได้ครบที่สุดในตอนนี้ |

ปัจจุบัน hard purge ครอบคลุมอย่างน้อย

- `users`
- `chat_history`
- `conversations`
- `processed_emails`
- `tool_logs`
- `reminders`
- `todos`
- `expenses`
- `user_locations`
- `oauth_states`
- `user_consents`
- `user_api_keys`
- `pending_messages`
- `schedules`
- `job_runs` ของ schedules ที่เป็นของ user นั้น
- Gmail token file ใต้ `credentials/gmail_{user_id}.json`

## Gmail และ Google OAuth Security

integration ของ Gmail และ Calendar ใช้ secret อยู่ 2 ชั้น

1. app-level OAuth client secret ใน `credentials.json`
2. per-user OAuth token files ใน `credentials/gmail_{user_id}.json`

การออกแบบปัจจุบัน:

- app-level client secret ถูกเก็บเป็น managed file แบบ encrypted-at-rest เมื่อมี `ENCRYPTION_KEY`
- ถ้ายังมี `credentials.json` แบบ plaintext รุ่นเก่า ระบบสามารถ auto-migrate ตอนใช้งานครั้งแรกได้
- operator ควร import OAuth client JSON แบบ plaintext ใหม่ผ่าน `python main.py --import-gmail-client-secrets /path/to/downloaded.json`
- Gmail token file ของแต่ละ user ถูกเก็บแบบ encrypted-at-rest และรองรับ migration จาก plaintext legacy
- ระบบพยายามตั้ง file permissions ให้เหมาะสมกับ managed files ด้วย

## Logging และ Minimization

ระบบกำลังขยับออกจากการเก็บ raw sensitive payload ใน operational logs ให้มากที่สุด

แนวทางปัจจุบัน:

- ใช้ structured log fields เช่น kind, reference hash และ payload size แทน raw text เมื่อทำได้
- processed email storage ถูก minimize เหลือเฉพาะ message ID สำหรับ dedup และ boolean has-subject flag เท่านั้น ไม่เก็บ subject, sender address หรือ sender domain อีกต่อไป
- ใช้ safe error fields และ minimized log fields แทนการเก็บ input/output ดิบ

สิ่งนี้ไม่ได้แปลว่าไม่มี operational data ที่อาจอ่อนไหวเลย แต่หมายถึงแนวทางหลักของระบบคือเก็บให้น้อยลงเมื่อ feature ไม่จำเป็นต้องใช้ payload เต็ม

## ข้อจำกัดที่ยังมีอยู่

rollout ปัจจุบันยังมีข้อจำกัดสำคัญ เช่น

- location data ยังเก็บแบบ plaintext ใน application database โดยใช้ consent, TTL และ delete controls เป็น mitigation หลัก
- chat history ยังเป็น plaintext ใน application database เมื่อผู้ใช้เปิด consent ไว้
- `telegram_chat_id` ยังเป็น plaintext เพราะจำเป็นต่อ Telegram routing และ lookup ปกติของระบบ
- API key rotation ยังเป็น advisory only
- operator ยังต้องรับผิดชอบเรื่องการป้องกัน host, backup, `.env` และ deployment environment เอง

## หน้าที่ของ Operator

operator ควรถือสิ่งต่อไปนี้เป็น operational control ขั้นพื้นฐาน

1. อย่าให้ `.env`, database files และ credential files หลุดเข้า version control
2. ตั้ง `ENCRYPTION_KEY` ก่อนเปิดใช้ private key storage หรือ Gmail secret import
3. ใช้ import flow สำหรับ Gmail client secrets แทนการแก้ managed file ด้วยมือ
4. ป้องกัน deployment host, filesystem permissions และ backups ให้เหมาะสม
5. ใช้ `/privacy`, `/mykeys` และ `/health` เป็นส่วนหนึ่งของการตรวจสอบระบบ
6. ถ้าผู้ใช้ขอลบข้อมูลทั้งหมด ให้ใช้ hard purge ไม่ใช่อาศัย deactivate อย่างเดียว

## สรุป

OpenMiniCrew ใช้โมเดลแบบผสมในปัจจุบัน ได้แก่

- encryption สำหรับ secrets และ direct identifiers ที่เสี่ยงสูง
- explicit consent สำหรับ Gmail, location และ chat history
- retention และ purge flows สำหรับ operational data
- minimization สำหรับ logs และ processed email metadata

แนวทางนี้ตั้งใจให้ pragmatic คือปกป้องข้อมูลที่เสี่ยงสูงก่อน โดยยังรักษา Telegram routing, chat workflows และการทำงานของ tools ภายใต้สถาปัตยกรรมปัจจุบันไว้ได้
