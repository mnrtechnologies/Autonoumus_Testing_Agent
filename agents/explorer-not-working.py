"""
IMPROVED DYNAMIC Explorer - Detects ALL clickable patterns dynamically
No hardcoding, just smart pattern recognition
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
from rich.table import Table

console = Console()


class ImprovedDynamicExplorer:
    """Explorer that dynamically discovers ALL clickable patterns"""

    def __init__(self, base_url: str, auth_data: Optional[Dict] = None, debug_mode: bool = True):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.discovered_urls = set()
        self.feature_hierarchy = []
        self.visited_urls = set()
        self.debug_mode = debug_mode

        self.auth_data = auth_data
        self.requires_auth = auth_data is not None

        # Debug stats
        self.debug_stats = {
            'total_detected': 0,
            'links': 0,
            'cards': 0,
            'buttons': 0,
            'clickable_divs': 0,
            'successful_navigations': 0,
            'failed_clicks': 0,
            'same_page_clicks': 0
        }

    async def deep_discover(self) -> Dict:
        """Deep discovery with DYNAMIC detection"""
        console.print("[bold cyan]🚀 IMPROVED DYNAMIC Explorer - Starting[/bold cyan]")
        console.print("[yellow]🎯 Detects ALL clickable patterns dynamically[/yellow]")

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

            await asyncio.sleep(2)

            # Get ALL clickable elements dynamically
            all_clickables = await self._extract_all_clickable_elements(page)
            console.print(f"\n[cyan]📊 Found {len(all_clickables)} clickable elements[/cyan]")

            # Discover main pages
            main_pages = await self._discover_main_pages_with_debug(page, all_clickables)

            console.print(f"\n[bold green]✅ Level 1 Complete: {len(main_pages)} unique pages discovered[/bold green]")

            # Show debug stats
            if self.debug_mode:
                self._show_debug_stats()

            # LEVEL 2 & 3: Deep dive
            console.print("\n[bold]═══ LEVEL 2-3: Features & Cascading Dropdowns ═══[/bold]")

            for page_data in main_pages:
                console.print(f"\n[cyan]🔍 Exploring: {page_data['name']}[/cyan]")

                try:
                    await page.goto(page_data['url'], wait_until='networkidle', timeout=15000)
                    await asyncio.sleep(2)

                    page_features = await self._discover_page_features(page, page_data)
                    page_data['features'] = page_features

                    dropdowns = [f for f in page_features if f['type'] == 'dropdown']

                    if dropdowns:
                        console.print(f"  📋 Found {len(dropdowns)} dropdowns")
                        await self._explore_cascading_dropdowns(page, dropdowns, page_data)

                    console.print(f"[green]  ✅ Completed: {page_data['name']}[/green]")

                except Exception as e:
                    console.print(f"[red]  ❌ Error: {str(e)[:80]}[/red]")

            await browser.close()

        self.feature_hierarchy = main_pages
        self._display_feature_tree()

        return {
            'main_pages': main_pages,
            'total_pages': len(main_pages),
            'total_features': sum(len(p.get('features', [])) for p in main_pages),
            'feature_hierarchy': self.feature_hierarchy,
            'content': self._build_content_index(main_pages),
            'debug_stats': self.debug_stats
        }

    async def _extract_all_clickable_elements(self, page):
        """
        Extract ALL potentially clickable elements using MULTIPLE strategies
        This is DYNAMIC - it finds patterns rather than hardcoding
        """
        console.print("[cyan]🎯 Extracting clickable elements with multiple strategies...[/cyan]")

        clickables = await page.evaluate("""
            () => {
                const elements = [];
                const seen = new Set();

                function getVisibleText(el) {
                    let text = '';
                    for (let node of el.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) {
                            text += node.textContent.trim() + ' ';
                        }
                    }
                    return text.trim() || el.innerText?.trim() || '';
                }

                function isVisible(el) {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                           style.visibility !== 'hidden' &&
                           style.opacity !== '0' &&
                           el.offsetParent !== null &&
                           rect.width > 0 && rect.height > 0;
                }

                function getUniqueKey(el, text, index) {
                    return el.tagName + '-' + text + '-' + index;
                }

                // STRATEGY 1: Traditional links
                console.log("Strategy 1: Links");
                document.querySelectorAll('a[href]').forEach((a, index) => {
                    if (!isVisible(a)) return;

                    const href = a.href;
                    const text = getVisibleText(a);

                    if (href && !href.startsWith('javascript:') &&
                        !href.startsWith('mailto:') &&
                        !href.startsWith('#') &&
                        text.length > 0 && text.length < 100) {

                        const key = 'link-' + href + text;
                        if (!seen.has(key)) {
                            seen.add(key);
                            elements.push({
                                type: 'link',
                                href: href,
                                text: text,
                                priority: 1,
                                selector: `a[href="${href}"]`
                            });
                        }
                    }
                });
                console.log(`Found ${elements.length} links`);

                // STRATEGY 2: Angular router links
                console.log("Strategy 2: Router links");
                const routerCount = elements.length;
                document.querySelectorAll('[routerlink], [ng-reflect-router-link]').forEach((el, index) => {
                    if (!isVisible(el)) return;

                    const routerLink = el.getAttribute('routerlink') || el.getAttribute('ng-reflect-router-link');
                    const text = getVisibleText(el);

                    if (routerLink && text.length > 0 && text.length < 100) {
                        const key = 'router-' + routerLink + text;
                        if (!seen.has(key)) {
                            seen.add(key);
                            elements.push({
                                type: 'router-link',
                                text: text,
                                routerLink: routerLink,
                                priority: 2,
                                selector: `[routerlink="${routerLink}"]`
                            });
                        }
                    }
                });
                console.log(`Found ${elements.length - routerCount} router links`);

                // STRATEGY 3: Elements with onclick
                console.log("Strategy 3: Onclick elements");
                const onclickCount = elements.length;
                document.querySelectorAll('[onclick]').forEach((el, index) => {
                    if (!isVisible(el)) return;

                    const text = getVisibleText(el);

                    if (text.length > 0 && text.length < 100) {
                        const key = getUniqueKey(el, text, index);
                        if (!seen.has(key)) {
                            seen.add(key);
                            elements.push({
                                type: 'onclick-element',
                                text: text,
                                priority: 3,
                                tagName: el.tagName,
                                index: index
                            });
                        }
                    }
                });
                console.log(`Found ${elements.length - onclickCount} onclick elements`);

                // STRATEGY 4: Buttons
                console.log("Strategy 4: Buttons");
                const buttonCount = elements.length;
                document.querySelectorAll('button:not([disabled])').forEach((btn, index) => {
                    if (!isVisible(btn)) return;

                    const text = getVisibleText(btn);

                    if (text.length > 0 && text.length < 100) {
                        const key = getUniqueKey(btn, text, index);
                        if (!seen.has(key)) {
                            seen.add(key);
                            elements.push({
                                type: 'button',
                                text: text,
                                priority: 4,
                                index: index
                            });
                        }
                    }
                });
                console.log(`Found ${elements.length - buttonCount} buttons`);

                // STRATEGY 5: Clickable divs/cards (cursor-pointer, hover effects, etc.)
                // THIS IS THE KEY - detect card-based navigation patterns
                console.log("Strategy 5: Clickable cards and divs");
                const cardCount = elements.length;

                const clickableSelectors = [
                    '.cursor-pointer',  // Tailwind cursor pointer
                    '[class*="clickable"]',
                    '[class*="card"][class*="cursor"]',
                    'div[class*="hover:scale"]',  // Tailwind hover effects
                    'div[class*="hover:shadow"]',
                    '[role="button"]',
                    'div[onclick]'
                ];

                clickableSelectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach((el, index) => {
                        if (!isVisible(el)) return;

                        const text = getVisibleText(el);

                        // Must have meaningful text
                        if (text.length < 3 || text.length > 100) return;

                        // Skip if it's just a container with links inside
                        const hasLinksInside = el.querySelectorAll('a[href]').length > 0;
                        if (hasLinksInside) return;

                        const key = getUniqueKey(el, text, index);
                        if (!seen.has(key)) {
                            seen.add(key);

                            // Get computed style to check for clickability indicators
                            const style = window.getComputedStyle(el);
                            const cursor = style.cursor;
                            const hasHoverEffect = el.className.includes('hover:');

                            elements.push({
                                type: 'clickable-card',
                                text: text,
                                priority: 5,
                                cursor: cursor,
                                hasHoverEffect: hasHoverEffect,
                                className: el.className,
                                tagName: el.tagName,
                                index: index
                            });
                        }
                    });
                });
                console.log(`Found ${elements.length - cardCount} clickable cards/divs`);

                // STRATEGY 6: Role-based clickables
                console.log("Strategy 6: Role-based elements");
                const roleCount = elements.length;
                document.querySelectorAll('[role="button"], [role="link"], [role="menuitem"]').forEach((el, index) => {
                    if (!isVisible(el)) return;

                    const text = getVisibleText(el);

                    if (text.length > 0 && text.length < 100) {
                        const key = getUniqueKey(el, text, index);
                        if (!seen.has(key)) {
                            seen.add(key);
                            elements.push({
                                type: 'role-element',
                                text: text,
                                role: el.getAttribute('role'),
                                priority: 6,
                                index: index
                            });
                        }
                    }
                });
                console.log(`Found ${elements.length - roleCount} role-based elements`);

                console.log(`Total: ${elements.length} clickable elements`);
                return elements;
            }
        """)

        # Sort by priority (lower number = higher priority)
        clickables.sort(key=lambda x: x.get('priority', 99))

        # Debug output
        self.debug_stats['total_detected'] = len(clickables)
        self.debug_stats['links'] = len([c for c in clickables if c['type'] == 'link'])
        self.debug_stats['buttons'] = len([c for c in clickables if c['type'] == 'button'])
        self.debug_stats['cards'] = len([c for c in clickables if c['type'] == 'clickable-card'])
        self.debug_stats['clickable_divs'] = len([c for c in clickables if c['type'] in ['onclick-element', 'role-element']])

        console.print(f"  • Links: {self.debug_stats['links']}")
        console.print(f"  • Router Links: {len([c for c in clickables if c['type'] == 'router-link'])}")
        console.print(f"  • Buttons: {self.debug_stats['buttons']}")
        console.print(f"  • Clickable Cards: {self.debug_stats['cards']} ⭐ KEY FOR NAVIGATION")
        console.print(f"  • Other Clickable: {self.debug_stats['clickable_divs']}")

        return clickables

    async def _discover_main_pages_with_debug(self, page, clickables):
        """Discover pages with detailed debugging"""
        main_pages = []
        initial_url = page.url

        console.print(f"\n[cyan]🖱️ Testing {len(clickables)} elements...[/cyan]")

        with Progress() as progress:
            task = progress.add_task("[cyan]Discovering pages...", total=len(clickables))

            for i, clickable in enumerate(clickables):
                try:
                    # Return to dashboard
                    if page.url != initial_url:
                        await page.goto(initial_url, wait_until='networkidle', timeout=10000)
                        await asyncio.sleep(1)

                    element_text = clickable.get('text', 'Unknown')[:40]
                    element_type = clickable.get('type', 'unknown')

                    if self.debug_mode:
                        console.print(f"  [{i+1}/{len(clickables)}] {element_type}: '{element_text}'...", end="")

                    # Try to click
                    clicked = await self._smart_click_with_debug(page, clickable)

                    if clicked:
                        try:
                            await page.wait_for_load_state('networkidle', timeout=5000)
                        except:
                            pass

                        await asyncio.sleep(1.5)
                        new_url = page.url

                        if new_url != initial_url and self._is_same_domain(new_url):
                            if new_url not in self.visited_urls:
                                self.visited_urls.add(new_url)

                                page_title = await page.title()
                                display_name = clickable.get('text', page_title or 'Untitled')

                                main_pages.append({
                                    'name': display_name.strip(),
                                    'url': new_url,
                                    'triggered_by': clickable.get('type'),
                                    'features': []
                                })

                                self.debug_stats['successful_navigations'] += 1

                                if self.debug_mode:
                                    console.print(f" ✅ NEW PAGE!")
                            else:
                                self.debug_stats['same_page_clicks'] += 1
                                if self.debug_mode:
                                    console.print(f" ⚠️ Already visited")
                        else:
                            self.debug_stats['same_page_clicks'] += 1
                            if self.debug_mode:
                                console.print(f" ➖ Same page")
                    else:
                        self.debug_stats['failed_clicks'] += 1
                        if self.debug_mode:
                            console.print(f" ❌ Click failed")

                except Exception as e:
                    self.debug_stats['failed_clicks'] += 1
                    if self.debug_mode:
                        console.print(f" ❌ Error: {str(e)[:30]}")

                progress.update(task, advance=1)

        return main_pages

    async def _smart_click_with_debug(self, page, clickable):
        """Try multiple click strategies"""
        clicked = False

        # Strategy 1: href for links
        if clickable.get('href'):
            try:
                await page.click(f"a[href='{clickable['href']}']", timeout=3000)
                clicked = True
                return clicked
            except:
                pass

        # Strategy 2: routerLink
        if clickable.get('routerLink'):
            try:
                await page.click(f"[routerlink='{clickable['routerLink']}']", timeout=3000)
                clicked = True
                return clicked
            except:
                pass

        # Strategy 3: Use saved selector
        if clickable.get('selector'):
            try:
                await page.click(clickable['selector'], timeout=3000)
                clicked = True
                return clicked
            except:
                pass

        # Strategy 4: Click by text content
        if not clicked and clickable.get('text'):
            text = clickable['text']

            # Try exact text match
            try:
                await page.click(f'text="{text}"', timeout=3000)
                clicked = True
                return clicked
            except:
                pass

            # Try partial text match
            try:
                await page.click(f"text={text[:30]}", timeout=3000)
                clicked = True
                return clicked
            except:
                pass

        # Strategy 5: For cards, try clicking by combining class and text
        if not clicked and clickable.get('type') == 'clickable-card':
            try:
                # Get the element by evaluating and clicking directly
                await page.evaluate(f"""
                    () => {{
                        const elements = Array.from(document.querySelectorAll('.cursor-pointer'));
                        const target = elements.find(el => el.innerText.trim().includes('{clickable['text'][:20]}'));
                        if (target) {{
                            target.click();
                            return true;
                        }}
                        return false;
                    }}
                """)
                clicked = True
                return clicked
            except:
                pass

        return clicked

    def _show_debug_stats(self):
        """Show debugging statistics"""
        console.print("\n[bold yellow]📊 DISCOVERY STATS[/bold yellow]")

        table = Table(title="Element Detection & Click Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="yellow")
        table.add_column("Percentage", style="green")

        total = self.debug_stats['total_detected']

        table.add_row("Total Detected", str(total), "100%")
        table.add_row("  ├─ Links", str(self.debug_stats['links']),
                     f"{self.debug_stats['links']/total*100:.1f}%" if total > 0 else "0%")
        table.add_row("  ├─ Clickable Cards", str(self.debug_stats['cards']),
                     f"{self.debug_stats['cards']/total*100:.1f}%" if total > 0 else "0%")
        table.add_row("  ├─ Buttons", str(self.debug_stats['buttons']),
                     f"{self.debug_stats['buttons']/total*100:.1f}%" if total > 0 else "0%")
        table.add_row("  └─ Other Clickable", str(self.debug_stats['clickable_divs']),
                     f"{self.debug_stats['clickable_divs']/total*100:.1f}%" if total > 0 else "0%")
        table.add_row("", "", "")
        table.add_row("Successful Navigations", str(self.debug_stats['successful_navigations']),
                     f"{self.debug_stats['successful_navigations']/total*100:.1f}%" if total > 0 else "0%")
        table.add_row("Same Page Clicks", str(self.debug_stats['same_page_clicks']),
                     f"{self.debug_stats['same_page_clicks']/total*100:.1f}%" if total > 0 else "0%")
        table.add_row("Failed Clicks", str(self.debug_stats['failed_clicks']),
                     f"{self.debug_stats['failed_clicks']/total*100:.1f}%" if total > 0 else "0%")

        console.print(table)

        # Success rate
        attempted = self.debug_stats['successful_navigations'] + self.debug_stats['same_page_clicks'] + self.debug_stats['failed_clicks']
        if attempted > 0:
            success_rate = self.debug_stats['successful_navigations'] / attempted * 100
            console.print(f"\n[bold]Navigation Success Rate: {success_rate:.1f}%[/bold]")

    def _build_content_index(self, main_pages):
        """Build content index for architect"""
        content = {}

        for page in main_pages:
            url = page['url']
            features_desc = []

            for feature in page.get('features', []):
                if feature['type'] == 'dropdown':
                    opts = feature.get('options', [])
                    if opts:
                        features_desc.append(f"{feature['label']}: {len(opts)} options")
                else:
                    features_desc.append(f"{feature['type']}: {feature['label']}")

            content[url] = {
                'title': page['name'],
                'features': features_desc,
                'feature_count': len(page.get('features', [])),
                'has_dropdowns': any(f['type'] == 'dropdown' for f in page.get('features', [])),
                'has_inputs': any(f['type'] == 'input' for f in page.get('features', [])),
                'has_buttons': any(f['type'] == 'button' for f in page.get('features', []))
            }

        return content

    async def _explore_cascading_dropdowns(self, page, dropdowns, page_data):
        """Explore cascading dropdowns"""
        console.print(f"  🔗 Checking for cascading dependencies...")

        data_dropdowns = []

        for i, dropdown in enumerate(dropdowns):
            options = await self._get_dropdown_options(page, dropdown)

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

            data_dropdowns.append({
                'index': i,
                'dropdown': dropdown,
                'has_options': len(options) > 0,
                'option_count': len(options),
                'initial_options': options
            })

        if not data_dropdowns:
            console.print(f"    ⚠️ No data dropdowns found")
            return

        enabled = [d for d in data_dropdowns if d['has_options']]
        disabled = [d for d in data_dropdowns if not d['has_options']]

        console.print(f"    ✅ {len(enabled)} data dropdowns enabled")
        console.print(f"    ⏸️ {len(disabled)} data dropdowns waiting (cascading)")

        if not disabled:
            for dd in data_dropdowns:
                dd['dropdown']['options'] = dd['initial_options']
                if dd['initial_options']:
                    console.print(f"    📋 {dd['dropdown']['label']}: {len(dd['initial_options'])} options")
            return

        console.print(f"  🔗 Cascading chain detected! Exploring sequentially...")

        for dd_index, dd_state in enumerate(data_dropdowns):
            dropdown = dd_state['dropdown']
            dropdown_index = dropdown['index']

            options = await self._get_dropdown_options(page, dropdown)

            if not options:
                console.print(f"    ⏸️ {dropdown['label']}: Waiting for previous selection")
                dropdown['options'] = []
                continue

            console.print(f"    📋 {dropdown['label']}: {len(options)} options")
            dropdown['options'] = options

            valid_option = None
            for opt in options:
                opt_val = str(opt['value']).lower().strip()
                opt_text = opt['text'].lower().strip()

                if not opt_val or opt_val in ['', 'select', 'choose', '--', '0', 'null']:
                    continue

                if any(kw in opt_text for kw in ['select', 'choose', 'pick', '--']):
                    continue

                valid_option = opt
                break

            if not valid_option and len(options) > 1:
                valid_option = options[1]
            elif not valid_option and options:
                valid_option = options[0]

            if valid_option:
                try:
                    console.print(f"      🔹 Selecting: '{valid_option['text'][:50]}' (value: {valid_option['value']})")

                    await page.evaluate("""
                        (args) => {
                            const selects = document.querySelectorAll('select');
                            const select = selects[args.index];

                            if (select) {
                                select.value = args.value;
                                ['input', 'change', 'blur'].forEach(eventType => {
                                    select.dispatchEvent(new Event(eventType, { bubbles: true }));
                                });
                            }
                        }
                    """, {'index': dropdown_index, 'value': valid_option['value']})

                    await asyncio.sleep(2)

                    next_dd_idx = dd_index + 1
                    if next_dd_idx < len(data_dropdowns):
                        next_dd = data_dropdowns[next_dd_idx]
                        next_dropdown = next_dd['dropdown']

                        next_options = await self._get_dropdown_options(page, next_dropdown)

                        if next_options:
                            console.print(f"      ✅ Next dropdown '{next_dropdown['label']}' unlocked: {len(next_options)} options")
                            next_dd['has_options'] = True
                            next_dropdown['options'] = next_options
                        else:
                            await asyncio.sleep(2)
                            next_options = await self._get_dropdown_options(page, next_dropdown)
                            if next_options:
                                console.print(f"      ✅ (Retry) Next dropdown now has {len(next_options)} options")
                                next_dd['has_options'] = True
                                next_dropdown['options'] = next_options

                except Exception as e:
                    console.print(f"      ❌ Selection failed: {str(e)[:80]}")

        console.print(f"  🔄 Final verification...")
        for dropdown in dropdowns:
            if dropdown.get('is_language'):
                continue

            final_options = await self._get_dropdown_options(page, dropdown)
            dropdown['options'] = final_options

            if final_options:
                console.print(f"    ✅ {dropdown['label']}: {len(final_options)} options")

    async def _get_dropdown_options(self, page, dropdown):
        """Get options from dropdown"""
        try:
            dropdown_index = dropdown.get('index', 0)

            dropdown_info = await page.evaluate("""
                (dropdownIdx) => {
                    const selects = document.querySelectorAll('select');
                    const select = selects[dropdownIdx];

                    if (!select) return null;

                    const info = {
                        disabled: select.disabled,
                        options: []
                    };

                    Array.from(select.options).forEach(opt => {
                        if (opt.value || opt.innerText.trim()) {
                            info.options.push({
                                value: opt.value,
                                text: opt.innerText.trim(),
                                disabled: opt.disabled
                            });
                        }
                    });

                    return info;
                }
            """, dropdown_index)

            if not dropdown_info or dropdown_info['disabled']:
                return []

            return [opt for opt in dropdown_info['options'] if not opt.get('disabled')]

        except Exception as e:
            return []

    async def _discover_page_features(self, page, page_data):
        """Discover all interactive features"""
        features = await page.evaluate("""
            () => {
                const features = [];

                document.querySelectorAll('select').forEach((select, i) => {
                    let label = 'Dropdown ' + (i+1);

                    if (select.previousElementSibling?.innerText) {
                        label = select.previousElementSibling.innerText.trim();
                    }

                    const parentLabel = select.closest('label');
                    if (parentLabel?.innerText) {
                        label = parentLabel.innerText.trim();
                    }

                    if (select.getAttribute('aria-label')) {
                        label = select.getAttribute('aria-label');
                    }

                    features.push({
                        type: 'dropdown',
                        label: label.substring(0, 50),
                        id: select.id,
                        name: select.name,
                        index: i,
                        disabled: select.disabled
                    });
                });

                document.querySelectorAll('input[type="text"], input[type="number"], input[type="email"], input[type="password"], textarea').forEach((input, i) => {
                    const label = input.previousElementSibling?.innerText ||
                                  input.placeholder ||
                                  input.getAttribute('aria-label') ||
                                  `Input ${i+1}`;

                    features.push({
                        type: 'input',
                        label: label.trim().substring(0, 50),
                        inputType: input.type,
                        placeholder: input.placeholder
                    });
                });

                document.querySelectorAll('button:not([disabled])').forEach((btn, i) => {
                    const text = btn.innerText.trim();
                    if (text && text.length < 50) {
                        features.push({
                            type: 'button',
                            label: text
                        });
                    }
                });

                document.querySelectorAll('input[type="file"]').forEach((input, i) => {
                    const label = input.previousElementSibling?.innerText || `File Upload ${i+1}`;
                    features.push({
                        type: 'file-upload',
                        label: label.trim(),
                        accept: input.accept
                    });
                });

                document.querySelectorAll('input[type="checkbox"]').forEach((input, i) => {
                    const label = input.nextElementSibling?.innerText ||
                                  input.previousElementSibling?.innerText ||
                                  `Checkbox ${i+1}`;
                    features.push({
                        type: 'checkbox',
                        label: label.trim().substring(0, 50)
                    });
                });

                document.querySelectorAll('input[type="radio"]').forEach((input, i) => {
                    const label = input.nextElementSibling?.innerText ||
                                  input.previousElementSibling?.innerText ||
                                  `Radio ${i+1}`;
                    features.push({
                        type: 'radio',
                        label: label.trim().substring(0, 50),
                        name: input.name
                    });
                });

                return features;
            }
        """)

        return features

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
                    icon = {
                        'input': '📝',
                        'button': '🔘',
                        'file-upload': '📎',
                        'checkbox': '☑️',
                        'radio': '🔘'
                    }.get(feature['type'], '•')
                    page_branch.add(f"{icon} {feature['label']}")

        console.print(tree)

    async def run(self) -> Dict:
        """Execute dynamic discovery"""
        discovery = await self.deep_discover()

        output_path = Path('output') / 'knowledge_base_improved.json'
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(discovery, f, indent=2)

        console.print(f"\n[bold green]✅ Improved KB saved: {output_path}[/bold green]")
        console.print(f"[bold]📊 Summary:[/bold]")
        console.print(f"  • Pages: {discovery['total_pages']}")
        console.print(f"  • Features: {discovery['total_features']}")
        console.print(f"  • Content entries: {len(discovery['content'])}")

        return discovery


# Compatibility alias
ExplorerAgent = ImprovedDynamicExplorer


async def main():
    with open('auth.json') as f:
        auth = json.load(f)

    explorer = ImprovedDynamicExplorer(
        "https://www.mnr-pst.com/dashboard",
        auth,
        debug_mode=True
    )
    kb = await explorer.run()


if __name__ == "__main__":
    asyncio.run(main())