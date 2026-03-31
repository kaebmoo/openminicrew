"""News Summary Tool — ดึงข่าวจาก Google News RSS + สรุปด้วย LLM"""

import urllib.parse
import xml.etree.ElementTree as ET

import requests

from tools.base import BaseTool
from core.llm import llm_router
from core.user_manager import get_user_by_id, get_preference
from core.logger import get_logger

log = get_logger(__name__)


class NewsSummaryTool(BaseTool):
    name = "news_summary"
    description = "สรุปข่าวเด่นวันนี้ หรือหาข่าวตามเรื่องที่สนใจจาก Google News"
    commands = ["/news"]

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": (
                "ค้นหาและสรุปข่าวล่าสุดจาก Google News. "
                "ใช้เมื่อ user ถามเรื่องข่าว ข่าวสาร สิ่งที่เกิดขึ้นล่าสุด. "
                "ไม่ใช่สำหรับค้นหาข้อมูลทั่วไป (ใช้ web_search). "
                "เช่น 'ข่าววันนี้', 'ข่าวเทคโนโลยี', 'มีข่าวอะไรใหม่'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": "หัวข้อข่าวที่สนใจ เช่น 'เทคโนโลยี', 'การเมือง', 'หุ้น', หรือปล่อยว่างเพื่อดูข่าวเด่นรวบยอด",
                    }
                },
            },
        }

    async def execute(self, user_id: str, args: str = "", **kwargs) -> str:
        topic = (args or "").strip()

        # 1. เลือก URL ตามการค้นหา
        if topic:
            query = urllib.parse.quote(topic)
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
            display_label = f"หัวข้อ: {topic}"
        else:
            rss_url = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
            display_label = "ข่าวเด่นทั่วไป"

        # 2. ดึงข้อมูล RSS
        try:
            resp = requests.get(rss_url, timeout=10)
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            items = root.findall("./channel/item")

            if not items:
                return f"ไม่พบข่าวสำหรับ {display_label} ในขณะนี้"

            # 3. คัดมาเฉพาะ 10 ข่าวล่าสุด
            max_news = 10
            headlines = []  # สำหรับส่งให้ LLM (ไม่มี URL)
            references = []  # สำหรับแปะท้าย (HTML clickable links)

            for i, item in enumerate(items[:max_news], 1):
                title = item.findtext("title")
                link = item.findtext("link")

                # แยกชื่อสำนักข่าวออกจาก title
                if title and " - " in title:
                    parts = title.rsplit(" - ", 1)
                    clean_title = parts[0]
                    source = parts[1].strip()
                else:
                    clean_title = title or ""
                    source = "อ่านข่าว"

                headlines.append(f"[{i}] {clean_title}")
                # สร้าง clickable link สั้นๆ แทน URL ยาว (ใช้ markdown format)
                references.append(f"{i}. [{source}]({link})")

            headlines_text = "\n".join(headlines)

        except Exception as e:
            log.error(f"Failed to fetch Google News: {e}")
            return "❌ เกิดข้อผิดพลาดในการดึงข้อมูลข่าวจาก Google News ลองใหม่อีกครั้ง"

        # 4. สรุปด้วย LLM (ส่งแค่หัวข้อ ไม่ส่ง URL)
        user = get_user_by_id(user_id) or {}
        provider = get_preference(user, "default_llm")

        system_prompt = (
            "คุณเป็นผู้ประกาศข่าวอัจฉริยะ โทนภาษา: กระชับ เป็นกันเอง เข้าใจง่าย\n"
            "ข้อมูลที่ได้รับคือหัวข้อข่าวล่าสุด แต่ละข่าวมีหมายเลขอ้างอิง [1], [2], ...\n"
            "หน้าที่ของคุณ:\n"
            "1. จัดหมวดหมู่ข่าวที่เกี่ยวข้องเข้าด้วยกัน\n"
            "2. สรุปใจความสำคัญให้สั้นกระชับ\n"
            "3. ใส่หมายเลขอ้างอิง [1] [2] ไว้ท้ายแต่ละข่าว เพื่อให้ user ไปดูลิงก์ได้\n"
            "4. ไม่ต้องใส่ URL เอง — ระบบจะใส่ให้ท้ายข้อความอัตโนมัติ"
        )

        prompt_text = f"กรุณาสรุปข่าวต่อไปนี้ ({display_label}):\n{headlines_text}"

        chat_resp = await llm_router.chat(
            messages=[{"role": "user", "content": prompt_text}],
            provider=provider,
            tier=self.preferred_tier,
            system=system_prompt,
        )

        # 5. ประกอบผลลัพธ์: สรุป + ลิงก์คลิกได้ (HTML)
        summary = chat_resp.get("content", "")
        refs_text = "\n".join(references)

        return f"📰 สรุปข่าว: {display_label}\n\n{summary}\n\n🔗 ลิงก์อ้างอิง:\n{refs_text}"
