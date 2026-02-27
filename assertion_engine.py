"""
assertion_engine.py
────────────────────────────────────────────────────────────────────────────
Layer 1: Assertion Engine for the Explorer Autonomous Testing Platform

Sits on top of the existing Playwright crawler and fires AFTER every action.
Converts the system from a "smart crawler" into an actual testing platform.

Three assertion types:
  1. DOM Assertions   → Did the right elements appear/change in the page?
  2. Network Assertions → Did the API respond correctly?
  3. Visual Assertions  → Does the screenshot look correct? Any broken UI?

Usage (plug into existing executor):
    engine = AssertionEngine(page, logger, openai_client)
    result = await engine.assert_after_action(action_type, context)
────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page, Response
from openai import OpenAI


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────

class AssertionStatus(Enum):
    PASS    = "PASS"
    FAIL    = "FAIL"
    WARNING = "WARNING"
    SKIP    = "SKIP"


class AssertionType(Enum):
    DOM      = "DOM"
    NETWORK  = "NETWORK"
    VISUAL   = "VISUAL"


@dataclass
class AssertionResult:
    """Single assertion result — one check, one outcome."""
    assertion_id:   str
    assertion_type: AssertionType
    name:           str
    description:    str
    status:         AssertionStatus
    expected:       str
    actual:         str
    timestamp:      str = field(default_factory=lambda: datetime.now().isoformat())
    screenshot_path: Optional[str] = None
    duration_ms:    float = 0.0
    details:        Dict  = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "assertion_id":   self.assertion_id,
            "type":           self.assertion_type.value,
            "name":           self.name,
            "description":    self.description,
            "status":         self.status.value,
            "expected":       self.expected,
            "actual":         self.actual,
            "timestamp":      self.timestamp,
            "screenshot":     self.screenshot_path,
            "duration_ms":    self.duration_ms,
            "details":        self.details,
        }


@dataclass
class ActionAssertionReport:
    """All assertion results for a single action (click, fill, upload etc.)"""
    action_id:    str
    action_type:  str
    url:          str
    timestamp:    str = field(default_factory=lambda: datetime.now().isoformat())
    assertions:   List[AssertionResult] = field(default_factory=list)

    @property
    def passed(self)  -> int: return sum(1 for a in self.assertions if a.status == AssertionStatus.PASS)
    @property
    def failed(self)  -> int: return sum(1 for a in self.assertions if a.status == AssertionStatus.FAIL)
    @property
    def warnings(self)-> int: return sum(1 for a in self.assertions if a.status == AssertionStatus.WARNING)
    @property
    def overall_status(self) -> AssertionStatus:
        if self.failed > 0:   return AssertionStatus.FAIL
        if self.warnings > 0: return AssertionStatus.WARNING
        return AssertionStatus.PASS

    def to_dict(self) -> Dict:
        return {
            "action_id":      self.action_id,
            "action_type":    self.action_type,
            "url":            self.url,
            "timestamp":      self.timestamp,
            "summary":        {"passed": self.passed, "failed": self.failed, "warnings": self.warnings},
            "overall_status": self.overall_status.value,
            "assertions":     [a.to_dict() for a in self.assertions],
        }


# ─────────────────────────────────────────────────────────────
# DOM Assertion Module
# ─────────────────────────────────────────────────────────────

class DOMAssertions:
    """
    Checks the DOM state after an action.
    All methods return AssertionResult — never raise exceptions.
    """

    def __init__(self, page: Page, output_dir: Path):
        self.page       = page
        self.output_dir = output_dir
        self._counter   = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter:04d}"

    async def assert_element_visible(
        self,
        selector: str,
        description: str,
        timeout_ms: int = 3000
    ) -> AssertionResult:
        """Assert that a specific element is visible on the page."""
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            await self.page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
            return AssertionResult(
                assertion_id   = aid,
                assertion_type = AssertionType.DOM,
                name           = "Element Visible",
                description    = description,
                status         = AssertionStatus.PASS,
                expected       = f"Element '{selector}' is visible",
                actual         = "Element found and visible",
                duration_ms    = (time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id   = aid,
                assertion_type = AssertionType.DOM,
                name           = "Element Visible",
                description    = description,
                status         = AssertionStatus.FAIL,
                expected       = f"Element '{selector}' is visible",
                actual         = f"Element not found within {timeout_ms}ms: {str(e)[:100]}",
                duration_ms    = (time.time() - start) * 1000,
            )

    async def assert_text_present(
        self,
        text: str,
        description: str,
        case_sensitive: bool = False
    ) -> AssertionResult:
        """Assert that specific text exists anywhere on the page."""
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            page_content = await self.page.content()
            check_text   = text if case_sensitive else text.lower()
            check_page   = page_content if case_sensitive else page_content.lower()
            found        = check_text in check_page

            return AssertionResult(
                assertion_id   = aid,
                assertion_type = AssertionType.DOM,
                name           = "Text Present",
                description    = description,
                status         = AssertionStatus.PASS if found else AssertionStatus.FAIL,
                expected       = f"Page contains text: '{text}'",
                actual         = "Text found on page" if found else f"Text '{text}' NOT found on page",
                duration_ms    = (time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id   = aid, assertion_type=AssertionType.DOM,
                name="Text Present", description=description,
                status=AssertionStatus.FAIL,
                expected=f"Page contains: '{text}'", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_text_not_present(
        self,
        text: str,
        description: str
    ) -> AssertionResult:
        """Assert that specific text does NOT exist on the page (negative check)."""
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            page_content = (await self.page.content()).lower()
            found        = text.lower() in page_content
            return AssertionResult(
                assertion_id   = aid,
                assertion_type = AssertionType.DOM,
                name           = "Text Not Present",
                description    = description,
                status         = AssertionStatus.FAIL if found else AssertionStatus.PASS,
                expected       = f"Page should NOT contain: '{text}'",
                actual         = f"Text '{text}' WAS found — unexpected" if found else "Text correctly absent",
                duration_ms    = (time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Text Not Present", description=description,
                status=AssertionStatus.FAIL,
                expected=f"Page should NOT contain: '{text}'", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_success_message(self) -> AssertionResult:
        """
        After any create/update/delete action, check if a success toast/snackbar appeared.
        Covers Material, Bootstrap, PrimeNG, and generic success patterns.
        """
        start = time.time()
        aid   = self._next_id("DOM")

        success_selectors = [
            # Angular Material snackbar
            'mat-snack-bar-container',
            '.mat-snack-bar-container',
            # Bootstrap toast/alert
            '.toast.show',
            '.alert-success',
            # PrimeNG toast
            '.p-toast-message-success',
            # Generic patterns
            '[class*="success"]',
            '[class*="Success"]',
            '[role="alert"]',
            '[role="status"]',
        ]
        success_keywords = [
            'success', 'saved', 'created', 'updated', 'deleted',
            'berhasil', 'tersimpan',  # Indonesian (seen in codebase)
            'added', 'completed', 'done',
        ]

        try:
            for selector in success_selectors:
                try:
                    el = self.page.locator(selector).first
                    if await el.count() > 0:
                        text = (await el.inner_text()).lower().strip()
                        if any(kw in text for kw in success_keywords) or len(text) > 0:
                            return AssertionResult(
                                assertion_id=aid, assertion_type=AssertionType.DOM,
                                name="Success Message",
                                description="Action should produce a success notification",
                                status=AssertionStatus.PASS,
                                expected="Success message or toast appeared",
                                actual=f"Found: '{text[:100]}' via '{selector}'",
                                duration_ms=(time.time() - start) * 1000,
                            )
                except Exception:
                    continue

            # Also check page text for success keywords
            page_text = (await self.page.inner_text("body")).lower()
            for kw in success_keywords:
                if kw in page_text:
                    return AssertionResult(
                        assertion_id=aid, assertion_type=AssertionType.DOM,
                        name="Success Message",
                        description="Action should produce a success notification",
                        status=AssertionStatus.PASS,
                        expected="Success message appeared",
                        actual=f"Keyword '{kw}' found in page body",
                        duration_ms=(time.time() - start) * 1000,
                    )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Success Message",
                description="Action should produce a success notification",
                status=AssertionStatus.WARNING,
                expected="Success message or toast appeared",
                actual="No success indicator found — action may have silently failed",
                duration_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Success Message", description="Success notification check",
                status=AssertionStatus.FAIL,
                expected="Success message appeared", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_error_message(
        self,
        expected_error_keyword: Optional[str] = None
    ) -> AssertionResult:
        """
        For NEGATIVE tests: assert that an error message appeared.
        Optionally check that the error contains a specific keyword.
        """
        start = time.time()
        aid   = self._next_id("DOM")

        error_selectors = [
            'mat-error',
            '.mat-error',
            '.alert-danger',
            '.alert-error',
            '.p-toast-message-error',
            '[class*="error"]',
            '[class*="Error"]',
            '[class*="invalid"]',
            '[role="alert"]',
        ]
        error_keywords = [
            'error', 'invalid', 'required', 'failed', 'wrong',
            'tidak valid', 'wajib', 'gagal',  # Indonesian
        ]

        try:
            found_text = None
            for selector in error_selectors:
                try:
                    els = self.page.locator(selector)
                    count = await els.count()
                    for i in range(min(count, 5)):
                        text = (await els.nth(i).inner_text()).strip()
                        if text:
                            found_text = text
                            break
                    if found_text:
                        break
                except Exception:
                    continue

            if found_text:
                keyword_match = True
                if expected_error_keyword:
                    keyword_match = expected_error_keyword.lower() in found_text.lower()

                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.DOM,
                    name="Error Message Present",
                    description=f"System should show error for invalid input",
                    status=AssertionStatus.PASS if keyword_match else AssertionStatus.WARNING,
                    expected=f"Error message containing '{expected_error_keyword}'" if expected_error_keyword else "Any error message",
                    actual=f"Error found: '{found_text[:100]}'",
                    duration_ms=(time.time() - start) * 1000,
                )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Error Message Present",
                description="System should show error for invalid input",
                status=AssertionStatus.FAIL,
                expected="Error message appeared after invalid input",
                actual="No error message found — system may have accepted invalid input",
                duration_ms=(time.time() - start) * 1000,
            )

        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Error Message Present", description="Error message check",
                status=AssertionStatus.FAIL,
                expected="Error message appeared", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_form_not_submitted(self) -> AssertionResult:
        """
        Negative test: after submitting an invalid form,
        assert the modal/form is still open (not dismissed).
        """
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            form_selectors = [
                'mat-dialog-container',
                '[role="dialog"]',
                'form',
                '.modal.show',
            ]
            for sel in form_selectors:
                el = self.page.locator(sel).first
                if await el.count() > 0:
                    visible = await el.is_visible()
                    if visible:
                        return AssertionResult(
                            assertion_id=aid, assertion_type=AssertionType.DOM,
                            name="Form Not Submitted",
                            description="Invalid form should stay open and not be submitted",
                            status=AssertionStatus.PASS,
                            expected="Form remains open after invalid submission attempt",
                            actual=f"Form still visible via '{sel}'",
                            duration_ms=(time.time() - start) * 1000,
                        )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Form Not Submitted",
                description="Invalid form should stay open",
                status=AssertionStatus.FAIL,
                expected="Form remains open",
                actual="Form appears to have closed — may have accepted invalid input",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Form Not Submitted", description="Form open check",
                status=AssertionStatus.FAIL,
                expected="Form remains open", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_list_updated(
        self,
        item_name: str,
        should_exist: bool = True
    ) -> AssertionResult:
        """
        After create/delete, assert the item appears in (or is gone from) the list.
        """
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            page_text = (await self.page.inner_text("body")).lower()
            found     = item_name.lower() in page_text

            if should_exist:
                status = AssertionStatus.PASS if found else AssertionStatus.FAIL
                actual = f"'{item_name}' found in list" if found else f"'{item_name}' NOT found in list"
                expected = f"'{item_name}' should appear in the list"
            else:
                status = AssertionStatus.PASS if not found else AssertionStatus.FAIL
                actual = f"'{item_name}' correctly absent from list" if not found else f"'{item_name}' still present — deletion may have failed"
                expected = f"'{item_name}' should be removed from the list"

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="List Updated",
                description=f"List should {'contain' if should_exist else 'not contain'} '{item_name}'",
                status=status, expected=expected, actual=actual,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="List Updated", description="List update check",
                status=AssertionStatus.FAIL,
                expected="List to reflect change", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_radio_group_exclusive(
        self,
        group_selector: str = 'mat-radio-group, [role="radiogroup"]'
    ) -> AssertionResult:
        """
        After clicking a radio button, assert only ONE is selected in the group.
        """
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            selected_count = await self.page.evaluate(f"""
                () => {{
                    const radios = document.querySelectorAll(
                        'input[type="radio"]:checked, mat-radio-button.mat-radio-checked, [role="radio"][aria-checked="true"]'
                    );
                    // Group by name attribute
                    const groups = {{}};
                    radios.forEach(r => {{
                        const name = r.getAttribute('name') || r.getAttribute('aria-labelledby') || 'default';
                        groups[name] = (groups[name] || 0) + 1;
                    }});
                    return Object.values(groups);
                }}
            """)

            over_selected = [count for count in selected_count if count > 1]
            if over_selected:
                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.DOM,
                    name="Radio Group Exclusive",
                    description="Only one radio button should be selected per group",
                    status=AssertionStatus.FAIL,
                    expected="Exactly 1 radio selected per group",
                    actual=f"Groups with multiple selections: {over_selected}",
                    duration_ms=(time.time() - start) * 1000,
                )
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Radio Group Exclusive",
                description="Only one radio button should be selected per group",
                status=AssertionStatus.PASS,
                expected="Exactly 1 radio selected per group",
                actual="All radio groups have exactly 1 selection",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Radio Group Exclusive", description="Radio group exclusivity",
                status=AssertionStatus.FAIL,
                expected="Exactly 1 radio per group", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_toggle_state_changed(
        self,
        selector: str,
        expected_state: bool
    ) -> AssertionResult:
        """After clicking a toggle, assert it is now in the expected state."""
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            state = await self.page.evaluate(f"""
                () => {{
                    const el = document.querySelector('{selector}');
                    if (!el) return null;
                    const checked = el.checked
                        || el.getAttribute('aria-checked') === 'true'
                        || el.classList.contains('mat-checked')
                        || el.classList.contains('is-checked');
                    return checked;
                }}
            """)

            if state is None:
                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.DOM,
                    name="Toggle State", description="Toggle state check",
                    status=AssertionStatus.FAIL,
                    expected=f"Toggle is {'ON' if expected_state else 'OFF'}",
                    actual=f"Toggle element '{selector}' not found",
                    duration_ms=(time.time() - start) * 1000,
                )

            match = bool(state) == expected_state
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Toggle State Changed",
                description=f"Toggle should be {'ON' if expected_state else 'OFF'} after click",
                status=AssertionStatus.PASS if match else AssertionStatus.FAIL,
                expected=f"Toggle state: {'ON' if expected_state else 'OFF'}",
                actual=f"Toggle state: {'ON' if state else 'OFF'}",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Toggle State Changed", description="Toggle state",
                status=AssertionStatus.FAIL,
                expected=f"Toggle {'ON' if expected_state else 'OFF'}", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_search_results_relevant(
        self,
        search_term: str
    ) -> AssertionResult:
        """
        After a search, assert ALL visible results contain the search term.
        This is the core search validation requirement.
        """
        start = time.time()
        aid   = self._next_id("DOM")
        try:
            results = await self.page.evaluate(f"""
                () => {{
                    // Common result row selectors
                    const rowSelectors = [
                        'table tbody tr',
                        '[class*="list-item"]',
                        '[class*="row"]',
                        '.cdk-row',
                        'mat-row',
                        '[role="row"]',
                        '.card',
                        '[class*="item"]',
                    ];

                    for (const sel of rowSelectors) {{
                        const rows = document.querySelectorAll(sel);
                        if (rows.length > 0) {{
                            return Array.from(rows).map(r => r.innerText.trim()).filter(t => t.length > 0);
                        }}
                    }}
                    return [];
                }}
            """)

            if not results:
                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.DOM,
                    name="Search Results Relevant",
                    description=f"Search for '{search_term}' should return matching results",
                    status=AssertionStatus.WARNING,
                    expected=f"Results containing '{search_term}'",
                    actual="No result rows found in DOM — page may have a different structure",
                    duration_ms=(time.time() - start) * 1000,
                )

            term_lower = search_term.lower()
            irrelevant = [r[:80] for r in results if term_lower not in r.lower()]

            if irrelevant:
                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.DOM,
                    name="Search Results Relevant",
                    description=f"Search for '{search_term}' — all results must contain the term",
                    status=AssertionStatus.FAIL,
                    expected=f"All results contain '{search_term}'",
                    actual=f"{len(irrelevant)} irrelevant result(s) found: {irrelevant[:3]}",
                    duration_ms=(time.time() - start) * 1000,
                    details={"total_results": len(results), "irrelevant": irrelevant},
                )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Search Results Relevant",
                description=f"Search for '{search_term}'",
                status=AssertionStatus.PASS,
                expected=f"All results contain '{search_term}'",
                actual=f"All {len(results)} result(s) are relevant",
                duration_ms=(time.time() - start) * 1000,
                details={"total_results": len(results)},
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Search Results Relevant", description="Search relevance check",
                status=AssertionStatus.FAIL,
                expected=f"Relevant results for '{search_term}'", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_empty_state_shown(self) -> AssertionResult:
        """
        After a search with no results, assert a proper empty state message is shown
        rather than a broken/blank UI.
        """
        start = time.time()
        aid   = self._next_id("DOM")
        empty_keywords = [
            'no result', 'no data', 'not found', 'empty', 'nothing found',
            'tidak ada', 'data tidak', 'kosong',  # Indonesian
            '0 result', '0 item',
        ]
        try:
            page_text = (await self.page.inner_text("body")).lower()
            for kw in empty_keywords:
                if kw in page_text:
                    return AssertionResult(
                        assertion_id=aid, assertion_type=AssertionType.DOM,
                        name="Empty State Shown",
                        description="When no results found, a clear empty state message should appear",
                        status=AssertionStatus.PASS,
                        expected="Empty state message visible",
                        actual=f"Found empty indicator: '{kw}'",
                        duration_ms=(time.time() - start) * 1000,
                    )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Empty State Shown",
                description="Empty state message check",
                status=AssertionStatus.FAIL,
                expected="Clear 'no results' message displayed",
                actual="No empty state message found — UI may appear broken or show stale data",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.DOM,
                name="Empty State Shown", description="Empty state check",
                status=AssertionStatus.FAIL,
                expected="Empty state message", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )


# ─────────────────────────────────────────────────────────────
# Network Assertion Module
# ─────────────────────────────────────────────────────────────

class NetworkAssertions:
    """
    Intercepts and asserts on API calls made during actions.
    Hooks into Playwright's response event listener.
    """

    def __init__(self, page: Page):
        self.page             = page
        self._captured:       List[Dict] = []
        self._counter:        int = 0
        self._listening:      bool = False

    def _next_id(self) -> str:
        self._counter += 1
        return f"NET_{self._counter:04d}"

    def start_capture(self):
        """Begin capturing network responses for the next action."""
        self._captured = []
        self._listening = True

        async def on_response(response: Response):
            if self._listening:
                try:
                    url    = response.url
                    status = response.status
                    # Only capture API calls, skip static assets
                    if any(ext in url for ext in ['.js', '.css', '.png', '.jpg', '.ico', '.woff']):
                        return
                    self._captured.append({
                        "url":    url,
                        "status": status,
                        "method": response.request.method,
                    })
                except Exception:
                    pass

        self.page.on("response", on_response)

    def stop_capture(self):
        """Stop capturing network responses."""
        self._listening = False

    async def assert_api_success(
        self,
        expected_methods: List[str] = None
    ) -> AssertionResult:
        """
        Assert that API calls made during the action returned success status codes (2xx).
        """
        start = time.time()
        aid   = self._next_id()

        api_calls = [c for c in self._captured if not any(
            ext in c["url"] for ext in ['.js', '.css', '.png', '.jpg', '.ico']
        )]

        if not api_calls:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.NETWORK,
                name="API Success",
                description="Action should trigger a successful API call",
                status=AssertionStatus.WARNING,
                expected="At least one API call with 2xx response",
                actual="No API calls detected during this action",
                duration_ms=(time.time() - start) * 1000,
            )

        failed_calls = [c for c in api_calls if not (200 <= c["status"] < 300)]

        if failed_calls:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.NETWORK,
                name="API Success",
                description="API call during action returned an error",
                status=AssertionStatus.FAIL,
                expected="All API calls return 2xx",
                actual=f"Failed calls: {[str(c['method']) + ' ' + str(c['url'])[-60:] + ' -> ' + str(c['status']) for c in failed_calls[:3]]}",
                duration_ms=(time.time() - start) * 1000,
                details={"failed_calls": failed_calls},
            )

        return AssertionResult(
            assertion_id=aid, assertion_type=AssertionType.NETWORK,
            name="API Success",
            description="All API calls returned success",
            status=AssertionStatus.PASS,
            expected="All API calls return 2xx",
            actual=f"{len(api_calls)} call(s) succeeded: {[str(c['status']) for c in api_calls[:5]]}",
            duration_ms=(time.time() - start) * 1000,
            details={"calls": api_calls},
        )

    async def assert_no_server_errors(self) -> AssertionResult:
        """Assert no 5xx server errors occurred during the action."""
        start = time.time()
        aid   = self._next_id()
        server_errors = [c for c in self._captured if c["status"] >= 500]

        if server_errors:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.NETWORK,
                name="No Server Errors",
                description="No 5xx server errors should occur",
                status=AssertionStatus.FAIL,
                expected="No 500+ errors",
                actual=f"Server errors: {[str(c['url'])[-60:] + ' -> ' + str(c['status']) for c in server_errors[:3]]}",
                duration_ms=(time.time() - start) * 1000,
                details={"server_errors": server_errors},
            )

        return AssertionResult(
            assertion_id=aid, assertion_type=AssertionType.NETWORK,
            name="No Server Errors",
            description="No server errors occurred",
            status=AssertionStatus.PASS,
            expected="No 500+ errors",
            actual="No server errors detected",
            duration_ms=(time.time() - start) * 1000,
        )

    async def assert_upload_accepted(self) -> AssertionResult:
        """After a file upload, assert the upload API returned success."""
        start = time.time()
        aid   = self._next_id()

        upload_calls = [c for c in self._captured if any(
            kw in c["url"].lower() for kw in ['upload', 'media', 'file', 'image', 'attachment']
        )]

        if not upload_calls:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.NETWORK,
                name="Upload Accepted",
                description="File upload should trigger upload API call",
                status=AssertionStatus.WARNING,
                expected="Upload API call with 2xx response",
                actual="No upload-related API call detected",
                duration_ms=(time.time() - start) * 1000,
            )

        failed = [c for c in upload_calls if not (200 <= c["status"] < 300)]
        if failed:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.NETWORK,
                name="Upload Accepted",
                description="Upload API returned error",
                status=AssertionStatus.FAIL,
                expected="Upload API returns 2xx",
                actual=f"Upload failed: {[str(c['url'])[-60:] + ' -> ' + str(c['status']) for c in failed]}",
                duration_ms=(time.time() - start) * 1000,
            )

        return AssertionResult(
            assertion_id=aid, assertion_type=AssertionType.NETWORK,
            name="Upload Accepted",
            description="File uploaded successfully",
            status=AssertionStatus.PASS,
            expected="Upload API returns 2xx",
            actual=f"Upload call succeeded with status {upload_calls[0]['status']}",
            duration_ms=(time.time() - start) * 1000,
        )


# ─────────────────────────────────────────────────────────────
# Visual Assertion Module
# ─────────────────────────────────────────────────────────────

class VisualAssertions:
    """
    Uses GPT-4 Vision to assert visual correctness of the page.
    Also detects broken images using native browser APIs.
    """

    def __init__(self, page: Page, openai_client: OpenAI, output_dir: Path):
        self.page       = page
        self.openai     = openai_client
        self.output_dir = output_dir
        self._counter   = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"VIS_{self._counter:04d}"

    async def _take_screenshot(self, label: str) -> Optional[str]:
        """Take a screenshot and return the file path."""
        try:
            screenshots_dir = self.output_dir / "screenshots"
            screenshots_dir.mkdir(exist_ok=True)
            ts   = datetime.now().strftime("%H%M%S_%f")
            path = screenshots_dir / f"{label}_{ts}.png"
            await self.page.screenshot(path=str(path), full_page=False)
            return str(path)
        except Exception:
            return None

    async def assert_no_broken_images(self) -> AssertionResult:
        """
        Scan all <img> tags on the page and detect broken ones using
        naturalWidth === 0 (browser-native broken image detection).
        """
        start = time.time()
        aid   = self._next_id()
        try:
            broken = await self.page.evaluate("""
                () => {
                    const imgs = document.querySelectorAll('img');
                    const broken = [];
                    imgs.forEach(img => {
                        const rect = img.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) return; // invisible, skip

                        const isBroken = img.naturalWidth === 0
                            || img.complete === false
                            || img.src === ''
                            || img.src === window.location.href;

                        if (isBroken) {
                            broken.push({
                                src:  img.src?.slice(-80) || '(empty)',
                                alt:  img.alt || '(no alt)',
                                x:    Math.round(rect.x),
                                y:    Math.round(rect.y),
                            });
                        }
                    });
                    return broken;
                }
            """)

            screenshot = await self._take_screenshot("broken_images_check")

            if broken:
                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.VISUAL,
                    name="No Broken Images",
                    description="All images on the page should load correctly",
                    status=AssertionStatus.FAIL,
                    expected="All images load successfully",
                    actual=f"{len(broken)} broken image(s): {[b['alt'] or b['src'] for b in broken[:3]]}",
                    screenshot_path=screenshot,
                    duration_ms=(time.time() - start) * 1000,
                    details={"broken_images": broken},
                )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="No Broken Images",
                description="All images load correctly",
                status=AssertionStatus.PASS,
                expected="All images load successfully",
                actual="No broken images detected",
                screenshot_path=screenshot,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="No Broken Images", description="Broken image scan",
                status=AssertionStatus.FAIL,
                expected="No broken images", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_page_looks_correct(
        self,
        context_description: str = "page after action"
    ) -> AssertionResult:
        """
        Use GPT-4 Vision to check if the page looks visually correct.
        Detects layout breaks, overlapping elements, and UI anomalies.
        """
        start = time.time()
        aid   = self._next_id()
        try:
            screenshot_path = await self._take_screenshot("visual_check")
            if not screenshot_path:
                return AssertionResult(
                    assertion_id=aid, assertion_type=AssertionType.VISUAL,
                    name="Page Visual Check", description=context_description,
                    status=AssertionStatus.WARNING,
                    expected="Page looks visually correct",
                    actual="Could not take screenshot for visual analysis",
                    duration_ms=(time.time() - start) * 1000,
                )

            with open(screenshot_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"You are a visual QA tester. Look at this screenshot of '{context_description}'.\n"
                                "Answer ONLY in this JSON format:\n"
                                '{"looks_correct": true/false, "issues": ["issue1", "issue2"], "summary": "one sentence"}\n'
                                "Check for: broken layouts, overlapping text, missing images (gray boxes), "
                                "error dialogs, blank/white sections that should have content, misaligned elements."
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "low"}
                        }
                    ]
                }]
            )

            raw     = response.choices[0].message.content.strip()
            clean   = raw.replace("```json", "").replace("```", "").strip()
            result  = json.loads(clean)

            looks_correct = result.get("looks_correct", True)
            issues        = result.get("issues", [])
            summary       = result.get("summary", "")

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="Page Visual Check",
                description=context_description,
                status=AssertionStatus.PASS if looks_correct else AssertionStatus.FAIL,
                expected="Page renders correctly without visual defects",
                actual=summary if summary else ("Looks correct" if looks_correct else f"Issues: {issues}"),
                screenshot_path=screenshot_path,
                duration_ms=(time.time() - start) * 1000,
                details={"issues": issues, "gpt_response": result},
            )

        except json.JSONDecodeError:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="Page Visual Check", description=context_description,
                status=AssertionStatus.WARNING,
                expected="Visual check completed",
                actual="GPT Vision response could not be parsed",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="Page Visual Check", description=context_description,
                status=AssertionStatus.WARNING,
                expected="Visual check completed", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )

    async def assert_upload_thumbnail_visible(self) -> AssertionResult:
        """After an upload, assert the thumbnail/preview appeared in the UI."""
        start = time.time()
        aid   = self._next_id()
        try:
            # Look for newly loaded images that appeared after upload
            thumbnail_selectors = [
                'img[src*="blob:"]',
                'img[src*="upload"]',
                'img[src*="media"]',
                '[class*="thumbnail"] img',
                '[class*="preview"] img',
                '.gallery img',
            ]
            for sel in thumbnail_selectors:
                el = self.page.locator(sel).first
                if await el.count() > 0:
                    visible = await el.is_visible()
                    if visible:
                        screenshot = await self._take_screenshot("upload_thumbnail")
                        return AssertionResult(
                            assertion_id=aid, assertion_type=AssertionType.VISUAL,
                            name="Upload Thumbnail Visible",
                            description="Uploaded file should appear as thumbnail in UI",
                            status=AssertionStatus.PASS,
                            expected="Thumbnail appears after upload",
                            actual=f"Thumbnail found via '{sel}'",
                            screenshot_path=screenshot,
                            duration_ms=(time.time() - start) * 1000,
                        )

            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="Upload Thumbnail Visible",
                description="Uploaded file thumbnail check",
                status=AssertionStatus.WARNING,
                expected="Thumbnail appears after upload",
                actual="No thumbnail found — upload may not have reflected in UI yet",
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return AssertionResult(
                assertion_id=aid, assertion_type=AssertionType.VISUAL,
                name="Upload Thumbnail Visible", description="Thumbnail check",
                status=AssertionStatus.FAIL,
                expected="Thumbnail visible", actual=str(e)[:100],
                duration_ms=(time.time() - start) * 1000,
            )


# ─────────────────────────────────────────────────────────────
# Main Assertion Engine — Orchestrates All Three Modules
# ─────────────────────────────────────────────────────────────

class AssertionEngine:
    """
    The main entry point. Plug this into the existing crawler's executor.

    After every action, call assert_after_action() with context about what
    just happened. The engine automatically runs the right assertions.

    Supported action_types:
        "create"      → success message + list update + API success + visual
        "update"      → success message + API success + visual
        "delete"      → success message + list removal + API success
        "upload"      → upload accepted + thumbnail visible + no broken images
        "search"      → results relevant + API success
        "search_empty"→ empty state shown
        "form_invalid"→ error message + form not submitted (negative test)
        "navigate"    → no broken images + visual check
        "toggle"      → toggle state changed
        "radio"       → radio group exclusive
    """

    def __init__(
        self,
        page:          Page,
        openai_client: OpenAI,
        output_dir:    Path,
        logger=None,
    ):
        self.page          = page
        self.output_dir    = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.logger        = logger

        # Sub-modules
        self.dom     = DOMAssertions(page, self.output_dir)
        self.network = NetworkAssertions(page)
        self.visual  = VisualAssertions(page, openai_client, self.output_dir)

        # All reports for the session
        self._all_reports:  List[ActionAssertionReport] = []
        self._action_count: int = 0

    # ── Public API ────────────────────────────────────────────

    def start_network_capture(self):
        """Call this BEFORE an action to capture its network calls."""
        self.network.start_capture()

    def stop_network_capture(self):
        """Call this AFTER an action to stop network capture."""
        self.network.stop_capture()

    async def assert_after_action(
        self,
        action_type:   str,
        context:       Dict = None,
    ) -> ActionAssertionReport:
        """
        Run the right set of assertions for the given action type.

        Args:
            action_type: One of the supported types (see class docstring)
            context:     Dict with optional keys:
                         - item_name:        str  (for list assertions)
                         - search_term:      str  (for search assertions)
                         - toggle_selector:  str  (for toggle assertions)
                         - toggle_expected:  bool (for toggle assertions)
                         - error_keyword:    str  (for negative tests)
                         - page_description: str  (for visual checks)
                         - run_visual:       bool (default True — set False to skip GPT Vision)

        Returns:
            ActionAssertionReport with all assertion results
        """
        self._action_count += 1
        ctx     = context or {}
        report  = ActionAssertionReport(
            action_id   = f"ACT_{self._action_count:04d}",
            action_type = action_type,
            url         = self.page.url,
        )

        await asyncio.sleep(1.5)  # Let UI settle before asserting

        run_visual = ctx.get("run_visual", True)

        # ── Route to correct assertion set ────────────────────
        if action_type == "create":
            report.assertions.append(await self.dom.assert_success_message())
            if ctx.get("item_name"):
                report.assertions.append(await self.dom.assert_list_updated(ctx["item_name"], should_exist=True))
            report.assertions.append(await self.network.assert_api_success())
            report.assertions.append(await self.network.assert_no_server_errors())
            if run_visual:
                report.assertions.append(await self.visual.assert_no_broken_images())

        elif action_type == "update":
            report.assertions.append(await self.dom.assert_success_message())
            report.assertions.append(await self.network.assert_api_success())
            report.assertions.append(await self.network.assert_no_server_errors())

        elif action_type == "delete":
            report.assertions.append(await self.dom.assert_success_message())
            if ctx.get("item_name"):
                report.assertions.append(await self.dom.assert_list_updated(ctx["item_name"], should_exist=False))
            report.assertions.append(await self.network.assert_api_success())

        elif action_type == "upload":
            report.assertions.append(await self.network.assert_upload_accepted())
            report.assertions.append(await self.network.assert_no_server_errors())
            report.assertions.append(await self.dom.assert_success_message())
            if run_visual:
                report.assertions.append(await self.visual.assert_upload_thumbnail_visible())
                report.assertions.append(await self.visual.assert_no_broken_images())

        elif action_type == "search":
            if ctx.get("search_term"):
                report.assertions.append(await self.dom.assert_search_results_relevant(ctx["search_term"]))
            report.assertions.append(await self.network.assert_api_success())
            report.assertions.append(await self.network.assert_no_server_errors())

        elif action_type == "search_empty":
            report.assertions.append(await self.dom.assert_empty_state_shown())

        elif action_type == "form_invalid":
            report.assertions.append(await self.dom.assert_error_message(ctx.get("error_keyword")))
            report.assertions.append(await self.dom.assert_form_not_submitted())

        elif action_type == "navigate":
            if run_visual:
                report.assertions.append(await self.visual.assert_no_broken_images())
                report.assertions.append(await self.visual.assert_page_looks_correct(
                    ctx.get("page_description", f"page at {self.page.url}")
                ))

        elif action_type == "toggle":
            if ctx.get("toggle_selector") is not None and ctx.get("toggle_expected") is not None:
                report.assertions.append(await self.dom.assert_toggle_state_changed(
                    ctx["toggle_selector"], ctx["toggle_expected"]
                ))

        elif action_type == "radio":
            report.assertions.append(await self.dom.assert_radio_group_exclusive())

        else:
            # Generic fallback — run basic checks for unknown action types
            report.assertions.append(await self.network.assert_no_server_errors())
            if run_visual:
                report.assertions.append(await self.visual.assert_no_broken_images())

        # ── Store and log ──────────────────────────────────────
        self._all_reports.append(report)
        self._log_report(report)

        return report

    # ── Session Summary ───────────────────────────────────────

    def get_session_summary(self) -> Dict:
        """Get aggregated results for the entire test session."""
        total   = sum(len(r.assertions) for r in self._all_reports)
        passed  = sum(r.passed  for r in self._all_reports)
        failed  = sum(r.failed  for r in self._all_reports)
        warnings= sum(r.warnings for r in self._all_reports)

        failed_actions = [
            r.to_dict() for r in self._all_reports
            if r.overall_status == AssertionStatus.FAIL
        ]

        return {
            "session_summary": {
                "total_actions_asserted": len(self._all_reports),
                "total_assertions":       total,
                "passed":                 passed,
                "failed":                 failed,
                "warnings":               warnings,
                "pass_rate":              f"{(passed/total*100):.1f}%" if total else "N/A",
            },
            "failed_actions": failed_actions,
            "all_reports":    [r.to_dict() for r in self._all_reports],
        }

    def save_session_report(self, filename: str = "assertion_report.json"):
        """Save the full session report to the output directory."""
        report_path = self.output_dir / filename
        summary     = self.get_session_summary()
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Assertion report saved → {report_path}")
        return str(report_path)

    # ── Internal ──────────────────────────────────────────────

    def _log_report(self, report: ActionAssertionReport):
        """Print a clean summary of the assertion report to console."""
        status_icon = {"PASS": "✅", "FAIL": "❌", "WARNING": "⚠️", "SKIP": "⏭️"}
        icon = status_icon.get(report.overall_status.value, "❓")
        print(f"\n  {icon} Assertions [{report.action_type.upper()}] "
              f"→ {report.passed} passed, {report.failed} failed, {report.warnings} warnings")

        for a in report.assertions:
            a_icon = status_icon.get(a.status.value, "❓")
            if a.status != AssertionStatus.PASS:
                print(f"     {a_icon} [{a.assertion_type.value}] {a.name}: {a.actual}")

        if self.logger:
            try:
                self.logger.log_action("assertion_report", report.to_dict())
            except Exception:
                pass