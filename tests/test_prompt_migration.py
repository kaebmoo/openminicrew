"""Test ว่า prompt ที่ migrate แล้วเหมือนกับ prompt เดิม"""

from datetime import date

from core import prompt_loader


def test_system_prompt_renders():
    """system/base.md render ได้พร้อม template vars ครบ"""
    today = date.today()
    prompt = prompt_loader.load_prompt(
        "system/base.md",
        date=today.isoformat(),
        year=today.year,
        buddhist_year=today.year + 543,
        tool_routing="(tool routing here)",
        anti_hallucination="(anti hallucination here)",
        privacy="(privacy here)",
    )
    assert today.isoformat() in prompt
    assert str(today.year + 543) in prompt
    assert "OpenMiniCrew" in prompt


def test_expense_routing_loads():
    desc = prompt_loader.load_prompt("tools/expense.md")
    assert "บันทึก" in desc
    assert "promptpay" in desc.lower()


def test_promptpay_routing_loads():
    desc = prompt_loader.load_prompt("tools/promptpay.md")
    assert "PromptPay" in desc or "พร้อมเพย์" in desc
    assert "expense" in desc.lower()


def test_expense_vision_renders():
    """Gemini Vision prompt render ได้กับ user_hint ทั้ง 2 case"""
    prompt_with_hint = prompt_loader.load_prompt(
        "internal/expense_vision_extract.md",
        user_hint="ข้อมูลเพิ่มเติมจากผู้ใช้: ใบเสร็จ Villa Market",
    )
    assert "Villa Market" in prompt_with_hint
    assert "JSON" in prompt_with_hint
    assert prompt_with_hint.count("{") == prompt_with_hint.count("}")

    prompt_no_hint = prompt_loader.load_prompt(
        "internal/expense_vision_extract.md",
        user_hint="",
    )
    assert "JSON" in prompt_no_hint


def test_smart_inbox_prompt_renders():
    prompt = prompt_loader.load_prompt(
        "internal/smart_inbox_action_items.md",
        emails_block="Email 1\nFrom: a@b.com\n",
    )
    assert "action items" in prompt.lower() or "action" in prompt
    meta = prompt_loader.load_metadata("internal/smart_inbox_action_items.md")
    assert "system_prompt" in meta
    assert "inbox" in meta["system_prompt"]


def test_all_tool_routing_files_exist():
    """ทุก tool ใน registry (ที่ migrate แล้ว) มีไฟล์ prompt

    Excluded: apikeys, settings (plan ตัดสินใจไม่ migrate — ใช้ self.description)
    """
    from tools.registry import registry

    if not registry.tools:
        registry.discover()

    excluded = {"apikeys", "settings"}
    missing = []
    for tool in registry.get_all():
        if tool.name in excluded:
            continue
        path = prompt_loader.PROMPTS_DIR / f"tools/{tool.name}.md"
        if not path.exists():
            missing.append(tool.name)

    assert not missing, f"Missing tool prompts: {missing}"


def test_system_section_files_exist():
    """4 ไฟล์ใน prompts/system/"""
    base = prompt_loader.PROMPTS_DIR / "system"
    for name in ("base.md", "tool_routing.md", "anti_hallucination.md", "privacy.md"):
        assert (base / name).exists(), f"Missing system/{name}"


def test_internal_section_files_exist():
    """ไฟล์ทั้ง 6 ใน prompts/internal/ — guardrail ป้องกันลบ/rename โดยไม่ตั้งใจ

    ทุกไฟล์ใน internal/ มี Python caller ที่ load_prompt() ตรง ๆ —
    ถ้าหายจะทำให้ tool ที่เกี่ยวข้องพังตอนรัน
    """
    base = prompt_loader.PROMPTS_DIR / "internal"
    expected = (
        "expense_vision_extract.md",      # tools/expense.py::_extract_expense_from_image
        "smart_inbox_action_items.md",    # tools/smart_inbox.py::_extract_action_items
        "work_email_summary.md",          # tools/work_email.py system prompt
        "news_summary_system.md",         # tools/news_summary.py system prompt
        "dictionary_lookup.md",           # tools/dictionary.py user prompt
        "gmail_summary_system.md",        # tools/gmail_summary.py system prompt
    )
    for name in expected:
        assert (base / name).exists(), f"Missing internal/{name}"


def test_internal_prompts_render():
    """ทุกไฟล์ใน internal/ render ได้ด้วย template vars ที่ caller ส่งมา"""
    # expense_vision_extract: user_hint
    p = prompt_loader.load_prompt(
        "internal/expense_vision_extract.md", user_hint=""
    )
    assert "JSON" in p
    assert p.count("{") == p.count("}")

    # smart_inbox_action_items: emails_block + system_prompt metadata
    p = prompt_loader.load_prompt(
        "internal/smart_inbox_action_items.md", emails_block="x"
    )
    assert "action" in p.lower()
    meta = prompt_loader.load_metadata("internal/smart_inbox_action_items.md")
    assert meta.get("system_prompt", "")

    # work_email_summary: now_str
    p = prompt_loader.load_prompt(
        "internal/work_email_summary.md", now_str="01 Jan 2026 09:00"
    )
    assert "01 Jan 2026 09:00" in p
    assert "อีเมล" in p

    # news_summary_system: no template vars
    p = prompt_loader.load_prompt("internal/news_summary_system.md")
    assert "ข่าว" in p
    assert "[1]" in p

    # dictionary_lookup: word
    p = prompt_loader.load_prompt(
        "internal/dictionary_lookup.md", word="managerial"
    )
    assert "managerial" in p

    # gmail_summary_system: now_str
    p = prompt_loader.load_prompt(
        "internal/gmail_summary_system.md", now_str="01 Jan 2026 09:00"
    )
    assert "01 Jan 2026 09:00" in p
    assert "อีเมล" in p
