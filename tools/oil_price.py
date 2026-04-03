"""Oil Price Tool -- เช็คราคาน้ำมันจากบางจากและ ปตท."""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

import requests

from core import db
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BANGCHAK_API_URL = "https://oil-price.bangchak.co.th/ApiOilPrice2/th"

PTT_SOAP_URL = "https://orapiweb.pttor.com/oilservice/OilPrice.asmx"
PTT_SOAP_NS = {"ns": "http://www.pttor.com"}

# Date patterns สำหรับ detect ว่า args เป็นวันที่
_DATE_PATTERNS = [
    # YYYY-MM-DD
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), "ymd"),
    # DD/MM/YYYY
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), "dmy"),
    # DD-MM-YYYY
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"), "dmy"),
]

# Keywords สำหรับ detect source จาก args
_PTT_KEYWORDS = {"ptt", "ปตท", "ปตท."}
_BANGCHAK_KEYWORDS = {"bangchak", "บางจาก"}

# หมายเหตุท้ายข้อความ
_NOTE_BANGKOK_RETAIL = (
    "หมายเหตุ: ราคาขายปลีก กทม. ยังไม่รวมภาษีบำรุงท้องถิ่น\n"
    "ราคาหน้าสถานีบริการอาจแตกต่างกันในแต่ละพื้นที่"
)

# Request timeout (seconds)
_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Bangchak API
# ---------------------------------------------------------------------------

def _fetch_bangchak() -> dict:
    """
    ดึงราคาน้ำมันจาก Bangchak API

    Returns:
        dict with keys: date, time, remark, oils (list of dicts)
        แต่ละ oil: {name, today, tomorrow}
    """
    resp = requests.get(BANGCHAK_API_URL, timeout=_TIMEOUT)
    resp.raise_for_status()

    raw = resp.json()
    if not raw or not isinstance(raw, list):
        raise ValueError("Bangchak API returned unexpected format")

    data = raw[0]

    # OilList เป็น JSON string ซ้อนอยู่ใน response — ต้อง parse อีกรอบ
    oil_list_raw = data.get("OilList", "[]")
    oil_list = json.loads(oil_list_raw) if isinstance(oil_list_raw, str) else oil_list_raw

    oils = []
    for item in oil_list:
        oils.append({
            "name": item.get("OilName", ""),
            "today": item.get("PriceToday", "-"),
            "tomorrow": item.get("PriceTomorrow", "-"),
        })

    return {
        "date": data.get("OilDateNow", ""),
        "time": data.get("OilPriceTime", ""),
        "remark": data.get("OilRemark2", ""),
        "oils": oils,
    }


def _format_bangchak(data: dict) -> str:
    """แปลงข้อมูล Bangchak เป็นข้อความ"""
    # ตรวจว่ามีราคาเปลี่ยนแปลง (วันนี้ ≠ พรุ่งนี้) หรือไม่
    has_price_change = any(
        oil["today"] != oil["tomorrow"] for oil in data["oils"]
    )

    header = f"ราคาน้ำมันบางจาก"
    if has_price_change:
        lines = [header, f"วันที่: {data['date']} | เวลาประกาศ: {data['time']}"]
    else:
        lines = [header, f"วันที่: {data['date']}"]
    if data["remark"]:
        lines.append(data["remark"])
    lines.append("")

    # Header
    lines.append(f"{'ประเภท':<28} {'วันนี้':>8}  {'พรุ่งนี้':>8}")
    lines.append("-" * 50)

    for oil in data["oils"]:
        name = oil["name"]
        today = oil["today"]
        tomorrow = oil["tomorrow"]
        lines.append(f"{name:<28} {today:>8}  {tomorrow:>8}")

    lines.append("")
    lines.append(_NOTE_BANGKOK_RETAIL)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PTT SOAP API — Current (latest national prices)
# ---------------------------------------------------------------------------

_SOAP_CURRENT = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <CurrentOilPrice xmlns="http://www.pttor.com">
      <Language>th</Language>
    </CurrentOilPrice>
  </soap:Body>
