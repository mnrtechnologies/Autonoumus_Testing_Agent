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


class ScopeManager:
    def __init__(self, target_url: str):
        self.target_url = target_url
        parsed = urlparse(target_url)
        self.target_path = parsed.path
        self.base_domain = f"{parsed.scheme}://{parsed.netloc}"

        print(f"🎯 Focused Testing Mode:")
        print(f"   Target: {target_url}")
        print(f"   Path: {self.target_path}")
        print(f"   Will ONLY test elements on this page\n")

    def is_element_in_scope(self, element: Dict, current_url: str) -> Tuple[bool, str]:
        tag = element.get('tag', '')
        href = element.get('href', '')
        text = element.get('text', '').strip()
        classes = ' '.join(element.get('classes', [])).lower()

        if tag == 'a' and href:
            absolute_url = urljoin(current_url, href)
            target_path = urlparse(absolute_url).path
            if target_path != self.target_path:
                return False, f"Navigation link to different page: {target_path}"

        nav_indicators = ['sidebar', 'sidenav', 'menu-item', 'nav-link']
        if any(indicator in classes for indicator in nav_indicators):
            if tag == 'a':
                return False, "Sidebar/menu navigation link"

        nav_texts = ['halaman utama', 'dashboard', 'home', 'beranda']
        if text.lower() in nav_texts and tag == 'a':
            return False, f"Navigation link: {text}"

        return True, "In scope"
