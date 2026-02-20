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
class Executor:

    def __init__(self, page: Page):
        self.page = page

    async def execute(
        self,
        locator: Locator,
        action: str,
        value: Optional[str] = None,

        elem_type: str = '',
        target_name: str = ''
    ) -> Dict:
        result = {"success": False, "action": action, "error": None}

        # Start capturing network calls for this action
        if hasattr(self, 'assertion_engine') and self.assertion_engine:
            self.assertion_engine.start_network_capture()

        try:
            await locator.wait_for(state="visible", timeout=3000)

            if action == "click":
                # Check if button is disabled
                is_disabled = await locator.evaluate("""
                    el => el.disabled || 
                          el.getAttribute('aria-disabled') === 'true' ||
                          el.classList.contains('mat-mdc-button-disabled')
                """)

                if is_disabled:
                    SUBMIT_KEYWORDS = ["simpan","save","submit","tambah","perbarui","update","cari","search"]
                    is_submit_type = any(kw in target_name.lower() for kw in SUBMIT_KEYWORDS)

                    if is_submit_type:
                        print(f"    ⏳ Submit button disabled, waiting up to 3s to enable...")
                        for i in range(6):
                            await asyncio.sleep(0.5)
                            is_disabled = await locator.evaluate("""
                                el => el.disabled || 
                                    el.getAttribute('aria-disabled') === 'true' ||
                                    el.classList.contains('mat-mdc-button-disabled')
                            """)
                            if not is_disabled:
                                print(f"    ✓ Button enabled after {(i+1)*0.5}s")
                                break

                    if is_disabled:
                        result["error"] = "Button remained disabled"
                        print(f"    ⚠️  Disabled immediately — skipping")
                        return result
                
                await locator.scroll_into_view_if_needed(timeout=5000)
                await locator.click(timeout=5000)
                print(f"    ✓ Clicked")

            elif action == "fill":
                await locator.fill(value or "TestValue", timeout=5000)
                print(f"    ✓ Filled: {value}")
                await asyncio.sleep(1)

            elif action == "select":
                tag = await locator.evaluate("el => el.tagName.toLowerCase()")
                if tag == 'select':
                    await locator.select_option(label=value or "", timeout=5000)
                    print(f"    ✓ Selected (native): {value}")
                else:
                    # Use improved custom dropdown handler
                    dropdown_result = await self._select_custom_dropdown(locator, value or "")
                    result["selected_value"]  = dropdown_result["selected"]
                    result["all_options"]     = dropdown_result["all_options"]
                    result["formcontrolname"] = dropdown_result.get("formcontrolname", "")

            elif action == "check":
                await locator.check(timeout=5000)
                print(f"    ✓ Checked")

            await asyncio.sleep(1.5)
            result["success"] = True
            if hasattr(self, 'assertion_engine') and self.assertion_engine:
                self.assertion_engine.stop_network_capture()

        except Exception as e:
            result["error"] = str(e)
            print(f"    ❌ Failed: {e}")

        return result

    async def _select_custom_dropdown(self, trigger: Locator, value: str) -> Dict:
        """
        Universal custom-dropdown: open, read ALL options, select value or first REAL option.
        IMPROVEMENT: Skip search inputs and select actual data options.
        """
        await trigger.scroll_into_view_if_needed(timeout=5000)
        await trigger.click(timeout=5000)
        print(f"    ✓ Opened custom dropdown")
        
        # Wait for dropdown options to render
        await asyncio.sleep(1.5)

        # Capture formcontrolname
        formcontrolname = ""
        try:
            formcontrolname = await trigger.get_attribute('formcontrolname') or ""
        except Exception:
            pass

        all_options: List[str] = []
        option_container_selectors = [
            # Angular Material (most specific first)
            '.mat-mdc-option',
            'mat-option',
            # ARIA roles
            '[role="option"]',
            # PrimeNG
            '.p-dropdown-item',
            '.p-multiselect-item',
            # Ant Design
            '.ant-select-item-option',
            # ng-select
            '.ng-option',
            # Vue Select
            '.vs__dropdown-option',
            # React Select
            '.react-select__option',
            # Generic overlay containers
            '.cdk-overlay-container mat-option',
            '.cdk-overlay-container [role="option"]',
            '.cdk-overlay-pane mat-option',
            '.dropdown-item',
            # Last resort - any visible li in overlay
            '.cdk-overlay-container li',
        ]
        
        # NEW: Helper function to check if an option is a search input
        async def is_search_input(opt_locator) -> bool:
            """Check if this option is actually a search input field"""
            try:
                # Check if it contains an input element
                has_input = await opt_locator.locator('input').count() > 0
                if has_input:
                    return True
                
                # Check if it has search-related classes
                class_attr = await opt_locator.get_attribute('class') or ""
                search_indicators = ['search', 'filter', 'input']
                if any(indicator in class_attr.lower() for indicator in search_indicators):
                    return True
                
                # Check if the text is "Search" or similar
                text = (await opt_locator.inner_text()).strip().lower()
                if text in ['search', 'filter', 'cari', 'pencarian', '']:
                    return True
                    
                return False
            except Exception:
                return False
        
        for sel in option_container_selectors:
            try:
                opts = self.page.locator(sel)
                count = await opts.count()
                if count > 0:
                    for i in range(count):
                        try:
                            opt = opts.nth(i)
                            
                            # NEW: Skip if this is a search input
                            if await is_search_input(opt):
                                print(f"    ⏭️  Skipping search input at index {i}")
                                continue
                            
                            text = (await opt.inner_text()).strip()
                            if text:
                                all_options.append(text)
                        except Exception:
                            pass
                    if all_options:
                        print(f"    📋 Available options: {all_options}")
                        break
            except Exception:
                continue

        clicked = False
        selected_value = None

        # Try to find exact match for the requested value
        specific_selectors = [
            f'mat-option:has-text("{value}")',
            f'.p-dropdown-item:has-text("{value}")',
            f'.p-multiselect-item:has-text("{value}")',
            f'.ant-select-item-option:has-text("{value}")',
            f'.ng-option:has-text("{value}")',
            f'.vs__dropdown-option:has-text("{value}")',
            f'.react-select__option:has-text("{value}")',
            f'[role="option"]:has-text("{value}")',
            f'[role="listbox"] li:has-text("{value}")',
            f'.cdk-overlay-container li:has-text("{value}")',
            f'.dropdown-item:has-text("{value}")',
        ]
        
        for sel in specific_selectors:
            try:
                opt = self.page.locator(sel).first
                if await opt.count() > 0:
                    # NEW: Check if this is a search input before clicking
                    if await is_search_input(opt):
                        continue
                        
                    await opt.wait_for(state="visible", timeout=2000)
                    await opt.click(timeout=3000)
                    selected_value = value
                    print(f"    ✓ Selected '{value}'")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            try:
                opt = self.page.get_by_role("option", name=value, exact=False)
                if await opt.count() > 0:
                    # NEW: Check if this is a search input before clicking
                    if not await is_search_input(opt.first):
                        await opt.first.click(timeout=3000)
                        selected_value = value
                        print(f"    ✓ Selected '{value}' via role=option")
                        clicked = True
            except Exception:
                pass

        # NEW: If still not clicked, select first REAL option (skip search inputs)
        if not clicked:
            for sel in option_container_selectors:
                try:
                    opts = self.page.locator(sel)
                    count = await opts.count()
                    
                    # Iterate through options to find first non-search option
                    for i in range(count):
                        opt = opts.nth(i)
                        
                        # Skip search inputs
                        if await is_search_input(opt):
                            print(f"    ⏭️  Skipping search input at index {i}")
                            continue
                        
                        # Found a real option - select it
                        await opt.wait_for(state="visible", timeout=2000)
                        selected_value = (await opt.inner_text()).strip()
                        
                        # Final check - if text is empty or still looks like search, skip
                        if not selected_value or selected_value.lower() in ['search', 'cari', 'filter']:
                            continue
                        
                        await opt.click(timeout=3000)
                        print(f"    ✓ No exact match — selected first real option (index {i}): '{selected_value}'")
                        clicked = True
                        break
                    
                    if clicked:
                        break
                        
                except Exception:
                    continue

        if not clicked:
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            raise Exception("Could not select any option from custom dropdown.")
        
        # Click outside to close dropdown
        await self.page.mouse.click(10, 10)
        await asyncio.sleep(0.5)
        
        return {
            "selected": selected_value,
            "all_options": all_options,
            "formcontrolname": formcontrolname
        }