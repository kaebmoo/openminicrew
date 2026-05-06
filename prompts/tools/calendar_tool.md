---
parameters_args: |
  sub-command string. STRICT format:
  • list
  • add YYYY-MM-DD HH:MM HH:MM ชื่องาน  (date MUST be YYYY-MM-DD, time MUST be HH:MM 24h)
    end time optional → default +1 ชม.
    examples: 'add 2026-04-22 14:00 15:00 ประชุมทีม' | 'add 2026-04-22 14:00 Claude Cowork'
  • delete <ลำดับ|event_id>
  IMPORTANT: always convert Thai date/time to YYYY-MM-DD HH:MM before calling.
args_required: false
---
จัดการ Google Calendar (ดู/เพิ่ม/ลบนัดหมาย). ใช้เมื่อ user ถามตารางงาน นัดหมาย หรือให้ลงปฏิทิน. ไม่ใช่สำหรับการจดงาน (ใช้ todo) หรือตั้งเตือนปลุก (ใช้ reminder/schedule). เช่น 'พรุ่งนี้มีนัดไหม', 'ดึงตารางงาน', 'เพิ่มนัดประชุม 10 โมง'
