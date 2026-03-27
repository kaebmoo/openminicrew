"""System command handlers — แยกออกจาก dispatcher.py"""

from __future__ import annotations

from core import db
from core.user_manager import get_preference, set_preference, is_owner
from core.memory import start_new_conversation
from core.privacy_commands import (
    has_pending_consent,
    build_start_consent_block,
    build_keyaudit_summary,
)
from tools.registry import registry
from core.logger import get_logger

log = get_logger(__name__)

_RESULT = tuple[str, None, None, int]


def _ok(text: str) -> _RESULT:
    return text, None, None, 0


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def handle_start(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    db.initialize_explicit_consents_for_new_user(user_id, source="start_onboarding")
    consent_rows = {row["consent_type"]: row for row in db.list_user_consents(user_id)}
    display_name = user.get("display_name") or "ผู้ใช้ใหม่"
    phone = user.get("phone_number")
    national_id = user.get("national_id")
    gmail_ok = user.get("gmail_authorized")

    # Fallback: ถ้า DB ยังไม่ได้ mark แต่ token file มีอยู่ → ถือว่า authorized
    if not gmail_ok:
        from core.security import get_gmail_token_path
        if get_gmail_token_path(user_id).exists():
            gmail_ok = True
            from core.db import get_conn
            with get_conn() as conn:
                conn.execute("UPDATE users SET gmail_authorized = 1 WHERE user_id = ?", (user_id,))

    # Returning user — มีข้อมูลตั้งค่าแล้วอย่างน้อย 1 อย่าง
    if phone or national_id or gmail_ok:
        lines = [f"สวัสดีอีกครั้ง {display_name}\n", "ข้อมูลปัจจุบัน:"]
        lines.append(f"• ชื่อ: {display_name}")
        lines.append(f"• เบอร์โทร: {phone}" if phone else "• เบอร์โทร: ยังไม่ได้ตั้ง (/setphone)")
        if national_id:
            masked = "X" * 9 + national_id[-4:]
            lines.append(f"• เลขบัตรประชาชน: {masked}")
        else:
            lines.append("• เลขบัตรประชาชน: ยังไม่ได้ตั้ง (สำหรับ PromptPay) (/setid)")
        lines.append("• Gmail: เชื่อมแล้ว" if gmail_ok else "• Gmail: ยังไม่ได้เชื่อม (/authgmail)")
        lines.append("")
        lines.extend(build_start_consent_block(consent_rows))
        if has_pending_consent(consent_rows):
            lines.append("")
            lines.append("ยังมี consent ที่ยังไม่ตั้งค่า ใช้ /consent เพื่อดูและตั้งค่าให้ชัดเจน")
        lines.append("\nพิมพ์ /help หรือถามงานที่ต้องการได้เลย")
        return _ok("\n".join(lines))

    # New user — แสดง setup instructions + แนะนำเครื่องมือ
    welcome = (
        f"ลงทะเบียนเรียบร้อยแล้ว {display_name}\n"
        "ยินดีต้อนรับสู่ OpenMiniCrew ผู้ช่วยส่วนตัวของคุณ\n"
        "\n"
        "--- เครื่องมือที่ใช้ได้ ---\n"
        "\n"
        "อีเมล\n"
        "  /email — สรุปอีเมล Gmail วันนี้\n"
        "  /wm — สรุปอีเมลงาน (IMAP)\n"
        "  /inbox — วิเคราะห์อีเมลล่าสุด หา action items\n"
        "\n"
        "งานและนัดหมาย\n"
        "  /todo — จัดการรายการสิ่งที่ต้องทำ\n"
        "  /remind — ตั้งเตือนความจำ\n"
        "  /calendar — ดูและเพิ่มนัดหมาย Google Calendar\n"
        "\n"
        "การเงิน\n"
        "  /expense — บันทึกรายจ่าย (ส่งรูปบิลได้)\n"
        "  /pay — สร้าง PromptPay QR\n"
        "  /fx — ตรวจอัตราแลกเปลี่ยน\n"
        "\n"
        "สถานที่และการเดินทาง\n"
        "  /places — ค้นหาสถานที่บนแผนที่\n"
        "  /traffic — เช็คเส้นทางและสภาพจราจร\n"
        "\n"
        "เครื่องมือทั่วไป\n"
        "  /qr — สร้าง QR Code\n"
        "  /convert — แปลงหน่วย\n"
        "  /search — ค้นหาข้อมูลเว็บ\n"
        "  /news — สรุปข่าวล่าสุด\n"
        "  /lotto — ตรวจหวย\n"
        "\n"
        "หรือพิมพ์คำถามเป็นภาษาธรรมชาติได้เลย\n"
        "เช่น \"แถวนี้มีอะไรกินบ้าง\" หรือ \"สรุปเมลวันนี้ให้หน่อย\"\n"
        "\n"
        "--- ตั้งค่าเพิ่มเติม ---\n"
        "\n"
        "  /setname ชื่อที่ต้องการ\n"
        "  /setphone 08XXXXXXXX\n"
        "  /setid เลขบัตรประชาชน 13 หลัก (สำหรับ PromptPay)\n"
        "  /authgmail — เชื่อมต่อ Gmail และ Calendar\n"
        "\n"
        "--- สิทธิ์การเข้าถึงข้อมูล ---\n"
        "\n"
        "Consent เริ่มต้นของผู้ใช้ใหม่ยังไม่เปิดอัตโนมัติ\n"
        "ระบบจะยังไม่เก็บข้อมูลส่วนตัวจนกว่าคุณจะอนุญาต\n"
        "  /consent chat on — ให้ระบบจำบริบทสนทนาไว้ชั่วคราว\n"
        "  /consent location on — ให้ระบบรับตำแหน่งเพื่อค้นหาสถานที่ใกล้เคียง\n"
        "  /authgmail — ให้ระบบอ่านอีเมลเพื่อสรุปและจัดการนัดหมาย\n"
        "\n"
        "พิมพ์ /consent เพื่อดูสถานะ หรือ /help เพื่อดูคำสั่งทั้งหมด"
    )
    return _ok(welcome)


# ---------------------------------------------------------------------------
# /model
# ---------------------------------------------------------------------------

async def handle_model(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    from core.llm import llm_router

    available = llm_router.get_available_providers(user_id=user_id)
    args = args.strip().lower()

    if not args:
        current = get_preference(user, "default_llm") or "claude"
        lines = ["🧠 LLM ที่ใช้ได้:\n"]
        for name in available:
            marker = "👉" if name == current else "  "
            lines.append(f"  {marker} ✅ {name}")
        lines.append(f"\nใช้: /model [ชื่อ] เช่น /model {available[0]}" if available else "\n❌ ไม่มี LLM ที่ตั้งค่าไว้")
        return _ok("\n".join(lines))

    if args not in available:
        return _ok(f"❌ ใช้ {args} ไม่ได้ — ยังไม่ได้ตั้งค่า API key\nลอง: /setkey {args} <key>\n✅ ใช้ได้: {', '.join(available)}")

    set_preference(user_id, "default_llm", args)
    return _ok(f"✅ เปลี่ยน LLM เป็น {args} เรียบร้อย")


# ---------------------------------------------------------------------------
# Owner-only commands
# ---------------------------------------------------------------------------

async def handle_adduser(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    if not is_owner(user):
        return _ok("❌ คำสั่งนี้ใช้ได้เฉพาะ owner")
    parts = args.strip().split(None, 1)
    if not parts:
        return _ok("❌ ใช้: /adduser <chat_id> [ชื่อ]")
    new_chat_id = parts[0]
    display_name = parts[1] if len(parts) > 1 else new_chat_id
    db.upsert_user(new_chat_id, new_chat_id, display_name)
    log.info(f"Owner {user_id} added user: {new_chat_id} ({display_name})")
    return _ok(f"✅ เพิ่มผู้ใช้ *{display_name}* (chat\\_id: `{new_chat_id}`) แล้ว")


async def handle_removeuser(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    if not is_owner(user):
        return _ok("❌ คำสั่งนี้ใช้ได้เฉพาะ owner")
    target_id = args.strip()
    if not target_id:
        return _ok("❌ ใช้: /removeuser <chat_id>")
    db.deactivate_user(target_id)
    log.info(f"Owner {user_id} deactivated: {target_id}")
    return _ok(f"✅ ปิดการใช้งาน chat\\_id: `{target_id}` แล้ว")


async def handle_listusers(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    if not is_owner(user):
        return _ok("❌ คำสั่งนี้ใช้ได้เฉพาะ owner")
    users = db.get_all_users()
    lines = [f"👥 *ผู้ใช้ทั้งหมด ({len(users)} คน):*\n"]
    for u in users:
        status = "✅" if u["is_active"] else "❌"
        lines.append(f"{status} {u['display_name']} — `{u['telegram_chat_id']}` ({u['role']})")
    return _ok("\n".join(lines))


async def handle_keyaudit(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    if not is_owner(user):
        return _ok("❌ คำสั่งนี้ใช้ได้เฉพาะ owner")
    return _ok(build_keyaudit_summary())


# ---------------------------------------------------------------------------
# Gmail, conversation, help
# ---------------------------------------------------------------------------

async def handle_authgmail(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    from core.gmail_oauth import generate_auth_url
    from core.config import WEBHOOK_HOST
    if not WEBHOOK_HOST:
        return _ok(
            "❌ ต้องตั้งค่า `WEBHOOK_HOST` ใน .env ก่อน\n"
            "เช่น: `WEBHOOK_HOST=https://yourdomain.com`"
        )
    url = generate_auth_url(user_id, user["telegram_chat_id"])
    if not url:
        return _ok("❌ ยังไม่ได้ตั้งค่า `credentials.json` (Google OAuth client)")
    return _ok(
        "🔐 *Authorize Gmail*\n\n"
        f"คลิกลิงก์นี้เพื่อ authorize Gmail ของคุณ:\n{url}\n\n"
        "⏱ ลิงก์หมดอายุใน 15 นาที\n\n"
        "_หลัง authorize แล้ว bot จะแจ้งให้ทราบอัตโนมัติ_"
    )


async def handle_new(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    conv_id = start_new_conversation(user_id)
    if not conv_id:
        return _ok("ℹ️ Chat history retention ปิดอยู่ จึงไม่สร้าง conversation ใหม่")
    return _ok(f"🆕 เริ่มสนทนาใหม่แล้ว (ID: `{conv_id}`)")


async def handle_history(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    conversations = db.list_conversations(user_id, limit=10)
    if not conversations:
        return _ok("📭 ยังไม่มีประวัติสนทนา")

    lines = ["📋 *ประวัติสนทนาล่าสุด:*\n"]
    for i, conv in enumerate(conversations, 1):
        title = conv["title"] or "ไม่มีชื่อ"
        count = conv["message_count"]
        time = conv["updated_at"][:16] if conv["updated_at"] else "—"
        lines.append(f"{i}. {title} ({count} ข้อความ, {time})")
    return _ok("\n".join(lines))


async def handle_help(user_id: str, user: dict, args: str, **kw) -> _RESULT:
    return _ok(registry.get_help_text())
