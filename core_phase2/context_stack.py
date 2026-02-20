import asyncio
import json
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple, Set
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from enum import Enum

from playwright.async_api import async_playwright, Page, Locator, FrameLocator
from openai import OpenAI



class ContextType(Enum):
    PAGE = "page"
    MODAL = "modal"
    FORM = "form"
    DROPDOWN = "dropdown"
    TABLE = "table"
    CONFIRMATION = "confirmation"


@dataclass
class ContextFrame:
    context_type: ContextType
    description: str
    timestamp: str
    url: str
    dom_hash: str
    overlay_selector: Optional[str] = None


class ContextStack:
    def __init__(self):
        self.stack: List[ContextFrame] = []
        self.max_depth = 10

    def push(self, frame: ContextFrame) -> bool:
        if len(self.stack) >= self.max_depth:
            return False
        self.stack.append(frame)
        print(f"  📚 Context: {frame.context_type.value} (depth={len(self.stack)})")
        return True

    def pop(self) -> Optional[ContextFrame]:
        if len(self.stack) > 1:
            frame = self.stack.pop()
            print(f"  📚 Context closed: {frame.context_type.value}")
            return frame
        return None

    def current(self) -> Optional[ContextFrame]:
        return self.stack[-1] if self.stack else None

    def depth(self) -> int:
        return len(self.stack)