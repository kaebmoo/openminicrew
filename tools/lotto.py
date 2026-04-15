"""Lotto Tool — ตรวจผลสลากกินแบ่งรัฐบาลผ่าน API"""

import re
import requests
from tools.base import BaseTool
from core import db
from core.logger import get_logger

log = get_logger(__name__)

API_BASE = "https://lotto.api.rayriffy.com"
LOTTO_API_HOST = "lotto.api.rayriffy.com"


def _lotto_get(url: str, timeout: int = 10) -> requests.Response:
    """Fetch using requests, fallback to proxy if OS network drops the domain entirely."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        # ลองดึงข้อมูลตรงๆ ให้เวลาสั้นๆ ถ้าเน็ตเครื่องโดนบล็อกก็จะหลุดไปหา proxy ทันที
        return requests.get(url, timeout=3, headers=headers)
    except Exception as e:
        log.warning(f"Direct fetch failed: {e}. Falling back to proxy for {url}")
        try:
            # ใช้ api.codetabs.com เพื่อทำ proxy เลี่ยงปัญหาการถูกบล็อกเส้นทางชั่วคราว
            proxy_url = f"https://api.codetabs.com/v1/proxy/?quest={url}"
            resp = requests.get(proxy_url, timeout=timeout, headers=headers)
            return resp
        except Exception as proxy_e:
            log.error(f"Proxy fallback failed: {proxy_e}")
            resp = requests.Response()
            resp.status_code = 500
            return resp
GLO_URL = "https://www.glo.or.th/mission/reward-payment/check-reward"

# Mapping prize id → emoji + Thai name
PRIZE_DISPLAY = {
    "prizeFirst":     ("🥇", "รางวัลที่ 1"),
    "prizeFirstNear": ("🥈", "รางวัลข้างเคียงรางวัลที่ 1"),
    "prizeSecond":    ("🥉", "รางวัลที่ 2"),
    "prizeThird":     ("4️⃣", "รางวัลที่ 3"),
    "prizeForth":     ("5️⃣", "รางวัลที่ 4"),
    "prizeFifth":     ("6️⃣", "รางวัลที่ 5"),
}

RUNNING_DISPLAY = {
    "runningNumberFrontThree": "รางวัลเลขหน้า 3 ตัว",
    "runningNumberBackThree":  "รางวัลเลขท้าย 3 ตัว",
    "runningNumberBackTwo":    "รางวัลเลขท้าย 2 ตัว",
}


class LottoTool(BaseTool):
    name = "lotto"
    description = (
        "ตรวจหวย ผลสลากกินแบ่งรัฐบาลไทย ดูงวดล่าสุดหรือระบุงวดได้ "
        "ตรวจเลขได้ทั้ง 6 หลัก, 3 หลัก, 2 หลัก"
    )
    commands = ["/lotto"]
    direct_output = True

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse_args(self, args: str):
        """
        Return dict with keys: mode, number, date_id

        Supported forms:
            ""                      → mode="summary"
            "list"                  → mode="list"
            "list 2"                → mode="list", page=2
            "check 820866"          → mode="check", number="820866"
            "check 820866 16022568" → mode="check", number="820866", date_id="16022568"
            "820866"                → mode="check", number="820866"
            "16022568"              → mode="summary", date_id="16022568"
            "16022568 820866"       → mode="check", number="820866", date_id="16022568"
        """
        result = {"mode": "summary", "number": None, "date_id": None, "page": 1}

        tokens = args.strip().split()
        if not tokens:
            return result

        first = tokens[0].lower()

        # --- month mode ---
        if first in ("month", "เดือน"):
            result["mode"] = "month"
            if len(tokens) >= 2 and re.match(r"^\d{6}$", tokens[1]):
                result["date_id"] = tokens[1]  # MMYYYY
            return result
        
        # --- check month mode ---
        if first in ("check_month", "ตรวจเดือน"):
            result["mode"] = "check_month"
            remaining = tokens[1:]
            for t in remaining:
                if re.match(r"^\d{6}$", t) and result["date_id"] is None:
                    result["date_id"] = t
                elif re.match(r"^\d{2,6}$", t) and result["number"] is None:
                    result["number"] = t
            return result

        # --- list mode ---
        if first in ("list", "งวด", "รายการ"):
            result["mode"] = "list"
            # optional page number: /lotto list 2
            if len(tokens) >= 2 and re.match(r"^\d+$", tokens[1]):
                result["page"] = int(tokens[1])
            return result

        # --- explicit check mode ---
        if first == "check":
            result["mode"] = "check"
            remaining = tokens[1:]  # everything after "check"
            for t in remaining:
                if re.match(r"^\d{8}$", t) and result["date_id"] is None:
                    result["date_id"] = t
                elif re.match(r"^\d{2,6}$", t) and result["number"] is None:
                    result["number"] = t
            return result

        # --- positional args (no mode keyword) ---
        # Collect 8-digit tokens as date_id candidates, others as number candidates
        date_candidates = [t for t in tokens if re.match(r"^\d{8}$", t)]
        month_candidates = [t for t in tokens if re.match(r"^\d{6}$", t)]
        num_candidates  = [t for t in tokens if re.match(r"^\d{2,6}$", t) and t not in month_candidates]

        if date_candidates:
            result["date_id"] = date_candidates[0]
        elif month_candidates:
            result["mode"] = "month"
            result["date_id"] = month_candidates[0]

        if num_candidates:
            result["mode"] = "check" if not month_candidates else "check_month"
            result["number"] = num_candidates[0]

        # Pure date only → stay in summary mode
        if result["date_id"] and not num_candidates and result["mode"] not in ("month", "check_month"):
            result["mode"] = "summary"

        return result

    # ------------------------------------------------------------------
    # API Calls
    # ------------------------------------------------------------------
    def _fetch_lotto(self, date_id: str = None) -> dict | None:
        """Fetch lotto data from API. Returns response dict or None on failure."""
        try:
            if date_id:
                url = f"{API_BASE}/lotto/{date_id}"
            else:
                url = f"{API_BASE}/latest"

            resp = _lotto_get(url)
            data = resp.json()

            if data.get("status") != "success":
                return None

            response = data.get("response", {})
            # API returns empty date and empty number arrays for non-existent dates
            if not response or not response.get("date"):
                return None

            return response

        except Exception as e:
            log.error(f"Lotto API error: {e}")
            return None

    def _fetch_draw_list(self, page: int = 1) -> list | None:
        """Fetch list of available draws from API."""
        try:
            resp = _lotto_get(f"{API_BASE}/list/{page}")
            data = resp.json()
            if data.get("status") != "success":
                return None
            return data.get("response", [])
        except Exception as e:
            log.error(f"Lotto list API error: {e}")
            return None

    def _find_nearby_draws(self, date_id: str) -> str:
        """When a date_id doesn't exist, find and show nearby draws."""
        draws = self._fetch_draw_list()
        if not draws:
            return ""

        # Extract month+year from date_id (DDMMYYYY)
        try:
            target_mm = date_id[2:4]
            target_yyyy = date_id[4:8]
        except (IndexError, TypeError):
            return ""

        # Find draws in the same month+year
        same_month = []
        for d in draws:
            did = d.get("id", "")
            if len(did) == 8 and did[2:4] == target_mm and did[4:8] == target_yyyy:
                same_month.append(d)

        if same_month:
            dates = [d.get('date', d.get('id')) for d in same_month]
            ids = [d.get('id') for d in same_month]
            lines = ["\n📅 งวดที่มีในเดือนเดียวกัน:"]
            for d, did in zip(dates, ids):
                lines.append(f"   • {d}  →  /lotto {did}")
            return "\n".join(lines)

        # If no same-month, show the 5 most recent
        lines = ["\n📅 งวดล่าสุดที่มี:"]
        for d in draws[:5]:
            date = d.get('date', d.get('id'))
            did = d.get('id')
            lines.append(f"   • {date}  →  /lotto {did}")
        return "\n".join(lines)

    def _format_draw_list(self, page: int = 1) -> str:
        """Format list of available draws."""
        draws = self._fetch_draw_list(page=page)
        if not draws:
            return self._fallback_links()

        lines = [f"📅 รายการงวดสลากที่มีผล (หน้า {page}):\n"]
        for d in draws:
            date = d.get('date', '')
            did = d.get('id', '')
            lines.append(f"  • {date}  →  /lotto {did}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------
    def _format_reward(self, reward_str: str) -> str:
        """Format reward string with commas: '6000000' → '6,000,000'"""
        try:
            return f"{int(reward_str):,}"
        except (ValueError, TypeError):
            return reward_str

    def _format_summary(self, data: dict) -> str:
        """Format lotto results for Telegram — prizes 1-3 + running numbers + link."""
        date_str = data.get("date", "ไม่ทราบงวด")
        endpoint = data.get("endpoint", "")

        lines = [f"🎰 ผลสลากกินแบ่งรัฐบาล — {date_str}\n"]

        # Prizes 1-3 + ข้างเคียง (show full numbers)
        show_ids = ["prizeFirst", "prizeFirstNear", "prizeSecond", "prizeThird"]
        for prize in data.get("prizes", []):
            pid = prize.get("id", "")
            if pid not in show_ids:
                continue

            emoji, name = PRIZE_DISPLAY.get(pid, ("", pid))
            reward = self._format_reward(prize.get("reward", ""))
            numbers = prize.get("number", [])

            lines.append(f"{emoji} {name} ({reward} บาท)")

            # แสดงเลข — แบ่งบรรทัดละ 5 เลข
            for i in range(0, len(numbers), 5):
                chunk = numbers[i:i+5]
                lines.append("   " + "  ".join(chunk))
            lines.append("")

        # Running numbers
        for rn in data.get("runningNumbers", []):
            rid = rn.get("id", "")
            name = RUNNING_DISPLAY.get(rid, rid)
            reward = self._format_reward(rn.get("reward", ""))
            numbers = ", ".join(rn.get("number", []))
            lines.append(f"📋 {name} ({reward} บาท): {numbers}")

        # Footer — prizes 4-5 link
        lines.append("")
        lines.append("ℹ️ รางวัลที่ 4 (50 เลข) และ 5 (100 เลข) — ตรวจด้วย:")
        lines.append("   /lotto check <เลข 6 หลัก>")

        if endpoint:
            lines.append(f"🔗 {endpoint}")

        return "\n".join(lines)

    def _format_check_result(self, number: str, data: dict) -> str:
        """Check a number against all prizes and running numbers."""
        date_str = data.get("date", "ไม่ทราบงวด")
        wins = []

        num_len = len(number)

        # Check prizes (6-digit exact match)
        if num_len == 6:
            for prize in data.get("prizes", []):
                pid = prize.get("id", "")
                _, name = PRIZE_DISPLAY.get(pid, ("", pid))
                reward = self._format_reward(prize.get("reward", ""))
                if number in prize.get("number", []):
                    wins.append(f"🎉 เลข {number} ถูก{name} — {reward} บาท!")

        # Check running numbers
        for rn in data.get("runningNumbers", []):
            rid = rn.get("id", "")
            name = RUNNING_DISPLAY.get(rid, rid)
            reward = self._format_reward(rn.get("reward", ""))
            rn_numbers = rn.get("number", [])

            if rid == "runningNumberBackTwo" and num_len == 2:
                if number in rn_numbers:
                    wins.append(f"🎉 เลขท้าย 2 ตัว \"{number}\" ถูก{name} — {reward} บาท!")
            elif rid == "runningNumberFrontThree" and num_len == 3:
                if number in rn_numbers:
                    wins.append(f"🎉 เลขหน้า 3 ตัว \"{number}\" ถูก{name} — {reward} บาท!")
            elif rid == "runningNumberBackThree" and num_len == 3:
                if number in rn_numbers:
                    wins.append(f"🎉 เลขท้าย 3 ตัว \"{number}\" ถูก{name} — {reward} บาท!")

        # Also check 6-digit number against running number back 2 and back 3
        if num_len == 6:
            back2 = number[-2:]
            back3 = number[-3:]
            front3 = number[:3]
            for rn in data.get("runningNumbers", []):
                rid = rn.get("id", "")
                name = RUNNING_DISPLAY.get(rid, rid)
                reward = self._format_reward(rn.get("reward", ""))
                rn_numbers = rn.get("number", [])

                if rid == "runningNumberBackTwo" and back2 in rn_numbers:
                    wins.append(f"🎉 เลขท้าย 2 ตัว \"{back2}\" ถูก{name} — {reward} บาท!")
                elif rid == "runningNumberBackThree" and back3 in rn_numbers:
                    wins.append(f"🎉 เลขท้าย 3 ตัว \"{back3}\" ถูก{name} — {reward} บาท!")
                elif rid == "runningNumberFrontThree" and front3 in rn_numbers:
                    wins.append(f"🎉 เลขหน้า 3 ตัว \"{front3}\" ถูก{name} — {reward} บาท!")

        header = f"🎰 ตรวจผลสลาก — งวด {date_str}\n"

        if wins:
            return header + "\n" + "\n".join(wins)
        else:
            return f"❌ เลข {number} ไม่ถูกรางวัล — งวด {date_str}"

    def _fallback_links(self, date_id: str = None) -> str:
        """Return fallback links when API is down."""
        lines = ["⚠️ ไม่สามารถดึงข้อมูลจาก API ได้ ลองตรวจเองได้ที่:"]
        if date_id:
            lines.append(f"🔗 https://news.sanook.com/lotto/check/{date_id}/")
        lines.append(f"🔗 {GLO_URL}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        if not args and "args" in kwargs:
            args = str(kwargs["args"])
            
        parsed = self._parse_args(args)

        try:
            # List mode
            if parsed["mode"] == "list":
                return self._format_draw_list(page=parsed.get("page", 1))

            # Validate check number format
            if parsed["mode"] in ("check", "check_month"):
                num = parsed["number"]
                if not num or not re.match(r"^\d{2,6}$", num):
                    return (
                        "⚠️ กรุณาใส่เลขที่ต้องการตรวจ:\n"
                        "   /lotto check <เลข 6 หลัก>  — ตรวจสลาก\n"
                        "   /lotto check <เลข 3 หลัก>  — ตรวจเลขหน้า/ท้าย 3 ตัว\n"
                        "   /lotto check <เลข 2 หลัก>  — ตรวจเลขท้าย 2 ตัว"
                    )

            # Handle multi-draw month modes
            if parsed["mode"] in ("month", "check_month"):
                target_mmyyyy = parsed["date_id"]
                if not target_mmyyyy or len(target_mmyyyy) != 6:
                    return "⚠️ กรุณาระบุเดือนและปีให้ถูกต้อง เช่น 022569 (MMYYYY)"
                
                # Search up to 3 pages to find all draws in the requested month
                matched_ids = []
                for p in range(1, 4):
                    draws = self._fetch_draw_list(page=p)
                    if not draws:
                        break
                    
                    found_in_page = False
                    for d in draws:
                        did = d.get("id", "")
                        if len(did) == 8 and did.endswith(target_mmyyyy):
                            matched_ids.append(did)
                            found_in_page = True
                    
                    # If we found matches on a previous page but none on this page, we've passed the month
                    if not found_in_page and matched_ids:
                        break

                if not matched_ids:
                    return f"❌ ไม่พบผลสลากในเดือน {target_mmyyyy[:2]}/{target_mmyyyy[2:]}"
                
                # Sort dates correctly (oldest first or newest first. API usually returns newest first, so we keep that order)
                results = []
                for did in matched_ids:
                    data = self._fetch_lotto(did)
                    if data:
                        if parsed["mode"] == "check_month":
                            res = self._format_check_result(parsed["number"], data)
                            # Only include if we won or if we want to show all. We'll show all.
                            results.append(res)
                        else:
                            results.append(self._format_summary(data))
                
                if not results:
                     return self._fallback_links()
                     
                final_result = "\n----------------------------------------\n\n".join(results)
                
                # Log usage
                db.log_tool_usage(
                    user_id=user_id,
                    tool_name=self.name,
                    status="success",
                    **db.make_log_field("input", f"{parsed['mode']} {target_mmyyyy}", kind="lotto_query"),
                    **db.make_log_field("output", final_result, kind="lotto_result"),
                )
                return final_result

            # Fetch data
            data = self._fetch_lotto(parsed["date_id"])

            if data is None:
                # ถ้าระบุ date_id แต่ไม่มีข้อมูล → บอกว่าไม่มีงวดนั้น + แสดงงวดใกล้เคียง
                if parsed["date_id"]:
                    msg = f"❌ ไม่มีผลสลากงวดวันที่ {parsed['date_id']}"
                    msg += "\n\nบางงวดที่ตรงกับวันหยุดจะเลื่อนวัน เช่น 1 ม.ค. → 2 ม.ค., 1 พ.ค. → 2 พ.ค."
                    nearby = self._find_nearby_draws(parsed["date_id"])
                    if nearby:
                        msg += nearby
                    return msg
                # API ล่มจริงๆ (ไม่ได้ระบุ date_id)
                return self._fallback_links()

            # Dispatch by mode
            if parsed["mode"] == "check":
                result = self._format_check_result(parsed["number"], data)
                input_summary = f"check {parsed['number']}"
            else:
                result = self._format_summary(data)
                input_summary = parsed["date_id"] or "latest"

            # Log usage
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", input_summary, kind="lotto_query"),
                **db.make_log_field("output", result, kind="lotto_result"),
            )

            return result

        except Exception as e:
            log.error(f"Lotto tool error for {user_id}: {e}")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", args, kind="lotto_query"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ เกิดข้อผิดพลาด: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ตรวจผลสลากกินแบ่งรัฐบาลไทย (หวย) "
                "ดูผลหวยงวดล่าสุด หรือระบุงวดที่ต้องการ (DDMMYYYY) "
                "ตรวจเลขสลากได้ (6 หลัก, 3 หลัก, 2 หลัก) "
                "สำคัญ: สลากออกทุกวันที่ 1 และ 16 ของเดือน แต่ถ้าตรงกับวันหยุดจะเลื่อน "
                "เช่น 1 ม.ค. เลื่อนเป็น 2 ม.ค. (02012569), 16 ม.ค. เลื่อนเป็น 17 ม.ค. (17012569), "
                "1 พ.ค. เลื่อนเป็น 2 พ.ค. (02052568) — "
                "ห้ามเดาวันที่เอง ถ้าไม่แน่ใจให้ใช้ 'list' ดูรายการหวยที่มี "
                "หรือส่ง args เป็น '' เพื่อดูหวยงวดล่าสุด "
                "ไม่สามารถทำนายผลล่วงหน้าได้ (หมายเหตุ: ปี พ.ศ. เช่น 2567, 2568, 2569 ไม่ใช่ปีในอนาคต เพราะ พ.ศ. มากกว่า ค.ศ. 543 ปี) "
                "ถ้าผู้ใช้ถามหาผลสลากทั้งเดือน ให้ใช้คำสั่ง month ตามด้วยเดือนปี (MMYYYY) เช่น 'month 022569' เพื่อดึงผลของทุกงวดในเดือนนั้น"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "คำสั่ง เช่น: '' (ตรวจหวยงวดล่าสุด), "
                            "'list' (รายการงวดที่มี), "
                            "'check 820866' (ตรวจเลขงวดล่าสุด), "
                            "'02012569' (ดูงวดที่ระบุ — ต้องเป็น DDMMYYYY ที่มีจริง), "
                            "'check 820866 02012569' (ตรวจเลขงวดที่ระบุ), "
                            "'month 022569' (ดูผลสลากทุกงวดในเดือนกุมภาพันธ์), "
                            "'check_month 820866 022569' (ตรวจเลข 820866 ในทุกงวดของเดือนกุมภาพันธ์)"
                        ),
                    }
                },
                "required": [],
            },
        }
