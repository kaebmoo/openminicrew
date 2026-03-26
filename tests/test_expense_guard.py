import pytest
from unittest.mock import patch
from tools.expense import ExpenseTool

@patch("tools.expense.db.add_expense", return_value=999)
def test_expense_guard(mock_add_expense):
    tool = ExpenseTool()
    user_id = "test_user"
    
    # Cases that should be blocked
    block_cases = [
        ["150", "รับเงิน"],
        ["รับเงิน", "150"],
        ["150", "เงินเข้า"]
    ]
    for tokens in block_cases:
        res = tool._add(user_id, tokens)
        assert "ดูเหมือนเป็นรายรับ ไม่ใช่รายจ่าย" in res, f"Failed to block: {tokens}"
        
    # Cases that should pass or return usage (not blocked by income guard)
    pass_cases = [
        ["150", "อาหาร", "ข้าวกลางวัน"],
        ["150"],  # Missing category, returns usage
        ["150", "ทั่วไป"]
    ]
    for tokens in pass_cases:
        mock_add_expense.reset_mock()
        res = tool._add(user_id, tokens)
        assert "ดูเหมือนเป็นรายรับ ไม่ใช่รายจ่าย" not in res, f"Incorrectly blocked: {tokens}"
