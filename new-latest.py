"""
TWO-TIER PLANNING ARCHITECTURE - OpenAI GPT-4 Vision Implementation
Discovery First, Execution Second

This implements the strategic two-tier approach:
TIER 1: Assumption Plan (The Scout) - Discovers hidden features
TIER 2: Main Action Plan (The Worker) - Tests discovered features

Architecture:
1. Vision Layer - GPT-4 Vision understands page structure
2. Component Classification - Separates "containers" from "features"
3. Assumption Planning - Creates discovery hypotheses
4. Discovery Execution - Validates assumptions, expands menus/modals
5. Main Action Planning - Builds comprehensive test plan
6. Testing Execution - Systematic feature testing

Features:
- ✅ OpenAI GPT-4 Vision for page understanding
- ✅ Two-tier planning (Discovery → Testing)
- ✅ Smart container detection (menus, modals, tabs)
- ✅ Real-time DOM mutation observation
- ✅ Semantic element identification
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

# OpenAI imports
from openai import OpenAI

from dotenv import load_dotenv
import os

load_dotenv()

console = Console()


class GPTVisionAnalyzer:
    """
    LAYER 1: Vision Analysis with GPT-4 Vision
    Understands page structure and classifies components
    """

    def __init__(self, openai_client: OpenAI):
        self.client = openai_client
        self.analysis_cache = {}

    async def analyze_page(self, page: Page, url: str) -> Dict:
        """
        Take screenshot and analyze with GPT-4 Vision API
        Returns enhanced analysis with component classification
        """
        console.print("[cyan]📸 VISION: Taking screenshot and analyzing with GPT-4...[/cyan]")

        # Ensure we are at the top before capturing
        await page.evaluate("window.scrollTo(0, 0)")
        # Take full page screenshot
        screenshot_bytes = await page.screenshot(full_page=True, type='png')

        # Save the screenshot to a file so you can open it and check the height
        with open("debug_screenshot.png", "wb") as f:
            f.write(screenshot_bytes)
            
        screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode('utf-8')

        # Check cache
        screenshot_hash = hashlib.md5(screenshot_bytes).hexdigest()[:8]
        if screenshot_hash in self.analysis_cache:
            console.print("[yellow]   Using cached Vision analysis[/yellow]")
            return self.analysis_cache[screenshot_hash]

        # Enhanced Vision prompt for Two-Tier Planning
        # Enhanced Vision prompt for Two-Tier Planning
        prompt = """You are a precision UI analysis agent. Your mission is to extract the structure of a web application for an automated testing crawler.

        **CRITICAL RULE: ZERO HALLUCINATION**
        - Do NOT invent elements based on what a dashboard "should" have.
        - Only list what is physically, visually present in the provided screenshot.
        - Transcribe text EXACTLY as shown. Do NOT translate (e.g., if you see "Identitas", write "Identitas", not "Identity").

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        📦 CATEGORY 1: CONTAINERS (Scouting Targets)
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        A CONTAINER is any UI element that hides/reveals other content.
        - Visual Indicators: Look for ">", "▼", "▶", "chevron", or horizontal tab bars.
        - Includes: Sidebar menus, dropdowns, accordions, and **Horizontal Tab Groups** (e.g., "Gambar", "Video").
        - State: 
            * "expanded": If child items are currently visible below/inside it.
            * "collapsed": If children are hidden.
        - Expected Children: If expanded, you MUST list every visible sub-item text exactly as shown.

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        🎯 CATEGORY 2: FEATURES (Action Targets)
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        A FEATURE is a standalone interactive element that performs an action.
        - Includes: Buttons ("Save", "Tambah"), direct links, and form inputs.
        - **PRIORITY LOGIC:** * "main" content features MUST have high priority (8-10).
            * "sidebar" navigation links MUST have lower priority (1-5). 
            * *Reasoning: The agent must test the current page functionality before navigating away.*

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        🔍 SYSTEMATIC SCANNING PROCESS
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        STEP 1: Scan for TABS and SEGMENTED CONTROLS in the main area. Mark these as CONTAINERS.
        STEP 2: Scan the SIDEBAR from top to bottom. Identify every item with an expansion arrow.
        STEP 3: Identify direct ACTION BUTTONS in the header and main content area.
        STEP 4: Verify that "main" features are ranked higher in priority than "sidebar" links.

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        📋 OUTPUT FORMAT
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        Return valid JSON in this EXACT format:

        {
        "page_type": "dashboard|list|form|settings|gallery",
        "layout": {
            "has_sidebar": true|false,
            "has_header": true|false
        },
        "containers": [
            {
            "text": "EXACT text from screen",
            "type": "expandable_menu|tabs|dropdown",
            "state": "collapsed|expanded",
            "location": "sidebar|header|main",
            "expected_children": ["Child Text 1", "Child Text 2"],
            "discovery_priority": 10,
            "expansion_indicator": "describe icon: '> arrow', 'tab underline', etc"
            }
        ],
        "features": [
            {
            "text": "EXACT text from screen",
            "type": "button|link|form_field",
            "location": "sidebar|header|main",
            "test_priority": 1-10,
            "expected_behavior": "what happens when clicked"
            }
        ],
        "discovery_strategy": {
            "recommended_order": ["Container to explore first", "Container second"],
            "reasoning": "why this order makes sense"
        }
        }

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ✅ QUALITY CHECKLIST
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        □ Did I find the horizontal tabs (if any)?
        □ Are "main" features prioritized higher than "sidebar" links?
        □ Is every piece of text transcribed exactly (no translations)?
        □ Did I avoid listing items that aren't actually visible?

        Analyze the screenshot and return JSON only."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4000
            )

            # Parse response
            vision_text = response.choices[0].message.content.strip()

            console.print("\n" + "="*80)
            console.print("RAW GPT-4 VISION RESPONSE:")
            console.print(vision_text)
            console.print("="*80 + "\n")

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
            console.print(f"[yellow]   Containers found: {len(analysis.get('containers', []))}[/yellow]")
            console.print(f"[yellow]   Features found: {len(analysis.get('features', []))}[/yellow]")

            return analysis

        except Exception as e:
            console.print(f"[red]   ❌ Vision analysis failed: {e}[/red]")
            import traceback
            console.print(f"[red]   {traceback.format_exc()}[/red]")
            # Return minimal structure
            return {
                "page_type": "unknown",
                "layout": {},
                "containers": [],
                "features": [],
                "discovery_strategy": {"recommended_order": [], "reasoning": "Vision failed"}
            }


