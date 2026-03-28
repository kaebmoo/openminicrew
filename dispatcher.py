"""Dispatcher — ตัดสินใจว่าจะ route message ไปที่ไหน
   - /command → system handler หรือ tool ตรง (ไม่เสีย token)
   - ข้อความอิสระ → LLM Router → function calling → tool
   - general chat → LLM ตอบตรง
"""

import asyncio
from datetime import date as _date_cls
from core.llm import llm_router
from core.memory import (
    save_user_message, save_assistant_message, get_context,
    ensure_conversation,
)
from core.user_manager import get_preference
from core.concurrency import user_rate_limiter, request_dedup
from core import db
from tools.registry import registry
from core.config import DISPATCH_TIMEOUT
MAX_RETRIES = 3  # จำนวนรอบ retry สูงสุดเมื่อ tool fail หรือ LLM เลือก tool ผิด
from interfaces.telegram_common import parse_command
from core.logger import get_logger

# -- Command handlers (แยกไว้ใน core/) --
from core.system_commands import (
    handle_help, handle_start, handle_model, handle_new, handle_history,
    handle_adduser, handle_removeuser, handle_listusers, handle_authgmail,
    handle_keyaudit,
)
from core.privacy_commands import (
    handle_consent, handle_privacy, handle_delete_my_data,
    handle_disconnectgmail, handle_clearlocation,
)

log = get_logger(__name__)

# command string → async handler(user_id, user, args, **kw) → (text, tool, model, tokens)
SYSTEM_COMMANDS: dict[str, ...] = {
    "/help": handle_help,
    "/consent": handle_consent,
    "/privacy": handle_privacy,
    "/start": handle_start,
    "/model": handle_model,
    "/adduser": handle_adduser,
    "/removeuser": handle_removeuser,
    "/delete_my_data": handle_delete_my_data,
    "/disconnectgmail": handle_disconnectgmail,
    "/clearlocation": handle_clearlocation,
    "/listusers": handle_listusers,
    "/keyaudit": handle_keyaudit,
    "/authgmail": handle_authgmail,
    "/new": handle_new,
    "/history": handle_history,
}


