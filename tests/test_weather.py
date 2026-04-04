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
