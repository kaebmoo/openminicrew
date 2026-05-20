"""LLM Connectivity Check — ทดสอบว่า server เชื่อมต่อแต่ละ LLM endpoint ได้ไหม

ใช้ตอน:
- Startup (main.py) → log + แจ้ง owner ถ้า provider ที่ configured เชื่อมไม่ได้
- /health endpoint → ดูสถานะ live (cached สั้นๆ เพื่อกัน hammering)

หลักการ:
- ยิง HEAD/GET ไป health_check_url ของแต่ละ provider ด้วย connect timeout สั้น (5s)
- ไม่สนใจ status code (401/404 ถือว่า OK — สำคัญที่ TCP+TLS ผ่าน)
- ถ้า ConnectTimeout / NetworkError → ระบุว่าเป็นปัญหา network ไม่ใช่ API key
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from core.providers.registry import provider_registry
from core.logger import get_logger

log = get_logger(__name__)


_HEALTH_TIMEOUT = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)

# Cache ผลล่าสุดเพื่อกัน /health ยิงถี่เกินไป
_LAST_RESULT: dict[str, Any] | None = None
_LAST_RESULT_AT: float = 0.0
_CACHE_TTL_SECONDS = 60.0


def _proxy_for_provider(name: str) -> str | None:
    """Return proxy URL ที่ provider นี้ใช้ — ถ้า reachability ต้องตรงกับ runtime จริง"""
    if name == "claude":
        try:
            from core.config import CLAUDE_HTTPS_PROXY
            return CLAUDE_HTTPS_PROXY or None
        except Exception:
            return None
    return None


async def _check_one(name: str, url: str) -> dict:
    """ทดสอบ provider เดียว — return {name, status, latency_ms, error, url, via_proxy}"""
    started = time.monotonic()
    proxy = _proxy_for_provider(name)
    client_kwargs: dict = {"timeout": _HEALTH_TIMEOUT}
    if proxy:
        try:
            client_kwargs["proxy"] = proxy  # httpx >= 0.26
        except TypeError:  # pragma: no cover
            pass
    try:
        try:
            client = httpx.AsyncClient(**client_kwargs)
        except TypeError:
            # httpx รุ่นเก่า: proxy -> proxies
            client_kwargs.pop("proxy", None)
            client_kwargs["proxies"] = proxy
            client = httpx.AsyncClient(**client_kwargs)
        try:
            # ใช้ GET เพราะบาง endpoint ไม่รับ HEAD; status code ไม่สำคัญ
            resp = await client.get(url)
        finally:
            await client.aclose()
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "name": name,
            "status": "ok",
            "latency_ms": latency_ms,
            "http_status": resp.status_code,
            "url": url,
            "via_proxy": proxy,
            "error": None,
        }
    except httpx.ConnectTimeout as e:
        return {
            "name": name, "status": "fail",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "url": url, "via_proxy": proxy,
            "error": f"connect_timeout: {e!r}", "kind": "network",
        }
    except httpx.ConnectError as e:
        return {
            "name": name, "status": "fail",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "url": url, "via_proxy": proxy,
            "error": f"connect_error: {e!r}", "kind": "network",
        }
    except httpx.TimeoutException as e:
        return {
            "name": name, "status": "fail",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "url": url, "via_proxy": proxy,
            "error": f"timeout: {e!r}", "kind": "network",
        }
    except httpx.ProxyError as e:
        return {
            "name": name, "status": "fail",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "url": url, "via_proxy": proxy,
            "error": f"proxy_error: {e!r}", "kind": "proxy",
        }
    except Exception as e:
        return {
            "name": name, "status": "fail",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "url": url, "via_proxy": proxy,
            "error": f"{type(e).__name__}: {e}", "kind": "other",
        }


async def check_llm_connectivity(only_configured: bool = True) -> dict:
    """ทดสอบ connectivity ของ LLM providers ทั้งหมด

    Args:
        only_configured: True = check เฉพาะ provider ที่มี API key
                         False = check ทุก provider ที่มี health_check_url

    Returns:
        {
            "checked_at": <unix ts>,
            "providers": [{name, status, latency_ms, error, ...}, ...],
            "any_fail": bool,
            "any_configured_fail": bool,  # สำคัญ — fail เฉพาะ provider ที่ตั้ง key ไว้
        }
    """
    targets: list[tuple[str, str]] = []
    configured_names: set[str] = set()

    for name, provider in provider_registry.providers.items():
        url = getattr(provider, "health_check_url", "") or ""
        if not url:
            continue
        is_configured = bool(provider.is_configured())
        if is_configured:
            configured_names.add(name)
        if only_configured and not is_configured:
            continue
        targets.append((name, url))

    if not targets:
        log.warning("[connectivity] no LLM providers to check (no API keys configured?)")
        return {
            "checked_at": time.time(),
            "providers": [],
            "any_fail": False,
            "any_configured_fail": False,
        }

    results = await asyncio.gather(*[_check_one(n, u) for n, u in targets])

    any_fail = any(r["status"] != "ok" for r in results)
    any_configured_fail = any(
        r["status"] != "ok" and r["name"] in configured_names for r in results
    )

    return {
        "checked_at": time.time(),
        "providers": results,
        "any_fail": any_fail,
        "any_configured_fail": any_configured_fail,
    }


async def check_llm_connectivity_cached(ttl: float = _CACHE_TTL_SECONDS) -> dict:
    """เหมือน check_llm_connectivity() แต่ cache ผลไว้ ttl วินาที"""
    global _LAST_RESULT, _LAST_RESULT_AT
    now = time.time()
    if _LAST_RESULT and (now - _LAST_RESULT_AT) < ttl:
        return _LAST_RESULT
    result = await check_llm_connectivity()
    _LAST_RESULT = result
    _LAST_RESULT_AT = now
    return result


def format_connectivity_report(report: dict) -> list[str]:
    """แปลง report เป็น log lines อ่านง่าย"""
    lines: list[str] = []
    for p in report.get("providers", []):
        via = f" via {p['via_proxy']}" if p.get("via_proxy") else ""
        if p["status"] == "ok":
            lines.append(
                f"[OK] llm.{p['name']}: reachable{via} "
                f"({p['latency_ms']}ms, http={p.get('http_status')})"
            )
        else:
            lines.append(
                f"[FAIL] llm.{p['name']}{via}: {p.get('error')} "
                f"(url={p.get('url')}, after {p['latency_ms']}ms)"
            )
    return lines


def build_owner_alert_message(report: dict) -> str | None:
    """สร้างข้อความแจ้ง owner ถ้ามี provider ที่ configured แต่เชื่อมไม่ได้"""
    failures = [
        p for p in report.get("providers", [])
        if p["status"] != "ok"
    ]
    if not failures:
        return None

    lines = [
        "⚠️ LLM connectivity check failed ตอน startup",
        "",
        "Provider ที่ configured แต่เชื่อมไม่ได้:",
    ]
    for p in failures:
        lines.append(f"• {p['name']} — {p.get('error', 'unknown')}")
    lines.append("")
    lines.append(
        "ผลกระทบ: user ที่ใช้ provider นี้จะเจอ timeout/error\n"
        "ตรวจ network egress / firewall / IPv6 ของ server"
    )
    return "\n".join(lines)


def run_connectivity_check_sync(timeout: float = 30.0) -> dict:
    """รัน connectivity check แบบ sync — เรียกจาก main.py ก่อน start event loop"""
    try:
        return asyncio.run(asyncio.wait_for(check_llm_connectivity(), timeout=timeout))
    except asyncio.TimeoutError:
        log.error(
            "[connectivity] startup check ใช้เวลานานเกิน %.1fs — ข้ามไปก่อน", timeout
        )
        return {
            "checked_at": time.time(),
            "providers": [],
            "any_fail": True,
            "any_configured_fail": True,
            "error": f"check itself timed out after {timeout}s",
        }
