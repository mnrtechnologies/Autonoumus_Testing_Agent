"""


tousif use thi
Semantic Driver - Production v1.4 [FIXED - Disabled Buttons]
Architecture: Observer → Memory → Decider → Executor (OMDE Loop)

FIXES IN THIS VERSION:
1. ✅ Identifier consistency - same method for loop handler and memory
2. ✅ Loop detection timing - records before checking
3. ✅ LLM context - includes execution history to prevent hallucination
4. ✅ Execution validation - only marks tested if successful
5. ✅ Better custom select handling - stores formcontrolname
6. ✅ Disabled button detection - includes disabled submit buttons in element list
7. ✅ Button enable waiting - waits up to 3s for disabled buttons to become enabled
8. ✅ Submit before cancel - enforces submit/save buttons tested before cancel

Key Features:
1. Focused Testing: Stays on target page, doesn't navigate away
2. Context-aware: Handles modals, forms, tables intelligently
3. Loop Detection: Prevents infinite loops with proper identifier matching
4. Smart Element Detection: Filters navigation links in focused mode
5. Overlay-scoped locators: Controller searches ONLY inside active overlay
6. Angular Material disabled detection: checks aria-disabled, not just .disabled
7. Custom component detection: discovers mat-select, ng-select, v-select,
   ant-select, p-dropdown, react-select and any [role=listbox/combobox] element
8. Custom select executor: clicks to open dropdown, then clicks the option
9. Disabled button handling: detects disabled submit buttons, waits for them to enable
"""
import asyncio
import json
# ADD at the top with other imports:
from widget_handler import WidgetHandler
import base64
import hashlib
from pathlib import Path
from datetime import datetime
import os
from typing import Optional, Dict, List, Any, Tuple, Set
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from knowledge_harvester import KnowledgeHarvester
from enum import Enum
# import anthropic
from element_filter import ElementFilter
from story_aware_decider import StoryAwareDecider, build_story_tester
from test_story_engine   import TestStoryTracker, ReportGenerator

from playwright.async_api import async_playwright, Page, Locator, FrameLocator
from openai import OpenAI
from page_state_extractor import PageStateExtractor, diff_states
from dotenv import load_dotenv
import os

load_dotenv()
# ═══════════════════════════════════════════════════════════════
#  CORE DATA MODELS
# ═══════════════════════════════════════════════════════════════

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
                    for a in ['click', 'fill', 'select', 'check','upload']
                )
                if not any_tested:
                    untested.append(elem)
        return untested

    def _get_identifier(self, element: Dict) -> str:
        is_in_overlay = element.get('in_overlay', False)
        context_prefix = 'overlay:' if is_in_overlay else 'page:'

        # ✅ File first (after prefix is defined)
        if element.get('element_type') == 'file':
            formcontrol = element.get('formcontrolname', '')
            if formcontrol:
                return f"{context_prefix}file:{formcontrol}"
            return f"{context_prefix}file:{element.get('id') or element.get('name') or element.get('text')}"

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

# ═══════════════════════════════════════════════════════════════
#  SCOPE MANAGER
# ═══════════════════════════════════════════════════════════════

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

        # if tag == 'button' and any(x in text.lower() for x in ['calendar', 'open calendar', 'datepicker']):
        #     return False, "Calendar icon — date filled directly"
        return True, "In scope"


# ═══════════════════════════════════════════════════════════════
#  CONTEXT STACK
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  LOOP DETECTOR
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  OBSERVER - Extracts interactive elements
# ═══════════════════════════════════════════════════════════════