def _build_system_prompt() -> str:
    """สร้าง system prompt พร้อมวันที่ปัจจุบัน — เรียกทุกครั้งเพื่อให้ date ไม่ stale"""
    today = _date_cls.today()
    return (
        f"วันที่ปัจจุบันคือ {today.isoformat()} "
        f"(ค.ศ. {today.year} / พ.ศ. {today.year + 543}) "
        "เมื่อผู้ใช้ระบุวันที่โดยไม่ระบุปี ให้ใช้ปีปัจจุบันเป็นค่าเริ่มต้นเสมอ "
        "คุณเป็นผู้ช่วยส่วนตัว ชื่อ OpenMiniCrew ตอบเป็นภาษาไทย กระชับ ได้ใจความ "
        "ถ้า user ต้องการทำงานที่ตรงกับ tool ที่มี ให้เรียกใช้ tool นั้น "
        "ถ้าไม่ตรงกับ tool ไหน ให้ตอบคำถามทั่วไปตามความรู้ของคุณ "
        "สำหรับคำถามเกี่ยวกับการจัดการผู้ใช้ เช่น ดูรายชื่อ user, เพิ่ม/ลบ user "
        "ให้แนะนำให้ใช้คำสั่งโดยตรง: /listusers, /adduser <chat_id> [ชื่อ], /removeuser <chat_id> "
        "สำหรับการจัดการ consent/ความยินยอม เช่น เปิด-ปิดประวัติสนทนา, อนุญาต-ยกเลิกตำแหน่ง, ดูสถานะ consent "
        "ให้ใช้ consent tool เสมอ ห้ามตอบเองว่าเปิด/ปิดแล้ว ต้องเรียก tool จริงเท่านั้น "
        "สำหรับดูประวัติสนทนา/chat history ให้ใช้ chat_history tool "
        "สำคัญมาก: เมื่อ user ขอข้อมูลจาก tool (อีเมล, แผนที่, ข่าว, อัตราแลกเปลี่ยน, ผลสลากกินแบ่ง หรือ หวย ฯลฯ) "
        "ให้เรียก tool ทันทีเสมอ ห้ามถามกลับหรือขอข้อมูลเพิ่ม — tool ทุกตัวมีค่าเริ่มต้นจัดการเองได้ และอย่าเดาชื่อ Tool เด็ดขาด ให้ใช้เฉพาะ Tool ที่มีในรายการเท่านั้น (เช่น เรื่องหวยสลากประจำเป็น lotto ไม่ใช่ lottery) "
        "ถ้า user ไม่ระบุรายละเอียด ให้เรียก tool โดยไม่ส่ง parameter (tool จะใช้ค่าเริ่มต้น) "
        "อย่าตอบจากประวัติการสนทนาเก่าหรือความรู้ของตัวเอง เพราะข้อมูลอาจล้าสมัยหรือผิดพลาด "
        "โดยเฉพาะ exchange_rate: ให้ส่ง date ตามที่ผู้ใช้ระบุเสมอ tool จัดการวันหยุดเอง "
        "หมายเหตุ: ปีที่ผู้ใช้ระบุเวลาถามมักจะเป็นปี พ.ศ. ของไทย (Buddhist Era) ซึ่งจะมากกว่า ค.ศ. (CE) 543 ปี "
        f"(เช่น ปี {today.year} คือ พ.ศ. {today.year + 543}) "
        "ให้พิจารณาว่าปี พ.ศ. ที่สมเหตุสมผล ไม่ใช่ปีในอนาคตเสมอ "
        "สำคัญ: ห้ามสร้างข้อความที่เลียนแบบผลลัพธ์ของ tool เด็ดขาด "
        "เช่น ห้ามพิมพ์ข้อความที่ดูเหมือน QR code, PromptPay, สภาพอากาศ, อัตราแลกเปลี่ยน ฯลฯ ด้วยตัวเอง "
        "ถ้างานนั้นมี tool รองรับ ต้องเรียก tool เท่านั้น ห้ามตอบเองเด็ดขาด "
        "เรื่องเส้นทาง/การเดินทาง/จราจร: ถ้า user ถามว่าจะไปที่ไหนสักแห่ง (เช่น 'จะไป X ยังไง', 'ไป X ไปอย่างไร') "
        "ให้เรียก traffic tool เสมอ แม้ว่าก่อนหน้าจะเคย error เรื่อง location ก็ตาม "
        "อย่าตอบเองจาก context เก่า ให้เรียก tool ใหม่ทุกครั้ง เพราะ user อาจส่ง location มาใหม่แล้ว "
        "สำคัญมาก: ห้ามแต่งผลลัพธ์เองเด็ดขาด ถ้า user ถามเรื่องที่ tool จัดการได้ (เช่น อีเมล, อีเมลงาน, work email, สภาพจราจร, ข่าว, หวย ฯลฯ) "
        "ต้องเรียก tool ทุกครั้ง ห้ามตอบว่า 'ไม่มี' หรือ 'ไม่พบ' โดยไม่ได้เรียก tool จริง "
        "ถ้า tool ยังไม่ได้ตั้งค่า tool จะแจ้ง user เอง คุณไม่ต้องเดาผลลัพธ์"
    )


# ---------------------------------------------------------------------------
# dispatch — thin routing layer
# ---------------------------------------------------------------------------

async def dispatch(user_id: str, user: dict, text: str, chat_id: str | int = None, message_id: int = None) -> tuple[str, str | None, str | None, int]:
    """
    ตัดสินใจ route message → return ข้อความที่จะส่งกลับ user

    Returns:
        (response_text, tool_used, llm_model, token_used)
    """
    command, args = parse_command(text)

    # ---- 1. System command → handler dict ----
    handler = SYSTEM_COMMANDS.get(command)
    if handler:
        return await handler(user_id, user, args)

    # ---- 2. Photo message → route ไป expense tool อัตโนมัติ ----
    if text.startswith("__photo:"):
        expense_tool = registry.get_tool("expense")
        if expense_tool:
            log.info("Photo message → routing to expense tool")
            try:
                result = await expense_tool.execute(user_id, text, chat_id=chat_id)
                return result, "expense", None, 0
            except Exception as e:
                log.error(f"Expense photo failed: {e}", exc_info=True)
                return f"❌ ไม่สามารถประมวลผลรูปได้: {e}", "expense", None, 0
        return "❌ ระบบบันทึกรายจ่ายยังไม่พร้อม", None, None, 0

    # ---- 3. Direct command → tool via registry (ไม่เสีย LLM token) ----
    tool = registry.get_by_command(command) if command else None
    if tool:
        log.info(f"Direct command: {command} → {tool.name}")
        try:
            result = await tool.execute(user_id, args, command=command,
                                        chat_id=chat_id, message_id=message_id)
            return result, tool.name, None, 0
        except Exception as e:
            log.error(f"Tool {tool.name} failed: {e}", exc_info=True)
            db.log_tool_usage(
                user_id,
                tool.name,
                status="failed",
                **db.make_log_field("input", f"{command or tool.name} {args}".strip(), kind="tool_command"),
                **db.make_error_fields(str(e)),
            )
            return f"เกิดข้อผิดพลาด: {e}\nกรุณาลองใหม่", tool.name, None, 0

    # ---- 4. ข้อความอิสระ → LLM Router ----
    conv_id = ensure_conversation(user_id)
    provider = get_preference(user, "default_llm")
    context = get_context(user_id, conversation_id=conv_id)
    context.append({"role": "user", "content": text})

    tool_specs = registry.get_all_specs()

    response_text, tool_used, llm_model, token_used = await _dispatch_with_retry(
        user_id=user_id,
        user=user,
        text=text,
        context=context,
        provider=provider,
        tool_specs=tool_specs,
    )

    if not response_text:
        log.warning(f"Retry loop returned empty for: {text[:80]}")
        return "ไม่สามารถประมวลผลได้ กรุณาลองใหม่", tool_used, llm_model, token_used

    return response_text, tool_used, llm_model, token_used


