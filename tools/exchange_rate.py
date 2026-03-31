"""Exchange Rate Tool — อัตราแลกเปลี่ยนเงินตราต่างประเทศ จาก BOT API (ธนาคารแห่งประเทศไทย)"""

import asyncio
import calendar
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from core import db
from core.config import BOT_API_EXCHANGE_TOKEN, BOT_API_HOLIDAY_TOKEN
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# สกุลเงินที่รองรับ (BOT API มีเท่านี้)
# ---------------------------------------------------------------------------
SUPPORTED_CURRENCIES: dict[str, str] = {
    "USD": "สหรัฐอเมริกา",
    "GBP": "สหราชอาณาจักร",
    "EUR": "ยูโรโซน",
    "JPY": "ญี่ปุ่น (ต่อ 100 เยน)",
    "HKD": "ฮ่องกง",
    "MYR": "มาเลเซีย",
    "SGD": "สิงคโปร์",
    "BND": "บรูไนดารุสซาลาม",
    "PHP": "ฟิลิปปินส์",
    "IDR": "อินโดนิเซีย (ต่อ 1000 รูเปีย)",
    "INR": "อินเดีย",
    "CHF": "สวิตเซอร์แลนด์",
    "AUD": "ออสเตรเลีย",
    "NZD": "นิวซีแลนด์",
    "CAD": "แคนาดา",
    "SEK": "สวีเดน",
    "DKK": "เดนมาร์ก",
    "NOK": "นอร์เวย์",
    "CNY": "จีน",
}

# สกุลที่แสดงเป็นค่าเริ่มต้น (เมื่อไม่ระบุ currency)
DEFAULT_CURRENCIES = ["USD", "GBP", "EUR", "JPY", "CNY"]

# BOT API endpoints
BOT_API_BASE = "https://gateway.api.bot.or.th"
EXCHANGE_RATE_URLS = {
    "daily": f"{BOT_API_BASE}/Stat-ExchangeRate/v2/DAILY_AVG_EXG_RATE/",
    "monthly": f"{BOT_API_BASE}/Stat-ExchangeRate/v2/MONTHLY_AVG_EXG_RATE/",
    "quarterly": f"{BOT_API_BASE}/Stat-ExchangeRate/v2/QUARTERLY_AVG_EXG_RATE/",
    "annual": f"{BOT_API_BASE}/Stat-ExchangeRate/v2/ANNUAL_AVG_EXG_RATE/",
}
HOLIDAY_URL = f"{BOT_API_BASE}/financial-institutions-holidays/"

PERIOD_LABELS = {
    "daily": "รายวัน",
    "monthly": "เฉลี่ยรายเดือน",
    "quarterly": "เฉลี่ยรายไตรมาส",
    "annual": "เฉลี่ยรายปี",
}

# Cache วันหยุด — เก็บ per-year เพื่อไม่ call API ซ้ำ
# structure: { year(int): set[date] }
_holiday_cache: dict[int, set[date]] = {}
_holiday_cache_loaded_from_db: set[int] = set()


# ---------------------------------------------------------------------------
# Helper: Holiday cache (SQLite-backed)
# ---------------------------------------------------------------------------

