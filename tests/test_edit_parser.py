"""Tests for core.edit_parser — free-text edit intent parsing + validation"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import edit_parser


_ITEMS = [
    {"note": "ข้าว", "amount": 40.0, "category": "อาหาร"},
    {"note": "?", "amount": 10.0, "category": "อาหาร"},
]


def _run(content):
    fake = AsyncMock(return_value={"content": content})
    with patch.object(edit_parser.llm_router, "chat", fake):
        return asyncio.run(edit_parser.parse_edit_intent(_ITEMS, "msg", user_id="u1"))


# ---- validation unit (no LLM) --------------------------------------------

def test_validate_drops_out_of_range_line():
    ops = edit_parser._validate_operations(
        [{"op": "edit", "line": 5, "note": "x"}, {"op": "edit", "line": 1, "note": "ok"}], 2
    )
    assert ops == [{"op": "edit", "line": 1, "note": "ok"}]


def test_validate_drops_bad_category_keeps_note():
    ops = edit_parser._validate_operations(
        [{"op": "edit", "line": 1, "note": "ผัดไท", "category": "ไม่มีหมวดนี้"}], 2
    )
    assert ops == [{"op": "edit", "line": 1, "note": "ผัดไท"}]


def test_validate_drops_nonpositive_amount():
    ops = edit_parser._validate_operations(
        [{"op": "edit", "line": 1, "amount": -5}, {"op": "edit", "line": 2, "amount": 30}], 2
    )
    # line1: amount invalid และไม่มี field อื่น → ตกทั้ง op; line2: amount ok
    assert ops == [{"op": "edit", "line": 2, "amount": 30.0}]


def test_validate_add_requires_amount():
    ops = edit_parser._validate_operations(
        [{"op": "add", "note": "โค้ก"}, {"op": "add", "note": "ชา", "amount": 25, "category": "เครื่องดื่ม"}], 2
    )
    assert ops == [{"op": "add", "note": "ชา", "amount": 25.0, "category": "เครื่องดื่ม"}]


def test_validate_delete_in_range():
    ops = edit_parser._validate_operations(
        [{"op": "delete", "line": 2}, {"op": "delete", "line": 9}], 2
    )
    assert ops == [{"op": "delete", "line": 2}]


def test_validate_rejects_unknown_op():
    assert edit_parser._validate_operations([{"op": "frobnicate", "line": 1}], 2) == []


# ---- parse via (mocked) LLM ----------------------------------------------

def test_parse_success():
    content = '{"operations": [{"op": "edit", "line": 2, "note": "ชาเย็น", "amount": 25}], "confidence": "high"}'
    result = _run(content)
    assert result["confidence"] == "high"
    assert result["operations"] == [{"op": "edit", "line": 2, "note": "ชาเย็น", "amount": 25.0}]


def test_parse_success_strips_markdown_fence():
    content = '```json\n{"operations": [{"op": "delete", "line": 1}], "confidence": "high"}\n```'
    result = _run(content)
    assert result["operations"] == [{"op": "delete", "line": 1}]


def test_parse_failure_no_json():
    result = _run("ขอโทษ ฉันไม่เข้าใจคำสั่งนี้เลย")
    assert result["operations"] == []
    assert result["confidence"] == "low"


def test_parse_validation_rejection_filters_invalid_ops():
    content = (
        '{"operations": ['
        '{"op": "edit", "line": 99, "note": "นอกช่วง"},'
        '{"op": "edit", "line": 1, "note": "ข้าวผัด", "category": "หมวดมั่ว"},'
        '{"op": "add", "note": "ไม่มีราคา"}'
        '], "confidence": "high"}'
    )
    result = _run(content)
    # เหลือเฉพาะ edit line1 (category มั่วถูกตัดทิ้ง), อีกสองอันตก
    assert result["operations"] == [{"op": "edit", "line": 1, "note": "ข้าวผัด"}]


def test_parse_llm_exception_is_graceful():
    fake = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(edit_parser.llm_router, "chat", fake):
        result = asyncio.run(edit_parser.parse_edit_intent(_ITEMS, "msg", user_id="u1"))
    assert result["operations"] == [] and result["confidence"] == "low"
    assert result["error"] == "llm_failed"
    assert fake.await_count == 2  # gemini + default provider ทั้งคู่ล้ม


def test_parse_falls_back_to_default_provider_on_gemini_failure():
    """P3: Gemini call ล้ม (transient) → retry provider default ของ router"""
    content = '{"operations": [{"op": "delete", "line": 1}], "confidence": "high"}'
    fake = AsyncMock(side_effect=[RuntimeError("gemini down"), {"content": content}])
    with patch.object(edit_parser.llm_router, "chat", fake):
        result = asyncio.run(edit_parser.parse_edit_intent(_ITEMS, "msg", user_id="u1"))
    assert result["operations"] == [{"op": "delete", "line": 1}]
    assert fake.await_count == 2
    # call แรกบังคับ gemini, call ที่สองไม่บังคับ provider (ใช้ default)
    assert fake.await_args_list[0].kwargs.get("provider") == "gemini"
    assert "provider" not in fake.await_args_list[1].kwargs