class Observer:

    OVERLAY_SELECTORS = [
        'mat-dialog-container',
        '[role="dialog"][aria-modal="true"]',
        '[role="alertdialog"]',
        '.modal.show',
        '.modal.active',
        '.dialog.open',
        '.popup.visible',
        '.dropdown-menu.show',
    ]

    @staticmethod
    async def get_elements(page: Page) -> Dict[str, Any]:
        """
        Extract truly interactive elements.
        Returns overlay_selector — the CSS selector of whichever overlay is active.
        """
        await page.evaluate("""
            async () => {
                window.scrollTo(0, document.body.scrollHeight);
                await new Promise(r => setTimeout(r, 500));
                window.scrollTo(0, 0);
                await new Promise(r => setTimeout(r, 500));
            }
        """)

        overlay_selectors_json = json.dumps(Observer.OVERLAY_SELECTORS)

        result = await page.evaluate(f"""() => {{
            const overlaySelectors = {overlay_selectors_json};
            const interactive = [];

            const strictSelectors = {{
                buttons:   'button',
                links:     'a[href]',
                inputs:    'input:not([type="hidden"])',
                selects:   'select',
                textareas: 'textarea',
            }};

            // ── Overlay detection ────────────────────────────────────────────
            let activeOverlay = null;
            let activeOverlaySelector = null;
            let maxZIndex = -1;

            for (const sel of overlaySelectors) {{
                document.querySelectorAll(sel).forEach(overlay => {{
                    const rect = overlay.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;

                    const style = window.getComputedStyle(overlay);
                    if (style.display === 'none' || style.visibility === 'hidden') return;

                    const zIndex = parseInt(style.zIndex) || 0;
                    if (zIndex > maxZIndex || !activeOverlay) {{
                        maxZIndex = zIndex;
                        activeOverlay = overlay;
                        activeOverlaySelector = sel;
                    }}
                }});
            }}

            // ── Helper: is element truly interactive? ────────────────────────
            function isTrulyInteractive(el) {{
                const rect = el.getBoundingClientRect();
                const tag = el.tagName.toLowerCase();
                const type = el.type || '';

                // ✅ ALWAYS allow file inputs (even if hidden / 0x0)
                if (tag === 'input' && type === 'file') {{
                    return true;
                }}

                if (rect.width === 0 || rect.height === 0) return false;

                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                if (style.opacity === '0') return false;

                if ((tag === 'input' || tag === 'textarea') &&
                    type !== 'checkbox' &&
                    type !== 'radio' &&
                    el.readOnly) return false;

                return true;
            }}
            // ── Helper: is element disabled? ─────────────────────────────────
            function isDisabled(el) {{
                if (el.disabled) return true;
                if (el.getAttribute('aria-disabled') === 'true') return true;
                if (el.hasAttribute('disabledinteractive') && el.classList.contains('mat-mdc-button-disabled-interactive')) return true;
                return false;
            }}

            const seen = new Set();

            // ── Collect buttons ───────────────────────────────────────────────
            document.querySelectorAll(strictSelectors.buttons).forEach(el => {{
                if (!isTrulyInteractive(el)) return;

                const rect = el.getBoundingClientRect();
                const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                const isBlocked   = activeOverlay && !isInOverlay;
                const disabled    = isDisabled(el);

                const _clone = el.cloneNode(true);
                _clone.querySelectorAll('mat-icon, .material-icons, svg, i.fa').forEach(function(n) {{ n.remove(); }});

                // Text after stripping icons (handles "Atur Suhu" correctly)
                const strippedText = (
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    _clone.innerText ||
                    _clone.textContent || ''
                ).trim().replace(/\s+/g, ' ').slice(0, 150);

                // ONLY use icon name as fallback if button has NO text at all
                // This catches more_vert, edit, delete icon-only buttons
                const iconFallback = strippedText ? '' : (
                    Array.from(el.querySelectorAll('mat-icon, .material-icons'))
                        .map(i => i.textContent.trim())
                        .filter(Boolean)
                        .join(' ')
                );

                const text = strippedText || iconFallback;
                if (!text) return;

                const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                const key = `${{contextPrefix}}button:${{text}}:${{el.id}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: 'button', type: el.type || 'button',
                    role: el.getAttribute('role') || 'button',
                    text, id: el.id || '', name: el.getAttribute('name') || '',
                    classes: Array.from(el.classList).slice(0, 5),
                    href: '', required: false, enabled: !disabled,
                    blocked: isBlocked, in_overlay: isInOverlay,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    element_type: 'button'
                }});
            }});

            // ── Collect links ─────────────────────────────────────────────────
            document.querySelectorAll(strictSelectors.links).forEach(el => {{
                if (!isTrulyInteractive(el)) return;

                const rect = el.getBoundingClientRect();
                const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                const isBlocked   = activeOverlay && !isInOverlay;

                const text = (
                    el.innerText || el.textContent ||
                    el.getAttribute('aria-label') || ''
                ).trim().slice(0, 150);

                const href = el.getAttribute('href') || '';
                const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                const key  = `${{contextPrefix}}link:${{text}}:${{href}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: 'a', type: '', role: 'link',
                    text, id: el.id || '', name: '',
                    classes: Array.from(el.classList).slice(0, 5),
                    href, required: false, enabled: true,
                    blocked: isBlocked, in_overlay: isInOverlay,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    element_type: 'link'
                }});
            }});

        // ── Collect inputs ────────────────────────────────────────────────
        document.querySelectorAll(strictSelectors.inputs).forEach(el => {{
            if (!isTrulyInteractive(el)) return;

            const rect = el.getBoundingClientRect();
            const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
            const isBlocked   = activeOverlay && !isInOverlay;

            const type             = (el.type || '').toLowerCase();
            const placeholder      = el.placeholder || '';
            const ariaLabel        = el.getAttribute('aria-label') || '';
            const nameAttr         = el.getAttribute('name') || '';
            const formControlName  = el.getAttribute('formcontrolname') || '';
            const id               = el.id || '';

            let label = placeholder || ariaLabel || formControlName || nameAttr;

            if (!label && id) {{
                const labelEl = document.querySelector(`label[for="${{id}}"]`);
                if (labelEl) label = labelEl.innerText.trim();
            }}

            if (!label) label = `${{type || 'text'}} input`;

            const contextPrefix = isInOverlay ? 'overlay:' : 'page:';

            // 🔥 FILE INPUT HANDLING
            if (type === 'file') {{

                const key = `${{contextPrefix}}file:${{label}}:${{id}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: 'input',
                    type: 'file',
                    role: 'button',
                    text: label || 'file-upload',
                    id,
                    name: nameAttr,
                    classes: Array.from(el.classList).slice(0, 5),
                    href: '',
                    required: el.hasAttribute('required'),
                    enabled: true,
                    blocked: isBlocked,
                    in_overlay: isInOverlay,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    element_type: 'file',
                    placeholder: '',
                    formcontrolname: formControlName
                }});

                return;
            }}

            const key = `${{contextPrefix}}input:${{type}}:${{label}}:${{id}}`;
            if (seen.has(key)) return;
            seen.add(key);

            interactive.push({{
                tag: 'input',
                type: type || 'text',
                role: 'textbox',
                text: label,
                id,
                name: nameAttr,
                classes: Array.from(el.classList).slice(0, 5),
                href: '',
                required: el.hasAttribute('required'),
                enabled: true,
                blocked: isBlocked,
                in_overlay: isInOverlay,
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                element_type: 'input',
                placeholder,
                formcontrolname: formControlName
            }});
        }});
            // ── Collect selects ───────────────────────────────────────────────
            document.querySelectorAll(strictSelectors.selects).forEach(el => {{
                if (!isTrulyInteractive(el)) return;

                const rect = el.getBoundingClientRect();
                const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                const isBlocked   = activeOverlay && !isInOverlay;

                const label = el.getAttribute('aria-label') || el.getAttribute('name') || 'Select';
                const formControlName = el.getAttribute('formcontrolname') || '';
                const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                const key   = `${{contextPrefix}}select:${{label}}:${{el.id}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: 'select', type: '', role: 'combobox',
                    text: label, id: el.id || '', name: el.getAttribute('name') || '',
                    classes: Array.from(el.classList).slice(0, 5),
                    href: '', required: el.hasAttribute('required'),
                    enabled: true, blocked: isBlocked, in_overlay: isInOverlay,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    element_type: 'select',
                    formcontrolname: formControlName
                }});
            }});

            // ── Collect textareas ─────────────────────────────────────────────
            document.querySelectorAll(strictSelectors.textareas).forEach(el => {{
                if (!isTrulyInteractive(el)) return;

                const rect = el.getBoundingClientRect();
                const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                const isBlocked   = activeOverlay && !isInOverlay;

                const placeholder     = el.placeholder || '';
                const ariaLabel       = el.getAttribute('aria-label') || '';
                const nameAttr        = el.getAttribute('name') || '';
                const formControlName = el.getAttribute('formcontrolname') || '';
                const id              = el.id || '';

                let label = placeholder || ariaLabel || formControlName || nameAttr;
                if (!label && id) {{
                    const labelEl = document.querySelector(`label[for="${{id}}"]`);
                    if (labelEl) label = labelEl.innerText.trim();
                }}
                if (!label) label = 'textarea';

                const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                const key = `${{contextPrefix}}textarea:${{label}}:${{id}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: 'textarea', type: '', role: 'textbox',
                    text: label, id, name: nameAttr,
                    classes: Array.from(el.classList).slice(0, 5),
                    href: '', required: el.hasAttribute('required'),
                    enabled: true, blocked: isBlocked, in_overlay: isInOverlay,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    element_type: 'textarea',
                    placeholder, formcontrolname: formControlName
                }});
            }});

            // ── Collect ARIA interactive elements (tabs, custom buttons) ──────
            const ariaSelectors = [
    '[role="tab"]',
    '[role="button"]:not(button)',
    '[role="menuitem"]:not(button):not(a)',
    '[tabindex="0"]:not(button):not(a):not(input):not(select):not(textarea)',
];
            ariaSelectors.forEach(sel => {{
                document.querySelectorAll(sel).forEach(el => {{
                    if (!isTrulyInteractive(el)) return;

                    const rect = el.getBoundingClientRect();
                    const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                    const isBlocked   = activeOverlay && !isInOverlay;

                    const text = (
                        el.getAttribute('aria-label') ||
                        el.getAttribute('title') ||
                        el.innerText ||
                        el.textContent || ''
                    ).trim().replace(/\s+/g, ' ').slice(0, 150);

                    if (!text) return;

                    const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                    const key = `${{contextPrefix}}aria:${{text}}:${{el.id}}`;
                    if (seen.has(key)) return;
                    seen.add(key);

                    interactive.push({{
                        tag: el.tagName.toLowerCase(),
                        type: el.getAttribute('role') || 'button',
                        role: el.getAttribute('role') || 'button',
                        text, id: el.id || '', name: el.getAttribute('name') || '',
                        classes: Array.from(el.classList).slice(0, 5),
                        href: el.getAttribute('href') || '',
                        required: false, enabled: !isDisabled(el),
                        blocked: isBlocked, in_overlay: isInOverlay,
                        x: Math.round(rect.x), y: Math.round(rect.y),
                        element_type: el.getAttribute('role') || 'button'
                    }});
                }});
            }});


            // ── Collect clickable divs/spans (JS handlers) ───────────────
            document.querySelectorAll('div, span').forEach(el => {{
                if (!isTrulyInteractive(el)) return;

                const rect = el.getBoundingClientRect();
                const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                const isBlocked   = activeOverlay && !isInOverlay;

                const hasClickHandler =
                    el.onclick ||
                    el.getAttribute('onclick') ||
                    el.getAttribute('role') === 'button' ||
                    el.classList.contains('cursor-pointer');

                if (!hasClickHandler) return;

                const text = (
                    el.innerText ||
                    el.getAttribute('aria-label') ||
                    ''
                ).trim().replace(/\s+/g, ' ').slice(0,150);

                if (!text) return;

                const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                const key = `${{contextPrefix}}divbutton:${{text}}:${{el.id}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: el.tagName.toLowerCase(),
                    type: 'button',
                    role: 'button',
                    text,
                    id: el.id || '',
                    name: '',
                    classes: Array.from(el.classList).slice(0,5),
                    href: '',
                    required: false,
                    enabled: true,
                    blocked: isBlocked,
                    in_overlay: isInOverlay,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    element_type: 'button'
                }});
            }});
            // ── Collect CUSTOM SELECT components ──────────────────────────────
            const customSelectSelectors = [
    'mat-form-field [role="combobox"]:not(input):not(select)',
    'mat-form-field [role="listbox"]:not(select)',
    'mat-form-field mat-select',
    'p-dropdown .p-dropdown',
    'p-multiselect .p-multiselect',
    '.ant-select-selector',
    'ng-select',
    '.vs__dropdown-toggle',
    '.react-select__control',
    '.v-select__slot',
];

            function getCustomLabel(el) {{
                let label = el.getAttribute('aria-label') || '';
                if (label) return label;

                label = el.getAttribute('formcontrolname') || '';
                if (label) return label;

                const labelledBy = el.getAttribute('aria-labelledby') || '';
                if (labelledBy) {{
                    const lbl = document.getElementById(labelledBy);
                    if (lbl) return lbl.innerText.trim();
                }}

                let node = el.parentElement;
                for (let i = 0; i < 4 && node; i++) {{
                    const lbl = node.querySelector('label');
                    if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
                    const matLabel = node.querySelector('mat-label');
                    if (matLabel && matLabel.innerText.trim()) return matLabel.innerText.trim();
                    node = node.parentElement;
                }}

                const placeholder = el.querySelector(
                    '.mat-mdc-select-placeholder, .p-placeholder, ' +
                    '.ant-select-selection-placeholder, .vs__placeholder, ' +
                    '[class*="placeholder"]'
                );
                if (placeholder && placeholder.innerText.trim())
                    return placeholder.innerText.trim();

                label = el.getAttribute('name') || '';
                if (label) return label;

                label = el.id || '';
                if (label) return label;

                return 'custom-select';
            }}

            function isCustomSelectDisabled(el) {{
                if (el.getAttribute('aria-disabled') === 'true') return true;
                if (el.hasAttribute('disabled')) return true;
                if (el.classList.contains('mat-mdc-select-disabled')) return true;
                if (el.classList.contains('mat-select-disabled')) return true;
                if (el.classList.contains('p-disabled')) return true;
                if (el.classList.contains('ant-select-disabled')) return true;
                return false;
            }}

            const seenCustom = new Set();
            const seenFormControls = new Set();  // Track formcontrolnames separately

            customSelectSelectors.forEach(sel => {{
                let elements;
                try {{ elements = document.querySelectorAll(sel); }}
                catch(e) {{ return; }}

                elements.forEach(el => {{
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;
                    if (el.closest('mat-paginator')) return;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return;
                    if (style.opacity === '0') return;

                    if (isCustomSelectDisabled(el)) return;

                    const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                    const isBlocked   = activeOverlay && !isInOverlay;

                    const label          = getCustomLabel(el);
                    const formcontrol    = el.getAttribute('formcontrolname') || '';
                    const id             = el.id || '';
                    const required       = el.hasAttribute('required') ||
                                        el.getAttribute('aria-required') === 'true';

                    const contextPrefix = isInOverlay ? 'overlay:' : 'page:';

                    // FIX: Prioritize formcontrolname for deduplication
                    // If element has formcontrolname, that's the primary key
                    let dedupKey;
                    if (formcontrol) {{
                        dedupKey = `${{contextPrefix}}formcontrol:${{formcontrol}}`;
                        // Also track formcontrolname separately
                        if (seenFormControls.has(formcontrol)) return;
                        seenFormControls.add(formcontrol);
                    }} else {{
                        dedupKey = `${{contextPrefix}}customselect:${{id || label}}`;
                    }}

                    if (seenCustom.has(dedupKey)) return;
                    seenCustom.add(dedupKey);

                    // Skip if native <select> with same formcontrolname already collected
                    if (formcontrol && seen.has(`${{contextPrefix}}select::${{formcontrol}}`)) return;

                    const nativeKey = `${{contextPrefix}}select::${{label}}:${{id}}`;
                    if (seen.has(nativeKey)) return;

                    interactive.push({{
                        tag: el.tagName.toLowerCase(),
                        type: 'custom-select',
                        role: el.getAttribute('role') || 'combobox',
                        text: label,
                        id,
                        name: el.getAttribute('name') || '',
                        classes: Array.from(el.classList).slice(0, 5),
                        href: '',
                        required,
                        enabled: true,
                        blocked: isBlocked,
                        in_overlay: isInOverlay,
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        element_type: 'custom-select',
                        placeholder: '',
                        formcontrolname: formcontrol
                    }});
                }});
            }});

            // ── Overlay type ──────────────────────────────────────────────────
            let overlayType = null;
            let widgetType = null;
            if (activeOverlay) {{
                const isCalendar = activeOverlay.querySelector(
                    'mat-calendar, [class*="mat-calendar"], [class*="datepicker-calendar"]'
                );
                if (isCalendar) {{
                    overlayType = 'widget';
                    widgetType  = 'calendar';
                }} else {{

                    const txt = activeOverlay.innerText.toLowerCase();
                    if (txt.includes('confirm') || txt.includes('yakin') || txt.includes('are you sure'))
                        overlayType = 'confirmation';
                    else if (activeOverlay.querySelector(
                        'input, select, textarea, mat-select, ng-select, ' +
                        '[role="combobox"], [formcontrolname]'
                    ))
                        overlayType = 'form';
                    else
                        overlayType = 'info';
                }}

                }}

            return {{
                has_overlay:       !!activeOverlay,
                overlay_type:      overlayType,
                widget_type:       widgetType,
                overlay_selector:  activeOverlaySelector,
                active_elements:   interactive.filter(e => !e.blocked),
                blocked_elements:  interactive.filter(e => e.blocked),
                total_discovered:  interactive.length
            }};
        }}""")


        return result

    @staticmethod
    async def detect_context(page: Page, elements_data: Dict) -> ContextType:
        if elements_data.get('has_overlay'):
            overlay_type = elements_data.get('overlay_type')
            if overlay_type == 'confirmation':
                return ContextType.CONFIRMATION
            elif overlay_type == 'form':
                return ContextType.FORM
            else:
                return ContextType.MODAL

        active = elements_data.get('active_elements', [])
        has_inputs = any(
            e.get('tag') in ('input', 'textarea', 'select') or
            e.get('element_type') == 'custom-select'
            for e in active
        )
        has_submit = any(
            any(kw in e.get('text', '').lower() for kw in
                ['submit', 'save', 'simpan', 'tambah', 'perbarui', 'update'])
            for e in active
        )
        if has_inputs and has_submit:
            return ContextType.FORM

        has_table = await page.evaluate(
            "() => document.querySelectorAll('table, .table, [role=grid]').length > 0"
        )
        if has_table:
            return ContextType.TABLE

        return ContextType.PAGE


