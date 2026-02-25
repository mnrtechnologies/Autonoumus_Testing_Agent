"""
SEMANTIC WEB EXPLORER - PRODUCTION ARCHITECTURE
LLM-Driven Adaptive Web Testing with Complete Component Architecture

Architecture: LLM decides WHAT, Code decides HOW
Components: Orchestrator → Discoverer → Classifier → Executor → Analyzer → Handlers
"""
import asyncio
import json
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple, Set
from urllib.parse import urlparse
from enum import Enum
from dataclasses import dataclass, asdict
from collections import deque
import os
from playwright.async_api import async_playwright, Page, Locator, BrowserContext
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

# ═══════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════

class ExplorationStatus(Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    EXPLORED = "EXPLORED"
    FAILED = "FAILED"

class SafetyClassification(Enum):
    SAFE = "SAFE"
    REVERSIBLE = "REVERSIBLE"
    DESTRUCTIVE = "DESTRUCTIVE"
    CRITICAL = "CRITICAL"

class PatternType(Enum):
    HIERARCHICAL = "HIERARCHICAL"
    FORM = "FORM"
    NAVIGATION = "NAVIGATION"
    MODAL = "MODAL"
    NO_CHANGE = "NO_CHANGE"
    ERROR = "ERROR"

class SafetyMode(Enum):
    EXPLORATION_ONLY = "EXPLORATION_ONLY"  # No destructive actions
    FULL_TESTING = "FULL_TESTING"          # All actions allowed
    READ_ONLY = "READ_ONLY"                # Only navigation

@dataclass
class ElementNode:
    """Element in the exploration tree"""
    id: str
    selector: str
    label: str
    element_type: str
    parent_id: Optional[str]
    depth: int
    exploration_status: ExplorationStatus
    requires_hover: bool
    is_ephemeral: bool
    state_when_visible: Optional[str]
    interaction_result: Optional[Dict]
    metadata: Dict
    children: List[str]
    priority: int = 5
    safety_classification: Optional[SafetyClassification] = None

@dataclass
class InteractionResult:
    """Result of an interaction"""
    success: bool
    pattern_type: Optional[PatternType]
    state_hash_before: str
    state_hash_after: str
    url_before: str
    url_after: str
    screenshot_before: str
    screenshot_after: str
    dom_snapshot: Dict
    error: Optional[str]
    new_elements: List[Dict]
    execution_time: float


# ═══════════════════════════════════════════════════════════════
#  COMPONENT 1: STATE FINGERPRINTER
# ═══════════════════════════════════════════════════════════════

class StateFingerprinter:
    """Generate stable, semantic hash of page state"""
    
    @staticmethod
    async def get_state_hash(page: Page) -> str:
        """Generate semantic state hash"""
        try:
            state_data = await page.evaluate("""() => {
                // Extract semantic structure
                const structure = {
                    url: window.location.pathname,
                    title: document.title,
                    forms: document.querySelectorAll('form').length,
                    buttons: document.querySelectorAll('button').length,
                    inputs: document.querySelectorAll('input').length,
                    links: document.querySelectorAll('a').length,
                    modals: document.querySelectorAll('[role="dialog"], .modal.show').length,
                    
                    // Navigation structure
                    nav_items: Array.from(document.querySelectorAll('nav a, [role="navigation"] a'))
                        .map(a => a.textContent?.trim())
                        .filter(Boolean)
                        .sort(),
                    
                    // Main headings (schema, not content)
                    headings: Array.from(document.querySelectorAll('h1, h2, h3'))
                        .map(h => h.tagName)
                        .slice(0, 10),
                    
                    // Form schemas (not values)
                    form_schemas: Array.from(document.querySelectorAll('form')).map(form => {
                        return {
                            fields: Array.from(form.querySelectorAll('input, select, textarea'))
                                .map(f => ({
                                    type: f.type || f.tagName.toLowerCase(),
                                    name: f.name || f.id || ''
                                }))
                        };
                    })
                };
                
                return structure;
            }""")
            
            # Normalize and hash
            normalized = json.dumps(state_data, sort_keys=True)
            return hashlib.sha256(normalized.encode()).hexdigest()[:16]
            
        except Exception as e:
            print(f"    ⚠️ State fingerprint failed: {e}")
            return "unknown_state"


# ═══════════════════════════════════════════════════════════════
#  COMPONENT 2: ELEMENT DISCOVERER
# ═══════════════════════════════════════════════════════════════

class ElementDiscoverer:
    """Find all interactive elements on the page"""
    
    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client
    
    async def discover_elements(self, page: Page, goal: str, current_depth: int) -> List[Dict]:
        """Complete discovery process"""
        
        print("\n  🔍 ELEMENT DISCOVERY")
        
        # Phase 1: Static scan
        static_elements = await self._static_scan(page)
        print(f"    Static scan: {len(static_elements)} elements")
        
        # Phase 2: Hover scan (sample-based)
        hover_elements = await self._hover_scan(page, sample_size=3)
        print(f"    Hover scan: {len(hover_elements)} elements")
        
        # Phase 3: Virtualization detection
        virtual_templates = await self._detect_virtualization(page)
        print(f"    Virtual templates: {len(virtual_templates)}")
        
        # Combine all elements
        all_elements = static_elements + hover_elements + virtual_templates
        
        # Phase 4: LLM prioritization
        prioritized = await self._prioritize_with_llm(all_elements, goal, page)
        
        print(f"    ✓ Total discovered: {len(prioritized)}")
        return prioritized
    
    async def _static_scan(self, page: Page) -> List[Dict]:
        """Find all visible interactive elements"""
        
        elements = await page.evaluate("""() => {
            const interactive = [];
            const selectors = [
                'button:not([disabled])',
                'a[href]:not([href="#"])',
                'input:not([type="hidden"]):not([disabled])',
                'select:not([disabled])',
                'textarea:not([disabled])',
                '[role="button"]:not([aria-disabled="true"])',
                '[role="menuitem"]',
                '[role="tab"]',
                '[role="link"]',
                '[onclick]',
                '[data-testid]'
            ];
            
            const seen = new Set();
            
            document.querySelectorAll(selectors.join(',')).forEach((el) => {
                // Skip if not visible
                if (!el.offsetParent && el.tagName !== 'INPUT') return;
                
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                
                // Extract label
                const text = (
                    el.innerText || 
                    el.value || 
                    el.placeholder || 
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.getAttribute('data-testid') ||
                    ''
                ).trim().slice(0, 100);
                
                if (!text) return; // Skip unlabeled elements
                
                // Build unique selector
                let selector = '';
                if (el.id) {
                    selector = `#${el.id}`;
                } else if (el.className && typeof el.className === 'string') {
                    const classes = el.className.split(' ').filter(c => 
                        c && !c.match(/^(css-|MuiBox-|makeStyles-)/)
                    ).slice(0, 2);
                    if (classes.length > 0) {
                        selector = el.tagName.toLowerCase() + '.' + classes.join('.');
                    }
                }
                
                if (!selector) {
                    selector = el.tagName.toLowerCase();
                }
                
                const key = `${selector}:${text}`;
                if (seen.has(key)) return;
                seen.add(key);
                
                interactive.push({
                    selector: selector,
                    label: text,
                    element_type: el.tagName.toLowerCase(),
                    type: el.type || '',
                    role: el.getAttribute('role') || '',
                    href: el.getAttribute('href') || '',
                    requires_hover: false,
                    is_ephemeral: false,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y)
                });
            });
            
            return interactive;
        }""")
        
        return elements
    
    async def _hover_scan(self, page: Page, sample_size: int = 3) -> List[Dict]:
        """Detect hover-triggered elements"""
        
        hover_elements = []
        
        try:
            # Find hover-able containers
            containers = await page.evaluate("""() => {
                const hoverable = [];
                const selectors = ['tr', '[role="row"]', '.card', 'li', '[role="listitem"]'];
                
                document.querySelectorAll(selectors.join(',')).forEach((el, idx) => {
                    if (!el.offsetParent) return;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0) return;
                    
                    hoverable.push({
                        index: idx,
                        selector: el.tagName.toLowerCase(),
                        x: Math.round(rect.x),
                        y: Math.round(rect.y)
                    });
                });
                
                return hoverable.slice(0, 5); // Sample first 5
            }""")
            
            # Test each container for hover effects
            for container in containers[:sample_size]:
                try:
                    # Hover over container
                    await page.mouse.move(container['x'] + 10, container['y'] + 10)
                    await asyncio.sleep(0.3)  # Wait for hover effects
                    
                    # Check for new elements
                    new_elements = await page.evaluate("""(x, y) => {
                        const elements = [];
                        const target = document.elementFromPoint(x, y);
                        if (!target) return elements;
                        
                        // Find action buttons within this container
                        const parent = target.closest('tr, [role="row"], .card, li');
                        if (!parent) return elements;
                        
                        parent.querySelectorAll('button, a, [role="button"]').forEach(el => {
                            const rect = el.getBoundingClientRect();
                            if (rect.width === 0) return;
                            
                            const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                            if (!text) return;
                            
                            elements.push({
                                selector: el.tagName.toLowerCase(),
                                label: text,
                                element_type: el.tagName.toLowerCase(),
                                requires_hover: true,
                                hover_target: parent.tagName.toLowerCase(),
                                is_ephemeral: true
                            });
                        });
                        
                        return elements;
                    }""", container['x'] + 10, container['y'] + 10)
                    
                    hover_elements.extend(new_elements)
                    
                except Exception:
                    continue
            
        except Exception as e:
            print(f"    Hover scan error: {e}")
        
        return hover_elements
    
    async def _detect_virtualization(self, page: Page) -> List[Dict]:
        """Detect virtualized/repeating patterns"""
        
        templates = await page.evaluate("""() => {
            const patterns = [];
            
            // Look for tables with many rows
            document.querySelectorAll('table, [role="table"]').forEach(table => {
                const rows = table.querySelectorAll('tr, [role="row"]');
                if (rows.length > 5) {
                    // Extract template from first visible row
                    const firstRow = Array.from(rows).find(r => r.offsetParent);
                    if (!firstRow) return;
                    
                    const actions = [];
                    firstRow.querySelectorAll('button, a[href], [role="button"]').forEach(btn => {
                        const text = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                        if (text) actions.push(text);
                    });
                    
                    if (actions.length > 0) {
                        patterns.push({
                            selector: 'table tr:first-child',
                            label: `Row Template (${actions.join(', ')})`,
                            element_type: 'template',
                            is_repeating_pattern: true,
                            available_actions: actions
                        });
                    }
                }
            });
            
            return patterns;
        }""")
        
        return templates
    
    async def _prioritize_with_llm(self, elements: List[Dict], goal: str, page: Page) -> List[Dict]:
        """Use LLM to prioritize elements based on goal"""
        
        if not elements:
            return []
        
        # Take screenshot for context
        screenshot_bytes = await page.screenshot()
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode()
        
        # Prepare elements summary
        elements_summary = [
            {
                "label": el.get("label", ""),
                "type": el.get("element_type", ""),
                "role": el.get("role", "")
            }
            for el in elements[:30]  # First 30 for LLM
        ]
        
        prompt = f"""Goal: {goal}

Elements found:
{json.dumps(elements_summary, indent=2)}

Rate each element's relevance to the goal (1=highest, 10=lowest).
Return ONLY JSON array with same length as input:
[{{"label": "...", "priority": 1}}, ...]"""

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                    ]
                }],
                max_tokens=2000,
                temperature=0.1
            )
            
            raw = response.choices[0].message.content
            priorities = json.loads(self._extract_json(raw))
            
            # Merge priorities back
            priority_map = {p['label']: p.get('priority', 5) for p in priorities}
            
            for el in elements:
                el['priority'] = priority_map.get(el.get('label', ''), 5)
            
        except Exception as e:
            print(f"    LLM prioritization failed: {e}")
            # Default priorities
            for el in elements:
                el['priority'] = 5
        
        # Sort by priority
        elements.sort(key=lambda x: x.get('priority', 5))
        
        return elements
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from markdown"""
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            return text[start:end].strip()
        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            return text[start:end].strip()
        return text.strip()


# ═══════════════════════════════════════════════════════════════
#  COMPONENT 3: ACTION CLASSIFIER
# ═══════════════════════════════════════════════════════════════

class ActionClassifier:
    """Classify actions as SAFE/DESTRUCTIVE"""
    
    DESTRUCTIVE_KEYWORDS = [
        'delete', 'remove', 'destroy', 'purge', 'clear all', 'reset',
        'deactivate', 'archive', 'trash', 'wipe', 'permanently',
        'cannot be undone', 'irreversible'
    ]
    
    @staticmethod
    async def classify_action(element: Dict, safety_mode: SafetyMode) -> Dict:
        """Classify element action safety"""
        
        label = element.get('label', '').lower()
        href = element.get('href', '').lower()
        element_type = element.get('element_type', '')
        
        # Check for destructive patterns
        is_destructive = any(kw in label for kw in ActionClassifier.DESTRUCTIVE_KEYWORDS)
        is_destructive_url = any(kw in href for kw in ['delete', 'remove', 'destroy'])
        
        # Classify
        if is_destructive or is_destructive_url:
            classification = SafetyClassification.DESTRUCTIVE
        elif element_type == 'a' and href.startswith('http'):
            classification = SafetyClassification.SAFE
        elif 'edit' in label or 'update' in label:
            classification = SafetyClassification.REVERSIBLE
        else:
            classification = SafetyClassification.SAFE
        
        # Check if allowed
        allowed = True
        special_handling = None
        
        if safety_mode == SafetyMode.EXPLORATION_ONLY:
            if classification == SafetyClassification.DESTRUCTIVE:
                allowed = True  # Allow click to see modal
                special_handling = "verify_modal_then_cancel"
            elif classification == SafetyClassification.CRITICAL:
                allowed = False
        elif safety_mode == SafetyMode.READ_ONLY:
            if classification in [SafetyClassification.DESTRUCTIVE, SafetyClassification.REVERSIBLE]:
                allowed = False
        
        return {
            'classification': classification,
            'allowed': allowed,
            'reason': f"{classification.value} action in {safety_mode.value} mode",
            'special_handling': special_handling
        }


# ═══════════════════════════════════════════════════════════════
#  COMPONENT 4: INTERACTION EXECUTOR
# ═══════════════════════════════════════════════════════════════

class InteractionExecutor:
    """Execute interactions with elements"""
    
    def __init__(self, page: Page, fingerprinter: StateFingerprinter):
        self.page = page
        self.fingerprinter = fingerprinter
    
    async def execute(self, element: Dict, special_handling: Optional[str] = None) -> InteractionResult:
        """Execute interaction with element"""
        
        start_time = datetime.now()
        
        # Capture before state
        state_before = await self.fingerprinter.get_state_hash(self.page)
        url_before = self.page.url
        screenshot_before = await self._screenshot_b64()
        
        success = False
        error = None
        pattern_type = None
        new_elements = []
        
        try:
            # Find element
            selector = element.get('selector', '')
            locator = await self._find_element(element)
            
            if not locator:
                raise Exception(f"Element not found: {selector}")
            
            # Scroll into view
            await locator.scroll_into_view_if_needed(timeout=5000)
            await asyncio.sleep(0.2)
            
            # Execute action
            if special_handling == "verify_modal_then_cancel":
                # Click to verify modal, then cancel
                await locator.click(timeout=5000)
                await asyncio.sleep(1)
                
                # Look for cancel button
                cancel = await self._find_cancel_button()
                if cancel:
                    await cancel.click(timeout=3000)
                    await asyncio.sleep(0.5)
                
                success = True
                pattern_type = PatternType.MODAL
                
            else:
                # Normal click
                await locator.click(timeout=5000)
                await asyncio.sleep(1)  # Wait for effects
                
                # Wait for stability
                await self._wait_for_stability()
                
                success = True
            
        except Exception as e:
            error = str(e)
            print(f"    ❌ Execution failed: {e}")
        
        # Capture after state
        state_after = await self.fingerprinter.get_state_hash(self.page)
        url_after = self.page.url
        screenshot_after = await self._screenshot_b64()
        
        # Get DOM snapshot
        dom_snapshot = await self._get_dom_snapshot()
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        return InteractionResult(
            success=success,
            pattern_type=pattern_type,
            state_hash_before=state_before,
            state_hash_after=state_after,
            url_before=url_before,
            url_after=url_after,
            screenshot_before=screenshot_before,
            screenshot_after=screenshot_after,
            dom_snapshot=dom_snapshot,
            error=error,
            new_elements=new_elements,
            execution_time=execution_time
        )
    
    async def _find_element(self, element: Dict) -> Optional[Locator]:
        """Find element using multiple strategies"""
        
        label = element.get('label', '')
        selector = element.get('selector', '')
        element_type = element.get('element_type', '')
        
        # Strategy 1: By role and name
        if element_type in ['button', 'link']:
            try:
                role = 'button' if element_type == 'button' else 'link'
                locator = self.page.get_by_role(role, name=label, exact=False)
                if await locator.count() > 0:
                    return locator.first
            except:
                pass
        
        # Strategy 2: By text
        try:
            locator = self.page.get_by_text(label, exact=False)
            if await locator.count() > 0:
                return locator.first
        except:
            pass
        
        # Strategy 3: By selector
        try:
            locator = self.page.locator(selector)
            if await locator.count() > 0:
                return locator.first
        except:
            pass
        
        return None
    
    async def _find_cancel_button(self) -> Optional[Locator]:
        """Find cancel/close button in modal"""
        
        for text in ['Cancel', 'Close', 'Dismiss', 'No', '×']:
            try:
                locator = self.page.get_by_role('button', name=text, exact=False)
                if await locator.count() > 0:
                    return locator.first
            except:
                continue
        
        return None
    
    async def _wait_for_stability(self):
        """Wait for page to stabilize"""
        try:
            await self.page.wait_for_load_state('networkidle', timeout=3000)
        except:
            await asyncio.sleep(0.5)
    
    async def _screenshot_b64(self) -> str:
        """Capture screenshot as base64"""
        try:
            screenshot_bytes = await self.page.screenshot()
            return base64.b64encode(screenshot_bytes).decode()
        except:
            return ""
    
    async def _get_dom_snapshot(self) -> Dict:
        """Get simplified DOM snapshot"""
        try:
            snapshot = await self.page.evaluate("""() => {
                return {
                    title: document.title,
                    url: window.location.href,
                    modals: document.querySelectorAll('[role="dialog"], .modal.show').length,
                    forms: document.querySelectorAll('form').length
                };
            }""")
            return snapshot
        except:
            return {}


# ═══════════════════════════════════════════════════════════════
#  COMPONENT 5: PATTERN ANALYZER
# ═══════════════════════════════════════════════════════════════

class PatternAnalyzer:
    """Analyze interaction results and classify patterns"""
    
    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client
    
    async def analyze(self, result: InteractionResult, element: Dict) -> Dict:
        """Analyze what happened after interaction"""
        
        # Quick checks first
        if result.url_before != result.url_after:
            return {
                'pattern': PatternType.NAVIGATION,
                'metadata': {'new_url': result.url_after}
            }
        
        if result.state_hash_before == result.state_hash_after:
            return {
                'pattern': PatternType.NO_CHANGE,
                'metadata': {}
            }
        
        # Use LLM for complex analysis
        prompt = f"""Analyze this web interaction:

