"""Dispatcher — ตัดสินใจว่าจะ route message ไปที่ไหน
   - /command → tool ตรง (ไม่เสีย token)
   - ข้อความอิสระ → LLM Router → function calling → tool
   - general chat → LLM ตอบตรง
"""

import asyncio
from core.llm import llm_router
from core.memory import save_user_message, save_assistant_message, get_context
from core.user_manager import get_preference, set_preference, is_owner
from core import db
from tools.registry import registry
from interfaces.telegram_common import parse_command
from core.logger import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = (
    "คุณเป็นผู้ช่วยส่วนตัว ชื่อ OpenMiniCrew ตอบเป็นภาษาไทย กระชับ ได้ใจความ "
    "ถ้า user ต้องการทำงานที่ตรงกับ tool ที่มี ให้เรียกใช้ tool นั้น "
    "ถ้าไม่ตรงกับ tool ไหน ให้ตอบคำถามทั่วไปตามความรู้ของคุณ "
    "สำหรับคำถามเกี่ยวกับการจัดการผู้ใช้ เช่น ดูรายชื่อ user, เพิ่ม/ลบ user "
    "ให้แนะนำให้ใช้คำสั่งโดยตรง: /listusers, /adduser <chat_id> [ชื่อ], /removeuser <chat_id> "
    "สำคัญ: เมื่อ user ขอข้อมูลจาก tool (อีเมล, แผนที่, ข่าว ฯลฯ) "
    "ให้เรียก tool เสมอ — อย่าตอบจากประวัติการสนทนาเก่า เพราะข้อมูลอาจล้าสมัยหรือผิดพลาด"
)


async def dispatch(user_id: str, user: dict, text: str) -> str:
    """
    ตัดสินใจ route message → return ข้อความที่จะส่งกลับ user

    Returns:
        (response_text, tool_used, llm_model, token_used)
    """
    command, args = parse_command(text)

    # ---- /help ----
    if command == "/help":
        return registry.get_help_text(), None, None, 0

    # ---- /model ----
    if command == "/model":
        return _handle_model_command(user_id, args), None, None, 0

    # ---- /adduser — owner only ----
    if command == "/adduser":
        if not is_owner(user):
            return "❌ คำสั่งนี้ใช้ได้เฉพาะ owner", None, None, 0
        parts = args.strip().split(None, 1)
        if not parts:
            return "❌ ใช้: /adduser <chat_id> [ชื่อ]", None, None, 0
        new_chat_id = parts[0]
        display_name = parts[1] if len(parts) > 1 else new_chat_id
        db.upsert_user(new_chat_id, new_chat_id, display_name)
        log.info(f"Owner {user_id} added user: {new_chat_id} ({display_name})")
        return f"✅ เพิ่มผู้ใช้ *{display_name}* (chat\\_id: `{new_chat_id}`) แล้ว", None, None, 0

    # ---- /removeuser — owner only ----
    if command == "/removeuser":
        if not is_owner(user):
            return "❌ คำสั่งนี้ใช้ได้เฉพาะ owner", None, None, 0
        target_id = args.strip()
        if not target_id:
            return "❌ ใช้: /removeuser <chat_id>", None, None, 0
        db.deactivate_user(target_id)
        log.info(f"Owner {user_id} deactivated: {target_id}")
        return f"✅ ปิดการใช้งาน chat\\_id: `{target_id}` แล้ว", None, None, 0

    # ---- /listusers — owner only ----
    if command == "/listusers":
        if not is_owner(user):
            return "❌ คำสั่งนี้ใช้ได้เฉพาะ owner", None, None, 0
        users = db.get_all_users()
        lines = [f"👥 *ผู้ใช้ทั้งหมด ({len(users)} คน):*\n"]
        for u in users:
            status = "✅" if u["is_active"] else "❌"
            lines.append(f"{status} {u['display_name']} — `{u['telegram_chat_id']}` ({u['role']})")
        return "\n".join(lines), None, None, 0

    # ---- /authgmail — authorize Gmail สำหรับ user นี้ ----
    if command == "/authgmail":
        from core.gmail_oauth import generate_auth_url
        from core.config import WEBHOOK_HOST
        if not WEBHOOK_HOST:
            return (
                "❌ ต้องตั้งค่า `WEBHOOK_HOST` ใน .env ก่อน\n"
                "เช่น: `WEBHOOK_HOST=https://yourdomain.com`"
            ), None, None, 0
        url = generate_auth_url(user_id, user["telegram_chat_id"])
        if not url:
            return "❌ ยังไม่ได้ตั้งค่า `credentials.json` (Google OAuth client)", None, None, 0
        return (
            "🔐 *Authorize Gmail*\n\n"
            f"คลิกลิงก์นี้เพื่อ authorize Gmail ของคุณ:\n{url}\n\n"
            "⏱ ลิงก์หมดอายุใน 15 นาที\n\n"
            "_หลัง authorize แล้ว bot จะแจ้งให้ทราบอัตโนมัติ_"
        ), None, None, 0

    # ---- Direct command → tool (ไม่เสีย LLM token) ----
    tool = registry.get_by_command(command) if command else None
    if tool:
        log.info(f"Direct command: {command} → {tool.name}")
        try:
            result = await tool.execute(user_id, args)
            return result, tool.name, None, 0
        except Exception as e:
            log.error(f"Tool {tool.name} failed: {e}")
            db.log_tool_usage(user_id, tool.name, status="failed", error_message=str(e))
            return f"เกิดข้อผิดพลาด: {e}\nกรุณาลองใหม่", tool.name, None, 0

    # ---- ข้อความอิสระ → LLM Router ----
    provider = get_preference(user, "default_llm")
    context = get_context(user_id)
    context.append({"role": "user", "content": text})

    tool_specs = registry.get_all_specs()

    try:
        # Step 1: ถาม LLM ว่าจะเรียก tool ไหน หรือตอบเอง
        resp = await llm_router.chat(
            messages=context,
            provider=provider,
            tier="cheap",
            system=SYSTEM_PROMPT,
            tools=tool_specs if tool_specs else None,
        )

        # Step 2: ถ้า LLM เลือก tool → เรียก tool แล้วส่งผลกลับให้ LLM สรุป
        if resp["tool_call"]:
            tool_name = resp["tool_call"]["name"]
            tool_args = resp["tool_call"].get("args", {})
            selected_tool = registry.get_tool(tool_name)

            if selected_tool:
                log.info(f"LLM selected tool: {tool_name}")
                try:
                    tool_result = await selected_tool.execute(user_id, **tool_args)

                    # direct_output=True → ส่งผลลัพธ์ตรงๆ (ไม่ผ่าน LLM ซ้ำ)
                    if selected_tool.direct_output:
                        return (
                            tool_result,
                            tool_name,
                            resp["model"],
                            resp["token_used"],
                        )

                    # direct_output=False → ส่งผลลัพธ์ให้ LLM สรุปเป็นภาษาธรรมชาติ
                    summary_messages = context + [
                        {"role": "assistant", "content": f"[เรียก {tool_name}]"},
                        {"role": "user", "content": (
                            f"ผลลัพธ์จาก {tool_name}:\n{tool_result}\n\n"
                            "ช่วยสรุปให้ user เข้าใจง่าย "
                            "ถ้ามี URL หรือลิงก์ ให้เก็บไว้ครบทุกอัน อย่าตัดออก"
                        )},
                    ]

                    summary = await llm_router.chat(
                        messages=summary_messages,
                        provider=provider,
                        tier="cheap",
                        system=SYSTEM_PROMPT,
                    )

                    total_tokens = resp["token_used"] + summary["token_used"]
                    return (
                        summary["content"],
                        tool_name,
                        summary["model"],
                        total_tokens,
                    )

                except Exception as e:
                    log.error(f"Tool {tool_name} execution failed: {e}")
                    db.log_tool_usage(user_id, tool_name, status="failed",
                                      error_message=str(e))
                    return f"เรียก {tool_name} ไม่สำเร็จ: {e}", tool_name, resp["model"], resp["token_used"]
            else:
                log.warning(f"LLM selected unknown tool: {tool_name}")

        # Step 3: ไม่ได้เรียก tool → ใช้ text response ตรง
        return resp["content"], None, resp["model"], resp["token_used"]

    except Exception as e:
        log.error(f"LLM dispatch failed: {e}")
        return f"เกิดข้อผิดพลาดในการประมวลผล: {e}\nกรุณาลองใหม่", None, None, 0


