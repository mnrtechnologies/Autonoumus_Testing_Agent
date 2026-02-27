"""
Semantic Driver - LLM-Driven Adaptive Web Testing
Architecture: LLM decides WHAT, Code decides HOW
No selector hallucinations. No syntax errors. Pure intelligence.
"""
import asyncio
import json
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, Locator
from openai import OpenAI
import os
from dotenv import load_dotenv


load_dotenv()
# ═══════════════════════════════════════════════════════════════
#  LAYER 1: DOM SIMPLIFIER
#  Converts messy HTML into clean interactive-only structure
# ═══════════════════════════════════════════════════════════════

class DOMSimplifier:
    """Strips DOM to only interactive elements"""

    @staticmethod
    async def get_interactive_dom(page: Page) -> List[Dict]:
        """Extract clean list of interactive elements"""

        dom_elements = await page.evaluate("""() => {
            const interactive = [];
            const selectors = [
                'button',
                'a[href]',
                'input',
                'select',
                'textarea',
                '[role="button"]',
                '[role="menuitem"]',
                '[role="tab"]',
                '[role="link"]',
                '[type="checkbox"]',
                '[type="radio"]'
            ];

            const seen = new Set();

            document.querySelectorAll(selectors.join(',')).forEach((el, idx) => {
                // Skip hidden elements
                if (!el.offsetParent && el.type !== 'hidden') return;

                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;

                // Extract meaningful info
                const text = (
                    el.innerText ||
                    el.value ||
                    el.placeholder ||
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    ''
                ).trim().slice(0, 100);

                const id = el.id || '';
                const classes = el.className && typeof el.className === 'string'
                    ? el.className.split(' ').filter(c => c.length > 0).slice(0, 3)
                    : [];

                const tag = el.tagName.toLowerCase();
                const type = el.type || '';
                const role = el.getAttribute('role') || '';
                const href = el.getAttribute('href') || '';

                // Create unique key
                const key = `${tag}:${text}:${id}`;
                if (seen.has(key)) return;
                seen.add(key);

                interactive.push({
                    index: interactive.length,
                    tag,
                    type,
                    role,
                    text,
                    id,
                    classes,
                    href,
                    enabled: !el.disabled,
                    visible: true,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                });
            });

            return interactive;
        }""")

        return dom_elements


# ═══════════════════════════════════════════════════════════════
#  LAYER 2: SEMANTIC CONTROLLER
#  Translates semantic intent to Playwright locators
# ═══════════════════════════════════════════════════════════════

