"""Weather Tool — ดูสภาพอากาศปัจจุบันและพยากรณ์ล่วงหน้าผ่าน Google Weather API"""

import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from tools.base import BaseTool
from core.config import GOOGLE_MAPS_API_KEY
from core import db
from core.logger import get_logger

log = get_logger(__name__)

# Default location: Nan Province, Thailand
NAN_LAT = 18.7836
NAN_LNG = 100.7780
NAN_NAME = "น่าน (จังหวัดน่าน)"

# Weather condition type → (emoji, คำอธิบายภาษาไทย)
# ใช้แทน description.text จาก API เพราะ API แปลไทยห่วยมาก (เช่น Clear → "ล้าง")
WEATHER_DESC = {
    # Clear / Sunny
    "CLEAR": ("☀️", "ท้องฟ้าแจ่มใส"),
    "MOSTLY_CLEAR": ("🌤", "แดดจัดเป็นส่วนใหญ่"),
    # Cloudy
    "PARTLY_CLOUDY": ("⛅", "มีเมฆบางส่วน"),
    "MOSTLY_CLOUDY": ("🌥", "เมฆมากเป็นส่วนใหญ่"),
    "CLOUDY": ("☁️", "มีเมฆมาก"),
    # Wind
    "WINDY": ("💨", "ลมแรง"),
    "WIND_AND_RAIN": ("🌬🌧", "ลมแรงและฝนตก"),
    # Rain showers
    "LIGHT_RAIN_SHOWERS": ("🌦", "ฝนตกเล็กน้อยเป็นพัก ๆ"),
    "CHANCE_OF_SHOWERS": ("🌦", "อาจมีฝนตก"),
    "SCATTERED_SHOWERS": ("🌦", "ฝนตกกระจาย"),
    "RAIN_SHOWERS": ("🌧", "ฝนตกเป็นพักๆ"),
    "HEAVY_RAIN_SHOWERS": ("⛈", "ฝนตกหนักเป็นพัก ๆ"),
    # Rain
    "LIGHT_RAIN": ("🌧", "ฝนตกเบาๆ"),
    "LIGHT_TO_MODERATE_RAIN": ("🌧", "ฝนตกเล็กน้อยถึงปานกลาง"),
    "RAIN": ("🌧", "ฝนตก"),
    "MODERATE_TO_HEAVY_RAIN": ("🌧", "ฝนตกปานกลางถึงหนัก"),
    "HEAVY_RAIN": ("⛈", "ฝนตกหนัก"),
    "RAIN_PERIODICALLY_HEAVY": ("⛈", "ฝนตกหนักเป็นช่วง ๆ"),
    # Snow showers
    "LIGHT_SNOW_SHOWERS": ("🌨", "หิมะตกเล็กน้อยเป็นพัก ๆ"),
    "CHANCE_OF_SNOW_SHOWERS": ("🌨", "อาจมีหิมะตก"),
    "SCATTERED_SNOW_SHOWERS": ("🌨", "หิมะตกกระจาย"),
    "SNOW_SHOWERS": ("🌨", "หิมะตกเป็นพักๆ"),
    "HEAVY_SNOW_SHOWERS": ("❄️", "หิมะตกหนักเป็นพัก ๆ"),
    # Snow
    "LIGHT_SNOW": ("🌨", "หิมะตกเล็กน้อย"),
    "LIGHT_TO_MODERATE_SNOW": ("🌨", "หิมะตกเล็กน้อยถึงปานกลาง"),
    "SNOW": ("❄️", "หิมะตก"),
    "MODERATE_TO_HEAVY_SNOW": ("❄️", "หิมะตกปานกลางถึงหนัก"),
    "HEAVY_SNOW": ("❄️", "หิมะตกหนัก"),
    "SNOWSTORM": ("❄️", "พายุหิมะ"),
    "SNOW_PERIODICALLY_HEAVY": ("❄️", "หิมะตกหนักเป็นช่วงๆ"),
    "HEAVY_SNOW_STORM": ("❄️", "พายุหิมะรุนแรง"),
    "BLOWING_SNOW": ("🌬❄️", "หิมะปลิว"),
    # Mixed
    "RAIN_AND_SNOW": ("🌨🌧", "ฝนปนหิมะ"),
    "HAIL": ("🧊", "ลูกเห็บ"),
    "HAIL_SHOWERS": ("🧊", "ลูกเห็บตกเป็นพักๆ"),
    # Thunderstorm
    "THUNDERSTORM": ("⛈", "พายุฝนฟ้าคะนอง"),
    "THUNDERSHOWER": ("⛈", "ฝนฟ้าคะนอง"),
    "LIGHT_THUNDERSTORM_RAIN": ("🌩", "ฝนฟ้าคะนองเล็กน้อย"),
    "SCATTERED_THUNDERSTORMS": ("🌩", "ฝนฟ้าคะนองกระจาย"),
    "HEAVY_THUNDERSTORM": ("⛈", "พายุฝนฟ้าคะนองรุนแรง"),
    # Other
    "FOG": ("🌫", "หมอก"),
}

