"""
Semantic Driver - Final Production Version
Architecture: Observer → Memory → Decider → Executor (OMDE Loop)

Key Features:
1. Focused Testing: Stays on target page, doesn't navigate away
2. Context-aware: Handles modals, forms, tables intelligently
3. Loop Detection: Prevents infinite loops
4. Smart Element Detection: Filters navigation links in focused mode
"""
import asyncio
import json
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from enum import Enum

from playwright.async_api import async_playwright, Page, Locator
from openai import OpenAI


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
    tested_elements: List[str] = field(default_factory=list)
    
    def mark_tested(self, element_name: str):
        if element_name and element_name not in self.tested_elements:
            self.tested_elements.append(element_name)


# ═══════════════════════════════════════════════════════════════
#  SCOPE MANAGER - Prevents unwanted navigation
# ═══════════════════════════════════════════════════════════════

class ScopeManager:
    """
    Controls what can be tested based on target URL
    FOCUSED MODE: Only tests the exact page provided
    """
    
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
        """
        Check if element should be tested
        Returns: (in_scope, reason)
        """
        
        tag = element.get('tag', '')
        href = element.get('href', '')
        text = element.get('text', '').strip()
        classes = ' '.join(element.get('classes', [])).lower()
        
        # Skip navigation links that would leave the page
        if tag == 'a' and href:
            absolute_url = urljoin(current_url, href)
            target_path = urlparse(absolute_url).path
            
            # If link goes to different page, skip it
            if target_path != self.target_path:
                return False, f"Navigation link to different page: {target_path}"
        
        # Skip sidebar/menu navigation elements
        nav_indicators = ['sidebar', 'sidenav', 'menu-item', 'nav-link']
        if any(indicator in classes for indicator in nav_indicators):
            if tag == 'a':
                return False, "Sidebar/menu navigation link"
        
        # Skip if element text suggests navigation
        nav_texts = ['halaman utama', 'dashboard', 'home', 'beranda']
        if text.lower() in nav_texts and tag == 'a':
            return False, f"Navigation link: {text}"
        
        return True, "In scope"


