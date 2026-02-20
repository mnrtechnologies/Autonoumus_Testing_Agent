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
                if (rect.width === 0 || rect.height === 0) return false;

                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                if (style.opacity === '0') return false;

                // Don't filter out disabled elements - we'll mark them as disabled instead
                // This allows us to see submit buttons that become enabled after form fills
                
                const tag = el.tagName.toLowerCase();
                const type = el.type || '';
                if ((tag === 'input' || tag === 'textarea') &&
                    type !== 'checkbox' && type !== 'radio' &&
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

                const text = (
                    el.innerText ||
                    el.textContent ||
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') || ''
                ).trim().slice(0, 150);

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
                if (!label) label = `${{el.type || 'text'}} input`;

                const contextPrefix = isInOverlay ? 'overlay:' : 'page:';
                const key = `${{contextPrefix}}input:${{el.type}}:${{label}}:${{id}}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({{
                    tag: 'input', type: el.type || 'text', role: 'textbox',
                    text: label, id, name: nameAttr,
                    classes: Array.from(el.classList).slice(0, 5),
                    href: '', required: el.hasAttribute('required'),
                    enabled: true, blocked: isBlocked, in_overlay: isInOverlay,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    element_type: 'input',
                    placeholder, formcontrolname: formControlName
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

            // ── Collect CUSTOM SELECT components ──────────────────────────────
            const customSelectSelectors = [
                '[role="combobox"]:not(input):not(select)',
                '[role="listbox"]:not(select)',
                'mat-select',
                'p-dropdown .p-dropdown',
                'p-multiselect .p-multiselect',
                '.ant-select-selector',
                'ng-select',
                '.vs__dropdown-toggle',
                '.react-select__control',
                '.v-select__slot',
                '[formcontrolname]:not(input):not(select):not(textarea)',
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
            if (activeOverlay) {{
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

            return {{
                has_overlay:       !!activeOverlay,
                overlay_type:      overlayType,
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