Element clicked: {element.get('label', 'unknown')} ({element.get('element_type', 'unknown')})

DOM changes:
- Modals before: {result.dom_snapshot.get('modals', 0)} (state: {result.state_hash_before[:8]})
- Modals after: {result.dom_snapshot.get('modals', 0)} (state: {result.state_hash_after[:8]})
- Forms: {result.dom_snapshot.get('forms', 0)}

What pattern does this represent?
- HIERARCHICAL: Menu/dropdown opened with new clickable options
- FORM: Form appeared or fields loaded
- MODAL: Dialog/popup appeared
- NO_CHANGE: Nothing visible changed
- ERROR: Something broke

Return ONLY JSON:
{{"pattern": "HIERARCHICAL|FORM|MODAL|NO_CHANGE|ERROR", "metadata": {{}}}}"""

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{result.screenshot_after}"}}
                    ]
                }],
                max_tokens=500,
                temperature=0.1
            )
            
            raw = response.choices[0].message.content
            analysis = json.loads(self._extract_json(raw))
            
            pattern_str = analysis.get('pattern', 'NO_CHANGE')
            pattern = PatternType[pattern_str] if pattern_str in PatternType.__members__ else PatternType.NO_CHANGE
            
            return {
                'pattern': pattern,
                'metadata': analysis.get('metadata', {})
            }
            
        except Exception as e:
            print(f"    Pattern analysis failed: {e}")
            return {
                'pattern': PatternType.NO_CHANGE,
                'metadata': {}
            }
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from markdown"""
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            return text[start:end].strip()
        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            return text[start:end].strip()
        return text.strip()


