"""Test: Places tool location resolution logic — restriction vs bias"""

import pytest
from unittest.mock import patch, MagicMock
from tools.places import PlacesTool


@pytest.fixture
def tool():
    return PlacesTool()


GPS_SATHORN = {"lat": 13.7210, "lng": 100.5290}


class TestResolveLocationParams:
    """Unit tests for _resolve_location_params — no API calls"""

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_nearby_keyword_uses_restriction(self, mock_loc, tool):
        """'ร้านกาแฟแถวนี้' + GPS → locationRestriction"""
        result = tool._resolve_location_params("u1", "ร้านกาแฟแถวนี้")
        assert "locationRestriction" in result
        assert "locationBias" not in result

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_nearby_en_keyword_uses_restriction(self, mock_loc, tool):
        """'coffee near me' + GPS → locationRestriction"""
        result = tool._resolve_location_params("u1", "coffee near me")
        assert "locationRestriction" in result

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_specific_name_uses_bias(self, mock_loc, tool):
        """'hole coffee' + GPS → locationBias (ไม่มี nearby keyword)"""
        result = tool._resolve_location_params("u1", "hole coffee")
        assert "locationBias" in result
        assert "locationRestriction" not in result

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_name_with_area_uses_bias(self, mock_loc, tool):
        """'hole coffee เมืองทอง' + GPS → locationBias"""
        result = tool._resolve_location_params("u1", "hole coffee เมืองทอง")
        assert "locationBias" in result
        assert "locationRestriction" not in result

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_generic_no_nearby_uses_bias(self, mock_loc, tool):
        """'ร้านกาแฟ' (ไม่มี 'แถวนี้') + GPS → locationBias"""
        result = tool._resolve_location_params("u1", "ร้านกาแฟ")
        assert "locationBias" in result
        assert "locationRestriction" not in result

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_bias_uses_gps_center(self, mock_loc, tool):
        """bias mode ใช้ GPS ของ user เป็นศูนย์กลาง ไม่ใช่ Bangkok center"""
        result = tool._resolve_location_params("u1", "hole coffee")
        center = result["locationBias"]["circle"]["center"]
        assert center["latitude"] == GPS_SATHORN["lat"]
        assert center["longitude"] == GPS_SATHORN["lng"]

    @patch("interfaces.telegram_common.get_user_location", return_value=GPS_SATHORN)
    def test_bias_radius_is_gps_bias_radius(self, mock_loc, tool):
        """bias mode ใช้ _GPS_BIAS_RADIUS ไม่ใช่ _BANGKOK_RADIUS"""
        result = tool._resolve_location_params("u1", "hole coffee")
        radius = result["locationBias"]["circle"]["radius"]
        assert radius == tool._GPS_BIAS_RADIUS

    @patch("interfaces.telegram_common.get_user_location", return_value=None)
    def test_no_gps_uses_bangkok_bias(self, mock_loc, tool):
        """ไม่มี GPS → bias กรุงเทพ 30km (เหมือนเดิม)"""
        result = tool._resolve_location_params("u1", "hole coffee")
        assert "locationBias" in result
        center = result["locationBias"]["circle"]["center"]
        assert center["latitude"] == tool._BANGKOK_CENTER["latitude"]

    @patch("interfaces.telegram_common.get_user_location", return_value=None)
    def test_no_gps_nearby_keyword_still_bias(self, mock_loc, tool):
        """'แถวนี้' แต่ไม่มี GPS → ยังคง bias (ไม่มี GPS ให้ restrict)"""
        result = tool._resolve_location_params("u1", "ร้านกาแฟแถวนี้")
        assert "locationBias" in result
        assert "locationRestriction" not in result


class TestNearbyKeywordRegex:
    """ตรวจว่า _NEARBY_KEYWORDS regex จับ keyword ได้ครบ"""

    @pytest.mark.parametrize("query", [
        "ร้านกาแฟแถวนี้",
        "ร้านอาหารใกล้นี้",
        "ร้านใกล้ๆนี้",
        "ร้านใกล้ๆ นี้",
        "ร้านตรงนี้",
        "ร้านรอบๆนี้",
        "ร้านรอบๆ นี้",
        "coffee nearby",
        "coffee near me",
        "coffee near here",
    ])
    def test_nearby_detected(self, query, tool):
        assert tool._NEARBY_KEYWORDS.search(query) is not None

    @pytest.mark.parametrize("query", [
        "hole coffee",
        "hole coffee เมืองทอง",
        "ร้านกาแฟ",
        "ร้านกาแฟสยาม",
        "Starbucks สุขุมวิท",
        "โรงพยาบาลใกล้ลาดพร้าว",   # "ใกล้ลาดพร้าว" ≠ "ใกล้นี้"
    ])
    def test_nearby_not_detected(self, query, tool):
        assert tool._NEARBY_KEYWORDS.search(query) is None