# ---------------------------------------------------------------------------
# LLM dispatch with retry + mid-tier fallback
# ---------------------------------------------------------------------------

async def _dispatch_with_retry(
    user_id: str,
    user: dict,
    text: str,
    context: list[dict],
    provider: str,
    tool_specs: list[dict],
) -> tuple[str, str | None, str | None, int]:
    """
    LLM Router พร้อม self-correction:
    ถ้า LLM เลือก tool ผิดชื่อ หรือ tool execute error → ส่ง feedback กลับให้ LLM คิดใหม่

    กรณีปกติ (tool สำเร็จครั้งแรก) ทำงานเหมือนเดิมทุกประการ:
    - direct_output=True → return ทันที (1 LLM call)
    - direct_output=False → LLM สรุป (2 LLM calls)

    Returns: (response_text, tool_used, llm_model, total_token_used)
    - response_text = None เมื่อหมดรอบ/LLM ตอบว่าง/LLM พัง
    """
    system_prompt = _build_system_prompt()
    messages = list(context)  # copy เพื่อไม่แก้ต้นฉบับ
    total_tokens = 0
    last_model = None
    last_tool_used = None

    for attempt in range(1, MAX_RETRIES + 1):
        log.info(f"[dispatch] attempt {attempt}/{MAX_RETRIES}")

        # ---- เรียก LLM ----
        try:
            resp = await llm_router.chat(
                messages=messages,
                provider=provider,
                tier="cheap",
                system=system_prompt,
                tools=tool_specs if tool_specs else None,
                user_id=user_id,
            )
        except Exception as e:
            # LLM API พัง (หลัง provider retry หมดแล้ว) → หยุดทันที
            log.error(f"[dispatch] LLM API failed at attempt {attempt}: {e}", exc_info=True)
            break

        total_tokens += resp.get("token_used", 0)
        last_model = resp.get("model")

        # ---- Case A: LLM ไม่เรียก tool → return text response ----
        if not resp.get("tool_call"):
            content = resp.get("content", "")
            if content:
                log.info(f"[dispatch] text response at attempt {attempt} ({len(content)} chars)")
                return content, last_tool_used, last_model, total_tokens
            # LLM ตอบว่าง → ให้ feedback แล้ว retry แทนการล้มทันที
            log.warning(f"[dispatch] empty response at attempt {attempt}")
            if attempt >= MAX_RETRIES:
                break

            messages.append({"role": "assistant", "content": ""})
            messages.append({"role": "user", "content": (
                "เมื่อกี้คุณตอบกลับมาเป็นค่าว่าง ซึ่งผู้ใช้จะไม่ได้รับประโยชน์ใดๆ\n"
                "กรุณาตอบใหม่โดยทำอย่างใดอย่างหนึ่ง:\n"
                "1. ถ้าควรใช้ tool ให้เรียก tool ที่เหมาะสมทันที\n"
                "2. ถ้าไม่ต้องใช้ tool ให้ตอบข้อความสั้นๆ ที่เป็นประโยชน์โดยตรง\n"
                "ห้ามตอบว่าง"
            )})
            continue

        # ---- Case B: LLM เรียก tool ----
        tool_name = resp["tool_call"]["name"]
        tool_args = resp["tool_call"].get("args", {})
        log.info(f"[dispatch] attempt {attempt}: tool_call={tool_name}({tool_args})")

        selected_tool = registry.get_tool(tool_name)

        # ---- Case B1: Tool ไม่มีจริง → แจ้ง LLM ให้เลือกใหม่ ----
        if not selected_tool:
            available = [t.name for t in registry.get_all()]
            log.warning(f"[dispatch] unknown tool '{tool_name}', available: {available}")

            if attempt >= MAX_RETRIES:
                break

            messages.append({"role": "assistant", "content": f"[เรียก {tool_name}]"})
            messages.append({"role": "user", "content": (
                f"ไม่มี tool ชื่อ '{tool_name}'\n"
                f"tool ที่มีจริง: {', '.join(available)}\n"
                f"กรุณาเลือก tool ที่ถูกต้อง หรือตอบ user โดยตรง"
            )})
            continue

        # ---- Case B2: Tool มีจริง → execute ----
        last_tool_used = tool_name

        try:
            tool_result = await selected_tool.execute(user_id, **tool_args)
        except Exception as e:
            log.error(f"[dispatch] tool {tool_name} error at attempt {attempt}: {e}", exc_info=True)
            db.log_tool_usage(
                user_id,
                tool_name,
                status="failed",
                **db.make_log_field("input", str(tool_args), kind="tool_call_args"),
                **db.make_error_fields(str(e)),
            )

            if attempt >= MAX_RETRIES:
                break

            messages.append({"role": "assistant", "content": f"[เรียก {tool_name}({tool_args}) → error]"})
            messages.append({"role": "user", "content": (
                f"tool '{tool_name}' ทำงานไม่สำเร็จ: {str(e)}\n"
                f"กรุณาลองวิธีอื่น ใช้ tool อื่น หรือแจ้ง user ว่าเกิดปัญหาอะไร"
            )})
            continue

        # ---- Case B3: Tool สำเร็จ ----
        log.info(f"[dispatch] tool {tool_name} success (direct_output={selected_tool.direct_output})")

        # direct_output=True → return ผลลัพธ์ตรงๆ ไม่ผ่าน LLM (ประหยัด token)
        if selected_tool.direct_output:
            return tool_result, tool_name, last_model, total_tokens

        # direct_output=False → ส่งผลลัพธ์ให้ LLM สรุปเป็นภาษาธรรมชาติ
        summary_messages = messages + [
            {"role": "assistant", "content": f"[เรียก {tool_name}]"},
            {"role": "user", "content": (
                f"ผลลัพธ์จาก {tool_name}:\n{tool_result}\n\n"
                "ช่วยสรุปให้ user เข้าใจง่าย "
                "ถ้ามี URL หรือลิงก์ ให้เก็บไว้ครบทุกอัน อย่าตัดออก"
            )},
        ]

        try:
            summary = await llm_router.chat(
                messages=summary_messages,
                provider=provider,
                tier="cheap",
                system=system_prompt,
                user_id=user_id,
            )
            total_tokens += summary.get("token_used", 0)
            return (
                summary.get("content", tool_result),
                tool_name,
                summary.get("model", last_model),
                total_tokens,
            )
        except Exception as e:
            # สรุปไม่ได้ → return ผล tool ดิบ (ดีกว่าไม่ return อะไร)
            log.error(f"[dispatch] summary failed: {e}, returning raw tool result")
            return tool_result, tool_name, last_model, total_tokens

    # ---- หลุดออกจาก loop → ลอง fallback 1 รอบด้วย tier "mid" ----
    log.warning(f"[dispatch] retry loop ended without response (tokens used: {total_tokens}), trying mid tier fallback")
    try:
        fallback_resp = await llm_router.chat(
            messages=messages[:2],  # ใช้แค่ context เดิม ไม่เอา retry feedback
            provider=provider,
            tier="mid",
            system=system_prompt,
            tools=tool_specs if tool_specs else None,
            user_id=user_id,
        )
        total_tokens += fallback_resp.get("token_used", 0)
        last_model = fallback_resp.get("model")

        # ถ้า fallback ตอบ text → ใช้เลย
        if not fallback_resp.get("tool_call"):
            content = fallback_resp.get("content", "")
            if content:
                log.info(f"[dispatch] mid-tier fallback returned text ({len(content)} chars)")
                return content, last_tool_used, last_model, total_tokens
        else:
            # fallback เรียก tool → execute
            fb_tool_name = fallback_resp["tool_call"]["name"]
            fb_tool_args = fallback_resp["tool_call"].get("args", {})
            fb_tool = registry.get_tool(fb_tool_name)
            if fb_tool:
                fb_result = await fb_tool.execute(user_id, **fb_tool_args)
                log.info(f"[dispatch] mid-tier fallback called {fb_tool_name} (direct_output={fb_tool.direct_output})")
                if fb_tool.direct_output:
                    return fb_result, fb_tool_name, last_model, total_tokens
                return fb_result, fb_tool_name, last_model, total_tokens
    except Exception as e:
        log.error(f"[dispatch] mid-tier fallback failed: {e}")

    return None, last_tool_used, last_model, total_tokens