</soap:Envelope>"""

_SOAP_CURRENT_HEADERS = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction": '"https://orapiweb.pttor.com/CurrentOilPrice"',
}


def _fetch_ptt_current() -> tuple[str, list[dict]]:
    """
    ดึงราคาน้ำมัน ปตท. ปัจจุบัน (CurrentOilPrice)

    Returns:
        (price_date_str, fuels)
        fuels: list of dicts [{product, price, diff}, ...]
    """
    resp = requests.post(
        PTT_SOAP_URL,
        data=_SOAP_CURRENT.encode("utf-8"),
        headers=_SOAP_CURRENT_HEADERS,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    result_node = root.find(".//ns:CurrentOilPriceResult", PTT_SOAP_NS)

    if result_node is None or not result_node.text:
        return "", []

    oil_data = ET.fromstring(result_node.text)

    def _get_text(node, tag, default=""):
        found = node.find(tag)
        return found.text if found is not None and found.text else default

    # ดึงวันที่จาก FUEL ตัวแรก
    price_date = ""
    first_fuel = oil_data.find("FUEL")
    if first_fuel is not None:
        raw_date = _get_text(first_fuel, "PRICE_DATE")
        if raw_date:
            price_date = raw_date.split("T")[0]  # "2026-04-02T00:00:00" -> "2026-04-02"

    fuels = []
    for fuel in oil_data.findall("FUEL"):
        product = _get_text(fuel, "PRODUCT")
        price = _get_text(fuel, "PRICE", "0.00")
        diff = _get_text(fuel, "PRICE_DIFF", "0.00")
        if product and price != "0.00":
            fuels.append({"product": product, "price": price, "diff": diff})

    return price_date, fuels


def _format_ptt_current(price_date: str, fuels: list[dict]) -> str:
    """แปลงข้อมูล PTT current เป็นข้อความ"""
    lines = [
        f"ราคาน้ำมัน ปตท.",
    ]
    if price_date:
        lines.append(f"ณ วันที่: {price_date}")
    lines.append("")

    lines.append(f"{'ประเภท':<28} {'ราคา':>8}  {'เปลี่ยนแปลง':>10}")
    lines.append("-" * 52)

    for fuel in fuels:
        product = fuel["product"]
        price = fuel["price"]
        diff = fuel["diff"]
        # แสดง +/- ถ้าเปลี่ยนแปลง
        try:
            diff_val = float(diff)
            if diff_val > 0:
                diff_display = f"+{diff}"
            elif diff_val == 0:
                diff_display = "0.00"
            else:
                diff_display = diff  # ติดลบอยู่แล้ว
        except (ValueError, TypeError):
            diff_display = diff

        lines.append(f"{product:<28} {price:>8}  {diff_display:>10}")

    lines.append("")
    lines.append(_NOTE_BANGKOK_RETAIL)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PTT SOAP API — Historical (by date)
# ---------------------------------------------------------------------------

def _build_soap_historical(day: int, month: int, year: int) -> tuple[str, dict]:
    """สร้าง SOAP envelope สำหรับ GetOilPrice + headers"""
    payload = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetOilPrice xmlns="http://www.pttor.com">
      <Language>th</Language>
      <DD>{day}</DD>
      <MM>{month}</MM>
      <YYYY>{year}</YYYY>
    </GetOilPrice>
  </soap:Body>
</soap:Envelope>"""

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": '"https://orapiweb.pttor.com/GetOilPrice"',
    }
    return payload, headers