class SemanticController:
    """
    The Translator: Converts LLM intent into working Playwright locators
    Uses Waterfall Strategy - tries methods in order until one works
    """

    def __init__(self, page: Page):
        self.page = page

    async def find_element(self, intent: Dict) -> Tuple[Optional[Locator], str]:
        """
        Find element based on semantic intent
        Returns: (Locator, method_used) or (None, error)
        """

        target_name = intent.get('target_name', '')
        element_type = intent.get('element_type', '')
        visual_hint = intent.get('visual_hint', '')

        if not target_name:
            return None, "No target_name provided"

        print(f"\n  🔍 Finding: '{target_name}' (type: {element_type})")

        # STRATEGY A: Role-based (most semantic)
        if element_type in ['button', 'link', 'checkbox', 'radio', 'textbox']:
            locator, method = await self._try_by_role(target_name, element_type)
            if locator:
                return locator, method

        # STRATEGY B: Text-based (most common)
        locator, method = await self._try_by_text(target_name)
        if locator:
            return locator, method

        # STRATEGY C: Placeholder/Label (for inputs)
        if element_type in ['input', 'textbox', 'select']:
            locator, method = await self._try_by_placeholder_or_label(target_name)
            if locator:
                return locator, method

        # STRATEGY D: Partial text match (fuzzy)
        locator, method = await self._try_by_partial_text(target_name)
        if locator:
            return locator, method

        # STRATEGY E: XPath (last resort)
        locator, method = await self._try_by_xpath(target_name, element_type)
        if locator:
            return locator, method

        return None, f"Element not found after all strategies: {target_name}"

    async def _try_by_role(self, name: str, role: str) -> Tuple[Optional[Locator], str]:
        """Strategy A: get_by_role"""
        try:
            # Map element_type to ARIA role
            role_map = {
                'button': 'button',
                'link': 'link',
                'checkbox': 'checkbox',
                'radio': 'radio',
                'textbox': 'textbox',
                'input': 'textbox'
            }

            aria_role = role_map.get(role, role)

            # Try exact match
            locator = self.page.get_by_role(aria_role, name=name, exact=True)
            if await locator.count() > 0:
                print(f"    ✓ Found via role (exact): get_by_role('{aria_role}', name='{name}')")
                return locator.first, f"role_exact:{aria_role}"

            # Try non-exact match
            locator = self.page.get_by_role(aria_role, name=name, exact=False)
            if await locator.count() > 0:
                print(f"    ✓ Found via role (fuzzy): get_by_role('{aria_role}', name~'{name}')")
                return locator.first, f"role_fuzzy:{aria_role}"

        except Exception as e:
            pass

        return None, ""

    async def _try_by_text(self, text: str) -> Tuple[Optional[Locator], str]:
        """Strategy B: get_by_text"""
        try:
            # Try exact match
            locator = self.page.get_by_text(text, exact=True)
            if await locator.count() > 0:
                print(f"    ✓ Found via text (exact): get_by_text('{text}')")
                return locator.first, "text_exact"

        except Exception:
            pass

        return None, ""

    async def _try_by_placeholder_or_label(self, text: str) -> Tuple[Optional[Locator], str]:
        """Strategy C: get_by_placeholder or get_by_label"""
        try:
            # Try placeholder
            locator = self.page.get_by_placeholder(text, exact=False)
            if await locator.count() > 0:
                print(f"    ✓ Found via placeholder: get_by_placeholder('{text}')")
                return locator.first, "placeholder"

            # Try label
            locator = self.page.get_by_label(text, exact=False)
            if await locator.count() > 0:
                print(f"    ✓ Found via label: get_by_label('{text}')")
                return locator.first, "label"

        except Exception:
            pass

        return None, ""

    async def _try_by_partial_text(self, text: str) -> Tuple[Optional[Locator], str]:
        """Strategy D: Fuzzy text match"""
        try:
            # Case-insensitive partial match
            locator = self.page.get_by_text(text, exact=False)
            if await locator.count() > 0:
                print(f"    ✓ Found via partial text: get_by_text(~'{text}')")
                return locator.first, "text_partial"

        except Exception:
            pass

        return None, ""

    async def _try_by_xpath(self, text: str, element_type: str) -> Tuple[Optional[Locator], str]:
        """Strategy E: XPath (last resort)"""
        try:
            # Build XPath based on element type
            if element_type == 'button':
                xpath = f"//button[contains(text(), '{text}')]"
            elif element_type == 'link':
                xpath = f"//a[contains(text(), '{text}')]"
            elif element_type == 'input':
                xpath = f"//input[@placeholder='{text}' or @aria-label='{text}']"
            else:
                xpath = f"//*[contains(text(), '{text}')]"

            locator = self.page.locator(f"xpath={xpath}")
            if await locator.count() > 0:
                print(f"    ✓ Found via XPath: {xpath}")
                return locator.first, "xpath"

        except Exception:
            pass

        return None, ""


# ═══════════════════════════════════════════════════════════════
#  LAYER 3: EXECUTION ENGINE
#  Safely executes actions with retry logic
# ═══════════════════════════════════════════════════════════════

