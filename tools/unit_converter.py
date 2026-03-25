"""Unit converter tool with Thai units."""

import re

from core import db
from core.logger import get_logger
from tools.base import BaseTool

log = get_logger(__name__)

LENGTH_TO_M = {
    "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
    "in": 0.0254, "inch": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344,
    "วา": 2.0, "ศอก": 0.5, "คืบ": 0.25, "นิ้วไทย": 0.0208333333,
}
WEIGHT_TO_G = {
    "g": 1.0, "kg": 1000.0, "lb": 453.59237, "oz": 28.349523125,
    "สลึง": 3.811, "บาททอง": 15.244, "ตำลึง": 60.976, "ชั่ง": 1219.52,
}
VOLUME_TO_L = {
    "ml": 0.001, "l": 1.0, "liter": 1.0,
    "ทะนาน": 1.0, "ถัง": 20.0, "เกวียน": 2000.0,
}
AREA_TO_M2 = {
    "ตร.ว.": 4.0, "ตารางวา": 4.0, "งาน": 400.0, "ไร่": 1600.0, "sqm": 1.0, "m2": 1.0,
}

UNIT_ALIASES = {
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
    "mile": "mi", "miles": "mi",
    "inch": "inch", "inches": "inch",
    "foot": "ft", "feet": "ft",
    "yard": "yd", "yards": "yd",
    "gram": "g", "grams": "g",
    "kilogram": "kg", "kilograms": "kg",
    "pound": "lb", "pounds": "lb",
    "ounce": "oz", "ounces": "oz",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "liter": "liter", "liters": "liter", "litre": "liter", "litres": "liter",
    "squaremeter": "m2", "squaremeters": "m2", "squaremetre": "m2", "squaremetres": "m2",
}


def _normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    normalized = unit.strip().lower()
    return UNIT_ALIASES.get(normalized, normalized)


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    from_u = from_unit.lower()
    to_u = to_unit.lower()
    if from_u == to_u:
        return value
    if from_u == "c":
        celsius = value
    elif from_u == "f":
        celsius = (value - 32.0) * 5.0 / 9.0
    elif from_u == "k":
        celsius = value - 273.15
    else:
        raise ValueError(f"ไม่รองรับอุณหภูมิหน่วย {from_unit}")

    if to_u == "c":
        return celsius
    if to_u == "f":
        return celsius * 9.0 / 5.0 + 32.0
    if to_u == "k":
        return celsius + 273.15
    raise ValueError(f"ไม่รองรับอุณหภูมิหน่วย {to_unit}")


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