# ═══════════════════════════════════════════════════════════════
#  DECIDER
# ═══════════════════════════════════════════════════════════════

class Decider:

    def __init__(self, openai_client: OpenAI, tester_ref=None):
        self.openai = openai_client
        self.tester = tester_ref  # Reference to SemanticTester for history access

    async def decide(
        self,
        screenshot_b64: str,
        context_frame: ContextFrame,
        elements: List[Dict]
    ) -> Dict:
        if not elements:
            return {"action": "done", "reasoning": "All elements tested"}

        prompt = self._build_prompt(context_frame.context_type, elements)

        try:
            diff_summary = self._summarise_state_diffs()
            print(f"\n🔍 STATE DIFF SUMMARY BEING SENT TO GPT:\n{diff_summary}\n")
            response = self.openai.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                    ]
                }],
                max_tokens=1500,
                temperature=0.2
            )
            raw = response.choices[0].message.content
            # response = self.openai.messages.create(
            #     model="claude-sonnet-4-20250514",
            #     max_tokens=1500,
            #     messages=[{
            #         "role": "user",
            #         "content": [
            #             {"type": "image", "source": {
            #                 "type": "base64",
            #                 "media_type": "image/png",
            #                 "data": screenshot_b64
            #             }},
            #             {"type": "text", "text": prompt}
            #         ]
            #     }]
            # )
            # raw = response.content[0].text
            print(f"  🤖 Decision raw response:\n{raw}\n")
            return json.loads(self._extract_json(raw))

        except Exception as e:
            print(f"  ⚠️  Decision failed: {e}")
            if elements:
                elem = elements[0]
                return {
                    "action": "click",
                    "target_name": elem.get('text', 'element'),
                    "element_type": elem.get('tag', 'button'),
                    "reasoning": "Fallback"
                }
            return {"action": "wait"}

    def _build_prompt(self, context_type: ContextType, elements: List[Dict]) -> str:

        # FIX 3: Add recent history context to prevent LLM hallucination
        recent_history = []
        if self.tester and hasattr(self.tester, 'history'):
            recent_history = self.tester.history[-5:]

        history_summary = ""
        if recent_history:
            history_summary = "\n\nRECENT ACTIONS (last 5 steps):\n"
            for h in recent_history:
                action = h.get('decision', {}).get('action', '')
                target = h.get('decision', {}).get('target_name', '')
                success = h.get('result', {}).get('success', False)
                status = "✓" if success else "✗"
                history_summary += f"  {status} {action} → {target}\n"
            history_summary += "\nDO NOT repeat these exact actions unless the element appears in UNTESTED list.\n"

        prompt = f"""You are a QA engineer creating a realistic user test story for a web form.
CONTEXT: {context_type.value}
{history_summary}

UNTESTED ELEMENTS ({len(elements)} remaining):
{json.dumps(elements[:15], indent=2)}

STRICT RULES — follow in this exact order:

MOST IMPORTANT RULE — READ THE SCREENSHOT CAREFULLY:
- The screenshot shows the CURRENT STATE of the page
- If you can see ANY table rows with data, you MUST use those exact values
- Look at every row in the table visible in the screenshot
- Use the FIRST ROW's actual data for search fields:
  * If you see a name like "Ramlaxman" in the table → use "Ramlaxman" for fullName field
  * If you see a role like "Super Admin" → use "Super Admin" for roleName field
  * If you see an email → use that exact email for emailId field
- If NO table data is visible yet, leave search fields EMPTY string ""
  so the search returns ALL results
- NEVER invent names, emails, or phone numbers that aren't visible on screen
- NEVER use "Ahmad Subekti", "Agus Santoso" or any made-up Indonesian names

- FOR SEARCH/FILTER FIELDS (fullName, emailId, phoneNumber, roleName, userStatus):
  Use ONLY values visible in the screenshot table. If not visible, use "" (empty string)
1. FILL / SELECT BEFORE TRIGGER (CRITICAL)
   - If the list contains BOTH input/select fields AND a submit/save button
     (Cari, Search, Filter, Simpan, Tambah, Perbarui, Save, Submit, TAMBAH),
     fill/select ALL fields first before clicking the button.
   - Never click search/filter when input fields are still untested.
   - Never click submit/save when any input or select is still untested.
   - If submit button shows enabled:false, fill all fields first - it will become enabled.

2. CORRECT ACTION PER ELEMENT TYPE (CRITICAL - Follow element_type from list above)
   - element_type "input" or "textarea"  → action = "fill"
   - element_type "file" → action = "upload"
   - element_type "select"               → action = "select", test_value = a valid option
   - element_type "custom-select"        → action = "select", test_value = a valid option
     (custom-select = Angular mat-select, ng-select, PrimeNG, Ant Design, Vue-select,
      React-select — NEVER use "fill" for these, always "select")
   - element_type "button"               → action = "click"
   - element_type "link"                 → action = "click"
   - element_type "checkbox" or "radio"  → action = "check"

3. REALISTIC VALUES (use appropriate value based on field name/placeholder):
   For INPUT fields (action="fill"):
   - phone/HP/contact: 08123456789
   - email: test@example.com
   - name/nama: Test Name
   - address/alamat: 123 Test Street
   - description: This is a test description
   - code/kode: 001
   - number/angka: 100
   - postal/zip: 12345
   - swift: TESTBANK1
   - npwp/tax: 123456789012345
   - bankType/tipe rekening: Savings
   - accountType: Business
       FOR DATE/TIME FIELDS - CRITICAL:
            - If field is named 'eventDate', 'date', 'datetime', or has calendar icon in screenshot
            - ALWAYS include BOTH date AND time in format: DD/MM/YYYY, HH:MM
            - Example: "19/02/2026, 17:25"
            - NEVER use date-only format like "16/02/2026"

   For SELECT/CUSTOM-SELECT fields (action="select"):
   - Look at screenshot for exact dropdown options first
   - If not visible, use sensible defaults:
     * status → "Active"
     * category/kategori → "General"
     * gender/jenis kelamin → "Male"
     * accountType → "Savings"
     * isPrimaryAccount → "Yes"

4. SUBMIT BEFORE CANCEL (CRITICAL IN FORMS)
   - In forms/modals, ALWAYS test submit/save buttons BEFORE cancel/back buttons
   - Common submit button text: Simpan, Save, Submit, Tambah, TAMBAH, Perbarui, Update
   - Common cancel button text: Batal, Cancel, Tutup, Close
   - If submit button is disabled (enabled:false), fill all fields first
   - Only click cancel if there is NO submit button in the element list

5. EXACT TARGET NAMES
   target_name = EXACT text or formcontrolname from the list. No asterisks, no quotes.

6. SKIP DISABLED BUTTONS (unless they're submit buttons that will enable after filling fields)
   - Skip buttons with enabled:false UNLESS they are submit/save buttons
   - Submit buttons often start disabled and enable after form is valid

7. ONLY choose from UNTESTED ELEMENTS list above - do not hallucinate elements.

"""

        if context_type == ContextType.CONFIRMATION:
            prompt += "CURRENT CONTEXT: Confirmation — click confirm/yes unless data loss risk, then cancel.\n"
        elif context_type == ContextType.FORM:
            prompt += "CURRENT CONTEXT: Form — fill/select ALL fields before clicking submit. Required fields first.\n"
        elif context_type == ContextType.MODAL:
            prompt += "CURRENT CONTEXT: Modal — test all elements inside before closing.\n"
        elif context_type == ContextType.TABLE:
            prompt += "CURRENT CONTEXT: Table — fill search inputs first, click search, then row actions, then create.\n"
        else:
            prompt += "CURRENT CONTEXT: Page — fill/select fields before clicking their trigger buttons.\n"

        prompt += """
Return ONLY valid JSON, no markdown:
{
  "action": "click|fill|select|check|upload",
  "target_name": "exact text or formcontrolname from the list",
  "element_type": "button|input|link|select|textarea|custom-select",
  "test_value": "value if filling/selecting, empty string for clicks",
  "reasoning": "one sentence"
}"""
        return prompt

    def _extract_json(self, text: str) -> str:
        if "```json" in text:
            start = text.find("```json") + 7
            end   = text.find("```", start)
            return text[start:end].strip()
        if "```" in text:
            start = text.find("```") + 3
            end   = text.find("```", start)
            return text[start:end].strip()
        return text.strip()


