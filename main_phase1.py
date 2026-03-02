import asyncio
import json
import os
from pathlib import Path
from typing import Optional,Dict,List
from urllib.parse import urlparse
from datetime import datetime

from anthropic import Anthropic
from playwright.async_api import async_playwright, Page
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from openai import OpenAI

from core.graph_builder import GraphBuilder
from core.knowledge_graph import KnowledgeGraph
from core.logger import CrawlerLogger
from core.state_manager import     StateManager
from core.vision_analyzer import GPTVisionAnalyzer

from detectors.component_detector import ComponentDetector
from detectors.dom_observer import  DOMObserver
from executors.dom_validator import  DOMStateValidator
from executors.path_resolver import  PathResolver
from executors.semantic_selector import SemanticSelector
from planning.planner import TwoTierPlanner

console = Console()

class TwoTierCrawler:
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

        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        if openai_api_key:
            self.openai = Anthropic(api_key=openai_api_key)
        else:
            self.openai = OpenAI()

        # Initialize logger FIRST
        self.logger = CrawlerLogger(Path("semantic_test_output"))

        # Initialize all layers with logger
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
            'pages_explored': 0,
            'containers_found': 0,
            'features_found': 0,
            'discovery_clicks': 0,
            'test_clicks': 0,
            'vision_calls': 0,
            'states_discovered': 0,
            'modals_detected': 0,
            'menus_expanded': 0,
            'features_tested': 0,
            'path_restorations': 0,
            'path_restoration_failures': 0
        }

        self.memory_file = Path('semantic_test_output') / 'two_tier_memory.json'
        self.exploration_memory = self._load_memory()

        self.knowledge_graph.load()

    async def _get_visible_sidebar_items(self, page: Page) -> List[str]:
        """
        Capture all currently visible items in the sidebar.
        Returns a list of text content from visible elements.
        """
        try:
            visible_items = await page.evaluate("""
                () => {
                    const sidebar = document.querySelector('aside, nav, [class*="sidebar"]');
                    if (!sidebar) return [];
                    
                    const allElements = sidebar.querySelectorAll('a, button, [role="menuitem"], li');
                    const visible = [];
                    
                    allElements.forEach(el => {
                        const rect = el.getBoundingClientRect();
                        const text = el.textContent?.trim();
                        
                        // Only include if visible and has text
                        if (rect.height > 0 && rect.width > 0 && text && text.length > 0) {
                            // Avoid duplicates by checking if text already exists
                            if (!visible.includes(text)) {
                                visible.push(text);
                            }
                        }
                    });
                    
                    return visible;
                }
            """)
            return visible_items
        except Exception as e:
            console.print(f"[dim]   ⚠️  Could not capture sidebar items: {e}[/dim]")
            self.logger.log_error("sidebar_capture_failed", str(e))
            return []

    def _load_memory(self) -> Dict:
        if self.memory_file.exists():
            with open(self.memory_file, 'r') as f:
                return json.load(f)
        return {
            'explored_containers': {},
            'explored_features': {},
            'discovered_features': {}
        }

    def _save_memory(self):
        self.memory_file.parent.mkdir(exist_ok=True)
        self.exploration_memory['last_run'] = datetime.now().isoformat()
        with open(self.memory_file, 'w') as f:
            json.dump(self.exploration_memory, f, indent=2)
        self.knowledge_graph.save()

    async def run(self):
        console.print(Panel.fit(
            "[bold cyan]🔬 TWO-TIER CRAWLER + KNOWLEDGE GRAPH + COMPREHENSIVE LOGGING[/bold cyan]\n"
            f"[yellow]Target: {self.base_url}[/yellow]\n"
            f"[yellow]Max Depth: {self.max_depth}[/yellow]\n"
            "[green]Phase 1: Discovery → builds Knowledge Graph[/green]\n"
            "[green]Phase 2: Testing  → PathResolver ensures state before each click[/green]\n"
            f"[cyan]Session Directory: {self.logger.session_dir}[/cyan]",
            border_style="cyan"
        ))

        self.logger.log_info(f"Starting crawler for {self.base_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1200, 'height': 700})
            page = await context.new_page()

            try:
                await self._setup_auth(page, context)
                await self.dom_observer.inject_observer(page)
                await self._two_tier_exploration(page, depth=0, breadcrumb="Root")
            except Exception as e:
                self.logger.log_error("crawler_exception", str(e), {
                    "url": page.url,
                    "traceback": __import__('traceback').format_exc()
                })
                raise
            finally:
                await browser.close()

        self._show_results()
        self._save_exploration_data()

        # Return the latest plan path so the orchestrator can hand it to Phase 2
        plans_dir = self.logger.session_dir / "plans"
        plan_files = sorted(plans_dir.glob("main_action_plan_v*.json"))
        return plan_files[-1] if plan_files else None

    async def _setup_auth(self, page: Page, context):
        console.print("\n[cyan]🔑 Setting up authentication...[/cyan]")
        self.logger.log_info("Setting up authentication")

        parsed = urlparse(self.base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"
        await page.goto(homepage)
        await page.wait_for_load_state('networkidle')

        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"window.localStorage.setItem('{key}', '{val}')")
                console.print(f"  ✓ localStorage: {key}")
                self.logger.log_action("auth_localStorage_set", {"key": key})
            except Exception as e:
                console.print(f"  ✗ localStorage: {key} — {e}")
                self.logger.log_error("auth_localStorage_failed", str(e), {"key": key})

        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"window.sessionStorage.setItem('{key}', '{val}')")
                console.print(f"  ✓ sessionStorage: {key}")
                self.logger.log_action("auth_sessionStorage_set", {"key": key})
            except Exception as e:
                console.print(f"  ✗ sessionStorage: {key}")
                self.logger.log_error("auth_sessionStorage_failed", str(e), {"key": key})

        cookies = self.auth_data.get('cookies', [])
        if cookies:
            try:
                await context.add_cookies(cookies)
                console.print(f"  ✓ Cookies: {len(cookies)} added")
                self.logger.log_action("auth_cookies_added", {"count": len(cookies)})
            except Exception as e:
                console.print(f"  ✗ Cookies: {e}")
                self.logger.log_error("auth_cookies_failed", str(e))

        console.print("[green]✅ Auth injected[/green]")

        await page.goto(self.base_url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(2)

        if 'login' in page.url.lower():
            raise Exception("Authentication failed — still on login page")

        console.print("[green]✅ Authenticated!\n[/green]")
        self.logger.log_info("Authentication successful")

    async def _two_tier_exploration(self, page: Page, depth: int, breadcrumb: str):
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️ Max depth {self.max_depth} reached[/yellow]")
            self.logger.log_info(f"Max depth {self.max_depth} reached")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]📍 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"{'='*80}\n")
        self.logger.log_info(f"Exploring at depth {depth}: {breadcrumb}")

        await asyncio.sleep(2)
        current_url = page.url
        state_hash = await self.state_manager.calculate_state_hash(page)

        if self.state_manager.is_state_visited(state_hash):
            console.print(f"[yellow]♻️ State already visited, skipping[/yellow]")
            self.logger.log_info(f"State {state_hash} already visited, skipping")
            return

        console.print("\n[bold yellow]🔍 INITIAL SCAN: Understanding page structure...[/bold yellow]")
        vision_analysis = await self.vision.analyze_page(page, current_url)
        self.stats['vision_calls'] += 1

        containers = await self.component_detector.detect_containers(
            page, vision_analysis.get('containers', [])
        )
        features = await self.component_detector.detect_features(
            page, vision_analysis.get('features', [])
        )

        self.stats['containers_found'] += len(containers)
        self.stats['features_found'] += len(features)

        if not containers and not features:
            console.print("[yellow]No components detected, ending exploration[/yellow]")
            self.logger.log_info("No components detected, ending exploration")
            return

        self.state_manager.record_state(state_hash, current_url, breadcrumb, containers, features)
        self.stats['states_discovered'] += 1
        self.stats['pages_explored'] += 1

        for container in containers:
            await self.graph_builder.register_container(page, container, current_url)

        for feature in features:
            await self.graph_builder.register_top_level_feature(page, feature, current_url)

        assumption_plan = self.planner.create_assumption_plan(
            containers, vision_analysis.get('discovery_strategy', {})
        )
        main_action_plan = self.planner.create_main_action_plan(features)

        console.print("\n" + "="*80)
        console.print("[bold green]🎯 PHASE 1: DISCOVERY — Executing Assumption Plan[/bold green]")
        console.print("="*80 + "\n")
        self.logger.log_info("Starting Phase 1: Discovery")

        await self._execute_assumption_plan(page, assumption_plan, current_url, depth, breadcrumb)

        # ----------------------------------------------------------------
        # NOTE: Testing (Phase 2) has been moved to main_orchestrator.py.
        # Exploration ends here. The orchestrator reads the saved plan
        # and passes each URL to a fresh SemanticTester instance.
        # ----------------------------------------------------------------
        console.print("\n[bold green]Exploration complete for this depth.[/bold green]")
        self.logger.log_info("Exploration complete — testing delegated to Phase 2 orchestrator")

    async def _execute_assumption_plan(
        self,
        page: Page,
        plan: List[Dict],
        current_url: str,
        depth: int,
        breadcrumb: str
    ):
        if not plan:
            console.print("[yellow]No discovery steps needed[/yellow]")
            return

        for step in plan:
            container = step['container']
            container_id = container['semantic_id']

            if container_id in self.exploration_memory.get('explored_containers', {}):
                if self.exploration_memory['explored_containers'][container_id].get('expanded'):
                    console.print(f"\n[yellow]⏭️  SKIPPING discovery: '{container['text']}' — already expanded[/yellow]")
                    self.logger.log_info(f"Skipping already expanded container: {container['text']}")
                    continue

            console.print(f"\n[bold yellow]🔓 DISCOVERY STEP {step['step_id']}: {step['reason']}[/bold yellow]")
            self.logger.log_info(f"Discovery step {step['step_id']}: {step['reason']}")

            # ✅ NEW: Capture visible items BEFORE clicking
            visible_before = await self._get_visible_sidebar_items(page)
            console.print(f"[dim]   📸 Captured {len(visible_before)} visible items before click[/dim]")
            self.logger.log_action("visible_items_before_click", {
                "container": container['text'],
                "count": len(visible_before),
                "items": visible_before[:10]  # Log first 10 for debugging
            })

            await self.dom_observer.get_changes(page)

            clicked = await self.semantic_selector.click_element(page, container)

            if not clicked:
                console.print("[red]   Discovery failed — skipping[/red]")
                self.logger.log_error("discovery_click_failed", f"Could not click {container['text']}", {
                    "container_id": container_id
                })
                continue

            self.stats['discovery_clicks'] += 1

            self.exploration_memory.setdefault('explored_containers', {})[container_id] = {
                'text': container.get('text'),
                'expanded': True,
                'expanded_at': datetime.now().isoformat(),
                'type': container.get('type')
            }

            await asyncio.sleep(2)

            # ✅ NEW: Capture visible items AFTER clicking
            visible_after = await self._get_visible_sidebar_items(page)
            console.print(f"[dim]   📸 Captured {len(visible_after)} visible items after click[/dim]")
            
            # ✅ NEW: Find only NEW items (items that appeared after clicking)
            new_items = [item for item in visible_after if item not in visible_before]
            console.print(f"[green]   ✨ Detected {len(new_items)} NEW items after expansion[/green]")

            if len(visible_before) == 0 and len(visible_after) == 0:
                console.print(f"[yellow]   ⚠️  Sidebar capture failed (0 items), disabling filter (trusting vision)[/yellow]")
                self.logger.log_action("filter_disabled_due_to_capture_failure", {
                    "container": container['text'],
                    "reason": "sidebar_capture_returned_empty"
                })
                new_items_filter = None  # Signal to NOT filter
            else:
                new_items_filter = new_items
            
            self.logger.log_action("visible_items_after_click", {
                "container": container['text'],
                "count_before": len(visible_before),
                "count_after": len(visible_after),
                "new_count": len(new_items),
                "new_items": new_items
            })

            changes = await self.dom_observer.get_changes(page)
            change_type = await self.dom_observer.detect_change_type(changes)

            console.print(f"[cyan]   Change detected: {change_type} ({len(changes)} DOM mutations)[/cyan]")
            self.logger.log_container_expansion(container, True, changes)

            if change_type in ["menu_expanded", "element_expanded", "modal_opened"]:
                # ✅ MODIFIED: Pass the new_items list to filter registration
                await self._rescan_and_register(page, container, current_url, depth, breadcrumb, new_items_filter)
                self.stats['menus_expanded'] += 1

                if change_type == "modal_opened":
                    self.stats['modals_detected'] += 1
                    await self._close_modal(page)

            self._save_memory()

    async def _rescan_and_register(
        self,
        page: Page,
        parent_container: Dict,
        current_url: str,
        depth: int,
        breadcrumb: str,
        new_items_filter: List[str] = None  # ✅ NEW: Optional filter of truly new items
    ):
        console.print("[cyan]🔍 Re-scanning for newly visible features...[/cyan]")
        self.logger.log_info(f"Re-scanning after expanding: {parent_container['text']}")

        vision_analysis = await self.vision.analyze_expanded_container(
            page, page.url, parent_container['text'])
        self.stats['vision_calls'] += 1

        raw_vision_features = vision_analysis.get('features', [])

        for container in vision_analysis.get('containers', []):
            is_target = container['text'].lower() in parent_container['text'].lower()
            if (container.get('state') == 'expanded' or is_target) and container.get('expected_children'):
                console.print(f"[yellow]   Extracting children from '{container['text']}'...[/yellow]")
                for child_text in container['expected_children']:
                    raw_vision_features.append({
                        "text": child_text,
                        "type": "link",
                        "location": "sidebar_child",
                        "test_priority": 8,
                        "expected_behavior": "Navigate to sub-page"
                    })

        new_features = await self.component_detector.detect_features(page, raw_vision_features)

        all_known_ids = set(self.exploration_memory.get('explored_features', {}).keys()) | \
                        set(self.exploration_memory.get('discovered_features', {}).keys()) | \
                        set(self.knowledge_graph.nodes.keys())

        truly_new = [f for f in new_features if f['semantic_id'] not in all_known_ids]

        # ✅ NEW: Apply the new_items_filter if provided
        if new_items_filter is not None and len(new_items_filter) > 0:
            before_filter_count = len(truly_new)
            truly_new = [
                f for f in truly_new 
                if f['text'] in new_items_filter
            ]
            filtered_out = before_filter_count - len(truly_new)
            
            if filtered_out > 0:
                console.print(f"[yellow]   🔍 Filtered out {filtered_out} features that were already visible[/yellow]")
                self.logger.log_action("features_filtered", {
                    "before_filter": before_filter_count,
                    "after_filter": len(truly_new),
                    "filtered_out": filtered_out
                })

        if not truly_new:
            console.print("[yellow]   No new features found[/yellow]")
            self.logger.log_info("No new features found during rescan")
            return

        console.print(f"[green]   ✨ Found {len(truly_new)} new features![/green]")
        self.logger.log_info(f"Found {len(truly_new)} new features")

        successfully_registered = []
        for feature in truly_new:
            feature_id = feature['semantic_id']

            success = await self.graph_builder.register_discovered_feature(
                page, feature, parent_container, current_url
            )
            if not success:
                console.print(f"[red]   Failed to register '{feature['text']}' in Knowledge Graph[/red]")
                continue
            successfully_registered.append(feature)

            self.exploration_memory.setdefault('discovered_features', {})[feature_id] = {
                'text': feature.get('text'),
                'discovered_from': parent_container.get('text'),
                'discovered_from_id': parent_container.get('semantic_id'),
                'anchor_url': current_url,
                'discovered_at': datetime.now().isoformat()
            }

            console.print(f"[green]      + {feature['text']}[/green]")

        self.planner.add_discovered_features_to_main_plan(successfully_registered)
        self.stats['features_found'] += len(truly_new)

    async def _execute_main_action_plan(
        self,
        page: Page,
        plan: List[Dict],
        depth: int,
        breadcrumb: str
    ):
        if not plan:
            console.print("[yellow]No test steps[/yellow]")
            return

        for step in plan:
            feature    = step['feature']
            feature_id = step.get('feature_id', feature.get('semantic_id', ''))

            if feature_id in self.exploration_memory.get('explored_features', {}):
                if self.exploration_memory['explored_features'][feature_id].get('tested'):
                    console.print(f"\n[yellow]⏭️  SKIPPING: '{feature['text']}' — already tested[/yellow]")
                    self.logger.log_info(f"Skipping already tested feature: {feature['text']}")
                    continue

            console.print(f"\n[bold yellow]🧪 TEST STEP {step['step_id']}: {step['reason']}[/bold yellow]")
            console.print(f"[cyan]   Test Type: {step['test_type']}[/cyan]")
            self.logger.log_info(f"Test step {step['step_id']}: {step['reason']}")

            ready = await self.path_resolver.prepare_for_click(page, feature_id, feature)

            if not ready:
                console.print(f"[red]   ❌ PathResolver could not prepare state — skipping[/red]")
                self.stats['path_restoration_failures'] += 1
                continue

            if self.state_manager.navigation_occurred:
                await self.dom_observer.inject_observer(page)
                self.state_manager.acknowledge_navigation()

            url_before = page.url

            clicked = await self.semantic_selector.click_element(page, feature)

            if not clicked:
                console.print("[red]   Test failed — could not click[/red]")
                self.logger.log_feature_test(feature, False)
                continue

            self.stats['test_clicks'] += 1
            self.stats['features_tested'] += 1

            self.exploration_memory.setdefault('explored_features', {})[feature_id] = {
                'text': feature.get('text'),
                'tested': True,
                'tested_at': datetime.now().isoformat(),
                'test_type': step['test_type']
            }

            await asyncio.sleep(2)

            url_after = page.url

            if url_after != url_before:
                console.print(f"[green]   🌐 Navigation: {url_after}[/green]")
                self.logger.log_feature_test(feature, True, True, url_after)
                self.logger.log_state_change(url_before, url_after, breadcrumb)

                self.state_manager.signal_navigation()

                new_breadcrumb = f"{breadcrumb} > {feature['text'][:30]}"
                await self._two_tier_exploration(page, depth + 1, new_breadcrumb)

                console.print("[yellow]   ⬅️  Going back...[/yellow]")
                try:
                    await page.go_back(wait_until='networkidle', timeout=10000)
                    await asyncio.sleep(2)
                    self.dom_observer.reset()
                    await self.dom_observer.inject_observer(page)
                    self.state_manager.signal_navigation()
                    self.logger.log_action("navigation_back", {"from_url": url_after, "to_url": url_before})
                except Exception as e:
                    console.print(f"[red]   Failed to go back: {e}[/red]")
                    self.logger.log_error("navigation_back_failed", str(e), {
                        "from_url": url_after,
                        "to_url": url_before
                    })
            else:
                self.logger.log_feature_test(feature, True, False)

            self._save_memory()

    async def _close_modal(self, page: Page):
        for selector in [
            'button[aria-label="Close"]', 'button.close',
            '[data-dismiss="modal"]', 'button:has-text("Close")',
            'button:has-text("Cancel")', '.modal-close'
        ]:
            try:
                await page.click(selector, timeout=2000)
                await asyncio.sleep(0.5)
                console.print("[green]   ✅ Modal closed[/green]")
                self.logger.log_action("modal_closed", {"method": "button_click"})
                return
            except:
                continue
        try:
            await page.keyboard.press('Escape')
            console.print("[green]   ✅ Modal closed with ESC[/green]")
            self.logger.log_action("modal_closed", {"method": "escape_key"})
        except:
            console.print("[yellow]   ⚠️  Could not close modal[/yellow]")
            self.logger.log_error("modal_close_failed", "Could not close modal")

    def _show_results(self):
        console.print("\n" + "="*80)
        console.print(Panel.fit("[bold green]✅ TWO-TIER + KNOWLEDGE GRAPH COMPLETE[/bold green]", border_style="green"))

        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="yellow")
        for key, value in self.stats.items():
            table.add_row(key.replace('_', ' ').title(), str(value))
        console.print(table)

        kg_table = Table(title="Knowledge Graph")
        kg_table.add_column("Metric", style="cyan")
        kg_table.add_column("Value", style="yellow")
        kg_table.add_row("Total Nodes", str(len(self.knowledge_graph.nodes)))
        kg_table.add_row("Total Edges", str(len(self.knowledge_graph.edges)))
        kg_table.add_row("DOM-Confirmed Edges", str(
            sum(1 for e in self.knowledge_graph.edges if e.get('confidence') == 'dom_confirmed')
        ))
        kg_table.add_row("Paths Computed", str(len(self.knowledge_graph.paths)))
        dom_action_edges = sum(1 for e in self.knowledge_graph.edges if e['edge_type'] == 'dom_action')
        nav_edges = sum(1 for e in self.knowledge_graph.edges if e['edge_type'] == 'navigation')
        kg_table.add_row("DOM Action Edges", str(dom_action_edges))
        kg_table.add_row("Navigation Edges", str(nav_edges))
        console.print(kg_table)

        console.print(f"\n  Discovery Steps: {len(self.planner.assumption_plan)}")
        console.print(f"  Testing Steps:   {len(self.planner.main_action_plan)}")
        
        # Save final summary
        kg_summary = {
            "total_nodes": len(self.knowledge_graph.nodes),
            "total_edges": len(self.knowledge_graph.edges),
            "dom_confirmed_edges": sum(1 for e in self.knowledge_graph.edges if e.get('confidence') == 'dom_confirmed'),
            "paths_computed": len(self.knowledge_graph.paths),
            "dom_action_edges": dom_action_edges,
            "navigation_edges": nav_edges
        }
        self.logger.save_final_summary(self.stats, kg_summary)

    def _save_exploration_data(self):
        output_dir = Path('semantic_test_output')
        output_dir.mkdir(exist_ok=True)

        data = {
            'metadata': {
                'base_url': self.base_url,
                'timestamp': datetime.now().isoformat(),
                'stats': self.stats,
                'architecture': 'two_tier_with_knowledge_graph_and_logging',
                'session_directory': str(self.logger.session_dir)
            },
            'knowledge_graph': {
                'nodes': self.knowledge_graph.nodes,
                'edges': self.knowledge_graph.edges,
                'paths': self.knowledge_graph.paths
            },
            'assumption_plan': self.planner.assumption_plan,
            'main_action_plan': self.planner.main_action_plan,
            'states': {
                h: {k: v for k, v in s.items()}
                for h, s in self.state_manager.states.items()
            }
        }

        output_file = output_dir / f'kg_exploration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.print(f"\n[bold green]💾 Saved: {output_file}[/bold green]")
        console.print(f"[bold green]💾 Knowledge Graph: semantic_test_output/knowledge_graph.json[/bold green]")
        console.print(f"[bold green]📁 Session Directory: {self.logger.session_dir}[/bold green]")
        console.print(f"[bold green]   ├─ crawler_log.txt (main log)[/bold green]")
        console.print(f"[bold green]   ├─ actions_log.jsonl (structured actions)[/bold green]")
        console.print(f"[bold green]   ├─ errors_log.txt (errors)[/bold green]")
        console.print(f"[bold green]   └─ plans/ (all plan versions)[/bold green]")


# =============================================================================
# Entry point
# =============================================================================

async def main():
    if not Path('auth.json').exists():
        console.print("[red]❌ auth.json not found![/red]")
        return

    openai_key = os.getenv('OPENAI_API_KEY')
    if not openai_key:
        console.print("[red]❌ OPENAI_API_KEY not set[/red]")
        return

    crawler = TwoTierCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=2,
        openai_api_key=openai_key
    )

    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())