# Override for nighttime (after sunset / before sunrise) — conditions that mention "แดด"
WEATHER_DESC_NIGHT = {
    "CLEAR": ("🌙", "ท้องฟ้าแจ่มใส"),
    "MOSTLY_CLEAR": ("🌙", "ท้องฟ้าโปร่ง"),
}

# Fallback sunrise/sunset hours if API doesn't provide them
_DEFAULT_SUNRISE_HOUR = 6
_DEFAULT_SUNSET_HOUR = 18


def _get_weather_desc(cond_type: str, hour: int | None = None,
                      sunrise_hour: int = _DEFAULT_SUNRISE_HOUR,
                      sunset_hour: int = _DEFAULT_SUNSET_HOUR,
                      fallback_text: str = "") -> tuple[str, str]:
    """Return (emoji, description) for a weather condition, using night variant when appropriate."""
    if hour is not None and (hour >= sunset_hour or hour < sunrise_hour):
        night = WEATHER_DESC_NIGHT.get(cond_type)
        if night:
            return night
    result = WEATHER_DESC.get(cond_type)
    if result:
        return result
    return ("☁️", fallback_text or cond_type)


_LOCAL_TZ = ZoneInfo("Asia/Bangkok")


def _parse_sun_time(iso_str: str) -> datetime | None:
    """Parse ISO UTC timestamp from Google Weather API → local datetime."""
    if not iso_str:
        return None
    try:
        # Truncate nanoseconds to microseconds for fromisoformat
        clean = iso_str.replace("Z", "+00:00")
        # Handle nanosecond precision: keep only 6 decimal digits
        if "." in clean:
            base, frac_and_tz = clean.split(".", 1)
            # Split fraction from timezone
            for i, c in enumerate(frac_and_tz):
                if c in ("+", "-"):
                    frac = frac_and_tz[:i][:6]
                    tz_part = frac_and_tz[i:]
                    clean = f"{base}.{frac}{tz_part}"
                    break
        return datetime.fromisoformat(clean).astimezone(_LOCAL_TZ)
    except (ValueError, TypeError):
        return None


