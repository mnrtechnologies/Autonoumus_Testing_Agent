
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
class Controller:

    def __init__(self, page: Page):
        self.page = page

    async def find(
        self,
        intent: Dict,
        overlay_selector: Optional[str] = None
    ) -> Tuple[Optional[Locator], str]:
        """
        Find element based on intent.
        When overlay_selector is provided, scope search to that container.
        """
        target    = intent.get('target_name', '')
        elem_type = intent.get('element_type', '')

        if not target:
            return None, "No target"

        print(f"  🔍 Finding: '{target}' ({elem_type})"
              + (f" [scoped to: {overlay_selector}]" if overlay_selector else ""))

        root = self.page.locator(overlay_selector) if overlay_selector else self.page

        if elem_type == 'custom-select':
            loc = await self._by_custom_select(target, root)
            if loc:
                return loc, "custom-select"
            loc = await self._by_formcontrolname(target, root)
            if loc:
                return loc, "formcontrolname"
            return None, "Not found"

        # if elem_type in ['button', 'link', 'checkbox', 'radio', 'textbox']:
        #     loc = await self._by_role(target, elem_type, root)
        #     if loc:
        #         return loc, "role"
        
        loc = await self._by_role(target, elem_type, root)
        if loc:
            return loc, "role"
        if elem_type in ['input', 'textbox', 'select', 'textarea']:
            loc = await self._by_placeholder_label(target, root)
            if loc:
                return loc, "placeholder/label"

        loc = await self._by_formcontrolname(target, root)
        if loc:
            return loc, "formcontrolname"

        loc = await self._by_text_interactive(target, elem_type, root)
        if loc:
            return loc, "text"

        loc = await self._by_id(target, root)
        if loc:
            return loc, "id"

        loc = await self._by_partial_text_interactive(target, elem_type, root)
        if loc:
            return loc, "partial_text"

        return None, "Not found"

    async def _by_custom_select(self, target: str, root) -> Optional[Locator]:
        for tag in ['mat-select', 'ng-select', '[role="combobox"]', '']:
            sel = (f"{tag}[formcontrolname='{target}']"
                   if tag else f"[formcontrolname='{target}']")
            try:
                loc = root.locator(sel)
                if await loc.count() > 0:
                    print(f"    ✓ Found custom-select by formcontrolname: {target}")
                    return loc.first
            except Exception:
                pass

        for sel in [
            f'mat-select[aria-label="{target}"]',
            f'ng-select[aria-label="{target}"]',
            f'[role="combobox"][aria-label="{target}"]',
        ]:
            try:
                loc = root.locator(sel)
                if await loc.count() > 0:
                    print(f"    ✓ Found custom-select by aria-label: {target}")
                    return loc.first
            except Exception:
                pass

        try:
            loc = root.get_by_role('combobox', name=target, exact=False)
            if await loc.count() > 0:
                print(f"    ✓ Found custom-select by role=combobox name: {target}")
                return loc.first
        except Exception:
            pass

        try:
            loc = root.locator('mat-form-field').filter(
                has=self.page.locator(f'mat-label:has-text("{target}")')
            ).locator('mat-select')
            if await loc.count() > 0:
                print(f"    ✓ Found mat-select by mat-label: {target}")
                return loc.first
        except Exception:
            pass

        try:
            loc = root.locator(
                f'[role="combobox"]'
            ).filter(has_text=target)
            if await loc.count() > 0:
                print(f"    ✓ Found [role=combobox] by text: {target}")
                return loc.first
        except Exception:
            pass

        return None

    async def _by_role(self, name: str, role: str, root) -> Optional[Locator]:
        try:
            role_map = {
                'button': 'button', 'link': 'link',
                'checkbox': 'checkbox', 'radio': 'radio',
                'textbox': 'textbox', 'input': 'textbox'
            }
            aria_role = role_map.get(role, role)

            loc = root.get_by_role(aria_role, name=name, exact=True)
            if await loc.count() > 0:
                return loc.first

            loc = root.get_by_role(aria_role, name=name, exact=False)
            if await loc.count() > 0:
                return loc.first
        except Exception:
            pass
        return None

    async def _by_placeholder_label(self, text: str, root) -> Optional[Locator]:
        try:
            loc = root.get_by_placeholder(text, exact=True)
            if await loc.count() > 0:
                return loc.first

            loc = root.get_by_placeholder(text, exact=False)
            if await loc.count() > 0:
                return loc.first

            loc = root.get_by_label(text, exact=False)
            if await loc.count() > 0:
                return loc.first
        except Exception:
            pass
        return None

    async def _by_formcontrolname(self, text: str, root) -> Optional[Locator]:
        for tag in ['input', 'textarea', 'select', 'mat-select', 'ng-select', '']:
            selector = (f"{tag}[formcontrolname='{text}']"
                        if tag else f"[formcontrolname='{text}']")
            try:
                loc = root.locator(selector)
                if await loc.count() > 0:
                    print(f"    ✓ Found by formcontrolname ({tag or 'any'}): {text}")
                    return loc.first
            except Exception:
                pass
        return None

    async def _by_text_interactive(self, text: str, elem_type: str, root) -> Optional[Locator]:
        tag_map = {
            'button': 'button', 'link': 'a',
            'input': 'input', 'select': 'select', 'textarea': 'textarea'
        }
        tag = tag_map.get(elem_type, '')
        try:
            if tag:
                loc = root.locator(tag).filter(has_text=text)
                if await loc.count() > 0:
                    return loc.first
            else:
                role_loc = root.locator(f'[role="{elem_type}"]').filter(has_text=text)
                if await role_loc.count() > 0:
                    return role_loc.first
                # Then fall back to common tags
                for t in ['button', 'a', 'input', 'select', 'textarea']:
                    loc = root.locator(t).filter(has_text=text)
                    if await loc.count() > 0:
                        return loc.first
        except Exception:
            pass
        return None

    async def _by_id(self, id_value: str, root) -> Optional[Locator]:
        try:
            loc = root.locator(f"#{id_value}")
            if await loc.count() > 0:
                print(f"    ✓ Found by ID: #{id_value}")
                return loc.first
        except Exception:
            pass
        return None

    async def _by_partial_text_interactive(self, text: str, elem_type: str, root) -> Optional[Locator]:
        tag_map = {
            'button': 'button', 'link': 'a',
            'input': 'input', 'select': 'select', 'textarea': 'textarea'
        }
        tag = tag_map.get(elem_type, 'button')
        try:
            loc = root.locator(tag).filter(has_text=text)
            if await loc.count() > 0:
                return loc.first
        except Exception:
            pass
        return None
