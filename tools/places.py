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

    # Bangkok center fallback
    _BANGKOK_CENTER = {"latitude": 13.7563, "longitude": 100.5018}
    _BANGKOK_RADIUS = 30000.0  # 30km

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ค้นหาสถานที่จริงบนแผนที่ เช่น ร้านกาแฟ ร้านอาหาร โรงพยาบาล ATM "
                "ร้านสะดวกซื้อ พร้อมข้อมูลรีวิว คะแนน เวลาเปิด-ปิด "
                "เช่น 'ร้านกาแฟแถวสยาม' หรือ 'coffee shop near MBK'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "สิ่งที่ต้องการค้นหา พร้อมสถานที่ "
                            "เช่น 'ร้านกาแฟแถวสยาม', 'restaurant near Sukhumvit', "
                            "'โรงพยาบาลใกล้ลาดพร้าว'"
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

        # 3. ถ้าพูดว่า "แถวนี้" แต่ยังไม่เคยส่งตำแหน่ง → ขอ location
        from interfaces.telegram_common import get_user_location
        if self._NEARBY_KEYWORDS.search(query) and not get_user_location(user_id):
            return (
                "📍 ยังไม่ทราบตำแหน่งปัจจุบันของคุณ\n\n"
                "กดปุ่ม 📎 (แนบไฟล์) แล้วเลือก Location เพื่อส่งตำแหน่ง\n"
                "จากนั้นพิมพ์คำถามอีกครั้งได้เลย"
            )

        # 4. Resolve location bias — ใช้ GPS จริงถ้ามี, fallback กรุงเทพ
        location_bias = self._resolve_location_bias(user_id, query)

        # 4.5 ตรวจว่าผู้ใช้ต้องการเฉพาะร้านที่เปิดอยู่หรือไม่
        want_open_now = bool(self._OPEN_NOW_KEYWORDS.search(query))

        # 5. Call Google Places API (New) - Text Search
        try:
            request_body = {
                "textQuery": query,
                "languageCode": "th",
                "maxResultCount": 10,
                "locationBias": location_bias,
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
            log.error("Google Places API HTTP error: %s", e)
            if resp.status_code == 400:
                return "❌ คำค้นหาไม่ถูกต้อง กรุณาลองใหม่"
            if resp.status_code == 403:
                return "❌ API Key ไม่ถูกต้อง หรือยังไม่ได้เปิดใช้ Places API (New)"
            return f"❌ เกิดข้อผิดพลาดจาก Google Places: {resp.status_code}"
        except requests.exceptions.RequestException as e:
            log.error("Google Places API request failed: %s", e)
            return "❌ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Places"

        # 6. Handle empty results
        places = data.get("places", [])
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

        # 7. Format response
        output = self._format_places(places, query, open_only=want_open_now)

        # 8. Log success
        db.log_tool_usage(
            user_id=user_id,
            tool_name=self.name,
            status="success",
            **db.make_log_field("input", query, kind="places_query"),
            **db.make_log_field("output", f"Found {len(places)} places", kind="places_result_count", size=len(places)),
        )

        return output

    def _resolve_location_bias(self, user_id: str, query: str) -> dict:
        """เลือก locationBias — ใช้ GPS จริงถ้าผู้ใช้พูดว่า 'แถวนี้' + เคยส่งตำแหน่ง"""
        from interfaces.telegram_common import get_user_location

        user_loc = get_user_location(user_id)

        if self._NEARBY_KEYWORDS.search(query) and user_loc:
            # ใช้ตำแหน่งจริงของ user, รัศมีแคบ 5 กม.
            return {
                "circle": {
                    "center": {"latitude": user_loc["lat"], "longitude": user_loc["lng"]},
                    "radius": 5000.0,
                }
            }

        if user_loc:
            # มีตำแหน่งแต่ไม่ได้พูดว่า "แถวนี้" — ใช้เป็น bias กว้างๆ
            return {
                "circle": {
                    "center": {"latitude": user_loc["lat"], "longitude": user_loc["lng"]},
                    "radius": self._BANGKOK_RADIUS,
                }
            }

        # Fallback: กรุงเทพกลาง
        return {
            "circle": {
                "center": self._BANGKOK_CENTER,
                "radius": self._BANGKOK_RADIUS,
            }
        }

    def _format_places(self, places: list[dict], query: str, open_only: bool = False) -> str:
        """Format places into readable output"""
        header = f"🔍 ค้นหา \"{query}\""
        if open_only:
            header += " (เฉพาะร้านที่เปิดอยู่)"
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
