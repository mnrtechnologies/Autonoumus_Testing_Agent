import asyncio
from typing import Dict
from playwright.async_api import Page
from rich.console import Console
from core.logger import CrawlerLogger

console = Console()



class SemanticSelector:
    def __init__(self, logger: CrawlerLogger):
        self.logger = logger

    async def click_element(self, page: Page, component: Dict) -> bool:
        text = component.get('text', '')
        location = component.get('location', '')

        console.print(f"[cyan]👆 SEMANTIC CLICK: '{text}' in {location}[/cyan]")
        self.logger.log_action("click_attempt", {
            "text": text,
            "location": location
        })

        try:
            if location == 'sidebar':
                selector = f"aside >> text={text}"
            elif location == 'header':
                selector = f"header >> text={text}"
            else:
                selector = f"text={text}"
            await page.click(selector, timeout=5000)
            console.print(f"[green]   ✅ Clicked using text selector[/green]")
            self.logger.log_action("click_success", {
                "text": text,
                "method": "text_selector"
            })
            return True
        except:
            pass

        try:
            css_sel = component.get('css_selector')
            if css_sel:
                await page.click(css_sel, timeout=3000)
                console.print(f"[green]   ✅ Clicked using CSS selector[/green]")
                self.logger.log_action("click_success", {
                    "text": text,
                    "method": "css_selector"
                })
                return True
        except:
            pass

        try:
            xpath = component.get('xpath')
            if xpath:
                await page.click(f"xpath={xpath}", timeout=3000)
                console.print(f"[green]   ✅ Clicked using XPath[/green]")
                self.logger.log_action("click_success", {
                    "text": text,
                    "method": "xpath"
                })
                return True
        except:
            pass

        try:
            clicked = await page.evaluate("""
                ({text, location}) => {
                    function isInLocation(el, loc) {
                        if (loc === 'sidebar') return el.closest('aside, nav, [class*="sidebar"]') !== null;
                        if (loc === 'header') return el.closest('header') !== null;
                        return true;
                    }
                    const allElements = Array.from(document.querySelectorAll('a, button, div, span, li'));
                    for (const el of allElements) {
                        const elText = el.textContent?.trim() || '';
                        if ((elText === text || elText.includes(text)) && isInLocation(el, location)) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """, {'text': text, 'location': location})

            if clicked:
                console.print(f"[green]   ✅ Clicked using manual search[/green]")
                self.logger.log_action("click_success", {
                    "text": text,
                    "method": "manual_search"
                })
                return True
        except:
            pass

        console.print(f"[red]   ❌ Could not click element[/red]")
        self.logger.log_action("click_failed", {
            "text": text,
            "location": location
        })
        return False