
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

class LoopDetector:
    def __init__(self):
        self.recent_actions: List[str] = []
        self.window_size = 5
        self.threshold = 3

    def record(self, action: str, target: str):
        signature = f"{action}:{target}"
        self.recent_actions.append(signature)
        if len(self.recent_actions) > self.window_size:
            self.recent_actions.pop(0)

    def is_looping(self) -> Tuple[bool, str]:
        if len(self.recent_actions) < self.threshold:
            return False, ""
        last_action = self.recent_actions[-1]
        count = self.recent_actions[-self.threshold:].count(last_action)
        if count >= self.threshold:
            return True, f"Same action {count} times: {last_action}"
        return False, ""