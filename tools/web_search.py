"""Web search tool using Tavily primary and DuckDuckGo fallback."""

import re
from urllib.parse import urlparse

from core import db
from core.api_keys import get_api_key
from core.config import DEFAULT_LLM
from core.logger import get_logger
from core.user_manager import get_preference, get_user_by_id
from tools.base import BaseTool

log = get_logger(__name__)

MAX_RESULTS = 5
MAX_SNIPPET_CHARS = 220
SUMMARY_RESULT_COUNT = 3

FACTUAL_QUERY_HINTS = (
    "ราคา", "ราคา", "เท่าไร", "กี่บาท", "อัตรา", "วันที่", "วันไหน", "คืออะไร",
    "ความหมาย", "สรุป", "ล่าสุด", "วันนี้", "เท่าไหร่", "rate", "price", "what is",
    "when", "meaning", "definition",
)

PREFERRED_DOMAINS = (
    ".go.th", ".or.th", ".ac.th", ".co.th", ".gov", ".edu",
)

LOW_SIGNAL_DOMAINS = (
    "youtube.com", "youtu.be", "tiktok.com", "facebook.com", "instagram.com",
)


def _extract_domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host.removeprefix("www.")


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def _clean_snippet(text: str) -> str:
    cleaned = (text or "").replace("\n", " ")
    cleaned = re.sub(r"\[\s*\.\.\.\s*\]", " ", cleaned)
    cleaned = re.sub(r"#{1,6}\s*", " ", cleaned)
    cleaned = re.sub(r"\|+", " ", cleaned)
    cleaned = re.sub(r"-{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _truncate_snippet(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    cleaned = _clean_snippet(text)
    if len(cleaned) <= limit:
        return cleaned

    truncated = cleaned[:limit].rsplit(" ", 1)[0].strip()
    if not truncated:
        truncated = cleaned[:limit].strip()
    return truncated + "..."


def _looks_factual_query(query: str) -> bool:
    normalized = _normalize_query(query)
    if not normalized:
        return False
    return any(hint in normalized for hint in FACTUAL_QUERY_HINTS)


def _score_result(query: str, item: dict) -> int:
    normalized_query = _normalize_query(query)
    query_terms = [term for term in re.split(r"\s+", normalized_query) if len(term) >= 2]

    title = (item.get("title") or "").lower()
    snippet = (item.get("snippet") or "").lower()
    domain = _extract_domain(item.get("url") or "")

    score = 0
    if domain.endswith(PREFERRED_DOMAINS):
        score += 8
    if any(low_signal in domain for low_signal in LOW_SIGNAL_DOMAINS):
        score -= 8

    if title:
        score += 4
    if snippet:
        score += 2

    for term in query_terms:
        if term in title:
            score += 3
        if term in snippet:
            score += 1
        if term in domain:
            score += 2

    if len(snippet) > 800:
        score -= 2

    return score


def _rank_and_filter_results(query: str, results: list[dict]) -> list[dict]:
    ranked = []
    seen_urls = set()
    seen_title_domain = set()

    for item in results:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        if not title or not url:
            continue

        dedupe_key = (title.lower(), _extract_domain(url))
        if url in seen_urls or dedupe_key in seen_title_domain:
            continue

        seen_urls.add(url)
        seen_title_domain.add(dedupe_key)
        ranked.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "score": _score_result(query, item),
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)
    for item in ranked:
        item.pop("score", None)
    return ranked[:MAX_RESULTS]


async def _generate_quick_summary(query: str, results: list[dict], provider: str, tier: str) -> str:
    from core.llm import llm_router

    if not _looks_factual_query(query) or not results:
        return ""

    source_lines = []
    for idx, item in enumerate(results[:SUMMARY_RESULT_COUNT], 1):
        title = item.get("title", "")
        domain = _extract_domain(item.get("url", ""))
        snippet = _truncate_snippet(item.get("snippet", ""), limit=160)
        source_lines.append(
            f"[{idx}] {title}\nเว็บ: {domain}\nข้อมูล: {snippet}\nลิงก์: {item.get('url', '')}"
        )

    resp = await llm_router.chat(
        messages=[{
            "role": "user",
            "content": (
                f"คำค้นหา: {query}\n\n"
                "สรุปคำตอบสั้นที่สุดจากผลค้นหาด้านล่างเป็นภาษาไทย 1-2 ประโยค\n"
                "- ถ้าผลลัพธ์ยังไม่พอชัด ให้บอกตามตรงว่าข้อมูลยังไม่ชัด\n"
                "- ห้ามแต่งตัวเลขหรือข้อเท็จจริงเพิ่ม\n"
                "- ไม่ต้องใส่ bullet\n\n"
                + "\n\n".join(source_lines)
            ),
        }],
        provider=provider,
        tier=tier,
        system="คุณเป็นผู้ช่วยสรุปผลค้นหาเว็บ ตอบสั้น ตรง และยึดตาม sources ที่ให้มาเท่านั้น",
    )
    return (resp.get("content") or "").strip()


