---
parameters_args: |
  รูปแบบ: '<consent_type> <action>' consent_type: chat | location | gmail action: on | off | status เช่น 'chat on', 'location off', 'chat status' ถ้าไม่ระบุ args หรือแค่ 'status' จะแสดงสถานะทั้งหมด
---
จัดการ consent/ความยินยอมของผู้ใช้ เปิด-ปิดการเก็บข้อมูล. ใช้เมื่อ user พูดเกี่ยวกับการอนุญาต/ยกเลิกการเก็บข้อมูล. เช่น 'เปิดยินยอมบันทึกการสนทนา', 'ปิดเก็บตำแหน่ง', 'ยกเลิกการยินยอมบันทึกการสนทนา', 'ดูสถานะ consent'. consent ที่มี: chat (ประวัติสนทนา), location (ตำแหน่ง GPS), gmail (อีเมล)