class ExecutionEngine:
    """
    The Body: Executes actions safely with verification
    """

    def __init__(self, page: Page):
        self.page = page

    async def execute_action(self, locator: Locator, action: str, value: Optional[str] = None) -> Dict:
        """
        Execute an action on a locator
        Returns: execution result
        """

        result = {
            "success": False,
            "action": action,
            "error": None,
            "state_changed": False
        }

        try:
            # Pre-check: is element ready?
            if not await self._is_element_ready(locator):
                result["error"] = "Element not ready (not visible or enabled)"
                return result

            # Capture before state
            before_hash = await self._get_state_hash()
            before_url = self.page.url

            # Execute action
            if action == "click":
                await locator.scroll_into_view_if_needed(timeout=5000)
                await locator.click(timeout=5000)
                print(f"    ✓ Clicked element")

            elif action == "fill":
                await locator.fill(value or "TestValue_Semantic", timeout=5000)
                print(f"    ✓ Filled: {value or 'TestValue_Semantic'}")

            elif action == "select":
                if value and value.isdigit():
                    await locator.select_option(index=int(value), timeout=5000)
                else:
                    await locator.select_option(value=value or "", timeout=5000)
                print(f"    ✓ Selected option")

            elif action == "check":
                await locator.check(timeout=5000)
                print(f"    ✓ Checked")

            elif action == "uncheck":
                await locator.uncheck(timeout=5000)
                print(f"    ✓ Unchecked")

            else:
                result["error"] = f"Unknown action: {action}"
                return result

            # Wait for effects
            await asyncio.sleep(1.5)

            # Check if state changed
            after_hash = await self._get_state_hash()
            after_url = self.page.url

            result["success"] = True
            result["state_changed"] = (after_hash != before_hash) or (after_url != before_url)
            result["url_changed"] = after_url != before_url
            result["new_url"] = after_url if after_url != before_url else None

            print(f"    📊 State changed: {result['state_changed']}")

        except Exception as e:
            result["error"] = str(e)
            print(f"    ❌ Execution failed: {e}")

        return result

    async def _is_element_ready(self, locator: Locator) -> bool:
        """Check if element is visible and enabled"""
        try:
            await locator.wait_for(state="visible", timeout=3000)
            is_visible = await locator.is_visible()
            is_enabled = await locator.is_enabled()
            return is_visible and is_enabled
        except:
            return False

    async def _get_state_hash(self) -> str:
        """Get hash of current DOM state"""
        try:
            html = await self.page.evaluate("document.body.innerHTML")
            return hashlib.md5(html.encode()).hexdigest()
        except:
            return ""


# ═══════════════════════════════════════════════════════════════
#  LAYER 4: AGENT BRAIN
#  LLM decides WHAT to do based on observation
# ═══════════════════════════════════════════════════════════════

