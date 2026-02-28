"""News Summary Tool — ดึงข่าวจาก Google News RSS + สรุปด้วย LLM"""

import urllib.parse
import xml.etree.ElementTree as ET

import requests

from tools.base import BaseTool
from core.llm import llm_router
from core.user_manager import get_user, get_preference
from core.logger import get_logger

log = get_logger(__name__)


class NewsSummaryTool(BaseTool):
    name = "news_summary"
    description = "สรุปข่าวเด่นวันนี้ หรือหาข่าวตามเรื่องที่สนใจจาก Google News"
    commands = ["/news"]

    def get_tool_spec(self) -> dict:
        return {
            "name": self.name,
            "description": "ใช้สำหรับค้นหาและสรุปข่าวล่าสุดจาก Google News สามารถค้นหาตาม keyword หรือดูข่าวเด่นทั่วไปได้",
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

    async def execute(self, user_id: str, args: str = "") -> str:
        topic = args.strip()

        # 1. เลือก URL ตามการค้นหา
        if topic:
            # ค้นหาตาม Keyword
            query = urllib.parse.quote(topic)
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=th&gl=TH&ceid=TH:th"
            display_label = f"หัวข้อ: {topic}"
        else:
            # ข่าวเด่นทั่วไป
            rss_url = "https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th"
            display_label = "ข่าวเด่นทั่วไป"

        # 2. ดึงข้อมูล RSS
        try:
            resp = requests.get(rss_url, timeout=10)
            resp.raise_for_status()

            # Parse XML
            root = ET.fromstring(resp.content)
            items = root.findall("./channel/item")

            if not items:
                return f"ไม่พบข่าวสำหรับ {display_label} ในขณะนี้"

            # 3. คัดมาเฉพาะ 10 ข่าวล่าสุด เพื่อไม่ให้ context ยาวเกินไป
            max_news = 10
            news_list = []
            for item in items[:max_news]:
                title = item.findtext("title")
                pub_date = item.findtext("pubDate")
                link = item.findtext("link")
                
                # ทำความสะอาด title นิดหน่อย (ลบชื่อสำนักข่าวท้าย title ถ้ามี)
                clean_title = title.split(" - ")[0] if title and " - " in title else title
                
                # เก็บเป็น markdown list
                news_list.append(f"- [{clean_title}]({link}) (พิมพ์เมื่อ: {pub_date})")

            news_text = "\n".join(news_list)

        except Exception as e:
            log.error(f"Failed to fetch Google News: {e}")
            return "❌ เกิดข้อผิดพลาดในการดึงข้อมูลข่าวจาก Google News ลองใหม่อีกครั้ง"

        # 4. สรุปด้วย LLM
        user = get_user(user_id) or {}
        provider = get_preference(user, "default_llm")

        system_prompt = (
            "คุณเป็นผู้ประกาศข่าวอัจฉริยะ โทนภาษา: กระชับ เป็นกันเอง เข้าใจง่ายเหมือนเล่าให้เพื่อนฟัง\n"
            "ข้อมูลที่ได้รับคือหัวข้อข่าวล่าสุดจาก Google News และลิงก์\n"
            "หน้าที่ของคุณ:\n"
            "1. จัดระเบียบข่าวที่เกี่ยวข้องเข้าด้วยกันเป็นหมวดหมู่ (ถ้ามี)\n"
            "2. สรุปใจความสำคัญของแต่ละข่าวให้สั้นและกระชับ\n"
            "3. ใส่ url ของข่าวด้วยรูปแบบ [อ่านต่อ](url) ไว้ท้ายข่าวที่เกี่ยวข้องเพื่อให้ชาวบ้านคลิกไปอ่านเต็มๆได้\n"
            "ไม่ต้องอธิบายวันที่ยิบย่อย แต่เอาสาระสำคัญมาเล่าให้ฟัง"
        )

        prompt_text = f"กรุณาสรุปข่าวต่อไปนี้ ({display_label}):\n{news_text}"

        chat_resp = await llm_router.chat(
            messages=[{"role": "user", "content": prompt_text}],
            provider=provider,
            tier="cheap",
            system=system_prompt,
        )

        return f"📰 **สรุปข่าว: {display_label}**\n\n{chat_resp.get('content')}"

# ลงทะเบียน Tool ไปเลย
tool = NewsSummaryTool()