def _ensure_holiday_table() -> None:
    """สร้างตาราง holiday cache ถ้ายังไม่มี"""
    conn = db.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_holidays_cache (
            year        INTEGER NOT NULL,
            holiday_date TEXT NOT NULL,
            description TEXT,
            PRIMARY KEY (year, holiday_date)
        )
    """)
    conn.commit()


def _load_holidays_from_db(year: int) -> Optional[set[date]]:
    """โหลดวันหยุดจาก SQLite — คืน None ถ้าไม่มีข้อมูลปีนั้น"""
    _ensure_holiday_table()
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT holiday_date FROM bot_holidays_cache WHERE year = ?", (year,)
    ).fetchall()
    if not rows:
        return None
    return {date.fromisoformat(r[0]) for r in rows}


def _save_holidays_to_db(year: int, holidays: set[date], descriptions: dict[date, str]) -> None:
    """บันทึกวันหยุดลง SQLite"""
    _ensure_holiday_table()
    conn = db.get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO bot_holidays_cache (year, holiday_date, description) VALUES (?, ?, ?)",
        [(year, d.isoformat(), descriptions.get(d, "")) for d in holidays],
    )
    conn.commit()


def _fetch_holidays_from_api(year: int) -> tuple[set[date], dict[date, str]]:
    """ดึงวันหยุดจาก BOT API — คืน (set[date], {date: description})"""
    headers = {
        "Authorization": BOT_API_HOLIDAY_TOKEN,
        "accept": "application/json",
    }
    resp = requests.get(
        HOLIDAY_URL,
        params={"year": year},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    holidays: set[date] = set()
    descriptions: dict[date, str] = {}
    for item in data.get("result", {}).get("data", []):
        d = date.fromisoformat(item["Date"])
        holidays.add(d)
        descriptions[d] = item.get("HolidayDescriptionThai", "")

    return holidays, descriptions


def get_holidays(year: int) -> set[date]:
    """
    คืน set ของวันหยุดธนาคารในปีที่ระบุ
    ลำดับการ lookup: in-memory cache → SQLite → BOT API
    """
    if year in _holiday_cache:
        return _holiday_cache[year]

    # ลองโหลดจาก SQLite ก่อน
    cached = _load_holidays_from_db(year)
    if cached is not None:
        _holiday_cache[year] = cached
        log.info(f"Holidays {year}: loaded {len(cached)} days from SQLite cache")
        return cached

    # ไม่มีใน DB → call API
    try:
        holidays, descriptions = _fetch_holidays_from_api(year)
        _save_holidays_to_db(year, holidays, descriptions)
        _holiday_cache[year] = holidays
        log.info(f"Holidays {year}: fetched {len(holidays)} days from BOT API and cached")
        return holidays
    except Exception as e:
        log.error(f"Failed to fetch holidays for {year}: {e}")
        return set()


def is_bank_holiday(d: date) -> bool:
    """ตรวจว่าวันที่กำหนดเป็นวันหยุดธนาคาร (รวมเสาร์-อาทิตย์)"""
    if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return True
    return d in get_holidays(d.year)


def last_business_day(from_date: Optional[date] = None) -> date:
    """หาวันทำการล่าสุด (ย้อนหลังจาก from_date)"""
    d = from_date or date.today()
    # ถ้า from_date เป็นปัจจุบัน ให้เริ่มจากเมื่อวาน
    # เพราะ BOT release ข้อมูลตอน 18:00 ของวันทำการ
    d = d - timedelta(days=1)
    for _ in range(14):  # ย้อนหลังสูงสุด 14 วัน (ป้องกัน infinite loop)
        if not is_bank_holiday(d):
            return d
        d -= timedelta(days=1)
    return d  # fallback


# ---------------------------------------------------------------------------
# Helper: Exchange Rate API
# ---------------------------------------------------------------------------

def _fetch_exchange_rate(target_date: date, currency: str,
                         period: str = "daily") -> Optional[dict]:
    """
    ดึงอัตราแลกเปลี่ยนจาก BOT API
    period: daily | monthly | quarterly | annual
    คืน dict ของข้อมูล หรือ None ถ้าไม่มีข้อมูล
    """
    headers = {
        "Authorization": f"Bearer {BOT_API_EXCHANGE_TOKEN}",
        "accept": "application/json",
    }

    # คำนวณ start/end period ตาม format ที่ API ต้องการ
    if period == "monthly":
        # YYYY-MM
        period_str = f"{target_date.year}-{target_date.month:02d}"
        start_str = end_str = period_str
    elif period == "quarterly":
        # YYYY-QN
        q = (target_date.month - 1) // 3 + 1
        period_str = f"{target_date.year}-Q{q}"
        start_str = end_str = period_str
    elif period == "annual":
        # YYYY
        period_str = str(target_date.year)
        start_str = end_str = period_str
    else:  # daily — YYYY-MM-DD
        start_str = end_str = target_date.isoformat()

    url = EXCHANGE_RATE_URLS.get(period, EXCHANGE_RATE_URLS["daily"])
    params = {
        "start_period": start_str,
        "end_period": end_str,
        "currency": currency,
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    records = data.get("result", {}).get("data", {}).get("data_detail", [])
    if not records:
        return None
    record = records[0]
    # ตรวจว่ามีค่า rate จริง (วันหยุด API อาจคืน record เปล่า)
    if not record.get("selling"):
        return None
    return record


def _fmt_num(val: str, decimals: int = 4) -> str:
    """ตัดทศนิยมให้เหลือ decimals หลัก — ถ้า parse ไม่ได้คืนค่าเดิม"""
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return val or "-"


def _format_rate(record: dict, currency: str) -> str:
    """แปลง record จาก API เป็นข้อความ"""
    buying_sight = _fmt_num(record.get("buying_sight"))
    buying_transfer = _fmt_num(record.get("buying_transfer"))
    selling = _fmt_num(record.get("selling"))

    country = SUPPORTED_CURRENCIES.get(currency, currency)
    return (
        f"{currency} ({country})\n"
        f"  ซื้อตั๋วเงิน: {buying_sight}  |  ซื้อโอน: {buying_transfer}  |  ขาย: {selling}"
    )


def _prev_period(target: date, period: str) -> date:
    """ย้อนกลับ 1 งวด — คืน date ที่อยู่ในงวดก่อนหน้า"""
    if period == "monthly":
        # ย้อน 1 เดือน
        if target.month == 1:
            return target.replace(year=target.year - 1, month=12, day=1)
        return target.replace(month=target.month - 1, day=1)
    elif period == "quarterly":
        # ย้อน 1 ไตรมาส (3 เดือน)
        month = target.month - 3
        year = target.year
        if month < 1:
            month += 12
            year -= 1
        return target.replace(year=year, month=month, day=1)
    elif period == "annual":
        return target.replace(year=target.year - 1, month=1, day=1)
    return target


def _period_label(target: date, period: str) -> str:
    """สร้าง label วันที่สำหรับแสดงผลตาม period"""
    if period == "monthly":
        thai_months = [
            "", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
            "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
        ]
        return f"{thai_months[target.month]} {target.year}"
    elif period == "quarterly":
        q = (target.month - 1) // 3 + 1
        return f"Q{q}/{target.year}"
    elif period == "annual":
        return f"ปี {target.year}"
    else:
        return target.strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Main Tool Class
# ---------------------------------------------------------------------------

class ExchangeRateTool(BaseTool):
    name = "exchange_rate"
    description = (
        "ดูอัตราแลกเปลี่ยนเงินตราต่างประเทศเป็นบาทไทย จากธนาคารแห่งประเทศไทย "
        "ระบุสกุลเงิน วันที่ และช่วงเวลาได้ (รายวัน/เดือน/ไตรมาส/ปี)"
    )
    commands = ["/fx", "/rate", "/exchange"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", date: str = "",
                      period: str = "daily", **kwargs) -> str:
        args = (args or "").strip().upper()

        # ผู้ใช้ถามว่ามีสกุลอะไรบ้าง
        if args in ("LIST", "?", "HELP", "สกุล", "มีอะไรบ้าง"):
            return self._list_currencies()

        # ถ้าไม่ระบุ → แสดง default currencies
        if not args:
            currencies = DEFAULT_CURRENCIES
        else:
            # แยก input หลายสกุล เช่น "USD EUR JPY"
            currencies = [c.strip() for c in args.replace(",", " ").split() if c.strip()]

        # ตรวจสกุลที่ไม่รู้จัก
        unknown = [c for c in currencies if c not in SUPPORTED_CURRENCIES]
        if unknown:
            return (
                f"ไม่รู้จักสกุลเงิน: {', '.join(unknown)}\n"
                f"พิมพ์ /fx list เพื่อดูรายการสกุลทั้งหมด"
            )

        # Validate period
        period = period.lower().strip() if period else "daily"
        if period not in EXCHANGE_RATE_URLS:
            return f"ไม่รู้จัก period: {period} (ใช้ daily, monthly, quarterly, annual)"

        # กำหนดวันที่เป้าหมาย
        if date:
            try:
                target = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            except ValueError:
                return f"รูปแบบวันที่ไม่ถูกต้อง: {date} (ใช้ YYYY-MM-DD)"
        else:
            target = date_module_today()

        # สำหรับ daily: ลองย้อนหลังถ้าไม่มีข้อมูล (วันหยุด/เสาร์-อาทิตย์)
        if period == "daily":
            if not date:
                target = last_business_day()
            biz_day = target
            first_currency = currencies[0]
            for _ in range(7):
                try:
                    test = _fetch_exchange_rate(biz_day, first_currency, "daily")
                    if test:
                        break
                except Exception:
                    pass
                biz_day -= timedelta(days=1)
                while biz_day.weekday() >= 5:
                    biz_day -= timedelta(days=1)
            target = biz_day

        # สำหรับ monthly/quarterly/annual: ลองย้อนงวดถ้าไม่มีข้อมูล (งวดปัจจุบันยังไม่จบ)
        elif period in ("monthly", "quarterly", "annual"):
            first_currency = currencies[0]
            for _ in range(3):
                try:
                    test = _fetch_exchange_rate(target, first_currency, period)
                    if test:
                        break
                except Exception:
                    pass
                target = _prev_period(target, period)

        try:
            results = []
            errors = []

            for currency in currencies:
                try:
                    record = _fetch_exchange_rate(target, currency, period)
                    if record:
                        results.append(_format_rate(record, currency))
                    else:
                        errors.append(f"{currency}: ไม่มีข้อมูล")
                except Exception as e:
                    log.warning(f"Failed to fetch {currency} ({period}): {e}")
                    errors.append(f"{currency}: ดึงข้อมูลไม่ได้")

            # สร้าง output
            label = _period_label(target, period)
            period_th = PERIOD_LABELS.get(period, "")
            lines = [f"อัตราแลกเปลี่ยน{period_th} ณ {label} (THB)\n"]
            if results:
                lines.extend(results)
            if errors:
                lines.append("\n" + "\n".join(errors))
            lines.append(f"\nที่มา: ธนาคารแห่งประเทศไทย")

            output = "\n".join(lines)

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", f"{period} {args or 'default'} {date}", kind="exchange_rate_query"),
                **db.make_log_field("output", output, kind="exchange_rate_result"),
            )
            return output

        except Exception as e:
            log.error(f"ExchangeRateTool failed for {user_id}: {e}")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", f"{period} {args or 'default'} {date}", kind="exchange_rate_query"),
                **db.make_error_fields(str(e)),
            )
            return f"เกิดข้อผิดพลาดในการดึงอัตราแลกเปลี่ยน: {e}"

    def _list_currencies(self) -> str:
        lines = ["สกุลเงินที่รองรับ:\n"]
        for code, country in SUPPORTED_CURRENCIES.items():
            lines.append(f"  {code} — {country}")
        lines.append("\nตัวอย่าง: /fx USD  หรือ  /fx USD EUR JPY")
        return "\n".join(lines)

    def get_tool_spec(self) -> dict:
        currency_list = ", ".join(SUPPORTED_CURRENCIES.keys())
        return {
            "name": self.name,
            "description": (
                "ดูอัตราแลกเปลี่ยนเงินตราต่างประเทศเป็นบาทไทย จากธนาคารแห่งประเทศไทย "
                "สำคัญมาก: เมื่อผู้ใช้พูดถึงอัตราแลกเปลี่ยน ให้เรียก tool นี้ทันที "
                "ห้ามถามกลับเด็ดขาด ห้ามขอข้อมูลเพิ่ม — ถ้าผู้ใช้ไม่ระบุสกุลเงิน ให้ส่ง args ว่าง (tool จะแสดง USD GBP EUR JPY CNY อัตโนมัติ) "
                "ถ้าผู้ใช้ไม่ระบุวันที่ ให้ส่ง date ว่าง (tool จะใช้วันทำการล่าสุดอัตโนมัติ) "
                "ถ้าผู้ใช้ไม่ระบุ period ให้ส่ง period ว่าง (tool จะใช้ daily อัตโนมัติ) "
                "tool จะจัดการวันหยุด/เสาร์-อาทิตย์เอง โดยหาวันทำการก่อนหน้าให้อัตโนมัติ "
                "ให้ส่ง date และ period ตามที่ผู้ใช้ระบุเสมอ ไม่ต้องตรวจสอบว่าเป็นวันหยุดหรือไม่"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            f"สกุลเงินที่ต้องการ เช่น 'USD', 'EUR', 'USD EUR JPY' (หลายสกุลได้) "
                            f"หรือ 'list' เพื่อดูทั้งหมด "
                            f"ค่าเริ่มต้น: ว่าง (แสดง USD GBP EUR JPY CNY) "
                            f"สกุลที่รองรับ: {currency_list}"
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "วันที่อ้างอิง รูปแบบ YYYY-MM-DD เช่น '2026-03-01' "
                            "ค่าเริ่มต้น: ว่าง (ใช้วันทำการล่าสุดอัตโนมัติ) "
                            "สำหรับ monthly ใช้วันใดก็ได้ในเดือนนั้น เช่น '2026-02-01' = ก.พ. 2026 "
                            "สำหรับ quarterly ใช้วันใดก็ได้ในไตรมาสนั้น เช่น '2026-01-01' = Q1/2026 "
                            "สำหรับ annual ใช้วันใดก็ได้ในปีนั้น เช่น '2025-01-01' = ปี 2025"
                        ),
                    },
                    "period": {
                        "type": "string",
                        "description": (
                            "ช่วงเวลาของอัตราแลกเปลี่ยน: "
                            "'daily' = รายวัน (ค่าเริ่มต้น), "
                            "'monthly' = เฉลี่ยรายเดือน, "
                            "'quarterly' = เฉลี่ยรายไตรมาส, "
                            "'annual' = เฉลี่ยรายปี"
                        ),
                    },
                },
                "required": [],
            },
        }


def date_module_today() -> date:
    """wrapper เพื่อให้ test mock ได้"""
    return date.today()
