"""
TAG & TRACK ARCHITECTURE - Complete Implementation
Version 2.0 - Production Ready

This implements the full 6-layer architecture:
1. Perception Layer - Find all clickable elements
2. Tagging Layer - Assign unique IDs (data-agent-id)
3. State Fingerprinting - Semantic hashing to recognize states
4. Decision Layer - LLM brain to choose next action
5. Execution Layer - Precise clicking using IDs
6. Loop - Re-scan after every action

Features:
- ✅ Unique ID injection (data-agent-id)
- ✅ State graph tracking
- ✅ Semantic hashing (ignores timestamps/dynamic content)
- ✅ Visited action tracking per state
- ✅ Expandable menu detection
- ✅ Modal handling
- ✅ Smart breadcrumb navigation
"""

import asyncio
import json
import hashlib
import os
from rich.logging import RichHandler
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urlparse
from datetime import datetime
import openai
import logging
from playwright.async_api import async_playwright, Page
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.tree import Tree

# --- LOGGING CONFIGURATION ---
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(rich_tracebacks=True),
        logging.FileHandler(log_file)
    ]
)
logger = logging.getLogger("TagAndTrack")

console = Console()


class StateNode:
    """
    Represents a unique state in the exploration graph
    """
    def __init__(self, state_hash: str, url: str, breadcrumb: str):
        self.state_hash = state_hash
        self.url = url
        self.breadcrumb = breadcrumb
        self.visited_ids: Set[str] = set()  # IDs we've clicked in this state
        self.transitions: Dict[str, str] = {}  # ID -> resulting state_hash
        self.element_ids: List[str] = []  # Available IDs in this state
        self.timestamp = datetime.now()
        self.visited_urls = set()
        self.dead_ids: Set[str] = set()
        logger.debug(f"Created StateNode: {state_hash} for {url}")
        
    def to_dict(self):
        return {
            'state_hash': self.state_hash,
            'url': self.url,
            'breadcrumb': self.breadcrumb,
            'visited_ids': list(self.visited_ids),
            'transitions': self.transitions,
            'element_ids': self.element_ids,
            'timestamp': self.timestamp.isoformat()
        }


