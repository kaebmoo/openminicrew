
## 🚀 **ลำดับการทำงาน OpenMiniCrew — ตั้งแต่ start ถึง user message**

### **Phase 1: Startup (main.py)**

```
python main.py
    ↓
[1/6] init_db()
      ↳ สร้างตาราง: users, chats, tool_logs, message_history ใน SQLite
      
[2/6] init_owner()
      ↳ ตรวจสอบว่า owner (OWNER_TELEGRAM_CHAT_ID) อยู่ใน DB หรือยัง
      ↳ ถ้ายัง → insert owner user ใหม่
      
[3/6] _ensure_gmail_auth()
      ↳ ตรวจสอบว่า owner มี Gmail token ที่ valid หรือยัง
      ↳ ถ้ายัง → เปิด browser เพื่อ OAuth ด้วย authorize_gmail_interactive()
      
[4/6] registry.discover()
      ↳ auto-discover tools ทั้งหมด จาก tools/ folder
      ↳ แต่ละ tool class ต้องมี: name, description, command, execute()
      ↳ บันทึกลงใน registry.tools dictionary
      
[5/6] init_scheduler()
      ↳ เริ่ม background scheduler (สำหรับ email polling, etc)
      
[6/6] start_bot()
      ↳ BOT_MODE = "webhook" or "polling"
      ↳ webhook: เปิด Flask server รับ POST จาก Telegram
      ↳ polling: เข้าลูป getUpdates() แบบ long-polling
```

---

### **Phase 2: Telegram Message Arrives (telegram_polling.py / telegram_webhook.py)**

```
Telegram message comes in
    ↓
telegram_polling.py:
  _handle_update(update)
    ↓ extract:
      - user_id (chat_id)
      - text (message content)
      - chat_id (สำหรับส่งกลับ)
    ↓
lookup user from DB:
  user = get_user(user_id)
    ↓
  if user exists and is_active:
    ↓
    process_message(user_id, user, chat_id, text)
    
    else: reject message (user ยังไม่ได้ authorize)
```

---

### **Phase 3: Main Processing (dispatcher.py::process_message)**

```
process_message(user_id, user, chat_id, text):

  [Step 1] Deduplication
    ↳ request_dedup.is_duplicate(user_id, text)
    ↳ ถ้าซ้ำภายใน 5 วินาที → skip
    
  [Step 2] Rate Limiting
    ↳ user_rate_limiter.allow(user_id)
    ↳ ถ้าเกิน 10 msg/นาที → ส่ง "ส่งข้อความเร็วเกินไป"
    
  [Step 3] Dispatch (ตัดสินใจ route)
    ↳ save_user_message(user_id, text)  ← บันทึก memory ก่อน
    ↳ response_text, tool_used, llm_model, token_used = 
        await dispatch(user_id, user, text)
        
  [Step 4] Save Memory
    ↳ save_assistant_message(user_id, response_text, ...)
    
  [Step 5] Send to Telegram
    ↳ send_message(chat_id, response_text)
```

---

### **Phase 4: Dispatch Logic (dispatcher.py::dispatch) ⭐ ← ที่สำคัญที่สุด**

```
dispatch(user_id, user, text):

  ┌─ Step 1: Parse command
  │  command, args = parse_command(text)
  │  เช่น "/help" → command="/help", args=""
  │      "/traffic ถนนสุขุมวิท" → command="/traffic", args="ถนนสุขุมวิท"
  │      "สวัสดี" → command=None, args=None
  │
  ├─ Step 2: Built-in commands (ไม่เสีย LLM token)
  │  if command == "/help":
  │    return registry.get_help_text()
  │
  │  if command == "/model":
  │    return _handle_model_command()  ← switch LLM provider
  │
  │  if command == "/adduser", "/removeuser", "/listusers":
  │    if is_owner(user):  ← เชค role=="owner" เท่านั้น
  │      return db.upsert_user() / db.deactivate_user() / db.get_all_users()
  │    else:
  │      return "❌ owner only"
  │
  │  if command == "/authgmail":
  │    return generate_auth_url() for Google OAuth
  │
  ├─ Step 3: Direct command → Tool (ไม่เสีย LLM token)
  │  tool = registry.get_by_command(command)
  │  if tool:
  │    result = await tool.execute(user_id, args)
  │    save to tool_logs
  │    return result
  │
  └─ Step 4: Free text → LLM Router (เสีย token) 🎯
      provider = get_preference(user, "default_llm")  ← get user's choice
      context = get_context(user_id)  ← pull from message_history
      context.append({"role": "user", "content": text})
      
      tool_specs = registry.get_all_specs()  ← get tool definitions
      
      ┌─ Step 4a: First LLM call (decide tool or direct answer?)
      │ resp = await llm_router.chat(
      │   messages=context,
      │   provider=provider,          ← "claude" or "gemini"
      │   tier="cheap",               ← pick smaller model (faster, cheaper)
      │   system=SYSTEM_PROMPT,       ← ระบุคำสั่ง: ไทย, ใช้ tools, etc
      │   tools=tool_specs            ← ส่ง tool definitions ให้ LLM เลือก
      │ )
      │
      │ Returns: {
      │   "content": "str",
      │   "tool_call": {"name": "tool_name", "args": {...}} or None,
      │   "model": "claude-3.5-sonnet",
      │   "token_used": 1500
      │ }
      │
      ├─ Step 4b: LLM decided to call tool?
      │ if resp["tool_call"]:
      │    tool_name = resp["tool_call"]["name"]
      │    tool_args = resp["tool_call"]["args"]
      │    selected_tool = registry.get_tool(tool_name)
      │    
      │    try:
      │      tool_result = await selected_tool.execute(user_id, **tool_args)
      │
      │      if selected_tool.direct_output:  ← บางทูล ตอบตรง ไม่ผ่าน LLM
      │        return tool_result
      │
      │      else:  ← ส่วนใหญ่ ต้องสรุปด้วย LLM
      │        ┌─ Step 4c: Second LLM call (summarize tool result)
      │        │ summary = await llm_router.chat(
      │        │   messages=context + [
      │        │     {"role": "assistant", "content": "[เรียก tool_name]"},
      │        │     {"role": "user", "content": f"ผลลัพธ์: {tool_result}\nช่วยสรุป"}
      │        │   ]
      │        │ )
      │        │ 
      │        │ return summary["content"]
      │        └─
      │    except Exception:
      │      log error
      │      return "เรียก tool ไม่สำเร็จ"
      │
      └─ Step 4d: LLM decided to answer directly
          return resp["content"]  ← ตอบเองจาก general knowledge
```

