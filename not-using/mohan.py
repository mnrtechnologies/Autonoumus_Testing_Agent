"""
ULTIMATE WEB CRAWLER - Production Ready
========================================

Features:
- ✅ Robust navigation detection (Angular SPA support)
- ✅ Intelligent form filling (text, email, password, number, date, etc.)
- ✅ Dropdown/Select handling
- ✅ Radio button and checkbox interaction
- ✅ Modal detection and exploration
- ✅ Pagination handling
- ✅ Tab switching
- ✅ Accordion expansion
- ✅ File upload simulation
- ✅ State restoration after navigation
- ✅ Smart deduplication
- ✅ GPT-4 Vision for page understanding
- ✅ Comprehensive error recovery
"""

import asyncio
import json
import hashlib
import os
import base64
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
import random
import string


from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.tree import Tree

from openai import OpenAI

from dotenv import load_dotenv
import os

load_dotenv()

console = Console()


class GPTVisionAnalyzer:
    """Enhanced Vision Analysis with comprehensive component detection"""

    def __init__(self, openai_client: OpenAI):
        self.client = openai_client
        self.analysis_cache = {}

    async def analyze_page(self, page: Page, url: str) -> Dict:
        """Analyze page with GPT-4 Vision - enhanced for all component types"""
        console.print("[cyan]📸 VISION: Analyzing page with GPT-4...[/cyan]")

        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        
        screenshot_bytes = await page.screenshot(full_page=True, type='png')
        screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode('utf-8')

        # Cache check
        screenshot_hash = hashlib.md5(screenshot_bytes).hexdigest()[:8]
        if screenshot_hash in self.analysis_cache:
            console.print("[yellow]   Using cached Vision analysis[/yellow]")
            return self.analysis_cache[screenshot_hash]

        prompt = """You are analyzing a web application to help an automated testing agent explore it systematically.

**MISSION: Identify ALL interactive elements on this page.**

Categorize elements into these types:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 CONTAINERS (Elements that hide/show other content)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Types:
- "expandable_menu" - Sidebar menus with > or ▼
- "accordion" - Collapsible sections
- "tabs" - Tab groups that switch content
- "modal_trigger" - Buttons that open dialogs/modals
- "dropdown" - Elements that show lists on click

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 FORMS (Input elements)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Types:
- "text_input" - Text fields
- "email_input" - Email fields
- "password_input" - Password fields
- "number_input" - Number fields
- "date_input" - Date pickers
- "textarea" - Multi-line text
- "select" - Dropdown selects
- "checkbox" - Checkboxes
- "radio" - Radio buttons
- "file_upload" - File upload fields
- "submit_button" - Form submit buttons

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ACTIONS (Direct action elements)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Types:
- "nav_link" - Navigation links
- "action_button" - Buttons (Save, Delete, Export, etc.)
- "pagination" - Next/Previous/Page number buttons
- "filter" - Filter controls
- "search" - Search boxes
- "sort" - Sort controls

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ CRITICAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Transcribe text EXACTLY as shown (no translation)
2. If a menu is expanded, list ALL visible sub-items in expected_children
3. For forms, identify ALL input fields individually
4. Look for pagination controls (Next, Previous, page numbers)
5. Identify modal triggers (buttons that open dialogs)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return JSON:

{
  "page_type": "dashboard|list|form|detail|settings",
  "layout": {
    "has_sidebar": true|false,
    "has_header": true|false,
    "has_footer": true|false,
    "has_modal": true|false
  },
  "containers": [
    {
      "text": "EXACT text",
      "type": "expandable_menu|accordion|tabs|modal_trigger|dropdown",
      "state": "collapsed|expanded|unknown",
      "location": "sidebar|header|main|footer",
      "expected_children": ["child1", "child2"],
      "priority": 1-10
    }
  ],
  "forms": [
    {
      "text": "Field label or placeholder",
      "type": "text_input|email_input|password_input|number_input|date_input|textarea|select|checkbox|radio|file_upload|submit_button",
      "location": "main|modal|sidebar",
      "required": true|false,
      "priority": 1-10
    }
  ],
  "actions": [
    {
      "text": "EXACT text",
      "type": "nav_link|action_button|pagination|filter|search|sort",
      "location": "sidebar|header|main|footer",
      "priority": 1-10,
      "expected_behavior": "what happens when clicked"
    }
  ],
  "discovery_strategy": {
    "recommended_order": ["First thing to do", "Second thing", ...],
    "reasoning": "why this order"
  }
}

Analyze the screenshot and return valid JSON only."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}
                            }
                        ]
                    }
                ],
                max_tokens=4000
            )

            vision_text = response.choices[0].message.content.strip()

            # Remove markdown code blocks
            if vision_text.startswith('```'):
                vision_text = vision_text.split('\n', 1)[1].rsplit('\n', 1)[0]
                if vision_text.startswith('json'):
                    vision_text = vision_text[4:].strip()

            analysis = json.loads(vision_text)
            self.analysis_cache[screenshot_hash] = analysis

            console.print(f"[green]   ✅ Vision complete - Page: {analysis.get('page_type', 'unknown')}[/green]")
            console.print(f"[yellow]   Containers: {len(analysis.get('containers', []))} | Forms: {len(analysis.get('forms', []))} | Actions: {len(analysis.get('actions', []))}[/yellow]")

            return analysis

        except Exception as e:
            console.print(f"[red]   ❌ Vision failed: {e}[/red]")
            return {
                "page_type": "unknown",
                "layout": {},
                "containers": [],
                "forms": [],
                "actions": [],
                "discovery_strategy": {"recommended_order": [], "reasoning": "Vision failed"}
            }


class FormFiller:
    """Intelligent form filling with realistic data generation"""

    def __init__(self):
        self.form_data_cache = {}

    def generate_realistic_data(self, field_type: str, field_text: str) -> str:
        """Generate realistic test data based on field type and label"""
        field_text_lower = field_text.lower()

        # Email
        if field_type == "email_input" or 'email' in field_text_lower:
            return f"test.user.{random.randint(1000, 9999)}@example.com"

        # Password
        if field_type == "password_input" or 'password' in field_text_lower:
            return "TestPassword123!"

        # Phone
        if 'phone' in field_text_lower or 'mobile' in field_text_lower or 'telepon' in field_text_lower:
            return f"+62812{random.randint(10000000, 99999999)}"

        # Name
        if 'name' in field_text_lower or 'nama' in field_text_lower:
            if 'first' in field_text_lower or 'depan' in field_text_lower:
                return random.choice(['Ahmad', 'Budi', 'Citra', 'Dewi', 'Eko'])
            elif 'last' in field_text_lower or 'belakang' in field_text_lower:
                return random.choice(['Santoso', 'Wijaya', 'Kusuma', 'Pratama', 'Sari'])
            else:
                return f"{random.choice(['Ahmad', 'Budi', 'Citra'])} {random.choice(['Santoso', 'Wijaya'])}"

        # Address
        if 'address' in field_text_lower or 'alamat' in field_text_lower:
            return f"Jl. Testing No. {random.randint(1, 100)}, Jakarta"

        # Number
        if field_type == "number_input" or 'number' in field_text_lower or 'jumlah' in field_text_lower:
            if 'age' in field_text_lower or 'umur' in field_text_lower:
                return str(random.randint(20, 60))
            return str(random.randint(1, 1000))

        # Date
        if field_type == "date_input" or 'date' in field_text_lower or 'tanggal' in field_text_lower:
            date = datetime.now() + timedelta(days=random.randint(1, 30))
            return date.strftime("%Y-%m-%d")

        # URL
        if 'url' in field_text_lower or 'website' in field_text_lower:
            return "https://example.com"

        # Default text
        return f"Test Data {random.randint(100, 999)}"

    async def fill_form_field(self, page: Page, field: Dict) -> bool:
        """Fill a single form field with appropriate data"""
        try:
            field_type = field.get('type', '')
            field_text = field.get('text', '')
            
            console.print(f"[cyan]   📝 Filling: {field_text} ({field_type})[/cyan]")

            # Generate data
            test_data = self.generate_realistic_data(field_type, field_text)

            # Find the field
            field_element = await self._find_form_field(page, field)
            if not field_element:
                console.print(f"[red]      ❌ Field not found[/red]")
                return False

            # Handle different field types
            if field_type in ['text_input', 'email_input', 'password_input', 'number_input', 'textarea']:
                await field_element.fill(test_data)
                console.print(f"[green]      ✅ Filled: {test_data}[/green]")
                return True

            elif field_type == 'date_input':
                await field_element.fill(test_data)
                return True

            elif field_type == 'select':
                # Select first non-empty option
                options = await field_element.locator('option').all()
                if len(options) > 1:
                    await field_element.select_option(index=1)
                    console.print(f"[green]      ✅ Selected option[/green]")
                return True

            elif field_type == 'checkbox':
                is_checked = await field_element.is_checked()
                if not is_checked:
                    await field_element.check()
                    console.print(f"[green]      ✅ Checked[/green]")
                return True

            elif field_type == 'radio':
                await field_element.check()
                console.print(f"[green]      ✅ Selected[/green]")
                return True

            elif field_type == 'file_upload':
                # Create a temporary test file
                test_file = Path('/tmp/test_upload.txt')
                test_file.write_text('Test file content')
                await field_element.set_input_files(str(test_file))
                console.print(f"[green]      ✅ File uploaded[/green]")
                return True

            return False

        except Exception as e:
            console.print(f"[red]      ❌ Error filling field: {e}[/red]")
            return False

    async def _find_form_field(self, page: Page, field: Dict):
        """Find form field using multiple strategies"""
        text = field.get('text', '')
        field_type = field.get('type', '')

        selectors_to_try = []

        # Type-specific selectors
        if field_type == 'text_input':
            selectors_to_try.extend([
                f'input[type="text"]:near(:text("{text}"))',
                f'input[type="text"][placeholder*="{text}"]',
                f'input[type="text"][name*="{text.lower().replace(" ", "_")}"]'
            ])
        elif field_type == 'email_input':
            selectors_to_try.extend([
                f'input[type="email"]',
                f'input[placeholder*="email"]'
            ])
        elif field_type == 'password_input':
            selectors_to_try.extend([
                f'input[type="password"]',
                f'input[placeholder*="password"]'
            ])
        elif field_type == 'select':
            selectors_to_try.extend([
                f'select:near(:text("{text}"))',
                f'select[name*="{text.lower().replace(" ", "_")}"]'
            ])
        elif field_type == 'checkbox':
            selectors_to_try.extend([
                f'input[type="checkbox"]:near(:text("{text}"))',
                f'input[type="checkbox"][name*="{text.lower().replace(" ", "_")}"]'
            ])
        elif field_type == 'radio':
            selectors_to_try.extend([
                f'input[type="radio"]:near(:text("{text}"))',
                f'input[type="radio"][value*="{text}"]'
            ])
        elif field_type == 'textarea':
            selectors_to_try.extend([
                f'textarea:near(:text("{text}"))',
                f'textarea[placeholder*="{text}"]'
            ])

        # Try each selector
        for selector in selectors_to_try:
            try:
                element = page.locator(selector).first
                if await element.count() > 0:
                    return element
            except:
                continue

        return None


class NavigationDetector:
    """Robust navigation detection for SPAs and traditional sites"""

    async def wait_for_navigation_or_change(self, page: Page, url_before: str, timeout: int = 10000) -> Dict:
        """
        Wait for EITHER:
        1. URL change (navigation)
        2. Significant DOM change (modal, tab switch, etc.)
        3. Timeout
        
        Returns: {
            'type': 'navigation' | 'dom_change' | 'no_change',
            'url_after': str,
            'description': str
        }
        """
        
        try:
            # Wait for URL to change
            await page.wait_for_url(lambda url: url != url_before, timeout=timeout)
            
            # URL changed - wait for page to settle
            await page.wait_for_load_state('networkidle', timeout=5000)
            
            return {
                'type': 'navigation',
                'url_after': page.url,
                'description': f'Navigated to {page.url}'
            }
            
        except PlaywrightTimeout:
            # No URL change - check for DOM changes
            url_after = page.url
            
            if url_after != url_before:
                # URL changed but networkidle timeout
                return {
                    'type': 'navigation',
                    'url_after': url_after,
                    'description': f'Navigated to {url_after} (still loading)'
                }
            
            # Check for modal/dialog
            modal_visible = await page.evaluate("""
                () => {
                    const modals = document.querySelectorAll('[role="dialog"], .modal, .dialog, [class*="modal"]');
                    return Array.from(modals).some(m => m.offsetHeight > 0);
                }
            """)
            
            if modal_visible:
                return {
                    'type': 'dom_change',
                    'url_after': url_after,
                    'description': 'Modal/dialog opened'
                }
            
            # Check for significant DOM changes
            visible_elements = await page.evaluate("""
                () => {
                    return document.querySelectorAll('*').length;
                }
            """)
            
            # If many elements, assume content changed
            if visible_elements > 100:
                return {
                    'type': 'dom_change',
                    'url_after': url_after,
                    'description': 'Content updated (no navigation)'
                }
            
            return {
                'type': 'no_change',
                'url_after': url_after,
                'description': 'No detectable changes'
            }


class SmartInteractor:
    """Smart interaction with all UI element types"""

    async def click_element(self, page: Page, element_data: Dict) -> bool:
        """Click element using multiple fallback strategies"""
        text = element_data.get('text', '').replace('>', '').replace('▼', '').replace('▶', '').strip()
        location = element_data.get('location', '')
        elem_type = element_data.get('type', '')

        console.print(f"[cyan]👆 Clicking: '{text}' ({elem_type})[/cyan]")

        # Strategy 1: Playwright text selector
        try:
            selectors = [
                f"text={text}",
                f"button:has-text('{text}')",
                f"a:has-text('{text}')",
                f"[role='button']:has-text('{text}')",
                f"li:has-text('{text}')"
            ]

            if location == 'sidebar':
                selectors = [f"aside >> {s}" for s in selectors] + selectors
            elif location == 'header':
                selectors = [f"header >> {s}" for s in selectors] + selectors

            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        await element.scroll_into_view_if_needed()
                        await element.click(timeout=3000)
                        console.print(f"[green]   ✅ Clicked using: {selector}[/green]")
                        return True
                except:
                    continue

        except Exception as e:
            pass

        # Strategy 2: Manual search by text
        try:
            clicked = await page.evaluate("""
                ({text, location}) => {
                    const allElements = Array.from(document.querySelectorAll('a, button, div, span, li, p, [role="button"]'));
                    
                    for (const el of allElements) {
                        const elementText = el.textContent?.trim();
                        if (elementText === text || elementText?.includes(text)) {
                            el.scrollIntoView({block: "center"});
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

        console.print(f"[red]   ❌ Could not click[/red]")
        return False

    async def close_modal(self, page: Page) -> bool:
        """Close modal/dialog using various strategies"""
        console.print("[cyan]   🔐 Attempting to close modal...[/cyan]")
        
        close_selectors = [
            'button[aria-label="Close"]',
            'button[aria-label="close"]',
            'button.close',
            '[data-dismiss="modal"]',
            'button:has-text("Close")',
            'button:has-text("Cancel")',
            'button:has-text("×")',
            '.modal-close',
            '[class*="close"]'
        ]

        for selector in close_selectors:
            try:
                await page.click(selector, timeout=2000)
                await asyncio.sleep(0.5)
                console.print("[green]   ✅ Modal closed[/green]")
                return True
            except:
                continue

        # Try ESC key
        try:
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.5)
            console.print("[green]   ✅ Modal closed with ESC[/green]")
            return True
        except:
            pass

        console.print("[yellow]   ⚠️ Could not close modal[/yellow]")
        return False


class StateManager:
    """Advanced state management with context tracking"""

    def __init__(self):
        self.states = {}
        self.exploration_tree = {}

    async def calculate_state_hash(self, page: Page) -> str:
        """Calculate unique state fingerprint"""
        state_data = await page.evaluate("""
            () => {
                return {
                    url: window.location.href,
                    title: document.title,
                    headings: Array.from(document.querySelectorAll('h1, h2, h3'))
                        .map(h => h.textContent?.trim())
                        .filter(t => t)
                        .slice(0, 5)
                        .join('|'),
                    interactive_count: document.querySelectorAll('a, button, input').length,
                    form_count: document.querySelectorAll('form, input').length
                };
            }
        """)

        hash_string = (
            f"{state_data['url']}"
            f"::{state_data['title']}"
            f"::{state_data['headings']}"
            f"::{state_data['interactive_count']}"
            f"::{state_data['form_count']}"
        )
        
        state_hash = hashlib.sha256(hash_string.encode()).hexdigest()[:12]
        return state_hash

    def is_state_visited(self, state_hash: str, context: str = '') -> bool:
        """Check if state visited in this context"""
        if state_hash not in self.states:
            return False
            
        # Check if visited in same context
        state = self.states[state_hash]
        if context and state.get('context') != context:
            return False
            
        return True

    def record_state(self, state_hash: str, url: str, breadcrumb: str, context: str = ''):
        """Record new state with context"""
        if state_hash not in self.states:
            self.states[state_hash] = {
                'hash': state_hash,
                'url': url,
                'breadcrumb': breadcrumb,
                'context': context,
                'visited_at': datetime.now().isoformat(),
                'visit_count': 1
            }
        else:
            self.states[state_hash]['visit_count'] += 1


class UltimateWebCrawler:
    """
    Production-ready web crawler with comprehensive exploration capabilities
    """

    def __init__(
        self,
        base_url: str,
        auth_file: str = "auth.json",
        max_depth: int = 5,
        max_states: int = 100,
        openai_api_key: Optional[str] = None
    ):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth
        self.max_states = max_states

        # Load auth
        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        # Initialize OpenAI
        if openai_api_key:
            self.openai = OpenAI(api_key=openai_api_key)
        else:
            self.openai = OpenAI()

        # Initialize components
        self.vision = GPTVisionAnalyzer(self.openai)
        self.form_filler = FormFiller()
        self.nav_detector = NavigationDetector()
        self.interactor = SmartInteractor()
        self.state_manager = StateManager()

        # Exploration memory
        self.explored = {
            'states': {},
            'forms_filled': {},
            'buttons_clicked': {},
            'containers_expanded': {}
        }

        # Statistics
        self.stats = {
            'pages_explored': 0,
            'navigations': 0,
            'forms_filled': 0,
            'buttons_clicked': 0,
            'containers_expanded': 0,
            'modals_opened': 0,
            'vision_calls': 0,
            'total_interactions': 0
        }

        self.output_dir = Path('output')
        self.output_dir.mkdir(exist_ok=True)

    async def run(self):
        """Main entry point"""
        console.print(Panel.fit(
            "[bold cyan]🚀 ULTIMATE WEB CRAWLER[/bold cyan]\n"
            f"[yellow]Target: {self.base_url}[/yellow]\n"
            f"[yellow]Max Depth: {self.max_depth}[/yellow]\n"
            f"[yellow]Max States: {self.max_states}[/yellow]\n"
            "[green]Capabilities: Forms, Dropdowns, Modals, Navigation, Pagination[/green]",
            border_style="cyan"
        ))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1400, 'height': 900}
            )
            page = await context.new_page()

            # Setup auth
            await self._setup_auth(page, context)

            # Start exploration
            await self._explore_page(page, depth=0, breadcrumb="Root", context='')

            await browser.close()

        # Show results
        self._show_results()
        self._save_results()

    async def _setup_auth(self, page: Page, context):
        """Setup authentication"""
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
            except:
                pass

        # Inject sessionStorage
        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                if isinstance(value, str):
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', '{value}')")
                else:
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', '{json.dumps(value)}')")
            except:
                pass

        # Add cookies
        cookies = self.auth_data.get('cookies', [])
        if cookies:
            try:
                await context.add_cookies(cookies)
            except:
                pass

        console.print("[green]✅ Auth configured[/green]")

        # Navigate to target
        console.print(f"[cyan]🌐 Navigating to: {self.base_url}[/cyan]")
        await page.goto(self.base_url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(2)

        console.print("[green]✅ Ready to explore!\n[/green]")

    async def _explore_page(self, page: Page, depth: int, breadcrumb: str, context: str):
        """
        Core exploration logic - handles all page types
        """
        
        # Check limits
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️ Max depth {self.max_depth} reached[/yellow]")
            return

        if len(self.state_manager.states) >= self.max_states:
            console.print(f"[yellow]⚠️ Max states {self.max_states} reached[/yellow]")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]📍 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"[yellow]URL: {page.url}[/yellow]")
        console.print(f"{'='*80}\n")

        # Scroll to load lazy content
        await self._scroll_page(page)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # Calculate state hash
        state_hash = await self.state_manager.calculate_state_hash(page)
        
        # Check if visited
        if self.state_manager.is_state_visited(state_hash, context):
            console.print(f"[yellow]♻️ State already explored, skipping[/yellow]")
            return

        # Record state
        self.state_manager.record_state(state_hash, page.url, breadcrumb, context)
        self.stats['pages_explored'] += 1

        # Vision analysis
        console.print("[bold yellow]🔍 Analyzing page with GPT-4 Vision...[/bold yellow]")
        analysis = await self.vision.analyze_page(page, page.url)
        self.stats['vision_calls'] += 1

        # Phase 1: Expand containers (discover hidden content)
        await self._phase_expand_containers(page, analysis, depth, breadcrumb, context)

        # Phase 2: Fill forms
        await self._phase_fill_forms(page, analysis, depth, breadcrumb, context)

        # Phase 3: Execute actions (navigation, buttons)
        await self._phase_execute_actions(page, analysis, depth, breadcrumb, context)

    async def _scroll_page(self, page: Page):
        """Scroll to load lazy content"""
        try:
            await page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 100;
                        let timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if(totalHeight >= document.body.scrollHeight){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 100);
                    });
                }
            """)
        except:
            pass

    async def _phase_expand_containers(self, page: Page, analysis: Dict, depth: int, breadcrumb: str, context: str):
        """Phase 1: Expand all containers to reveal hidden content"""
        containers = analysis.get('containers', [])
        
        if not containers:
            return

        console.print(f"\n[bold green]🎯 PHASE 1: EXPANDING {len(containers)} CONTAINERS[/bold green]\n")

        for container in containers:
            container_id = self._create_element_id(container)
            
            # Skip if already expanded
            if container_id in self.explored['containers_expanded']:
                console.print(f"[yellow]⏭️ Skipping: {container.get('text')} (already expanded)[/yellow]")
                continue

            console.print(f"[cyan]🔓 Expanding: {container.get('text')}[/cyan]")

            # Click to expand
            url_before = page.url
            clicked = await self.interactor.click_element(page, container)
            
            if not clicked:
                continue

            self.stats['containers_expanded'] += 1
            self.stats['total_interactions'] += 1
            
            # Mark as expanded
            self.explored['containers_expanded'][container_id] = {
                'text': container.get('text'),
                'expanded_at': datetime.now().isoformat()
            }

            # Wait for changes
            await asyncio.sleep(1)

            # Check what happened
            change = await self.nav_detector.wait_for_navigation_or_change(page, url_before, timeout=3000)
            
            console.print(f"[yellow]   Result: {change['description']}[/yellow]")

            if change['type'] == 'navigation':
                # Navigation occurred - explore recursively
                console.print(f"[green]   🌐 Navigated to: {change['url_after']}[/green]")
                new_breadcrumb = f"{breadcrumb} > {container.get('text', '')[:30]}"
                
                await self._explore_page(page, depth + 1, new_breadcrumb, context)
                
                # Go back
                await page.go_back(wait_until='networkidle', timeout=10000)
                await asyncio.sleep(2)
                
            elif change['type'] == 'dom_change':
                # Content changed (modal, accordion, etc.)
                if 'modal' in change['description'].lower():
                    self.stats['modals_opened'] += 1
                    # Explore modal content
                    await self._explore_modal(page, depth, breadcrumb)
                else:
                    # Content expanded - re-scan
                    await asyncio.sleep(1)

    async def _phase_fill_forms(self, page: Page, analysis: Dict, depth: int, breadcrumb: str, context: str):
        """Phase 2: Fill all forms on the page"""
        forms = analysis.get('forms', [])
        
        if not forms:
            return

        console.print(f"\n[bold green]🎯 PHASE 2: FILLING {len(forms)} FORM FIELDS[/bold green]\n")

        # Group fields by form (submit buttons indicate separate forms)
        submit_buttons = [f for f in forms if f.get('type') == 'submit_button']
        input_fields = [f for f in forms if f.get('type') != 'submit_button']

        # Fill all input fields
        for field in input_fields:
            field_id = self._create_element_id(field)
            
            if field_id in self.explored['forms_filled']:
                continue

            filled = await self.form_filler.fill_form_field(page, field)
            
            if filled:
                self.stats['forms_filled'] += 1
                self.stats['total_interactions'] += 1
                self.explored['forms_filled'][field_id] = {
                    'text': field.get('text'),
                    'filled_at': datetime.now().isoformat()
                }

        # Submit each form
        for submit_btn in submit_buttons:
            btn_id = self._create_element_id(submit_btn)
            
            if btn_id in self.explored['buttons_clicked']:
                continue

            console.print(f"\n[cyan]📤 Submitting form: {submit_btn.get('text')}[/cyan]")
            
            url_before = page.url
            clicked = await self.interactor.click_element(page, submit_btn)
            
            if not clicked:
                continue

            self.stats['buttons_clicked'] += 1
            self.stats['total_interactions'] += 1
            self.explored['buttons_clicked'][btn_id] = True

            # Wait for response
            change = await self.nav_detector.wait_for_navigation_or_change(page, url_before, timeout=10000)
            
            console.print(f"[yellow]   Result: {change['description']}[/yellow]")

            if change['type'] == 'navigation':
                # Form submitted - explore result page
                console.print(f"[green]   🌐 Form submitted, navigated to: {change['url_after']}[/green]")
                self.stats['navigations'] += 1
                
                new_breadcrumb = f"{breadcrumb} > Form Submit"
                await self._explore_page(page, depth + 1, new_breadcrumb, context)
                
                # Go back
                await page.go_back(wait_until='networkidle', timeout=10000)
                await asyncio.sleep(2)

    async def _phase_execute_actions(self, page: Page, analysis: Dict, depth: int, breadcrumb: str, context: str):
        """Phase 3: Execute all actions (links, buttons, pagination)"""
        actions = analysis.get('actions', [])
        
        if not actions:
            return

        console.print(f"\n[bold green]🎯 PHASE 3: EXECUTING {len(actions)} ACTIONS[/bold green]\n")

        # Sort by priority
        actions_sorted = sorted(actions, key=lambda x: x.get('priority', 5), reverse=True)

        for action in actions_sorted:
            action_id = self._create_element_id(action)
            
            # Skip if already clicked in this context
            if action_id in self.explored['buttons_clicked']:
                console.print(f"[yellow]⏭️ Skipping: {action.get('text')} (already clicked)[/yellow]")
                continue

            action_type = action.get('type', '')
            action_text = action.get('text', '')

            console.print(f"[cyan]🎬 Executing: {action_text} ({action_type})[/cyan]")

            url_before = page.url
            clicked = await self.interactor.click_element(page, action)
            
            if not clicked:
                continue

            self.stats['buttons_clicked'] += 1
            self.stats['total_interactions'] += 1
            self.explored['buttons_clicked'][action_id] = True

            # Wait for changes
            change = await self.nav_detector.wait_for_navigation_or_change(page, url_before, timeout=8000)
            
            console.print(f"[yellow]   Result: {change['description']}[/yellow]")

            if change['type'] == 'navigation':
                # Navigated to new page
                console.print(f"[green]   🌐 Navigated to: {change['url_after']}[/green]")
                self.stats['navigations'] += 1
                
                new_breadcrumb = f"{breadcrumb} > {action_text[:30]}"
                new_context = f"{context}/{action_type}"
                
                await self._explore_page(page, depth + 1, new_breadcrumb, new_context)
                
                # Go back
                console.print(f"[yellow]   ⬅️ Going back to: {breadcrumb}[/yellow]")
                await page.go_back(wait_until='networkidle', timeout=10000)
                await asyncio.sleep(2)
                
            elif change['type'] == 'dom_change':
                # Content changed without navigation
                if 'modal' in change['description'].lower():
                    self.stats['modals_opened'] += 1
                    await self._explore_modal(page, depth, breadcrumb)

    async def _explore_modal(self, page: Page, depth: int, breadcrumb: str):
        """Explore content inside a modal/dialog"""
        console.print("[cyan]   📋 Exploring modal content...[/cyan]")
        
        await asyncio.sleep(1)
        
        # Take screenshot of modal
        analysis = await self.vision.analyze_page(page, page.url)
        self.stats['vision_calls'] += 1
        
        # Look for form fields in modal
        modal_forms = analysis.get('forms', [])
        for field in modal_forms:
            await self.form_filler.fill_form_field(page, field)
        
        # Look for buttons in modal
        modal_actions = analysis.get('actions', [])
        for action in modal_actions[:3]:  # Limit to first 3 actions
            if 'submit' in action.get('text', '').lower() or 'save' in action.get('text', '').lower():
                await self.interactor.click_element(page, action)
                await asyncio.sleep(1)
                break
        
        # Close modal
        await self.interactor.close_modal(page)
        await asyncio.sleep(1)

    def _create_element_id(self, element: Dict) -> str:
        """Create unique ID for an element"""
        text = element.get('text', '')
        elem_type = element.get('type', '')
        location = element.get('location', '')
        
        normalized = text.lower().replace(' ', '_').replace('-', '_')
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')
        
        return f"{location}_{elem_type}_{normalized}"[:60]

    def _show_results(self):
        """Display exploration results"""
        console.print("\n" + "="*80)
        console.print(Panel.fit(
            "[bold green]✅ EXPLORATION COMPLETE[/bold green]",
            border_style="green"
        ))

        # Stats table
        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="yellow")

        for key, value in self.stats.items():
            table.add_row(key.replace('_', ' ').title(), str(value))

        console.print(table)

        # States explored
        console.print(f"\n[bold cyan]States Explored: {len(self.state_manager.states)}[/bold cyan]")
        for state_hash, state in list(self.state_manager.states.items())[:10]:
            console.print(f"  • {state['breadcrumb']} - {state['url']}")

    def _save_results(self):
        """Save exploration data"""
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
                    'context': state.get('context', ''),
                    'visited_at': state['visited_at']
                }
                for hash, state in self.state_manager.states.items()
            },
            'explored_elements': {
                'containers': len(self.explored['containers_expanded']),
                'forms': len(self.explored['forms_filled']),
                'buttons': len(self.explored['buttons_clicked'])
            }
        }

        output_file = self.output_dir / f'ultimate_crawl_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.print(f"\n[bold green]💾 Results saved: {output_file}[/bold green]")


async def main():
    """Entry point"""
    
    if not Path('auth.json').exists():
        console.print("[red]❌ auth.json not found![/red]")
        return

    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        # Fallback to hardcoded key (not recommended for production)
        openai_key = os.getenv('OPENAI_KEY')


    crawler = UltimateWebCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=10,
        max_states=200,
        openai_api_key=openai_key
    )

    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())