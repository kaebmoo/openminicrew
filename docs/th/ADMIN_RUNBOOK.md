# คู่มือปฏิบัติการสำหรับผู้ดูแลระบบ (Admin Operations Runbook)

> English version: [Admin Operations Runbook](../en/ADMIN_RUNBOOK.md)

เอกสารนี้สำหรับผู้ดูแลระบบที่ดูแล OpenMiniCrew ใน production โดยเน้นขั้นตอนปฏิบัติจริงด้าน privacy/security, incident response และ key management

## 1. ขอบเขตและผู้ใช้งานเอกสาร

ใช้เอกสารนี้เมื่อคุณรับผิดชอบงานต่อไปนี้:

- จัดการความลับของระบบและไฟล์ `.env`
- หมุนคีย์เข้ารหัสและ OAuth client secrets
- จัดการคำขอลบข้อมูลของผู้ใช้
- ตรวจสอบเหตุการณ์ผิดปกติหรือสงสัยข้อมูลรั่วไหล
- ตรวจสอบสุขภาพระบบหลังเปลี่ยนค่า sensitive

## 2. ไฟล์สำคัญและตำแหน่งข้อมูล

- ฐานข้อมูลหลัก: `data/openminicrew.db` (หรือค่าที่ตั้งผ่าน `DB_PATH`)
- App-level OAuth client secret: `credentials.json` (จัดเก็บแบบ encrypted-at-rest เมื่อเปิดใช้งาน)
- Gmail token รายผู้ใช้: `credentials/gmail_{user_id}.json`
- Runtime secret config: `.env`

ให้ถือว่าทุกไฟล์ด้านบนเป็นข้อมูลอ่อนไหวแบบ data-at-rest

## 3. Preflight Checks ก่อนทำงานที่กระทบข้อมูลอ่อนไหว

1. ตรวจสุขภาพระบบก่อน:
   - `GET /health` (กรณี webhook mode)
   - หรือทดสอบผ่าน Telegram เช่น `/privacy`, `/mykeys`
2. ยืนยันว่า `ENCRYPTION_KEY` ถูกตั้งค่าและใช้งานได้
3. ยืนยันว่ามี backup ล่าสุดและมีแผน restore ที่ทดสอบได้
4. หากงานอาจกระทบผู้ใช้ ให้แจ้ง maintenance window ล่วงหน้า

## 4. งานตรวจสอบประจำวัน/ประจำสัปดาห์

งานประจำวัน:

1. ตรวจสถานะ `/health` และ readiness warnings
2. ตรวจ `/mykeys` เพื่อดู advisory เรื่อง key rotation
3. ดู log ว่ามี auth fail/decrypt warning/OAuth error ผิดปกติหรือไม่

งานประจำสัปดาห์:

1. ตรวจว่า cleanup jobs และ scheduler heartbeat ยังทำงาน
2. ตรวจแนวโน้ม event ใน `security_audit_logs`
3. ตรวจสิทธิ์ไฟล์ของ `credentials.json` และโฟลเดอร์ `credentials/`

## 5. ขั้นตอนหมุนคีย์เข้ารหัส (ENCRYPTION_KEY Rotation)

ใช้เมื่อมีการเปลี่ยน `ENCRYPTION_KEY`

1. สร้าง Fernet key ใหม่ แล้วตั้งเป็น `ENCRYPTION_KEY`
2. ย้ายคีย์เดิมไป `ENCRYPTION_KEY_PREVIOUS` หรือเพิ่มใน `ENCRYPTION_KEY_PREVIOUS_LIST`
3. สั่ง re-encrypt ข้อมูล:

```bash
python main.py --rotate-encryption
```

4. ตรวจสอบผล:
   - `/health` ไม่อยู่สถานะ fail
   - `/mykeys` อ่าน private keys ได้
   - ฟีเจอร์ Gmail/OAuth ยังใช้งานได้กับบัญชีทดสอบอย่างน้อย 1 ราย
5. เมื่อระบบนิ่งแล้ว ค่อยถอด previous keys ออกจาก env

