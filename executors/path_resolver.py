import asyncio
from typing import List, Dict
from playwright.async_api import Page
from rich.console import Console
from core.knowledge_graph import KnowledgeGraph
from .dom_validator import DOMStateValidator
from .semantic_selector import SemanticSelector
from core.logger import CrawlerLogger

console = Console()

class PathResolver:
    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        dom_validator: DOMStateValidator,
        semantic_selector,
        logger: CrawlerLogger
    ):
        self.kg = knowledge_graph
        self.validator = dom_validator
        self.selector = semantic_selector
        self.logger = logger
        
        # NEW: Statistics tracking
        self.stats = {
            'direct_navigations': 0,
            'traditional_paths': 0,
            'failed_direct_navigations': 0
        }

    async def prepare_for_click(self, page: Page, feature_id: str, feature: Dict) -> bool:
        console.print(f"\n[bold cyan]🗺️  PATH RESOLVER: Preparing to reach '{feature['text']}'[/bold cyan]")
        self.logger.log_info(f"PATH RESOLUTION START for '{feature['text']}'")

        # ========================================================================
        # NEW: TELEPORT CHECK - The "Fast Lane"
        # ========================================================================
        target_url = self.kg.get_target_url(feature_id)
        
        if target_url:
            console.print(f"[bold green]   ⚡ DEEP LINK DETECTED: {target_url}[/bold green]")
            console.print(f"[cyan]   🚀 Attempting direct navigation (bypassing click path)...[/cyan]")
            self.logger.log_action("deep_link_attempt", {
                "feature_id": feature_id,
                "feature_text": feature['text'],
                "target_url": target_url
            })
            
            try:
                # Direct navigation - instant teleport!
                await page.goto(target_url, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)  # Allow page to stabilize
                
                # Verify we reached the correct page
                current_url = page.url
                if current_url == target_url or current_url.startswith(target_url):
                    console.print(f"[bold green]   ✅ TELEPORT SUCCESS! Arrived at: {current_url}[/bold green]")
                    self.stats['direct_navigations'] += 1
                    self.logger.log_action("deep_link_success", {
                        "feature_id": feature_id,
                        "target_url": target_url,
                        "actual_url": current_url
                    })
                    self.logger.log_path_resolution(
                        feature_id, 
                        feature['text'], 
                        0,  # No traditional path steps needed
                        0,  # No restoration needed
                        True,
                        method="deep_link"
                    )
                    return True
                else:
                    # URL mismatch - unexpected redirect or error
                    console.print(f"[yellow]   ⚠️  URL mismatch after navigation[/yellow]")
                    console.print(f"[yellow]      Expected: {target_url}[/yellow]")
                    console.print(f"[yellow]      Got: {current_url}[/yellow]")
                    console.print(f"[yellow]   Falling back to traditional path...[/yellow]")
                    self.stats['failed_direct_navigations'] += 1
                    self.logger.log_action("deep_link_mismatch", {
                        "feature_id": feature_id,
                        "expected_url": target_url,
                        "actual_url": current_url
                    })
                    # Continue to traditional path below
                    
            except Exception as e:
                console.print(f"[red]   ❌ Direct navigation failed: {e}[/red]")
                console.print(f"[yellow]   Falling back to traditional path...[/yellow]")
                self.stats['failed_direct_navigations'] += 1
                self.logger.log_error("deep_link_navigation_failed", str(e), {
                    "feature_id": feature_id,
                    "target_url": target_url
                })
                # Continue to traditional path below
        
        # ========================================================================
        # TRADITIONAL PATH - The "Walking Directions"
        # ========================================================================
        console.print(f"[cyan]   🚶 Using traditional click path[/cyan]")
        self.stats['traditional_paths'] += 1
        
        path = self.kg.get_path(feature_id)

        if not path:
            console.print(f"[yellow]   No path in graph for {feature_id} — attempting direct click[/yellow]")
            self.logger.log_path_resolution(feature_id, feature['text'], 0, 0, True, method="direct_click")
            return True

        console.print(f"[cyan]   Path has {len(path)} steps[/cyan]")

        restoration_queue = []

        for step in path:
            step_type = step['step_type']

            if step_type == 'ensure_url':
                on_correct_url = await self.validator.is_on_correct_url(
                    page, step['target_url']
                )
                if not on_correct_url:
                    console.print(f"[yellow]   ⚠️  Need to navigate to: {step['target_url']}[/yellow]")
                    restoration_queue.append(step)
                else:
                    console.print(f"[dim]   ✓ Already on correct URL[/dim]")

            elif step_type == 'expand_container':
                is_expanded = await self.validator.is_container_expanded(
                    page,
                    step['container_text'],
                    step.get('container_location', 'sidebar')
                )
                if not is_expanded:
                    console.print(f"[yellow]   ⚠️  Need to expand: '{step['container_text']}'[/yellow]")
                    restoration_queue.append(step)
                else:
                    console.print(f"[dim]   ✓ Already expanded: '{step['container_text']}'[/dim]")

        if not restoration_queue:
            console.print(f"[green]   ✅ All prerequisites satisfied — ready to click[/green]")
            self.logger.log_path_resolution(feature_id, feature['text'], len(path), 0, True, method="traditional")
            return True

        console.print(f"[cyan]   Executing {len(restoration_queue)} restoration steps...[/cyan]")
        success = await self._execute_restoration(page, restoration_queue)

        if success:
            console.print(f"[green]   ✅ Restoration complete — ready to click[/green]")
            self.logger.log_path_resolution(
                feature_id, 
                feature['text'], 
                len(path), 
                len(restoration_queue), 
                True,
                method="traditional"
            )
        else:
            console.print(f"[red]   ❌ Restoration failed[/red]")
            self.logger.log_path_resolution(
                feature_id, 
                feature['text'], 
                len(path), 
                len(restoration_queue), 
                False,
                method="traditional"
            )

        return success

    async def _execute_restoration(self, page: Page, queue: List[Dict]) -> bool:
        for step in queue:
            step_type = step['step_type']

            if step_type == 'ensure_url':
                target_url = step['target_url']
                console.print(f"[cyan]   🌐 Navigating to: {target_url}[/cyan]")
                self.logger.log_action("restoration_navigate", {"target_url": target_url})
                
                try:
                    await page.goto(target_url, wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(2)
                    console.print(f"[green]   ✅ Navigated successfully[/green]")
                except Exception as e:
                    console.print(f"[red]   ❌ Navigation failed: {e}[/red]")
                    self.logger.log_error("restoration_navigation_failed", str(e), {"target_url": target_url})
                    return False

            elif step_type == 'expand_container':
                container_text = step['container_text']
                container_location = step.get('container_location', 'sidebar')
                console.print(f"[cyan]   🔓 Expanding: '{container_text}'[/cyan]")
                self.logger.log_action("restoration_expand", {
                    "container_text": container_text,
                    "location": container_location
                })

                container_component = {
                    'text': container_text,
                    'location': container_location,
                    'css_selector': f"text={container_text}",
                    'xpath': None
                }

                clicked = await self.selector.click_element(page, container_component)

                if not clicked:
                    console.print(f"[red]   ❌ Could not expand '{container_text}'[/red]")
                    self.logger.log_error("restoration_expand_failed", f"Could not expand '{container_text}'", {
                        "container_text": container_text
                    })
                    return False

                await asyncio.sleep(1.5)

                is_now_expanded = await self.validator.is_container_expanded(
                    page, container_text, container_location
                )
                if not is_now_expanded:
                    console.print(f"[yellow]   ⚠️  '{container_text}' may not have expanded, continuing anyway[/yellow]")

        return True
    
    def get_stats(self) -> Dict:
        """
        NEW METHOD: Get navigation statistics
        """
        total = self.stats['direct_navigations'] + self.stats['traditional_paths']
        return {
            **self.stats,
            'total_navigations': total,
            'deep_link_success_rate': (
                self.stats['direct_navigations'] / total * 100 
                if total > 0 else 0
            )
        }