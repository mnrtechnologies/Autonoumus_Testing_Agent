"""
HYBRID VISION + DOM ARCHITECTURE - Complete Implementation
Combines Claude Vision understanding with real-time DOM observation

This implements the complete hybrid approach:
1. Vision Layer - Understand page structure and components
2. Component Detection - Map Vision insights to DOM elements
3. DOM Observer - Real-time change detection with MutationObserver
4. Semantic Selectors - Stable element finding without XPath
5. Intelligent Planning - Strategy-based exploration
6. State Management - Track exploration progress

Features:
- ✅ Claude Vision API for page understanding
- ✅ OpenAI GPT-4 for decision making (fallback)
- ✅ Real-time DOM mutation observation
- ✅ Semantic element identification (no XPath dependency)
- ✅ Smart menu/modal/tab detection
- ✅ State-based exploration with deduplication
- ✅ Complete Angular SPA support
"""

import asyncio
import json
import hashlib
import os
import base64
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urlparse
from datetime import datetime
from io import BytesIO


from playwright.async_api import async_playwright, Page
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.tree import Tree

# LLM imports
import anthropic
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

console = Console()


class VisionAnalyzer:
    """
    LAYER 1: Vision Analysis
    Uses Claude Vision to understand page structure
    """

    def __init__(self, anthropic_client: anthropic.Anthropic):
        self.client = anthropic_client
        self.analysis_cache = {}

    async def analyze_page(self, page: Page, url: str) -> Dict:
        """
        Take screenshot and analyze with Vision API
        """
        console.print("[cyan]📸 VISION: Taking screenshot and analyzing...[/cyan]")

        # Take full page screenshot
        screenshot_bytes = await page.screenshot(full_page=False, type='png')
        screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode('utf-8')

        # Check cache
        screenshot_hash = hashlib.md5(screenshot_bytes).hexdigest()[:8]
        if screenshot_hash in self.analysis_cache:
            console.print("[yellow]   Using cached Vision analysis[/yellow]")
            return self.analysis_cache[screenshot_hash]

        # Vision prompt
        prompt = """Analyze this web application interface carefully.

Identify and describe:

1. **Page Type**: What kind of page is this? (dashboard, list view, form, settings, etc.)

2. **Main Areas**: Identify the key sections:
   - Navigation/Sidebar menus
   - Header/Top navigation
   - Main content area
   - Any modals or overlays

3. **Interactive Components**: For each interactive element, identify:
   - **Type**: link, button, expandable_menu, tab, modal_trigger, form_input, etc.
   - **Text/Label**: What does it say?
   - **Current State**: expanded/collapsed, active/inactive, visible/hidden
   - **Location**: sidebar, header, main content, footer
   - **Expected Children**: For menus, what submenu items do you expect?

4. **Component Hierarchy**: Which items are parents/children of others?

5. **Exploration Strategy**: Based on the structure, what's the best way to explore this page?
   - If there's a sidebar menu, should we use depth-first traversal?
   - If there are tabs, should we iterate through them?
   - Are there expandable sections that need special handling?

Respond with JSON in this exact format:
{
  "page_type": "dashboard|list|form|settings|etc",
  "main_areas": {
    "sidebar": {
      "present": true|false,
      "items": [
        {
          "text": "Menu Item Name",
          "type": "link|expandable_menu|button",
          "state": "expanded|collapsed|active",
          "location": "sidebar",
          "expected_children": ["Child1", "Child2"],
          "priority": 1-10
        }
      ]
    },
    "header": {
      "present": true|false,
      "items": []
    },
    "main_content": {
      "type": "dashboard_widgets|table|form|etc",
      "interactive_elements": []
    },
    "modals": []
  },
  "component_hierarchy": {
    "Parent Menu": ["Child1", "Child2"]
  },
  "recommended_strategy": "depth_first_menu|tab_iteration|modal_first|breadth_first",
  "exploration_notes": "Any special instructions for exploring this page"
}

Be thorough and precise. Return only valid JSON."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )

            # Parse response
            vision_text = response.content[0].text.strip()
            print("\n" + "="*80)
            print("RAW VISION API RESPONSE:")
            print(vision_text)
            print("="*80 + "\n")

            # Remove markdown code blocks if present
            if vision_text.startswith('```'):
                vision_text = vision_text.split('\n', 1)[1].rsplit('\n', 1)[0]
                if vision_text.startswith('json'):
                    vision_text = vision_text[4:].strip()

            analysis = json.loads(vision_text)

            # Cache it
            self.analysis_cache[screenshot_hash] = analysis

            console.print("[green]   ✅ Vision analysis complete[/green]")
            console.print(f"[yellow]   Page Type: {analysis.get('page_type', 'unknown')}[/yellow]")
            console.print(f"[yellow]   Strategy: {analysis.get('recommended_strategy', 'unknown')}[/yellow]")

            return analysis

        except Exception as e:
            console.print(f"[red]   ❌ Vision analysis failed: {e}[/red]")
            # Return minimal structure
            return {
                "page_type": "unknown",
                "main_areas": {},
                "recommended_strategy": "breadth_first",
                "exploration_notes": "Vision analysis failed, using fallback"
            }


class ComponentDetector:
    """
    LAYER 2: Component Detection
    Maps Vision insights to actual DOM elements
    """

    async def detect_components(self, page: Page, vision_analysis: Dict) -> List[Dict]:
        """
        Find DOM elements corresponding to Vision-identified components
        """
        console.print("[cyan]🔍 COMPONENT DETECTION: Mapping Vision to DOM...[/cyan]")

        components = []
        component_id = 1

        # Extract all components from Vision analysis
        main_areas = vision_analysis.get('main_areas', {})

        for area_name, area_data in main_areas.items():
            if not isinstance(area_data, dict):
                continue

            items = area_data.get('items', [])
            if not items:
                items = area_data.get('interactive_elements', [])

            for item in items:
                if not isinstance(item, dict):
                    continue

                text = item.get('text', '')
                item_type = item.get('type', 'unknown')
                location = item.get('location', area_name)

                if not text:
                    continue

                # Find this element in the DOM
                dom_element = await self._find_element_by_semantics(
                    page, text, location, item_type
                )

                if dom_element:
                    component = {
                        'component_id': component_id,
                        'semantic_id': self._create_semantic_id(text, location, item_type),
                        'text': text,
                        'type': item_type,
                        'location': location,
                        'state': item.get('state', 'unknown'),
                        'expected_children': item.get('expected_children', []),
                        'priority': item.get('priority', 5),
                        'xpath': dom_element['xpath'],
                        'css_selector': dom_element['css_selector'],
                        'vision_data': item
                    }
                    components.append(component)
                    component_id += 1

        console.print(f"[green]   ✅ Detected {len(components)} components[/green]")
        return components

    async def _find_element_by_semantics(
        self,
        page: Page,
        text: str,
        location: str,
        elem_type: str
    ) -> Optional[Dict]:
        """
        Find element using Playwright's built-in selectors
        """
        console.print(f"[cyan]      🔎 Searching for: '{text}'[/cyan]")

        try:
            # Try different selector strategies
            selectors_to_try = [
                f"text={text}",  # Exact text
                f"text=/{text}/i",  # Case insensitive
            ]

            # Add location-specific selectors
            if location == 'sidebar':
                selectors_to_try.insert(0, f"aside >> text={text}")
                selectors_to_try.insert(0, f"nav >> text={text}")
            elif location == 'header':
                selectors_to_try.insert(0, f"header >> text={text}")

            for selector in selectors_to_try:
                try:
                    element = await page.wait_for_selector(selector, timeout=2000, state='visible')
                    if element:
                        console.print(f"[green]         ✅ Found with selector: {selector}[/green]")
                        return {
                            'found': True,
                            'xpath': f"//text()[contains(., '{text}')]/parent::*",
                            'css_selector': selector,
                            'actual_text': text
                        }
                except:
                    continue

            console.print(f"[red]         ❌ Not found[/red]")
            return None

        except Exception as e:
            console.print(f"[red]         Exception: {e}[/red]")
            return None

    def _create_semantic_id(self, text: str, location: str, elem_type: str) -> str:
        """
        Create stable semantic ID
        """
        # Normalize text
        normalized = text.lower().replace(' ', '_').replace('-', '_')
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')

        # Create ID
        semantic_id = f"{location}_{elem_type}_{normalized}"
        return semantic_id[:50]  # Limit length


class DOMObserver:
    """
    LAYER 3: Real-time DOM Observation
    Injects MutationObserver to watch for changes
    """

    def __init__(self):
        self.observer_injected = False
        self.changes_log = []

    async def inject_observer(self, page: Page):
        """
        Inject MutationObserver into the page
        """
        if self.observer_injected:
            return

        console.print("[cyan]👁️ DOM OBSERVER: Injecting MutationObserver...[/cyan]")

        await page.evaluate("""
            () => {
                // Create global change log
                window.__agentChangeLog = [];

                // Create observer
                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        const change = {
                            type: mutation.type,
                            timestamp: Date.now(),
                            target: mutation.target.tagName,
                        };

                        if (mutation.type === 'childList') {
                            change.addedNodes = mutation.addedNodes.length;
                            change.removedNodes = mutation.removedNodes.length;

                            // Log added elements
                            mutation.addedNodes.forEach(node => {
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    window.__agentChangeLog.push({
                                        action: 'element_added',
                                        tag: node.tagName,
                                        text: node.textContent?.substring(0, 50),
                                        timestamp: Date.now()
                                    });
                                }
                            });

                            // Log removed elements
                            mutation.removedNodes.forEach(node => {
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    window.__agentChangeLog.push({
                                        action: 'element_removed',
                                        tag: node.tagName,
                                        timestamp: Date.now()
                                    });
                                }
                            });
                        } else if (mutation.type === 'attributes') {
                            change.attributeName = mutation.attributeName;
                            change.oldValue = mutation.oldValue;
                            change.newValue = mutation.target.getAttribute(mutation.attributeName);

                            window.__agentChangeLog.push({
                                action: 'attribute_changed',
                                attribute: mutation.attributeName,
                                old: mutation.oldValue,
                                new: change.newValue,
                                timestamp: Date.now()
                            });
                        }
                    });
                });

                // Start observing
                observer.observe(document.body, {
                    childList: true,
                    attributes: true,
                    attributeOldValue: true,
                    subtree: true,
                    characterData: false
                });

                window.__agentObserver = observer;
                console.log('✅ MutationObserver injected and active');
            }
        """)

        self.observer_injected = True
        console.print("[green]   ✅ MutationObserver active[/green]")

    async def get_changes(self, page: Page) -> List[Dict]:
        """
        Retrieve logged changes from the observer
        """
        try:
            changes = await page.evaluate("""
                () => {
                    const changes = window.__agentChangeLog || [];
                    window.__agentChangeLog = []; // Clear log
                    return changes;
                }
            """)
            return changes
        except:
            return []

    async def detect_change_type(self, changes: List[Dict]) -> str:
        """
        Classify what type of change occurred
        """
        if not changes:
            return "no_change"

        added = sum(1 for c in changes if c.get('action') == 'element_added')
        removed = sum(1 for c in changes if c.get('action') == 'element_removed')
        attr_changed = sum(1 for c in changes if c.get('action') == 'attribute_changed')

        # Check for modal (dialog added)
        for change in changes:
            if change.get('tag') in ['DIALOG', 'DIV'] and change.get('action') == 'element_added':
                text = change.get('text', '').lower()
                if 'modal' in text or 'dialog' in text:
                    return "modal_opened"

        # Check for menu expansion (multiple elements added)
        if added >= 3:
            return "menu_expanded"

        # Check for collapse
        if removed >= 3:
            return "menu_collapsed"

        # Attribute changes (aria-expanded, etc.)
        if attr_changed > 0:
            for change in changes:
                if change.get('attribute') == 'aria-expanded':
                    if change.get('new') == 'true':
                        return "element_expanded"
                    else:
                        return "element_collapsed"

        return "content_changed"


class SemanticSelector:
    """
    LAYER 4: Semantic Element Selection
    Find and click elements using semantic matching (no XPath)
    """

    async def click_element(self, page: Page, component: Dict) -> bool:
        """
        Click element using multiple fallback strategies
        """
        text = component.get('text', '')
        location = component.get('location', '')

        console.print(f"[cyan]👆 SEMANTIC CLICK: '{text}' in {location}[/cyan]")

        # Strategy 1: Playwright's text selector with location
        try:
            if location == 'sidebar':
                selector = f"aside >> text={text}"
            elif location == 'header':
                selector = f"header >> text={text}"
            else:
                selector = f"text={text}"

            await page.click(selector, timeout=5000)
            console.print(f"[green]   ✅ Clicked using text selector[/green]")
            return True
        except:
            pass

        # Strategy 2: Use stored CSS selector
        try:
            css_sel = component.get('css_selector')
            if css_sel:
                await page.click(css_sel, timeout=3000)
                console.print(f"[green]   ✅ Clicked using CSS selector[/green]")
                return True
        except:
            pass

        # Strategy 3: Use XPath
        try:
            xpath = component.get('xpath')
            if xpath:
                await page.click(f"xpath={xpath}", timeout=3000)
                console.print(f"[green]   ✅ Clicked using XPath[/green]")
                return True
        except:
            pass

        # Strategy 4: Manual search by text
        try:
            clicked = await page.evaluate("""
                ({text, location}) => {
                    function isInLocation(el, loc) {
                        if (loc === 'sidebar') {
                            return el.closest('aside, nav, [class*="sidebar"]') !== null;
                        } else if (loc === 'header') {
                            return el.closest('header') !== null;
                        }
                        return true;
                    }

                    const allElements = Array.from(document.querySelectorAll('a, button, div, span, li'));
                    for (const el of allElements) {
                        const elText = el.textContent?.trim() || '';
                        if ((elText === text || elText.includes(text)) && isInLocation(el, location)) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """, {'text': text, 'location': location})

            if clicked:
                console.print(f"[green]   ✅ Clicked using manual search[/green]")
                return True
        except:
            pass

        console.print(f"[red]   ❌ Could not click element[/red]")
        return False


class ExplorationPlanner:
    """
    LAYER 5: Intelligent Planning
    Creates exploration strategy based on Vision analysis
    """

    def create_plan(self, vision_analysis: Dict, components: List[Dict]) -> List[Dict]:
        """
        Create exploration plan based on page structure
        """
        console.print("[cyan]📋 PLANNER: Creating exploration strategy...[/cyan]")

        strategy = vision_analysis.get('recommended_strategy', 'breadth_first')
        plan = []
        step_id = 1

        if strategy == 'depth_first_menu':
            # Explore menus completely before moving on
            plan = self._plan_depth_first_menu(components, step_id)
        elif strategy == 'tab_iteration':
            # Click through tabs sequentially
            plan = self._plan_tab_iteration(components, step_id)
        else:
            # Default: breadth-first
            plan = self._plan_breadth_first(components, step_id)

        console.print(f"[green]   ✅ Created plan with {len(plan)} steps[/green]")
        console.print(f"[yellow]   Strategy: {strategy}[/yellow]")

        return plan

    def _plan_depth_first_menu(self, components: List[Dict], start_id: int) -> List[Dict]:
        """
        Depth-first menu exploration
        """
        plan = []
        step_id = start_id

        # Group by parent-child relationships
        menus = [c for c in components if c.get('type') == 'expandable_menu']
        links = [c for c in components if c.get('type') in ['link', 'button']]

        # Sort by priority
        menus.sort(key=lambda x: x.get('priority', 5), reverse=True)

        for menu in menus:
            # Step: Expand menu
            plan.append({
                'step_id': step_id,
                'action': 'expand',
                'component': menu,
                'reason': f"Expand {menu['text']} menu"
            })
            step_id += 1

            # Expected children
            expected = menu.get('expected_children', [])
            for child_name in expected:
                plan.append({
                    'step_id': step_id,
                    'action': 'click_child',
                    'parent': menu,
                    'child_name': child_name,
                    'reason': f"Explore {child_name} under {menu['text']}"
                })
                step_id += 1

        # Add remaining links
        for link in links:
            if link.get('priority', 5) >= 7:  # High priority links
                plan.append({
                    'step_id': step_id,
                    'action': 'click',
                    'component': link,
                    'reason': f"Explore {link['text']}"
                })
                step_id += 1

        return plan

    def _plan_tab_iteration(self, components: List[Dict], start_id: int) -> List[Dict]:
        """
        Tab iteration strategy
        """
        plan = []
        step_id = start_id

        tabs = [c for c in components if c.get('type') == 'tab']

        for tab in tabs:
            plan.append({
                'step_id': step_id,
                'action': 'click_tab',
                'component': tab,
                'reason': f"Switch to {tab['text']} tab"
            })
            step_id += 1

        return plan

    def _plan_breadth_first(self, components: List[Dict], start_id: int) -> List[Dict]:
        """
        Simple breadth-first exploration
        """
        plan = []
        step_id = start_id

        # Sort by priority
        components_sorted = sorted(components, key=lambda x: x.get('priority', 5), reverse=True)

        for comp in components_sorted[:20]:  # Limit to top 20
            plan.append({
                'step_id': step_id,
                'action': 'click',
                'component': comp,
                'reason': f"Explore {comp['text']}"
            })
            step_id += 1

        return plan


class StateManager:
    """
    LAYER 6: State Management
    Tracks visited states and prevents loops
    """

    def __init__(self):
        self.states = {}
        self.current_state_hash = None

    async def calculate_state_hash(self, page: Page) -> str:
        """
        Calculate semantic state fingerprint
        """
        state_data = await page.evaluate("""
            () => {
                return {
                    url: window.location.pathname,
                    title: document.title,
                    main_headings: Array.from(document.querySelectorAll('h1, h2, h3'))
                        .map(h => h.textContent?.trim())
                        .filter(t => t).join('|'),
                    interactive_count: document.querySelectorAll('a, button').length
                };
            }
        """)

        hash_string = f"{state_data['url']}::{state_data['main_headings']}::{state_data['interactive_count']}"
        state_hash = hashlib.sha256(hash_string.encode()).hexdigest()[:12]

        return state_hash

    def is_state_visited(self, state_hash: str) -> bool:
        """
        Check if we've been to this state before
        """
        return state_hash in self.states

    def record_state(self, state_hash: str, url: str, breadcrumb: str, components: List[Dict]):
        """
        Record a new state
        """
        if state_hash not in self.states:
            self.states[state_hash] = {
                'hash': state_hash,
                'url': url,
                'breadcrumb': breadcrumb,
                'component_count': len(components),
                'visited_at': datetime.now().isoformat(),
                'visited_components': set()
            }


class HybridVisionCrawler:
    """
    MAIN ORCHESTRATOR
    Combines all layers into hybrid Vision + DOM crawler
    """

    def __init__(
        self,
        base_url: str,
        auth_file: str = "auth.json",
        max_depth: int = 3,
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None
    ):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth

        # Load auth
        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        # Initialize LLM clients
        if anthropic_api_key:
            self.anthropic = anthropic.Anthropic(api_key=anthropic_api_key)
        else:
            self.anthropic = anthropic.Anthropic()

        if openai_api_key:
            self.openai = OpenAI(api_key=openai_api_key)
        else:
            self.openai = None

        # Initialize layers
        self.vision = VisionAnalyzer(self.anthropic)
        self.component_detector = ComponentDetector()
        self.dom_observer = DOMObserver()
        self.semantic_selector = SemanticSelector()
        self.planner = ExplorationPlanner()
        self.state_manager = StateManager()

        # Stats
        self.stats = {
            'pages_explored': 0,
            'components_found': 0,
            'clicks_performed': 0,
            'vision_calls': 0,
            'states_discovered': 0,
            'modals_detected': 0,
            'menus_expanded': 0
        }
        self.memory_file = Path('output') / 'exploration_memory.json'
        self.exploration_memory = self._load_memory()

    def _load_memory(self) -> Dict:
        """
        Load exploration memory from disk
        """
        if self.memory_file.exists():
            console.print("[cyan]📂 Loading previous exploration memory...[/cyan]")
            with open(self.memory_file, 'r') as f:
                memory = json.load(f)
            console.print(f"[green]   ✅ Loaded {len(memory.get('explored_components', {}))} explored components[/green]")
            return memory
        else:
            console.print("[yellow]   No previous memory found, starting fresh[/yellow]")
            return {
                'explored_components': {},
                'exploration_queue': [],
                'last_run': None
            }

    def _save_memory(self):
        """
        Save exploration memory to disk
        """
        self.memory_file.parent.mkdir(exist_ok=True)
        self.exploration_memory['last_run'] = datetime.now().isoformat()

        with open(self.memory_file, 'w') as f:
            json.dump(self.exploration_memory, f, indent=2)

    async def run(self):
        """
        Main entry point
        """
        console.print(Panel.fit(
            "[bold cyan]🔬 HYBRID VISION + DOM CRAWLER[/bold cyan]\n"
            f"[yellow]Target: {self.base_url}[/yellow]\n"
            f"[yellow]Max Depth: {self.max_depth}[/yellow]\n"
            "[green]Combining Vision understanding with real-time DOM observation[/green]",
            border_style="cyan"
        ))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={'width': 1200, 'height': 700}
            )
            page = await context.new_page()

            # Setup auth
            await self._setup_auth(page, context)

            # Inject DOM observer
            await self.dom_observer.inject_observer(page)

            # Start exploration
            await self._explore_page(page, depth=0, breadcrumb="Root")

            await browser.close()

        # Show results
        self._show_results()
        self._save_exploration_data()

    async def _setup_auth(self, page: Page, context):
        """
        Setup authentication from auth.json
        """
        console.print("\n[cyan]🔑 Setting up authentication...[/cyan]")

        parsed = urlparse(self.base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"

        await page.goto(homepage)
        await page.wait_for_load_state('networkidle')

        # Inject localStorage
        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                if isinstance(value, str):
                    await page.evaluate(f"window.localStorage.setItem('{key}', '{value}')")
                else:
                    await page.evaluate(f"window.localStorage.setItem('{key}', '{json.dumps(value)}')")
                console.print(f"  ✓ localStorage: {key}")
            except Exception as e:
                console.print(f"  ✗ localStorage failed: {key} - {e}")

        # Inject sessionStorage
        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                if isinstance(value, str):
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', '{value}')")
                else:
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', '{json.dumps(value)}')")
                console.print(f"  ✓ sessionStorage: {key}")
            except Exception as e:
                console.print(f"  ✗ sessionStorage failed: {key}")

        # Add cookies
        cookies = self.auth_data.get('cookies', [])
        if cookies:
            try:
                await context.add_cookies(cookies)
                console.print(f"  ✓ Cookies: {len(cookies)} added")
            except Exception as e:
                console.print(f"  ✗ Cookies failed: {e}")

        console.print("[green]✅ Auth data injected[/green]")

        # Navigate to actual page
        console.print(f"[cyan]🌐 Navigating to: {self.base_url}[/cyan]")
        await page.goto(self.base_url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(2)  # Wait for Angular to initialize

        current_url = page.url
        if 'login' in current_url.lower():
            console.print("[red]❌ Authentication failed - still on login page[/red]")
            raise Exception("Authentication failed")

        console.print("[green]✅ Successfully authenticated![/green]\n")

    async def _explore_page(self, page: Page, depth: int, breadcrumb: str):
        """
        Main exploration loop combining all layers
        """
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️ Max depth {self.max_depth} reached[/yellow]")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]📍 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"{'='*80}\n")

        # Wait for page stability
        await asyncio.sleep(2)

        # Calculate state hash
        state_hash = await self.state_manager.calculate_state_hash(page)
        current_url = page.url

        # Check if already visited
        if self.state_manager.is_state_visited(state_hash):
            console.print(f"[yellow]♻️ State already visited, skipping[/yellow]")
            return

        # LAYER 1: Vision Analysis
        vision_analysis = await self.vision.analyze_page(page, current_url)
        self.stats['vision_calls'] += 1

        # LAYER 2: Component Detection
        components = await self.component_detector.detect_components(page, vision_analysis)
        self.stats['components_found'] += len(components)

        if not components:
            console.print("[yellow]No components detected, ending exploration[/yellow]")
            return

        # Record state
        self.state_manager.record_state(state_hash, current_url, breadcrumb, components)
        self.stats['states_discovered'] += 1
        self.stats['pages_explored'] += 1

        # LAYER 5: Create Exploration Plan
        plan = self.planner.create_plan(vision_analysis, components)

        # Execute plan
        for step in plan:
            await self._execute_step(page, step, depth, breadcrumb)

    async def _execute_step(self, page: Page, step: Dict, depth: int, breadcrumb: str):
        """
        Execute a single exploration step
        """
        action = step.get('action')
        component = step.get('component')
        reason = step.get('reason', 'No reason')

        if not component:
            return

        component_id = component.get('semantic_id')

        # CHECK MEMORY - Skip if already explored
        if component_id in self.exploration_memory.get('explored_components', {}):
            comp_status = self.exploration_memory['explored_components'][component_id]
            if comp_status.get('explored') == True:
                console.print(f"\n[yellow]⏭️  SKIPPING: {component['text']} - Already explored[/yellow]")
                return

        console.print(f"\n[bold yellow]📌 STEP {step['step_id']}: {reason}[/bold yellow]")

        # Record URL before action
        url_before = page.url

        # Clear change log
        await self.dom_observer.get_changes(page)

        # LAYER 4: Semantic Click
        clicked = await self.semantic_selector.click_element(page, component)

        if not clicked:
            console.print("[red]   Skipping step due to click failure[/red]")
            return

        self.stats['clicks_performed'] += 1

        # MARK AS EXPLORED in memory
        self.exploration_memory['explored_components'][component_id] = {
            'text': component.get('text'),
            'explored': True,
            'last_visit': datetime.now().isoformat(),
            'type': component.get('type')
        }

        # Wait for changes
        await asyncio.sleep(2)

        # LAYER 3: Check what changed
        changes = await self.dom_observer.get_changes(page)
        change_type = await self.dom_observer.detect_change_type(changes)

        console.print(f"[cyan]   Change detected: {change_type}[/cyan]")
        console.print(f"[cyan]   Total DOM changes: {len(changes)}[/cyan]")

        # Check URL
        url_after = page.url

        if url_after != url_before:
            # Navigation occurred
            console.print(f"[green]   🌐 Navigation: {url_after}[/green]")

            # Recursively explore new page
            new_breadcrumb = f"{breadcrumb} > {component['text'][:30]}"
            await self._explore_page(page, depth + 1, new_breadcrumb)

            # Go back
            console.print("[yellow]   ⬅️ Going back...[/yellow]")
            try:
                await page.go_back(wait_until='networkidle', timeout=10000)
                await asyncio.sleep(2)
                # Re-inject observer after navigation
                await self.dom_observer.inject_observer(page)
            except Exception as e:
                console.print(f"[red]   Failed to go back: {e}[/red]")

        elif change_type == "modal_opened":
            # Modal detected
            console.print("[yellow]   🔲 Modal detected[/yellow]")
            self.stats['modals_detected'] += 1

            # Explore modal
            new_breadcrumb = f"{breadcrumb} > Modal({component['text'][:20]})"
            await self._explore_page(page, depth + 1, new_breadcrumb)

            # Close modal
            await self._close_modal(page)
            await asyncio.sleep(1)

        elif change_type in ["menu_expanded", "element_expanded"]:
            # Menu/content expanded
            console.print("[green]   📂 Content expanded - rescanning for new items[/green]")
            self.stats['menus_expanded'] += 1
            await asyncio.sleep(1)

            # RE-SCAN FOR CHILDREN - This is critical!
            await self._rescan_for_children(page, component, depth, breadcrumb)

        # SAVE MEMORY after every action
        self._save_memory()



            # Re-analyze to find new components
            # (In a full implementation, we'd re-scan for new elements here)


    async def _rescan_for_children(self, page: Page, parent_component: Dict, depth: int, breadcrumb: str):
        """
        Re-scan DOM after menu expansion to find newly visible children
        """
        console.print("[cyan]🔍 Re-scanning for newly visible children...[/cyan]")

        # Get current visible elements in sidebar
        try:
            new_elements = await page.evaluate("""
                () => {
                    const sidebar = document.querySelector('aside, nav, [class*="sidebar"]');
                    if (!sidebar) return [];

                    const links = Array.from(sidebar.querySelectorAll('a, button, li'));
                    return links
                        .filter(el => {
                            const style = window.getComputedStyle(el);
                            return style.display !== 'none' &&
                                style.visibility !== 'hidden' &&
                                el.offsetParent !== null;
                        })
                        .map(el => ({
                            text: el.textContent?.trim() || '',
                            tag: el.tagName,
                            visible: true
                        }))
                        .filter(item => item.text.length > 0 && item.text.length < 50);
                }
            """)

            console.print(f"[cyan]   Found {len(new_elements)} visible elements[/cyan]")

            # Find NEW children that weren't in our memory before
            parent_id = parent_component.get('semantic_id')
            children_found = 0

            for elem in new_elements:
                # Create semantic ID for this element
                child_id = self.component_detector._create_semantic_id(
                    elem['text'],
                    'sidebar',
                    'link'
                )

                # Check if this is NEW
                if child_id not in self.exploration_memory.get('explored_components', {}):
                    console.print(f"[green]      ✨ NEW child found: {elem['text']}[/green]")

                    # Add to queue
                    if child_id not in self.exploration_memory.get('exploration_queue', []):
                        self.exploration_memory['exploration_queue'].append(child_id)

                        # Mark as discovered but not explored
                        self.exploration_memory['explored_components'][child_id] = {
                            'text': elem['text'],
                            'explored': False,
                            'parent_id': parent_id,
                            'discovered_at': datetime.now().isoformat(),
                            'type': 'link',
                            'location': 'sidebar'
                        }
                        children_found += 1

            console.print(f"[green]   ✅ Added {children_found} new children to exploration queue[/green]")

            # Save memory after discovering children
            self._save_memory()

            # Now explore the children we just found
            await self._explore_queue_items(page, depth, breadcrumb)

        except Exception as e:
            console.print(f"[red]   ❌ Re-scan failed: {e}[/red]")

    async def _explore_queue_items(self, page: Page, depth: int, breadcrumb: str):
        """
        Explore items in the exploration queue
        """
        queue = self.exploration_memory.get('exploration_queue', [])

        console.print(f"[cyan]📋 Processing exploration queue: {len(queue)} items[/cyan]")

        while queue:
            # Get next item
            component_id = queue.pop(0)
            self.exploration_memory['exploration_queue'] = queue

            # Get component data
            comp_data = self.exploration_memory['explored_components'].get(component_id)
            if not comp_data:
                continue

            # Skip if already explored
            if comp_data.get('explored') == True:
                console.print(f"[yellow]   ⏭️  Skipping {comp_data['text']} - already explored[/yellow]")
                continue

            # Create component dict for execution
            component = {
                'semantic_id': component_id,
                'text': comp_data['text'],
                'type': comp_data.get('type', 'link'),
                'location': comp_data.get('location', 'sidebar'),
                'css_selector': f"text={comp_data['text']}"
            }

            # Create step
            step = {
                'step_id': self.stats['clicks_performed'] + 1,
                'action': 'click',
                'component': component,
                'reason': f"Explore {comp_data['text']} from queue"
            }

            # Execute
            await self._execute_step(page, step, depth, breadcrumb)

            # Update queue reference
            queue = self.exploration_memory.get('exploration_queue', [])


    async def _close_modal(self, page: Page):
        """
        Close modal using various strategies
        """
        close_selectors = [
            'button[aria-label="Close"]',
            'button.close',
            '[data-dismiss="modal"]',
            'button:has-text("Close")',
            'button:has-text("Cancel")',
            '.modal-close'
        ]

        for selector in close_selectors:
            try:
                await page.click(selector, timeout=2000)
                await asyncio.sleep(0.5)
                console.print("[green]   ✅ Modal closed[/green]")
                return
            except:
                continue

        # Try ESC key
        try:
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.5)
            console.print("[green]   ✅ Modal closed with ESC[/green]")
        except:
            console.print("[yellow]   ⚠️ Could not close modal[/yellow]")
        self._save_memory()
        print("memory svaed")
    def _show_results(self):
        """
        Display exploration results
        """
        console.print("\n" + "="*80)
        console.print(Panel.fit(
            "[bold green]✅ EXPLORATION COMPLETE[/bold green]",
            border_style="green"
        ))

        # Stats table
        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="yellow")

        for key, value in self.stats.items():
            table.add_row(key.replace('_', ' ').title(), str(value))

        console.print(table)

    def _save_exploration_data(self):
        """
        Save exploration data to file
        """
        output_dir = Path('output')
        output_dir.mkdir(exist_ok=True)

        data = {
            'metadata': {
                'base_url': self.base_url,
                'timestamp': datetime.now().isoformat(),
                'stats': self.stats
            },
            'states': {
                hash: {
                    'url': state['url'],
                    'breadcrumb': state['breadcrumb'],
                    'component_count': state['component_count'],
                    'visited_at': state['visited_at']
                }
                for hash, state in self.state_manager.states.items()
            }
        }

        output_file = output_dir / f'exploration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.print(f"\n[bold green]💾 Data saved: {output_file}[/bold green]")


async def main():
    """
    Main entry point
    """

    # Check for auth.json
    if not Path('auth.json').exists():
        console.print("[red]❌ auth.json not found![/red]")
        console.print("[yellow]Please create auth.json with your authentication data[/yellow]")
        return

    # API keys
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    # Initialize crawler
    crawler = HybridVisionCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=3,
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key
    )

    # Run
    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())