class WeatherTool(BaseTool):
    name = "weather"
    description = "ดูสภาพอากาศปัจจุบัน และพยากรณ์อากาศล่วงหน้า 7 วัน"
    commands = ["/weather"]
    direct_output = True

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "ดูสภาพอากาศปัจจุบัน และพยากรณ์อากาศล่วงหน้า (ใช้ได้ทั้งเมื่อระบุชื่อเมือง หรือถามอากาศแถวนี้)",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "ชื่อเมืองหรือสถานที่ที่ต้องการดูสภาพอากาศ เช่น 'เชียงใหม่', 'Tokyo', 'London'. หากผู้ใช้ถามว่า 'อากาศแถวนี้' หรือไม่ระบุสถานที่ ให้เว้นว่างไว้ ระบบจะใช้ GPS ปัจจุบัน",
                    },
                    "forecast_days": {
                        "type": "integer",
                        "description": "จำนวนวันที่ต้องการพยากรณ์ล่วงหน้า (1-10). ค่าเริ่มต้น 10. ถ้าผู้ใช้ถามวันที่เจาะจง ให้คำนวณจำนวนวันจากวันนี้ เช่น วันนี้ 4 เมษา ถามวันที่ 11 เมษา = ส่ง 8. ถ้าไม่ระบุให้ใช้ค่าเริ่มต้น 10",
                    },
                    "show_history": {
                        "type": "boolean",
                        "description": "ตั้งเป็น True หากผู้ใช้ถามถึงอดีต (เช่น ย้อนหลัง, อดีต, วันก่อน, เมื่อวาน, ที่ผ่านมา, เมื่อกี้)",
                    },
                    "history_hours": {
                        "type": "integer",
                        "description": "จำนวนชั่วโมงย้อนหลังที่ต้องการดู (1-24). ค่าเริ่มต้น 24. ถ้า 'เมื่อวาน' ให้ส่ง 24, 'เมื่อ 2-3 ชั่วโมงก่อน' ให้ส่ง 3",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "วันที่เจาะจงที่อยากดูพยากรณ์ รูปแบบ YYYY-MM-DD เช่น '2026-04-11'. ถ้าระบุจะแสดงเฉพาะวันนั้น. ถ้าไม่ระบุจะแสดงทั้งหมด",
                    }
                },
            },
        }

    async def execute(self, user_id: str, args: str = "", forecast_days: int = 10, show_history: bool = False, history_hours: int = 24, target_date: str = "", **kwargs) -> str:
        if not GOOGLE_MAPS_API_KEY:
            return "❌ ยังไม่ได้ตั้งค่า Google Maps API Key ใน .env"

        query = args.strip()
        lat, lng, area_name = None, None, None

        # 1. Resolve Location
        if query:
            # Geocode the requested location
            lat, lng, area_name_from_api = self._geocode(query)
            if lat is not None:
                area_name = area_name_from_api or query
            else:
                # Fallback directly to Nan if geocode fails but user queried something? 
                # Better to just mention it's not found and we default to Nan
                lat, lng = NAN_LAT, NAN_LNG
                area_name = NAN_NAME
                query_not_found = True
        else:
            # Try to get user GPS
            from interfaces.telegram_common import get_user_location
            user_loc = get_user_location(user_id)
            if user_loc:
                lat, lng = user_loc["lat"], user_loc["lng"]
                area_name = self._reverse_geocode(lat, lng) or "ตำแหน่งปัจจุบันของคุณ"
            else:
                # Default to Nan
                lat, lng = NAN_LAT, NAN_LNG
                area_name = NAN_NAME

        # Fetch Data
        try:
            # Clamp values to safe ranges
            forecast_days = max(1, min(forecast_days, 10))
            history_hours = max(1, min(history_hours, 24))

            current_data = self._get_current_conditions(lat, lng)
            hourly_data = self._get_hourly_forecast(lat, lng, hours=6)
            history_data = self._get_hourly_history(lat, lng, hours=history_hours) if show_history else {}
            forecast_data = self._get_forecast(lat, lng, days=forecast_days)
            
            output = self._format_weather(area_name, current_data, hourly_data, history_data, forecast_data, lat, lng, target_date=target_date)
            
            # Note if fallback to Nan happened
            if lat == NAN_LAT and lng == NAN_LNG and area_name == NAN_NAME:
                if query and not getattr(self, "query_not_found", False): 
                    # it was meant to be Nan or we couldn't geocode
                    pass
                else:
                    output = "💡 เนื่องจากไม่พิกัดตำแหน่ง จึงแสดงสภาพอากาศของ จ.น่าน เป็นค่าเริ่มต้น\n(หากต้องการดูพื้นที่อื่น สามารถระบุชื่อสถานที่ เช่น `/weather เชียงใหม่` หรือแชร์ Location มาที่บอทก่อนได้ครับ)\n\n" + output

            db.log_tool_usage(
                user_id=user_id,
                tool_name=self.name,
                status="success",
                **db.make_log_field("input", query or "gps_or_nan", kind="weather_query"),
                **db.make_log_field("output", area_name, kind="weather_result"),
            )
            return output

        except requests.exceptions.RequestException as e:
            log.error(f"Weather API Error: {e}")
            db.log_tool_usage(user_id, self.name, args, status="failed", error_message=str(e))
            return "❌ ไม่สามารถดึงข้อมูลสภาพอากาศจาก Google Weather API ได้ในขณะนี้"

    def _geocode(self, query: str):
        """แปลงชื่อสถานที่เป้น lat, lng ผ่าน Googla Maps Geocoding API"""
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": query,
                    "key": GOOGLE_MAPS_API_KEY,
                    "language": "th",
                },
                timeout=5,
            )
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                res = data["results"][0]
                loc = res["geometry"]["location"]
                name = res.get("formatted_address", query)
                # Remove ", ประเทศไทย" for cleaner display
                name = name.replace(", ประเทศไทย", "").replace(" ประเทศไทย", "")
                return loc["lat"], loc["lng"], name
        except Exception as e:
            log.error(f"Geocoding error for '{query}': {e}")
        return None, None, None

    def _reverse_geocode(self, lat: float, lng: float) -> str:
        """แปลง lat, lng เป็นชื่อพื้นที่"""
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
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                name = data["results"][0].get("formatted_address", "")
                name = name.replace(", ประเทศไทย", "").replace(" ประเทศไทย", "")
                return name
        except Exception:
            pass
        return ""

    def _get_current_conditions(self, lat: float, lng: float) -> dict:
        resp = requests.get(
            "https://weather.googleapis.com/v1/currentConditions:lookup",
            params={
                "key": GOOGLE_MAPS_API_KEY,
                "location.latitude": lat,
                "location.longitude": lng,
                "languageCode": "th",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_forecast(self, lat: float, lng: float, days: int = 7) -> dict:
        resp = requests.get(
            "https://weather.googleapis.com/v1/forecast/days:lookup",
            params={
                "key": GOOGLE_MAPS_API_KEY,
                "location.latitude": lat,
                "location.longitude": lng,
                "days": days,
                "pageSize": days,
                "languageCode": "th",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_hourly_forecast(self, lat: float, lng: float, hours: int = 3) -> dict:
        resp = requests.get(
            "https://weather.googleapis.com/v1/forecast/hours:lookup",
            params={
                "key": GOOGLE_MAPS_API_KEY,
                "location.latitude": lat,
                "location.longitude": lng,
                "hours": hours,
                "languageCode": "th",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_hourly_history(self, lat: float, lng: float, hours: int = 3) -> dict:
        resp = requests.get(
            "https://weather.googleapis.com/v1/history/hours:lookup",
            params={
                "key": GOOGLE_MAPS_API_KEY,
                "location.latitude": lat,
                "location.longitude": lng,
                "hours": hours,
                "languageCode": "th",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def _format_weather(self, area_name: str, current: dict, hourly: dict, history: dict, forecast: dict, lat: float, lng: float, target_date: str = "") -> str:
        lines = []

        # --- Extract sunrise/sunset from today's forecast ---
        sunrise_hour = _DEFAULT_SUNRISE_HOUR
        sunset_hour = _DEFAULT_SUNSET_HOUR
        sunrise_dt = None
        sunset_dt = None
        today_forecast = (forecast.get("forecastDays") or [None])[0]
        if today_forecast:
            sun_events = today_forecast.get("sunEvents", {})
            sunrise_dt = _parse_sun_time(sun_events.get("sunriseTime", ""))
            sunset_dt = _parse_sun_time(sun_events.get("sunsetTime", ""))
            if sunrise_dt:
                sunrise_hour = sunrise_dt.hour
            if sunset_dt:
                sunset_hour = sunset_dt.hour

        # --- Current Conditions ---
        now_hour = datetime.now().hour
        cond = current.get("weatherCondition", {})
        cond_type = cond.get("type", "UNKNOWN")
        icon, desc = _get_weather_desc(cond_type, hour=now_hour, sunrise_hour=sunrise_hour, sunset_hour=sunset_hour,
                                       fallback_text=cond.get("description", {}).get("text", cond_type))
        
        temp = current.get("temperature", {}).get("degrees", "?")
        feels = current.get("feelsLikeTemperature", {}).get("degrees", "?")
        humid = current.get("relativeHumidity", "?")
        
        wind_speed = current.get("wind", {}).get("speed", {}).get("value", "?")
        
        rain_prob = current.get("precipitation", {}).get("probability", {}).get("percent", 0)

        # Parse target_date if provided (YYYY-MM-DD)
        target_y, target_m, target_d = 0, 0, 0
        if target_date:
            try:
                parts = target_date.split("-")
                target_y, target_m, target_d = int(parts[0]), int(parts[1]), int(parts[2])
            except (ValueError, IndexError):
                pass

        # If target_date is set, show concise header + only that day
        if target_y:
            lines.append(f"📍 **สภาพอากาศ: {area_name}**")
            lines.append(f"{icon} **ตอนนี้:** {temp}°C (รู้สึกเหมือน {feels}°C) | {desc}")
            lines.append("")

            # Filter to target date
            days_data = forecast.get("forecastDays", [])
            found = False
            for day in days_data:
                dd = day.get("displayDate", {})
                if dd.get("year") == target_y and dd.get("month") == target_m and dd.get("day") == target_d:
                    found = True
                    daytime = day.get("daytimeForecast", {})
                    nighttime = day.get("nighttimeForecast", {})
                    d_cond = daytime.get("weatherCondition", {})
                    d_icon, d_desc = WEATHER_DESC.get(d_cond.get("type", ""), ("☁️", d_cond.get("description", {}).get("text", "")))
                    n_cond = nighttime.get("weatherCondition", {})
                    n_icon, n_desc = WEATHER_DESC.get(n_cond.get("type", ""), ("☁️", n_cond.get("description", {}).get("text", "")))
                    max_t = day.get("maxTemperature", {}).get("degrees", "?")
                    min_t = day.get("minTemperature", {}).get("degrees", "?")
                    d_rain = daytime.get("precipitation", {}).get("probability", {}).get("percent", 0)
                    n_rain = nighttime.get("precipitation", {}).get("probability", {}).get("percent", 0)
                    d_humid = daytime.get("relativeHumidity", "?")
                    d_wind = daytime.get("wind", {}).get("speed", {}).get("value", "?")
                    d_uv = daytime.get("uvIndex", "?")

                    # Sunrise / Sunset for target date
                    t_sun = day.get("sunEvents", {})
                    t_sr_dt = _parse_sun_time(t_sun.get("sunriseTime", ""))
                    t_ss_dt = _parse_sun_time(t_sun.get("sunsetTime", ""))
                    t_sr_str = t_sr_dt.strftime("%H:%M") if t_sr_dt else "N/A"
                    t_ss_str = t_ss_dt.strftime("%H:%M") if t_ss_dt else "N/A"

                    lines.append(f"📅 **พยากรณ์วันที่ {target_d}/{target_m}/{target_y}:**")
                    lines.append(f"🌡 อุณหภูมิ: {min_t}°C ถึง {max_t}°C")
                    lines.append(f"☀️ กลางวัน: {d_icon} {d_desc} | ☔ ฝน {d_rain}%")
                    lines.append(f"🌙 กลางคืน: {n_icon} {n_desc} | ☔ ฝน {n_rain}%")
                    lines.append(f"💧 ความชื้น: {d_humid}% | 💨 ลม: {d_wind} km/h | ☀️ UV: {d_uv}")
                    lines.append(f"🌅 พระอาทิตย์ขึ้น: {t_sr_str} | 🌇 พระอาทิตย์ตก: {t_ss_str}")
                    break

            if not found:
                lines.append(f"❌ ไม่พบข้อมูลพยากรณ์สำหรับวันที่ {target_d}/{target_m}/{target_y}")
                lines.append("สามารถพยากรณ์ล่วงหน้าได้สูงสุด 10 วัน")

            lines.append("")
            query_safe = urllib.parse.quote(f"สภาพอากาศ {area_name}")
            lines.append(f"🔗 [ดูรายละเอียดเพิ่มเติมบน Google](https://www.google.com/search?q={query_safe})")
            return "\n".join(lines)

        # --- Full output (no target_date) ---
        lines.append(f"📍 **สภาพอากาศ: {area_name}**")
        lines.append(f"{icon} **ปัจจุบัน:** {temp}°C (รู้สึกเหมือน {feels}°C) | {desc}")
        lines.append(f"💧 ความชื้น: {humid}% | 💨 ลม: {wind_speed} km/h | ☔ โอกาสฝนตก: {rain_prob}%")
        if sunrise_dt or sunset_dt:
            sr_str = sunrise_dt.strftime("%H:%M") if sunrise_dt else "N/A"
            ss_str = sunset_dt.strftime("%H:%M") if sunset_dt else "N/A"
            lines.append(f"🌅 พระอาทิตย์ขึ้น: {sr_str} | 🌇 พระอาทิตย์ตก: {ss_str}")
        lines.append("")

        # --- Hourly History ---
        history_hours = history.get("historyHours", [])
        if history_hours:
            lines.append("🕰 **ย้อนหลัง:**")
            for h in reversed(history_hours):  # API usually returns newest to oldest, reverse to display chronological
                dt = h.get("displayDateTime", {})
                h_hour = dt.get('hours', 0)
                hr = f"{h_hour:02d}:00"
                h_temp = h.get("temperature", {}).get("degrees", "?")
                h_rain = h.get("precipitation", {}).get("probability", {}).get("percent", 0)
                h_cond = h.get("weatherCondition", {})
                h_icon, h_desc = _get_weather_desc(h_cond.get("type", ""), hour=h_hour,
                                                   sunrise_hour=sunrise_hour, sunset_hour=sunset_hour,
                                                   fallback_text=h_cond.get("description", {}).get("text", ""))

                lines.append(f"- **{hr}**: {h_temp}°C | {h_icon} {h_desc} | ☔ ฝน {h_rain}%")
            lines.append("")

        # --- Hourly Forecast ---
        hours_data = hourly.get("forecastHours", [])
        if hours_data:
            lines.append("🕒 **แนวโน้มรายชั่วโมง:**")
            for h in hours_data:
                dt = h.get("displayDateTime", {})
                h_hour = dt.get('hours', 0)
                hr = f"{h_hour:02d}:00"
                h_temp = h.get("temperature", {}).get("degrees", "?")
                h_rain = h.get("precipitation", {}).get("probability", {}).get("percent", 0)
                h_cond = h.get("weatherCondition", {})
                h_icon, h_desc = _get_weather_desc(h_cond.get("type", ""), hour=h_hour,
                                                   sunrise_hour=sunrise_hour, sunset_hour=sunset_hour,
                                                   fallback_text=h_cond.get("description", {}).get("text", ""))

                lines.append(f"- **{hr}**: {h_temp}°C | {h_icon} {h_desc} | ☔ ฝน {h_rain}%")
            lines.append("")

        # --- Daily Forecast ---
        days = forecast.get("forecastDays", [])
        if days:
            lines.append("📅 **พยากรณ์อากาศล่วงหน้า:**")
            
            for i, day in enumerate(days):
                date_dict = day.get("displayDate", {})
                
                # Make date display nicer (e.g. "วันนี้", "พรุ่งนี้", or Date)
                if i == 0:
                    date_label = "วันนี้"
                elif i == 1:
                    date_label = "พรุ่งนี้"
                else:
                    date_label = f"{date_dict.get('day', '')}/{date_dict.get('month', '')}/{date_dict.get('year', '')}"
                
                daytime = day.get("daytimeForecast", {})
                d_cond = daytime.get("weatherCondition", {})
                d_icon, d_desc = WEATHER_DESC.get(d_cond.get("type", ""), ("☁️", d_cond.get("description", {}).get("text", "")))
                
                max_t = day.get("maxTemperature", {}).get("degrees", "?")
                min_t = day.get("minTemperature", {}).get("degrees", "?")
                d_rain = daytime.get("precipitation", {}).get("probability", {}).get("percent", 0)

                lines.append(f"- **{date_label}**: {min_t}°C ถึง {max_t}°C | {d_icon} {d_desc} | ☔ ฝน {d_rain}%")

        lines.append("")
        
        # Link mapping
        query_safe = urllib.parse.quote(f"สภาพอากาศ {area_name}")
        lines.append(f"🔗 [ดูรายละเอียดเพิ่มเติมบน Google](https://www.google.com/search?q={query_safe})")
        
        return "\n".join(lines)