class TagAndTrackCrawler:
    """
    Complete Tag & Track Architecture Implementation
    """

    def __init__(
        self,
        base_url: str,
        auth_file: str = "auth.json",
        max_depth: int = 5,
        llm_model: str = "gpt-4o-mini",
        api_key: Optional[str] = None
    ):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth
        self.llm_model = llm_model
        self.global_url_counts = {}
        logger.info(f"Initializing Crawler for domain: {self.domain}")

        # Load auth
        try:
            with open(auth_file, 'r') as f:
                self.auth_data = json.load(f)
                logger.info(f"Successfully loaded auth from {auth_file}")
        except Exception as e:
                logger.error(f"Failed to load auth file: {e}")
                self.auth_data = {}
        # Initialize OpenAI Client
        if api_key:
            self.llm = openai.OpenAI(api_key=api_key)
        else:
            self.llm = openai.OpenAI

        # STATE GRAPH - The core of Tag & Track
        self.state_graph: Dict[str, StateNode] = {}  # hash -> StateNode
        self.current_state_hash: Optional[str] = None

        # ID counter for tagging
        self.next_id = 101  # Start from 101

        # Stats
        self.stats = {
            'total_elements_tagged': 0,
            'llm_evaluations': 0,
            'elements_clicked': 0,
            'states_discovered': 0,
            'transitions_mapped': 0,
            'modals_detected': 0,
            'expandable_menus_found': 0,
            'llm_cost': 0.0
        }

    async def run(self):
        """Main entry point"""
        logger.info("Starting crawler main loop")
        console.print(Panel.fit(
            "[bold cyan]🏗️  TAG & TRACK ARCHITECTURE - WEB CRAWLER[/bold cyan]\n"
            f"[yellow]Target: {self.base_url}[/yellow]\n"
            f"[yellow]Max Depth: {self.max_depth}[/yellow]\n"
            f"[green]State-based exploration with unique ID tracking[/green]",
            border_style="cyan"
        ))

        async with async_playwright() as p:
            logger.info("Launching browser...")
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()

            # Inject auth
            await self._setup_auth(page, context)

            # Start exploration from root
            await self._explore_from_state(page, depth=0, breadcrumb="Dashboard")

            logger.info("Closing browser and saving results...")
            await browser.close()

        # Show results
        self._show_results()
        self._save_state_graph()

        return self.state_graph

    async def _setup_auth(self, page: Page, context):
        """Setup authentication"""
        console.print("\n[cyan]🔑 Setting up authentication...[/cyan]")
        logger.info("Injecting authentication credentials")

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
                console.print(f"  ✗ localStorage failed: {key}")

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
                console.print(f"  ✗ Cookies failed")

        console.print("[green]✅ Auth data injected[/green]")

        # Navigate to actual page
        console.print(f"[cyan]🌐 Navigating to: {self.base_url}[/cyan]")
        await page.goto(self.base_url, wait_until='networkidle', timeout=15000)

        current_url = page.url
        if 'login' in current_url.lower():
            console.print("[red]❌ Authentication failed[/red]")
            raise Exception("Authentication failed")

        console.print("[green]✅ Successfully authenticated![/green]\n")

    # ==================== LAYER 1: PERCEPTION ====================

    async def _find_interactive_elements(self, page: Page) -> List[Dict]:
        """
        LAYER 1: PERCEPTION
        Find all interactive elements using multiple detection strategies
        """
        console.print("[cyan]👁️  LAYER 1: Perception - Finding interactive elements...[/cyan]")

        # First, let's check if the page is fully loaded
        await page.wait_for_load_state('networkidle', timeout=10000)

        elements = await page.evaluate("""
            () => {
                const elements = [];
                const seen = new Set();

                function getVisibleText(el) {
                    let text = '';
                    for (let node of el.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            text += node.textContent.trim() + ' ';
                        }
                    }
                    return text.trim() || el.innerText?.trim() || el.getAttribute('aria-label') || '';
                }

                function isVisible(el) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                           style.visibility !== 'hidden' &&
                           style.opacity !== '0' &&
                           rect.width > 0 && rect.height > 0;
                }

                function getXPath(el) {
                    // If element has unique ID, use it
                    if (el.id) return `//*[@id="${el.id}"]`;

                    // Build path from root
                    const parts = [];
                    let current = el;

                    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
                        let index = 1;  // XPath is 1-indexed
                        let sibling = current.previousSibling;

                        // Count preceding siblings with same tag
                        while (sibling) {
                            if (sibling.nodeType === Node.ELEMENT_NODE && sibling.nodeName === current.nodeName) {
                                index++;
                            }
                            sibling = sibling.previousSibling;
                        }

                        // Count total siblings with same tag to determine if index is needed
                        let totalSameTags = 0;
                        const parent = current.parentNode;
                        if (parent) {
                            for (let child of parent.children) {
                                if (child.nodeName === current.nodeName) {
                                    totalSameTags++;
                                }
                            }
                        }

                        const tagName = current.nodeName.toLowerCase();
                        // Only add index if there are multiple elements with same tag
                        const pathIndex = totalSameTags > 1 ? `[${index}]` : '';
                        parts.unshift(tagName + pathIndex);

                        current = current.parentNode;
                    }

                    return '//' + parts.join('/');
                }

                function addElement(el, detectionMethod) {
                    if (!isVisible(el)) return;
                    // If the element is inside another interactive element, skip it.
                    let parent = el.parentElement;
                    while (parent && parent !== document.body) {
                        if (['A', 'BUTTON'].includes(parent.tagName) || parent.getAttribute('role') === 'button') {
                            return; 
                        }
                        parent = parent.parentElement;
                    }
                    // --- END PARENT CHECK ---
                    const xpath = getXPath(el);
                    if (seen.has(xpath)) return;
                    seen.add(xpath);

                    const text = getVisibleText(el);

                    // Filter out elements with no meaningful content
                    if (text.length < 1 && !el.getAttribute('aria-label') && !el.id) {
                        return;
                    }

                    // Generate a reliable CSS selector
                    let cssSelector = '';
                    if (el.id) {
                        cssSelector = `#${CSS.escape(el.id)}`;
                    } else if (el.className && typeof el.className === 'string') {
                        const classes = el.className.split(' ').filter(c => c && c.length > 0);
                        if (classes.length > 0) {
                            cssSelector = el.tagName.toLowerCase() + '.' + classes.map(c => CSS.escape(c)).join('.');
                        }
                    }

                    // Fallback: tag name only
                    if (!cssSelector) {
                        cssSelector = el.tagName.toLowerCase();
                    }

                    elements.push({
                        xpath: xpath,
                        cssSelector: cssSelector,
                        text: text,
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        classes: el.className || null,
                        role: el.getAttribute('role') || null,
                        ariaLabel: el.getAttribute('aria-label') || null,
                        href: el.href || null,
                        detectionMethod: detectionMethod,
                        location: el.closest('nav') ? 'nav' :
                                 el.closest('aside') ? 'sidebar' :
                                 el.closest('[class*="sidebar"]') ? 'sidebar' :
                                 el.closest('header') ? 'header' :
                                 'main',
                        // Store a unique fingerprint for this element
                        fingerprint: `${el.tagName}:${text.substring(0, 30)}:${el.id || el.className || ''}`
                    });
                }

                // Strategy 1: Cursor pointer test
                document.querySelectorAll('*').forEach(el => {
                    const style = window.getComputedStyle(el);
                    if (style.cursor === 'pointer') {
                        addElement(el, 'cursor-pointer');
                    }
                });

                // Strategy 2: Standard interactive tags
                document.querySelectorAll('button, a[href], input[type="button"], input[type="submit"]').forEach(el => {
                    addElement(el, 'standard-tag');
                });

                // Strategy 3: ARIA roles
                document.querySelectorAll('[role="button"], [role="menuitem"], [role="tab"], [role="link"]').forEach(el => {
                    addElement(el, 'aria-role');
                });

                // Strategy 4: Event listeners (elements with onclick)
                document.querySelectorAll('[onclick]').forEach(el => {
                    addElement(el, 'onclick-attribute');
                });

                // Strategy 5: Router links (SPA frameworks)
                document.querySelectorAll('[routerlink], [ng-reflect-router-link], [data-route]').forEach(el => {
                    addElement(el, 'router-link');
                });

                return elements;
            }
        """)

        console.print(f"[green]   Found {len(elements)} interactive elements[/green]")
        return elements
    
    import hashlib

    def _generate_stable_id(self, element: Dict) -> str:
        """
        Creates a unique, deterministic ID based on element properties.
        """
        # Create a string combining stable attributes
        # We include 'location' (nav/sidebar/main) to distinguish 
        # between similar buttons in different areas.
        signature = f"{element['tag']}_{element['text']}_{element['location']}_{element['xpath']}"
        
        # Return a short 8-character hash
        return hashlib.md5(signature.encode()).hexdigest()[:8]

    # ==================== LAYER 2: TAGGING ====================

    async def _tag_elements(self, page: Page, elements: List[Dict]) -> List[Dict]:
        """
        LAYER 2: TAGGING
        Inject unique data-agent-id to each element
        """
        console.print("[cyan]🏷️  LAYER 2: Tagging - Assigning unique IDs...[/cyan]")

        tagged_elements = []
        failures = 0

        # Inject all IDs in one batch for efficiency and reliability
        tagging_script = """
            (elementsData) => {
                const results = [];

                for (const elementData of elementsData) {
                    try {
                        let el = null;

                        // Strategy 1: Try by ID (most reliable)
                        if (!el && elementData.id) {
                            el = document.getElementById(elementData.id);
                        }

                        // Strategy 2: Try by CSS selector
                        if (!el && elementData.cssSelector) {
                            try {
                                const candidates = document.querySelectorAll(elementData.cssSelector);
                                // If multiple matches, find by text
                                if (candidates.length === 1) {
                                    el = candidates[0];
                                } else if (candidates.length > 1 && elementData.text) {
                                    for (const candidate of candidates) {
                                        const candidateText = candidate.innerText?.trim() || '';
                                        if (candidateText === elementData.text) {
                                            el = candidate;
                                            break;
                                        }
                                    }
                                    // If still not found, use first match
                                    if (!el) el = candidates[0];
                                }
                            } catch (e) {}
                        }

                        // Strategy 3: Try XPath
                        if (!el && elementData.xpath) {
                            try {
                                el = document.evaluate(
                                    elementData.xpath,
                                    document,
                                    null,
                                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                                    null
                                ).singleNodeValue;
                            } catch (e) {}
                        }

                        // Strategy 4: Find by text content and tag (last resort)
                        if (!el && elementData.text && elementData.text.length > 3 && elementData.tag) {
                            const allElements = document.querySelectorAll(elementData.tag);
                            for (const elem of allElements) {
                                const elemText = elem.innerText?.trim() || '';
                                if (elemText === elementData.text) {
                                    el = elem;
                                    break;
                                }
                            }
                        }

                        // If found, tag it
                        if (el && el.nodeType === Node.ELEMENT_NODE) {
                            // Check if already tagged (avoid duplicates)
                            if (!el.hasAttribute('data-agent-id')) {
                                el.setAttribute('data-agent-id', elementData.agentId);
                                results.push({
                                    success: true,
                                    agentId: elementData.agentId,
                                    actualTag: el.tagName,
                                    method: 'tagged'
                                });
                            } else {
                                results.push({
                                    success: false,
                                    agentId: elementData.agentId,
                                    reason: 'already_tagged',
                                    existingId: el.getAttribute('data-agent-id')
                                });
                            }
                        } else {
                            results.push({
                                success: false,
                                agentId: elementData.agentId,
                                reason: 'element_not_found'
                            });
                        }
                    } catch (error) {
                        results.push({
                            success: false,
                            agentId: elementData.agentId,
                            reason: error.message
                        });
                    }
                }

                return results;
            }
        """

        # Prepare data for batch tagging
        elements_data = []
        for element in elements:
            agent_id = self._generate_stable_id(element)

            elements_data.append({
                'xpath': element.get('xpath'),
                'cssSelector': element.get('cssSelector'),
                'id': element.get('id'),
                'text': element.get('text', ''),
                'tag': element.get('tag'),
                'fingerprint': element.get('fingerprint'),
                'agentId': str(agent_id),
                'originalElement': element
            })

        # Execute batch tagging
        try:
            results = await page.evaluate(tagging_script, elements_data)

            # Process results
            for i, result in enumerate(results):
                if result['success']:
                    element = elements_data[i]['originalElement']
                    element['agent_id'] = str(result['agentId'])
                    tagged_elements.append(element)
                else:
                    failures += 1

        except Exception as e:
            console.print(f"[red]   Batch tagging failed: {e}[/red]")
            console.print("[yellow]   Falling back to individual tagging...[/yellow]")

            # Fallback: tag individually
            for element_data in elements_data:
                try:
                    success = await page.evaluate("""
                        (xpath, agentId) => {
                            try {
                                const el = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                                if (el) {
                                    el.setAttribute('data-agent-id', agentId);
                                    return true;
                                }
                            } catch (e) {}
                            return false;
                        }
                    """, element_data['xpath'], element_data['agentId'])

                    if success:
                        element = element_data['originalElement']
                        element['agent_id'] = str(element_data['agentId'])
                        tagged_elements.append(element)
                    else:
                        failures += 1
                except:
                    failures += 1

        self.stats['total_elements_tagged'] += len(tagged_elements)

        if tagged_elements:
            console.print(f"[green]   ✅ Tagged {len(tagged_elements)} elements (IDs: {tagged_elements[0]['agent_id']} - {tagged_elements[-1]['agent_id']})[/green]")
        else:
            console.print(f"[red]   ❌ Failed to tag any elements![/red]")

        if failures > 0:
            console.print(f"[yellow]   ⚠️  {failures} elements could not be tagged[/yellow]")

        return tagged_elements

    # ==================== LAYER 3: STATE FINGERPRINTING ====================

    async def _calculate_state_hash(self, page: Page) -> str:
        """
        LAYER 3: STATE FINGERPRINTING
        Create semantic hash that ignores dynamic content
        """
        console.print("[cyan]🔍 LAYER 3: Fingerprinting - Calculating state hash...[/cyan]")

        state_data = await page.evaluate("""
            () => {
                // Get all elements with data-agent-id
                const taggedElements = Array.from(document.querySelectorAll('[data-agent-id]'));

                // Create structure signature (ignore dynamic text like timestamps)
                const structure = taggedElements.map(el => {
                    const style = window.getComputedStyle(el);
                    return {
                        id: el.getAttribute('data-agent-id'),
                        tag: el.tagName,
                        visible: style.display !== 'none' && style.visibility !== 'hidden',
                        location: el.closest('nav') ? 'nav' :
                                 el.closest('aside') ? 'sidebar' :
                                 el.closest('[class*="sidebar"]') ? 'sidebar' : 'main'
                    };
                }).filter(el => el.visible);

                // Also include URL path (not query params)
                const urlPath = window.location.pathname;

                // Get main content structure (ignore text content)
                const mainElements = Array.from(document.querySelectorAll('main *, [role="main"] *, #main *'));
                const contentStructure = mainElements.map(el => el.tagName).join('|');

                return {
                    url_path: urlPath,
                    'tagged_structure': structure.map(s => `${s.id}:${s.tag}:${s.visible}:${s.location}`).join('|'),
                    content_structure_hash: contentStructure.substring(0, 500), // Limit to avoid huge strings
                    element_count: structure.length
                };
            }
        """)

        # Create hash from normalized data
        hash_string = f"{state_data['url_path']}::{state_data['tagged_structure']}::{state_data['content_structure_hash']}"
        state_hash = hashlib.sha256(hash_string.encode()).hexdigest()[:16]  # Use first 16 chars

        console.print(f"[green]   State Hash: {state_hash}[/green]")
        console.print(f"[green]   URL: {state_data['url_path']}[/green]")
        console.print(f"[green]   Elements: {state_data['element_count']}[/green]")

        return state_hash

    def _get_or_create_state_node(self, state_hash: str, url: str, breadcrumb: str) -> StateNode:
        """Get existing state node or create new one"""
        if state_hash in self.state_graph:
            console.print(f"[yellow]   ♻️  Known state: {breadcrumb}[/yellow]")
            return self.state_graph[state_hash]
        else:
            console.print(f"[green]   ✨ New state discovered: {breadcrumb}[/green]")
            node = StateNode(state_hash, url, breadcrumb)
            self.state_graph[state_hash] = node
            self.stats['states_discovered'] += 1
            return node

    # ==================== LAYER 4: DECISION ====================

    async def _decide_next_action(
        self,
        state_node: StateNode,
        tagged_elements: List[Dict],
        page: Page,
        depth: int
    ) -> Optional[Dict]:
        """
        LAYER 4: DECISION
        Use LLM to decide which element to click next
        """
        console.print("[cyan]🧠 LAYER 4: Decision - LLM choosing next action...[/cyan]")

        # Filter out already visited IDs
        unvisited_elements = [
            el for el in tagged_elements
            if el['agent_id'] not in state_node.visited_ids
        ]

        if not unvisited_elements:
            console.print("[yellow]   All elements in this state have been visited[/yellow]")
            return None

        # Store available IDs in state node
        state_node.element_ids = [el['agent_id'] for el in tagged_elements]

        # Prepare element summaries for LLM
        # 1. Get the current breadcrumb as a list of lowercase words for easy comparison
        breadcrumb_words = [word.strip().lower() for word in state_node.breadcrumb.split('>')]
        
        element_summaries = []
        for el in unvisited_elements:
            # OPTIONAL: Limit the total sent to LLM, but prioritize non-nav items
            if len(element_summaries) >= 25:
                break
                
            element_text = el['text'].strip().lower()
            
            # 2. HEURISTIC: Flag if the element text is already in our path
            is_in_breadcrumb = any(word in element_text or element_text in word 
                                   for word in breadcrumb_words if len(word) > 2)
            
            # 3. Add rich context so the LLM can make an informed choice
            element_summaries.append({
                'id': el['agent_id'],
                'text': el['text'][:50],
                'tag': el['tag'],
                'location': el['location'], # 'nav', 'sidebar', or 'main'
                'is_back_navigation': is_in_breadcrumb, # CRITICAL: Tells LLM this is a loop risk
                'target_url_hint': el.get('href', 'unknown') # If available
            })

        prompt = f"""You are exploring a web application systematically.

Current State:
- Breadcrumb: {state_node.breadcrumb}
- URL: {state_node.url}
- Depth: {depth}/{self.max_depth}
- Visited IDs in this state: {list(state_node.visited_ids)}

Available unvisited elements ({len(unvisited_elements)}):
{json.dumps(element_summaries, indent=2)}


Choose the BEST element to click next:
1. Prioritize navigation items (menus, tabs)
2. Explore sidebar/nav items before main content
3. Avoid logout, language selectors, help buttons
4. Prefer items that likely lead to new pages/features

Known Dead-Ends (clicked but no change): {list(state_node.dead_ids)}

STRICT RULE: Do NOT click any ID listed as a Known Dead-End.

CRITICAL RULES:
1. DO NOT click navigation items that are already in your Breadcrumb (e.g., if you are in 'Menu', don't click 'Menu' again).
2. Prioritize items that YOU HAVE NOT CLICKED YET in any parent state.
3. If you feel stuck in a loop, choose a "Main" content button instead of a "Sidebar" navigation link.

STRICT NAVIGATION RULES:

NO REPETITION: Do not click any element whose text matches any part of the Current Breadcrumb: {state_node.breadcrumb}.

DEPTH AWARENESS: You are at Depth {depth}. If you have been alternating between two URLs, you MUST choose a button in the 'main' location instead of the 'nav' or 'sidebar'.

BREADCRUMB CHECK: Before choosing, list the words in the breadcrumb and ensure your chosen ID's text is not one of them.

Respond with JSON:
{{
  "agent_id": <id_string>,
  "reasoning": "<brief explanation>",
  "expected_outcome": "new_page|modal|expand_menu|unknown"
}}

Choose ONE element. Return JSON only."""

        try:
            # OpenAI specific call
            response = self.llm.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}  # Forces GPT to return valid JSON
            )

            self.stats['llm_evaluations'] += 1
            # Update cost calculation for OpenAI rates (approximate for gpt-4o-mini)
            self.stats['llm_cost'] += (response.usage.prompt_tokens * 0.00000015) + (response.usage.completion_tokens * 0.0000006)

            # OpenAI response parsing
            llm_text = response.choices[0].message.content.strip()
            decision = json.loads(llm_text)

            # Find the chosen element
            chosen_element = next(
                (el for el in unvisited_elements if str(el['agent_id']) == str(decision['agent_id'])),
                None
            )

            if chosen_element:
                console.print(f"[green]   ✅ Decision: Click #{decision['agent_id']} - {chosen_element['text'][:40]}[/green]")
                console.print(f"[yellow]   Reasoning: {decision['reasoning']}[/yellow]")
                return {
                    'element': chosen_element,
                    'decision': decision
                }
            else:
                console.print("[red]   LLM chose invalid ID[/red]")
                return None

        except Exception as e:
            console.print(f"[red]   LLM decision failed: {e}[/red]")
            # Fallback: pick first unvisited
            if unvisited_elements:
                return {
                    'element': unvisited_elements[0],
                    'decision': {'reasoning': 'Fallback - LLM failed'}
                }
            return None

    # ==================== LAYER 5: EXECUTION ====================

    async def _execute_click(self, page: Page, element: Dict) -> bool:
        """
        LAYER 5: EXECUTION
        Click element using data-agent-id with 100% precision
        """
        agent_id = element['agent_id']
        console.print(f"[cyan]👆 LAYER 5: Execution - Clicking element #{agent_id}...[/cyan]")

        try:
            # Primary method: Use data-agent-id selector
            selector = f'[data-agent-id="{agent_id}"]'
            await page.click(selector, timeout=5000)
            console.print(f"[green]   ✅ Click successful (using data-agent-id)[/green]")
            return True

        except Exception as e:
            console.print(f"[yellow]   Retrying with xpath...[/yellow]")
            # Fallback: xpath
            try:
                await page.click(f"xpath={element['xpath']}", timeout=3000)
                console.print(f"[green]   ✅ Click successful (using xpath)[/green]")
                return True
            except:
                console.print(f"[red]   ❌ Click failed[/red]")
                return False

    # ==================== LAYER 6: LOOP (Main Exploration) ====================

    async def _explore_from_state(self, page: Page, depth: int, breadcrumb: str):
        """
        Main exploration loop - combines all 6 layers
        """
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️  Max depth {self.max_depth} reached[/yellow]")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]🔄 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"{'='*80}\n")

        # Wait for page to stabilize
        await self._wait_for_stability(page)

        # LAYER 1: Find interactive elements
        elements = await self._find_interactive_elements(page)

        if not elements:
            console.print("[yellow]No interactive elements found[/yellow]")
            return

        # LAYER 2: Tag elements with unique IDs
        tagged_elements = await self._tag_elements(page, elements)

        # Safety check: if no elements were tagged, we can't proceed
        if not tagged_elements:
            console.print("[red]❌ Could not tag any elements - stopping exploration of this state[/red]")
            console.print("[yellow]💡 This might be due to dynamic content or iframe issues[/yellow]")
            return

        # LAYER 3: Calculate state fingerprint
        state_hash = await self._calculate_state_hash(page)
        current_url = page.url

        # Get or create state node
        state_node = self._get_or_create_state_node(state_hash, current_url, breadcrumb)
        self.current_state_hash = state_hash

        # If we've fully explored this state, skip
        unvisited_count = sum(
            1 for el in tagged_elements
            if el['agent_id'] not in state_node.visited_ids
            and el['agent_id'] not in state_node.dead_ids
        )

        if unvisited_count == 0:
            console.print("[yellow]⚪ This state is fully explored[/yellow]")
            return

        console.print(f"[green]📊 State has {unvisited_count} unvisited elements[/green]\n")

        # Exploration loop
        while True:
            # LAYER 4: LLM decides next action
            action = await self._decide_next_action(state_node, tagged_elements, page, depth)

            if not action:
                console.print("[green]✅ All worthy elements explored in this state[/green]")
                break

            element = action['element']
            agent_id = element['agent_id']
            element_text = element['text'][:40]

            # Mark as visited BEFORE clicking (to avoid infinite loops if click fails)
            state_node.visited_ids.add(agent_id)

            # Capture state before clicking
            state_before_hash = state_hash
            url_before = page.url

            # LAYER 5: Execute click
            clicked = await self._execute_click(page, element)

            if not clicked:
                console.print("[red]   Skipping to next element[/red]")
                continue

            self.stats['elements_clicked'] += 1

            # Wait for changes
            await asyncio.sleep(2)

            # LAYER 6: Re-scan to detect changes
            url_after = page.url

            # Check what happened
            if url_after != url_before:
                console.print(f"[green]   🌐 Navigation detected: {url_after}[/green]")
                
                # --- START SATURATION GUARD ---
                # Normalize URL by removing query params/fragments for better matching
                clean_url = url_after.split('?')[0].split('#')[0]
                self.global_url_counts[clean_url] = self.global_url_counts.get(clean_url, 0) + 1
                
                if self.global_url_counts[clean_url] > 3:
                    logger.warning(f"URL {clean_url} saturated ({self.global_url_counts[clean_url]} visits). Forcing backtrack.")
                    # We return here to "pop" off the current depth and go back to the previous state
                    return 
                # --- END SATURATION GUARD ---

                # Record transition in state graph
                state_node.transitions[agent_id] = "navigation"
                self.stats['transitions_mapped'] += 1

                # Recursively explore new page
                new_breadcrumb = f"{breadcrumb} > {element_text}"
                await self._explore_from_state(page, depth + 1, new_breadcrumb)

                # Navigate back
                try:
                    await page.go_back(wait_until='networkidle', timeout=5000)
                    await asyncio.sleep(1)
                except:
                    console.print("[yellow]   Could not go back, navigating to original URL[/yellow]")
                    await page.goto(url_before, wait_until='networkidle')
                    await asyncio.sleep(1)

                # Re-tag elements after returning (page might have changed)
                elements = await self._find_interactive_elements(page)
                tagged_elements = await self._tag_elements(page, elements)

            else:
                # Check if state changed (modal, expanded menu, etc.)
                state_after_hash = await self._calculate_state_hash(page)

                if state_after_hash != state_before_hash:
                    console.print(f"[green]   🔄 State changed (modal/expansion)[/green]")

                    # Check for modal
                    modal_present = await self._check_modal(page)
                    if modal_present:
                        console.print("[yellow]   🔲 Modal detected[/yellow]")
                        self.stats['modals_detected'] += 1

                        state_node.transitions[agent_id] = state_after_hash
                        self.stats['transitions_mapped'] += 1

                        # Explore modal
                        new_breadcrumb = f"{breadcrumb} > Modal({element_text})"
                        await self._explore_from_state(page, depth + 1, new_breadcrumb)

                        # Close modal
                        await self._close_modal(page)
                        await asyncio.sleep(1)

                        # Re-tag after modal closes
                        elements = await self._find_interactive_elements(page)
                        tagged_elements = await self._tag_elements(page, elements)
                    else:
                        console.print("[green]   📂 Content expanded[/green]")
                        # State changed but no modal - possibly expanded menu
                        # Re-tag to catch new elements
                        elements = await self._find_interactive_elements(page)
                        tagged_elements = await self._tag_elements(page, elements)
                else:
                    console.print("[yellow]   ⚪ No state change detected[/yellow]")
                    state_node.dead_ids.add(agent_id)

    # Instead of just asyncio.sleep(2)
    async def _wait_for_stability(self, page: Page):
        await page.wait_for_load_state('networkidle')
        # Wait until the number of data-agent-id elements stops changing
        last_count = 0
        for _ in range(5):
            current_count = await page.locator('[data-agent-id]').count()
            if current_count == last_count and current_count > 0:
                break
            last_count = current_count
            await asyncio.sleep(0.5)

    async def _check_modal(self, page: Page) -> bool:
        """Check if modal is present"""
        return await page.evaluate("""
            () => {
                const selectors = ['[role="dialog"]', '.modal', '[class*="modal"]', '[class*="dialog"]'];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden') {
                            return true;
                        }
                    }
                }
                return false;
            }
        """)

    async def _close_modal(self, page: Page):
        """Close modal"""
        close_selectors = [
            'button[aria-label="Close"]',
            'button.close',
            '[data-dismiss="modal"]',
            'button:has-text("Close")',
            'button:has-text("Cancel")'
        ]

        for selector in close_selectors:
            try:
                await page.click(selector, timeout=2000)
                await asyncio.sleep(0.5)
                return
            except:
                continue

        # Try ESC
        try:
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.5)
        except:
            pass

    def _estimate_cost(self, usage) -> float:
        """Estimate API cost"""
        input_cost = usage.input_tokens / 1_000_000 * 3.0
        output_cost = usage.output_tokens / 1_000_000 * 15.0
        return input_cost + output_cost

    def _show_results(self):
        """Show exploration results"""
        console.print("\n" + "="*80)
        console.print(Panel.fit(
            "[bold green]✅ EXPLORATION COMPLETE[/bold green]",
            border_style="green"
        ))

        # Stats table
        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="yellow")

        table.add_row("States Discovered", str(self.stats['states_discovered']))
        table.add_row("Elements Tagged", str(self.stats['total_elements_tagged']))
        table.add_row("Elements Clicked", str(self.stats['elements_clicked']))
        table.add_row("Transitions Mapped", str(self.stats['transitions_mapped']))
        table.add_row("Modals Detected", str(self.stats['modals_detected']))
        table.add_row("LLM Evaluations", str(self.stats['llm_evaluations']))
        table.add_row("LLM Cost", f"${self.stats['llm_cost']:.4f}")

        console.print(table)

        # Show state graph tree
        self._show_state_tree()

    def _show_state_tree(self):
        """Visualize state graph as tree"""
        console.print("\n[bold cyan]📊 STATE GRAPH[/bold cyan]")

        tree = Tree("🌐 Root State")

        for state_hash, node in list(self.state_graph.items())[:10]:  # Limit to 10
            branch = tree.add(f"[cyan]{node.breadcrumb}[/cyan]")
            branch.add(f"Hash: {state_hash}")
            branch.add(f"URL: {node.url}")
            branch.add(f"Visited: {len(node.visited_ids)} elements")
            branch.add(f"Transitions: {len(node.transitions)}")

        console.print(tree)

    def _save_state_graph(self):
        """Save state graph to file"""
        output_path = Path('semantic_test_output') / 'state_graph.json'
        output_path.parent.mkdir(exist_ok=True)

        graph_data = {
            'metadata': {
                'base_url': self.base_url,
                'timestamp': datetime.now().isoformat(),
                'total_states': len(self.state_graph),
                'stats': self.stats
            },
            'states': {
                hash: node.to_dict()
                for hash, node in self.state_graph.items()
            }
        }

        with open(output_path, 'w') as f:
            json.dump(graph_data, f, indent=2)

        console.print(f"\n[bold green]💾 State graph saved: {output_path}[/bold green]")


async def main():
    """Run the Tag & Track crawler"""

    if not Path('auth.json').exists():
        console.print("[red]❌ auth.json not found![/red]")
        return

    # Configure API key
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        console.print("[red]❌ OPENAI_API_KEY not set![/red]")
        return

    # Initialize crawler

    crawler = TagAndTrackCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=10,
        api_key=api_key
    )

    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())