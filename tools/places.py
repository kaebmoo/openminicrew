"""Places Tool — ค้นหาสถานที่ใกล้เคียง ผ่าน Google Places API (New)"""

import re

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# Price level mapping from Places API (New)
PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": "ฟรี",
    "PRICE_LEVEL_INEXPENSIVE": "💰 ราคาถูก",
    "PRICE_LEVEL_MODERATE": "💰💰 ปานกลาง",
    "PRICE_LEVEL_EXPENSIVE": "💰💰💰 แพง",
    "PRICE_LEVEL_VERY_EXPENSIVE": "💰💰💰💰 แพงมาก",
}


class PlacesTool(BaseTool):
    name = "places"
    description = "ค้นหาสถานที่จริงบนแผนที่ เช่น ร้านกาแฟ ร้านอาหาร โรงพยาบาล ร้านสะดวกซื้อ พร้อมข้อมูลรีวิว ระยะทาง และเวลาเปิด-ปิด"
    commands = ["/places", "/nearby"]
    direct_output = True

    # คำที่บ่งบอกว่าผู้ใช้หมายถึง "ตรงนี้" (ต้องใช้ GPS)
    _NEARBY_KEYWORDS = re.compile(r"(แถวนี้|ใกล้นี้|ใกล้ๆนี้|ใกล้ๆ นี้|ตรงนี้|รอบๆนี้|รอบๆ นี้|nearby|near me|near here)")

    # คำที่บ่งบอกว่าต้องการเฉพาะร้านที่เปิดอยู่
    _OPEN_NOW_KEYWORDS = re.compile(r"(เปิดอยู่|ที่เปิด|เปิดตอนนี้|open now|ยังเปิด|เปิดไหม)")

    # ดึง minimum rating จาก query เช่น "4.5 ดาวขึ้นไป", "rating 4+", "4 ดาว"
    _RATING_PATTERN = re.compile(r"(\d+\.?\d*)\s*(?:ดาว|stars?|rating)(?:\s*ขึ้นไป|\+)?", re.IGNORECASE)

    # Bangkok center fallback
    _BANGKOK_CENTER = {"latitude": 13.7563, "longitude": 100.5018}
    _BANGKOK_RADIUS = 30000.0  # 30km

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ค้นหาสถานที่จริงบนแผนที่ เช่น ร้านกาแฟ ร้านอาหาร โรงพยาบาล. "
                "ใช้เมื่อ user พูดถึงร้าน/สถานที่ เช่น 'หาร้าน...', 'ร้าน...ดีๆ', 'ร้าน...ราคาถูก', 'ร้าน...4.5 ดาว'. "
                "ต้องใช้ tool นี้เสมอเมื่อ user ถามหาร้านหรือสถานที่ ห้ามตอบจากความรู้ทั่วไป. "
                "ไม่ใช่สำหรับเช็คเส้นทาง/ระยะทาง/จราจร -- ให้ใช้ traffic แทน. "
                "แม้ผู้ใช้ไม่ระบุทำเล ระบบจะใช้พิกัด GPS ปัจจุบันของผู้ใช้เป็นค่าเริ่มต้นอัตโนมัติ. "
                "เช่น 'ร้านกาแฟแถวสยาม', 'ร้านอาหารเปิดอยู่', 'ก๋วยเตี๋ยวเรือ 4.5 ดาว ราคาไม่แพง'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "สิ่งที่ต้องการค้นหา พร้อมสถานที่ "
                            "เช่น 'ร้านกาแฟแถวสยาม', 'restaurant near Sukhumvit', "
                            "'โรงพยาบาลใกล้ลาดพร้าว'. "
                            "หากผู้ใช้ใช้คำว่า 'แถวนี้', 'ใกล้ๆ' รูปแบบนี้ หรือไม่ระบุทำเล (เช่น 'หาร้านกาแฟ') ให้ส่งคำนั้นมาเลย "
                            "เช่น 'ร้านอาหารแถวนี้' หรือ 'ร้านกาแฟ' (ระบบจะใช้พิกัด GPS ของผู้ใช้เป็นค่าเริ่มต้นเสมอ)"
                        ),
                    }
                },
                "required": ["args"],
            },
        }

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        args = args or ""
        # 1. Validate API key
        if not GOOGLE_MAPS_API_KEY:
            return (
                "❌ ยังไม่ได้ตั้งค่า Google Maps API Key\n\n"
                "วิธีตั้งค่า:\n"
                "1. ไปที่ https://console.cloud.google.com/google/maps-apis\n"
                "2. เปิดใช้ Places API (New)\n"
                "3. สร้าง API Key\n"
                "4. เพิ่มใน .env: GOOGLE_MAPS_API_KEY=your_key"
            )

        # 2. Parse arguments
        query = args.strip()
        if not query:
            return (
                "🔍 กรุณาระบุสิ่งที่ต้องการค้นหา\n\n"
                "ตัวอย่าง:\n"
                "  /places ร้านกาแฟแถวสยาม\n"
                "  /places restaurant near Sukhumvit\n"
                "  /places โรงพยาบาลใกล้ลาดพร้าว\n"
                "  /places ATM ใกล้ MBK\n"
                "  หรือพิมพ์: หาร้านกาแฟมี wifi แถวสยาม\n\n"
                "💡 ส่งตำแหน่งปัจจุบันแล้วพิมพ์ \"ร้านกาแฟแถวนี้\" ได้เลย"
            )

        # 3. Resolve location — ใช้ GPS จริงถ้ามี (restriction), fallback กรุงเทพ (bias)
        from interfaces.telegram_common import get_user_location
        nearby_requested = bool(self._NEARBY_KEYWORDS.search(query))
        user_loc = get_user_location(user_id)
        has_location = user_loc is not None

        # ถ้าผู้ใช้พิมพ์ "แถวนี้" แต่ยังไม่ได้ให้ consent location → ขอ consent
        if nearby_requested and not has_location:
            if not db.has_user_consent(user_id, db.CONSENT_LOCATION, default=False):
                from tools.response import InlineKeyboardResponse
                return InlineKeyboardResponse(
                    text=(
                        "📍 การค้นหา \"แถวนี้\" ต้องใช้ตำแหน่งของคุณ\n"
                        "ระบบจะเก็บตำแหน่งไว้ชั่วคราวเพื่อค้นหาสถานที่ใกล้เคียง\n"
                        "อนุญาตให้ใช้ตำแหน่งไหมครับ?"
                    ),
                    buttons=[[
                        {"text": "✅ อนุญาต", "callback_data": "consent:location:on"},
                        {"text": "❌ ไม่อนุญาต", "callback_data": "consent:location:off"},
                    ]],
                    memory_text="ขอ consent location สำหรับค้นหาสถานที่ใกล้เคียง",
                )

        location_params = self._resolve_location_params(user_id, query)

        # 4.5 ตรวจว่าผู้ใช้ต้องการเฉพาะร้านที่เปิดอยู่หรือไม่
        want_open_now = bool(self._OPEN_NOW_KEYWORDS.search(query))

        # 4.6 ตรวจ minimum rating filter
        min_rating = 0.0
        rating_match = self._RATING_PATTERN.search(query)
        if rating_match:
            min_rating = float(rating_match.group(1))

        # 5. Call Google Places API (New) - Text Search
        try:
            request_body = {
                "textQuery": query,
                "languageCode": "th",
                "maxResultCount": 10,
                **location_params,
            }
            if want_open_now:
                request_body["openNow"] = True

            resp = requests.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers={
                    "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                    "X-Goog-FieldMask": (
                        "places.displayName,"
                        "places.formattedAddress,"
                        "places.rating,"
                        "places.userRatingCount,"
                        "places.currentOpeningHours,"
                        "places.priceLevel,"
                        "places.nationalPhoneNumber,"
                        "places.websiteUri,"
                        "places.googleMapsUri,"
                        "places.location"
                    ),
                },
                json=request_body,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        except requests.exceptions.Timeout:
            log.error("Google Places API timeout")
            return "❌ Google Places ไม่ตอบสนอง ลองใหม่อีกครั้งครับ"
        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = resp.text[:300]
            except Exception:
                pass
            log.error("Google Places API HTTP %s: %s | body: %s", resp.status_code, e, error_body)
            if resp.status_code == 400:
                return "❌ คำค้นหาไม่ถูกต้อง กรุณาลองใหม่"
            if resp.status_code == 403:
                # แยกสาเหตุ: key ผิด vs quota exceeded vs API ไม่ได้เปิด
                body_lower = error_body.lower()
                if "quota" in body_lower or "rate" in body_lower:
                    return "❌ Google Places API ถึงขีดจำกัดการใช้งานชั่วคราว กรุณาลองใหม่ในอีกสักครู่"
                if "not activated" in body_lower or "enable" in body_lower:
                    return "❌ ยังไม่ได้เปิดใช้ Places API (New) ใน Google Cloud Console"
                return "❌ API Key ไม่ถูกต้อง หรือยังไม่ได้เปิดใช้ Places API (New)"
            if resp.status_code == 429:
                return "❌ Google Places API ถึงขีดจำกัด กรุณาลองใหม่ในอีกสักครู่"
            return f"❌ เกิดข้อผิดพลาดจาก Google Places: {resp.status_code}"
        except requests.exceptions.RequestException as e:
            log.error("Google Places API request failed: %s", e)
            return "❌ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Places"

        # 6. Filter by rating + handle empty results
        places = data.get("places", [])
        if min_rating > 0:
            places = [p for p in places if (p.get("rating") or 0) >= min_rating]
        if not places:
            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", query, kind="places_query"),
                **db.make_log_field("output", "0 places", kind="places_result_count", size=0),
            )
            return (
                f"🔍 ไม่พบสถานที่สำหรับ \"{query}\"\n\n"
                "ลองใช้คำค้นหาที่กว้างขึ้น เช่น:\n"
                "  ร้านกาแฟแถวสยาม (แทน ร้านกาแฟ latte art แถวสยาม)\n"
                "  โรงพยาบาลใกล้สุขุมวิท (แทน โรงพยาบาลเอกชนใกล้สุขุมวิท)"
            )

        # 7. สร้างข้อความตำแหน่งไว้ด้านบน
        if has_location:
            area_name = self._reverse_geocode(user_loc["lat"], user_loc["lng"])
            loc_label = area_name or "ตำแหน่ง GPS ล่าสุดของคุณ"
            if nearby_requested:
                location_line = f"📍 ค้นหาใกล้: {loc_label}\nส่ง Location ใหม่ถ้าต้องการเปลี่ยนพื้นที่\n\n"
            else:
                location_line = f"📍 ผลลัพธ์ให้น้ำหนักใกล้: {loc_label}\nพิมพ์ 'แถวนี้' เพื่อจำกัดเฉพาะรอบตำแหน่ง หรือส่ง Location ใหม่\n\n"
        else:
            location_line = "📍 ไม่มีตำแหน่ง GPS — ผลลัพธ์อิงจากกรุงเทพกลาง\nส่ง Location มาเพื่อค้นหาใกล้ตัวมากขึ้น\n\n"

        # 8. Format response — ตำแหน่งอยู่บนสุด ตามด้วยผลลัพธ์
        output = location_line + self._format_places(places, query, open_only=want_open_now, min_rating=min_rating)

        # 8. Log success
        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", query, kind="places_query"),
            **db.make_log_field("output", f"Found {len(places)} places", kind="places_result_count", size=len(places)),
        )

        return output

    def _reverse_geocode(self, lat: float, lng: float) -> str:
        """แปลง lat/lng เป็นชื่อย่าน เช่น 'แขวงทุ่งวัดดอน เขตสาทร'"""
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "latlng": f"{lat},{lng}",
                    "key": GOOGLE_MAPS_API_KEY,
                    "language": "th",
                    "result_type": "sublocality|locality",
                },
                timeout=5,
            )
            results = resp.json().get("results", [])
            if results:
                return results[0].get("formatted_address", "").replace(" ประเทศไทย", "")
        except Exception:
            pass
        return ""

    # ประมาณ 1 องศา latitude ≈ 111 km, 3km ≈ 0.027 องศา
    _GPS_OFFSET = 0.027   # ~3km — restriction สำหรับ nearby
    _GPS_BIAS_RADIUS = 10000.0  # 10km — bias สำหรับ non-nearby + GPS

    def _resolve_location_params(self, user_id: str, query: str) -> dict:
        """เลือก location parameter สำหรับ Places API.

        - มี GPS + nearby keyword ("แถวนี้") → restriction ~3km (บังคับใกล้)
        - มี GPS + ไม่มี nearby keyword → bias 10km (ให้น้ำหนักใกล้ แต่ไม่บังคับ)
        - ไม่มี GPS → bias กรุงเทพกลาง 30km
        """
        from interfaces.telegram_common import get_user_location

        user_loc = get_user_location(user_id)
        nearby_requested = bool(self._NEARBY_KEYWORDS.search(query))

        if user_loc:
            lat, lng = user_loc["lat"], user_loc["lng"]

            if nearby_requested:
                # User บอกชัดว่า "แถวนี้" → restriction 3km
                offset = self._GPS_OFFSET
                return {
                    "locationRestriction": {
                        "rectangle": {
                            "low":  {"latitude": lat - offset, "longitude": lng - offset},
                            "high": {"latitude": lat + offset, "longitude": lng + offset},
                        }
                    }
                }
            else:
                # ค้นหาเจาะจง หรือค้นหาทั่วไปแต่ไม่ได้บอก "แถวนี้"
                # → bias จาก GPS ให้น้ำหนัก แต่ไม่บังคับ
                return {
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": lat, "longitude": lng},
                            "radius": self._GPS_BIAS_RADIUS,
                        }
                    }
                }

        # ไม่มี GPS → bias กรุงเทพกลาง
        return {
            "locationBias": {
                "circle": {
                    "center": self._BANGKOK_CENTER,
                    "radius": self._BANGKOK_RADIUS,
                }
            }
        }

    def _format_places(self, places: list[dict], query: str, open_only: bool = False, min_rating: float = 0.0) -> str:
        """Format places into readable output"""
        header = f"🔍 ค้นหา \"{query}\""
        if open_only:
            header += " (เฉพาะร้านที่เปิดอยู่)"
        if min_rating > 0:
            header += f" (≥ {min_rating} ดาว)"
        lines = [header, f"พบ {len(places)} สถานที่:\n"]

        for i, place in enumerate(places, 1):
            name = place.get("displayName", {}).get("text", "ไม่ทราบชื่อ")
            address = place.get("formattedAddress", "")
            rating = place.get("rating")
            review_count = place.get("userRatingCount", 0)
            price_level = place.get("priceLevel", "")
            phone = place.get("nationalPhoneNumber", "")
            website = place.get("websiteUri", "")
            maps_url = place.get("googleMapsUri", "")

            # Name + rating
            rating_text = ""
            if rating:
                stars = "⭐" * int(round(rating))
                rating_text = f" {stars} {rating}"
                if review_count:
                    rating_text += f" ({review_count:,} รีวิว)"

            lines.append(f"*{i}. {name}*{rating_text}")

            # Address
            if address:
                lines.append(f"   📍 {address}")

            # Opening hours
            opening = place.get("currentOpeningHours", {})
            if opening:
                is_open = opening.get("openNow")
                if is_open is True:
                    lines.append("   🟢 เปิดอยู่")
                elif is_open is False:
                    lines.append("   🔴 ปิดอยู่")

            # Price level
            if price_level and price_level in PRICE_LEVELS:
                lines.append(f"   {PRICE_LEVELS[price_level]}")

            # Phone
            if phone:
                lines.append(f"   📞 {phone}")

            # Website
            if website:
                # Shorten display URL
                display_url = re.sub(r"^https?://", "", website).rstrip("/")
                if len(display_url) > 40:
                    display_url = display_url[:37] + "..."
                lines.append(f"   🌐 [{display_url}]({website})")

            # Google Maps link
            if maps_url:
                lines.append(f"   🗺 [ดูใน Google Maps]({maps_url})")

            lines.append("")  # blank line between places

        return "\n".join(lines).rstrip()