# ═══════════════════════════════════════════════════════════════
#  CONTROLLER
# ═══════════════════════════════════════════════════════════════

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

        if elem_type == 'file':
            loc = root.locator('input[type="file"]')
            if await loc.count() > 0:
                print("    ✓ Found file input")
                return loc.first, "file"

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
            'button': ['button', 'div', 'span'],
            'link': ['a'],
            'input': ['input'],
            'select': ['select'],
            'textarea': ['textarea']
        }

        tags = tag_map.get(elem_type, ['button', 'div'])

        try:
            loc = root.get_by_text(text, exact=True)
            if await loc.count() > 0:
                print("    ✓ Found by get_by_text")
                return loc.first
        except Exception:
            pass

        return None

        # try:
        #     for tag in tags:
        #         loc = root.locator(tag).filter(has_text=text)
        #         if await loc.count() > 0:
        #             print(f"    ✓ Found by text in <{tag}>")
        #             return loc.first
        # except Exception:
        #     pass

        # return None

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


# ═══════════════════════════════════════════════════════════════
#  EXECUTOR
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  EXECUTOR - FIXED VERSION
# ═══════════════════════════════════════════════════════════════

class Executor:

    def __init__(self, page: Page):
        self.page = page

    async def execute(
        self,
        locator: Locator,
        action: str,
        value: Optional[str] = None,
        elem_type: str = ''
    ) -> Dict:
        result = {"success": False, "action": action, "error": None}

        try:
            if action == "upload":
                # Only need it attached
                await locator.wait_for(state="attached", timeout=5000)

                upload_dir = Path("test_upload_files")
                upload_dir.mkdir(exist_ok=True)

                test_file = upload_dir / "test_image.png"

                if not test_file.exists():
                    from PIL import Image
                    img = Image.new("RGB", (300, 300), color=(120, 150, 200))
                    img.save(test_file)

                await locator.set_input_files(str(test_file), timeout=10000)
                print(f"    ✓ Uploaded file: {test_file}")
            else:
            
                await locator.wait_for(state="visible", timeout=3000)

                if action == "click":
                    # Check if button is disabled
                    is_disabled = await locator.evaluate("""
                        el => el.disabled ||
                            el.getAttribute('aria-disabled') === 'true' ||
                            el.classList.contains('mat-mdc-button-disabled')
                    """)

                    if is_disabled:
                        print(f"    ⏳ Button is disabled, waiting for it to enable...")
                        # Wait up to 3 seconds for button to become enabled
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
                            print(f"    ⚠️  Button still disabled after 3s - skipping")
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


