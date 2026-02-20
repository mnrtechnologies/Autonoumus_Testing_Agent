
import hashlib
from typing import Dict
from datetime import datetime
from playwright.async_api import Page
from .logger import CrawlerLogger


class StateManager:
    def __init__(self, logger: CrawlerLogger):
        self.states = {}
        self.current_state_hash = None
        self._navigation_occurred = False
        self.logger = logger

    async def calculate_state_hash(self, page: Page) -> str:
        state_data = await page.evaluate("""
            () => ({
                url: window.location.pathname,
                title: document.title,
                main_headings: Array.from(document.querySelectorAll('h1, h2, h3'))
                    .map(h => h.textContent?.trim()).filter(t => t).join('|'),
                interactive_count: document.querySelectorAll('a, button').length
            })
        """)
        hash_string = f"{state_data['url']}::{state_data['main_headings']}::{state_data['interactive_count']}"
        return hashlib.sha256(hash_string.encode()).hexdigest()[:12]

    def is_state_visited(self, state_hash: str) -> bool:
        return state_hash in self.states

    def record_state(self, state_hash, url, breadcrumb, containers, features):
        if state_hash not in self.states:
            self.states[state_hash] = {
                'hash': state_hash,
                'url': url,
                'breadcrumb': breadcrumb,
                'container_count': len(containers),
                'feature_count': len(features),
                'visited_at': datetime.now().isoformat()
            }
            self.logger.log_action("state_recorded", {
                "state_hash": state_hash,
                "url": url,
                "breadcrumb": breadcrumb
            })

    def signal_navigation(self):
        self._navigation_occurred = True
        self.logger.log_action("navigation_signal", {"status": "navigation_occurred"})

    def acknowledge_navigation(self):
        self._navigation_occurred = False

    @property
    def navigation_occurred(self) -> bool:
        return self._navigation_occurred