---

## 📊 **Visual Flow Diagram**

```
┌─────────────────────────────────────────────────────────┐
│                    main.py startup                      │
│  [DB] → [Owner] → [Gmail] → [Tools] → [Scheduler] → BOT│
└─────────────────────────────────────────────────────────┘
                          ↓
         ┌────────────────────────────────┐
         │  Telegram Updates (Polling)    │
         │  or (Webhook) POST received    │
         └────────────────────────────────┘
                          ↓
         ┌────────────────────────────────┐
         │  parse_command(text)           │
         │  lookup user from DB           │
         └────────────────────────────────┘
                          ↓
         ┌────────────────────────────────┐
         │  process_message()             │
         │  - dedup check                 │
         │  - rate limit check            │
         │  - save to memory              │
         │  - dispatch(text)              │
         └────────────────────────────────┘
                          ↓
         ┌────────────────────────────────────────────────┐
         │             dispatcher.dispatch()             │
         ├────────────────────────────────────────────────┤
         │                                                │
         │ ┌─ Built-in commands (0 token)               │
         │ │  /help, /model, /adduser, /listusers...    │
         │ │  → return static response                  │
         │ │                                             │
         │ ├─ Direct commands (0 token)                 │
         │ │  /traffic ถนน → tool.execute() → result    │
         │ │                                             │
         │ └─ Free text (LLM router)                    │
         │    ┌─ LLM call #1: decide tool or answer?   │
         │    │  prompt + tools definitions             │
         │    │                                          │
         │    ├─ if tool_call: ┌─ execute tool         │
         │    │                 │                       │
         │    │                 ├─ if direct_output:   │
         │    │                 │  return result        │
         │    │                 │                       │
         │    │                 └─ LLM call #2:        │
         │    │                    summarize result     │
         │    │                    return summary       │
         │    │                                          │
         │    └─ else: answer directly                  │
         │       (no tool called)                       │
         │                                              │
         └────────────────────────────────────────────────┘
                          ↓
         ┌────────────────────────────────┐
         │  save_assistant_message()      │
         │  (บันทึก response ลง memory)    │
         └────────────────────────────────┘
                          ↓
         ┌────────────────────────────────┐
         │  send_message() to Telegram    │
         │  response_text → user          │
         └────────────────────────────────┘
```

---

## 🔑 **Key Points ที่ต้องรู้**

| ส่วนประกอบ | ที่อยู่ | หน้าที่ |
|-----------|-------|--------|
| **main.py** | Root | Entry point, startup 6 steps, handle signal graceful shutdown |
| **dispatcher.py** | Root | Heart of routing logic — เลือกว่า command/tool/LLM ไหน |
| **telegram_polling.py** | `interfaces/` | Long-polling loop, extract message, call `process_message()` |
| **dispatcher::dispatch()** | Main logic | 4 paths: built-in → direct tool → LLM decide tool → LLM answer |
| **llm_router.chat()** | `core/llm.py` | Unified API to Claude & Gemini, auto-fallback |
| **registry** | `tools/registry.py` | Auto-discover tools, provide tool specs to LLM |
| **memory** | `core/memory.py` | Save user messages + responses in `message_history` table |
| **db** | `core/db.py` | SQLite WAL, users, chats, tool_logs, message_history |

---

## 💡 **2 Paths อย่างลึก**

### **Path A: Direct Command (/traffic ถนนสุขุมวิท)**
```
/traffic ถนนสุขุมวิท
    ↓
parse_command() → command="/traffic", args="ถนนสุขุมวิท"
    ↓
tool = registry.get_by_command("/traffic")  ← ค้นหาจาก tools registry
    ↓
tool.execute(user_id, "ถนนสุขุมวิท")  ← เรียก execute() ตรงเลย
    ↓
return result (0 LLM token ใช้)
```

### **Path B: Free Text ("ถนนสุขุมวิท เป็นไง")**
```
"ถนนสุขุมวิท เป็นไง"
    ↓
dispatch() → ไม่มี command prefix
    ↓
LLM call #1:
  system_prompt: "ถ้าเกี่ยวข้องกับ traffic tool ให้เรียกมัน"
  tools: [traffic tool spec, email tool spec, ...]
  message: "ถนนสุขุมวิท เป็นไง"
    ↓
LLM decides: "ควรเรียก traffic tool"
    ↓
tool.execute(user_id, location="ถนนสุขุมวิท")
    ↓
LLM call #2:
  summarize: "ผลลัพธ์ที่ได้: ... ช่วยสรุปเป็นภาษาไทยให้ user"
    ↓
return summary
```

---