# ---------------------------------------------------------------------------
# process_message — full pipeline
# ---------------------------------------------------------------------------

async def process_message(user_id: str, user: dict, chat_id: str | int, text: str, message_id: int = None):
    """
    Full pipeline: dedup → rate limit → dispatch + save memory + send Telegram
    เรียกจากทั้ง polling และ webhook
    """
    from interfaces.telegram_common import send_message, send_tool_response, TypingIndicator
    from tools.response import MediaResponse

    log.info(f"[process_message] user={user_id}, chat={chat_id}, text={text[:80]}")

    # ---- Dedup: ข้อความซ้ำภายใน 5 วินาที → skip ----
    if request_dedup.is_duplicate(user_id, text):
        log.info(f"Skipping duplicate message from {user_id}")
        return

    # ---- Rate limit: เกิน 10 msg/นาที → แจ้ง user ----
    if not user_rate_limiter.allow(user_id):
        remaining = user_rate_limiter.remaining(user_id)
        send_message(chat_id, "⏳ ส่งข้อความเร็วเกินไป กรุณารอสักครู่แล้วลองใหม่")
        return

    with TypingIndicator(chat_id):
        # จัดการ conversation
        conv_id = ensure_conversation(user_id)

        save_user_message(user_id, text, conversation_id=conv_id)

        # Auto-set title จากข้อความแรกของ user (ถ้ายังไม่มี title)
        if conv_id:
            existing_title = db.get_conversation_title(conv_id)
            if not existing_title:
                db.update_conversation(conv_id, title=text[:50])
            else:
                db.update_conversation(conv_id)

        try:
            result = await asyncio.wait_for(dispatch(user_id, user, text, chat_id=chat_id, message_id=message_id), timeout=DISPATCH_TIMEOUT)
        except asyncio.TimeoutError:
            log.error(f"dispatch timeout for user {user_id}")
            timeout_msg = "⏱ หมดเวลา — กรุณาลองใหม่"
            save_assistant_message(user_id, timeout_msg, conversation_id=conv_id)
            request_dedup.remove(user_id, text)  # ให้ retry ได้
            send_message(chat_id, timeout_msg)
            return

        if isinstance(result, tuple):
            response_text, tool_used, llm_model, token_used = result
        else:
            response_text, tool_used, llm_model, token_used = result, None, None, 0

        from tools.response import InlineKeyboardResponse
        if isinstance(response_text, InlineKeyboardResponse):
            memory_text = response_text.memory_text or response_text.text
        elif isinstance(response_text, MediaResponse):
            memory_text = response_text.text
        else:
            memory_text = response_text

        # ถ้า dispatch ส่ง error กลับมา → clear dedup ให้ user retry ได้ทันที
        if isinstance(memory_text, str) and memory_text and ("ไม่สำเร็จ" in memory_text or "ข้อผิดพลาด" in memory_text):
            request_dedup.remove(user_id, text)

        # บันทึก memory
        save_assistant_message(
            user_id, memory_text,
            tool_used=tool_used, llm_model=llm_model,
            token_used=token_used,
            conversation_id=conv_id,
        )

    # ส่งกลับ Telegram (หลัง typing หยุด)
    if not response_text:
        log.warning(f"Empty response for user {user_id}, text={text[:50]}")
        response_text = "ไม่สามารถประมวลผลได้ กรุณาลองใหม่"
    send_tool_response(chat_id, response_text)

    # ส่งข้อความค้าง (เช่น morning briefing ที่ส่งไม่ได้ตอนเน็ตหลุด)
    try:
        from scheduler import flush_pending
        flush_pending(str(chat_id))
    except Exception as e:
        log.warning(f"flush_pending failed: {e}")