# ═══════════════════════════════════════════════════════════════
#  CONTEXT STACK - Memory system
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
    
    @staticmethod
    async def get_elements(page: Page) -> Dict[str, Any]:
        """Extract interactive elements with overlay detection"""
        
        result = await page.evaluate("""() => {
            const interactive = [];
            const selectors = [
                'button',
                'a[href]',
                'input:not([type="hidden"])',
                'select',
                'textarea',
                '[role="button"]',
                '[role="menuitem"]',
                '[role="tab"]',
                '[type="checkbox"]',
                '[type="radio"]'
            ];
            
            // Detect overlays
            const overlaySelectors = [
                '.modal.show',
                '.modal.active',
                '[role="dialog"]',
                '[role="alertdialog"]',
                '[aria-modal="true"]',
                '.dialog.open',
                '.popup.visible',
                '.dropdown-menu.show'
            ];
            
            let activeOverlay = null;
            let maxZIndex = -1;
            
            for (const sel of overlaySelectors) {
                document.querySelectorAll(sel).forEach(overlay => {
                    if (!overlay.offsetParent) return;
                    const rect = overlay.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;
                    
                    const style = window.getComputedStyle(overlay);
                    const zIndex = parseInt(style.zIndex) || 0;
                    
                    if (zIndex > maxZIndex || !activeOverlay) {
                        maxZIndex = zIndex;
                        activeOverlay = overlay;
                    }
                });
            }
            
            const seen = new Set();
            
            document.querySelectorAll(selectors.join(',')).forEach((el) => {
                if (!el.offsetParent && el.type !== 'hidden') return;
                
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                
                const isInOverlay = activeOverlay ? activeOverlay.contains(el) : false;
                const isBlocked = activeOverlay && !isInOverlay;
                
                const text = (
                    el.innerText || 
                    el.value || 
                    el.placeholder || 
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.getAttribute('name') ||
                    ''
                ).trim().slice(0, 150);
                
                const id = el.id || '';
                const name = el.getAttribute('name') || '';
                const classes = el.className && typeof el.className === 'string' 
                    ? el.className.split(' ').filter(c => c.length > 0).slice(0, 5)
                    : [];
                
                const tag = el.tagName.toLowerCase();
                const type = el.type || '';
                const role = el.getAttribute('role') || '';
                const href = el.getAttribute('href') || '';
                const required = el.hasAttribute('required');
                
                const key = `${tag}:${text}:${id}:${name}`;
                if (seen.has(key)) return;
                seen.add(key);
                
                interactive.push({
                    tag,
                    type,
                    role,
                    text,
                    id,
                    name,
                    classes,
                    href,
                    required,
                    enabled: !el.disabled,
                    blocked: isBlocked,
                    in_overlay: isInOverlay,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y)
                });
            });
            
            let overlayType = null;
            if (activeOverlay) {
                const overlayText = activeOverlay.innerText.toLowerCase();
                if (overlayText.includes('confirm') || overlayText.includes('yakin')) {
                    overlayType = 'confirmation';
                } else if (activeOverlay.querySelector('form') || activeOverlay.querySelector('input')) {
                    overlayType = 'form';
                } else {
                    overlayType = 'info';
                }
            }
            
            return {
                has_overlay: !!activeOverlay,
                overlay_type: overlayType,
                active_elements: interactive.filter(e => !e.blocked),
                blocked_elements: interactive.filter(e => e.blocked)
            };
        }""")
        
        return result
    
    @staticmethod
    async def detect_context(page: Page, elements_data: Dict) -> ContextType:
        """Determine context type"""
        
        if elements_data.get('has_overlay'):
            overlay_type = elements_data.get('overlay_type')
            if overlay_type == 'confirmation':
                return ContextType.CONFIRMATION
            elif overlay_type == 'form':
                return ContextType.FORM
            else:
                return ContextType.MODAL
        
        active = elements_data.get('active_elements', [])
        has_inputs = any(e.get('tag') == 'input' for e in active)
        has_submit = any('submit' in e.get('text', '').lower() or 'save' in e.get('text', '').lower() or 'simpan' in e.get('text', '').lower() for e in active)
        
        if has_inputs and has_submit:
            return ContextType.FORM
        
        has_table = await page.evaluate("() => document.querySelectorAll('table, .table, [role=grid]').length > 0")
        if has_table:
            return ContextType.TABLE
        
        return ContextType.PAGE


# ═══════════════════════════════════════════════════════════════
#  DECIDER - Intelligent decision making
# ═══════════════════════════════════════════════════════════════

class Decider:
    
    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client
    
    async def decide(
        self,
        screenshot_b64: str,
        context_frame: ContextFrame,
        elements: List[Dict]
    ) -> Dict:
        """Make next action decision"""
        
        untested = [e for e in elements if e.get('text', '') not in context_frame.tested_elements]
        
        if not untested:
            return {"action": "done", "reasoning": "All elements tested"}
        
        prompt = self._build_prompt(context_frame.context_type, untested)
        
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o",
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
            decision = json.loads(self._extract_json(raw))
            return decision
            
        except Exception as e:
            print(f"  ⚠️  Decision failed: {e}")
            if untested:
                elem = untested[0]
                return {
                    "action": "click",
                    "target_name": elem.get('text', 'element'),
                    "element_type": elem.get('tag', 'button'),
                    "reasoning": "Fallback"
                }
            return {"action": "wait"}
    
    def _build_prompt(self, context_type: ContextType, untested: List[Dict]) -> str:
        
        prompt = f"""You are testing a web page. Choose ONE action.

CONTEXT: {context_type.value}
UNTESTED ELEMENTS ({len(untested)} remaining):
{json.dumps(untested[:15], indent=2)}
"""
        
        if context_type == ContextType.CONFIRMATION:
            prompt += "\nPRIORITY: Click Confirm/Yes/OK or Cancel based on safety"
        
        elif context_type == ContextType.FORM:
            prompt += "\nPRIORITY: Fill required fields first, then submit"
        
        elif context_type == ContextType.MODAL:
            prompt += "\nPRIORITY: Test modal contents before closing"
        
        elif context_type == ContextType.TABLE:
            prompt += "\nPRIORITY: Test search, then row actions, then create/delete"
        
        else:
            prompt += "\nPRIORITY: Test interactive elements on the page"
        
        prompt += """

Return ONLY valid JSON:
{
  "action": "click|fill|select|check",
  "target_name": "exact element text",
  "element_type": "button|input|link|select",
  "test_value": "value if filling",
  "reasoning": "why this action (1 sentence)"
}"""
        
        return prompt
    
    def _extract_json(self, text: str) -> str:
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
#  CONTROLLER - Translates intent to locators
# ═══════════════════════════════════════════════════════════════

