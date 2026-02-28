# คู่มือเพิ่ม Tool ใหม่ — OpenMiniCrew

> 🇬🇧 [English version](docs/en/TOOLS_GUIDE.md)

## สารบัญ

- [ภาพรวม](#ภาพรวม)
- [ขั้นตอนเพิ่ม Tool ใหม่](#ขั้นตอนเพิ่ม-tool-ใหม่)
- [Template พื้นฐาน](#template-พื้นฐาน)
- [ตัวอย่าง 1: Tool ง่าย — พยากรณ์อากาศ](#ตัวอย่าง-1-tool-ง่าย--พยากรณ์อากาศ)
- [ตัวอย่าง 2: Tool ที่เรียก API — Google Maps](#ตัวอย่าง-2-tool-ที่เรียก-api--google-maps)
- [ตัวอย่าง 3: Tool ที่ใช้ LLM — สรุปข่าว](#ตัวอย่าง-3-tool-ที่ใช้-llm--สรุปข่าว)
- [รายละเอียดสำคัญ](#รายละเอียดสำคัญ)
- [Checklist ก่อน Deploy](#checklist-ก่อน-deploy)
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

    async def execute(self, user_id: str, args: str = "") -> str:
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

from tools.base import BaseTool
from core.logger import get_logger

log = get_logger(__name__)


class MyTool(BaseTool):
    name = "my_tool"
    description = "คำอธิบายที่ LLM จะใช้ตัดสินใจว่าจะเรียก tool นี้เมื่อไหร่"
    commands = ["/mytool"]

    async def execute(self, user_id: str, args: str = "") -> str:
        """
        ฟังก์ชันหลัก — ถูกเรียกเมื่อ user ใช้ /command หรือ LLM เลือก tool นี้

        Parameters:
            user_id: Telegram chat ID ของ user (string)
            args: ข้อความที่ตามหลัง command เช่น "/mytool hello" → args = "hello"

        Returns:
            string ที่จะส่งกลับให้ user (หรือส่งให้ LLM สรุปอีกที)
        """
        if not args:
            return "กรุณาระบุ... เช่น /mytool xxx"

        try:
            # === ทำงานหลัก ===
            result = f"ผลลัพธ์สำหรับ: {args}"
            return result

        except Exception as e:
            log.error(f"MyTool failed: {e}")
            return f"เกิดข้อผิดพลาด: {e}"

    def get_tool_spec(self) -> dict:
        """
        บอก LLM ว่า tool นี้รับ parameter อะไร
        LLM Router จะแปลง format ให้ตรง provider (Claude/Gemini) อัตโนมัติ
        """
        return {
            "name": "my_tool",
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
            "name": "weather",
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

ถามเส้นทาง + สภาพจราจร ผ่าน Google Maps Directions API

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

```python
# tools/traffic.py
"""Traffic Tool — เช็คเส้นทาง + สภาพจราจรผ่าน Google Maps"""

import requests
from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core.logger import get_logger

log = get_logger(__name__)


class TrafficTool(BaseTool):
    name = "traffic"
    description = "เช็คเส้นทางและสภาพจราจรระหว่าง 2 จุด ผ่าน Google Maps"
    commands = ["/traffic"]

    async def execute(self, user_id: str, args: str = "") -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "ยังไม่ได้ตั้งค่า GOOGLE_MAPS_API_KEY ใน .env"

        if not args:
            return (
                "กรุณาระบุต้นทางและปลายทาง เช่น:\n"
                "/traffic สยาม ไป สีลม\n"
                "/traffic บ้าน ไป ออฟฟิศ"
            )

        # แยกต้นทาง-ปลายทาง
        parts = args.replace(" ไป ", "|").replace(" to ", "|").replace("→", "|").split("|")
        if len(parts) < 2:
            return "กรุณาระบุ: /traffic [ต้นทาง] ไป [ปลายทาง]"

        origin = parts[0].strip()
        destination = parts[1].strip()

        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": origin,
                    "destination": destination,
                    "mode": "driving",
                    "departure_time": "now",      # ข้อมูลจราจร real-time
                    "language": "th",
                    "key": GOOGLE_MAPS_API_KEY,
                },
                timeout=10,
            )
            data = resp.json()

            if data["status"] != "OK":
                return f"หาเส้นทางไม่ได้: {data['status']}"

            route = data["routes"][0]
            leg = route["legs"][0]

            # ข้อมูลพื้นฐาน
            distance = leg["distance"]["text"]
            duration = leg["duration"]["text"]

            # ข้อมูลจราจร (ถ้ามี)
            traffic_duration = leg.get("duration_in_traffic", {}).get("text", "")
            traffic_info = ""
            if traffic_duration:
                traffic_info = f"\n🚦 ใช้เวลาจริง (จราจร): {traffic_duration}"

            # สรุปเส้นทาง
            steps_summary = []
            for i, step in enumerate(leg["steps"][:5], 1):  # แสดงแค่ 5 ขั้นตอนแรก
                instruction = step["html_instructions"]
                # ลบ HTML tags
                import re
                instruction = re.sub(r"<[^>]+>", "", instruction)
                step_dist = step["distance"]["text"]
                steps_summary.append(f"  {i}. {instruction} ({step_dist})")

            steps_text = "\n".join(steps_summary)
            if len(leg["steps"]) > 5:
                steps_text += f"\n  ... และอีก {len(leg['steps']) - 5} ขั้นตอน"

            return (
                f"🗺 เส้นทาง: {leg['start_address']}\n"
                f"➡️ ไป: {leg['end_address']}\n\n"
                f"📏 ระยะทาง: {distance}\n"
                f"⏱ เวลาปกติ: {duration}"
                f"{traffic_info}\n\n"
                f"📍 เส้นทาง:\n{steps_text}"
            )

        except Exception as e:
            log.error(f"Traffic API error: {e}")
            return f"เกิดข้อผิดพลาด: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "traffic",
            "description": (
                "เช็คเส้นทางและสภาพจราจรระหว่าง 2 จุด เช่น "
                "'สยาม ไป สีลม', 'บ้าน ไป สนามบิน'"
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
                    }
                },
                "required": ["args"],
            },
        }
```

**ใช้งาน:**
```
/traffic สยาม ไป สีลม
/traffic บ้าน ไป สนามบิน
หรือพิมพ์: "จากสยามไปสีลมใช้เวลาเท่าไหร่ รถติดไหม"
```

---

## ตัวอย่าง 3: Tool ที่ใช้ LLM — สรุปข่าว

ดึงข่าวจาก RSS Feed แล้วให้ LLM สรุป

```python
# tools/news_summary.py
"""News Summary Tool — สรุปข่าววันนี้จาก RSS feeds"""

import feedparser
from tools.base import BaseTool
from core.config import DEFAULT_LLM
from core.llm import llm_router
from core.logger import get_logger

log = get_logger(__name__)

# RSS Feeds ภาษาไทย
FEEDS = {
    "tech": {
        "label": "เทคโนโลยี",
        "url": "https://www.blognone.com/atom.xml",
    },
    "news": {
        "label": "ข่าวทั่วไป",
        "url": "https://www.thairath.co.th/rss",
    },
}


class NewsSummaryTool(BaseTool):
    name = "news_summary"
    description = "สรุปข่าวล่าสุดจากแหล่งข่าวต่างๆ"
    commands = ["/news"]

    async def execute(self, user_id: str, args: str = "") -> str:
        category = args.strip().lower() if args else "tech"

        feed_info = FEEDS.get(category)
        if not feed_info:
            categories = ", ".join(f"{k} ({v['label']})" for k, v in FEEDS.items())
            return f"หมวดที่รองรับ: {categories}"

        try:
            # 1. ดึงข่าวจาก RSS
            feed = feedparser.parse(feed_info["url"])
            entries = feed.entries[:10]  # 10 ข่าวล่าสุด

            if not entries:
                return f"ไม่พบข่าว{feed_info['label']}ล่าสุด"

            # 2. เตรียมข้อมูลส่ง LLM
            news_text = ""
            for i, entry in enumerate(entries, 1):
                title = entry.get("title", "")
                summary = entry.get("summary", "")[:300]
                news_text += f"\n--- ข่าว #{i} ---\n"
                news_text += f"หัวข้อ: {title}\n"
                news_text += f"เนื้อหา: {summary}\n"

            # 3. ให้ LLM สรุป
            system = (
                "คุณเป็นผู้ช่วยสรุปข่าว ตอบเป็นภาษาไทย กระชับ เข้าใจง่าย "
                "จัดกลุ่มข่าวที่เกี่ยวข้อง บอกประเด็นสำคัญ "
                "ใช้ emoji ให้อ่านง่าย"
            )
            resp = await llm_router.chat(
                messages=[{"role": "user", "content": f"สรุปข่าว{feed_info['label']}:\n{news_text}"}],
                provider=DEFAULT_LLM,
                tier="cheap",
                system=system,
            )

            return f"📰 ข่าว{feed_info['label']}ล่าสุด:\n\n{resp['content']}"

        except Exception as e:
            log.error(f"News fetch error: {e}")
            return f"ดึงข่าวไม่ได้: {e}"

    def get_tool_spec(self) -> dict:
        return {
            "name": "news_summary",
            "description": "สรุปข่าวล่าสุด เลือกหมวดได้ เช่น tech (เทคโนโลยี), news (ทั่วไป)",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "หมวดข่าว: tech (เทคโนโลยี), news (ทั่วไป)",
                    }
                },
                "required": [],
            },
        }
```

**ใช้งาน:**
```
/news tech
/news
หรือพิมพ์: "มีข่าวเทคโนโลยีอะไรใหม่บ้าง"
```

---

## รายละเอียดสำคัญ

### 1. `execute()` รับ-ส่งอะไร

```
Input:
  user_id  → Telegram chat ID (string) เช่น "25340254"
  args     → ข้อความหลัง command เช่น "/email force 7d" → args = "force 7d"
             หรือถูก LLM ส่งมาเป็น string

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
ผลลัพธ์ถูกส่งให้ LLM สรุปเป็นภาษาธรรมชาติ
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
from core.config import DEFAULT_LLM
resp = await llm_router.chat(messages=[...], provider=DEFAULT_LLM, tier="cheap")

# Config
from core.config import SOME_CONFIG

# Security (Gmail)
from core.security import get_gmail_credentials

# Logger
from core.logger import get_logger
log = get_logger(__name__)
```

### 4. `get_tool_spec()` เขียนยังไง

Tool spec เป็น **format กลาง** — LLM Router จะแปลงให้ตรง provider อัตโนมัติ:

```python
def get_tool_spec(self) -> dict:
    return {
        "name": "tool_name",           # ต้องตรงกับ self.name
        "description": "คำอธิบาย",     # LLM ใช้ตัดสินใจ — ยิ่งชัดเจนยิ่งดี
        "parameters": {
            "type": "object",
            "properties": {
                "args": {              # ชื่อ parameter
                    "type": "string",  # ประเภท: string, integer, boolean
                    "description": "อธิบาย parameter",
                }
            },
            "required": [],            # list ของ parameter ที่จำเป็น
        },
    }
```

**ถ้า tool ไม่มี parameter** — ไม่ต้อง override `get_tool_spec()` เลย (BaseTool มี default)

### 5. Error Handling

```python
async def execute(self, user_id: str, args: str = "") -> str:
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

---

## Checklist ก่อน Deploy

- [ ] ไฟล์อยู่ใน `tools/` directory
- [ ] Class inherit จาก `BaseTool`
- [ ] ตั้ง `name`, `description`, `commands` ครบ
- [ ] `execute()` return string เสมอ (ไม่ return None)
- [ ] `execute()` ไม่ให้ exception หลุด — catch ทุกกรณี
- [ ] `get_tool_spec()` มี description ชัดเจน (LLM ใช้ตัดสินใจ)
- [ ] ถ้าใช้ API key → เพิ่มใน `.env`, `.env.example`, `core/config.py`
- [ ] ถ้าใช้ library ใหม่ → เพิ่มใน `requirements.txt`
- [ ] ทดสอบผ่าน `/command` ตรง
- [ ] ทดสอบผ่านพิมพ์อิสระ (LLM เลือก tool ถูก)
- [ ] อัพเดท README.md (ตาราง commands)

---

## แนวคิด Tool ที่น่าสนใจ

| Tool | คำสั่ง | API ที่ใช้ | ความยาก |
|---|---|---|---|
| พยากรณ์อากาศ | `/weather` | Open-Meteo (ฟรี) | ง่าย |
| แปลภาษา | `/translate` | ใช้ LLM (ไม่ต้อง API เพิ่ม) | ง่าย |
| สรุปข่าว | `/news` | RSS + LLM | ง่าย |
| จดบันทึก/เตือนความจำ | `/note` | SQLite (มีอยู่แล้ว) | ง่าย |
| ค้นหาเว็บ | `/search` | Google Custom Search / SerpAPI | ปานกลาง |
| เส้นทาง/จราจร | `/traffic` | Google Maps Directions API | ปานกลาง |
| ค่าเงิน/อัตราแลกเปลี่ยน | `/fx` | exchangerate-api (ฟรี) | ง่าย |
| ติดตามพัสดุ | `/track` | Thailand Post API / Kerry API | ปานกลาง |
| จัดการ Google Calendar | `/cal` | Google Calendar API | ยาก |
| อ่านไฟล์แนบ email | `/attachment` | Gmail API + PDF parser | ยาก |
| สรุป YouTube | `/yt` | YouTube Transcript API + LLM | ปานกลาง |

---

## Tips

1. **description สำคัญมาก** — LLM ใช้ description ตัดสินใจว่าจะเรียก tool ไหนเมื่อ user พิมพ์อิสระ ถ้า description ไม่ชัด LLM จะเลือกผิด

2. **ใช้ LLM เป็น formatter** — tool ดึงข้อมูลดิบมา แล้วส่งให้ LLM สรุปเป็นภาษาธรรมชาติ ผลลัพธ์จะดีกว่า format เองมาก (ดูตัวอย่างใน email_summary)

3. **ตั้ง command หลายตัวได้** — `commands = ["/weather", "/w"]` ให้ user พิมพ์สั้นๆ ได้

4. **ทดสอบ /command ก่อน** — ทดสอบผ่าน `/command` ตรงก่อน เพราะไม่ผ่าน LLM ดู output ตรงๆ ง่ายกว่า debug

5. **เก็บ API key ใน .env เสมอ** — อย่า hardcode ลงในไฟล์ tool โดยเด็ดขาด
