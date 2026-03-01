"""Traffic Tool — เช็คเส้นทาง สภาพจราจร และเวลาเดินทาง ผ่าน Google Maps"""

import re
import urllib.parse

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

_MODE_ICONS = {
    "driving": "🚗",
    "walking": "🚶",
    "transit": "🚌",
    "two_wheeler": "🏍",
}

# Fallback สำหรับ direct command เช่น "/traffic สยาม ไป สีลม มอไซค์"
# เรียงจาก specific → general เพื่อกัน false positive
_MODE_FALLBACK = [
    (re.compile(r"มอเตอร์ไซค์|มอไซค์|motorcycle|motorbike", re.IGNORECASE), "two_wheeler"),
    (re.compile(r"เดินเท้า|เดิน(?!ทาง)|walking|on\s+foot", re.IGNORECASE), "walking"),
    (re.compile(r"รถโดยสาร|ขนส่งสาธารณะ|รถเมล์|รถไฟฟ้า|สาธารณะ|transit|bus|bts|mrt", re.IGNORECASE), "transit"),
]


class TrafficTool(BaseTool):
    name = "traffic"
    description = "เช็คเส้นทาง สภาพจราจร และเวลาการเดินทางระหว่างสองจุด ผ่าน Google Maps พร้อมข้อมูล real-time traffic"
    commands = ["/traffic", "/route"]
    direct_output = True

    SEPARATORS = [" ไป ", " to ", "→", "➡", " ถึง ", "|"]

    # คำที่หมายถึง "ตำแหน่งปัจจุบัน"
    _HERE_KEYWORDS = re.compile(r"^(แถวนี้|ที่นี่|ตรงนี้|here|จุดนี้|ตำแหน่งนี้)$", re.IGNORECASE)

    # คำที่บ่งบอกว่าต้องการหลีกเลี่ยงทางด่วน/ทางพิเศษ ทั้งหมด
    _AVOID_TOLLS_KEYWORDS = re.compile(
        r"(ไม่ขึ้นทางด่วน|ไม่ใช้ทางด่วน|ไม่เอาทางด่วน|หลีกเลี่ยงทางด่วน|"
        r"ไม่ขึ้นทางพิเศษ|ไม่ใช้ทางพิเศษ|ไม่เอาทางพิเศษ|หลีกเลี่ยงทางพิเศษ|"
        r"ไม่ขึ้นโทลเวย์|ไม่ใช้โทลเวย์|"
        r"no toll|avoid toll|no expressway|avoid expressway|no highway)",
        re.IGNORECASE,
    )

    _ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    # คำที่บ่งบอกว่าต้องการหลีกเลี่ยงเส้นทางเฉพาะ เช่น "ไม่ขึ้น ดอนเมืองโทลเวย์"
    # (มีช่องว่างระหว่าง ไม่ขึ้น/ไม่ผ่าน กับชื่อเส้นทาง)
    _AVOID_SPECIFIC_PATTERN = re.compile(
        r"(?:ไม่ขึ้น|ไม่ผ่าน)\s+(\S+)",
        re.IGNORECASE,
    )

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ใช้เช็คเส้นทาง ระยะทาง เวลาเดินทาง และสภาพจราจร real-time "
                "ระหว่างสองสถานที่ผ่าน Google Maps เช่น 'สยาม ไป สีลม' หรือ 'Siam to Silom'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "ต้นทางและปลายทาง คั่นด้วย 'ไป', 'to', '→' "
                            "เช่น 'สยาม ไป สีลม', 'MBK to Asiatique' "
                            "ถ้าผู้ใช้ไม่ระบุต้นทาง ให้ใช้ 'ที่นี่ ไป <ปลายทาง>' "
                            "เช่น ผู้ใช้ถาม 'ไปบางรักรถติดไหม' → args = 'ที่นี่ ไป บางรัก' "
                            "ถ้าผู้ใช้ระบุว่าไม่ขึ้นทางด่วนทั้งหมด ให้ต่อท้ายด้วย 'ไม่ขึ้นทางด่วน' "
                            "ถ้าผู้ใช้ต้องการหลีกเลี่ยงทางด่วนเส้นใดเส้นหนึ่งโดยเฉพาะ "
                            "ให้ต่อท้ายด้วย 'ไม่ขึ้น <ชื่อทางด่วน>' "
                            "เช่น → args = 'จันทน์ ไป แจ้งวัฒนะ ไม่ขึ้น ดอนเมืองโทลเวย์'"
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["driving", "walking", "transit", "two_wheeler"],
                        "description": (
                            "โหมดการเดินทาง: "
                            "'driving' = รถยนต์ (default), "
                            "'walking' = เดินเท้า, "
                            "'transit' = รถโดยสาร/รถไฟฟ้า/BTS/MRT, "
                            "'two_wheeler' = มอเตอร์ไซค์"
                        ),
                    },
                },
                "required": ["args"],
            },
        }

    async def execute(self, user_id: str, args: str = "", mode: str = "driving", **kwargs) -> str:
        # 1. Validate API key
        if not GOOGLE_MAPS_API_KEY:
            return (
                "❌ ยังไม่ได้ตั้งค่า Google Maps API Key\n\n"
                "วิธีตั้งค่า:\n"
                "1. ไปที่ https://console.cloud.google.com/google/maps-apis\n"
                "2. เปิดใช้ Directions API\n"
                "3. สร้าง API Key\n"
                "4. เพิ่มใน .env: GOOGLE_MAPS_API_KEY=your_key"
            )

        # 2. โหมดการเดินทาง
        if mode not in _MODE_ICONS:
            mode = "driving"

        # Fallback: ถ้า mode ยังเป็น default ให้ตรวจจาก args
        # (รองรับ direct command เช่น "/traffic สยาม ไป สีลม มอไซค์")
        raw_args = args.strip()
        if mode == "driving":
            for pattern, m in _MODE_FALLBACK:
                if pattern.search(raw_args):
                    mode = m
                    raw_args = pattern.sub("", raw_args).strip()
                    break

        mode_icon = _MODE_ICONS[mode]

        # ตรวจจับ "ไม่ขึ้นทางด่วน" ก่อน parse เส้นทาง
        avoid_tolls = bool(self._AVOID_TOLLS_KEYWORDS.search(raw_args))
        if avoid_tolls:
            raw_args = self._AVOID_TOLLS_KEYWORDS.sub("", raw_args).strip()

        # ตรวจจับการหลีกเลี่ยงเส้นทางเฉพาะ เช่น "ไม่ขึ้น ดอนเมืองโทลเวย์"
        avoid_specific = self._AVOID_SPECIFIC_PATTERN.findall(raw_args)
        if avoid_specific:
            raw_args = self._AVOID_SPECIFIC_PATTERN.sub("", raw_args)
            raw_args = re.sub(r"\s*(แต่|และ)\s*", " ", raw_args).strip()

        parsed = self._parse_route_args(raw_args)
        if not parsed:
            return (
                "📍 กรุณาระบุต้นทางและปลายทาง\n\n"
                "ตัวอย่าง:\n"
                "  /traffic สยาม ไป สีลม\n"
                "  /traffic Siam to Silom\n"
                "  /traffic สยาม → อโศก\n"
                "  หรือพิมพ์: จากสยามไปสีลมรถติดไหม"
            )

        origin, destination = parsed

        if origin.lower() == destination.lower():
            return "📍 ต้นทางและปลายทางเป็นที่เดียวกัน ลองระบุสถานที่ต่างกันดูครับ"

        # 3. แปลง "แถวนี้/ที่นี่" → พิกัด GPS (ถ้ามี)
        origin = self._resolve_here(user_id, origin)
        destination = self._resolve_here(user_id, destination)
        if origin is None or destination is None:
            return (
                "📍 ยังไม่ทราบตำแหน่งปัจจุบันของคุณ\n\n"
                "กดปุ่ม 📎 (แนบไฟล์) แล้วเลือก Location เพื่อส่งตำแหน่ง\n"
                "จากนั้นพิมพ์คำถามอีกครั้งได้เลย"
            )

        # 4. เลือก API ตาม mode
        if mode == "two_wheeler":
            output = self._call_routes_api(origin, destination)
        else:
            output = self._call_directions_api(
                origin, destination, mode, mode_icon,
                avoid_tolls, avoid_specific,
            )

        # 5. Log success
        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            input_summary=f"{origin} → {destination} [{mode}]",
            output_summary=output[:200],
            status="success",
        )

        return output

    def _call_directions_api(self, origin: str, destination: str, mode: str, mode_icon: str,
                             avoid_tolls: bool, avoid_specific: list) -> str:
        """ใช้ Directions API สำหรับ driving / walking / transit"""
        try:
            params = {
                "origin": origin,
                "destination": destination,
                "mode": mode,
                "alternatives": "true",
                "language": "th",
                "region": "th",
                "key": GOOGLE_MAPS_API_KEY,
            }
            if mode in ("driving", "transit"):
                params["departure_time"] = "now"
            if avoid_tolls and mode == "driving":
                params["avoid"] = "tolls"

            resp = requests.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params=params, timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            log.error("Google Maps Directions API timeout")
            return "❌ Google Maps ไม่ตอบสนอง ลองใหม่อีกครั้งครับ"
        except requests.exceptions.RequestException as e:
            log.error(f"Directions API error: {e}")
            return "❌ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Maps"

        status = data.get("status", "UNKNOWN")
        if status != "OK":
            return self._handle_api_error(status, origin, destination)

        routes = data.get("routes", [])
        if not routes:
            return f"📍 ไม่พบเส้นทางจาก {origin} ไป {destination}"

        if avoid_specific:
            routes = self._prefer_routes_avoiding(routes, avoid_specific)

        output = self._format_route(routes[0], origin, destination,
                                    mode=mode, mode_icon=mode_icon,
                                    avoid_tolls=avoid_tolls, avoid_specific=avoid_specific)

        if len(routes) > 1:
            output += "\n\n🔀 *เส้นทางอื่น:*"
            for i, route in enumerate(routes[1:3], 2):
                leg = route["legs"][0]
                summary = route.get("summary", "")
                dist = leg["distance"]["text"]
                dur_traffic = leg.get("duration_in_traffic", leg["duration"])["text"]
                output += f"\n  {i}. ผ่าน {summary} — {dist}, ~{dur_traffic}"

        return output

    def _call_routes_api(self, origin: str, destination: str) -> str:
        """ใช้ Routes API สำหรับมอเตอร์ไซค์ (TWO_WHEELER)"""
        body = {
            "origin": self._location_for_routes_api(origin),
            "destination": self._location_for_routes_api(destination),
            "travelMode": "TWO_WHEELER",
            "routingPreference": "TRAFFIC_AWARE",
            "computeAlternativeRoutes": True,
            "languageCode": "th",
            "regionCode": "TH",
            "units": "METRIC",
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": (
                "routes.legs.distanceMeters,routes.legs.duration,"
                "routes.legs.staticDuration,routes.legs.startLocation,"
                "routes.legs.endLocation,routes.legs.steps,"
                "routes.distanceMeters,routes.duration,"
                "routes.staticDuration,routes.description"
            ),
        }
        try:
            resp = requests.post(self._ROUTES_API_URL, json=body, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout:
            log.error("Google Maps Routes API timeout")
            return "❌ Google Maps ไม่ตอบสนอง ลองใหม่อีกครั้งครับ"
        except requests.exceptions.RequestException as e:
            log.error(f"Routes API error: {e}")
            return "❌ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Maps"

        routes = data.get("routes", [])
        if not routes:
            err = data.get("error", {}).get("message", "")
            log.error(f"Routes API no results: {err}")
            return f"📍 ไม่พบเส้นทางมอเตอร์ไซค์จาก {origin} ไป {destination}"

        return self._format_motorcycle_route(routes[0], origin, destination, routes[1:])

    def _location_for_routes_api(self, location: str) -> dict:
        """แปลง location string → Routes API format (address หรือ latLng)"""
        parts = location.split(",")
        if len(parts) == 2:
            try:
                return {"location": {"latLng": {
                    "latitude": float(parts[0]),
                    "longitude": float(parts[1]),
                }}}
            except ValueError:
                pass
        return {"address": location}

    def _format_motorcycle_route(self, route: dict, origin: str, destination: str, alt_routes: list) -> str:
        """Format Routes API response สำหรับมอเตอร์ไซค์"""
        leg = route["legs"][0]
        description = route.get("description", "")

        dist_m = leg.get("distanceMeters", route.get("distanceMeters", 0))
        dist_text = f"{dist_m/1000:.1f} กม." if dist_m >= 1000 else f"{dist_m} ม."

        def sec_to_text(s: int) -> str:
            return f"{s//3600} ชม. {(s%3600)//60} นาที" if s >= 3600 else f"{s//60} นาที"

        dur_sec = int(leg.get("duration", route.get("duration", "0s")).rstrip("s"))
        static_sec = int(leg.get("staticDuration", route.get("staticDuration", "0s")).rstrip("s"))
        delay_sec = dur_sec - static_sec

        if delay_sec > 60:
            delay_text = f"⚠️ รถติดเพิ่มเวลา: ~{delay_sec//60} นาที"
        elif delay_sec <= 0:
            delay_text = "✅ การจราจรคล่องตัว"
        else:
            delay_text = "✅ การจราจรปกติ"

        lines = [
            f"🏍 *เส้นทาง (มอเตอร์ไซค์):* {origin}",
            f"➡️ *ไป:* {destination}",
        ]
        if description:
            lines.append(f"🛣 *ผ่าน:* {description}")
        lines += [
            "",
            f"📏 ระยะทาง: {dist_text}",
            f"⏱ เวลาปกติ: {sec_to_text(static_sec)}",
            f"🚦 เวลาจริง (traffic): {sec_to_text(dur_sec)}",
            delay_text,
        ]

        steps = leg.get("steps", [])
        if steps:
            lines.append("\n📍 *เส้นทางโดยย่อ:*")
            for i, step in enumerate(steps[:5], 1):
                instr = re.sub(r"<[^>]+>", "",
                               step.get("navigationInstruction", {}).get("instructions", ""))
                step_m = step.get("distanceMeters", 0)
                step_text = f"{step_m/1000:.1f} กม." if step_m >= 1000 else f"{step_m} ม."
                lines.append(f"  {i}. {instr} ({step_text})")
            if len(steps) > 5:
                lines.append(f"  ... อีก {len(steps) - 5} ขั้นตอน")

        if alt_routes:
            lines.append("\n🔀 *เส้นทางอื่น:*")
            for i, r in enumerate(alt_routes[:2], 2):
                alt_leg = r["legs"][0]
                alt_m = alt_leg.get("distanceMeters", r.get("distanceMeters", 0))
                alt_dur = int(alt_leg.get("duration", r.get("duration", "0s")).rstrip("s"))
                alt_desc = r.get("description", "")
                alt_dist = f"{alt_m/1000:.1f} กม." if alt_m >= 1000 else f"{alt_m} ม."
                lines.append(f"  {i}. ผ่าน {alt_desc} — {alt_dist}, ~{alt_dur//60} นาที")

        # !3e9 = motorcycle (TWO_WHEELER) travel mode ใน Google Maps path format
        maps_url = (
            f"https://www.google.com/maps/dir/"
            f"{urllib.parse.quote(origin, safe='')}"
            f"/{urllib.parse.quote(destination, safe='')}"
            f"/data=!3e9"
        )
        lines.append(f"\n🗺 [เปิดใน Google Maps]({maps_url})")
        return "\n".join(lines)

    def _resolve_here(self, user_id: str, location: str) -> str | None:
        """แปลง 'แถวนี้/ที่นี่' → พิกัด GPS จริง, return None ถ้าไม่มีตำแหน่ง"""
        if not self._HERE_KEYWORDS.match(location.strip()):
            return location  # ไม่ใช่ keyword → ส่งคืนตามเดิม

        from interfaces.telegram_common import get_user_location
        user_loc = get_user_location(user_id)
        if not user_loc:
            return None  # ไม่มีตำแหน่ง → caller จะแจ้ง user

        return f"{user_loc['lat']},{user_loc['lng']}"

    def _prefer_routes_avoiding(self, routes: list, avoid_roads: list[str]) -> list:
        """เรียงเส้นทางใหม่ — เส้นทางที่ไม่ผ่านถนนที่ต้องการหลีกเลี่ยงมาก่อน"""
        avoid_lower = [r.lower() for r in avoid_roads]
        preferred, fallback = [], []
        for route in routes:
            summary = route.get("summary", "").lower()
            if any(kw in summary for kw in avoid_lower):
                fallback.append(route)
            else:
                preferred.append(route)
        return preferred if preferred else fallback

    def _parse_route_args(self, args: str) -> tuple[str, str] | None:
        """Parse 'A ไป B' into (origin, destination)
        ถ้าไม่มี separator แต่มีข้อความ → ถือว่าต้นทางคือ 'ที่นี่' (ตำแหน่งปัจจุบัน)
        """
        if not args:
            return None

        for sep in self.SEPARATORS:
            if sep in args:
                parts = args.split(sep, 1)
                if len(parts) == 2:
                    origin = parts[0].strip()
                    dest = parts[1].strip()
                    if origin and dest:
                        return origin, dest
                    # กรณี "ไป บางรัก" — origin ว่าง, dest มี
                    if not origin and dest:
                        return "ที่นี่", dest

        # ไม่มี separator เลย เช่น "บางรัก" → ถือว่าเป็นปลายทาง, ต้นทาง = ตำแหน่งปัจจุบัน
        # ตัดคำนำหน้า "ไป/to/จะไป/ไปที่" ออก
        dest = re.sub(r"^(จะไป|ไปที่|ไป|to)\s*", "", args, flags=re.IGNORECASE).strip()
        return ("ที่นี่", dest) if dest else None

    def _handle_api_error(self, status: str, origin: str, dest: str) -> str:
        """Return user-friendly error message based on API status"""
        if status in ("ZERO_RESULTS", "NOT_FOUND"):
            return (
                f"📍 ไม่พบเส้นทางจาก \"{origin}\" ไป \"{dest}\"\n\n"
                "ลองใช้ชื่อสถานที่ที่ชัดเจนขึ้น เช่น:\n"
                "  สยามพารากอน, MBK Center, สนามบินสุวรรณภูมิ"
            )
        if status == "MAX_WAYPOINTS_EXCEEDED":
            return "❌ ระบุได้แค่ต้นทาง-ปลายทาง ไม่รองรับหลายจุดแวะ"
        if status == "INVALID_REQUEST":
            return "❌ คำขอไม่ถูกต้อง กรุณาลองใหม่"
        if status == "OVER_DAILY_LIMIT":
            return "❌ API Key หมดโควต้าวันนี้ ลองใหม่พรุ่งนี้"
        if status == "OVER_QUERY_LIMIT":
            return "❌ เรียกใช้บ่อยเกินไป รอสักครู่แล้วลองใหม่"
        if status == "REQUEST_DENIED":
            return "❌ API Key ไม่ถูกต้อง หรือยังไม่ได้เปิดใช้ Directions API"
        return f"❌ เกิดข้อผิดพลาด: {status}"

    def _format_route(self, route: dict, origin: str, destination: str, mode: str = "driving", mode_icon: str = "🚗", avoid_tolls: bool = False, avoid_specific: list[str] | None = None) -> str:
        """Format a single route into readable output"""
        leg = route["legs"][0]
        summary = route.get("summary", "")

        start_addr = leg.get("start_address", origin)
        end_addr = leg.get("end_address", destination)
        distance = leg["distance"]["text"]
        duration_normal = leg["duration"]["text"]
        duration_traffic = leg.get("duration_in_traffic", {}).get("text", "")

        # Calculate delay
        delay_text = ""
        if "duration_in_traffic" in leg:
            normal_sec = leg["duration"]["value"]
            traffic_sec = leg["duration_in_traffic"]["value"]
            delay_sec = traffic_sec - normal_sec
            if delay_sec > 60:
                delay_min = delay_sec // 60
                delay_text = f"⚠️ รถติดเพิ่มเวลา: ~{delay_min} นาที"
            elif delay_sec <= 0:
                delay_text = "✅ การจราจรคล่องตัว"
            else:
                delay_text = "✅ การจราจรปกติ"

        lines = [
            f"{mode_icon} *เส้นทาง:* {start_addr}",
            f"➡️ *ไป:* {end_addr}",
        ]
        if avoid_tolls:
            lines.append("🚫 *ไม่ใช้ทางด่วน*")
        if avoid_specific:
            lines.append(f"🚫 *หลีกเลี่ยง:* {', '.join(avoid_specific)}")
        if summary:
            lines.append(f"🛣 *ผ่าน:* {summary}")
        lines.append("")
        lines.append(f"📏 ระยะทาง: {distance}")
        lines.append(f"⏱ เวลาปกติ: {duration_normal}")
        if duration_traffic:
            lines.append(f"🚦 เวลาจริง (traffic): {duration_traffic}")
        if delay_text:
            lines.append(delay_text)

        # Navigation steps (first 5)
        steps = leg.get("steps", [])
        if steps:
            lines.append("\n📍 *เส้นทางโดยย่อ:*")
            for i, step in enumerate(steps[:5], 1):
                instruction = re.sub(r"<[^>]+>", "", step.get("html_instructions", ""))
                step_dist = step["distance"]["text"]
                lines.append(f"  {i}. {instruction} ({step_dist})")
            if len(steps) > 5:
                lines.append(f"  ... อีก {len(steps) - 5} ขั้นตอน")

        # Google Maps directions link
        # เมื่อมีการหลีกเลี่ยงเส้นทางเฉพาะ ให้ใส่ waypoint จากขั้นตอนที่มีระยะทางมากที่สุด
        # เพื่อบังคับให้ Maps แสดงเส้นทางเดียวกับที่เลือก
        maps_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(start_addr)}"
        if avoid_specific and len(steps) > 3:
            main_step = max(steps[2:], key=lambda s: s.get("distance", {}).get("value", 0))
            loc = main_step.get("start_location", {})
            if loc.get("lat") and loc.get("lng"):
                maps_url += f"&waypoints={loc['lat']},{loc['lng']}"
        maps_url += f"&destination={urllib.parse.quote(end_addr)}&travelmode={mode}"
        lines.append(f"\n🗺 [เปิดใน Google Maps]({maps_url})")

        return "\n".join(lines)