class AgentBrain:
    """
    The General: Makes decisions about WHAT to test
    Does NOT generate code or selectors
    """

    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client

    async def observe(self, screenshot_b64: str, dom_elements: List[Dict],
                     memory: List[Dict]) -> Dict:
        """
        LLM observes current state
        Returns: observation with untested elements
        """

        memory_summary = self._format_memory(memory)

        prompt = f"""You are observing a web application to test it systematically.

INTERACTIVE ELEMENTS ON SCREEN:
{json.dumps(dom_elements[:30], indent=2)}

TESTING MEMORY (what we've tested):
{memory_summary}

Analyze what you see and answer:
1. What is the current page/state?
2. Which elements have NOT been tested yet?
3. Are there modals/dropdowns/forms open?
4. Is testing complete?

Return ONLY valid JSON:
{{
  "current_state": "vendor list page with 3 rows visible",
  "state_type": "page|modal|form|menu|error",
  "untested_elements": [
    {{"name": "Tambah", "type": "button", "description": "add new vendor"}},
    {{"name": "Cari", "type": "button", "description": "search vendors"}}
  ],
  "open_overlays": ["modal with form" or "dropdown menu" or null],
  "all_tested": false,
  "notes": "any observations"
}}"""

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
            observation = json.loads(self._extract_json(raw))
            return observation

        except Exception as e:
            print(f"  ⚠️  Observation failed: {e}")
            return {"all_tested": False, "untested_elements": []}

    async def plan(self, screenshot_b64: str, observation: Dict, memory: List[Dict]) -> Dict:
        """
        LLM decides WHAT to test next
        Returns: semantic intent (NOT code)
        """

        untested = observation.get('untested_elements', [])
        state_type = observation.get('state_type', 'page')
        overlays = observation.get('open_overlays')

        if not untested:
            return {"action": "stop", "reason": "nothing left to test"}

        memory_summary = self._format_memory(memory)

        prompt = f"""You are planning the next test action.

CURRENT STATE: {observation.get('current_state', 'unknown')}
STATE TYPE: {state_type}
OPEN OVERLAYS: {overlays}

UNTESTED ELEMENTS:
{json.dumps(untested, indent=2)}

RECENT ACTIONS:
{memory_summary}

Priority rules:
1. If overlay (modal/form/dropdown) is open, test its elements first
2. Test forms and primary buttons before secondary actions
3. Test destructive actions (delete) LAST
4. If in form, fill all fields before submitting

Pick ONE element to test next.

Return ONLY valid JSON:
{{
  "action": "click|fill|select|check",
  "target_name": "exact name/text of element (e.g. 'Tambah' or 'Cari')",
  "element_type": "button|input|link|checkbox|select",
  "test_value": "if fill/select, what value to use",
  "visual_hint": "any visual clues (color, position)",
  "priority": "high|medium|low",
  "reasoning": "why test this element now"
}}

If you need to close an overlay first:
{{
  "action": "close_overlay",
  "target_name": "close button or Cancel",
  "reasoning": "need to close modal before continuing"
}}"""

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
                max_tokens=1500,
                temperature=0.2
            )

            raw = response.choices[0].message.content
            plan = json.loads(self._extract_json(raw))
            return plan

        except Exception as e:
            print(f"  ⚠️  Planning failed: {e}")
            return {"action": "stop", "reason": f"planning error: {e}"}

    async def adapt(self, screenshot_b64: str, plan: Dict, execution_result: Dict) -> Dict:
        """
        LLM evaluates what happened and learns
        """

        prompt = f"""You just executed a test action. Analyze the result.

PLAN:
{json.dumps(plan, indent=2)}

EXECUTION RESULT:
{json.dumps(execution_result, indent=2)}

Look at the screenshot and tell me:
1. Did it succeed?
2. What is the NEW state?
3. Any new elements that appeared?
4. Need recovery?

Return ONLY valid JSON:
{{
  "success_assessment": "succeeded|failed|partial",
  "new_state_description": "what changed",
  "new_elements_appeared": [{{"name": "X", "type": "button"}}],
  "needs_recovery": false,
  "recovery_action": "if true, suggest: close_modal|go_back|refresh",
  "learning": "what we learned"
}}"""

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
                max_tokens=1000,
                temperature=0.1
            )

            raw = response.choices[0].message.content
            adaptation = json.loads(self._extract_json(raw))
            return adaptation

        except Exception as e:
            print(f"  ⚠️  Adaptation failed: {e}")
            return {"success_assessment": "unknown", "needs_recovery": False}

    def _format_memory(self, memory: List[Dict]) -> str:
        """Format recent memory for LLM"""
        if not memory:
            return "No history yet."

        recent = memory[-10:]
        lines = []
        for m in recent:
            plan = m.get('plan', {})
            result = m.get('execution_result', {})
            lines.append(
                f"- {plan.get('action', '?')} on '{plan.get('target_name', '?')}' "
                f"→ {'✓' if result.get('success') else '✗'}"
            )
        return "\n".join(lines)

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
#  MAIN ORCHESTRATOR
#  Connects all layers
# ═══════════════════════════════════════════════════════════════

