
import asyncio
import json
import hashlib
import base64
from typing import Dict, List
from playwright.async_api import Page
from rich.console import Console
from openai import OpenAI
from .logger import CrawlerLogger
import anthropic
from openai import OpenAI
import base64


console = Console()

class GPTVisionAnalyzer:
    def __init__(self, openai_client: OpenAI, logger: CrawlerLogger):
        self.client = openai_client
        self.analysis_cache = {}
        self.logger = logger
    
    async def analyze_expanded_container(self, page: Page, url: str, container_text: str) -> Dict:
        """
        Analyze an expanded container with scrolling to capture ALL children.
        Takes multiple screenshots at different scroll positions.
        """
        console.print(f"[cyan]📸 VISION: Analyzing expanded container '{container_text}' with scroll...[/cyan]")
        self.logger.log_info(f"Starting expanded container analysis for: {container_text}")

        screenshots = []
        
        try:
            # Find the expanded menu container - ADJUST THIS SELECTOR FOR YOUR APP!
            menu_selector = '.fuse-vertical-navigation-item-children'
            
            # Check if element exists and is scrollable
            is_scrollable = await page.evaluate(f'''
                (() => {{
                    const el = document.querySelector('{menu_selector}');
                    if (!el) return false;
                    return el.scrollHeight > el.clientHeight;
                }})()
            ''')
            
            if is_scrollable:
                console.print("[yellow]   📜 Menu is scrollable - taking multiple screenshots[/yellow]")
                
                # Scroll to BOTTOM and capture
                await page.evaluate(f'''
                    document.querySelector('{menu_selector}').scrollTop = 
                    document.querySelector('{menu_selector}').scrollHeight
                ''')
                await page.wait_for_timeout(500)
                screenshot_bottom = await page.screenshot(full_page=False, type='png')
                screenshots.append(screenshot_bottom)
                
                # Scroll to TOP and capture
                await page.evaluate(f'''
                    document.querySelector('{menu_selector}').scrollTop = 0
                ''')
                await page.wait_for_timeout(500)
                screenshot_top = await page.screenshot(full_page=False, type='png')
                screenshots.append(screenshot_top)
                
            else:
                console.print("[yellow]   📄 Menu not scrollable - taking single screenshot[/yellow]")
                screenshot = await page.screenshot(full_page=False, type='png')
                screenshots.append(screenshot)
                
        except Exception as e:
            console.print(f"[red]   ⚠️ Scroll failed, using single screenshot: {e}[/red]")
            screenshot = await page.screenshot(full_page=False, type='png')
            screenshots = [screenshot]

        # Now send ALL screenshots to vision model
        # Convert screenshots to base64
        image_urls = []
        for screenshot_bytes in screenshots:
            screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode('utf-8')
            image_urls.append(f"data:image/png;base64,{screenshot_b64}")

        prompt = f"""You are analyzing an EXPANDED menu container titled "{container_text}".

    **IMPORTANT:** You are receiving MULTIPLE screenshots of the same menu at different scroll positions.
    Your job is to identify ALL unique child items across ALL screenshots.

    Look for:
    - Menu items (links)
    - Sub-sections
    - Buttons

    Return ONLY the child items you see, in this format:

    {{
    "page_type": "expanded_menu",
    "containers": [],
    "features": [
        {{
        "text": "EXACT text from screen",
        "type": "link|button",
        "location": "sidebar_child",
        "test_priority": 8,
        "expected_behavior": "Navigate to sub-page"
        }}
    ],
    "discovery_strategy": {{
        "recommended_order": [],
        "reasoning": "All items discovered from expanded menu"
    }}
    }}

    **CRITICAL:** Copy text EXACTLY character-by-character. Do NOT translate or paraphrase."""

        try:
            # Build message content with all screenshots
            message_content = [{"type": "text", "text": prompt}]
            for img_url in image_urls:
                message_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url}
                })

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": message_content
                }],
                max_tokens=4000
            )
