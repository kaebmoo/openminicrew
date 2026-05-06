# Prompts Directory

Prompt templates ทั้งหมดของ openminicrew อยู่ที่นี่ — แก้ markdown ไม่ต้อง redeploy bot

## โครงสร้าง

- `system/` — System prompt หลัก ใส่ใน LLM ทุก call
  - `base.md` — โครงหลัก compose จาก section อื่น
  - `tool_routing.md` — กฎการเลือก tool
  - `anti_hallucination.md` — ห้ามแต่งผลลัพธ์ tool
  - `privacy.md` — prompt injection guard
- `tools/` — Tool routing descriptions (1 ไฟล์ต่อ tool)
  - body = description ของ tool (positive + negative boundary + examples)
  - frontmatter `parameters_args:` (block scalar) = description ของ args parameter
  - frontmatter `args_required: false` = ถ้า args เป็น optional (default required)
- `internal/` — Prompts ที่ tool เรียก LLM ภายใน
  - `expense_vision_extract.md` — Gemini Vision สำหรับใบเสร็จ
  - `smart_inbox_action_items.md` — สกัด action items จากอีเมล

## วิธีแก้ prompt

1. แก้ไฟล์ใน `prompts/` ที่ต้องการ
2. **Production:** restart bot — `systemctl restart openminicrew`
3. **Dev mode:** ตั้ง `PROMPT_HOT_RELOAD=1` ใน `.env` → bot reload prompt อัตโนมัติเมื่อไฟล์เปลี่ยน

## Template variables

ใช้ `{variable_name}` syntax (Python `str.format()`)

ถ้าต้องการ literal `{` หรือ `}` ใน text (เช่น JSON ใน prompt) ใช้ `{{` กับ `}}`

ตัวอย่าง:
```markdown
{{"key": "value", "user": "{user_name}"}}
```
จะ render เป็น `{"key": "value", "user": "Alice"}` เมื่อ `user_name="Alice"`

## YAML frontmatter (optional)

```markdown
---
name: my-tool
description: short single-line description
parameters_args: |
  multi-line value
  รองรับ block scalar (|) สำหรับ value ยาว ๆ
args_required: false
---
Body content here (อ่านด้วย load_prompt())
```

อ่าน frontmatter ด้วย `load_metadata("path/to/file.md")`

## Validation

`core.prompt_loader.validate_all_prompts()` รันตอน startup ใน `main.py`

ถ้า prompt มี syntax error (เช่น `{` ไม่ปิด) → bot crash พร้อม error message
ถ้า template variable ไม่ตรงกับ default dummies → warning log (ไม่ block startup)

Default dummies ที่ครอบคลุม: `date`, `year`, `buddhist_year`, `today`, `user_name`, `tool_name`

## วิธีเพิ่ม prompt ใหม่

1. สร้างไฟล์ markdown ใน subdirectory ที่เหมาะสม (`system/`, `tools/`, `internal/`, หรือสร้างใหม่)
2. ใน Python ใช้ `load_prompt("relative/path.md", **vars)`
3. ถ้ามี template variable ใหม่ที่ไม่อยู่ใน default dummies — เพิ่ม dummy ใน `validate_all_prompts(dummy_vars=...)` argument ตอนเรียกที่ `main.py`

## Related plans

- `plan/plan-prompt-system-and-self-improvement.md` — master plan (5 phases)
- `plan/plan-prompt-externalization.md` — Phase 1 (ไฟล์นี้)
- ในอนาคต: Phase 2 Skills จะใช้ prompt_loader เดียวกัน