def _fetch_ptt_historical(target: date) -> list[dict]:
    """
    ดึงราคาน้ำมัน ปตท. ณ วันที่กำหนด (GetOilPrice)

    Returns:
        list of dicts: [{product, price}, ...]
    """
    payload, headers = _build_soap_historical(target.day, target.month, target.year)

    resp = requests.post(PTT_SOAP_URL, data=payload.encode("utf-8"),
                         headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    result_node = root.find(".//ns:GetOilPriceResult", PTT_SOAP_NS)

    if result_node is None or not result_node.text:
        return []

    oil_data = ET.fromstring(result_node.text)
    fuels = []
    for fuel in oil_data.findall("FUEL"):
        product = fuel.findtext("PRODUCT", "")
        price = fuel.findtext("PRICE", "")
        if product and price:
            fuels.append({"product": product, "price": price})

    return fuels


def _format_ptt_historical(fuels: list[dict], target: date) -> str:
    """แปลงข้อมูล PTT historical เป็นข้อความ"""
    lines = [
        f"ราคาน้ำมัน ปตท.",
        f"ณ วันที่: {target.strftime('%d/%m/%Y')}",
        "",
        f"{'ประเภท':<28} {'ราคา (บาท)':>10}",
        "-" * 42,
    ]

    for fuel in fuels:
        lines.append(f"{fuel['product']:<28} {fuel['price']:>10}")

    lines.append("")
    lines.append(_NOTE_BANGKOK_RETAIL)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date_str(text: str) -> date | None:
    """
    พยายาม parse วันที่จาก string หลาย format

    รองรับ: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    Returns: date object หรือ None
    """
    text = text.strip()
    for pattern, fmt in _DATE_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        try:
            if fmt == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:  # dmy
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
    return None


def _find_latest_ptt_date(start: date | None = None, max_retries: int = 7) -> tuple[date, list[dict]]:
    """
    หาวันที่ล่าสุดที่ ปตท. มีข้อมูลราคา (ข้ามวันหยุด/เสาร์-อาทิตย์)

    Returns: (date, fuels)
    Raises: ValueError ถ้าไม่พบข้อมูลภายใน max_retries วัน
    """
    target = start or date.today()
    for _ in range(max_retries):
        fuels = _fetch_ptt_historical(target)
        if fuels:
            return target, fuels
        target -= timedelta(days=1)
    raise ValueError(f"ไม่พบข้อมูลราคาน้ำมัน ปตท. ย้อนหลัง {max_retries} วัน")


# ---------------------------------------------------------------------------
# Tool Class
# ---------------------------------------------------------------------------

class OilPriceTool(BaseTool):
    name = "oil_price"
    description = "เช็คราคาน้ำมันจากบางจากและ ปตท."
    commands = ["/oil", "/fuel"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "",
                      date: str = "", compare_date: str = "", **kwargs) -> str:
        """
        Main entry point

        Parameters:
            user_id: Telegram chat ID
            args: free text (สำหรับ /command parsing)
            date: วันที่ YYYY-MM-DD สำหรับดูราคาย้อนหลัง (ปตท.)
            compare_date: วันที่สำหรับเปรียบเทียบ (YYYY-MM-DD)
        """
        raw_args = (args or "").strip()

        try:
            # ----- Compare mode: เปรียบเทียบราคา 2 วัน -----
            if compare_date:
                return self._handle_compare(user_id, date or "", compare_date)

            # ----- LLM path: explicit date parameter -----
            if date:
                return self._handle_historical_str(user_id, date)

            # ----- Direct /command path: parse args -----
            if raw_args:
                return self._handle_args(user_id, raw_args)

            # ----- Default: Bangchak today + tomorrow -----
            return self._handle_bangchak(user_id)

        except Exception as e:
            log.error("OilPriceTool failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", f"{raw_args}|{date}", kind="tool_command"),
                **db.make_error_fields(str(e)),
            )
            return f"เกิดข้อผิดพลาดในการดึงราคาน้ำมัน: {e}"

    # ----- Handlers -----

    def _handle_args(self, user_id: str, raw_args: str) -> str:
        """Parse free-text args จาก /command"""
        lower = raw_args.lower()

        # 1. ตรวจ date pattern
        parsed_date = _parse_date_str(raw_args)
        if parsed_date:
            return self._handle_historical(user_id, parsed_date)

        # 2. ตรวจ source keywords
        if lower in _PTT_KEYWORDS:
            return self._handle_ptt_current(user_id)

        if lower in _BANGCHAK_KEYWORDS:
            return self._handle_bangchak(user_id)

        # 3. ไม่รู้จัก → แสดง usage
        return self._usage()

    def _handle_bangchak(self, user_id: str) -> str:
        """ดึงราคาจาก Bangchak API"""
        data = _fetch_bangchak()
        if not data["oils"]:
            return "ไม่พบข้อมูลราคาน้ำมันจากบางจาก"

        result = _format_bangchak(data)

        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", "bangchak", kind="tool_command"),
            **db.make_log_field("output", result[:200], kind="tool_result"),
        )
        return result

    def _handle_ptt_current(self, user_id: str) -> str:
        """ดึงราคา ปตท. ปัจจุบัน (CurrentOilPrice — มี price diff)"""
        price_date, fuels = _fetch_ptt_current()
        if not fuels:
            return "ไม่พบข้อมูลราคาน้ำมัน ปตท."

        result = _format_ptt_current(price_date, fuels)

        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", f"ptt current {price_date}", kind="tool_command"),
            **db.make_log_field("output", result[:200], kind="tool_result"),
        )
        return result

    def _handle_historical_str(self, user_id: str, date_str: str) -> str:
        """Handle date parameter จาก LLM (string YYYY-MM-DD)"""
        try:
            target = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            return f"รูปแบบวันที่ไม่ถูกต้อง: {date_str} (ใช้ YYYY-MM-DD)"
        return self._handle_historical(user_id, target)

    def _handle_historical(self, user_id: str, target: date) -> str:
        """ดึงราคา ปตท. ณ วันที่กำหนด (GetOilPrice)"""
        fuels = _fetch_ptt_historical(target)
        if not fuels:
            # ลองย้อนหลังหาวันที่มีข้อมูล
            try:
                target, fuels = _find_latest_ptt_date(target)
            except ValueError:
                return (
                    f"ไม่พบข้อมูลราคาน้ำมัน ปตท. ณ วันที่ "
                    f"{target.strftime('%d/%m/%Y')} หรือวันใกล้เคียง"
                )

        result = _format_ptt_historical(fuels, target)

        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", f"historical {target.isoformat()}", kind="tool_command"),
            **db.make_log_field("output", result[:200], kind="tool_result"),
        )
        return result

    # ----- Compare -----

    def _handle_compare(self, user_id: str, date_a_str: str, date_b_str: str) -> str:
        """เปรียบเทียบราคาน้ำมัน ปตท. 2 วัน"""
        # Parse date A
        if date_a_str:
            try:
                target_a = datetime.strptime(date_a_str.strip(), "%Y-%m-%d").date()
            except ValueError:
                return f"รูปแบบวันที่ไม่ถูกต้อง: {date_a_str} (ใช้ YYYY-MM-DD)"
        else:
            target_a = date.today()

        # Parse date B
        try:
            target_b = datetime.strptime(date_b_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            return f"รูปแบบวันที่ไม่ถูกต้อง: {date_b_str} (ใช้ YYYY-MM-DD)"

        # ดึงข้อมูลทั้ง 2 วัน (ข้ามวันหยุด)
        try:
            actual_a, fuels_a = _find_latest_ptt_date(target_a)
        except ValueError:
            return f"ไม่พบข้อมูลราคาน้ำมัน ปตท. ณ วันที่ {target_a.strftime('%d/%m/%Y')} หรือวันใกล้เคียง"

        try:
            actual_b, fuels_b = _find_latest_ptt_date(target_b)
        except ValueError:
            return f"ไม่พบข้อมูลราคาน้ำมัน ปตท. ณ วันที่ {target_b.strftime('%d/%m/%Y')} หรือวันใกล้เคียง"

        # จับคู่ fuel type
        map_a = {f["product"]: float(f["price"]) for f in fuels_a}
        map_b = {f["product"]: float(f["price"]) for f in fuels_b}

        # ใช้ลำดับจาก fuels_a เป็นหลัก
        common = [p for p in map_a if p in map_b]
        if not common:
            return "ไม่พบประเภทน้ำมันที่ตรงกันระหว่าง 2 วัน"

        label_a = actual_a.strftime("%d/%m/%Y")
        label_b = actual_b.strftime("%d/%m/%Y")

        lines = [
            "เปรียบเทียบราคาน้ำมัน ปตท.",
            f"{label_a} vs {label_b}",
            "",
            f"{'ประเภท':<28} {'ราคา A':>8}  {'ราคา B':>8}  {'ผลต่าง':>8}",
            "-" * 60,
        ]

        diffs = []
        for product in common:
            price_a = map_a[product]
            price_b = map_b[product]
            diff = price_b - price_a
            diffs.append(diff)
            sign = "+" if diff > 0 else ""
            lines.append(
                f"{product:<28} {price_a:>8.2f}  {price_b:>8.2f}  {sign}{diff:>7.2f}"
            )

        avg_diff = sum(diffs) / len(diffs)
        sign = "+" if avg_diff > 0 else ""
        direction = "เพิ่มขึ้น" if avg_diff > 0 else ("ลดลง" if avg_diff < 0 else "ไม่เปลี่ยนแปลง")
        lines.append("")
        lines.append(f"สรุป: ราคาเฉลี่ย{direction} {sign}{avg_diff:.2f} บาท/ประเภท")
        lines.append("")
        lines.append(_NOTE_BANGKOK_RETAIL)

        result = "\n".join(lines)

        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", f"compare {actual_a.isoformat()} vs {actual_b.isoformat()}", kind="tool_command"),
            **db.make_log_field("output", result[:200], kind="tool_result"),
        )
        return result

    # ----- Usage / Help -----

    def _usage(self) -> str:
        return (
            "เช็คราคาน้ำมัน:\n"
            "  /oil            -- ราคาล่าสุด (บางจาก วันนี้+พรุ่งนี้)\n"
            "  /oil ptt        -- ราคาล่าสุด (ปตท. พร้อมการเปลี่ยนแปลง)\n"
            "  /oil 2026-01-15 -- ราคาย้อนหลัง (ปตท.)\n"
            "  /oil 15/1/2026  -- ราคาย้อนหลัง (ปตท.)\n"
            "\nหรือพิมพ์: ราคาน้ำมันวันนี้, น้ำมันเท่าไหร่"
        )

    # ----- Tool Spec -----

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                # Positive
                "เช็คราคาน้ำมันปัจจุบัน (บางจาก/ปตท.) ราคาย้อนหลัง และเปรียบเทียบราคา 2 วัน. "
                # Negative boundary
                "ไม่ใช่สำหรับอัตราแลกเปลี่ยนเงินตรา (ใช้ exchange_rate) "
                "และไม่ใช่สำหรับค้นหาสถานีบริการ/ปั๊มน้ำมัน (ใช้ places). "
                # Examples
                "เช่น 'ราคาน้ำมันวันนี้', 'น้ำมันเท่าไหร่', 'ดีเซลราคาเท่าไหร่', "
                "'ราคาน้ำมันเมื่อวาน', 'ราคาน้ำมัน ปตท', "
                "'ราคาน้ำมัน 1 ม.ค. กับวันนี้ ต่างกันเท่าไหร่', "
                "'เทียบน้ำมันเดือนที่แล้วกับเดือนนี้'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "แหล่งข้อมูล: 'ptt' หรือ 'ปตท' สำหรับราคา ปตท. "
                            "หรือ 'bangchak' หรือ 'บางจาก' สำหรับราคาบางจาก "
                            "ถ้าว่าง = แสดงราคาบางจาก (วันนี้+พรุ่งนี้)"
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "วันที่สำหรับราคาย้อนหลัง (ปตท.) รูปแบบ YYYY-MM-DD "
                            "เช่น '2026-01-15' "
                            "ถ้าไม่ระบุ = ราคาล่าสุด"
                        ),
                    },
                    "compare_date": {
                        "type": "string",
                        "description": (
                            "วันที่สำหรับเปรียบเทียบ (YYYY-MM-DD) "
                            "เมื่อ user ถามเปรียบเทียบ 2 วัน ให้ใส่วันแรกใน date "
                            "และวันที่สองใน compare_date "
                            "เช่น ถาม 'ราคาน้ำมัน 1 ม.ค. กับวันนี้' "
                            "→ date='2025-01-01', compare_date='2026-04-02'"
                        ),
                    },
                },
                "required": [],
            },
        }