def _handle_model_command(user_id: str, args: str) -> str:
    from core.llm import llm_router

    available = llm_router.get_available_providers()
    args = args.strip().lower()

    if not args:
        # แสดงรายการ providers ที่ใช้ได้
        lines = ["🧠 LLM ที่ใช้ได้:\n"]
        for name in available:
            lines.append(f"  ✅ {name}")
        lines.append(f"\nใช้: /model [ชื่อ] เช่น /model {available[0]}" if available else "\n❌ ไม่มี LLM ที่ตั้งค่าไว้")
        return "\n".join(lines)

    if args not in available:
        return f"❌ ใช้ {args} ไม่ได้ — ยังไม่ได้ตั้งค่า API key\n✅ ใช้ได้: {', '.join(available)}"

    set_preference(user_id, "default_llm", args)
    return f"✅ เปลี่ยน LLM เป็น {args} เรียบร้อย"


async def process_message(user_id: str, user: dict, chat_id: str | int, text: str):
    """
    Full pipeline: dispatch + save memory + send Telegram
    เรียกจากทั้ง polling และ webhook
    """
    from interfaces.telegram_common import send_message, TypingIndicator

    with TypingIndicator(chat_id):
        save_user_message(user_id, text)

        result = await dispatch(user_id, user, text)

        if isinstance(result, tuple):
            response_text, tool_used, llm_model, token_used = result
        else:
            response_text, tool_used, llm_model, token_used = result, None, None, 0

        # บันทึก memory
        save_assistant_message(
            user_id, response_text,
            tool_used=tool_used, llm_model=llm_model,
            token_used=token_used,
        )

    # ส่งกลับ Telegram (หลัง typing หยุด)
    send_message(chat_id, response_text)