class ComponentDetector:
    """
    LAYER 2: Component Detection
    Maps Vision insights to actual DOM elements
    """

    async def detect_containers(self, page: Page, vision_containers: List[Dict]) -> List[Dict]:
        """
        Find DOM elements for containers (expandable menus, modals, etc.)
        """
        console.print("[cyan]🔍 CONTAINER DETECTION: Mapping containers to DOM...[/cyan]")

        containers = []
        container_id = 1

        for container_data in vision_containers:
            text = container_data.get('text', '')
            container_type = container_data.get('type', 'unknown')
            location = container_data.get('location', 'unknown')

            if not text:
                continue

            # Find this element in the DOM
            dom_element = await self._find_element_by_semantics(
                page, text, location, container_type
            )

            if dom_element:
                container = {
                    'container_id': container_id,
                    'semantic_id': self._create_semantic_id(text, location, container_type),
                    'text': text,
                    'type': container_type,
                    'location': location,
                    'state': container_data.get('state', 'unknown'),
                    'expected_children': container_data.get('expected_children', []),
                    'discovery_priority': container_data.get('discovery_priority', 5),
                    'xpath': dom_element['xpath'],
                    'css_selector': dom_element['css_selector'],
                    'vision_data': container_data
                }
                containers.append(container)
                container_id += 1

        console.print(f"[green]   ✅ Detected {len(containers)} containers[/green]")
        return containers

    async def detect_features(self, page: Page, vision_features: List[Dict]) -> List[Dict]:
        """
        Find DOM elements for features (buttons, links, etc.)
        """
        console.print("[cyan]🔍 FEATURE DETECTION: Mapping features to DOM...[/cyan]")

        features = []
        feature_id = 1

        for feature_data in vision_features:
            text = feature_data.get('text', '')
            feature_type = feature_data.get('type', 'unknown')
            location = feature_data.get('location', 'unknown')

            if not text:
                continue

            # Find this element in the DOM
            dom_element = await self._find_element_by_semantics(
                page, text, location, feature_type
            )

            if dom_element:
                feature = {
                    'feature_id': feature_id,
                    'semantic_id': self._create_semantic_id(text, location, feature_type),
                    'text': text,
                    'type': feature_type,
                    'location': location,
                    'test_priority': feature_data.get('test_priority', 5),
                    'expected_behavior': feature_data.get('expected_behavior', ''),
                    'xpath': dom_element['xpath'],
                    'css_selector': dom_element['css_selector'],
                    'vision_data': feature_data
                }
                features.append(feature)
                feature_id += 1

        console.print(f"[green]   ✅ Detected {len(features)} features[/green]")
        return features

    async def _find_element_by_semantics(self, page: Page, text: str, location: str, elem_type: str) -> Optional[Dict]:
        # 1. Clean the text (Remove the > arrows GPT-4 Vision sees)
        clean_text = text.replace('>', '').replace('▼', '').replace('▶', '').strip()
        console.print(f"[cyan]      🔎 Searching for: '{clean_text}'[/cyan]")

        try:
            # 2. Aggressive Selector List (from specific to fuzzy)
            selectors_to_try = [
                f"text='{clean_text}'",                # Exact text match
                f"text=/{clean_text}/i",               # Case-insensitive fuzzy
                f"button:has-text('{clean_text}')",    # If Vision thinks it's a button
                f"a:has-text('{clean_text}')",         # If Vision thinks it's a link
                f".menu-item:has-text('{clean_text}')",# Common Sidebar class
                f"li:has-text('{clean_text}')"         # Common list item wrapper
            ]

            # 3. Try each selector with a small wait
            for selector in selectors_to_try:
                try:
                    # Use locator().first to avoid "strict mode" errors if multiple match
                    element = page.locator(selector).first
                    
                    # Ensure it's actually in the DOM and potentially visible
                    if await element.count() > 0:
                        # Force scroll into view so we are 100% sure it's there
                        await element.scroll_into_view_if_needed()
                        
                        return {
                            'found': True,
                            'xpath': f"//*[contains(text(), '{clean_text}')]",
                            'css_selector': selector,
                            'actual_text': clean_text
                        }
                except:
                    continue

            console.print(f"[red]         ❌ Not found in DOM[/red]")
            return None
        except Exception:
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
        clean_text = text.replace('>', '').replace('▼', '').replace('▶', '').strip()
        location = component.get('location', '')

        console.print(f"[cyan]👆 SEMANTIC CLICK: '{text}' in {location}[/cyan]")

        # Strategy 1: Playwright's text selector with location
        try:
            for t in [clean_text, text]:
                if location == 'sidebar':
                    selector = f"aside >> text={text}"
                elif location == 'header':
                    selector = f"header >> text={text}"
                else:
                    selector = f"text={text}"
                loc = page.locator(selector).first
                await page.locator(selector).scroll_into_view_if_needed()
                await page.click(selector, timeout=5000)
                console.print(f"[green]   ✅ Clicked using text selector[/green]")
                return True
        except:
            pass

        # Strategy 2: Use stored CSS selector
        try:
            css_sel = component.get('css_selector')
            if css_sel:
                loc = page.locator(css_sel).first
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
                ({text, clean_text, location}) => {
                    const targets = [text, clean_text];
                    const allElements = Array.from(document.querySelectorAll('a, button, div, span, li, p'));
                    
                    for (const t of targets) {
                        for (const el of allElements) {
                            if (el.textContent?.trim().includes(t)) {
                                el.scrollIntoView({block: "center"});
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """, {'text': text, 'clean_text': clean_text, 'location': location})
            if clicked:
                console.print(f"[green]   ✅ Clicked using manual search[/green]")
                return True
        except:
            pass

        console.print(f"[red]   ❌ Could not click element[/red]")
        return False
    
    async def handle_inputs(self, page: Page):
            """Find and fill all visible input fields to unlock more of the site"""
            inputs = await page.locator('input:visible, textarea:visible').all()
            for i in inputs:
                try:
                    # Use a generic test value or AI-generated value
                    await i.fill("Test Exploration")
                    await i.press("Enter")
                except: continue


class TwoTierPlanner:
    """
    LAYER 5: Two-Tier Planning System
    Creates separate Discovery and Testing plans
    """

    def __init__(self):
        self.assumption_plan = []
        self.main_action_plan = []

    def create_assumption_plan(self, containers: List[Dict], vision_strategy: Dict) -> List[Dict]:
        """
        TIER 1: Create Assumption Plan (Discovery Phase)
        This plan focuses on expanding/opening containers to reveal hidden features
        """
        console.print("[cyan]📋 TIER 1 PLANNER: Creating Assumption Plan (Discovery)...[/cyan]")

        plan = []
        step_id = 1

        # Sort containers by discovery priority
        containers_sorted = sorted(
            containers,
            key=lambda x: x.get('discovery_priority', 5),
            reverse=True
        )

        # Follow recommended order from Vision if available
        recommended_order = vision_strategy.get('recommended_order', [])

        if recommended_order:
            # Reorder based on Vision's recommendation
            ordered_containers = []
            for rec_name in recommended_order:
                for container in containers_sorted:
                    if rec_name.lower() in container['text'].lower():
                        ordered_containers.append(container)
                        break

            # Add any remaining containers
            for container in containers_sorted:
                if container not in ordered_containers:
                    ordered_containers.append(container)

            containers_sorted = ordered_containers

        # Create discovery steps
        for container in containers_sorted:
            assumption = {
                'step_id': step_id,
                'tier': 'assumption',
                'action': 'discover',
                'hypothesis': f"{container['text']} contains hidden features",
                'container': container,
                'expected_children': container.get('expected_children', []),
                'priority': container.get('discovery_priority', 5),
                'reason': f"Expand {container['text']} to discover sub-items"
            }
            plan.append(assumption)
            step_id += 1

        self.assumption_plan = plan

        console.print(f"[green]   ✅ Assumption Plan created with {len(plan)} discovery steps[/green]")
        console.print(f"[yellow]   Strategy: {vision_strategy.get('reasoning', 'Sequential discovery')}[/yellow]")

        return plan

    def create_main_action_plan(self, features: List[Dict]) -> List[Dict]:
        """
        TIER 2: Create Main Action Plan (Testing Phase)
        This plan focuses on testing discovered features
        """
        console.print("[cyan]📋 TIER 2 PLANNER: Creating Main Action Plan (Testing)...[/cyan]")

        plan = []
        step_id = 1

        # Sort features by test priority
        features_sorted = sorted(
            features,
            key=lambda x: x.get('test_priority', 5),
            reverse=True
        )

        for feature in features_sorted:
            action = {
                'step_id': step_id,
                'tier': 'main_action',
                'action': 'test',
                'feature': feature,
                'test_type': self._determine_test_type(feature),
                'priority': feature.get('test_priority', 5),
                'reason': f"Test {feature['text']} functionality"
            }
            plan.append(action)
            step_id += 1

        self.main_action_plan = plan

        console.print(f"[green]   ✅ Main Action Plan created with {len(plan)} test steps[/green]")

        return plan

    def _determine_test_type(self, feature: Dict) -> str:
        """
        Determine what type of test to perform on this feature
        """
        feature_type = feature.get('type', '').lower()

        if 'button' in feature_type:
            return 'functional_test'
        elif 'link' in feature_type:
            return 'navigation_test'
        elif 'form' in feature_type or 'input' in feature_type:
            return 'input_validation'
        elif 'widget' in feature_type:
            return 'ui_validation'
        else:
            return 'general_test'

    def add_discovered_features_to_main_plan(self, new_features: List[Dict]):
        """
        Add newly discovered features to the Main Action Plan
        Called after Assumption Plan execution discovers new items
        """
        console.print(f"[cyan]➕ Adding {len(new_features)} discovered features to Main Action Plan...[/cyan]")

        next_step_id = len(self.main_action_plan) + 1

        for feature in new_features:
            action = {
                'step_id': next_step_id,
                'tier': 'main_action',
                'action': 'test',
                'feature': feature,
                'test_type': self._determine_test_type(feature),
                'priority': feature.get('test_priority', 5),
                'reason': f"Test {feature['text']} (discovered during exploration)",
                'discovered': True
            }
            self.main_action_plan.append(action)
            next_step_id += 1

        # Re-sort by priority
        self.main_action_plan.sort(key=lambda x: x.get('priority', 5), reverse=True)

        # Re-number steps
        for idx, action in enumerate(self.main_action_plan, 1):
            action['step_id'] = idx

        console.print(f"[green]   ✅ Main Action Plan now has {len(self.main_action_plan)} total steps[/green]")


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

    def record_state(self, state_hash: str, url: str, breadcrumb: str, containers: List[Dict], features: List[Dict]):
        """
        Record a new state
        """
        if state_hash not in self.states:
            self.states[state_hash] = {
                'hash': state_hash,
                'url': url,
                'breadcrumb': breadcrumb,
                'container_count': len(containers),
                'feature_count': len(features),
                'visited_at': datetime.now().isoformat()
            }


class TwoTierCrawler:
    """
    MAIN ORCHESTRATOR
    Implements Two-Tier Planning: Discovery First, Testing Second
    """

    def __init__(
        self,
        base_url: str,
        auth_file: str = "auth.json",
        max_depth: int = 2,
        openai_api_key: Optional[str] = None
    ):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth

        # Load auth
        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        # Initialize OpenAI client
        if openai_api_key:
            self.openai = OpenAI(api_key="OPENAI_API_KEY")
        else:
            self.openai = OpenAI()

        # Initialize layers
        self.vision = GPTVisionAnalyzer(self.openai)
        self.component_detector = ComponentDetector()
        self.dom_observer = DOMObserver()
        self.semantic_selector = SemanticSelector()
        self.planner = TwoTierPlanner()
        self.state_manager = StateManager()

        # Stats
        self.stats = {
            'pages_explored': 0,
            'containers_found': 0,
            'features_found': 0,
            'discovery_clicks': 0,
            'test_clicks': 0,
            'vision_calls': 0,
            'states_discovered': 0,
            'modals_detected': 0,
            'menus_expanded': 0,
            'features_tested': 0
        }

        self.memory_file = Path('output') / 'two_tier_memory.json'
        self.exploration_memory = self._load_memory()

    def _load_memory(self) -> Dict:
        """
        Load exploration memory from disk
        """
        if self.memory_file.exists():
            console.print("[cyan]📂 Loading previous exploration memory...[/cyan]")
            with open(self.memory_file, 'r') as f:
                memory = json.load(f)
            console.print(f"[green]   ✅ Loaded memory[/green]")
            return memory
        else:
            console.print("[yellow]   No previous memory found, starting fresh[/yellow]")
            return {
                'explored_containers': {},
                'explored_features': {},
                'discovered_features': {},
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
        Main entry point - Two-Tier Execution
            """
        self.exploration_memory = {
        'explored_containers': {}, 
        'explored_features': {}, 
        'discovered_features': {}
        }
        self._save_memory() # Save this empty state to the file
        
        console.print("[yellow]🚀 Fresh Crawl Started: Memory cleared for total exploration.[/yellow]")
        console.print(Panel.fit(
            "[bold cyan]🔬 TWO-TIER PLANNING CRAWLER[/bold cyan]\n"
            f"[yellow]Target: {self.base_url}[/yellow]\n"
            f"[yellow]Max Depth: {self.max_depth}[/yellow]\n"
            "[green]Phase 1: Discovery (Expand containers)[/green]\n"
            "[green]Phase 2: Testing (Test features)[/green]",
            border_style="cyan"
        ))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1200, 'height': 700}
            )
            page = await context.new_page()

            # Setup auth
            await self._setup_auth(page, context)

            # Inject DOM observer
            await self.dom_observer.inject_observer(page)

            # TWO-TIER EXPLORATION
            await self._two_tier_exploration(page, depth=0, breadcrumb="Root")

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
        await asyncio.sleep(3)

        current_url = page.url
        if 'login' in current_url.lower():
            console.print("[red]❌ Authentication failed - still on login page[/red]")
            raise Exception("Authentication failed")

        console.print("[green]✅ Successfully authenticated![/green]\n")

    async def scroll_to_bottom(self, page: Page):
        """
        Scrolls the page to the bottom to trigger lazy-loading 
        and ensure all elements are rendered.
        """
        console.print("[cyan]📜 Scrolling to load all content...[/cyan]")
        await page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    let distance = 100;
                    let timer = setInterval(() => {
                        let scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if(totalHeight >= scrollHeight){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        """)
        await asyncio.sleep(2) # Wait for any lazy-loaded animations

    async def _two_tier_exploration(self, page: Page, depth: int, breadcrumb: str):
        """
        TWO-TIER EXPLORATION ORCHESTRATOR

        Phase 1: Execute Assumption Plan (Discovery)
        Phase 2: Execute Main Action Plan (Testing)
        """
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️ Max depth {self.max_depth} reached[/yellow]")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]📍 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"{'='*80}\n")

        await self.scroll_to_bottom(page)
        await page.evaluate("window.scrollTo(0, 0)")
        # Wait for page stability
        console.print("[yellow]⏳ Waiting for DOM to settle after scroll...[/yellow]")
        await asyncio.sleep(3)

        # Calculate state hash
        state_hash = await self.state_manager.calculate_state_hash(page)
        current_url = page.url

        # Check if already visited
        if self.state_manager.is_state_visited(state_hash):
            console.print(f"[yellow]♻️ State already visited, skipping[/yellow]")
            return

        # === INITIAL VISION ANALYSIS ===
        console.print("\n[bold yellow]🔍 INITIAL SCAN: Understanding page structure...[/bold yellow]")
        vision_analysis = await self.vision.analyze_page(page, current_url)
        self.stats['vision_calls'] += 1

        # === COMPONENT DETECTION ===
        containers = await self.component_detector.detect_containers(
            page,
            vision_analysis.get('containers', [])
        )

        features = await self.component_detector.detect_features(
            page,
            vision_analysis.get('features', [])
        )

        self.stats['containers_found'] += len(containers)
        self.stats['features_found'] += len(features)

        if not containers and not features:
            console.print("[yellow]No components detected, ending exploration[/yellow]")
            return

        # Record state
        self.state_manager.record_state(state_hash, current_url, breadcrumb, containers, features)
        self.stats['states_discovered'] += 1
        self.stats['pages_explored'] += 1

        # === CREATE TWO-TIER PLANS ===
        assumption_plan = self.planner.create_assumption_plan(
            containers,
            vision_analysis.get('discovery_strategy', {})
        )

        main_action_plan = self.planner.create_main_action_plan(features)

        # === PHASE 1: EXECUTE ASSUMPTION PLAN (DISCOVERY) ===
        console.print("\n" + "="*80)
        console.print("[bold green]🎯 PHASE 1: DISCOVERY - Executing Assumption Plan[/bold green]")
        console.print("="*80 + "\n")

        await self._execute_assumption_plan(page, assumption_plan, depth, breadcrumb)

        # === PHASE 2: EXECUTE MAIN ACTION PLAN (TESTING) ===
        console.print("\n" + "="*80)
        console.print("[bold green]🎯 PHASE 2: TESTING - Executing Main Action Plan[/bold green]")
        console.print("="*80 + "\n")

        await self._execute_main_action_plan(page, self.planner.main_action_plan, depth, breadcrumb)

    async def _execute_assumption_plan(self, page: Page, plan: List[Dict], depth: int, breadcrumb: str):
        """
        PHASE 1: Execute Discovery Plan
        Click containers to reveal hidden features
        """
        if not plan:
            console.print("[yellow]No discovery steps needed[/yellow]")
            return

        for step in plan:
            container = step.get('container')
            container_id = container.get('semantic_id')

            # Check memory
            if container_id in self.exploration_memory.get('explored_containers', {}):
                cont_status = self.exploration_memory['explored_containers'][container_id]
                if cont_status.get('expanded') == True:
                    console.print(f"\n[yellow]⏭️  SKIPPING: {container['text']} - Already expanded[/yellow]")
                    continue

            console.print(f"\n[bold yellow]🔓 DISCOVERY STEP {step['step_id']}: {step['reason']}[/bold yellow]")
            console.print(f"[cyan]   Hypothesis: {step['hypothesis']}[/cyan]")

            # Clear change log
            await self.dom_observer.get_changes(page)

            # Click to expand
            clicked = await self.semantic_selector.click_element(page, container)

            if not clicked:
                console.print("[red]   Discovery failed - skipping[/red]")
                continue

            self.stats['discovery_clicks'] += 1

            # Mark as expanded
            self.exploration_memory['explored_containers'][container_id] = {
                'text': container.get('text'),
                'expanded': True,
                'expanded_at': datetime.now().isoformat(),
                'type': container.get('type')
            }

            # Wait for changes
            await asyncio.sleep(2)

            # Check what changed
            changes = await self.dom_observer.get_changes(page)
            change_type = await self.dom_observer.detect_change_type(changes)

            console.print(f"[cyan]   Change detected: {change_type}[/cyan]")
            console.print(f"[cyan]   DOM changes: {len(changes)}[/cyan]")

            # Re-scan for newly visible features
            if change_type in ["menu_expanded", "element_expanded", "modal_opened"]:
                await self._rescan_and_add_features(page, container, depth, breadcrumb)
                self.stats['menus_expanded'] += 1

                if change_type == "modal_opened":
                    self.stats['modals_detected'] += 1
                    # Close modal after scanning
                    await self._close_modal(page)

            # Save memory
            self._save_memory()
    def _get_parent_container_id(self, child: Dict) -> Optional[str]:
        """
        If child has location='sidebar_child', find its parent container
        """
        if child.get('location') == 'sidebar_child':
            # Look in discovered_features to find which container discovered this child
            feature_id = child.get('semantic_id')
            discovery_info = self.exploration_memory.get('discovered_features', {}).get(feature_id)
            if discovery_info:
                return discovery_info.get('discovered_from_id')  # Need to store parent ID!
        return None

    async def _is_container_expanded(self, page: Page, container_semantic_id: str) -> bool:
        """
        Check if container is actually expanded in the current DOM
        """
        # Get the container from memory
        container = self._get_container_from_memory(container_semantic_id)

        # Check aria-expanded attribute or visible children
        is_expanded = await page.evaluate("""
            ({text, location}) => {
                // Find the container element
                const selectors = location === 'sidebar'
                    ? ['aside', 'nav', '[class*="sidebar"]']
                    : ['*'];

                for (const sel of selectors) {
                    const container = document.querySelector(sel);
                    if (!container) continue;

                    const element = Array.from(container.querySelectorAll('*'))
                        .find(el => el.textContent?.trim().includes(text));

                    if (element) {
                        // Check aria-expanded
                        if (element.getAttribute('aria-expanded') === 'true') return true;

                        // Check if children are visible
                        const parent = element.closest('li, div');
                        if (parent) {
                            const children = parent.querySelectorAll('ul li, [class*="submenu"] *');
                            return children.length > 0 &&
                                Array.from(children).some(c => c.offsetHeight > 0);
                        }
                    }
                }
                return false;
            }
        """, {'text': container['text'], 'location': container['location']})

        return is_expanded

    async def click_child_with_parent_check(self, page: Page, child: Dict) -> bool:
        """
        Smart click that ensures parent is expanded first
        """
        # 1. Is this a child element (has a parent container)?
        parent_id = self._get_parent_container_id(child)

        if parent_id:
            # 2. Check if parent is actually expanded in the DOM
            is_expanded = await self._is_container_expanded(page, parent_id)

            if not is_expanded:
                console.print(f"[yellow]⚠️ Parent '{parent_id}' is collapsed. Re-expanding...[/yellow]")

                # 3. Re-expand the parent
                parent_container = self._get_container_from_memory(parent_id)
                await self.semantic_selector.click_element(page, parent_container)
                await asyncio.sleep(1)  # Wait for expansion

        # 4. Now click the child
        return await self.semantic_selector.click_element(page, child)

    async def _execute_main_action_plan(self, page: Page, plan: List[Dict], depth: int, breadcrumb: str):
        """
        PHASE 2: Execute Testing Plan
        Test all discovered features
        """
        if not plan:
            console.print("[yellow]No test steps needed[/yellow]")
            return

        for step in plan:
            feature = step.get('feature')
            feature_id = feature.get('semantic_id')

            # Check memory
            if feature_id in self.exploration_memory.get('explored_features', {}):
                feat_status = self.exploration_memory['explored_features'][feature_id]
                if feat_status.get('tested') == True:
                    console.print(f"\n[yellow]⏭️  SKIPPING: {feature['text']} - Already tested[/yellow]")
                    continue

            console.print(f"\n[bold yellow]🧪 TEST STEP {step['step_id']}: {step['reason']}[/bold yellow]")
            console.print(f"[cyan]   Test Type: {step['test_type']}[/cyan]")

            # Record URL before action
            url_before = page.url

            # Click feature
            clicked = await self.semantic_selector.click_element(page, feature)

            if not clicked:
                console.print("[red]   Test failed - could not click[/red]")
                continue

            self.stats['test_clicks'] += 1
            self.stats['features_tested'] += 1

            # Mark as tested
            self.exploration_memory['explored_features'][feature_id] = {
                'text': feature.get('text'),
                'tested': True,
                'tested_at': datetime.now().isoformat(),
                'test_type': step['test_type']
            }

            # Wait for changes
            await asyncio.sleep(3)

            # Check URL and State after action
            url_after = page.url

            if url_after != url_before:
                # 1. Navigation occurred - Enter recursive exploration
                console.print(f"[green]   🌐 Navigation detected: {url_after}[/green]")
                new_breadcrumb = f"{breadcrumb} > {feature['text'][:30]}"
                
                # DIVE DEEPER
                await self._two_tier_exploration(page, depth + 1, new_breadcrumb)

                # 2. RETURN AND RESTORE STATE
                console.print(f"[yellow]   ⬅️ Returning to parent: {breadcrumb}[/yellow]")
                try:
                    # Go back and wait for the dashboard to actually load
                    await page.go_back(wait_until='networkidle', timeout=15000)
                    await asyncio.sleep(3) 
                    
                    # IMPORTANT: Reset view to top so detection works
                    await page.evaluate("window.scrollTo(0, 0)")
                    
                    # RE-INJECT OBSERVER
                    await self.dom_observer.inject_observer(page)

                    # FIX: If this was a sidebar child, we MUST re-expand the parent 
                    # because it likely collapsed during navigation
                    if feature.get('location') == 'sidebar_child':
                        parent_id = self._get_parent_container_id(feature)
                        if parent_id:
                            console.print(f"[yellow]   🔄 Re-opening sidebar menu: {parent_id}[/yellow]")
                            parent_container = self._get_container_from_memory(parent_id)
                            if parent_container:
                                await self.semantic_selector.click_element(page, parent_container)
                                await asyncio.sleep(2) # Wait for expansion animation

                except Exception as e:
                    console.print(f"[red]   Failed to restore previous state: {e}[/red]")

            # Save memory to ensure we don't re-test this specific feature
            self._save_memory()

    async def _rescan_and_add_features(self, page: Page, parent_container: Dict, depth: int, breadcrumb: str):
        """
        After expanding a container, re-scan to find newly visible features
        FIX: Includes 'Data Spill' logic to capture expected children as features
        """
        console.print("[cyan]🔍 Re-scanning for newly visible features...[/cyan]")

        # 1. Take new screenshot
        vision_analysis = await self.vision.analyze_page(page, page.url)
        self.stats['vision_calls'] += 1

        # 2. Get the features the model explicitly found
        raw_vision_features = vision_analysis.get('features', [])

        # === 🛠️ THE FIX STARTS HERE ===
        # The model often hides sub-menus inside 'containers' -> 'expected_children'.
        # We must extract them and force them into the 'features' list so they get clicked.

        for container in vision_analysis.get('containers', []):
            # Check if this container is the one we just expanded
            # OR if the model sees it as 'expanded'
            is_expanded = container.get('state') == 'expanded'
            is_target = container['text'].lower() in parent_container['text'].lower()

            if (is_expanded or is_target) and 'expected_children' in container:
                console.print(f"[yellow]   ⚠️ Fix: Extracting children from '{container['text']}' as features...[/yellow]")

                for child_text in container['expected_children']:
                    # Create a "fake" feature object for the sub-menu item
                    synthetic_feature = {
                        "text": child_text,
                        "type": "link",
                        "location": "sidebar_child",
                        "test_priority": 8, # High priority!
                        "expected_behavior": "Navigate to sub-page"
                    }

                    # Add it to the list of things to find
                    raw_vision_features.append(synthetic_feature)
                    console.print(f"[green]      + Extracted: {child_text}[/green]")
        # === 🛠️ THE FIX ENDS HERE ===

        # 3. Now detect DOM elements for EVERYTHING (including the extracted children)
        new_features = await self.component_detector.detect_features(
            page,
            raw_vision_features
        )

        # 4. Filter duplicates and add to plan (Existing logic)
        truly_new_features = []
        for feature in new_features:
            feature_id = feature.get('semantic_id')
            if feature_id not in self.exploration_memory.get('explored_features', {}):
                truly_new_features.append(feature)
                self.exploration_memory['discovered_features'][feature_id] = {
                    'text': feature.get('text'),
                    'discovered_from': parent_container.get('text'),
                    'discovered_at': datetime.now().isoformat()
                }

        if truly_new_features:
            console.print(f"[green]   ✨ Found {len(truly_new_features)} new features![/green]")
            for feat in truly_new_features:
                console.print(f"[green]      - {feat['text']}[/green]")

            self.planner.add_discovered_features_to_main_plan(truly_new_features)
            self.stats['features_found'] += len(truly_new_features)
        else:
            console.print("[yellow]   No new features found[/yellow]")

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

    def _show_results(self):
        """
        Display exploration results
        """
        console.print("\n" + "="*80)
        console.print(Panel.fit(
            "[bold green]✅ TWO-TIER EXPLORATION COMPLETE[/bold green]",
            border_style="green"
        ))

        # Stats table
        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="yellow")

        for key, value in self.stats.items():
            table.add_row(key.replace('_', ' ').title(), str(value))

        console.print(table)

        # Plans summary
        console.print("\n[bold cyan]Plan Summary:[/bold cyan]")
        console.print(f"  Discovery Steps: {len(self.planner.assumption_plan)}")
        console.print(f"  Testing Steps: {len(self.planner.main_action_plan)}")

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
                'stats': self.stats,
                'architecture': 'two_tier_planning'
            },
            'assumption_plan': self.planner.assumption_plan,
            'main_action_plan': self.planner.main_action_plan,
            'states': {
                hash: {
                    'url': state['url'],
                    'breadcrumb': state['breadcrumb'],
                    'container_count': state['container_count'],
                    'feature_count': state['feature_count'],
                    'visited_at': state['visited_at']
                }
                for hash, state in self.state_manager.states.items()
            }
        }

        output_file = output_dir / f'two_tier_exploration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
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

    # OpenAI API key
    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        console.print("[red]❌ OPENAI_API_KEY environment variable not set![/red]")
        return

    # Initialize crawler
    crawler = TwoTierCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=20,
        openai_api_key=openai_key
    )

    # Run
    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())