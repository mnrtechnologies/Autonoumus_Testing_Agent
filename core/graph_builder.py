import asyncio
from typing import Dict, Optional
from playwright.async_api import Page
from rich.console import Console
from .knowledge_graph import KnowledgeGraph
from .logger import CrawlerLogger

console = Console()
class GraphBuilder:
    def __init__(self, knowledge_graph: KnowledgeGraph, logger: CrawlerLogger):
        self.kg = knowledge_graph
        self.logger = logger

    async def register_container(
        self,
        page: Page,
        container: Dict,
        current_url: str,
        parent_container_id: Optional[str] = None
    ):
        target_url=container.get('target_url')
        container_id = container['semantic_id']

        self.kg.add_node(
            semantic_id=container_id,
            text=container['text'],
            node_type='container',
            location=container.get('location', 'unknown'),
            anchor_url=current_url,
            element_type=container.get('type', 'expandable_menu'),
            confidence='vision_only',
            target_url=container.get('target_url')
        )

        if parent_container_id:
            self.kg.add_edge(
                from_id=parent_container_id,
                to_id=container_id,
                edge_type='dom_action',
                anchor_url=current_url,
                confidence='vision_only'
            )

        self.kg.build_path_for_feature(
            feature_id=container_id,
            parent_container_id=parent_container_id
        )

    async def register_discovered_feature(
        self,
        page: Page,
        feature: Dict,
        parent_container: Dict,
        current_url: str
    ):
        feature_id = feature['semantic_id']
        container_id = parent_container['semantic_id']

        self.kg.add_node(
            semantic_id=feature_id,
            text=feature['text'],
            node_type='feature',
            location=feature.get('location', 'unknown'),
            anchor_url=current_url,
            element_type=feature.get('type', 'unknown'),
            confidence='dom_confirmed',
            target_url=feature.get('target_url')
        )

        is_dom_child = await self._check_dom_ancestry(
            page,
            parent_text=parent_container['text'],
            child_text=feature['text']
        )

        confidence = 'dom_confirmed' if is_dom_child else 'vision_only'

        if is_dom_child:
            self.kg.upgrade_confidence(feature_id)
            console.print(f"[green]   ✅ DOM confirmed: '{feature['text']}' is child of '{parent_container['text']}'[/green]")
            self.logger.log_action("dom_ancestry_confirmed", {
                "parent": parent_container['text'],
                "child": feature['text']
            })
        else:
            console.print(f"[yellow]   ⚠️  Vision only: '{feature['text']}' (could not confirm DOM ancestry)[/yellow]")
            self.logger.log_action("dom_ancestry_failed", {
                "parent": parent_container['text'],
                "child": feature['text']
            })

        self.kg.add_edge(
            from_id=container_id,
            to_id=feature_id,
            edge_type='dom_action',
            anchor_url=current_url,
            confidence='dom_confirmed'
        )

        self.kg.build_path_for_feature(
            feature_id=feature_id,
            parent_container_id=container_id
        )
        return True

    async def register_top_level_feature(
        self,
        page: Page,
        feature: Dict,
        current_url: str
    ):
        feature_id = feature['semantic_id']

        self.kg.add_node(
            semantic_id=feature_id,
            text=feature['text'],
            node_type='feature',
            location=feature.get('location', 'unknown'),
            anchor_url=current_url,
            element_type=feature.get('type', 'unknown'),
            confidence='dom_confirmed',
            target_url=feature.get('target_url')
        )

        self.kg.build_path_for_feature(
            feature_id=feature_id,
            parent_container_id=None
        )

    async def _check_dom_ancestry(
        self,
        page: Page,
        parent_text: str,
        child_text: str
    ) -> bool:
        try:
            result = await page.evaluate("""
                ({parentText, childText}) => {
                    const allElements = Array.from(document.querySelectorAll('*'));
                    
                    const parentEl = allElements.find(el => {
                        const directText = Array.from(el.childNodes)
                            .filter(n => n.nodeType === Node.TEXT_NODE)
                            .map(n => n.textContent.trim())
                            .join('');
                        return directText.includes(parentText) || 
                            el.textContent.trim().startsWith(parentText);
                    });
                    
                    if (!parentEl) return false;
                    
                    const containerEl = parentEl.closest('li, [class*="menu-item"], [class*="nav-item"]') 
                                    || parentEl.parentElement;
                    
                    if (!containerEl) return false;
                    
                    const childEl = Array.from(containerEl.querySelectorAll('*'))
                        .find(el => {
                            const text = el.textContent?.trim() || '';
                            return text.includes(childText) || text.startsWith(childText);
                        });
                    
                    if (!childEl) return false;
                    
                    const childLocation = childEl.closest('[class*="sidebar"]') ? 'sidebar' :
                                        childEl.closest('[class*="header"]') ? 'header' :
                                        childEl.closest('main, [class*="content"]') ? 'main' : 'unknown';
                    
                    const parentLocation = containerEl.closest('[class*="sidebar"]') ? 'sidebar' :
                                        containerEl.closest('[class*="header"]') ? 'header' : 'unknown';
                    
                    if (childLocation === 'main' && parentLocation === 'sidebar') {
                        return false;
                    }
                    
                    const isExpanded = parentEl.getAttribute('aria-expanded') === 'true';
                    const hasVisibleChildren = containerEl.querySelector('ul, [class*="submenu"], [class*="dropdown"]');
                    
                    if (hasVisibleChildren) {
                        const collapsibleSection = childEl.closest('ul, [class*="submenu"], [class*="dropdown"]');
                        if (!collapsibleSection) return false;
                        
                        if (!containerEl.contains(collapsibleSection)) return false;
                    }
                    
                    return true;
                }
            """, {'parentText': parent_text, 'childText': child_text})

            return bool(result)

        except Exception as e:
            console.print(f"[dim]   DOM ancestry check failed: {e}[/dim]")
            self.logger.log_error("dom_ancestry_check_exception", str(e), {
                "parent_text": parent_text,
                "child_text": child_text
            })
            return False
