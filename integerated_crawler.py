"""
main.py  (Final Integrated — Phase 1 + Phase 2 v1.4 [FIXED])
─────────────────────────────────────────────────────────────
Two-phase crawler:

  Phase 1 — EXPLORATION
      TwoTierCrawler runs GPT-4 Vision discovery, builds the Knowledge
      Graph, and saves versioned main_action_plan_vN.json files under
      output/session_<timestamp>/plans/

  Phase 2 — DEEP TESTING  (SemanticTester v1.4 — fully updated)
      After exploration completes, url_extractor reads the freshly-saved
      plan, collects every unique target_url from link-type features, and
      passes them one-by-one to SemanticTester.

      Phase 2 now includes:
        • StoryAwareDecider  (replaces plain Decider)
        • WidgetHandler      (date-picker / widget routing)
        • ElementFilter      (AI-powered element filtering)
        • TestStoryTracker + ReportGenerator
        • Toast detection on overlay close
        • Loop-detected story marking
        • Submit-failure story marking
        • Full 4-strategy element matcher

Run:
    python main.py
"""

import asyncio
import json
import os
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

from playwright.async_api import async_playwright, Page
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ── Phase 1 imports ──────────────────────────────────────────────────────────
from core.graph_builder           import GraphBuilder
from core.knowledge_graph         import KnowledgeGraph
from core.logger                  import CrawlerLogger
from core.state_manager           import StateManager
from core.vision_analyzer         import GPTVisionAnalyzer
from detectors.component_detector import ComponentDetector
from detectors.dom_observer       import DOMObserver
from executors.dom_validator      import DOMStateValidator
from executors.path_resolver      import PathResolver
from executors.semantic_selector  import SemanticSelector
from planning.planner             import TwoTierPlanner

# ── Phase 2 core imports ─────────────────────────────────────────────────────
from core_phase2.global_memory  import GlobalMemory
from core_phase2.context_stack  import ContextStack, ContextFrame, ContextType
from core_phase2.loop_detector  import LoopDetector
from core_phase2.controller     import Controller
from core_phase2.executor       import Executor
from core_phase2.observer       import Observer
from core_phase2.scope_manager  import ScopeManager

# ── Phase 2 updated components (from main_phase2.py) ────────────────────────
from widget_handler          import WidgetHandler
from element_filter          import ElementFilter
from story_aware_decider     import StoryAwareDecider, build_story_tester
from test_story_engine       import TestStoryTracker, ReportGenerator

# ── Workflow tracker & URL extractor ────────────────────────────────────────
from workflow_tracker import WorkflowTracker
from url_extractor    import get_urls_from_latest_plan

console = Console()


# ════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — EXPLORATION  (unchanged)
# ════════════════════════════════════════════════════════════════════════════

