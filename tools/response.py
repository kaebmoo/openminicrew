"""Platform-agnostic response objects for tools."""

from dataclasses import dataclass, field


@dataclass
class MediaResponse:
    text: str = ""
    image: bytes | None = None
    image_caption: str = ""
    file_bytes: bytes | None = None
    file_name: str = ""


@dataclass
class InlineKeyboardResponse:
    """Response with inline keyboard buttons — platform sends as interactive message.

    buttons format: [[{"text": "label", "callback_data": "data"}, ...], ...]
    Each inner list = one row of buttons.
    """
    text: str = ""
    buttons: list = field(default_factory=list)
    memory_text: str = ""  # ข้อความที่จะบันทึกใน memory (ถ้าต่างจาก text)
