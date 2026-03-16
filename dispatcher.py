"""Dispatcher — ตัดสินใจว่าจะ route message ไปที่ไหน
   - /command → tool ตรง (ไม่เสีย token)
   - ข้อความอิสระ → LLM Router → function calling → tool
   - general chat → LLM ตอบตรง
"""

import asyncio
from core.llm import llm_router
from core.memory import (
    save_user_message, save_assistant_message, get_context,
    ensure_conversation, start_new_conversation,
)
from core.user_manager import get_preference, set_preference, is_owner
from core.concurrency import user_rate_limiter, request_dedup
from core import db
from tools.registry import registry
from core.config import DISPATCH_TIMEOUT
MAX_RETRIES = 3  # จำนวนรอบ retry สูงสุดเมื่อ tool fail หรือ LLM เลือก tool ผิด
from interfaces.telegram_common import parse_command
from core.logger import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = (
    "คุณเป็นผู้ช่วยส่วนตัว ชื่อ OpenMiniCrew ตอบเป็นภาษาไทย กระชับ ได้ใจความ "
    "ถ้า user ต้องการทำงานที่ตรงกับ tool ที่มี ให้เรียกใช้ tool นั้น "
    "ถ้าไม่ตรงกับ tool ไหน ให้ตอบคำถามทั่วไปตามความรู้ของคุณ "
    "สำหรับคำถามเกี่ยวกับการจัดการผู้ใช้ เช่น ดูรายชื่อ user, เพิ่ม/ลบ user "
    "ให้แนะนำให้ใช้คำสั่งโดยตรง: /listusers, /adduser <chat_id> [ชื่อ], /removeuser <chat_id> "
    "สำคัญมาก: เมื่อ user ขอข้อมูลจาก tool (อีเมล, แผนที่, ข่าว, อัตราแลกเปลี่ยน, ผลสลากกินแบ่ง หรือ หวย ฯลฯ) "
    "ให้เรียก tool ทันทีเสมอ ห้ามถามกลับหรือขอข้อมูลเพิ่ม — tool ทุกตัวมีค่าเริ่มต้นจัดการเองได้ และอย่าเดาชื่อ Tool เด็ดขาด ให้ใช้เฉพาะ Tool ที่มีในรายการเท่านั้น (เช่น เรื่องหวยสลากประจำเป็น lotto ไม่ใช่ lottery) "
    "ถ้า user ไม่ระบุรายละเอียด ให้เรียก tool โดยไม่ส่ง parameter (tool จะใช้ค่าเริ่มต้น) "
    "อย่าตอบจากประวัติการสนทนาเก่าหรือความรู้ของตัวเอง เพราะข้อมูลอาจล้าสมัยหรือผิดพลาด "
    "โดยเฉพาะ exchange_rate: ให้ส่ง date ตามที่ผู้ใช้ระบุเสมอ tool จัดการวันหยุดเอง "
    "หมายเหตุ: ปีที่ผู้ใช้ระบุเวลาถามมักจะเป็นปี พ.ศ. ของไทย (Buddhist Era) ซึ่งจะมากกว่า ค.ศ. (CE) 543 ปี (เช่น ปี 2026 คือ พ.ศ. 2569) ให้พิจารณาว่าปี พ.ศ. ที่สมเหตุสมผล ไม่ใช่ปีในอนาคตเสมอ"
)


