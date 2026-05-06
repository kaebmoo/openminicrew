"""Prompt Loader — โหลด prompt จาก markdown + render template variables

Usage:
    from core.prompt_loader import load_prompt
    text = load_prompt("system/base.md", date="2026-01-01")

ไฟล์ prompt อยู่ใน prompts/ directory ใต้ project root
รองรับ:
- Template variables ด้วย Python str.format() syntax
- Frontmatter YAML (optional) — fields เก็บเป็น metadata
- Hot reload ใน dev mode (ENV: PROMPT_HOT_RELOAD=1)
- Startup validation ที่ render ทุก template ด้วย dummy values
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from core.logger import get_logger

log = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
HOT_RELOAD = os.getenv("PROMPT_HOT_RELOAD", "").lower() in ("1", "true", "yes")


@dataclass
class _CachedPrompt:
    body: str
    metadata: dict
    mtime: float


_cache: dict[str, _CachedPrompt] = {}
_cache_lock = Lock()


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """แยก YAML frontmatter ออกจาก body ถ้ามี

    Format:
        ---
        key: value
        ---
        body content here
    """
    if not text.startswith("---\n"):
        return {}, text

    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text

    frontmatter_text = parts[0][4:]
    body = parts[1].lstrip("\n")

    metadata: dict = {}
    for line in frontmatter_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip().strip('"').strip("'")

    return metadata, body


def _read_prompt_file(rel_path: str) -> _CachedPrompt:
    """อ่าน prompt file + parse frontmatter"""
    path = PROMPTS_DIR / rel_path
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {rel_path} (absolute: {path})"
        )
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text)
    return _CachedPrompt(body=body, metadata=metadata, mtime=path.stat().st_mtime)


def _get_cached(rel_path: str) -> _CachedPrompt:
    """โหลดจาก cache ถ้ามี — ใน hot reload mode จะตรวจ mtime ทุกครั้ง"""
    with _cache_lock:
        cached = _cache.get(rel_path)
        if cached is not None and not HOT_RELOAD:
            return cached

        if HOT_RELOAD and cached is not None:
            path = PROMPTS_DIR / rel_path
            if path.stat().st_mtime <= cached.mtime:
                return cached
            log.info("Hot reload: %s", rel_path)

        loaded = _read_prompt_file(rel_path)
        _cache[rel_path] = loaded
        return loaded


def load_prompt(rel_path: str, **template_vars) -> str:
    """โหลด prompt + render template variables

    Args:
        rel_path: path relative to prompts/ directory เช่น "system/base.md"
        **template_vars: ตัวแปรที่จะ substitute ใน prompt

    Returns:
        rendered prompt text (body เท่านั้น ไม่รวม frontmatter)

    Raises:
        FileNotFoundError: ไม่พบไฟล์
        KeyError: template มี variable ที่ไม่ได้ส่งมา (ตอน render)
    """
    cached = _get_cached(rel_path)
    try:
        return cached.body.format(**template_vars)
    except KeyError as e:
        raise KeyError(
            f"Missing template variable {e} in prompt {rel_path}"
        ) from e


def load_metadata(rel_path: str) -> dict:
    """โหลดเฉพาะ frontmatter metadata"""
    return _get_cached(rel_path).metadata


def find_template_variables(text: str) -> set[str]:
    """หา {variable} ทั้งหมดใน text — ใช้สำหรับ validation"""
    return set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text))


def validate_all_prompts(dummy_vars: dict[str, str] | None = None) -> list[str]:
    """Render ทุก prompt ด้วย dummy values — return list error messages

    เรียกตอน bot startup เพื่อ catch template ที่ broken ก่อน serve traffic
    """
    if dummy_vars is None:
        dummy_vars = {}

    default_dummies = {
        "date": "2026-01-01",
        "year": "2026",
        "buddhist_year": "2569",
        "today": "2026-01-01",
        "user_name": "TestUser",
        "tool_name": "test_tool",
    }
    merged = {**default_dummies, **dummy_vars}

    errors: list[str] = []
    if not PROMPTS_DIR.exists():
        return [f"PROMPTS_DIR ไม่มีอยู่จริง: {PROMPTS_DIR}"]

    for path in PROMPTS_DIR.rglob("*.md"):
        rel = path.relative_to(PROMPTS_DIR).as_posix()
        try:
            cached = _read_prompt_file(rel)
            required_vars = find_template_variables(cached.body)
            missing = required_vars - set(merged.keys())
            if missing:
                test_vars = {var: merged.get(var, "DUMMY") for var in required_vars}
                cached.body.format(**test_vars)
                log.warning(
                    "Prompt %s ใช้ตัวแปร %s ที่ไม่มีใน default dummies",
                    rel,
                    sorted(missing),
                )
            else:
                cached.body.format(**{var: merged[var] for var in required_vars})
        except Exception as e:
            errors.append(f"{rel}: {e}")

    return errors
