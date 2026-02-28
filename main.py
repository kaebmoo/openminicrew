"""OpenMiniCrew — Entry Point
   1. Init DB
   2. Init owner user
   3. (Auto) Authorize Gmail if no token found
   4. Discover tools
   5. Start scheduler
   6. Start bot (polling or webhook)
   7. Handle graceful shutdown

Usage:
    python main.py               # รันปกติ (auto-detect Gmail auth)
    python main.py --auth-gmail  # authorize Gmail แล้วออก
"""

import signal
import sys

from core.config import BOT_MODE, OWNER_TELEGRAM_CHAT_ID
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
    """ตรวจสอบว่า owner มี Gmail token หรือยัง ถ้ายังก็เปิด browser ให้ authorize"""
    user_id = OWNER_TELEGRAM_CHAT_ID
    token_path = get_gmail_token_path(user_id)

    if token_path.exists():
        log.info("Gmail token found — OK")
        return True

    log.warning("=" * 50)
    log.warning("Gmail token ไม่พบ! กำลังเปิด browser เพื่อ authorize...")
    log.warning("=" * 50)

    success = authorize_gmail_interactive(user_id)
    if success:
        log.info("Gmail authorized สำเร็จ!")
        return True
    else:
        log.error("Gmail authorization ล้มเหลว — email tools จะยังใช้ไม่ได้")
        return False


def main():
    # Handle --auth-gmail flag
    if "--auth-gmail" in sys.argv:
        print("=== Gmail Authorization ===")
        print(f"Authorizing Gmail for owner (chat_id: {OWNER_TELEGRAM_CHAT_ID})...")
        success = authorize_gmail_interactive(OWNER_TELEGRAM_CHAT_ID)
        if success:
            print("✅ Gmail authorized สำเร็จ! สามารถรัน bot ได้เลย")
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
