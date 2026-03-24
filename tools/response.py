"""Platform-agnostic response object for tools that return media."""

from dataclasses import dataclass


@dataclass
class MediaResponse:
    text: str = ""
    image: bytes | None = None
    image_caption: str = ""
    file_bytes: bytes | None = None
    file_name: str = ""
