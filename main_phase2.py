
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
from widget_handler import WidgetHandler
from element_filter import ElementFilter
from story_aware_decider import StoryAwareDecider, build_story_tester
from test_story_engine   import TestStoryTracker, ReportGenerator
import os
from playwright.async_api import async_playwright, Page, Locator, FrameLocator
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

from core_phase2.global_memory import GlobalMemory
from core_phase2.context_stack import ContextStack, ContextFrame, ContextType
from core_phase2.loop_detector import LoopDetector
from core_phase2.controller import Controller
from core_phase2.executor import Executor
from core_phase2.observer import Observer
from core_phase2.scope_manager import ScopeManager
from core_phase2.decider import Decider 
import asyncio
import json 


class SemanticTester:

    def __init__(self, openai_api_key: str, auth_file: str = "auth.json"):
        self.openai = OpenAI(api_key=openai_api_key)

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
        self.scope:      Optional[ScopeManager] = None
        self.decider:    Optional[Decider]      = None
        self.controller: Optional[Controller]   = None
        self.executor:   Optional[Executor]     = None

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
                self._save_results()
                input("\n👁️  Press Enter to close...")
                await browser.close()

    async def _test_loop(self, page: Page):
        max_iter  = 50
        iteration = 0

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
                if elements_data.get("overlay_type") == "widget":
                    widget_type = elements_data.get("widget_type", "")
                    print(f"  🧩 Widget detected: {widget_type} — routing to WidgetHandler")

                    # Get date values from active story
                    start_val = "01/01/2025"
                    end_val   = "17/02/2026"
                    if self.story_tracker and self.story_tracker.active_story:
                        start_val = self.story_tracker.active_story.get_value_for("start") or start_val
                        end_val   = self.story_tracker.active_story.get_value_for("end")   or end_val

                    widget_handler = WidgetHandler(page)
                    success = await widget_handler.handle(
                        widget_type=widget_type,
                        value={"start": start_val, "end": end_val}
                    )

                    # Mark both start and end as tested
                    for field in ["start", "end"]:
                        self.global_memory.mark_tested(f"page:input:{field}", "fill")
                        print(f"  ✅ Marked as tested: page:input:{field}")

                    continue  # Skip rest of loop, go to next iteration

                else:
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

            elif not has_overlay_now and was_in_overlay:
                toast_text = await self._detect_toast(page)      # ← ADD
                self.story_tracker.complete_story(toast_text)
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
            scoped_elements = []

            for elem in active_elements:
                in_scope, reason = self.scope.is_element_in_scope(elem, page.url)
                if in_scope:
                    scoped_elements.append(elem)
                else:
                    print(f"  🚫 Skipped: {elem.get('text', 'element')[:30]} - {reason}")

            # ── GLOBAL MEMORY FILTER ─────────────────────────────────────────
            untested = self.global_memory.get_untested(scoped_elements)
            full_screenshot = await self._full_screenshot(page, f"story_gen_{self.step}")
            await self.decider.maybe_generate_story(
                page=page, elements=scoped_elements,
                screenshot_b64=screenshot,
                context_type=current.context_type.value,
                url=page.url
            )

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
                if self.context_stack.depth() > 1 and current.overlay_selector:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(1)
                    continue
                else:
                    print(f"  🏁 Testing complete!")
                    break

            # ── DECIDE ───────────────────────────────────────────────────────
            print("\n[DECIDE]")
            decision = await self.decider.decide(screenshot, current, untested)

            if decision.get('action') == 'done':
                break

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
                elem_type=decision.get('element_type', ''),
                target_name=decision.get('target_name', '')
            )

            # FIX 4: Only mark as tested if execution was successful
            if matching_elem:
                identifier = self.global_memory._get_identifier(matching_elem)
                if result.get('success') and matching_elem:
                    # identifier = self.global_memory._get_identifier(matching_elem)
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
            else:
                self.story_tracker.record_action(
                    action=decision.get("action",""), target=decision.get("target_name",""),
                    value=decision.get("test_value",""), success=result.get("success",False),
                    error=result.get("error") if not result.get("success") else None
                )
            self.history.append({
                "step":        self.step,
                "decision":    decision,
                "result":      result,
                "all_options": result.get("all_options"),
                "timestamp":   datetime.now().isoformat()
            })

            print(f"  Success: {result.get('success')}")
            await asyncio.sleep(1)

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

    def _save_results(self):
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

        if self.story_tracker.active_story:
            self.story_tracker.abandon_story("Session ended")
        if self.story_tracker.stories:
            self.report_gen.generate_all(self.story_tracker.stories)
        else:
            print("  ⚠️  No stories recorded")


# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════

async def main():
    if not Path('auth.json').exists():
        print("❌ auth.json not found")
        return

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("❌ OPENAI_API_KEY not found")
        return


    tester = SemanticTester(openai_api_key=key)

    url = input("\nEnter URL to test: ").strip()
    if not url:
        print("❌ No URL")
        return

    await tester.run(url)


if __name__ == "__main__":
    asyncio.run(main())