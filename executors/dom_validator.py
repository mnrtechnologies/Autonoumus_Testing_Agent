import asyncio
from typing import Dict
from urllib.parse import urlparse
from playwright.async_api import Page
from rich.console import Console
from core.logger import CrawlerLogger

console = Console()


class DOMStateValidator:
    def __init__(self, logger: CrawlerLogger):
        self.logger = logger

    async def is_on_correct_url(self, page: Page, target_url: str) -> bool:
        current = page.url
        current_path = urlparse(current).path.rstrip('/')
        target_path = urlparse(target_url).path.rstrip('/')
        result = current_path == target_path
        
        self.logger.log_action("url_check", {
            "current_url": current,
            "target_url": target_url,
            "match": result
        })
        
        return result

    async def is_container_expanded(
        self,
        page: Page,
        container_text: str,
        container_location: str
    ) -> bool:
        try:
            result = await page.evaluate("""
                ({text, location}) => {
                    function findInLocation(text, location) {
                        let scope = document;
                        if (location === 'sidebar') {
                            scope = document.querySelector('aside, nav, [class*="sidebar"]') || document;
                        } else if (location === 'header') {
                            scope = document.querySelector('header') || document;
                        }
                        
                        return Array.from(scope.querySelectorAll('*')).find(el => {
                            const t = el.textContent?.trim() || '';
                            return t === text || t.startsWith(text);
                        });
                    }
                    
                    const el = findInLocation(text, location);
                    if (!el) return false;
                    
                    if (el.getAttribute('aria-expanded') === 'true') return true;
                    
                    const parent = el.closest('li, [class*="menu-item"]');
                    if (parent) {
                        const children = parent.querySelectorAll('ul li, [class*="submenu"] li, [class*="sub-item"]');
                        const visibleChildren = Array.from(children).filter(c => {
                            const rect = c.getBoundingClientRect();
                            return rect.height > 0 && rect.width > 0;
                        });
                        return visibleChildren.length > 0;
                    }
                    
                    return false;
                }
            """, {'text': container_text, 'location': container_location})

            self.logger.log_action("container_expansion_check", {
                "container_text": container_text,
                "location": container_location,
                "is_expanded": bool(result)
            })

            return bool(result)

        except Exception as e:
            console.print(f"[dim]   DOM state check failed for '{container_text}': {e}[/dim]")
            self.logger.log_error("dom_state_check_failed", str(e), {
                "container_text": container_text,
                "location": container_location
            })
            return False