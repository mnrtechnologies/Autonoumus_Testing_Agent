import asyncio
from typing import List, Dict, Optional
from playwright.async_api import Page
from rich.console import Console
from core.logger import CrawlerLogger
from urllib.parse import urljoin, urlparse

console = Console()


class ComponentDetector:
    def __init__(self, logger: CrawlerLogger):
        self.logger = logger

    async def detect_containers(self, page: Page, vision_containers: List[Dict]) -> List[Dict]:
        console.print("[cyan]🔍 CONTAINER DETECTION: Mapping containers to DOM...[/cyan]")
        self.logger.log_info("Starting container detection")
        
        containers = []
        container_id = 1

        for container_data in vision_containers:
            text = container_data.get('text', '')
            container_type = container_data.get('type', 'unknown')
            location = container_data.get('location', 'unknown')

            if not text:
                continue

            dom_element = await self._find_element_by_semantics(page, text, location, container_type)

            if dom_element:
                container = {
                    'container_id': container_id,
                    'semantic_id': self._create_semantic_id(text, location, container_type),
                    'text': text,
                    'type': container_type,
                    'location': location,
                    'state': container_data.get('state', 'unknown'),
                    'expected_children': container_data.get('expected_children', []),
                    'discovery_priority': container_data.get('discovery_priority', 5),
                    'xpath': dom_element['xpath'],
                    'css_selector': dom_element['css_selector'],
                    'target_url': dom_element.get('target_url'),  # NEW: Add target URL
                    'vision_data': container_data
                }
                containers.append(container)
                
                # Log URL extraction if found
                if dom_element.get('target_url'):
                    console.print(f"[green]         🔗 Extracted URL: {dom_element['target_url']}[/green]")
                
                self.logger.log_action("container_detected", {
                    "container_id": container_id,
                    "text": text,
                    "type": container_type,
                    "location": location,
                    "has_target_url": bool(dom_element.get('target_url'))
                })
                container_id += 1

        console.print(f"[green]   ✅ Detected {len(containers)} containers[/green]")
        self.logger.log_info(f"Detected {len(containers)} containers")
        return containers

    async def detect_features(self, page: Page, vision_features: List[Dict]) -> List[Dict]:
        console.print("[cyan]🔍 FEATURE DETECTION: Mapping features to DOM...[/cyan]")
        self.logger.log_info("Starting feature detection")
        
        features = []
        feature_id = 1

        for feature_data in vision_features:
            text = feature_data.get('text', '')
            feature_type = feature_data.get('type', 'unknown')
            location = feature_data.get('location', 'unknown')

            if not text:
                continue

            dom_element = await self._find_element_by_semantics(page, text, location, feature_type)

            if dom_element:
                feature = {
                    'feature_id': feature_id,
                    'semantic_id': self._create_semantic_id(text, location, feature_type),
                    'text': text,
                    'type': feature_type,
                    'location': location,
                    'test_priority': feature_data.get('test_priority', 5),
                    'expected_behavior': feature_data.get('expected_behavior', ''),
                    'xpath': dom_element['xpath'],
                    'css_selector': dom_element['css_selector'],
                    'target_url': dom_element.get('target_url'),  # NEW: Add target URL
                    'vision_data': feature_data
                }
                features.append(feature)
                
                # Log URL extraction if found
                if dom_element.get('target_url'):
                    console.print(f"[green]         🔗 Extracted URL: {dom_element['target_url']}[/green]")
                
                self.logger.log_action("feature_detected", {
                    "feature_id": feature_id,
                    "text": text,
                    "type": feature_type,
                    "location": location,
                    "has_target_url": bool(dom_element.get('target_url'))
                })
                feature_id += 1

        console.print(f"[green]   ✅ Detected {len(features)} features[/green]")
        self.logger.log_info(f"Detected {len(features)} features")
        return features

    async def _find_element_by_semantics(self, page, text, location, elem_type) -> Optional[Dict]:
        """
        UPGRADED: Now extracts href attributes for direct URL navigation
        """
        console.print(f"[cyan]      🔎 Searching for: '{text}'[/cyan]")
        try:
            selectors_to_try = [f"text={text}", f"text=/{text}/i"]

            if location == 'sidebar':
                selectors_to_try.insert(0, f"aside >> text={text}")
                selectors_to_try.insert(0, f"nav >> text={text}")
            elif location == 'header':
                selectors_to_try.insert(0, f"header >> text={text}")

            for selector in selectors_to_try:
                try:
                    element = await page.wait_for_selector(selector, timeout=2000, state='visible')
                    if element:
                        console.print(f"[green]         ✅ Found with selector: {selector}[/green]")
                        
                        # NEW: Extract target URL if this is a link
                        target_url = await self._extract_target_url(page, element, text)
                        
                        return {
                            'found': True,
                            'xpath': f"//text()[contains(., '{text}')]/parent::*",
                            'css_selector': selector,
                            'actual_text': text,
                            'target_url': target_url  # NEW: Include extracted URL
                        }
                except:
                    continue

            console.print(f"[red]         ❌ Not found[/red]")
            return None

        except Exception as e:
            console.print(f"[red]         Exception: {e}[/red]")
            return None

    async def _extract_target_url(self, page: Page, element, text: str) -> Optional[str]:
        """
        NEW METHOD: Extracts and normalizes the target URL from an element
        
        Logic:
        1. Check if element is <a> tag or has href attribute
        2. Extract href value
        3. Filter out invalid URLs (javascript:, #, logout, etc.)
        4. Convert relative URLs to absolute
        5. Return normalized URL or None
        """
        try:
            # Check tag name
            tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
            
            # Only process links
            if tag_name != 'a':
                # Check if it's wrapped in a link
                parent_link = await element.evaluate("""
                    el => {
                        let current = el;
                        while (current && current.tagName !== 'A') {
                            current = current.parentElement;
                        }
                        return current ? current.href : null;
                    }
                """)
                if not parent_link:
                    return None
                href = parent_link
            else:
                # Direct <a> tag
                href = await element.get_attribute('href')
            
            if not href:
                return None
            
            # Filter out invalid/unwanted URLs
            invalid_patterns = [
                'javascript:',
                'void(0)',
                '#',
                'logout',
                'signout',
                'sign-out'
            ]
            
            href_lower = href.lower()
            if any(pattern in href_lower for pattern in invalid_patterns):
                console.print(f"[dim]         ⏭️  Skipping invalid href: {href}[/dim]")
                return None
            
            # Convert relative URLs to absolute
            current_url = page.url
            absolute_url = urljoin(current_url, href)
            
            # Validate the URL structure
            parsed = urlparse(absolute_url)
            if not parsed.scheme or not parsed.netloc:
                console.print(f"[yellow]         ⚠️  Malformed URL: {absolute_url}[/yellow]")
                return None
            
            # Success!
            console.print(f"[cyan]         ⚡ Deep Link Extracted: {absolute_url}[/cyan]")
            return absolute_url
            
        except Exception as e:
            console.print(f"[dim]         ⚠️  URL extraction failed: {e}[/dim]")
            return None

    def _create_semantic_id(self, text: str, location: str, elem_type: str) -> str:
        normalized = text.lower().replace(' ', '_').replace('-', '_')
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')
        return f"{location}_{elem_type}_{normalized}"[:50]