class TwoTierCrawler:
    def __init__(
        self,
        base_url: str,
        auth_file: str = "auth.json",
        max_depth: int = 2,
        openai_api_key: Optional[str] = None
    ):
        self.base_url  = base_url
        self.domain    = urlparse(base_url).netloc
        self.max_depth = max_depth

        with open(auth_file, "r") as f:
            self.auth_data = json.load(f)

        openai_key  = os.getenv("OPENAI_API_KEY") or openai_api_key

        self.openai = OpenAI(api_key=openai_key)

        self.logger = CrawlerLogger(Path("semantic_test_output"))

        self.vision             = GPTVisionAnalyzer(self.openai, self.logger)
        self.knowledge_graph    = KnowledgeGraph(self.logger)
        self.dom_validator      = DOMStateValidator(self.logger)
        self.graph_builder      = GraphBuilder(self.knowledge_graph, self.logger)
        self.component_detector = ComponentDetector(self.logger)
        self.dom_observer       = DOMObserver(self.logger)
        self.semantic_selector  = SemanticSelector(self.logger)
        self.planner            = TwoTierPlanner(self.logger)
        self.state_manager      = StateManager(self.logger)

        self.path_resolver = PathResolver(
            self.knowledge_graph,
            self.dom_validator,
            self.semantic_selector,
            self.logger
        )

        self.stats = {
            "pages_explored":    0,
            "containers_found":  0,
            "features_found":    0,
            "discovery_clicks":  0,
            "vision_calls":      0,
            "states_discovered": 0,
            "menus_expanded":    0,
            "modals_detected":   0,
        }

        self.memory_file        = Path("semantic_test_output") / "two_tier_memory.json"
        self.exploration_memory = self._load_memory()
        self.knowledge_graph.load()

    # ── Memory helpers ───────────────────────────────────────────────────────

    def _load_memory(self) -> Dict:
        if self.memory_file.exists():
            with open(self.memory_file, "r") as f:
                return json.load(f)
        return {
            "explored_containers": {},
            "explored_features":   {},
            "discovered_features": {}
        }

    def _save_memory(self):
        self.memory_file.parent.mkdir(exist_ok=True)
        self.exploration_memory["last_run"] = datetime.now().isoformat()
        with open(self.memory_file, "w") as f:
            json.dump(self.exploration_memory, f, indent=2)
        self.knowledge_graph.save()

    # ── Auth ─────────────────────────────────────────────────────────────────

    async def _setup_auth(self, page: Page, context):
        console.print("\n[cyan]🔑 Setting up authentication...[/cyan]")
        self.logger.log_info("Setting up authentication")

        parsed   = urlparse(self.base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"
        await page.goto(homepage)
        await page.wait_for_load_state("networkidle")

        for key, value in self.auth_data.get("local_storage", {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate("([k, v]) => window.localStorage.setItem(k, v)", [key, val])
                console.print(f"  ✓ localStorage: {key}")
            except Exception as e:
                console.print(f"  ✗ localStorage: {key} — {e}")

        for key, value in self.auth_data.get("session_storage", {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate("([k, v]) => window.sessionStorage.setItem(k, v)", [key, val])
                console.print(f"  ✓ sessionStorage: {key}")
            except Exception as e:
                console.print(f"  ✗ sessionStorage: {key} — {e}")

        cookies = self.auth_data.get("cookies", [])
        if cookies:
            try:
                await context.add_cookies(cookies)
                console.print(f"  ✓ Cookies: {len(cookies)} added")
            except Exception as e:
                console.print(f"  ✗ Cookies: {e}")

        console.print("[green]✅ Auth injected[/green]")
        await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        if "login" in page.url.lower():
            raise Exception("Authentication failed — still on login page")

        console.print("[green]✅ Authenticated!\n[/green]")
        self.logger.log_info("Authentication successful")

    # ── Sidebar snapshot helper ──────────────────────────────────────────────

    async def _get_visible_sidebar_items(self, page: Page) -> List[str]:
        try:
            return await page.evaluate("""
                () => {
                    const sidebar = document.querySelector('aside, nav, [class*="sidebar"]');
                    if (!sidebar) return [];
                    const seen = new Set();
                    const out  = [];
                    sidebar.querySelectorAll('a, button, [role="menuitem"], li').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        const text = el.textContent?.trim();
                        if (rect.height > 0 && rect.width > 0 && text && !seen.has(text)) {
                            seen.add(text);
                            out.push(text);
                        }
                    });
                    return out;
                }
            """)
        except Exception as e:
            self.logger.log_error("sidebar_capture_failed", str(e))
            return []

    # ── Main exploration entry ───────────────────────────────────────────────

    async def run_exploration(self) -> str:
        """
        Run Phase 1 exploration only.
        Returns the session directory path so Phase 2 can find the plan.
        """
        console.print(Panel.fit(
            "[bold cyan]🔬 PHASE 1: EXPLORATION[/bold cyan]\n"
            f"[yellow]Target : {self.base_url}[/yellow]\n"
            f"[yellow]Depth  : {self.max_depth}[/yellow]\n"
            "[green]Builds Knowledge Graph + saves action plans[/green]\n"
            f"[cyan]Session: {self.logger.session_dir}[/cyan]",
            border_style="cyan"
        ))
        self.logger.log_info(f"Starting exploration for {self.base_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1200, "height": 700})
            page    = await context.new_page()

            try:
                await self._setup_auth(page, context)
                await self.dom_observer.inject_observer(page)
                await self._two_tier_exploration(page, depth=0, breadcrumb="Root")
            except Exception as e:
                self.logger.log_error("crawler_exception", str(e), {
                    "url":       page.url,
                    "traceback": __import__("traceback").format_exc()
                })
                raise
            finally:
                await browser.close()

        self._show_exploration_results()
        self._save_exploration_data()
        return str(self.logger.session_dir)

    async def _two_tier_exploration(self, page: Page, depth: int, breadcrumb: str):
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️ Max depth {self.max_depth} reached[/yellow]")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]📍 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"{'='*80}\n")
        self.logger.log_info(f"Exploring at depth {depth}: {breadcrumb}")

        await asyncio.sleep(2)
        current_url = page.url
        state_hash  = await self.state_manager.calculate_state_hash(page)

        if self.state_manager.is_state_visited(state_hash):
            console.print("[yellow]♻️ State already visited, skipping[/yellow]")
            return

        console.print("\n[bold yellow]🔍 INITIAL SCAN: Understanding page structure...[/bold yellow]")
        vision_analysis = await self.vision.analyze_page(page, current_url)
        self.stats["vision_calls"] += 1

        containers = await self.component_detector.detect_containers(
            page, vision_analysis.get("containers", [])
        )
        features = await self.component_detector.detect_features(
            page, vision_analysis.get("features", [])
        )

        self.stats["containers_found"] += len(containers)
        self.stats["features_found"]   += len(features)

        if not containers and not features:
            console.print("[yellow]No components detected, ending exploration[/yellow]")
            return

        self.state_manager.record_state(state_hash, current_url, breadcrumb, containers, features)
        self.stats["states_discovered"] += 1
        self.stats["pages_explored"]    += 1

        for container in containers:
            await self.graph_builder.register_container(page, container, current_url)
        for feature in features:
            await self.graph_builder.register_top_level_feature(page, feature, current_url)

        assumption_plan = self.planner.create_assumption_plan(
            containers, vision_analysis.get("discovery_strategy", {})
        )
        self.planner.create_main_action_plan(features)

        console.print("\n[bold green]🎯 DISCOVERY — Executing Assumption Plan[/bold green]\n")
        self.logger.log_info("Starting discovery phase")
        await self._execute_assumption_plan(page, assumption_plan, current_url, depth, breadcrumb)

        self._save_memory()

    async def _execute_assumption_plan(
        self, page: Page, plan: List[Dict],
        current_url: str, depth: int, breadcrumb: str
    ):
        if not plan:
            console.print("[yellow]No discovery steps needed[/yellow]")
            return

        for step in plan:
            container    = step["container"]
            container_id = container["semantic_id"]

            if self.exploration_memory.get("explored_containers", {}).get(
                container_id, {}
            ).get("expanded"):
                console.print(
                    f"\n[yellow]⏭️  SKIPPING '{container['text']}' — already expanded[/yellow]"
                )
                continue

            console.print(
                f"\n[bold yellow]🔓 DISCOVERY {step['step_id']}: {step['reason']}[/bold yellow]"
            )

            visible_before = await self._get_visible_sidebar_items(page)
            await self.dom_observer.get_changes(page)

            clicked = await self.semantic_selector.click_element(page, container)
            if not clicked:
                console.print("[red]   Discovery failed — skipping[/red]")
                self.logger.log_error("discovery_click_failed",
                                      f"Could not click {container['text']}")
                continue

            self.stats["discovery_clicks"] += 1
            self.exploration_memory.setdefault("explored_containers", {})[container_id] = {
                "text":        container.get("text"),
                "expanded":    True,
                "expanded_at": datetime.now().isoformat(),
            }

            await asyncio.sleep(2)

            visible_after = await self._get_visible_sidebar_items(page)
            new_items     = [i for i in visible_after if i not in visible_before]
            console.print(f"[green]   ✨ {len(new_items)} new items detected[/green]")

            new_items_filter = new_items if (visible_before or visible_after) else None

            changes     = await self.dom_observer.get_changes(page)
            change_type = await self.dom_observer.detect_change_type(changes)
            console.print(f"[cyan]   Change: {change_type}[/cyan]")
            self.logger.log_container_expansion(container, True, changes)

            if change_type in ["menu_expanded", "element_expanded", "modal_opened"]:
                await self._rescan_and_register(
                    page, container, current_url, depth, breadcrumb, new_items_filter
                )
                self.stats["menus_expanded"] += 1
                if change_type == "modal_opened":
                    self.stats["modals_detected"] += 1
                    await self._close_modal(page)

            self._save_memory()

    async def _rescan_and_register(
        self, page: Page, parent_container: Dict,
        current_url: str, depth: int, breadcrumb: str,
        new_items_filter: Optional[List[str]] = None
    ):
        console.print("[cyan]🔍 Re-scanning for newly visible features...[/cyan]")

        vision_analysis = await self.vision.analyze_expanded_container(
            page, page.url, parent_container["text"]
        )
        self.stats["vision_calls"] += 1

        raw_vision_features = vision_analysis.get("features", [])

        for container in vision_analysis.get("containers", []):
            is_target = container["text"].lower() in parent_container["text"].lower()
            if (container.get("state") == "expanded" or is_target) and container.get("expected_children"):
                for child_text in container["expected_children"]:
                    raw_vision_features.append({
                        "text":              child_text,
                        "type":              "link",
                        "location":          "sidebar_child",
                        "test_priority":     8,
                        "expected_behavior": "Navigate to sub-page"
                    })

        new_features = await self.component_detector.detect_features(page, raw_vision_features)

        all_known_ids = (
            set(self.exploration_memory.get("explored_features", {}).keys())
            | set(self.exploration_memory.get("discovered_features", {}).keys())
            | set(self.knowledge_graph.nodes.keys())
        )
        truly_new = [f for f in new_features if f["semantic_id"] not in all_known_ids]

        if new_items_filter is not None and new_items_filter:
            before    = len(truly_new)
            truly_new = [f for f in truly_new if f["text"] in new_items_filter]
            filtered  = before - len(truly_new)
            if filtered:
                console.print(f"[yellow]   🔍 Filtered out {filtered} already-visible features[/yellow]")

        if not truly_new:
            console.print("[yellow]   No new features found[/yellow]")
            return

        console.print(f"[green]   ✨ {len(truly_new)} new features![/green]")
        successfully_registered = []

        for feature in truly_new:
            feature_id = feature["semantic_id"]
            success    = await self.graph_builder.register_discovered_feature(
                page, feature, parent_container, current_url
            )
            if not success:
                continue
            successfully_registered.append(feature)
            self.exploration_memory.setdefault("discovered_features", {})[feature_id] = {
                "text":            feature.get("text"),
                "discovered_from": parent_container.get("text"),
                "anchor_url":      current_url,
                "discovered_at":   datetime.now().isoformat()
            }
            console.print(f"[green]      + {feature['text']}[/green]")

        self.planner.add_discovered_features_to_main_plan(successfully_registered)
        self.stats["features_found"] += len(truly_new)

    async def _close_modal(self, page: Page):
        for selector in [
            'button[aria-label="Close"]', "button.close",
            '[data-dismiss="modal"]',     'button:has-text("Close")',
            'button:has-text("Cancel")',  ".modal-close"
        ]:
            try:
                await page.click(selector, timeout=2000)
                await asyncio.sleep(0.5)
                console.print("[green]   ✅ Modal closed[/green]")
                return
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
            console.print("[green]   ✅ Modal closed with ESC[/green]")
        except Exception:
            console.print("[yellow]   ⚠️ Could not close modal[/yellow]")

    def _show_exploration_results(self):
        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value",  style="yellow")
        for key, value in self.stats.items():
            table.add_row(key.replace("_", " ").title(), str(value))
        console.print(table)

        kg_table = Table(title="Knowledge Graph")
        kg_table.add_column("Metric", style="cyan")
        kg_table.add_column("Value",  style="yellow")
        kg_table.add_row("Total Nodes",    str(len(self.knowledge_graph.nodes)))
        kg_table.add_row("Total Edges",    str(len(self.knowledge_graph.edges)))
        kg_table.add_row("Paths Computed", str(len(self.knowledge_graph.paths)))
        console.print(kg_table)

    def _save_exploration_data(self):
        output_dir = Path("semantic_test_output")
        output_dir.mkdir(exist_ok=True)
        data = {
            "metadata": {
                "base_url":    self.base_url,
                "timestamp":   datetime.now().isoformat(),
                "stats":       self.stats,
                "session_dir": str(self.logger.session_dir)
            },
            "knowledge_graph": {
                "nodes": self.knowledge_graph.nodes,
                "edges": self.knowledge_graph.edges,
                "paths": self.knowledge_graph.paths
            },
            "assumption_plan":  self.planner.assumption_plan,
            "main_action_plan": self.planner.main_action_plan,
        }
        out = output_dir / f"exploration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(out, "w") as f:
            json.dump(data, f, indent=2)
        console.print(f"[bold green]💾 Exploration data saved: {out}[/bold green]")


# ════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — SEMANTIC TESTER  v1.4 [FIXED]
#  Fully updated from main_phase2.py:
#    • StoryAwareDecider instead of plain Decider
#    • WidgetHandler for date-picker overlays
#    • ElementFilter (AI-powered)
#    • TestStoryTracker + ReportGenerator
#    • Toast detection on overlay close
#    • Loop / submit-fail story marking
#    • Full 4-strategy element matcher
# ════════════════════════════════════════════════════════════════════════════

class SemanticTester:
    """
    Runs the Observe → Decide → Execute loop on a single target URL.
    Reuses the same browser context across multiple URLs so auth persists.
    """

    def __init__(self, openai_api_key: str, auth_file: str = "auth.json"):
        self.openai    = OpenAI(api_key=openai_api_key)
        self.auth_file = auth_file

        with open(auth_file, "r") as f:
            self.auth_data = json.load(f)

        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = Path("semantic_test_output")
        self.output_dir.mkdir(exist_ok=True)

        # Core Phase 2 components
        self.observer       = Observer()
        self.context_stack  = ContextStack()
        self.loop_detector  = LoopDetector()
        self.global_memory  = GlobalMemory()
        self.element_filter = ElementFilter(self.openai)

        self.scope:      Optional[ScopeManager]      = None
        self.decider:    Optional[StoryAwareDecider] = None
        self.controller: Optional[Controller]        = None
        self.executor:   Optional[Executor]          = None

        self.history:     List[Dict] = []
        self.url_results: List[Dict] = []
        self.step = 0

        # Story engine (built via helper so tracker/gen/generator share openai ref)
        self.story_tracker, self.report_gen, self.story_gen = build_story_tester(
            self.openai, self.output_dir, self.session_id
        )

        # Workflow tracker
        self.workflow_tracker = WorkflowTracker(self.output_dir)

        print(f"\n{'='*80}")
        print("🧠 SEMANTIC DRIVER - Production v1.4 [FIXED] (Integrated)")
        print(f"{'='*80}")
        print(f"Session: {self.session_id}\n")

    # ── Public entry-point ───────────────────────────────────────────────────

    async def run_all(self, urls: List[str]):
        """Open one browser, inject auth once, then test each URL in sequence."""
        if not urls:
            console.print("[yellow]⚠️  No URLs to test.[/yellow]")
            return

        console.print(Panel.fit(
            "[bold cyan]🧪 PHASE 2: DEEP TESTING[/bold cyan]\n"
            f"[yellow]{len(urls)} URL(s) to test[/yellow]\n"
            "[green]Observe → Decide → Execute loop per page[/green]",
            border_style="cyan"
        ))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1400, "height": 900})
            page    = await context.new_page()

            try:
                await self._inject_auth(page, context, urls[0])

                # Wire up shared page components
                self.controller = Controller(page)
                self.executor   = Executor(page)
                self.decider    = StoryAwareDecider(
                    self.openai, tester_ref=self, story_tracker=self.story_tracker
                )

                for idx, url in enumerate(urls, 1):
                    console.print(f"\n{'='*80}")
                    console.print(
                        f"[bold cyan]🌐 TESTING URL {idx}/{len(urls)}: {url}[/bold cyan]"
                    )
                    console.print(f"{'='*80}")

                    url_start_step = self.step
                    try:
                        await self._test_single_url(page, url)
                    except Exception as e:
                        console.print(f"[red]❌ Error testing {url}: {e}[/red]")
                        import traceback
                        traceback.print_exc()

                    steps_taken = self.step - url_start_step
                    self.url_results.append({
                        "url":         url,
                        "index":       idx,
                        "steps_taken": steps_taken,
                        "tested_at":   datetime.now().isoformat()
                    })
                    console.print(
                        f"[green]   ✅ Finished URL {idx}/{len(urls)} "
                        f"({steps_taken} steps)[/green]"
                    )

            finally:
                self._save_results()
                self.workflow_tracker.finalize()
                await browser.close()

        self._print_summary()

    # ── Single-URL orchestration ─────────────────────────────────────────────

    async def _test_single_url(self, page: Page, target_url: str):
        """Navigate to one URL and run the full test loop."""
        # Reset per-URL state (global_memory intentionally NOT reset)
        self.scope         = ScopeManager(target_url)
        self.context_stack = ContextStack()
        self.loop_detector = LoopDetector()
        self.global_memory = GlobalMemory()

        await page.goto(target_url, wait_until="networkidle", timeout=30000)
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
        await self._test_loop(page)

    # ── Main test loop ───────────────────────────────────────────────────────

    async def _test_loop(self, page: Page, max_iter: int = 50):
        iteration = 0

        while iteration < max_iter:
            iteration += 1
            self.step += 1

            print(f"\n{'='*80}")
            print(f"STEP {self.step} | Iter {iteration} | Depth: {self.context_stack.depth()}")
            print(f"{'='*80}")

            # ── OBSERVE ──────────────────────────────────────────────────────
            print("\n[OBSERVE]")
            screenshot    = await self._screenshot(page, f"step_{self.step}")
            elements_data = await self.observer.get_elements(page)

            print(f"  Overlay: {elements_data.get('has_overlay')}")
            if elements_data.get("overlay_selector"):
                print(f"  Overlay selector: {elements_data.get('overlay_selector')}")
            print(f"  Discovered: {elements_data.get('total_discovered', 0)} interactive elements")

            # ── UPDATE CONTEXT STACK ─────────────────────────────────────────
            print("\n[MEMORY]")
            dom_hash     = await self._dom_hash(page)
            current      = self.context_stack.current()
            context_type = await self.observer.detect_context(page, elements_data)

            has_overlay_now  = elements_data.get("has_overlay", False)
            overlay_selector = elements_data.get("overlay_selector")
            was_in_overlay   = current.context_type in [
                ContextType.MODAL, ContextType.FORM, ContextType.CONFIRMATION
            ]

            if has_overlay_now and not was_in_overlay:
                # ── Widget check (date-picker etc.) ──────────────────────────
                if elements_data.get("overlay_type") == "widget":
                    widget_type = elements_data.get("widget_type", "")
                    print(f"  🧩 Widget detected: {widget_type} — routing to WidgetHandler")

                    start_val = "01/01/2025"
                    end_val   = "17/02/2026"
                    if self.story_tracker and self.story_tracker.active_story:
                        start_val = (
                            self.story_tracker.active_story.get_value_for("start") or start_val
                        )
                        end_val = (
                            self.story_tracker.active_story.get_value_for("end") or end_val
                        )

                    widget_handler = WidgetHandler(page)
                    await widget_handler.handle(
                        widget_type=widget_type,
                        value={"start": start_val, "end": end_val}
                    )

                    for field in ["start", "end"]:
                        self.global_memory.mark_tested(f"page:input:{field}", "fill")
                        print(f"  ✅ Marked as tested: page:input:{field}")

                    continue  # skip rest of loop iteration

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
                toast_text = await self._detect_toast(page)
                self.story_tracker.complete_story(toast_text)
                self.context_stack.pop()
                current = self.context_stack.current()
                current.dom_hash         = dom_hash
                current.overlay_selector = None

            else:
                current.dom_hash = dom_hash
                if has_overlay_now:
                    current.overlay_selector = overlay_selector

            # ── ELEMENT FILTER → SCOPE FILTER ────────────────────────────────
            active_elements = elements_data.get("active_elements", [])
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

            # Generate new stories if needed (uses full-page screenshot)
            full_screenshot = await self._full_screenshot(page, f"story_gen_{self.step}")
            await self.decider.maybe_generate_story(
                page=page,
                elements=scoped_elements,
                screenshot_b64=full_screenshot,
                context_type=current.context_type.value,
                url=page.url
            )

            if len(scoped_elements) > len(untested):
                print("  ✅ Global memory working:")
                tested_ids = {self.global_memory._get_identifier(u) for u in untested}
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
                print("  ✅ All elements tested")
                if self.context_stack.depth() > 1 and current.overlay_selector:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(1)
                    continue
                else:
                    print("  🏁 Testing complete!")
                    break

            # ── DECIDE ───────────────────────────────────────────────────────
            print("\n[DECIDE]")
            decision = await self.decider.decide(screenshot, current, untested)

            if decision.get("action") == "done":
                break

            print(f"  Action: {decision.get('action')}")
            print(f"  Target: {decision.get('target_name')}")

            self.loop_detector.record(decision.get("action"), decision.get("target_name"))
            is_loop, reason = self.loop_detector.is_looping()

            if is_loop:
                print(f"  🔁 Loop: {reason}")
                self.story_tracker.mark_loop_detected(decision.get("target_name", ""))

                matching_elem = self._find_matching_elem(untested, scoped_elements, decision)

                # Fallback: check full scoped list
                if not matching_elem:
                    matching_elem = self._find_matching_elem(scoped_elements, [], decision)

                if matching_elem:
                    identifier = self.global_memory._get_identifier(matching_elem)
                    self.global_memory.mark_tested(identifier, decision.get("action"))
                    print(f"     Marked as tested: {identifier}")
                else:
                    print(
                        f"     ⚠️  Could not find element '{decision.get('target_name')}' "
                        f"in untested list — forcing skip"
                    )

                if self.context_stack.depth() > 1:
                    self.context_stack.pop()
                continue

            # ── EXECUTE ──────────────────────────────────────────────────────
            print("\n[EXECUTE]")
            matching_elem = self._find_matching_elem(untested, scoped_elements, decision)

            locator, method = await self.controller.find(
                decision, overlay_selector=current.overlay_selector
            )

            if not locator:
                print("  ❌ Not found")
                if matching_elem:
                    identifier = self.global_memory._get_identifier(matching_elem)
                    self.global_memory.mark_tested(identifier, decision.get("action"))
                    print(f"     Marked as tested (not found): {identifier}")
                continue

            print(f"  ✓ Found: {method}")

            result = await self.executor.execute(
                locator,
                decision.get("action"),
                decision.get("test_value"),
                elem_type=decision.get("element_type", "")
            )

            # Mark tested: success OR permanently disabled
            if matching_elem:
                identifier = self.global_memory._get_identifier(matching_elem)
                err        = result.get("error", "") or ""

                if result.get("success"):
                    self.global_memory.mark_tested(identifier, decision.get("action"))
                    print(f"  ✅ Marked as tested: {identifier}")
                elif "disabled" in err.lower():
                    self.global_memory.mark_tested(identifier, decision.get("action"))
                    print(f"  ⚠️  Marked as tested (disabled button): {identifier}")
                else:
                    print("  ⚠️  Execution failed — will retry this element")
            else:
                print("  ⚠️  Could not find matching element in list — cannot mark as tested")

            # ── Story tracking ───────────────────────────────────────────────
            is_submit = any(
                kw in decision.get("target_name", "").lower()
                for kw in ["simpan", "save", "submit", "tambah", "perbarui", "update"]
            )
            if is_submit and not result.get("success"):
                self.story_tracker.mark_submit_failed(
                    decision.get("target_name", ""), result.get("error", "")
                )
            else:
                self.story_tracker.record_action(
                    action=decision.get("action", ""),
                    target=decision.get("target_name", ""),
                    value=decision.get("test_value", ""),
                    success=result.get("success", False),
                    error=result.get("error") if not result.get("success") else None
                )

            self.history.append({
                "step":        self.step,
                "url":         page.url,
                "decision":    decision,
                "result":      result,
                "all_options": result.get("all_options"),
                "timestamp":   datetime.now().isoformat()
            })

            print(f"  Success: {result.get('success')}")

            self.workflow_tracker.track_action(
                decision=decision,
                result=result,
                context_frame=current,
                url=page.url,
                step_number=self.step
            )

            await asyncio.sleep(1)

        print(f"\n  🏁 Loop finished after {iteration} iterations")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _find_matching_elem(
        self,
        primary: List[Dict],
        fallback: List[Dict],
        decision: Dict
    ) -> Optional[Dict]:
        """
        4-strategy element matcher:
        1. formcontrolname exact match
        2. text exact match
        3. name exact match
        4. text partial match
        Tries primary pool first, then fallback.
        """
        target = decision.get("target_name", "").strip()
        for pool in (primary, fallback):
            for elem in pool:
                if elem.get("formcontrolname", "") == target:
                    return elem
                if elem.get("text", "").strip() == target:
                    return elem
                if elem.get("name", "") == target:
                    return elem
                elem_text = elem.get("text", "").strip()
                if elem_text and target and target in elem_text:
                    return elem
        return None

    async def _inject_auth(self, page: Page, context, target_url: str):
        parsed = urlparse(target_url)
        home   = f"{parsed.scheme}://{parsed.netloc}/"

        await page.goto(home)
        await page.wait_for_load_state("networkidle")

        for key, value in self.auth_data.get("local_storage", {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"localStorage.setItem('{key}', `{val}`)")
            except Exception:
                pass

        for key, value in self.auth_data.get("session_storage", {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"sessionStorage.setItem('{key}', `{val}`)")
            except Exception:
                pass

        cookies = self.auth_data.get("cookies", [])
        if cookies:
            await context.add_cookies(cookies)

        print("  ✅ Auth injected\n")

    async def _screenshot(self, page: Page, name: str) -> str:
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            await page.screenshot(path=path, full_page=False)
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception:
            return ""

    async def _full_screenshot(self, page: Page, name: str) -> str:
        path = self.output_dir / f"{self.session_id}_{name}.png"
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await page.screenshot(path=path, full_page=True)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            with open(path, "rb") as f:
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
        selectors = [
            "mat-snack-bar-container", '[role="alert"]', '[role="status"]',
            ".toast", "[class*='toast']", ".alert", "[class*='snack']"
        ]
        try:
            for sel in selectors:
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
            "url_results": self.url_results,
            "history":     self.history
        }
        out = self.output_dir / f"test_{self.session_id}.json"
        with open(out, "w") as f:
            json.dump(results, f, indent=2)
        console.print(f"\n[bold green]💾 Results: {out}[/bold green]")

        # Finalise story reports
        if self.story_tracker.active_story:
            self.story_tracker.abandon_story("Session ended")
        if self.story_tracker.stories:
            self.report_gen.generate_all(self.story_tracker.stories)
        else:
            print("  ⚠️  No stories recorded")

    def _print_summary(self):
        success = sum(1 for h in self.history if h.get("result", {}).get("success"))
        console.print(Panel.fit(
            f"[bold green]🏁 PHASE 2 COMPLETE[/bold green]\n"
            f"[cyan]URLs tested : {len(self.url_results)}[/cyan]\n"
            f"[cyan]Total steps : {self.step}[/cyan]\n"
            f"[green]Success     : {success}[/green]\n"
            f"[red]Failed      : {len(self.history) - success}[/red]",
            border_style="green"
        ))


# ════════════════════════════════════════════════════════════════════════════
#  ORCHESTRATOR — Phase 1 → Phase 2 end-to-end
# ════════════════════════════════════════════════════════════════════════════

async def main():
    if not Path("auth.json").exists():
        console.print("[red]❌ auth.json not found![/red]")
        return

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        console.print("[red]❌ OPENAI_API_KEY environment variable not set.[/red]")
        return

    console.print(Panel.fit(
        "[bold white]🚀 FULL PIPELINE: EXPLORATION → DEEP TESTING[/bold white]",
        border_style="white"
    ))

    # ── Phase 1: Exploration ─────────────────────────────────────────────────
    crawler = TwoTierCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=2,
        openai_api_key=openai_key
    )
    session_dir = await crawler.run_exploration()
    console.print(f"\n[bold green]✅ Phase 1 complete — session: {session_dir}[/bold green]")

    # ── Extract URLs from latest plan ────────────────────────────────────────
    console.print("\n[cyan]🔍 Extracting test URLs from latest action plan...[/cyan]")
    urls = get_urls_from_latest_plan(output_dir=Path(session_dir) / "plans")
    if not urls:
        urls = get_urls_from_latest_plan(output_dir=Path("semantic_test_output"))

    if not urls:
        console.print(
            "[yellow]⚠️  No testable URLs found in plan. "
            "Check that exploration discovered link features.[/yellow]"
        )
        return

    # ── Phase 2: Deep Testing ────────────────────────────────────────────────
    tester = SemanticTester(openai_api_key=openai_key)
    await tester.run_all(urls)

    console.print(Panel.fit(
        "[bold green]🎉 FULL PIPELINE COMPLETE[/bold green]",
        border_style="green"
    ))


if __name__ == "__main__":
    asyncio.run(main())