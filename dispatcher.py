"""Dispatcher — ตัดสินใจว่าจะ route message ไปที่ไหน
   - /command → tool ตรง (ไม่เสีย token)
   - ข้อความอิสระ → LLM Router → function calling → tool
   - general chat → LLM ตอบตรง
"""

import asyncio
from core.llm import llm_router
from core.memory import save_user_message, save_assistant_message, get_context
from core.user_manager import get_preference, set_preference
from core import db
from tools.registry import registry
from interfaces.telegram_common import parse_command
from core.logger import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = (
    "คุณเป็นผู้ช่วยส่วนตัว ชื่อ OpenMiniCrew ตอบเป็นภาษาไทย กระชับ ได้ใจความ "
    "ถ้า user ต้องการทำงานที่ตรงกับ tool ที่มี ให้เรียกใช้ tool นั้น "
    "ถ้าไม่ตรงกับ tool ไหน ให้ตอบคำถามทั่วไปตามความรู้ของคุณ"
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
                    raw_args = tool_args.get("args", "")
                    if not isinstance(raw_args, str):
                        raw_args = str(raw_args)
                    tool_result = await selected_tool.execute(user_id, raw_args)

                    # ส่งผลลัพธ์ tool กลับให้ LLM สรุปเป็นภาษาธรรมชาติ
                    summary_messages = context + [
                        {"role": "assistant", "content": f"[เรียก {tool_name}]"},
                        {"role": "user", "content": f"ผลลัพธ์จาก {tool_name}:\n{tool_result}\n\nช่วยสรุปให้ user เข้าใจง่าย"},
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
