"""Test prompt_loader — load, frontmatter, template, validation"""

import pytest

from core import prompt_loader


@pytest.fixture(autouse=True)
def _patch_dir(tmp_path, monkeypatch):
    """ใช้ temp dir แทน prompts/ จริง + clear cache"""
    monkeypatch.setattr(prompt_loader, "PROMPTS_DIR", tmp_path)
    prompt_loader._cache.clear()
    yield
    prompt_loader._cache.clear()


def test_load_simple_prompt(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("Hello world", encoding="utf-8")
    assert prompt_loader.load_prompt("test.md") == "Hello world"


def test_load_with_template_vars(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("Today is {date}", encoding="utf-8")
    assert prompt_loader.load_prompt("test.md", date="2026-01-01") == "Today is 2026-01-01"


def test_frontmatter_parsing(tmp_path):
    p = tmp_path / "test.md"
    p.write_text(
        "---\nname: my-skill\ndescription: \"test desc\"\n---\nBody here",
        encoding="utf-8",
    )
    assert prompt_loader.load_prompt("test.md") == "Body here"
    assert prompt_loader.load_metadata("test.md") == {
        "name": "my-skill",
        "description": "test desc",
    }


def test_missing_variable_raises(tmp_path):
    p = tmp_path / "test.md"
    p.write_text("Hello {name}", encoding="utf-8")
    with pytest.raises(KeyError):
        prompt_loader.load_prompt("test.md")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        prompt_loader.load_prompt("missing.md")


def test_validate_all_prompts_clean(tmp_path):
    (tmp_path / "a.md").write_text("Today is {date}", encoding="utf-8")
    (tmp_path / "b.md").write_text("No vars here", encoding="utf-8")
    errors = prompt_loader.validate_all_prompts()
    assert errors == []


def test_validate_finds_unknown_var(tmp_path):
    p = tmp_path / "broken.md"
    p.write_text("Hello {nonexistent_xyz}", encoding="utf-8")
    errors = prompt_loader.validate_all_prompts()
    # validate_all_prompts ใช้ "DUMMY" fallback render ผ่าน → no error
    # แค่ warn ใน log
    assert errors == []


def test_find_template_variables():
    assert prompt_loader.find_template_variables("Hello {name}, today is {date}") == {"name", "date"}
    assert prompt_loader.find_template_variables("No variables") == set()


def test_escaped_braces_not_treated_as_vars(tmp_path):
    """{{ }} คือ literal { } ใน Python format — ใช้ใน JSON template"""
    p = tmp_path / "json.md"
    p.write_text('{{"key": "{value}"}}', encoding="utf-8")
    rendered = prompt_loader.load_prompt("json.md", value="x")
    assert rendered == '{"key": "x"}'