class UnitConverterTool(BaseTool):
    name = "unit_converter"
    description = "แปลงหน่วยไทยและสากล เช่น ไร่เป็นตารางเมตร, บาททองเป็นกรัม, km เป็น mi, C เป็น F"
    commands = ["/convert", "/unit"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        query = (args or "").strip()
        if not query:
            return self._usage()

        try:
            result = self._convert(query)
            db.log_tool_usage(
                user_id,
                self.name,
                status="success",
                **db.make_log_field("input", query, kind="conversion_query"),
                **db.make_log_field("output", result, kind="conversion_result"),
            )
            return result
        except (TypeError, ValueError) as e:
            log.error("Unit converter failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id,
                self.name,
                status="failed",
                **db.make_log_field("input", query, kind="conversion_query"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ แปลงหน่วยไม่สำเร็จ: {e}\n\n{self._usage()}"

    def _convert(self, query: str) -> str:
        land_match = re.match(r"^(\d+)-(\d+)-(\d+)(?:\s*(?:เป็น|to|->|→)?\s*([^\s]+))?$", query, re.IGNORECASE)
        if land_match:
            rai, ngan, sq_wa = map(int, land_match.groups()[:3])
            to_unit = land_match.group(4) or "ตารางเมตร"
            if to_unit.lower() not in ("ตารางเมตร", "sqm", "m2", "ตร.ม."):
                raise ValueError(f"ไม่รองรับการแปลงพื้นที่เป็น {to_unit}")
            total_m2 = rai * 1600 + ngan * 400 + sq_wa * 4
            return f"📐 {rai}-{ngan}-{sq_wa} = {_format_number(total_m2)} {to_unit}"

        thai_land_match = re.match(r"^(?:([\d.]+)\s*ไร่)?\s*(?:([\d.]+)\s*งาน)?\s*(?:([\d.]+)\s*(?:ตร\.ว\.|ตารางวา))?(?:\s*(?:เป็น|to|->|→)?\s*([^\s]+))?$", query, re.IGNORECASE)
        if thai_land_match and any(thai_land_match.groups()[:3]):
            r_str, n_str, w_str, t_unit = thai_land_match.groups()
            rai = float(r_str) if r_str else 0.0
            ngan = float(n_str) if n_str else 0.0
            sq_wa = float(w_str) if w_str else 0.0
            to_unit = t_unit or "ตารางเมตร"
            
            if to_unit.lower() not in ("ตารางเมตร", "sqm", "m2", "ตร.ม."):
                raise ValueError(f"ไม่รองรับการแปลงพื้นที่เป็น {to_unit}")
            
            total_m2 = rai * 1600 + ngan * 400 + sq_wa * 4
            
            parts = []
            if rai > 0:
                parts.append(f"{_format_number(rai)} ไร่")
            if ngan > 0:
                parts.append(f"{_format_number(ngan)} งาน")
            if sq_wa > 0:
                parts.append(f"{_format_number(sq_wa)} ตารางวา")
            
            input_str = " ".join(parts)
            return f"📐 {input_str} = {_format_number(total_m2)} {to_unit}"

        match = re.match(r"^([\d.]+)\s*([^\s]+)(?:\s*(?:เป็น|to|->|→)\s*([^\s]+))?$", query, re.IGNORECASE)
        if not match:
            raise ValueError("รูปแบบไม่ถูกต้อง")

        value = float(match.group(1))
        from_unit = _normalize_unit(match.group(2)) or ""
        to_unit = _normalize_unit(match.group(3))

        if from_unit in ("c", "f", "k") or (to_unit and to_unit in ("c", "f", "k")):
            if not to_unit:
                to_unit = "c" if from_unit in ("f", "k") else "f"
            converted = _convert_temperature(value, from_unit, to_unit)
            return f"🌡 {_format_number(value)} {from_unit.upper()} = {_format_number(converted)} {to_unit.upper()}"

        if from_unit in LENGTH_TO_M and (to_unit in LENGTH_TO_M or not to_unit):
            to_unit = to_unit or "m"
            converted = value * LENGTH_TO_M[from_unit] / LENGTH_TO_M[to_unit]
            return f"📏 {_format_number(value)} {from_unit} = {_format_number(converted)} {to_unit}"

        if from_unit in WEIGHT_TO_G and (to_unit in WEIGHT_TO_G or not to_unit):
            to_unit = to_unit or "g"
            converted = value * WEIGHT_TO_G[from_unit] / WEIGHT_TO_G[to_unit]
            return f"⚖️ {_format_number(value)} {from_unit} = {_format_number(converted)} {to_unit}"

        if from_unit in VOLUME_TO_L and (to_unit in VOLUME_TO_L or not to_unit):
            to_unit = to_unit or "l"
            converted = value * VOLUME_TO_L[from_unit] / VOLUME_TO_L[to_unit]
            return f"🥤 {_format_number(value)} {from_unit} = {_format_number(converted)} {to_unit}"

        if from_unit in AREA_TO_M2 and (to_unit in AREA_TO_M2 or not to_unit):
            to_unit = to_unit or "m2"
            converted = value * AREA_TO_M2[from_unit] / AREA_TO_M2[to_unit]
            return f"📐 {_format_number(value)} {from_unit} = {_format_number(converted)} {to_unit}"

        if not to_unit:
            raise ValueError(f"ไม่รู้จักหน่วย {from_unit}")

        raise ValueError(f"ยังไม่รองรับการแปลง {from_unit} → {to_unit}")

    def _usage(self) -> str:
        return (
            "ตัวอย่าง:\n"
            "• /convert 10 km to mi\n"
            "• /convert 30 c to f\n"
            "• /convert 2 ไร่ เป็น ตารางเมตร\n"
            "• /convert 3 บาททอง เป็น g\n"
            "• /convert 1-2-30 เป็น ตารางเมตร"
        )

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "แปลงหน่วยไทยและสากล เช่น '/convert 10 km to mi', '/convert 2 ไร่ เป็น ตารางเมตร', '/convert 3 บาททอง เป็น g' ถ้าไม่ได้ระบุหน่วยปลายทางให้ใช้เป็นหน่วย SI Base Units เสมอ ยกเว้นอุณหภูมิให้ใช้เป็น C เสมอ",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string", "description": "ข้อความการแปลงหน่วย เช่น '10 km to mi' หรือ '2 ไร่ เป็น ตารางเมตร'"}
                },
                "required": ["args"],
            },
        }