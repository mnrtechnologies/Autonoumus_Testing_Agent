import asyncio
from typing import List, Dict
from playwright.async_api import Page
from rich.console import Console
from core.logger import CrawlerLogger

console = Console()


class DOMObserver:
    def __init__(self, logger: CrawlerLogger):
        self.observer_injected = False
        self.logger = logger

    async def inject_observer(self, page: Page):
        if self.observer_injected:
            return

        console.print("[cyan]👁️ DOM OBSERVER: Injecting MutationObserver...[/cyan]")
        self.logger.log_info("Injecting DOM MutationObserver")

        await page.evaluate("""
            () => {
                window.__agentChangeLog = [];
                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        if (mutation.type === 'childList') {
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
                            window.__agentChangeLog.push({
                                action: 'attribute_changed',
                                attribute: mutation.attributeName,
                                old: mutation.oldValue,
                                new: mutation.target.getAttribute(mutation.attributeName),
                                timestamp: Date.now()
                            });
                        }
                    });
                });
                observer.observe(document.body, {
                    childList: true, attributes: true, attributeOldValue: true,
                    subtree: true, characterData: false
                });
                window.__agentObserver = observer;
            }
        """)

        self.observer_injected = True
        console.print("[green]   ✅ MutationObserver active[/green]")

    async def get_changes(self, page: Page) -> List[Dict]:
        try:
            return await page.evaluate("""
                () => {
                    const changes = window.__agentChangeLog || [];
                    window.__agentChangeLog = [];
                    return changes;
                }
            """)
        except:
            return []

    async def detect_change_type(self, changes: List[Dict]) -> str:
        if not changes:
            return "no_change"

        added = sum(1 for c in changes if c.get('action') == 'element_added')
        removed = sum(1 for c in changes if c.get('action') == 'element_removed')

        for change in changes:
            if change.get('tag') in ['DIALOG', 'DIV'] and change.get('action') == 'element_added':
                text = change.get('text', '').lower()
                if 'modal' in text or 'dialog' in text:
                    return "modal_opened"

        if added >= 3:
            return "menu_expanded"
        if removed >= 3:
            return "menu_collapsed"

        for change in changes:
            if change.get('attribute') == 'aria-expanded':
                return "element_expanded" if change.get('new') == 'true' else "element_collapsed"

        return "content_changed"

    def reset(self):
        self.observer_injected = False