หมายเหตุ rollback:

- หากพบ decryption error ให้คืนคีย์เดิมใน previous-key env ก่อน แล้วทดสอบซ้ำ

## 6. ขั้นตอนหมุน Gmail OAuth Client Secret

1. ดาวน์โหลด OAuth client JSON ชุดใหม่จาก Google Cloud Console
2. import ผ่านคำสั่งระบบเท่านั้น (ห้ามแก้ไฟล์ managed โดยตรง):

```bash
python main.py --import-gmail-client-secrets /path/to/downloaded.json
```

3. ทดสอบ flow เชื่อม Gmail หรือ OAuth และตรวจ log
4. ลบไฟล์ plaintext ชั่วคราวบนเครื่องแอดมินอย่างปลอดภัย

## 7. การลบข้อมูลผู้ใช้และคำขอด้าน Privacy

สำหรับการลบข้อมูลแบบครบ ให้ผู้ใช้ใช้คำสั่ง:

- `/delete_my_data confirm`

Checklist หลังทำงาน:

1. ยืนยันว่าผู้ใช้ได้รับข้อความสำเร็จ
2. ยืนยันว่าข้อมูลผู้ใช้ถูกลบจากตารางที่เกี่ยวข้อง
3. ยืนยันว่า `credentials/gmail_{user_id}.json` ถูกลบ (ถ้ามี)
4. ยืนยันว่ามี audit event ใน `security_audit_logs`

หมายเหตุด้าน governance:

- `security_audit_logs` ถูกเก็บต่อโดยตั้งใจในขั้นตอน hard purge ไม่ใช่ช่องโหว่ของการลบข้อมูล

ข้อควรจำ:

- การ deactivate อย่างเดียวไม่ใช่ hard purge
- backup/export ภายนอกระบบหลักอาจยังเก็บข้อมูลเดิม

## 8. Incident Response (สงสัยข้อมูลรั่วไหล)

1. Contain: จำกัดสิทธิ์การเข้าถึง และหยุด automation ที่ไม่จำเป็น
2. Assess: ตรวจ `security_audit_logs`, app logs และ infra logs เพื่อประเมินขอบเขต
3. Revoke: ยกเลิก OAuth และถอนคีย์ที่อาจรั่ว
4. Rotate: หมุนคีย์เข้ารหัสและ/หรือ OAuth client secret ตามความเสี่ยง
5. Eradicate/Recover: purge ข้อมูลที่เกี่ยวข้องและกู้บริการกลับ
6. Post-incident review: บันทึก root cause, impact และแผนป้องกันซ้ำ

## 9. การจัดการ Backup และ Export

1. เข้ารหัสที่เก็บ backup/export ทุกชุด
2. จำกัดสิทธิ์เข้าถึงตามหลัก least privilege
3. ตั้ง retention/deletion schedule ให้ backup/export ด้วย
4. ทดสอบขั้นตอน restore เป็นรอบ

การ hard purge ในฐานข้อมูลหลักยังไม่ถือว่าเสร็จเชิงนโยบาย หากยังไม่มีการจัดการสำเนา backup/export ภายนอก

## 10. คำสั่งอ้างอิงสำหรับผู้ดูแลระบบ

คำสั่งที่ใช้บ่อย:

```bash
python main.py --rotate-encryption
python main.py --import-gmail-client-secrets /path/to/client_secret.json
python main.py --auth-gmail <chat_id>
python main.py --list-gmail
python main.py --revoke-gmail <chat_id>
```

คำสั่งตรวจสอบในแชต:

- `/privacy`
- `/mykeys`
- `/health` (webhook endpoint)

## 11. งานกำกับเอกสารและความเป็นเจ้าของ

แนะนำให้บันทึก metadata ในกระบวนการปฏิบัติการ:

- เจ้าของเอกสาร/ทีมรับผิดชอบ
- วันที่ review ล่าสุด
- วันที่หมุนคีย์ล่าสุดที่สำเร็จ
- วันที่ซ้อม incident ล่าสุด
