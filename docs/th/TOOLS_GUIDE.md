# คู่มือเพิ่ม Tool ใหม่ — OpenMiniCrew

> 🇬🇧 [English version](docs/en/TOOLS_GUIDE.md)

## สารบัญ

- [ภาพรวม](#ภาพรวม)
- [ขั้นตอนเพิ่ม Tool ใหม่](#ขั้นตอนเพิ่ม-tool-ใหม่)
- [Template พื้นฐาน](#template-พื้นฐาน)
- [ตัวอย่าง 1: Tool ง่าย — พยากรณ์อากาศ](#ตัวอย่าง-1-tool-ง่าย--พยากรณ์อากาศ)
- [ตัวอย่าง 2: Tool ที่เรียก API — Google Maps](#ตัวอย่าง-2-tool-ที่เรียก-api--google-maps)
- [ตัวอย่าง 3: Tool ค้นหาสถานที่ — Google Places](#ตัวอย่าง-3-tool-ค้นหาสถานที่--google-places)
- [ตัวอย่าง 4: Tool ที่ใช้ LLM — สรุปข่าว](#ตัวอย่าง-4-tool-ที่ใช้-llm--สรุปข่าว)
- [ตัวอย่าง 5: Tool ที่ต้องการความฉลาดสูง (ใช้ LLM ระดับ Mid)](#ตัวอย่าง-5-tool-ที่ต้องการความฉลาดสูง-ใช้-llm-ระดับ-mid)
- [รายละเอียดสำคัญ](#รายละเอียดสำคัญ)
- [Checklist ก่อน Deploy](#checklist-ก่อน-deploy)
- [Tools ที่มีอยู่แล้ว](#tools-ที่มีอยู่แล้ว)
- [แนวคิด Tool ที่น่าสนใจ](#แนวคิด-tool-ที่น่าสนใจ)

---

## ภาพรวม

ระบบ Tool ของ OpenMiniCrew ออกแบบให้เพิ่มง่าย:

```
สร้างไฟล์ .py ใหม่ใน tools/
         │
         ▼
registry auto-discover → ลงทะเบียนอัตโนมัติ
         │
         ▼
ใช้งานได้ทันที 2 แบบ:
  1. /command → เรียก tool ตรง (ไม่เสีย LLM token)
  2. พิมพ์อิสระ → LLM เลือก tool ให้ (function calling)
```

**ไม่ต้องแก้ไฟล์ core ใดๆ** — แค่สร้างไฟล์เดียวใน `tools/`

---

## ขั้นตอนเพิ่ม Tool ใหม่

### Step 1: สร้างไฟล์ใน `tools/`

```bash
touch tools/my_tool.py
```

> ⚠️ ชื่อไฟล์ห้ามซ้ำกับ `base.py`, `registry.py`, `__init__.py`

### Step 2: เขียน class ที่ inherit `BaseTool`

```python
from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"           # ชื่อ tool (unique)
    description = "คำอธิบาย"    # LLM ใช้ตัดสินใจเลือก tool
    commands = ["/mytool"]     # คำสั่งตรง (ไม่เสีย token)
    direct_output = True       # True = ส่งผลตรง, False = ให้ LLM สรุปอีกที
    preferred_tier = "cheap"   # cheap = Haiku/Flash, mid = Sonnet/Pro

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        # ทำงานหลัก
        return "ผลลัพธ์"
```

### Step 3: (Optional) เพิ่ม dependencies

```bash
# ถ้า tool ต้องใช้ library ใหม่
pip install some-library
echo "some-library" >> requirements.txt
```

### Step 4: (Optional) เพิ่ม config ใหม่ใน `.env`

```bash
# เพิ่มใน .env
GOOGLE_MAPS_API_KEY=xxx

# เพิ่มใน core/config.py
GOOGLE_MAPS_API_KEY = _optional("GOOGLE_MAPS_API_KEY", "")

# เพิ่มใน .env.example ด้วย
```

### Step 5: รีสตาร์ท bot

```bash
# Ctrl+C แล้วรันใหม่
python main.py
# จะเห็น log: Registered tool: my_tool (commands: ['/mytool'])
```

---

## Template พื้นฐาน

```python
"""My Tool — คำอธิบายสั้นๆ"""

import requests          # ถ้าต้องเรียก API
from tools.base import BaseTool
from core import db
from core.logger import get_logger

log = get_logger(__name__)


class MyTool(BaseTool):
    name = "my_tool"
    description = "คำอธิบายที่ LLM จะใช้ตัดสินใจว่าจะเรียก tool นี้เมื่อไหร่"
    commands = ["/mytool"]
    direct_output = True       # True = ส่งผลตรงๆ, False = ส่งให้ LLM สรุปอีกที
    preferred_tier = "cheap"   # cheap = Haiku/Flash, mid = Sonnet/Pro (ใช้เมื่อ tool เรียก LLM เอง)

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        """
        ฟังก์ชันหลัก — ถูกเรียกเมื่อ user ใช้ /command หรือ LLM เลือก tool นี้

        Parameters:
            user_id: Telegram chat ID ของ user (string)
            args: ข้อความที่ตามหลัง command เช่น "/mytool hello" → args = "hello"
            **kwargs: parameter เพิ่มเติมที่ LLM ส่งมา

        Returns:
            string ที่จะส่งกลับให้ user
        """
        if not args:
            return "กรุณาระบุ... เช่น /mytool xxx"

        try:
            # === ทำงานหลัก ===
            result = f"ผลลัพธ์สำหรับ: {args}"

            # === Log usage (แนะนำ) ===
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", args, kind="tool_command"),
                **db.make_log_field("output", result, kind="tool_result"),
            )

            return result

        except Exception as e:
            log.error(f"MyTool failed for {user_id}: {e}")
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="failed",
                **db.make_log_field("input", args, kind="tool_command"),
                **db.make_error_fields(str(e)),
            )
            return f"เกิดข้อผิดพลาด: {e}"

    def get_tool_spec(self) -> dict:
        """
        บอก LLM ว่า tool นี้รับ parameter อะไร
        LLM Router จะแปลง format ให้ตรง provider (Claude/Gemini) อัตโนมัติ
        """
        return {
            "name": self.name,               # ❗ ใช้ self.name เสมอ ห้าม hardcode
            "description": "คำอธิบายที่ LLM จะใช้ตัดสินใจ",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "อธิบายว่า parameter นี้คืออะไร",
                    }
                },
                "required": [],
            },
        }
```

หมายเหตุเรื่อง structured logging:

- ควรใช้ `db.make_log_field(...)` สำหรับ input และ output metadata แทนการเก็บ `input_summary` และ `output_summary` แบบ raw text
- ควรใช้ `db.make_error_fields(...)` เพื่อเก็บ error metadata ที่ redact แล้ว แทนการเก็บ exception text ตรง ๆ
- ควรตั้งค่า `kind` ให้สม่ำเสมอ เช่น `tool_command`, `tool_result`, `search_query`, หรือ `media_image` เพื่อให้ log ยังวิเคราะห์ต่อได้หลังทำ minimization

---

## ตัวอย่าง 1: Tool ง่าย — พยากรณ์อากาศ

ใช้ Open-Meteo API (ฟรี ไม่ต้อง API key)

```python
# tools/weather.py
"""Weather Tool — พยากรณ์อากาศวันนี้"""

import requests
from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)

# พิกัดเมืองหลัก
CITIES = {
    "กรุงเทพ": (13.75, 100.50),
    "bangkok": (13.75, 100.50),
    "เชียงใหม่": (18.79, 98.98),
    "ภูเก็ต": (7.88, 98.39),
    "ขอนแก่น": (16.43, 102.83),
}


class WeatherTool(BaseTool):
    name = "weather"
    description = "พยากรณ์อากาศวันนี้ ระบุชื่อเมืองได้"
    commands = ["/weather"]

    async def execute(self, user_id: str, args: str = "") -> str:
        city = args.strip().lower() if args else "กรุงเทพ"

        # หาพิกัด
        coords = CITIES.get(city)
        if not coords:
            # ลอง match ภาษาไทย
            for name, c in CITIES.items():
                if city in name.lower():
                    coords = c
                    city = name
                    break

        if not coords:
            cities_list = ", ".join(CITIES.keys())
            return f"ไม่รู้จักเมือง '{args}'\nเมืองที่รองรับ: {cities_list}"

        lat, lon = coords

        try:
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                    "timezone": "Asia/Bangkok",
                },
                timeout=10,
            )
            data = resp.json().get("current", {})

            temp = data.get("temperature_2m", "?")
            humidity = data.get("relative_humidity_2m", "?")
            wind = data.get("wind_speed_10m", "?")

            return (
                f"🌤 สภาพอากาศ{city}ตอนนี้:\n"
                f"🌡 อุณหภูมิ: {temp}°C\n"
                f"💧 ความชื้น: {humidity}%\n"
                f"💨 ลม: {wind} km/h"
            )

        except Exception as e:
            log.error(f"Weather API error: {e}")
            return f"ดึงข้อมูลอากาศไม่ได้: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "พยากรณ์อากาศวันนี้ตามเมืองที่ระบุ",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "ชื่อเมือง เช่น กรุงเทพ, เชียงใหม่, ภูเก็ต",
                    }
                },
                "required": [],
            },
        }
```

**ใช้งาน:**
```
/weather กรุงเทพ
/weather เชียงใหม่
หรือพิมพ์: "อากาศวันนี้เป็นยังไง"
```

---

## ตัวอย่าง 2: Tool ที่เรียก API — Google Maps

เช็คเส้นทาง + สภาพจราจร + เวลาเดินทาง ผ่าน Google Maps Directions API และ Routes API

### Step 1: ตั้งค่า

```bash
# เพิ่มใน .env
GOOGLE_MAPS_API_KEY=AIzaSyXxx
```

```python
# เพิ่มใน core/config.py
GOOGLE_MAPS_API_KEY = _optional("GOOGLE_MAPS_API_KEY", "")
```

### Step 2: สร้าง Tool

> ตัวอย่างนี้ย่อจาก `tools/traffic.py` จริง เพื่อแสดงโครงสร้างหลัก

```python
# tools/traffic.py
"""Traffic Tool — เช็คเส้นทาง สภาพจราจร และเวลาเดินทาง ผ่าน Google Maps"""

import re
import urllib.parse

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# Separators สำหรับแยกต้นทาง-ปลายทาง
SEPARATORS = [" ไป ", " to ", "→", "➡", " ถึง ", "|"]

# Regex สำหรับตรวจจับโหมดจากภาษาไทย
_MODE_FALLBACK = [
    (re.compile(r"มอเตอร์ไซค์|มอไซค์|motorcycle|motorbike", re.IGNORECASE), "two_wheeler"),
    (re.compile(r"เดินเท้า|เดิน(?!ทาง)|walking|on\s+foot", re.IGNORECASE), "walking"),
    (re.compile(r"รถโดยสาร|ขนส่งสาธารณะ|รถเมล์|รถไฟฟ้า|transit|bus|bts|mrt", re.IGNORECASE), "transit"),
]


class TrafficTool(BaseTool):
    name = "traffic"
    description = "เช็คเส้นทาง สภาพจราจร และเวลาการเดินทางระหว่างสองจุด ผ่าน Google Maps"
    commands = ["/traffic", "/route"]
    direct_output = True

    async def execute(self, user_id: str, args: str = "", mode: str = "driving", **kwargs) -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "ยังไม่ได้ตั้งค่า GOOGLE_MAPS_API_KEY ใน .env"

        if not args:
            return (
                "กรุณาระบุต้นทางและปลายทาง เช่น:\n"
                "/traffic สยาม ไป สีลม\n"
                "/traffic บ้าน ไป สนามบิน เดินเท้า\n"
                "/traffic สยาม ไป อโศก มอไซค์"
            )

        # แยกต้นทาง-ปลายทาง (รองรับหลาย separator)
        origin, destination = None, None
        for sep in SEPARATORS:
            if sep in args:
                parts = args.split(sep, 1)
                origin, destination = parts[0].strip(), parts[1].strip()
                break

        if not origin or not destination:
            return "กรุณาระบุ: /traffic [ต้นทาง] ไป [ปลายทาง]"

        # ตรวจจับโหมดจากข้อความ (เช่น "มอไซค์", "เดินเท้า")
        for pattern, detected_mode in _MODE_FALLBACK:
            if pattern.search(args):
                mode = detected_mode
                break

        try:
            # เรียก API ตามโหมด
            if mode == "two_wheeler":
                # ใช้ Routes API (New) สำหรับมอเตอร์ไซค์
                result = self._call_routes_api(origin, destination)
            else:
                # ใช้ Directions API สำหรับ driving/walking/transit
                result = self._call_directions_api(origin, destination, mode)

            db.log_tool_usage(user_id, self.name, args[:100], result[:200], "success")
            return result

        except Exception as e:
            log.error(f"Traffic API error: {e}")
            db.log_tool_usage(user_id, self.name, args[:100], status="failed", error_message=str(e))
            return f"เกิดข้อผิดพลาด: {e}"

    def _call_directions_api(self, origin, destination, mode):
        """เรียก Google Maps Directions API"""
        params = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "departure_time": "now",
            "alternatives": "true",
            "language": "th",
            "region": "th",
            "key": GOOGLE_MAPS_API_KEY,
        }
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params=params, timeout=15,
        )
        data = resp.json()
        if data["status"] != "OK":
            return f"หาเส้นทางไม่ได้: {data['status']}"

        # จัดรูปแบบผลลัพธ์ (เส้นทาง, ระยะทาง, เวลา, จราจร, ลิงก์ Google Maps)
        # ... (ย่อ — ดู source จริงใน tools/traffic.py)
        route = data["routes"][0]
        leg = route["legs"][0]
        return f"🗺 {leg['start_address']} → {leg['end_address']}\n📏 {leg['distance']['text']} ⏱ {leg['duration']['text']}"

    def _call_routes_api(self, origin, destination):
        """เรียก Routes API (New) สำหรับ two_wheeler"""
        # POST https://routes.googleapis.com/directions/v2:computeRoutes
        # ... (ย่อ — ดู source จริงใน tools/traffic.py)
        return "🏍 เส้นทางมอเตอร์ไซค์..."

    def get_tool_spec(self) -> dict:
        return {
            "name": "traffic",
            "description": (
                "ใช้เช็คเส้นทาง ระยะทาง เวลาเดินทาง และสภาพจราจร real-time "
                "ระหว่างสองจุด ผ่าน Google Maps"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "ต้นทางและปลายทาง คั่นด้วย 'ไป' เช่น "
                            "'สยาม ไป สีลม', 'Central World ไป สุวรรณภูมิ'"
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["driving", "walking", "transit", "two_wheeler"],
                        "description": (
                            "โหมดการเดินทาง: driving=รถยนต์, walking=เดินเท้า, "
                            "transit=รถโดยสาร, two_wheeler=มอเตอร์ไซค์"
                        ),
                    },
                },
                "required": ["args"],
            },
        }
```

**ฟีเจอร์หลักของ Traffic Tool (ใน code จริง):**

- เลือก**โหมด**ได้: รถยนต์, เดินเท้า, ขนส่งสาธารณะ, มอเตอร์ไซค์
- **หลีกเลี่ยงทางด่วน**: "ไม่ขึ้นทางด่วน" หรือเจาะจง "ไม่ขึ้น ดอนเมืองโทลเวย์"
- **แถวนี้**: ตรวจจับ GPS ของ user (เช่น "ไปสยาม" = จากตรงนี้ไปสยาม)
- **เส้นทางทางเลือก**: แสดงได้สูงสุด 3 เส้นทาง
- **Google Maps URL**: ลิงก์กดเปิดแผนที่ได้เลย
- ใช้ **Directions API** (driving/walking/transit) + **Routes API New** (two_wheeler)

**ใช้งาน:**
```
/traffic สยาม ไป สีลม
/traffic สยาม ไป อโศก มอไซค์
/traffic สยาม ไป สีลม เดินเท้า
/traffic จันทน์ ไป แจ้งวัฒนะ ไม่ขึ้นทางด่วน
/route บ้าน ไป สนามบิน
หรือพิมพ์: "จากสยามไปสีลมใช้เวลาเท่าไหร่ รถติดไหม"
```

---

## ข้อกำหนดและทางเลือกของ Google Maps API

### 📋 Google Maps APIs ที่ใช้ในโปรเจกต์นี้

โปรเจกต์ปัจจุบันใช้ APIs เหล่านี้ (ต้อง enable ใน Google Cloud Console):

- **Directions API** — คำนวณเส้นทาง (driving, walking, transit)
- **Routes API** — เส้นทางมอเตอร์ไซค์ (two_wheeler)
- **Places API (New)** — ค้นหาสถานที่ (Text Search)
- **Geocoding API** — แปลงชื่อสถานที่เป็นพิกัด

#### สำหรับเพิ่มฟีเจอร์เพิ่มเติม

- **Distance Matrix API** — คำนวณระยะทาง/เวลาระหว่างหลายจุด
- **Geolocation API** — ตรวจจับตำแหน่งปัจจุบันของผู้ใช้
- **Maps JavaScript API** (ถ้าต้องการแสดงแผนที่บนเว็บ) — มี Traffic Layer สำหรับจราจร real-time

### 💳 ข้อกำหนดเรื่อง Billing

**สำคัญ:** Google Maps APIs ต้องเปิด **Billing Account** (ใส่บัตรเครดิต) ถึงจะใช้ได้ แม้จะมี free tier ที่เยอะก็ตาม

| ประเด็น             | รายละเอียด                                              |
|---------------------|--------------------------------------------------------|
| **Billing Account** | **จำเป็น** — ต้องเพิ่มบัตรเครดิตใน Google Cloud        |
| **Free Tier**       | $200/เดือน (ใช้ได้ประมาณ 40,000 requests)             |
| **Personal Use**    | ใช้แบบส่วนตัวไม่เกิน free tier แน่นอน                  |
| **ค่าใช้จ่าย**      | ไม่มีค่าใช้จ่ายถ้าไม่เกิน free tier                    |

**เปรียบเทียบกับ Tools ที่มีอยู่:**

- ✅ Gmail API — ใช้ OAuth อย่างเดียว **ไม่ต้อง billing**
- ✅ Google News RSS — **ไม่ต้อง API key** ฟรีสนิท
- ✅ Bank of Thailand API — **ไม่ต้อง billing** ใช้ token ฟรี
- ✅ Rayriffy Lotto API — **ไม่ต้อง API key** ฟรี
- ❌ Google Maps/Places APIs — **ต้อง billing account** (แต่มี free tier)

### 🆓 ทางเลือก APIs ฟรี (ไม่ต้อง Billing)

ถ้าไม่อยากใส่บัตรเครดิต มี **ทางเลือกฟรี 100%**:

#### สำหรับเส้นทาง + จราจร

| API                    | Free Tier              | ข้อมูลจราจร                    | หมายเหตุ             |
|------------------------|------------------------|-------------------------------|---------------------|
| **OpenRouteService**   | 2,500 requests/วัน     | Traffic patterns (ไม่ real-time) | ไม่ต้อง billing     |
| **Mapbox Directions**  | 100,000 requests/เดือน | Traffic patterns              | ไม่ต้องบัตรเครดิต   |
| **OSRM** (self-hosted) | Unlimited              | ไม่มีข้อมูลจราจร              | ต้อง hosting เอง    |

#### สำหรับค้นหาสถานที่

| API                   | Free Tier              | ฟีเจอร์                                          | หมายเหตุ                |
|-----------------------|------------------------|--------------------------------------------------|------------------------|
| **Foursquare Places** | 100,000 requests/วัน   | ข้อมูล POI ละเอียด, wifi, ปลั๊กไฟ              | ทางเลือกฟรีที่ดี       |
| **Overpass API**      | Unlimited              | ข้อมูล OpenStreetMap                             | ข้อมูลดิบ ต้องประมวลผลเอง |
| **Mapbox Search**     | 100,000 requests/เดือน | เหมาะสำหรับค้นหาที่อยู่                          | ข้อมูล POI จำกัด       |

---

## ตัวอย่าง 3: Tool ค้นหาสถานที่ — Google Places

ค้นหาสถานที่ใกล้เคียง ผ่าน Google Places API (New) — Text Search

> ตัวอย่างนี้ย่อจาก `tools/places.py` จริง

```python
# tools/places.py
"""Places Tool — ค้นหาสถานที่ใกล้เคียง ผ่าน Google Places API (New)"""

import re

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# Price level mapping จาก Places API (New)
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "ฟรี",
    "PRICE_LEVEL_INEXPENSIVE": "💰 ราคาถูก",
    "PRICE_LEVEL_MODERATE": "💰💰 ปานกลาง",
    "PRICE_LEVEL_EXPENSIVE": "💰💰💰 แพง",
    "PRICE_LEVEL_VERY_EXPENSIVE": "💰💰💰💰 แพงมาก",
}


class PlacesTool(BaseTool):
    name = "places"
    description = "ค้นหาสถานที่ใกล้เคียง เช่น ร้านกาแฟ ร้านอาหาร โรงพยาบาล ร้านสะดวกซื้อ"
    commands = ["/places", "/nearby", "/search"]
    direct_output = True

    # คำที่บ่งบอกว่าผู้ใช้หมายถึง "ตรงนี้" (ต้องใช้ GPS)
    _NEARBY_KEYWORDS = re.compile(r"(แถวนี้|ใกล้นี้|ตรงนี้|nearby|near me)")
    _OPEN_NOW_KEYWORDS = re.compile(r"(เปิดอยู่|เปิดตอนนี้|open now|ยังเปิด|เปิดไหม)")
    _BANGKOK_CENTER = {"latitude": 13.7563, "longitude": 100.5018}

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "ยังไม่ได้ตั้งค่า GOOGLE_MAPS_API_KEY ใน .env"

        if not args:
            return (
                "กรุณาระบุสิ่งที่ต้องการค้นหา:\n"
                "/places ร้านกาแฟแถวสยาม\n"
                "/places ร้านอาหารเปิดอยู่แถวนี้"
            )

        try:
            # ตรวจจับ "เปิดอยู่" → openNow filter
            open_now = bool(self._OPEN_NOW_KEYWORDS.search(args))

            # สร้าง location bias (circle รอบตำแหน่งผู้ใช้หรือกรุงเทพ)
            location_bias = {
                "circle": {
                    "center": self._BANGKOK_CENTER,
                    "radius": 30000.0,  # 30km
                }
            }

            # เรียก Google Places API (New) — Text Search
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": (
                    "places.displayName,places.formattedAddress,places.rating,"
                    "places.userRatingCount,places.currentOpeningHours,"
                    "places.priceLevel,places.googleMapsUri"
                ),
            }

            body = {
                "textQuery": args,
                "languageCode": "th",
                "locationBias": location_bias,
                "maxResultCount": 10,
            }
            if open_now:
                body["openNow"] = True

            resp = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=body,
                timeout=10,
            )
            data = resp.json()
            results = data.get("places", [])

            if not results:
                return f"ไม่พบสถานที่สำหรับ: {args}"

            # จัดรูปแบบผลลัพธ์
            output = f"📍 พบ {len(results)} สถานที่:\n\n"
            for i, place in enumerate(results[:5], 1):
                name = place.get("displayName", {}).get("text", "ไม่ระบุ")
                address = place.get("formattedAddress", "")
                rating = place.get("rating")
                stars = "⭐" * int(rating) if rating else ""
                maps_url = place.get("googleMapsUri", "")

                output += f"{i}. {name} {stars}\n"
                output += f"   📍 {address}\n"
                if maps_url:
                    output += f"   🔗 {maps_url}\n"
                output += "\n"

            db.log_tool_usage(user_id, self.name, args[:100], status="success")
            return output

        except Exception as e:
            log.error(f"Places API error: {e}")
            db.log_tool_usage(user_id, self.name, args[:100], status="failed", error_message=str(e))
            return f"เกิดข้อผิดพลาด: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "places",
            "description": (
                "ค้นหาสถานที่ใกล้เคียง เช่น 'ร้านกาแฟแถวสยาม', "
                "'restaurant near Sukhumvit', 'โรงพยาบาลใกล้ลาดพร้าว'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "สิ่งที่ต้องการค้นหา พร้อมสถานที่ เช่น "
                            "'ร้านกาแฟแถวสยาม', 'restaurant near Sukhumvit'"
                        ),
                    }
                },
                "required": ["args"],
            },
        }
```

**ฟีเจอร์หลักของ Places Tool (ใน code จริง):**

- ใช้ **Google Places API (New)** — Text Search endpoint
- **Location Bias**: ใช้ GPS ของ user (ถ้ามี) หรือ fallback กรุงเทพ 30km
- **Open Now Filter**: ตรวจจับ "เปิดอยู่", "open now" แล้วกรองเฉพาะที่เปิด
- แสดง: ชื่อ, rating, ที่อยู่, เวลาเปิด-ปิด, ราคา, เบอร์โทร, เว็บไซต์, Google Maps link

**ใช้งาน:**
```
/places ร้านกาแฟแถวสยาม
/places ร้านอาหารเปิดอยู่แถวนี้
/search ATM ใกล้ MBK
/nearby โรงพยาบาลใกล้ลาดพร้าว
หรือพิมพ์: "หาร้านกาแฟมีปลั๊กไฟแถวนี้"
```

---

## ตัวอย่าง 4: Tool ที่ใช้ LLM — สรุปข่าว

ดึงข่าวจาก Google News RSS แล้วให้ LLM สรุป

> ตัวอย่างนี้ย่อจาก `tools/news_summary.py` จริง

```python
# tools/news_summary.py
"""News Summary Tool — ดึงข่าวจาก Google News RSS + สรุปด้วย LLM"""

import urllib.parse
import xml.etree.ElementTree as ET

import requests

from tools.base import BaseTool
from core.llm import llm_router
from core.user_manager import get_user, get_preference
from core.logger import get_logger

log = get_logger(__name__)


class NewsSummaryTool(BaseTool):
    name = "news_summary"
    description = "สรุปข่าวเด่นวันนี้ หรือหาข่าวตามเรื่องที่สนใจจาก Google News"
    commands = ["/news"]
    # direct_output = True (default) — tool สรุปด้วย LLM เองแล้ว ส่งผลตรงๆ

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "ค้นหาและสรุปข่าวล่าสุดจาก Google News ค้นหาตาม keyword หรือดูข่าวเด่นทั่วไปได้",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "หัวข้อข่าวที่สนใจ เช่น 'เทคโนโลยี', 'การเมือง', 'หุ้น', หรือปล่อยว่าง",
                    }
                },
            },
        }

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        topic = (args or "").strip()

        # 1. เลือก RSS URL ตามการค้นหา
        if topic:
            query = urllib.parse.quote(topic)
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
            display_label = f"หัวข้อ: {topic}"
        else:
            rss_url = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
            display_label = "ข่าวเด่นทั่วไป"

        # 2. ดึงข้อมูล RSS
        try:
            resp = requests.get(rss_url, timeout=10)
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            items = root.findall("./channel/item")

            if not items:
                return f"ไม่พบข่าวสำหรับ {display_label}"

            # 3. คัด 10 ข่าวล่าสุด + แยกชื่อสำนักข่าวออก
            max_news = 10
            headlines = []
            references = []

            for i, item in enumerate(items[:max_news], 1):
                title = item.findtext("title")
                link = item.findtext("link")

                if title and " - " in title:
                    clean_title = title.rsplit(" - ", 1)[0]
                    source = title.rsplit(" - ", 1)[1].strip()
                else:
                    clean_title = title or ""
                    source = "อ่านข่าว"

                headlines.append(f"[{i}] {clean_title}")
                references.append(f"{i}. [{source}]({link})")

            headlines_text = "\n".join(headlines)

        except Exception as e:
            log.error(f"Failed to fetch Google News: {e}")
            return "❌ ดึงข้อมูลข่าวไม่ได้ ลองใหม่อีกครั้ง"

        # 4. สรุปด้วย LLM (ส่งแค่หัวข้อ ไม่ส่ง URL)
        user = get_user(user_id) or {}
        provider = get_preference(user, "default_llm")

        system_prompt = (
            "คุณเป็นผู้ประกาศข่าวอัจฉริยะ โทนภาษา: กระชับ เป็นกันเอง\n"
            "1. จัดหมวดหมู่ข่าวที่เกี่ยวข้องเข้าด้วยกัน\n"
            "2. สรุปใจความสำคัญให้สั้นกระชับ\n"
            "3. ใส่หมายเลขอ้างอิง [1] [2] ไว้ท้ายแต่ละข่าว\n"
            "4. ไม่ต้องใส่ URL — ระบบจะแปะให้ท้ายข้อความอัตโนมัติ"
        )

        chat_resp = await llm_router.chat(
            messages=[{"role": "user", "content": f"สรุปข่าว ({display_label}):\n{headlines_text}"}],
            provider=provider,
            tier=self.preferred_tier,
            system=system_prompt,
        )

        # 5. ประกอบผลลัพธ์: สรุป + ลิงก์คลิกได้
        summary = chat_resp.get("content", "")
        refs_text = "\n".join(references)

        return f"📰 สรุปข่าว: {display_label}\n\n{summary}\n\n🔗 ลิงก์อ้างอิง:\n{refs_text}"
```

**จุดสำคัญ:**

- ใช้ **Google News RSS** (ฟรี ไม่ต้อง API key)
- **ค้นหาตาม keyword** ได้ (ไม่ใช่ category-based)
- Tool เรียก **LLM สรุปเอง** ภายใน → ใช้ `direct_output = True` (default) เพราะไม่ต้องให้ dispatcher สรุปซ้ำ
- ใช้ `self.preferred_tier` แทน hardcode `tier="cheap"`

**ใช้งาน:**
```
/news
/news เทคโนโลยี
/news การเมือง
/news หุ้น
หรือพิมพ์: "มีข่าวเทคโนโลยีอะไรใหม่บ้าง"
```

---

## ตัวอย่าง 5: Tool ที่ต้องการความฉลาดสูง (ใช้ LLM ระดับ Mid)

บางครั้งคุณอาจสร้าง Tool ที่สลับซับซ้อน เช่น การวิเคราะห์ข้อมูลเชิงลึก, สรุปเอกสารยาวๆ หรืองานเขียนโค้ด
ซึ่งโมเดลทั่วไป (Cheap) อาจตอบโจทย์ได้ไม่ดีพอ

**วิธีที่ 1: ตั้ง `preferred_tier` ระดับ class** (แนะนำ — ทุก LLM call ในตัว tool ใช้ tier เดียวกัน)

```python
class MySmartTool(BaseTool):
    preferred_tier = "mid"  # ← ทุก llm_router.chat() ที่ใช้ self.preferred_tier จะได้ Sonnet/Pro

    async def execute(self, ...):
        resp = await llm_router.chat(..., tier=self.preferred_tier, ...)
```

**วิธีที่ 2: ระบุ `tier` เฉพาะ call** (สำหรับกรณีที่ต้องการ mix tier ในตัว tool เดียว)

```python
# call แรก: ใช้ cheap สำหรับงานง่าย
resp1 = await llm_router.chat(..., tier="cheap", ...)

# call ที่สอง: ใช้ mid สำหรับงานวิเคราะห์
resp2 = await llm_router.chat(..., tier="mid", ...)
```

**ตัวอย่างเต็ม:**

```python
# tools/research_tool.py
"""Research Tool — วิเคราะห์ข้อมูลเชิงลึกผ่าน LLM สุดฉลาด"""

from tools.base import BaseTool
from core.llm import llm_router
from core.user_manager import get_user, get_preference
from core.logger import get_logger

log = get_logger(__name__)

class ResearchSummaryTool(BaseTool):
    name = "research_summary"
    description = "วิเคราะห์และสรุปผลข้อมูลเชิงลึกแบบละเอียดยิบ"
    commands = ["/research"]
    direct_output = True
    preferred_tier = "mid"  # ← ใช้โมเดลตัวเก่งเสมอ

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        if not args:
            return "กรุณาระบุหัวข้อวิเคราะห์: /research [หัวข้อ]"

        try:
            user = get_user(user_id) or {}
            provider = get_preference(user, "default_llm")

            system_prompt = (
                "คุณคือนักวิเคราะห์ข้อมูลอาวุโส "
                "สรุปวิเคราะห์ข้อมูลด้วยหลักเหตุผลลอจิก วิเคราะห์ผลกระทบ และข้อแนะนำ"
            )

            resp = await llm_router.chat(
                messages=[{"role": "user", "content": f"วิเคราะห์หัวข้อ:\n{args}"}],
                provider=provider,
                tier=self.preferred_tier,  # ← ใช้ "mid" จาก class attribute
                system=system_prompt,
            )

            return f"🔬 **บทวิเคราะห์เชิงลึก: {args}**\n\n{resp['content']}"

        except Exception as e:
            log.error(f"Research failed: {e}")
            return f"การวิเคราะห์ล้มเหลว: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "ระดมสมองวิเคราะห์หัวข้อยากๆ หรือพิจารณาข้อมูลเชิงลึก",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "หัวข้อที่จะให้เจาะลึกวิเคราะห์",
                    }
                },
                "required": [],
            },
        }
```

**สิ่งที่เกิดขึ้น:**
1. dispatcher รับคำร้องและส่งมาหา Tool ตามปกติ (dispatcher ใช้โมเดลถูก)
2. เมื่อเข้าสู่ตัว Tool, เราให้ Tool สร้างหน้าต่างแชทเพื่อคุยกับโมเดลตัวแพง (Mid)
3. พ่นผลลัพธ์สุดฉลาดกลับไปยัง user ในท้ายที่สุด
(ด้วยความที่ `direct_output=True` dispatcher ตัวหลักรอบนอกจึงไม่ต้องย่อสรุปข้อมูลซ้ำด้วยโมเดลถูก ทำให้ผลลัพธ์จากโมเดล Mid ถูกรักษาไว้เต็ม 100%)

**Tools ที่ใช้ `preferred_tier = "mid"` ในปัจจุบัน:**
- `gmail_summary` — สรุป Gmail ต้องความเข้าใจสูง
- `work_email` — สรุป IMAP + ไฟล์แนบ ต้องความเข้าใจสูง

---

## รายละเอียดสำคัญ

### 1. `execute()` รับ-ส่งอะไร

```
Signature:
  async def execute(self, user_id: str, args: str = "", **kwargs) -> str

Input:
  user_id  → Telegram chat ID (string) เช่น "25340254"
  args     → ข้อความหลัง command เช่น "/email force 7d" → args = "force 7d"
             หรือถูก LLM ส่งมาเป็น string
  **kwargs → parameter เพิ่มเติมที่ LLM ส่งมาตาม tool spec
             เช่น mode="walking", category="tech"
             ต้องมี **kwargs เสมอ — dispatcher ส่ง dict ทั้งก้อนผ่าน **tool_args

Output:
  return string → ข้อความที่จะส่งกลับให้ user ผ่าน Telegram
```

### 2. การทำงานร่วมกับ LLM (Function Calling)

```
User พิมพ์: "อากาศวันนี้เป็นยังไง"
         │
         ▼
LLM เห็น tool spec ทั้งหมด
         │
         ▼
LLM เลือก: weather tool (เพราะ description ตรง)
         │
         ▼
Dispatcher เรียก WeatherTool.execute(user_id, args)
         │
         ▼
ถ้า direct_output=True → ส่งผลตรงให้ user
ถ้า direct_output=False → ส่งผลให้ LLM สรุปอีกที
         │
         ▼
ส่งกลับ user ผ่าน Telegram
```

> **สำคัญ:** `description` ใน class และ `get_tool_spec()` ต้องชัดเจน —
> LLM ใช้ description ตัดสินใจว่าจะเรียก tool ไหน

### 3. ใช้ modules จาก core ได้

```python
# Database
from core import db
db.log_tool_usage(user_id, "my_tool", status="success")

# LLM
from core.llm import llm_router
resp = await llm_router.chat(messages=[...], provider=provider, tier="cheap")

# User preference (ดึง LLM provider ของ user)
from core.user_manager import get_user, get_preference
user = get_user(user_id) or {}
provider = get_preference(user, "default_llm")

# Config
from core.config import SOME_CONFIG

# Gmail credentials
from core.security import get_gmail_credentials

# Logger
from core.logger import get_logger
log = get_logger(__name__)
```

### 4. `get_tool_spec()` เขียนยังไง (Standardized Format)

Tool spec เป็น **format กลาง** — LLM Router จะแปลงให้ตรง provider อัตโนมัติ.
สิ่งสำคัญที่สุดคือ **`description`** ต้องเขียนให้ครอบคลุมขอบเขต (Boundary) เพื่อให้ LLM เลือก Tool ได้ถูกต้อง โดยให้ยึดโครงสร้างนี้:

1. **Positive:** อธิบายว่า Tool นี้ทำอะไรได้
2. **Usage Condition:** "ใช้เมื่อ..." อธิบาย pattern คำถามที่ควรเข้า Tool นี้
3. **Negative Boundary:** "ไม่ใช่สำหรับ..." ดักทางที่ LLM มักจะหลงมาผิด และบอกว่าควรไปใช้ Tool ไหนแทน
4. **Examples:** "เช่น..." ตัวอย่างคำถามที่ถูกต้อง

```python
def get_tool_spec(self) -> dict:
    return {
        "name": self.name,             # ❗ ใช้ self.name เสมอ ห้าม hardcode
        "description": (
            "ค้นหาสถานที่จริงบนแผนที่ เช่น ร้านกาแฟ ร้านอาหาร โรงพยาบาล. "
            "ใช้เมื่อ user ถามว่า 'มีร้านอะไรแถวนี้' หรือ 'หาร้าน...'. "
            "ไม่ใช่สำหรับเช็คเส้นทาง/ระยะทาง/จราจร -- ให้ใช้ traffic แทน. "
            "เช่น 'ร้านกาแฟแถวสยาม', 'ATM ใกล้ MBK'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "args": {              # ชื่อ parameter
                    "type": "string",  # ประเภท: string, integer, boolean
                    "description": "อธิบาย parameter",
                }
            },
            "required": ["args"],      # list ของ parameter ที่จำเป็น
        },
    }
```

**เพิ่ม enum parameter** — ให้ LLM เลือกค่าที่ถูกต้องได้ตรงๆ แทนการ regex text:

```python
"properties": {
    "args": {
        "type": "string",
        "description": "ต้นทางและปลายทาง คั่นด้วย 'ไป'",
    },
    "mode": {
        "type": "string",
        "enum": ["driving", "walking", "transit", "two_wheeler"],
        "description": "โหมดการเดินทาง: driving=รถยนต์, walking=เดินเท้า, transit=รถโดยสาร, two_wheeler=มอเตอร์ไซค์",
    },
},
```

LLM จะส่ง `mode="walking"` ตรงๆ → `execute()` รับผ่าน `**kwargs` หรือเป็น named param ก็ได้:

```python
async def execute(self, user_id: str, args: str = "", mode: str = "driving", **kwargs) -> str:
    # mode ถูก extract มาจาก kwargs อัตโนมัติ
    ...
```

**ถ้า tool ไม่มี parameter** — ไม่ต้อง override `get_tool_spec()` เลย (BaseTool มี default)

### 5. Error Handling

```python
async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
    try:
        # ทำงานหลัก
        result = do_something()
        return result

    except Exception as e:
        log.error(f"MyTool failed for {user_id}: {e}")

        # (optional) บันทึก log ลง DB
        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="failed",
            error_message=str(e),
        )

        # return error message ที่ user-friendly
        return f"เกิดข้อผิดพลาด: {e}"
```

> ⚠️ **อย่าให้ exception หลุดออกจาก `execute()`** — dispatcher จะ catch ได้
> แต่ user จะได้ error message ที่ไม่สวย ควร catch เองแล้ว return ข้อความที่อ่านง่าย

### 6. Input Guard (ป้องกัน Tool หลงทาง)

ถึงแม้ `description` ใน `get_tool_spec()` จะเขียนชัดเจนแล้ว แต่ในบางครั้ง LLM ก็ยังอาจจะส่ง intent ผิดๆ มาเข้า Tool ได้ (โดยเฉพาะเรื่องใกล้เคียงกัน เช่น บันทึกรายได้ ไปเข้า Expense Tool)
เพื่อความปลอดภัย ควรทำ **Input Guard** ดักที่ต้นทางของ logic ภายใน Tool เสมอ:

```python
def _is_invalid_intent(self, text: str) -> bool:
    # ดักจับคำที่อาจเป็น intent ของ Tool อื่น
    keywords = {"รับเงิน", "รับโอน", "รายได้", "เงินเข้า"}
    return any(kw in text for kw in keywords)

async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
    # 1. ป้องกัน Input ผิดประเภท
    if self._is_invalid_intent(args):
        return "❌ ดูเหมือนคุณต้องการบันทึกรายได้/สร้าง QR รับเงิน กรุณาใช้คำสั่งที่เหมาะสม"
        
    # 2. ทำงานปกติ
    ...
```

### 7. `direct_output` — ส่งตรง vs ผ่าน LLM

```python
class MyTool(BaseTool):
    direct_output = True   # ส่งผลตรงๆ ไม่ต้องให้ LLM สรุปอีกที
    # direct_output = False  # ส่งผลให้ LLM สรุปเป็นภาษาธรรมชาติอีกที
```

| ค่า | ใช้เมื่อ | ตัวอย่าง |
|---|---|---|
| `True` (default) | tool format output เองสวยแล้ว หรือ tool สรุปด้วย LLM เองภายใน | traffic, places, lotto, gmail_summary, news_summary |
| `False` | อยากให้ dispatcher ส่งผลดิบให้ LLM สรุปเป็นภาษาธรรมชาติอีกที | (ไม่มี tool ปัจจุบันที่ใช้ — แต่ framework รองรับ) |

> **หมายเหตุ:** tools ที่เรียก LLM เองภายใน (เช่น gmail_summary, news_summary)
> ใช้ `direct_output = True` เพราะ output สรุปแล้ว ไม่ต้องให้ dispatcher สรุปซ้ำ

### 8. `preferred_tier` — เลือกระดับ LLM

```python
class MyTool(BaseTool):
    preferred_tier = "cheap"   # Haiku/Flash — เร็ว ถูก (default)
    # preferred_tier = "mid"   # Sonnet/Pro — ฉลาดกว่า แต่ช้าและแพงกว่า
```

| Tier | โมเดล | ใช้เมื่อ | Tools ที่ใช้ |
|---|---|---|---|
| `"cheap"` (default) | Haiku / Gemini Flash | งานสรุปทั่วไป ไม่ซับซ้อน | news_summary |
| `"mid"` | Sonnet / Gemini Pro | งานที่ต้องเข้าใจเนื้อหาลึก | gmail_summary, work_email |

ใช้ใน `execute()` ผ่าน `self.preferred_tier`:

```python
resp = await llm_router.chat(
    messages=[...],
    provider=provider,
    tier=self.preferred_tier,  # ← ใช้ค่าจาก class attribute
    system=system_prompt,
)
```

---

## Checklist ก่อน Deploy

### บังคับ (ขาดข้อใด = bug)

- [ ] ไฟล์อยู่ใน `tools/` directory
- [ ] Class inherit จาก `BaseTool`
- [ ] ตั้ง `name`, `description`, `commands` ครบ
- [ ] `execute()` มี signature: `async def execute(self, user_id: str, args: str = "", **kwargs) -> str`
- [ ] `execute()` return string เสมอ (ไม่ return None)
- [ ] `execute()` ครอบด้วย `try/except` ไม่ให้ exception หลุด
- [ ] `get_tool_spec()` ใช้ `self.name` (**ห้าม hardcode** ชื่อ tool)
- [ ] ตั้ง `direct_output` ตามที่ต้องการ

### แนะนำ (ไม่ทำ = ทำงานได้แต่ไม่ดี)

- [ ] `db.log_tool_usage()` ทั้ง success และ failed (dispatcher จัดการ failed ให้แล้ว แต่ success ต้อง log เอง)
- [ ] ตั้ง `preferred_tier` ถ้า tool เรียก LLM เอง (`"mid"` สำหรับงานซับซ้อน)
- [ ] `get_tool_spec()` มี description ชัดเจน (LLM ใช้ตัดสินใจ)
- [ ] ถ้าใช้ enum parameter → ระบุ `"enum": [...]` ใน properties
- [ ] ถ้าใช้ API key → เพิ่มใน `.env`, `.env.example`, `core/config.py`
- [ ] ถ้าใช้ library ใหม่ → เพิ่มใน `requirements.txt`
- [ ] ทดสอบผ่าน `/command` ตรง
- [ ] ทดสอบผ่านพิมพ์อิสระ (LLM เลือก tool ถูก)
- [ ] output ไม่เกิน Telegram limit (~4096 chars)

---

## Tools ที่มีอยู่แล้ว

| Tool | Commands | API/Source | preferred_tier | API Keys ที่ต้องมี |
|---|---|---|---|---|
| **expense** — บันทึกรายจ่าย | `/exp`, `/expense` | SQLite + Gemini Vision (รูปบิล) | cheap | `GEMINI_API_KEY` (เฉพาะถ่ายรูปบิล) |
| **promptpay** — สร้าง PromptPay QR | `/pay`, `/promptpay` | EMVCo + segno | cheap | ไม่ต้อง |
| **qrcode_gen** — สร้าง QR Code ทั่วไป | `/qr` | segno | cheap | ไม่ต้อง |
| **gmail_summary** — สรุป Gmail | `/gmail`, `/email` | Gmail API (OAuth2) + LLM | mid | `ANTHROPIC_API_KEY` หรือ `GEMINI_API_KEY` |
| **work_email** — สรุปอีเมลที่ทำงาน (IMAP) | `/wm`, `/workmail` | IMAP + LLM | mid | `WORK_IMAP_HOST`, `WORK_IMAP_PORT`, `WORK_IMAP_USER`, `WORK_IMAP_PASSWORD` |
| **smart_inbox** — หา action items จากอีเมล | `/inbox` | Gmail API + LLM | mid | `ANTHROPIC_API_KEY` หรือ `GEMINI_API_KEY` |
| **traffic** — เส้นทาง/จราจร | `/traffic`, `/route` | Google Maps Directions + Routes API | cheap | `GOOGLE_MAPS_API_KEY` |
| **places** — ค้นหาสถานที่ | `/places`, `/nearby` | Google Places API (New) | cheap | `GOOGLE_MAPS_API_KEY` |
| **exchange_rate** — อัตราแลกเปลี่ยน | `/fx`, `/rate`, `/exchange` | Bank of Thailand API | cheap | `BOT_API_EXCHANGE_TOKEN`, `BOT_API_HOLIDAY_TOKEN` |
| **news_summary** — สรุปข่าว | `/news` | Google News RSS + LLM | cheap | ไม่ต้อง (RSS ฟรี) |
| **web_search** — ค้นหาเว็บ | `/search`, `/google` | Google Custom Search + LLM | cheap | `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_CX` |
| **lotto** — ตรวจสลากกินแบ่ง | `/lotto` | lotto.api.rayriffy.com | cheap | ไม่ต้อง (API ฟรี) |
| **todo** — จัดการ to-do list | `/todo` | SQLite | cheap | ไม่ต้อง |
| **reminder** — ตั้งเตือนครั้งเดียว | `/remind` | SQLite + asyncio scheduler | cheap | ไม่ต้อง |
| **schedule** — ตั้งเวลา tool อัตโนมัติ | `/schedule` | SQLite + asyncio scheduler | cheap | ไม่ต้อง |
| **calendar_tool** — Google Calendar | `/cal`, `/calendar` | Google Calendar API (OAuth2) | cheap | ไม่ต้อง (ใช้ OAuth2) |
| **unit_converter** — แปลงหน่วย | `/convert`, `/unit` | Built-in | cheap | ไม่ต้อง |
| **settings** — ตั้งค่าส่วนตัว + ดูบัญชีอีเมล | `/setname`, `/setphone`, `/setid`, `/myemail` | SQLite + Gmail API (profile) | cheap | ไม่ต้อง |
| **apikeys** — จัดการ API keys | `/setkey`, `/mykeys`, `/removekey` | SQLite (encrypted) | cheap | ไม่ต้อง |

> **หมายเหตุ:** ทุก tool ใช้ `direct_output = True` (default) — tools ที่ใช้ LLM (gmail_summary, work_email, news_summary, smart_inbox, web_search) สรุปเองภายในแล้ว

---

## แนวคิด Tool ที่น่าสนใจ

| Tool | คำสั่ง | API ที่ใช้ | ความยาก |
|---|---|---|---|
| พยากรณ์อากาศ | `/weather` | Open-Meteo (ฟรี) | ง่าย |
| แปลภาษา | `/translate` | ใช้ LLM (ไม่ต้อง API เพิ่ม) | ง่าย |
| ติดตามพัสดุ | `/track` | Thailand Post API / Kerry API | ปานกลาง |
| สรุป YouTube | `/yt` | YouTube Transcript API + LLM | ปานกลาง |

---

## Tips

1. **description สำคัญมาก** — LLM ใช้ description ตัดสินใจว่าจะเรียก tool ไหนเมื่อ user พิมพ์อิสระ ถ้า description ไม่ชัด LLM จะเลือกผิด

2. **ใช้ LLM เป็น formatter** — tool ดึงข้อมูลดิบมา แล้วส่งให้ LLM สรุปเป็นภาษาธรรมชาติ ผลลัพธ์จะดีกว่า format เองมาก (ดูตัวอย่างใน gmail_summary, news_summary)

3. **ตั้ง command หลายตัวได้** — `commands = ["/weather", "/w"]` ให้ user พิมพ์สั้นๆ ได้

4. **ทดสอบ /command ก่อน** — ทดสอบผ่าน `/command` ตรงก่อน เพราะไม่ผ่าน LLM ดู output ตรงๆ ง่ายกว่า debug

5. **เก็บ API key ใน .env เสมอ** — อย่า hardcode ลงในไฟล์ tool โดยเด็ดขาด

6. **ใช้ `preferred_tier` แทน hardcode** — ตั้ง `preferred_tier = "mid"` ที่ class level แทนใส่ `tier="mid"` ตรงๆ ใน code ทำให้ปรับเปลี่ยนง่าย