class Controller:
    
    def __init__(self, page: Page):
        self.page = page
    
    async def find(self, intent: Dict) -> Tuple[Optional[Locator], str]:
        """Find element based on intent"""
        
        target = intent.get('target_name', '')
        elem_type = intent.get('element_type', '')
        
        if not target:
            return None, "No target"
        
        print(f"  🔍 Finding: '{target}' ({elem_type})")
        
        # Strategy 1: Role
        if elem_type in ['button', 'link', 'checkbox', 'radio', 'textbox']:
            loc = await self._by_role(target, elem_type)
            if loc: return loc, "role"
        
        # Strategy 2: Text
        loc = await self._by_text(target)
        if loc: return loc, "text"
        
        # Strategy 3: Placeholder/Label
        if elem_type in ['input', 'textbox', 'select']:
            loc = await self._by_placeholder_label(target)
            if loc: return loc, "placeholder/label"
        
        # Strategy 4: Partial text
        loc = await self._by_partial_text(target)
        if loc: return loc, "partial_text"
        
        return None, "Not found"
    
    async def _by_role(self, name: str, role: str) -> Optional[Locator]:
        try:
            role_map = {'button': 'button', 'link': 'link', 'checkbox': 'checkbox', 
                       'radio': 'radio', 'textbox': 'textbox', 'input': 'textbox'}
            aria_role = role_map.get(role, role)
            
            loc = self.page.get_by_role(aria_role, name=name, exact=True)
            if await loc.count() > 0:
                return loc.first
            
            loc = self.page.get_by_role(aria_role, name=name, exact=False)
            if await loc.count() > 0:
                return loc.first
        except:
            pass
        return None
    
    async def _by_text(self, text: str) -> Optional[Locator]:
        try:
            loc = self.page.get_by_text(text, exact=True)
            if await loc.count() > 0:
                return loc.first
        except:
            pass
        return None
    
    async def _by_placeholder_label(self, text: str) -> Optional[Locator]:
        try:
            loc = self.page.get_by_placeholder(text, exact=False)
            if await loc.count() > 0:
                return loc.first
            
            loc = self.page.get_by_label(text, exact=False)
            if await loc.count() > 0:
                return loc.first
        except:
            pass
        return None
    
    async def _by_partial_text(self, text: str) -> Optional[Locator]:
        try:
            loc = self.page.get_by_text(text, exact=False)
            if await loc.count() > 0:
                return loc.first
        except:
            pass
        return None


# ═══════════════════════════════════════════════════════════════
#  EXECUTOR - Executes actions safely
# ═══════════════════════════════════════════════════════════════

class Executor:
    
    def __init__(self, page: Page):
        self.page = page
    
    async def execute(self, locator: Locator, action: str, value: Optional[str] = None) -> Dict:
        """Execute action"""
        
        result = {"success": False, "action": action, "error": None}
        
        try:
            await locator.wait_for(state="visible", timeout=3000)
            
            if action == "click":
                await locator.scroll_into_view_if_needed(timeout=5000)
                await locator.click(timeout=5000)
                print(f"    ✓ Clicked")
                
            elif action == "fill":
                await locator.fill(value or "TestValue", timeout=5000)
                print(f"    ✓ Filled: {value}")
                
            elif action == "select":
                await locator.select_option(value=value or "0", timeout=5000)
                print(f"    ✓ Selected")
                
            elif action == "check":
                await locator.check(timeout=5000)
                print(f"    ✓ Checked")
            
            await asyncio.sleep(1.5)
            result["success"] = True
            
        except Exception as e:
            result["error"] = str(e)
            print(f"    ❌ Failed: {e}")
        
        return result