# ═══════════════════════════════════════════════════════════════
#  COMPONENT 6: ORCHESTRATOR (Main Controller)
# ═══════════════════════════════════════════════════════════════

class Orchestrator:
    """Main controller coordinating all components"""
    
    def __init__(self, openai_api_key: str, goal: str, safety_mode: SafetyMode,
                 max_depth: int = 10, max_elements: int = 200):
        self.openai = OpenAI(api_key=openai_api_key)
        self.goal = goal
        self.safety_mode = safety_mode
        self.max_depth = max_depth
        self.max_elements = max_elements
        
        # Components
        self.fingerprinter = StateFingerprinter()
        self.discoverer = ElementDiscoverer(self.openai)
        self.analyzer = PatternAnalyzer(self.openai)
        
        # State
        self.element_tree: Dict[str, ElementNode] = {}
        self.exploration_queue: deque = deque()
        self.visited_states: Set[str] = set()
        self.interaction_history: List[Dict] = []
        self.elements_explored = 0
        self.current_depth = 0
        
        # Session
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path('exploration_output')
        self.output_dir.mkdir(exist_ok=True)
        
        print(f"\n{'='*80}")
        print("🧠 SEMANTIC WEB EXPLORER - PRODUCTION ARCHITECTURE")
        print(f"{'='*80}")
        print(f"Goal: {goal}")
        print(f"Safety Mode: {safety_mode.value}")
        print(f"Max Depth: {max_depth}")
        print(f"Session: {self.session_id}")
        print(f"{'='*80}\n")
    
    async def explore(self, page: Page):
        """Main exploration loop"""
        
        # Initialize
        self.executor = InteractionExecutor(page, self.fingerprinter)
        
        iteration = 0
        max_iterations = self.max_elements
        
        while iteration < max_iterations:
            iteration += 1
            
            print(f"\n{'='*60}")
            print(f"ITERATION {iteration}")
            print(f"{'='*60}")
            
            # Check stopping conditions
            if await self._check_stopping_conditions():
                break
            
            # Get next element to explore
            element = await self._get_next_element(page)
            
            if not element:
                print("\n✅ Exploration complete - no more elements")
                break
            
            print(f"\n  🎯 Target: {element.get('label', 'unknown')} ({element.get('element_type', 'unknown')})")
            
            # Safety check
            safety_check = await ActionClassifier.classify_action(element, self.safety_mode)
            
            if not safety_check['allowed']:
                print(f"  🚫 Blocked: {safety_check['reason']}")
                self.elements_explored += 1
                continue
            
            print(f"  ✓ Safety: {safety_check['classification'].value}")
            
            # Execute interaction
            print(f"  ⚡ Executing...")
            result = await self.executor.execute(element, safety_check['special_handling'])
            
            if not result.success:
                print(f"  ❌ Failed: {result.error}")
                self.elements_explored += 1
                continue
            
            print(f"  ✓ Success ({result.execution_time:.1f}s)")
            
            # Analyze result
            print(f"  🔍 Analyzing pattern...")
            analysis = await self.analyzer.analyze(result, element)
            pattern = analysis['pattern']
            
            print(f"  📊 Pattern: {pattern.value}")
            
            # Handle pattern
            await self._handle_pattern(pattern, analysis, result, page)
            
            # Record
            self._record_interaction(element, result, analysis)
            self.elements_explored += 1
            
            # Save progress
            if iteration % 10 == 0:
                self._save_progress()
            
            await asyncio.sleep(0.5)
        
        print(f"\n{'='*60}")
        print(f"🏁 EXPLORATION COMPLETE")
        print(f"{'='*60}")
        print(f"Elements explored: {self.elements_explored}")
        print(f"Iterations: {iteration}")
        print(f"{'='*60}\n")
        
        self._save_final_report()
    
    async def _get_next_element(self, page: Page) -> Optional[Dict]:
        """Get next element to explore"""
        
        # If queue empty, discover new elements
        if len(self.exploration_queue) == 0:
            print("\n  🔍 Discovery phase...")
            
            elements = await self.discoverer.discover_elements(
                page, 
                self.goal, 
                self.current_depth
            )
            
            # Add to queue
            for el in elements:
                self.exploration_queue.append(el)
            
            if len(self.exploration_queue) == 0:
                return None
        
        # Get next from queue
        return self.exploration_queue.popleft()
    
    async def _handle_pattern(self, pattern: PatternType, analysis: Dict, 
                              result: InteractionResult, page: Page):
        """Handle different interaction patterns"""
        
        if pattern == PatternType.NAVIGATION:
            # Check if we've visited this page
            state_hash = result.state_hash_after
            if state_hash in self.visited_states:
                print("    ↺ Already visited this page")
                await page.go_back()
                await asyncio.sleep(1)
            else:
                self.visited_states.add(state_hash)
                print("    ✓ New page, continuing exploration")
        
        elif pattern == PatternType.HIERARCHICAL:
            print("    → Hierarchical pattern detected")
            # Discover new child elements
            new_elements = await self.discoverer.discover_elements(page, self.goal, self.current_depth + 1)
            for el in new_elements[:5]:  # Limit children
                self.exploration_queue.append(el)
            print(f"    + Added {len(new_elements[:5])} child elements")
        
        elif pattern == PatternType.FORM:
            print("    → Form detected")
            # For now, skip form filling (can add form handler later)
            # Close form if possible
            try:
                cancel = await self.executor._find_cancel_button()
                if cancel:
                    await cancel.click()
                    await asyncio.sleep(0.5)
            except:
                pass
        
        elif pattern == PatternType.MODAL:
            print("    → Modal detected")
            # Close modal
            try:
                cancel = await self.executor._find_cancel_button()
                if cancel:
                    await cancel.click()
                    await asyncio.sleep(0.5)
            except:
                pass
    
    async def _check_stopping_conditions(self) -> bool:
        """Check if we should stop exploring"""
        
        if self.elements_explored >= self.max_elements:
            print(f"\n🛑 Max elements reached ({self.max_elements})")
            return True
        
        if self.current_depth >= self.max_depth:
            print(f"\n🛑 Max depth reached ({self.max_depth})")
            return True
        
        return False
    
    def _record_interaction(self, element: Dict, result: InteractionResult, analysis: Dict):
        """Record interaction in history"""
        
        self.interaction_history.append({
            'step': self.elements_explored,
            'element': element,
            'result': {
                'success': result.success,
                'pattern': analysis['pattern'].value,
                'state_changed': result.state_hash_before != result.state_hash_after,
                'execution_time': result.execution_time
            },
            'timestamp': datetime.now().isoformat()
        })
    
    def _save_progress(self):
        """Save current progress"""
        progress_file = self.output_dir / f"progress_{self.session_id}.json"
        
        with open(progress_file, 'w') as f:
            json.dump({
                'session_id': self.session_id,
                'elements_explored': self.elements_explored,
                'queue_size': len(self.exploration_queue),
                'history_size': len(self.interaction_history)
            }, f, indent=2)
    
    def _save_final_report(self):
        """Save final exploration report"""
        
        report = {
            'session_id': self.session_id,
            'goal': self.goal,
            'safety_mode': self.safety_mode.value,
            'summary': {
                'total_elements': self.elements_explored,
                'total_interactions': len(self.interaction_history),
                'unique_states': len(self.visited_states)
            },
            'history': self.interaction_history[-50:]  # Last 50
        }
        
        report_file = self.output_dir / f"report_{self.session_id}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n💾 Report saved: {report_file}")


