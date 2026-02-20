
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
class GlobalMemory:
    """
    Global memory that persists across ALL contexts.
    Remembers every element tested in the entire session.
    """
    def __init__(self):
        self.tested_elements: Set[str] = set()
        self.tested_actions: List[Dict] = []

    def mark_tested(self, element_identifier: str, action: str):
        signature = f"{action}:{element_identifier}"
        self.tested_elements.add(signature)
        self.tested_actions.append({
            "element": element_identifier,
            "action": action,
            "timestamp": datetime.now().isoformat()
        })

    def is_tested(self, element_identifier: str, action: str) -> bool:
        signature = f"{action}:{element_identifier}"
        return signature in self.tested_elements

    def get_untested(self, elements: List[Dict], action_type: str = None) -> List[Dict]:
        untested = []
        for elem in elements:
            identifier = self._get_identifier(elem)
            if action_type:
                if not self.is_tested(identifier, action_type):
                    untested.append(elem)
            else:
                any_tested = any(
                    self.is_tested(identifier, a)
                    for a in ['click', 'fill', 'select', 'check']
                )
                if not any_tested:
                    untested.append(elem)
        return untested

    def _get_identifier(self, element: Dict) -> str:
        """
        CRITICAL: This method defines how we identify elements.
        Must be used consistently everywhere in the codebase.
        """
        is_in_overlay = element.get('in_overlay', False)
        context_prefix = 'overlay:' if is_in_overlay else 'page:'

        formcontrol = element.get('formcontrolname', '')
        if formcontrol:
            return f"{context_prefix}{element.get('tag', 'input')}:{formcontrol}"

        name_attr = element.get('name', '')
        if name_attr:
            return f"{context_prefix}{element.get('element_type', 'element')}:{name_attr}"

        text = element.get('text', '').strip()
        elem_type = element.get('element_type', element.get('tag', ''))
        if text:
            return f"{context_prefix}{elem_type}:{text[:50]}"

        id_attr = element.get('id', '')
        if id_attr:
            return f"{context_prefix}{elem_type}:#{id_attr}"

        return f"{context_prefix}{elem_type}:unknown"