# ═══════════════════════════════════════════════════════════════
#  MAIN TESTER
# ═══════════════════════════════════════════════════════════════

class SemanticTester:
    
    def __init__(self, openai_api_key: str, auth_file: str = "auth.json"):
        self.openai = OpenAI(api_key=openai_api_key)
        
        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)
        
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path('semantic_test_output')
        self.output_dir.mkdir(exist_ok=True)
        
        self.observer = Observer()
        self.context_stack = ContextStack()
        self.loop_detector = LoopDetector()
        self.scope: Optional[ScopeManager] = None
        self.decider: Optional[Decider] = None
        self.controller: Optional[Controller] = None
        self.executor: Optional[Executor] = None
        
        self.history: List[Dict] = []
        self.step = 0
        
        print(f"\n{'='*80}")
        print("🧠 SEMANTIC DRIVER - Production v1.0")
        print(f"{'='*80}")
        print(f"Session: {self.session_id}\n")
    
    async def run(self, target_url: str):
        """Main entry point"""
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1200, 'height': 700})
            page = await context.new_page()
            
            # Initialize
            self.scope = ScopeManager(target_url)
            self.decider = Decider(self.openai)
            self.controller = Controller(page)
            self.executor = Executor(page)
            
            try:
                print("[1/3] 🔑 Authenticating...")
                await self._inject_auth(page, context, target_url)
                
                print(f"[2/3] 🌐 Navigating to target...")
                await page.goto(target_url, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)
                
                # Init stack
                dom_hash = await self._dom_hash(page)
                initial = ContextFrame(
                    context_type=ContextType.PAGE,
                    description="Target page",
                    timestamp=datetime.now().isoformat(),
                    url=page.url,
                    dom_hash=dom_hash
                )
                self.context_stack.push(initial)
                
                print(f"[3/3] 🚀 Starting testing loop...\n")
                await self._test_loop(page)
                
            except Exception as e:
                print(f"\n❌ Error: {e}")
                import traceback
                traceback.print_exc()
                
            finally:
                self._save_results()
                input("\n👁️  Press Enter to close...")
                await browser.close()
    
    async def _test_loop(self, page: Page):
        """Main OMDE loop"""
        
        max_iter = 50
        iteration = 0
        
        while iteration < max_iter:
            iteration += 1
            self.step += 1
            
            print(f"\n{'='*80}")
            print(f"STEP {iteration} | Depth: {self.context_stack.depth()}")
            print(f"{'='*80}")
            
            # OBSERVE
            print("\n[OBSERVE]")
            screenshot = await self._screenshot(page, f"step_{self.step}")
            elements_data = await self.observer.get_elements(page)
            
            print(f"  Overlay: {elements_data.get('has_overlay')}")
            print(f"  Active elements: {len(elements_data.get('active_elements', []))}")
            
            # UPDATE MEMORY
            print("\n[MEMORY]")
            dom_hash = await self._dom_hash(page)
            current = self.context_stack.current()
            
            context_type = await self.observer.detect_context(page, elements_data)
            
            if current.dom_hash != dom_hash:
                if elements_data.get('has_overlay') and current.context_type != ContextType.MODAL:
                    new_frame = ContextFrame(
                        context_type=context_type,
                        description=f"{context_type.value} opened",
                        timestamp=datetime.now().isoformat(),
                        url=page.url,
                        dom_hash=dom_hash
                    )
                    self.context_stack.push(new_frame)
                
                elif not elements_data.get('has_overlay') and current.context_type == ContextType.MODAL:
                    self.context_stack.pop()
                
                else:
                    current.dom_hash = dom_hash
            
            current = self.context_stack.current()
            
            # FILTER ELEMENTS BASED ON SCOPE
            active_elements = elements_data.get('active_elements', [])
            scoped_elements = []
            
            for elem in active_elements:
                in_scope, reason = self.scope.is_element_in_scope(elem, page.url)
                if in_scope:
                    scoped_elements.append(elem)
                else:
                    print(f"  🚫 Skipped: {elem.get('text', 'element')[:30]} - {reason}")
            
            print(f"  Context: {current.context_type.value}")
            print(f"  In-scope elements: {len(scoped_elements)}")
            print(f"  Tested: {len(current.tested_elements)}")
            
            untested = [e for e in scoped_elements if e.get('text', '') not in current.tested_elements]
            
            if not untested:
                print(f"  ✅ Context complete")
                if self.context_stack.depth() > 1:
                    self.context_stack.pop()
                    continue
                else:
                    print(f"  🏁 All done!")
                    break
            
            # DECIDE
            print("\n[DECIDE]")
            decision = await self.decider.decide(screenshot, current, untested)
            
            if decision.get('action') == 'done':
                break
            
            print(f"  Action: {decision.get('action')}")
            print(f"  Target: {decision.get('target_name')}")
            
            # Loop check
            is_loop, reason = self.loop_detector.is_looping()
            if is_loop:
                print(f"  🔁 Loop: {reason}")
                if self.context_stack.depth() > 1:
                    self.context_stack.pop()
                continue
            
            # EXECUTE
            print("\n[EXECUTE]")
            locator, method = await self.controller.find(decision)
            
            if not locator:
                print(f"  ❌ Not found")
                current.mark_tested(decision.get('target_name', ''))
                continue
            
            print(f"  ✓ Found: {method}")
            
            result = await self.executor.execute(
                locator,
                decision.get('action'),
                decision.get('test_value')
            )
            
            self.loop_detector.record(
                decision.get('action'),
                decision.get('target_name')
            )
            
            current.mark_tested(decision.get('target_name', ''))
            
            self.history.append({
                "step": self.step,
                "decision": decision,
                "result": result,
                "timestamp": datetime.now().isoformat()
            })
            
            print(f"  Success: {result.get('success')}")
            
            await asyncio.sleep(1)
        
        print(f"\n{'='*80}")
        print(f"🏁 Complete: {iteration} steps")
        print(f"{'='*80}")
    
    async def _inject_auth(self, page: Page, context, target_url: str):
        """Inject auth"""
        parsed = urlparse(target_url)
        home = f"{parsed.scheme}://{parsed.netloc}/"
        
        await page.goto(home)
        await page.wait_for_load_state('networkidle')
        
        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"localStorage.setItem('{key}', `{val}`)")
            except:
                pass
        
        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"sessionStorage.setItem('{key}', `{val}`)")
            except:
                pass
        
        cookies = self.auth_data.get('cookies', [])
        if cookies:
            await context.add_cookies(cookies)
        
        print("  ✅ Auth injected\n")
    
    async def _screenshot(self, page: Page, name: str) -> str:
        """Capture screenshot"""
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            await page.screenshot(path=path, full_page=False)
            with open(path, 'rb') as f:
                return base64.b64encode(f.read()).decode()
        except:
            return ""
    
    async def _dom_hash(self, page: Page) -> str:
        """Get DOM hash"""
        try:
            html = await page.evaluate("document.body.innerHTML")
            return hashlib.md5(html.encode()).hexdigest()[:16]
        except:
            return ""
    
    def _save_results(self):
        """Save results"""
        results = {
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "total_steps": self.step,
            "history": self.history
        }
        
        out = self.output_dir / f"test_{self.session_id}.json"
        with open(out, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results: {out}")
        
        success = sum(1 for h in self.history if h.get('result', {}).get('success'))
        print(f"\n📊 SUMMARY")
        print(f"  Total: {len(self.history)}")
        print(f"  Success: {success}")
        print(f"  Failed: {len(self.history) - success}")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def main():
    if not Path('auth.json').exists():
        print("❌ auth.json not found")
        return
    
    key = "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"
    
    tester = SemanticTester(openai_api_key=key)
    
    url = input("\nEnter URL to test: ").strip()
    
    if not url:
        print("❌ No URL")
        return
    
    await tester.run(url)


if __name__ == "__main__":
    asyncio.run(main())