# ═══════════════════════════════════════════════════════════════
#  MAIN TESTER
# ═══════════════════════════════════════════════════════════════

class SemanticTester:

    def __init__(self, openai_api_key: str, auth_file: str = "auth.json"):
        self.openai = OpenAI(api_key=openai_api_key)
        # self.anthropic = anthropic.Anthropic(api_key=openai_api_key)

        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path('semantic_test_output')
        self.output_dir.mkdir(exist_ok=True)

        self.observer      = Observer()
        self.context_stack = ContextStack()
        self.loop_detector = LoopDetector()
        self.global_memory = GlobalMemory()
        self.element_filter = ElementFilter(self.openai)
        self.harvester = KnowledgeHarvester(
            output_dir=self.output_dir,
            session_id=self.session_id,
            openai_client=self.openai
        )
        self.state_extractor = PageStateExtractor(self.openai)
        self.scope:      Optional[ScopeManager] = None
        self.decider:    Optional[Decider]      = None
        self.controller: Optional[Controller]   = None
        self.executor:   Optional[Executor]     = None
    #     self.harvester = KnowledgeHarvester(
    #     output_dir=self.output_dir,
    #     session_id=self.session_id,
    #     openai_client=self.openai
    # )
        self.history: List[Dict] = []
        self.step = 0
        self.story_tracker, self.report_gen, self.story_gen = build_story_tester(self.openai, self.output_dir, self.session_id)

        print(f"\n{'='*80}")
        print("🧠 SEMANTIC DRIVER - Production v1.4 [FIXED]")
        print(f"{'='*80}")
        print(f"Session: {self.session_id}\n")

    async def _full_screenshot(self, page: Page, name: str) -> str:
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            # Scroll to bottom first so table data loads
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            # Take full page screenshot
            await page.screenshot(path=path, full_page=True)
            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return ""

    async def run(self, target_url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1400, 'height': 900})
            page    = await context.new_page()

            self.scope      = ScopeManager(target_url)
            # self.decider    = Decider(self.openai, tester_ref=self)
            #  # Pass self reference
            self.decider = StoryAwareDecider(self.openai, tester_ref=self, story_tracker=self.story_tracker)
            self.controller = Controller(page)
            self.executor   = Executor(page)

            try:
                print("[1/3] 🔑 Authenticating...")
                await self._inject_auth(page, context, target_url)

                print(f"[2/3] 🌐 Navigating to target...")
                await page.goto(target_url, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)

                dom_hash = await self._dom_hash(page)
                initial  = ContextFrame(
                    context_type=ContextType.PAGE,
                    description="Target page",
                    timestamp=datetime.now().isoformat(),
                    url=page.url,
                    dom_hash=dom_hash,
                    overlay_selector=None
                )
                self.context_stack.push(initial)

                print(f"[3/3] 🚀 Starting testing loop...\n")
                await self._test_loop(page)

            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()

            finally:
                # self._save_results()
                await self._save_results()
                if getattr(self, '_interactive', True):
                    input("\n👁️  Press Enter to close...")
                await browser.close()

    def _validate_decision(self, decision: Dict, untested: List[Dict]) -> Dict:
        """Enforce that LLM can only pick from the untested list. No hallucination allowed."""
        target = decision.get('target_name', '').strip()

        # Special handling for file inputs
        # --- Special handling for file inputs ---
        for elem in untested:
            if elem.get('element_type') == 'file':
                if (
                    target == elem.get('formcontrolname', '').strip() or
                    target == elem.get('text', '').strip() or
                    target == elem.get('id', '').strip()
                ):
                    print("  🔧 Normalizing file interaction → upload")

                    # Force correct action for file input
                    decision['action'] = 'upload'
                    decision['element_type'] = 'file'
                    decision['test_value'] = ''   # Ignore GPT file path

                    return decision

        # Check if decision target exists in untested list
        for elem in untested:
            if (elem.get('formcontrolname', '').strip() == target or
                elem.get('text', '').strip() == target or
                elem.get('name', '').strip() == target):
                return decision  # ✅ Valid choice
            # Partial match
            elem_text = elem.get('text', '').strip()
            if elem_text and (target in elem_text or elem_text in target):
                return decision

        # ❌ LLM hallucinated — override with best choice from untested
        print(f"  🚨 VALIDATION OVERRIDE: '{target}' not in untested list!")
        print(f"     Available: {[e.get('formcontrolname') or e.get('text') for e in untested]}")

        # Priority 1: inputs/selects/textareas (fill before submit)
        for elem in untested:
            if elem.get('element_type') in ['file', 'input', 'textarea', 'select', 'custom-select', 'combobox']:
                return self._elem_to_decision(elem)

        # Priority 2: non-cancel buttons
        cancel_keywords = ['batal', 'cancel', 'tutup', 'close', 'kembali', 'back']
        for elem in untested:
            text = (elem.get('text') or '').lower()
            if elem.get('element_type') == 'button' and not any(k in text for k in cancel_keywords):
                return self._elem_to_decision(elem)

        # Priority 3: anything remaining
        return self._elem_to_decision(untested[0])

    def _elem_to_decision(self, elem: Dict) -> Dict:
        """Convert an element dict into a decision dict."""
        elem_type = elem.get('element_type', 'button')
        action_map = {
            'input': 'fill',
            'textarea': 'fill',
            'file': 'upload',
            'select': 'select',
            'custom-select': 'select',
            'button': 'click',
            'link': 'click',
            'checkbox': 'check',
            'radio': 'check'
        }
        target = elem.get('formcontrolname') or elem.get('text', '')
        print(f"  🔄 Forced to: {action_map.get(elem_type, 'click')} → '{target}'")
        return {
            'action': action_map.get(elem_type, 'click'),
            'target_name': target,
            'element_type': elem_type,
            'test_value': '',
            'reasoning': 'Validation override — LLM picked element outside untested list'
        }

    async def _test_loop(self, page: Page):
        max_iter  = 50
        iteration = 0

        previous_elements = []

        while iteration < max_iter:
            iteration  += 1
            self.step  += 1

            print(f"\n{'='*80}")
            print(f"STEP {iteration} | Depth: {self.context_stack.depth()}")
            print(f"{'='*80}")

            # ── OBSERVE ──────────────────────────────────────────────────────
            print("\n[OBSERVE]")
            screenshot    = await self._screenshot(page, f"step_{self.step}")
            elements_data = await self.observer.get_elements(page)
            # self.harvester.harvest_page(page.url, screenshot, elements_data)
            # self.harvester.harvest_actions(active_elements)
            print(f"DEBUG overlay detected: {elements_data.get('has_overlay')}")
            print(f"DEBUG overlay selector: {elements_data.get('overlay_selector')}")
            for e in elements_data.get('active_elements', []):
                print(f"DEBUG element: {e.get('text','')[:30]} | in_overlay={e.get('in_overlay')} | type={e.get('element_type')}")

            print(f"  Overlay: {elements_data.get('has_overlay')}")
            if elements_data.get('overlay_selector'):
                print(f"  Overlay selector: {elements_data.get('overlay_selector')}")
            print(f"  Discovered: {elements_data.get('total_discovered', 0)} interactive elements")

            # ── UPDATE CONTEXT STACK ─────────────────────────────────────────
            print("\n[MEMORY]")
            dom_hash     = await self._dom_hash(page)
            current      = self.context_stack.current()
            context_type = await self.observer.detect_context(page, elements_data)

            has_overlay_now  = elements_data.get('has_overlay', False)
            overlay_selector = elements_data.get('overlay_selector')
            was_in_overlay   = current.context_type in [
                ContextType.MODAL, ContextType.FORM, ContextType.CONFIRMATION
            ]

            if has_overlay_now and not was_in_overlay:
    # CHECK IF WIDGET FIRST
             self.global_memory.tested_elements = {
                k for k in self.global_memory.tested_elements
                if 'overlay:' not in k
                    }
             print(f"  🧹 After clear, overlay keys remaining: {[k for k in self.global_memory.tested_elements if k.startswith('overlay:')]}")
             new_frame = ContextFrame(
                        context_type=context_type,
                        description=f"{context_type.value} opened",
                        timestamp=datetime.now().isoformat(),
                        url=page.url,
                        dom_hash=dom_hash,
                        overlay_selector=overlay_selector
                    )
             self.context_stack.push(new_frame)
             current = self.context_stack.current()
             self.harvester.harvest_form(
        overlay_type=elements_data.get("overlay_type"),
        fields=active_elements,
        screenshot_b64=screenshot
    )


            elif not has_overlay_now and was_in_overlay:
                print("DEBUG overlay closing, current overlay memory:")
                for e in self.global_memory.tested_elements:
                    if e.startswith('overlay:'):
                        print(f"  {e}")
                toast_text = await self._detect_toast(page)      # ← ADD
                # self.story_tracker.complete_story(toast_text)
                self.context_stack.pop()
                current = self.context_stack.current()
                current.dom_hash         = dom_hash
                current.overlay_selector = None

            else:
                current.dom_hash = dom_hash
                if has_overlay_now:
                    current.overlay_selector = overlay_selector

            # ── SCOPE FILTER ─────────────────────────────────────────────────
            active_elements = elements_data.get('active_elements', [])
            active_elements = await self.element_filter.filter(
                elements=active_elements,
                screenshot_b64=screenshot,
                url=page.url,
                context_type=current.context_type.value
            )
            for e in active_elements:
                if e.get('element_type') == 'file':
                    print("🔥 FILE STILL PRESENT AFTER FILTER")
            self.harvester.harvest_page(page.url, screenshot, elements_data)
            self.harvester.harvest_actions(active_elements)
            scoped_elements = []

            for elem in active_elements:
                in_scope, reason = self.scope.is_element_in_scope(elem, page.url)
                if in_scope:
                    scoped_elements.append(elem)
                else:
                    print(f"  🚫 Skipped: {elem.get('text', 'element')[:30]} - {reason}")

            # ── GLOBAL MEMORY FILTER ─────────────────────────────────────────
            print(f"  🔍 Before get_untested, overlay keys: {[k for k in self.global_memory.tested_elements if k.startswith('overlay:')]}")
            untested = self.global_memory.get_untested(scoped_elements)
            print(f"{untested} this is untested logs")
            tested_positions = set()
            for elem in scoped_elements:
                identifier = self.global_memory._get_identifier(elem)
                if any(self.global_memory.is_tested(identifier, a)
                    for a in ['click', 'fill', 'select', 'check','upload']):
                    tested_positions.add((elem.get('x'), elem.get('y')))


            untested = [
                e for e in untested
                if (e.get('x'), e.get('y')) not in tested_positions
            ]
            print(f"{untested} second this is untested logs")
            full_screenshot = await self._full_screenshot(page, f"story_gen_{self.step}")
            # await self.decider.maybe_generate_story(
            #     page=page, elements=scoped_elements,
            #     screenshot_b64=screenshot,
            #     context_type=current.context_type.value,
            #     url=page.url
            # )

            if len(scoped_elements) > len(untested):
                print(f"  ✅ Global memory working:")
                tested_ids = {
                    self.global_memory._get_identifier(u) for u in untested
                }
                for elem in scoped_elements:
                    ident = self.global_memory._get_identifier(elem)
                    if ident not in tested_ids:
                        print(f"     - Already tested: {ident}")

            print(f"  Context: {current.context_type.value}")
            print(f"  Overlay scope: {current.overlay_selector or 'none (full page)'}")
            print(f"  In-scope elements: {len(scoped_elements)}")
            print(f"  Already tested (global): {len(scoped_elements) - len(untested)}")
            print(f"  Remaining untested: {len(untested)}")

            if not untested:
                print(f"  ✅ All elements tested")
                if self.context_stack.depth() > 1:
                    self.context_stack.pop()
                    continue
                else:
                    print(f"  🏁 Testing complete!")
                    break


            new_elements = [
                e for e in scoped_elements
                if not any(
                    (p.get('formcontrolname') or p.get('text')) ==
                    (e.get('formcontrolname') or e.get('text'))
                    for p in previous_elements
                )
            ]

            # ── DECIDE ───────────────────────────────────────────────────────
            print("\n[DECIDE]")
            print(f"  Elements being passed to decider:")
            for e in untested:
                print(f"    - [{e.get('element_type')}] {e.get('formcontrolname') or e.get('text')} | in_overlay={e.get('in_overlay')}")
            # decision = await self.decider.decide(screenshot, current, untested)
            last_action = self.history[-1] if self.history else None
            decision = await self.decider.decide(screenshot, current, untested, last_action=last_action, new_elements=new_elements)

            if decision.get('action') == 'done':
                break
            decision = self._validate_decision(decision, untested)

            print(f"  Action: {decision.get('action')}")
            print(f"  Target: {decision.get('target_name')}")

            # FIX 2: Record action BEFORE checking for loops
            self.loop_detector.record(
                decision.get('action'),
                decision.get('target_name')
            )

            is_loop, reason = self.loop_detector.is_looping()
            if is_loop:
                print(f"  🔁 Loop: {reason}")
                self.story_tracker.mark_loop_detected(decision.get("target_name", ""))  # ← ADD

                # FIX 1: Find the actual element dict to get proper identifier
                # Try multiple matching strategies
                matching_elem = None
                decision_target = decision.get('target_name', '').strip()

                for elem in untested:
                    # Strategy 1: Exact match on formcontrolname
                    if elem.get('formcontrolname', '') == decision_target:
                        matching_elem = elem
                        break

                    # Strategy 2: Exact match on text/label
                    if elem.get('text', '').strip() == decision_target:
                        matching_elem = elem
                        break

                    # Strategy 3: Exact match on name
                    if elem.get('name', '') == decision_target:
                        matching_elem = elem
                        break

                    # Strategy 4: Partial match on text (for labels like "Tipe Bank *" vs "Tipe Bank")
                    elem_text = elem.get('text', '').strip()
                    if elem_text and decision_target in elem_text:
                        matching_elem = elem
                        break

                # Strategy 5: If still not found, try all scoped elements (not just untested)
                if not matching_elem:
                    for elem in scoped_elements:
                        if (elem.get('formcontrolname', '') == decision_target or
                            elem.get('text', '').strip() == decision_target or
                            decision_target in elem.get('text', '').strip()):
                            matching_elem = elem
                            break

                if matching_elem:
                    # Use the SAME identifier method as GlobalMemory
                    identifier = self.global_memory._get_identifier(matching_elem)
                    self.global_memory.mark_tested(identifier, decision.get('action'))
                    print(f"     Marked as tested: {identifier}")
                else:
                    print(f"     ⚠️  Could not find element '{decision_target}' in untested list - forcing skip")

                if self.context_stack.depth() > 1:
                    self.context_stack.pop()
                continue

            # ── EXECUTE ──────────────────────────────────────────────────────
            print("\n[EXECUTE]")
            state_before = await self.state_extractor.extract(
                screenshot_b64=screenshot,
                url=page.url
            )
            state_after = {}
            state_diff = {}

            # Find matching element for proper identification
            # Use same matching logic as loop handler
            matching_elem = None
            decision_target = decision.get('target_name', '').strip()

            for elem in untested:
                # Strategy 1: Exact match on formcontrolname
                if elem.get('formcontrolname', '') == decision_target:
                    matching_elem = elem
                    break

                # Strategy 2: Exact match on text/label
                if elem.get('text', '').strip() == decision_target:
                    matching_elem = elem
                    break

                # Strategy 3: Exact match on name
                if elem.get('name', '') == decision_target:
                    matching_elem = elem
                    break

                # Strategy 4: Partial match on text
                elem_text = elem.get('text', '').strip()
                if elem_text and decision_target in elem_text:
                    matching_elem = elem
                    break

            locator, method = await self.controller.find(
                decision,
                overlay_selector=current.overlay_selector
            )

            if not locator:
                print(f"  ❌ Not found")
                if matching_elem:
                    identifier = self.global_memory._get_identifier(matching_elem)
                    self.global_memory.mark_tested(identifier, decision.get('action'))
                    print(f"     Marked as tested (not found): {identifier}")
                continue

            print(f"  ✓ Found: {method}")

            result = await self.executor.execute(
                locator,
                decision.get('action'),
                decision.get('test_value'),
                elem_type=decision.get('element_type', '')
            )
            print(f"  🔍 state_diff stored: {state_diff}")
            if result.get("all_options"):
                self.harvester.harvest_dropdown(
                    field_name=decision.get("target_name"),
                    options=result.get("all_options")
                )
            screenshot_after = await self._screenshot(page, f"after_step_{self.step}")
            state_after = await self.state_extractor.extract(
                screenshot_b64=screenshot_after,
                url=page.url,
                action_context=f"{decision.get('action')} '{decision.get('target_name')}'"
            )
            state_diff = diff_states(state_before, state_after)
            print(f"  🔍 state_diff stored: {state_diff}")

            if state_diff:
                print(f"  📸 State diff: {state_diff}")
            # FIX 4: Only mark as tested if execution was successful
            is_submit = any(
                kw in decision.get("target_name", "").lower()
                for kw in ["simpan", "save", "submit", "tambah", "perbarui", "update"]
            )

            validation_failed = (
                state_diff.get("error_appeared") is not None
                or (
                    state_diff.get("toast_appeared")
                    and "validation" in state_diff["toast_appeared"].lower()
                )
            )

            if matching_elem:
                identifier = self.global_memory._get_identifier(matching_elem)

                if result.get("success"):

                    if is_submit and validation_failed:
                        print("⚠️ Submit failed validation — NOT marking as tested")
                    else:
                        self.global_memory.mark_tested(identifier, decision.get("action"))
                        print(f"✅ Marked as tested: {identifier}")                    # identifier = self.global_memory._get_identifier(matching_elem)
                    self.global_memory.mark_tested(identifier, decision.get('action'))
                    print(f"  ✅ Marked as tested: {identifier}")
                    # print(f"  ✅ Marked as tested: {identifier}")
                elif result.get('error') and 'disabled' in result.get('error', '').lower():
                    # if matching_elem and result.get('error') and 'disabled' in result.get('error', '').lower():
                        # identifier = self.global_memory._get_identifier(matching_elem)

                        self.global_memory.mark_tested(identifier, decision.get('action'))
                        print(f"  ⚠️  Marked as tested (disabled button): {identifier}")

                    # print(f"  ⚠️  Execution failed - will retry this element")
                # elif not matching_elem:
                    # print(f"  ⚠️  Could not find matching element in list - cannot mark as tested")
                else:
                    print(f"  ⚠️  Execution failed - will retry this element")
            else:
                print(f"  ⚠️  Could not find matching element in list - cannot mark as tested")


            is_submit = any(kw in decision.get("target_name","").lower()
                for kw in ["simpan","save","submit","tambah","perbarui","update"])
            if is_submit and not result.get("success"):
                self.story_tracker.mark_submit_failed(decision.get("target_name",""), result.get("error",""))
            # else:
            #     self.story_tracker.record_action(
            #         action=decision.get("action",""), target=decision.get("target_name",""),
            #         value=decision.get("test_value",""), success=result.get("success",False),
            #         error=result.get("error") if not result.get("success") else None
            #     )
            self.history.append({
                "step":        self.step,
                "url":        page.url,
                "page_title": await page.title(),
                "decision":    decision,
                "result":      result,
                "all_options": result.get("all_options"),
                "timestamp":   datetime.now().isoformat(),
                "state_before": state_before,
                "state_after":  state_after,
                "state_diff":   state_diff,
            })

            print(f"  Success: {result.get('success')}")
            await asyncio.sleep(1)
            previous_elements = scoped_elements.copy()

        print(f"\n{'='*80}")
        print(f"🏁 Complete: {iteration} steps")
        print(f"{'='*80}")

    async def _inject_auth(self, page: Page, context, target_url: str):
        parsed = urlparse(target_url)
        home   = f"{parsed.scheme}://{parsed.netloc}/"

        await page.goto(home)
        await page.wait_for_load_state('networkidle')

        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"localStorage.setItem('{key}', `{val}`)")
            except Exception:
                pass

        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"sessionStorage.setItem('{key}', `{val}`)")
            except Exception:
                pass

        cookies = self.auth_data.get('cookies', [])
        if cookies:
            await context.add_cookies(cookies)

        print("  ✅ Auth injected\n")

    async def _screenshot(self, page: Page, name: str) -> str:
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            await page.screenshot(path=path, full_page=False)
            with open(path, 'rb') as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return ""

    async def _dom_hash(self, page: Page) -> str:
        try:
            html = await page.evaluate("document.body.innerHTML")
            return hashlib.md5(html.encode()).hexdigest()[:16]
        except Exception:
            return ""

    async def _detect_toast(self, page: Page) -> str:
        sels = ["mat-snack-bar-container", '[role="alert"]', '[role="status"]',
                ".toast", "[class*='toast']", ".alert", "[class*='snack']"]
        try:
            for sel in sels:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    text = await loc.first.inner_text()
                    if text and text.strip():
                        return text.strip()
        except Exception:
            pass
        return ""

    async def _save_results(self):
        results = {
            "session_id":  self.session_id,
            "timestamp":   datetime.now().isoformat(),
            "total_steps": self.step,
            "history":     self.history
        }
        out = self.output_dir / f"test_{self.session_id}.json"
        with open(out, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\n💾 Results: {out}")

        success = sum(1 for h in self.history if h.get('result', {}).get('success'))
        print(f"\n📊 SUMMARY")
        print(f"  Total:   {len(self.history)}")
        print(f"  Success: {success}")
        print(f"  Failed:  {len(self.history) - success}")
        await self.harvester.generate_stories(history=self.history)




# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def main():
    if not Path('auth.json').exists():
        print("❌ auth.json not found")
        return

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("❌ OPENAI_API_KEY not set")
        return

    tester = SemanticTester(openai_api_key=key)
    tester._interactive = True

    url = input("\nEnter URL to test: ").strip()
    if not url:
        print("❌ No URL")
        return

    await tester.run(url)


if __name__ == "__main__":
    asyncio.run(main())