# ═══════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def main():
    """Main entry point"""
    
    # Check for auth file
    if not Path('auth.json').exists():
        print("❌ auth.json not found!")
        print("Create auth.json with your authentication data:")
        print("""
{
  "local_storage": {},
  "session_storage": {},
  "cookies": []
}
        """)
        return
    
    # Configuration
    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        print("❌ OPENAI_API_KEY not set!")
        return
    
    print("\n" + "="*80)
    print("🧠 SEMANTIC WEB EXPLORER")
    print("="*80 + "\n")
    
    # Get user input
    target_url = input("Enter URL to explore: ").strip()
    if not target_url:
        print("❌ No URL provided")
        return
    
    goal = input("Enter exploration goal (e.g., 'Find and test user settings'): ").strip()
    if not goal:
        goal = "General exploration of the application"
    
    print("\nSafety Modes:")
    print("1. EXPLORATION_ONLY - Safe exploration, no destructive actions")
    print("2. FULL_TESTING - Test everything (use with caution)")
    print("3. READ_ONLY - Only navigation, no interactions")
    
    mode_choice = input("\nChoose safety mode (1/2/3) [1]: ").strip() or "1"
    
    safety_mode_map = {
        "1": SafetyMode.EXPLORATION_ONLY,
        "2": SafetyMode.FULL_TESTING,
        "3": SafetyMode.READ_ONLY
    }
    safety_mode = safety_mode_map.get(mode_choice, SafetyMode.EXPLORATION_ONLY)
    
    # Load auth
    with open('auth.json', 'r') as f:
        auth_data = json.load(f)
    
    # Start exploration
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1400, 'height': 900})
        page = await context.new_page()
        
        try:
            # Inject authentication
            print("\n[1/3] 🔑 Injecting authentication...")
            parsed = urlparse(target_url)
            homepage = f"{parsed.scheme}://{parsed.netloc}/"
            
            await page.goto(homepage)
            await page.wait_for_load_state('networkidle')
            
            # localStorage
            for key, value in auth_data.get('local_storage', {}).items():
                try:
                    val = value if isinstance(value, str) else json.dumps(value)
                    await page.evaluate(f"window.localStorage.setItem('{key}', `{val}`)")
                    print(f"  ✓ localStorage: {key}")
                except Exception as e:
                    print(f"  ✗ localStorage: {key} - {e}")
            
            # sessionStorage
            for key, value in auth_data.get('session_storage', {}).items():
                try:
                    val = value if isinstance(value, str) else json.dumps(value)
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', `{val}`)")
                    print(f"  ✓ sessionStorage: {key}")
                except Exception as e:
                    print(f"  ✗ sessionStorage: {key} - {e}")
            
            # Cookies
            cookies = auth_data.get('cookies', [])
            if cookies:
                await context.add_cookies(cookies)
                print(f"  ✓ Cookies: {len(cookies)}")
            
            print("\n[2/3] 🌐 Navigating to target...")
            await page.goto(target_url, wait_until='networkidle', timeout=30000)
            await asyncio.sleep(2)
            
            print(f"\n[3/3] 🚀 Starting exploration...\n")
            
            # Create orchestrator and explore
            orchestrator = Orchestrator(
                openai_api_key=openai_key,
                goal=goal,
                safety_mode=safety_mode,
                max_depth=10,
                max_elements=100
            )
            
            await orchestrator.explore(page)
            
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            input("\n👁️  Browser open. Press Enter to close...")
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())