class SemanticTester:
    """
    Main orchestrator - connects Brain, Controller, Engine
    """

    def __init__(self, openai_api_key: str, auth_file: str = "auth.json"):
        self.openai = OpenAI(api_key=openai_api_key)

        # Load auth
        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        # Session
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path('semantic_test_output')
        self.output_dir.mkdir(exist_ok=True)

        # Memory
        self.memory: List[Dict] = []
        self.step_counter = 0

        # Components
        self.brain: Optional[AgentBrain] = None
        self.controller: Optional[SemanticController] = None
        self.engine: Optional[ExecutionEngine] = None
        self.dom_simplifier = DOMSimplifier()

        print(f"\n{'='*80}")
        print("🧠 SEMANTIC DRIVER - LLM Decides, Code Executes")
        print(f"{'='*80}")
        print(f"Session: {self.session_id}")
        print(f"{'='*80}\n")

    async def run_test(self, target_url: str):
        """Main entry point"""

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1400, 'height': 900})
            page = await context.new_page()

            # Initialize components with page
            self.brain = AgentBrain(self.openai)
            self.controller = SemanticController(page)
            self.engine = ExecutionEngine(page)

            try:
                print("[1/3] 🔑 Injecting authentication...")
                await self._inject_auth(page, context, target_url)

                print(f"\n[2/3] 🌐 Navigating to {target_url}...")
                await page.goto(target_url, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)

                print(f"\n[3/3] 🚀 Starting semantic testing loop...\n")
                await self._testing_loop(page)

            except Exception as e:
                print(f"\n❌ Fatal error: {e}")
                import traceback
                traceback.print_exc()
                await self._capture_screenshot(page, "fatal_error")

            finally:
                self._save_results()
                input("\n👁️  Browser open. Press Enter to close...")
                await browser.close()

    async def _testing_loop(self, page: Page):
        """Main testing loop"""

        max_iterations = 50
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            self.step_counter += 1

            print(f"\n{'='*80}")
            print(f"ITERATION {iteration}")
            print(f"{'='*80}")

            # PHASE 1: OBSERVE
            print("\n[OBSERVE] 👁️  LLM analyzing current state...")
            screenshot_b64 = await self._get_screenshot_b64(page, f"observe_{self.step_counter}")
            dom_elements = await self.dom_simplifier.get_interactive_dom(page)

            observation = await self.brain.observe(screenshot_b64, dom_elements, self.memory)

            print(f"  State: {observation.get('current_state', 'unknown')}")
            print(f"  Untested: {len(observation.get('untested_elements', []))}")

            if observation.get('all_tested'):
                print("\n✅ Testing complete!")
                break

            # PHASE 2: PLAN
            print("\n[PLAN] 🧠 LLM deciding next action...")
            plan = await self.brain.plan(screenshot_b64, observation, self.memory)

            if plan.get('action') == 'stop':
                print("\n🛑 Testing stopped")
                break

            print(f"  Action: {plan.get('action')}")
            print(f"  Target: {plan.get('target_name')}")
            print(f"  Reasoning: {plan.get('reasoning', 'N/A')}")

            # PHASE 3: TRANSLATE
            print("\n[TRANSLATE] 🔧 Finding element...")
            locator, method = await self.controller.find_element(plan)

            if not locator:
                print(f"  ❌ {method}")
                # Store failure and continue
                self.memory.append({
                    "step": self.step_counter,
                    "plan": plan,
                    "execution_result": {"success": False, "error": method}
                })
                continue

            print(f"  ✓ Found via: {method}")

            # PHASE 4: EXECUTE
            print("\n[EXECUTE] ⚡ Performing action...")
            execution_result = await self.engine.execute_action(
                locator,
                plan.get('action'),
                plan.get('test_value')
            )

            # Capture after state
            await asyncio.sleep(1)
            after_screenshot_b64 = await self._get_screenshot_b64(page, f"after_{self.step_counter}")

            # PHASE 5: ADAPT
            print("\n[ADAPT] 🔄 LLM evaluating result...")
            adaptation = await self.brain.adapt(after_screenshot_b64, plan, execution_result)

            print(f"  Assessment: {adaptation.get('success_assessment', 'unknown')}")
            print(f"  Learning: {adaptation.get('learning', 'none')}")

            # Store in memory
            self.memory.append({
                "step": self.step_counter,
                "plan": plan,
                "execution_result": execution_result,
                "adaptation": adaptation,
                "timestamp": datetime.now().isoformat()
            })

            # Recovery if needed
            if adaptation.get('needs_recovery'):
                print(f"  🚨 Recovery: {adaptation.get('recovery_action', 'unknown')}")
                await self._perform_recovery(page, adaptation.get('recovery_action'))

            await asyncio.sleep(0.5)

        print(f"\n{'='*80}")
        print(f"🏁 Testing complete after {iteration} iterations")
        print(f"{'='*80}")

    async def _perform_recovery(self, page: Page, action: str):
        """Perform recovery action"""
        if action == "close_modal":
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)
        elif action == "go_back":
            await page.go_back()
            await asyncio.sleep(2)
        elif action == "refresh":
            await page.reload()
            await asyncio.sleep(2)

    async def _inject_auth(self, page: Page, context, target_url: str):
        """Inject authentication"""
        parsed = urlparse(target_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"

        await page.goto(homepage)
        await page.wait_for_load_state('networkidle')

        # localStorage
        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"window.localStorage.setItem('{key}', `{val}`)")
                print(f"  ✓ localStorage: {key}")
            except Exception as e:
                print(f"  ✗ localStorage: {key} - {e}")

        # sessionStorage
        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"window.sessionStorage.setItem('{key}', `{val}`)")
                print(f"  ✓ sessionStorage: {key}")
            except Exception as e:
                print(f"  ✗ sessionStorage: {key} - {e}")

        # Cookies
        cookies = self.auth_data.get('cookies', [])
        if cookies:
            await context.add_cookies(cookies)
            print(f"  ✓ Cookies: {len(cookies)}")

        print("  ✅ Auth injected\n")

    async def _get_screenshot_b64(self, page: Page, name: str) -> str:
        """Capture screenshot and return base64"""
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            await page.screenshot(path=path, full_page=False)
            with open(path, 'rb') as f:
                return base64.b64encode(f.read()).decode()
        except Exception as e:
            print(f"  ⚠️  Screenshot failed: {e}")
            return ""

    async def _capture_screenshot(self, page: Page, name: str):
        """Just capture screenshot"""
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            await page.screenshot(path=path, full_page=False)
        except:
            pass

    def _save_results(self):
        """Save session results"""
        results = {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "total_steps": self.step_counter,
            "memory": self.memory
        }

        out_file = self.output_dir / f"semantic_test_{self.session_id}.json"
        with open(out_file, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\n💾 Results: {out_file}")

        # Summary
        successful = sum(1 for m in self.memory
                        if m.get('execution_result', {}).get('success'))
        print(f"\n📊 SUMMARY")
        print(f"  Total actions: {len(self.memory)}")
        print(f"  Successful: {successful}")
        print(f"  Failed: {len(self.memory) - successful}")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def main():
    if not Path('auth.json').exists():
        print("❌ auth.json not found!")
        return

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        print("❌ OPENAI_API_KEY not set!")
        return

    tester = SemanticTester(openai_api_key=openai_key, auth_file="auth.json")

    print("\n" + "="*80)
    print("🧠 SEMANTIC DRIVER")
    print("="*80)

    target_url = input("\nEnter URL to test: ").strip()

    if not target_url:
        print("❌ No URL provided")
        return

    await tester.run_test(target_url)


if __name__ == "__main__":
    asyncio.run(main())