#             response = self.client.messages.create(
#     model="claude-sonnet-4-20250514",
#     max_tokens=1500,
#     messages=[{
#         "role": "user",
#         "content": [
#             {"type": "image", "source": {
#                 "type": "base64",
#                 "media_type": "image/png",
#                 "data": screenshot_b64
#             }},
#             {"type": "text", "text": prompt}
#         ]
#     }]
# )
            vision_text = response.choices[0].message.content

            # vision_text = response.content[0].text
            
            console.print("\n" + "="*80)
            console.print(f"EXPANDED CONTAINER VISION RESPONSE ({container_text}):")
            console.print(vision_text)
            console.print("="*80 + "\n")

            if vision_text.startswith('```'):
                vision_text = vision_text.split('\n', 1)[1].rsplit('\n', 1)[0]
                if vision_text.startswith('json'):
                    vision_text = vision_text[4:].strip()

            analysis = json.loads(vision_text)
            
            console.print(f"[green]   ✅ Found {len(analysis.get('features', []))} children in '{container_text}'[/green]")
            
            return analysis

        except Exception as e:
            console.print(f"[red]   ❌ Expanded container analysis failed: {e}[/red]")
            self.logger.log_error("expanded_container_analysis_failed", str(e))
            return {
                "page_type": "expanded_menu",
                "containers": [],
                "features": [],
                "discovery_strategy": {"recommended_order": [], "reasoning": "Analysis failed"}
            }
    async def analyze_page(self, page: Page, url: str) -> Dict:
        console.print("[cyan]📸 VISION: Taking screenshot and analyzing with GPT-4...[/cyan]")
        self.logger.log_info(f"Starting vision analysis for: {url}")

        screenshot_bytes = await page.screenshot(full_page=False, type='png')
        screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode('utf-8')

        screenshot_hash = hashlib.md5(screenshot_bytes).hexdigest()[:8]
        if screenshot_hash in self.analysis_cache:
            console.print("[yellow]   Using cached Vision analysis[/yellow]")
            self.logger.log_info("Using cached vision analysis")
            return self.analysis_cache[screenshot_hash]

        prompt = """You are analyzing a web application to help an automated testing agent explore it systematically.

**YOUR MISSION:**
Identify ALL interactive elements and classify them into two categories:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 CATEGORY 1: CONTAINERS (Things that HIDE other things)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A CONTAINER is any UI element that:
- Has a visual expansion indicator (>, ▶, ▼, ›, arrow icon, chevron)
- Shows/hides child elements when clicked
- Contains nested menu items that aren't currently visible

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 CATEGORY 2: FEATURES (Things that DO actions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A FEATURE is any UI element that:
- Performs a direct action (Save, Delete, Export, Download)
- Navigates to a page (Links that go somewhere)
- Accepts user input (Search boxes, form fields)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 CRITICAL RULE: CHARACTER-PERFECT TRANSCRIPTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**WHY THIS MATTERS:**
The testing agent will search the DOM using EXACT text matching. Even one wrong 
character will cause the element detection to fail completely.

**TRANSCRIPTION RULES:**
1. Copy EVERY character exactly as it appears (including spaces, punctuation)
2. Preserve capitalization EXACTLY ("Sedekah" ≠ "sedekah")
3. Do NOT fix typos you see on screen - copy them as-is
4. Do NOT translate to English (keep original language)
5. Do NOT paraphrase or use similar words
6. Include diacritics/accents if present (é, ñ, etc.)

**EXAMPLES:**

✅ CORRECT TRANSCRIPTION:
  Screen shows: "Lihat semua"
  You write:    "Lihat semua"

❌ WRONG - Similar meaning but different text:
  Screen shows: "Lihat semua"
  You write:    "Lihat selengkapnya"  ← Different words!

❌ WRONG - Typo introduced:
  Screen shows: "Sedekah Sekarang"
  You write:    "Sedehak Sekarang"  ← Missing 'a'!

❌ WRONG - Translated:
  Screen shows: "Sedekah Sekarang"
  You write:    "Donate Now"  ← Wrong language!

❌ WRONG - Capitalization changed:
  Screen shows: "Buat Acara"
  You write:    "buat acara"  ← Wrong capitalization!

**DOUBLE-CHECK EACH TEXT FIELD BEFORE SUBMITTING YOUR RESPONSE**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return JSON in this EXACT format:

{
  "page_type": "dashboard|list|form|settings",
  "layout": { "has_sidebar": true|false, "has_header": true|false },
  "containers": [
    {
      "text": "CHARACTER-PERFECT copy from screen - verify each letter!",
      "type": "expandable_menu",
      "state": "collapsed|expanded",
      "location": "sidebar|header|main",
      "expected_children": [],
      "discovery_priority": 9,
      "expansion_indicator": "describe what you see"
    }
  ],
  "features": [
    {
      "text": "CHARACTER-PERFECT copy from screen - verify each letter!",
      "type": "button|link|form_field",
      "location": "sidebar|header|main",
      "test_priority": 1,
      "expected_behavior": "what happens when clicked"
    }
  ],
  "discovery_strategy": {
    "recommended_order": [],
    "reasoning": "why this order makes sense"
  }
}

**BEFORE RETURNING YOUR RESPONSE:**
1. Re-read each "text" field
2. Compare it character-by-character with what you see on screen
3. Verify capitalization matches exactly
4. Confirm no translation occurred

Return valid JSON only."""

        try:
#             response = self.client.messages.create(
#     model="claude-sonnet-4-20250514",
#     max_tokens=1500,
#     messages=[{
#         "role": "user",
#         "content": [
#             {"type": "image", "source": {
#                 "type": "base64",
#                 "media_type": "image/png",
#                 "data": screenshot_b64
#             }},
#             {"type": "text", "text": prompt}
#         ]
#     }]
# )

#             vision_text = response.content[0].text

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}"
                                }
                            }
                        ]
                    }
                ]
            )

            vision_text = response.choices[0].message.content


            console.print("\n" + "="*80)
            console.print("RAW GPT-4 VISION RESPONSE:")
            console.print(vision_text)
            console.print("="*80 + "\n")
            
            self.logger.log_info("Raw GPT-4 Vision Response:")
            self.logger.log_info(vision_text)

            if vision_text.startswith('```'):
                vision_text = vision_text.split('\n', 1)[1].rsplit('\n', 1)[0]
                if vision_text.startswith('json'):
                    vision_text = vision_text[4:].strip()

            analysis = json.loads(vision_text)
            self.analysis_cache[screenshot_hash] = analysis
            
            # Log the analysis
            self.logger.log_vision_analysis(url, analysis)

            console.print(f"[green]   ✅ Vision analysis complete[/green]")
            console.print(f"[yellow]   Page Type: {analysis.get('page_type', 'unknown')}[/yellow]")
            console.print(f"[yellow]   Containers found: {len(analysis.get('containers', []))}[/yellow]")
            console.print(f"[yellow]   Features found: {len(analysis.get('features', []))}[/yellow]")

            return analysis

        except Exception as e:
            console.print(f"[red]   ❌ Vision analysis failed: {e}[/red]")
            self.logger.log_error("vision_analysis_failed", str(e), {"url": url})
            import traceback
            console.print(f"[red]   {traceback.format_exc()}[/red]")
            return {
                "page_type": "unknown",
                "layout": {},
                "containers": [],
                "features": [],
                "discovery_strategy": {"recommended_order": [], "reasoning": "Vision failed"}
            }