def _format_search_results(query: str, results: list[dict], quick_summary: str = "") -> str:
    if not results:
        return f"ไม่พบผลค้นหาสำหรับ: {query}"

    lines = [f"ผลค้นหาเว็บสำหรับ: {query}\n"]
    if quick_summary:
        lines.append(f"สรุปเร็ว: {quick_summary}\n")
    for idx, item in enumerate(results[:MAX_RESULTS], 1):
        title = (item.get("title") or "(ไม่มีชื่อ)").strip()
        url = (item.get("url") or "").strip()
        domain = _extract_domain(url)
        snippet = _truncate_snippet(item.get("snippet") or "")

        lines.append(f"{idx}. {title}")
        if domain:
            lines.append(f"   เว็บ: {domain}")
        if snippet:
            lines.append(f"   สรุป: {snippet}")
        if url:
            lines.append(f"   ลิงก์: {url}")
        lines.append("")

    return "\n".join(lines).strip()


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "ค้นหาข้อมูลบนเว็บหรือข่าวจากอินเทอร์เน็ตด้วย Tavily หรือ DuckDuckGo แล้วส่งผลลัพธ์ให้ LLM สรุป"
    commands = ["/search", "/google"]
    direct_output = False
    preferred_tier = "cheap"

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        query = (args or "").strip()
        if not query:
            return "❌ ใช้: /search <คำค้นหา>"

        try:
            tavily_key = get_api_key(user_id, "tavily")
            if tavily_key:
                raw_results = self._search_tavily(query, tavily_key)
            else:
                raw_results = self._search_ddg(query)
            ranked_results = _rank_and_filter_results(query, raw_results)
            user = get_user_by_id(user_id) or {}
            provider = get_preference(user, "default_llm") or DEFAULT_LLM
            quick_summary = ""
            if _looks_factual_query(query):
                try:
                    quick_summary = await _generate_quick_summary(query, ranked_results, provider, self.preferred_tier)
                except (ImportError, ValueError, RuntimeError) as e:
                    log.warning("Quick web summary failed for %s: %s", user_id, e)

            result = _format_search_results(query, ranked_results, quick_summary=quick_summary)
            db.log_tool_usage(
                user_id,
                self.name,
                status="success",
                **db.make_log_field("input", query, kind="search_query"),
                **db.make_log_field("output", result, kind="search_result"),
            )
            return result
        except (ImportError, ValueError, RuntimeError) as e:
            log.error("Web search failed for %s: %s", user_id, e)
            db.log_tool_usage(
                user_id,
                self.name,
                status="failed",
                **db.make_log_field("input", query, kind="search_query"),
                **db.make_error_fields(str(e)),
            )
            return f"❌ ค้นหาเว็บไม่สำเร็จ: {e}"

    def _search_tavily(self, query: str, api_key: str) -> list[dict]:
        import requests

        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "search_depth": "advanced", "max_results": 5},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in data.get("results", [])
        ]
        return results

    def _search_ddg(self, query: str) -> list[dict]:
        try:
            from duckduckgo_search import DDGS
        except ImportError as exc:
            raise ValueError("ไม่มี Tavily key และ duckduckgo-search ยังไม่ถูกติดตั้ง") from exc

        results = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=MAX_RESULTS):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("href", ""),
                        "snippet": item.get("body", ""),
                    }
                )
        return results

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ค้นหาข้อมูลบนเว็บจากคำถามของ user แล้วคืนผลลัพธ์ดิบให้ LLM สรุป. "
                "ใช้สำหรับค้นหาข้อมูลทั่วไป ข้อเท็จจริง รีวิว ราคา. "
                "ไม่ใช่สำหรับค้นหาข่าว/สรุปข่าว (ใช้ news_summary) "
                "และไม่ใช่สำหรับค้นหาสถานที่บนแผนที่ (ใช้ places). "
                "เช่น 'AI คืออะไร', 'รีวิว iPhone 16', 'วิธีทำ pad thai'"
            ),
            "parameters": {
                "type": "object",
                "properties": {"args": {"type": "string", "description": "คำค้นหาเว็บ"}},
                "required": ["args"],
            },
        }