async def dispatch(user_id: str, user: dict, text: str) -> tuple[str, str | None, str | None, int]:
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

    # ---- /new — เริ่มสนทนาใหม่ ----
    if command == "/new":
        conv_id = start_new_conversation(user_id)
        return f"🆕 เริ่มสนทนาใหม่แล้ว (ID: `{conv_id}`)", None, None, 0

    # ---- /history — ดูประวัติสนทนา ----
    if command == "/history":
        conversations = db.list_conversations(user_id, limit=10)
        if not conversations:
            return "📭 ยังไม่มีประวัติสนทนา", None, None, 0

        lines = ["📋 *ประวัติสนทนาล่าสุด:*\n"]
        for i, conv in enumerate(conversations, 1):
            title = conv["title"] or "ไม่มีชื่อ"
            count = conv["message_count"]
            time = conv["updated_at"][:16] if conv["updated_at"] else "—"
            lines.append(f"{i}. {title} ({count} ข้อความ, {time})")

        return "\n".join(lines), None, None, 0

    # ---- Direct command → tool (ไม่เสีย LLM token) ----
    tool = registry.get_by_command(command) if command else None
    if tool:
        log.info(f"Direct command: {command} → {tool.name}")
        try:
            result = await tool.execute(user_id, args)
            return result, tool.name, None, 0
        except Exception as e:
            log.error(f"Tool {tool.name} failed: {e}", exc_info=True)
            db.log_tool_usage(user_id, tool.name, status="failed", error_message=str(e))
            return f"เกิดข้อผิดพลาด: {e}\nกรุณาลองใหม่", tool.name, None, 0

    # ---- ข้อความอิสระ → LLM Router ----
    conv_id = ensure_conversation(user_id)
    provider = get_preference(user, "default_llm")
    context = get_context(user_id, conversation_id=conv_id)
    context.append({"role": "user", "content": text})

    tool_specs = registry.get_all_specs()

    # LLM Router พร้อม self-correction: retry ได้ถ้า tool fail หรือ LLM เลือก tool ผิด
    response_text, tool_used, llm_model, token_used = await _dispatch_with_retry(
        user_id=user_id,
        user=user,
        text=text,
        context=context,
        provider=provider,
        tool_specs=tool_specs,
    )

    # ถ้า retry loop return None → fallback error message
    if not response_text:
        log.warning(f"Retry loop returned empty for: {text[:80]}")
        return "ไม่สามารถประมวลผลได้ กรุณาลองใหม่", tool_used, llm_model, token_used

    return response_text, tool_used, llm_model, token_used


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
                system=SYSTEM_PROMPT,
                tools=tool_specs if tool_specs else None,
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
            # LLM ตอบว่าง → break
            log.warning(f"[dispatch] empty response at attempt {attempt}")
            break

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
                user_id, tool_name,
                input_summary=str(tool_args)[:200],
                status="failed",
                error_message=str(e),
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
                system=SYSTEM_PROMPT,
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

    # ---- หลุดออกจาก loop ----
    log.warning(f"[dispatch] retry loop ended without response (tokens used: {total_tokens})")
    return None, last_tool_used, last_model, total_tokens


async def process_message(user_id: str, user: dict, chat_id: str | int, text: str):
    """
    Full pipeline: dedup → rate limit → dispatch + save memory + send Telegram
    เรียกจากทั้ง polling และ webhook
    """
    from interfaces.telegram_common import send_message, TypingIndicator

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
        existing_title = db.get_conversation_title(conv_id)
        if not existing_title:
            db.update_conversation(conv_id, title=text[:50])
        else:
            db.update_conversation(conv_id)

        try:
            result = await asyncio.wait_for(dispatch(user_id, user, text), timeout=DISPATCH_TIMEOUT)
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

        # ถ้า dispatch ส่ง error กลับมา → clear dedup ให้ user retry ได้ทันที
        if response_text and ("ไม่สำเร็จ" in response_text or "ข้อผิดพลาด" in response_text):
            request_dedup.remove(user_id, text)

        # บันทึก memory
        save_assistant_message(
            user_id, response_text,
            tool_used=tool_used, llm_model=llm_model,
            token_used=token_used,
            conversation_id=conv_id,
        )

    # ส่งกลับ Telegram (หลัง typing หยุด)
    if not response_text:
        log.warning(f"Empty response for user {user_id}, text={text[:50]}")
        response_text = "ไม่สามารถประมวลผลได้ กรุณาลองใหม่"
    send_message(chat_id, response_text)

    # ส่งข้อความค้าง (เช่น morning briefing ที่ส่งไม่ได้ตอนเน็ตหลุด)
    try:
        from scheduler import flush_pending
        flush_pending(str(chat_id))
    except Exception as e:
        log.warning(f"flush_pending failed: {e}")
