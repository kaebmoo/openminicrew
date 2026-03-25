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
    python main.py --import-gmail-client-secrets <path>  # import client secrets แล้วเข้ารหัสเก็บ
    python main.py --list-gmail              # ดูว่า user ไหนมี Gmail token แล้วบ้าง
    python main.py --revoke-gmail <chat_id>  # ลบ Gmail token ของ user
"""

import signal
import sys
import os
import atexit
from pathlib import Path

from core.config import BOT_MODE, OWNER_TELEGRAM_CHAT_ID, CREDENTIALS_DIR
from core.db import init_db
from core.user_manager import init_owner
from core.logger import get_logger
from core.readiness import STATUS_FAIL, STATUS_WARN, collect_startup_readiness, summarize_startup_readiness
from core.security import authorize_gmail_interactive, get_gmail_token_path, import_gmail_client_secrets
from tools.registry import registry
from scheduler import init_scheduler, stop_scheduler

log = get_logger("OpenMiniCrew")

_PID_FILE = Path("/tmp/openminicrew.pid")


def _acquire_pid_lock():
    """ป้องกัน bot รันซ้ำ — เขียน PID file, exit ถ้ามีตัวอื่นรันอยู่"""
    if _PID_FILE.exists():
        try:
            existing_pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
            # ตรวจว่า process ยังอยู่ไหม
            os.kill(existing_pid, 0)  # signal 0 = แค่ตรวจว่ามีอยู่ไหม ไม่ได้ส่ง signal
            print(f"❌ Bot อยู่แล้ว! (PID {existing_pid}) -- ส่ง kill {existing_pid} ถ้าต้องการ restart")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Process ตายไปแล้ว → ลบ PID file เก่า
            _PID_FILE.unlink(missing_ok=True)

    _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: _PID_FILE.unlink(missing_ok=True))
    log.info("PID lock acquired: %s", os.getpid())


def _graceful_shutdown(signum, _frame):
    """Handle SIGTERM / SIGINT — ปิดทุกอย่างให้เรียบร้อย"""
    log.info("Received signal %s, shutting down gracefully...", signum)
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


def _run_startup_self_check(bot_mode: str = BOT_MODE) -> dict:
    report = collect_startup_readiness(bot_mode=bot_mode)
    for line, check in zip(summarize_startup_readiness(report), report["checks"]):
        if check["status"] == STATUS_FAIL:
            log.error(line)
        elif check["status"] == STATUS_WARN:
            log.warning(line)
        else:
            log.info(line)

    if report["should_fail_fast"]:
        raise RuntimeError(
            f"Startup readiness failed in {report['bot_mode']} mode (policy={report['policy']})"
        )
    return report


def main():
    args = sys.argv[1:]

    # --import-gmail-client-secrets <path>
    if "--import-gmail-client-secrets" in args:
        idx = args.index("--import-gmail-client-secrets")
        if idx + 1 >= len(args):
            print("ใช้: python main.py --import-gmail-client-secrets <path>")
            sys.exit(1)
        source_path = args[idx + 1]
        try:
            target_path = import_gmail_client_secrets(source_path)
            print(f"✅ Imported Gmail client secrets ไปยัง {target_path}")
            sys.exit(0)
        except (FileNotFoundError, OSError, ValueError, RuntimeError) as err:
            print(f"❌ Import Gmail client secrets ล้มเหลว: {err}")
            sys.exit(1)

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
        print("=== Gmail Authorization ===")
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

    # PID lock — ป้องกัน bot รันซ้ำ
    _acquire_pid_lock()

    log.info("=" * 50)
    log.info("OpenMiniCrew starting up...")
    log.info("=" * 50)
    _run_startup_self_check(BOT_MODE)

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
    log.info("[4/6] Tools discovered: %s", list(registry.tools.keys()))

    # 5. Start scheduler
    init_scheduler()
    log.info("[5/6] Scheduler started")

    # 6. Start bot
    log.info("[6/6] Starting bot in %s mode...", BOT_MODE.upper())

    if BOT_MODE == "webhook":
        from interfaces.telegram_webhook import start_webhook
        start_webhook()
    else:
        from interfaces.telegram_polling import start_polling
        start_polling()


if __name__ == "__main__":
    main()
