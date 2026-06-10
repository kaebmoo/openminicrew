from unittest.mock import patch

import pytest
from tools.weather import WeatherTool

@pytest.fixture
def weather_tool():
    return WeatherTool()

@pytest.mark.asyncio
@patch("tools.weather.requests.get")
async def test_weather_geocode_success(mock_get, weather_tool):
    """Test geocoding and weather fetching"""
    # Mock geocode response
    def side_effect(*args, **kwargs):
        class MockResp:
            def __init__(self, json_data, status=200):
                self._json = json_data
                self.status_code = status
            def json(self): return self._json
            def raise_for_status(self): pass

        url = args[0]
        if "geocode" in url:
            return MockResp({
                "status": "OK",
                "results": [{
                    "geometry": {"location": {"lat": 18.78, "lng": 100.77}},
                    "formatted_address": "Nan"
                }]
            })
        elif "currentConditions" in url:
            return MockResp({
                "temperature": {"degrees": 25},
                "weatherCondition": {"type": "SUNNY", "description": {"text": "Sunny"}}
            })
        elif "history/hours" in url:
            return MockResp({"historyHours": []})
        elif "forecast/hours" in url:
            return MockResp({"forecastHours": []})
        elif "forecast/days" in url:
            return MockResp({"forecastDays": []})
        
        return MockResp({})

    mock_get.side_effect = side_effect

    # Set fake API key for test
    with patch("tools.weather.GOOGLE_MAPS_API_KEY", "fake_key"):
        result = await weather_tool.execute(user_id="user1", args="น่าน")
        assert "Nan" in result
        assert "25°C" in result

@pytest.mark.asyncio
@patch("tools.weather.GOOGLE_MAPS_API_KEY", "")
async def test_weather_missing_api_key(weather_tool):
    result = await weather_tool.execute(user_id="user1", args="น่าน")
    assert "ยังไม่ได้ตั้งค่า Google Maps API Key" in result


def _forecast_day(year, month, day):
    return {
        "displayDate": {"year": year, "month": month, "day": day},
        "daytimeForecast": {
            "weatherCondition": {"type": "RAIN"},
            "precipitation": {"probability": {"percent": 50}},
        },
        "maxTemperature": {"degrees": 33},
        "minTemperature": {"degrees": 27},
    }


def test_thai_weekday_helper():
    from tools.weather import _thai_weekday

    assert _thai_weekday(2026, 6, 10) == "พุธ"
    assert _thai_weekday(2026, 6, 14) == "อาทิตย์"
    # ข้อมูลไม่ครบ/ไม่ valid ต้องไม่ throw
    assert _thai_weekday(None, 6, 10) == ""
    assert _thai_weekday(2026, 13, 99) == ""


def test_daily_forecast_uses_weekday_labels(weather_tool):
    # 10 วันเริ่ม 2026-06-10 (วันพุธ)
    days = [_forecast_day(2026, 6, d) for d in range(10, 20)]
    result = weather_tool._format_weather(
        "น่าน", current={}, hourly={}, history={},
        forecast={"forecastDays": days}, lat=18.78, lng=100.77,
    )

    assert "- **วันนี้**:" in result
    assert "- **พรุ่งนี้**:" in result   # 11/6
    assert "- **ศุกร์**:" in result      # 12/6
    assert "- **อาทิตย์**:" in result    # 14/6
    # ไม่แสดงวันที่แบบ d/m/yyyy ในสัปดาห์แรกแล้ว
    assert "12/6/2026" not in result
    # พ้นสัปดาห์แรก ชื่อวันซ้ำ ต้องมีวันที่กำกับ
    assert "- **พุธ 17/6**:" in result
    assert "- **ศุกร์ 19/6**:" in result


def test_target_date_header_includes_weekday(weather_tool):
    days = [_forecast_day(2026, 6, d) for d in range(10, 20)]
    result = weather_tool._format_weather(
        "น่าน", current={}, hourly={}, history={},
        forecast={"forecastDays": days}, lat=18.78, lng=100.77,
        target_date="2026-06-12",
    )

    assert "พยากรณ์วันศุกร์ที่ 12/6/2026" in result
