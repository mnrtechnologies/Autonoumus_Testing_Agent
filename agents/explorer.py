"""
CASCADING Explorer - Handles Dependent/Cascading Dropdowns
Waits for each dropdown to populate before moving to the next one
"""

import asyncio
import json
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress
from rich.tree import Tree

console = Console()


class CascadingExplorerAgent:
    """Handles cascading/dependent dropdowns that populate based on previous selections"""
    
    def __init__(self, base_url: str, auth_data: Optional[Dict] = None):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.discovered_urls = set()
        self.feature_hierarchy = []
        
        self.auth_data = auth_data
        self.requires_auth = auth_data is not None
    
    async def deep_discover(self) -> Dict:
        """Deep discovery with cascading dropdown support"""
        console.print("[bold cyan]🏗️ CASCADING Explorer Agent - Starting[/bold cyan]")
        console.print("[yellow]🎯 Handles dependent dropdowns that load sequentially[/yellow]")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            # LEVEL 1: Discover Main Pages
            console.print("\n[bold]═══ LEVEL 1: Main Pages ═══[/bold]")
            
            if self.requires_auth:
                await self._setup_auth(page, context)
            else:
                await page.goto(self.base_url, wait_until='networkidle')
            
            dashboard_elements = await self._extract_clickable_elements(page)
            main_pages = await self._click_and_discover_pages(page, dashboard_elements)
            
            console.print(f"[bold green]✅ Level 1 Complete: {len(main_pages)} pages[/bold green]")
            
            # LEVEL 2 & 3: Deep dive with cascading support
            console.print("\n[bold]═══ LEVEL 2-3: Features & Cascading Dropdowns ═══[/bold]")
            
            for page_data in main_pages:
                console.print(f"\n[cyan]🔍 Exploring: {page_data['name']}[/cyan]")
                
                await page.goto(page_data['url'], wait_until='networkidle', timeout=15000)
                await asyncio.sleep(2)
                
                # Discover all features
                page_features = await self._discover_page_features(page, page_data)
                page_data['features'] = page_features
                
                # Handle cascading dropdowns
                dropdowns = [f for f in page_features if f['type'] == 'dropdown']
                
                if dropdowns:
                    console.print(f"  📋 Found {len(dropdowns)} dropdowns")
                    
                    # Explore cascading chain
                    await self._explore_cascading_dropdowns(page, dropdowns, page_data)
                
                console.print(f"[green]  ✅ Completed: {page_data['name']}[/green]")
            
            await browser.close()
        
        self.feature_hierarchy = main_pages
        self._display_feature_tree()
        
        return {
            'base_url': self.base_url,
            'main_pages': main_pages,
            'total_pages': len(main_pages),
            'total_features': sum(len(p.get('features', [])) for p in main_pages),
            'feature_hierarchy': self.feature_hierarchy
        }
    
    async def _explore_cascading_dropdowns(self, page, dropdowns, page_data):
        """
        COMPLETE FIX: Properly detect and explore cascading dropdowns
        - Pure JavaScript evaluation (no Playwright locators)
        - Skip language/non-data dropdowns
        - Select valid options and trigger events
        - Wait for cascade to complete
        """
        console.print(f"  🔗 Checking for cascading dependencies...")
        
        # Step 1: Get initial state of ALL dropdowns using pure JS
        data_dropdowns = []
        
        for i, dropdown in enumerate(dropdowns):
            options = await self._get_dropdown_options(page, dropdown)
            
            # Detect language dropdown (2 options: English + Telugu)
            is_language_dropdown = False
            if len(options) == 2:
                texts = [opt['text'].lower() for opt in options]
                if 'english' in texts[0] or 'english' in texts[1]:
                    is_language_dropdown = True
            
            if is_language_dropdown:
                console.print(f"    🌐 Skipping language dropdown: {dropdown['label']}")
                dropdown['options'] = options
                dropdown['is_language'] = True
                continue
            
            # This is a data dropdown
            data_dropdowns.append({
                'index': i,
                'dropdown': dropdown,
                'has_options': len(options) > 0,
                'option_count': len(options),
                'initial_options': options
            })
        
        if not data_dropdowns:
            console.print(f"    ⚠️  No data dropdowns found (only language selectors)")
            return
        
        # Step 2: Identify cascade chain
        enabled = [d for d in data_dropdowns if d['has_options']]
        disabled = [d for d in data_dropdowns if not d['has_options']]
        
        console.print(f"    ✅ {len(enabled)} data dropdowns enabled")
        console.print(f"    ⏸️  {len(disabled)} data dropdowns waiting (cascading)")
        
        if not disabled:
            # No cascading - just store options
            for dd in data_dropdowns:
                dd['dropdown']['options'] = dd['initial_options']
                if dd['initial_options']:
                    console.print(f"    📋 {dd['dropdown']['label']}: {len(dd['initial_options'])} options")
            return
        
        # Step 3: CASCADING DETECTED - Explore sequentially
        console.print(f"  🔗 Cascading chain detected! Exploring sequentially...")
        
        for dd_index, dd_state in enumerate(data_dropdowns):
            dropdown = dd_state['dropdown']
            dropdown_index = dropdown['index']
            
            # Re-fetch current options
            options = await self._get_dropdown_options(page, dropdown)
            
            if not options:
                console.print(f"    ⏸️  {dropdown['label']}: Waiting for previous selection")
                dropdown['options'] = []
                continue
            
            console.print(f"    📋 {dropdown['label']}: {len(options)} options")
            dropdown['options'] = options
            
            # Find first valid option (skip placeholders)
            valid_option = None
            for opt in options:
                opt_val = str(opt['value']).lower().strip()
                opt_text = opt['text'].lower().strip()
                
                # Skip empty or placeholder values
                if not opt_val or opt_val in ['', 'select', 'choose', '--', '0', 'null', 'undefined']:
                    continue
                
                # Skip placeholder text
                if any(keyword in opt_text for keyword in ['select', 'choose', 'pick', '--', 'please select']):
                    continue
                
                valid_option = opt
                break
            
            # Fallback strategies
            if not valid_option and len(options) > 1:
                # Try second option
                valid_option = options[1]
            elif not valid_option and options:
                # Last resort: use first option
                valid_option = options[0]
            
            if valid_option:
                try:
                    console.print(f"      🔹 Selecting: '{valid_option['text'][:50]}' (value: {valid_option['value']})")
                    
                    # Use pure JavaScript to select and trigger events
                    selection_result = await page.evaluate("""
                        (args) => {
                            const selects = document.querySelectorAll('select');
                            const select = selects[args.index];
                            
                            if (!select) return { success: false, error: 'Dropdown not found' };
                            
                            try {
                                // Set the value
                                select.value = args.value;
                                
                                // Trigger all possible events
                                const events = ['input', 'change', 'blur'];
                                events.forEach(eventType => {
                                    const event = new Event(eventType, { bubbles: true, cancelable: true });
                                    select.dispatchEvent(event);
                                });
                                
                                // Also try React-style events if it's a React app
                                if (select._valueTracker) {
                                    select._valueTracker.setValue('');
                                }
                                
                                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                    window.HTMLSelectElement.prototype, 
                                    'value'
                                ).set;
                                nativeInputValueSetter.call(select, args.value);
                                
                                const changeEvent = new Event('change', { bubbles: true });
                                select.dispatchEvent(changeEvent);
                                
                                return { success: true, selectedValue: select.value };
                            } catch (error) {
                                return { success: false, error: error.message };
                            }
                        }
                    """, {'index': dropdown_index, 'value': valid_option['value']})
                    
                    if not selection_result.get('success'):
                        console.print(f"      ⚠️  Selection warning: {selection_result.get('error', 'Unknown')}")
                    
                    console.print(f"      ⏳ Waiting for cascade to load...")
                    
                    # Wait for network activity with multiple strategies
                    try:
                        # First try: wait for network idle
                        await page.wait_for_load_state('networkidle', timeout=3000)
                    except:
                        pass
                    
                    # Additional wait for DOM updates
                    await asyncio.sleep(2)
                    
                    # Check if next dropdown became enabled
                    next_dd_idx = dd_index + 1
                    if next_dd_idx < len(data_dropdowns):
                        next_dd = data_dropdowns[next_dd_idx]
                        next_dropdown = next_dd['dropdown']
                        
                        # Re-fetch options for next dropdown
                        next_options = await self._get_dropdown_options(page, next_dropdown)
                        
                        if next_options:
                            console.print(f"      ✅ Next dropdown '{next_dropdown['label']}' unlocked: {len(next_options)} options")
                            next_dd['has_options'] = True
                            next_dd['initial_options'] = next_options
                            # Update the dropdown's options immediately
                            next_dropdown['options'] = next_options
                        else:
                            console.print(f"      ⚠️  Next dropdown '{next_dropdown['label']}' still empty")
                            
                            # Try waiting a bit more and check again
                            await asyncio.sleep(2)
                            next_options_retry = await self._get_dropdown_options(page, next_dropdown)
                            if next_options_retry:
                                console.print(f"      ✅ (Retry) Next dropdown now has {len(next_options_retry)} options")
                                next_dd['has_options'] = True
                                next_dd['initial_options'] = next_options_retry
                                next_dropdown['options'] = next_options_retry
                    
                except Exception as e:
                    console.print(f"      ❌ Selection failed: {str(e)[:80]}")
            else:
                console.print(f"      ⚠️  No valid option found to select")
        
        # Step 4: Final verification - get ALL dropdown states
        console.print(f"  🔄 Final verification: Getting complete state...")
        for dropdown in dropdowns:
            if dropdown.get('is_language'):
                continue
            
            final_options = await self._get_dropdown_options(page, dropdown)
            dropdown['options'] = final_options
            
            if final_options:
                console.print(f"    ✅ {dropdown['label']}: {len(final_options)} options")
            else:
                console.print(f"    ⏸️  {dropdown['label']}: Still empty (may need manual interaction)")
    
    async def _get_dropdown_options(self, page, dropdown):
        """Get options from a dropdown - COMPLETELY AVOIDING PLAYWRIGHT LOCATORS"""
        try:
            dropdown_index = dropdown.get('index', 0)
            
            # Use pure JavaScript evaluation - NO Playwright locators
            dropdown_info = await page.evaluate("""
                (dropdownIdx) => {
                    const selects = document.querySelectorAll('select');
                    const select = selects[dropdownIdx];
                    
                    if (!select) return null;
                    
                    const info = {
                        disabled: select.disabled,
                        optionCount: select.options.length,
                        options: []
                    };
                    
                    // Get all options
                    Array.from(select.options).forEach(opt => {
                        const value = opt.value;
                        const text = opt.innerText.trim();
                        
                        if (value || text) {
                            info.options.push({
                                value: value,
                                text: text,
                                disabled: opt.disabled
                            });
                        }
                    });
                    
                    return info;
                }
            """, dropdown_index)
            
            if not dropdown_info:
                return []
            
            if dropdown_info['disabled']:
                return []
            
            # Filter out disabled options
            valid_options = [
                opt for opt in dropdown_info['options'] 
                if not opt.get('disabled')
            ]
            
            return valid_options
            
        except Exception as e:
            console.print(f"    ⚠️ Error getting options from {dropdown.get('label', 'dropdown')}: {str(e)[:60]}")
            return []
    async def _click_and_discover_pages(self, page, elements):
        """Click dashboard elements to discover main pages"""
        main_pages = []
        
        ai_apps = [e for e in elements if any(keyword in e.get('text', '').lower() 
                  for keyword in ['question', 'content', 'progress', 'learning', 
                                  'video', 'evaluation', 'lab'])]
        
        console.print(f"[cyan]🖱️ Clicking {len(ai_apps)} AI Apps...[/cyan]")
        
        for i, app in enumerate(ai_apps):
            try:
                console.print(f"  [{i+1}/{len(ai_apps)}] {app['text'][:40]}...", end="")
                
                initial_url = page.url
                clicked = await self._smart_click(page, app, i)
                
                if clicked:
                    await page.wait_for_load_state('networkidle', timeout=5000)
                    await asyncio.sleep(1)
                    
                    new_url = page.url
                    
                    if new_url != initial_url and self._is_same_domain(new_url):
                        main_pages.append({
                            'name': app['text'].strip(),
                            'url': new_url,
                            'features': []
                        })
                        console.print(f" ✅")
                    else:
                        console.print(f" ⚠️")
                    
                    await page.goto(self.base_url, wait_until='networkidle')
                    await asyncio.sleep(1)
                else:
                    console.print(f" ❌")
                    
            except Exception as e:
                console.print(f" ❌ {str(e)[:30]}")
        
        return main_pages
    
    async def _discover_page_features(self, page, page_data):
        """Discover all interactive features on a page"""
        features = await page.evaluate("""
            () => {
                const features = [];
                
                // Dropdowns
                document.querySelectorAll('select').forEach((select, i) => {
                    // Try to get label from various sources
                    let label = 'Dropdown ' + (i+1);
                    
                    // Check previous sibling
                    if (select.previousElementSibling && select.previousElementSibling.innerText) {
                        label = select.previousElementSibling.innerText.trim();
                    }
                    
                    // Check parent label
                    const parentLabel = select.closest('label');
                    if (parentLabel && parentLabel.innerText) {
                        label = parentLabel.innerText.trim();
                    }
                    
                    // Check aria-label or placeholder
                    if (select.getAttribute('aria-label')) {
                        label = select.getAttribute('aria-label');
                    }
                    
                    features.push({
                        type: 'dropdown',
                        label: label.substring(0, 50),
                        id: select.id,
                        name: select.name,
                        index: i,
                        selector: select.id ? `#${select.id}` : `select:nth-of-type(${i+1})`,
                        disabled: select.disabled
                    });
                });
                
                // Input fields
                document.querySelectorAll('input[type="text"], input[type="number"], textarea').forEach((input, i) => {
                    const label = input.previousElementSibling?.innerText || 
                                  input.placeholder ||
                                  `Input ${i+1}`;
                    
                    features.push({
                        type: 'input',
                        label: label.trim(),
                        placeholder: input.placeholder
                    });
                });
                
                // Buttons
                document.querySelectorAll('button:not([disabled])').forEach((btn, i) => {
                    const text = btn.innerText.trim();
                    if (text && text.length < 50) {
                        features.push({
                            type: 'button',
                            label: text,
                            selector: `button:nth-of-type(${i+1})`
                        });
                    }
                });
                
                // File uploads
                document.querySelectorAll('input[type="file"]').forEach((input, i) => {
                    const label = input.previousElementSibling?.innerText || `File Upload ${i+1}`;
                    features.push({
                        type: 'file-upload',
                        label: label.trim(),
                        accept: input.accept
                    });
                });
                
                return features;
            }
        """)
        
        return features
    
    async def _smart_click(self, page, element, index):
        """Try multiple strategies to click"""
        clicked = False
        
        if not clicked and element.get('text'):
            try:
                el = page.locator(f"text={element['text'][:20]}").first
                await el.wait_for(state='visible', timeout=3000)
                await el.click(timeout=3000)
                clicked = True
            except:
                pass
        
        if not clicked:
            try:
                el = page.locator("div.cursor-pointer").nth(index)
                await el.wait_for(state='visible', timeout=3000)
                await el.click(timeout=3000)
                clicked = True
            except:
                pass
        
        return clicked
    
    async def _setup_auth(self, page, context):
        """Set up authentication"""
        console.print(f"[cyan]🔑 Injecting authentication...[/cyan]")
        
        parsed = urlparse(self.base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"
        
        await page.goto(homepage)
        await page.wait_for_load_state('networkidle')
        
        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                if isinstance(value, str):
                    await page.evaluate(f"window.localStorage.setItem('{key}', '{value}')")
                else:
                    await page.evaluate(f"window.localStorage.setItem('{key}', '{json.dumps(value)}')")
            except:
                pass
        
        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                if isinstance(value, str):
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', '{value}')")
                else:
                    await page.evaluate(f"window.sessionStorage.setItem('{key}', '{json.dumps(value)}')")
            except:
                pass
        
        cookies = self.auth_data.get('cookies', [])
        if cookies:
            try:
                await context.add_cookies(cookies)
            except:
                pass
        
        console.print("[green]✅ Auth injected[/green]")
        await page.goto(self.base_url, wait_until='networkidle', timeout=15000)
        
        if 'login' in page.url.lower():
            raise Exception("Authentication failed")
        
        console.print("[green]✅ Authenticated![/green]")
    
    async def _extract_clickable_elements(self, page):
        """Extract clickable elements"""
        return await page.evaluate("""
            () => {
                const elements = [];
                
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.href;
                    if (href && !href.startsWith('javascript:') && !href.startsWith('mailto:')) {
                        elements.push({type: 'link', href: href, text: a.innerText.trim()});
                    }
                });
                
                document.querySelectorAll('div[class*="cursor-pointer"], div[onclick]').forEach((div, index) => {
                    elements.push({type: 'clickable-div', text: div.innerText.trim(), index: index});
                });
                
                return elements;
            }
        """)
    
    def _is_same_domain(self, url: str) -> bool:
        try:
            return urlparse(url).netloc == self.domain
        except:
            return False
    
    def _display_feature_tree(self):
        """Display discovered features as tree"""
        console.print("\n[bold]═══ COMPLETE FEATURE MAP ═══[/bold]\n")
        
        tree = Tree("🏠 Dashboard")
        
        for page in self.feature_hierarchy:
            page_branch = tree.add(f"📄 {page['name']}")
            
            for feature in page.get('features', []):
                if feature['type'] == 'dropdown':
                    opts = feature.get('options', [])
                    if opts:
                        feature_branch = page_branch.add(
                            f"📋 {feature['label']} ({len(opts)} options)"
                        )
                        for opt in opts[:3]:
                            feature_branch.add(f"  • {opt['text']}")
                        if len(opts) > 3:
                            feature_branch.add(f"  ... +{len(opts)-3} more")
                    else:
                        page_branch.add(f"📋 {feature['label']} (empty/dependent)")
                else:
                    page_branch.add(f"{self._get_icon(feature['type'])} {feature['label']}")
        
        console.print(tree)
    
    def _get_icon(self, feature_type):
        icons = {
            'input': '📝',
            'button': '🔘',
            'file-upload': '📎',
            'dropdown': '📋'
        }
        return icons.get(feature_type, '•')
    
    async def run(self) -> Dict:
        """Execute cascading discovery"""
        discovery = await self.deep_discover()
        
        output_path = Path('output') / 'knowledge_base_cascading.json'
        output_path.parent.mkdir(exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(discovery, f, indent=2)
        
        console.print(f"\n[bold green]✅ Cascading KB saved: {output_path}[/bold green]")
        console.print(f"[bold]📊 Summary:[/bold]")
        console.print(f"  • Pages: {discovery['total_pages']}")
        console.print(f"  • Features: {discovery['total_features']}")
        
        return discovery


# Compatibility alias
ExplorerAgent = CascadingExplorerAgent


async def main():
    with open('auth.json') as f:
        auth = json.load(f)
    
    explorer = CascadingExplorerAgent("https://www.mnr-pst.com/dashboard", auth)
    kb = await explorer.run()


if __name__ == "__main__":
    asyncio.run(main())