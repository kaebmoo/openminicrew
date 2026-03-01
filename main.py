"""OpenMiniCrew — Entry Point
   1. Init DB
   2. Init owner user
   3. (Auto) Authorize Gmail if no token found
   4. Discover tools
   5. Start scheduler
   6. Start bot (polling or webhook)
   7. Handle graceful shutdown

Usage:
    python main.py                           # รันปกติ (auto-detect Gmail auth)
    python main.py --auth-gmail              # authorize Gmail สำหรับ owner แล้วออก
    python main.py --auth-gmail <chat_id>    # authorize Gmail สำหรับ user ที่ระบุ
    python main.py --list-gmail              # ดูว่า user ไหนมี Gmail token แล้วบ้าง
    python main.py --revoke-gmail <chat_id>  # ลบ Gmail token ของ user
"""

import signal
import sys

from core.config import BOT_MODE, OWNER_TELEGRAM_CHAT_ID, CREDENTIALS_DIR
from core.db import init_db
from core.user_manager import init_owner
from core.logger import get_logger
from core.security import authorize_gmail_interactive, get_gmail_token_path
from tools.registry import registry
from scheduler import init_scheduler, stop_scheduler

log = get_logger("OpenMiniCrew")


def _graceful_shutdown(signum, frame):
    """Handle SIGTERM / SIGINT — ปิดทุกอย่างให้เรียบร้อย"""
    log.info(f"Received signal {signum}, shutting down gracefully...")
    stop_scheduler()
    log.info("Goodbye!")
    sys.exit(0)


def _ensure_gmail_auth():
    """ตรวจสอบว่า owner มี Gmail token ที่ valid หรือยัง ถ้ายังก็เปิด browser ให้ authorize"""
    from core.security import get_gmail_credentials

    user_id = OWNER_TELEGRAM_CHAT_ID
    token_path = get_gmail_token_path(user_id)

    if not token_path.exists():
        log.warning("=" * 50)
        log.warning("Gmail token ไม่พบ! กำลังเปิด browser เพื่อ authorize...")
        log.warning("=" * 50)
        success = authorize_gmail_interactive(user_id)
        if success:
            log.info("Gmail authorized สำเร็จ!")
        else:
            log.error("Gmail authorization ล้มเหลว — email tools จะยังใช้ไม่ได้")
        return success

    # Token ไฟล์มีอยู่ — ตรวจสอบว่า valid + refresh ได้จริง
    creds = get_gmail_credentials(user_id)
    if creds:
        log.info("Gmail token valid — OK")
        return True

    log.warning("⚠️  Gmail token ไม่ valid (expired หรือ revoked) — กรุณา re-authorize")
    log.warning("    รัน: python main.py --auth-gmail")
    return False


def main():
    args = sys.argv[1:]

    # --list-gmail
    if "--list-gmail" in args:
        tokens = sorted(CREDENTIALS_DIR.glob("gmail_*.json"))
        if not tokens:
            print("ยังไม่มี Gmail token ใดเลย")
        else:
            print(f"Gmail tokens ({len(tokens)} รายการ):")
            for path in tokens:
                user_id = path.stem.replace("gmail_", "")
                label = " (owner)" if user_id == OWNER_TELEGRAM_CHAT_ID else ""
                print(f"  • {user_id}{label}")
        sys.exit(0)

    # --revoke-gmail <chat_id>
    if "--revoke-gmail" in args:
        idx = args.index("--revoke-gmail")
        if idx + 1 >= len(args):
            print("ใช้: python main.py --revoke-gmail <chat_id>")
            sys.exit(1)
        target = args[idx + 1]
        token_path = get_gmail_token_path(target)
        if not token_path.exists():
            print(f"ไม่พบ token สำหรับ user: {target}")
            sys.exit(1)
        token_path.unlink()
        print(f"✅ ลบ Gmail token ของ {target} แล้ว")
        sys.exit(0)

    # --auth-gmail [chat_id]
    if "--auth-gmail" in args:
        idx = args.index("--auth-gmail")
        # ถ้ามี argument ถัดไปและไม่ใช่ flag อื่น → ใช้เป็น user_id
        if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
            target = args[idx + 1]
        else:
            target = OWNER_TELEGRAM_CHAT_ID
        print(f"=== Gmail Authorization ===")
        print(f"Authorizing Gmail for user: {target}...")
        success = authorize_gmail_interactive(target)
        if success:
            print(f"✅ Gmail authorized สำเร็จ สำหรับ {target}")
        else:
            print("❌ Gmail authorization ล้มเหลว กรุณาตรวจสอบ credentials.json")
        sys.exit(0 if success else 1)

    # Graceful shutdown handlers
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    log.info("=" * 50)
    log.info("OpenMiniCrew starting up...")
    log.info("=" * 50)

    # 1. Init database
    init_db()
    log.info("[1/6] Database initialized")

    # 2. Init owner user
    init_owner()
    log.info("[2/6] Owner user initialized")

    # 3. Auto-check Gmail authorization
    _ensure_gmail_auth()
    log.info("[3/6] Gmail auth checked")

    # 4. Discover tools
    registry.discover()
    log.info(f"[4/6] Tools discovered: {list(registry.tools.keys())}")

    # 5. Start scheduler
    init_scheduler()
    log.info("[5/6] Scheduler started")

    # 6. Start bot
    log.info(f"[6/6] Starting bot in {BOT_MODE.upper()} mode...")

    if BOT_MODE == "webhook":
        from interfaces.telegram_webhook import start_webhook
        start_webhook()
    else:
        from interfaces.telegram_polling import start_polling
        start_polling()


if __name__ == "__main__":
    main()
