import asyncio
import json
import base64
import hashlib
import logging
import os
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from urllib.parse import urlparse
from dotenv import load_dotenv
import os

load_dotenv()

from playwright.async_api import async_playwright, Page, Locator, BrowserContext
from openai import OpenAI

# Windows Terminal UTF-8 Fix
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ═══════════════════════════════════════════════════════════════
#  CONFIG & LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("hybrid_explorer.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("HybridExplorer")

# ═══════════════════════════════════════════════════════════════
#  SYSTEM 2: HYBRID MEMORY
# ═══════════════════════════════════════════════════════════════
class HybridMemory:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.db_path = Path(f"discovery_graph_{session_id}.json")
        self.graph = {"states": {}, "stack": []}
        self.load()

    def load(self):
        if self.db_path.exists():
            with open(self.db_path, 'r') as f:
                self.graph = json.load(f)

    def save(self):
        with open(self.db_path, 'w') as f:
            json.dump(self.graph, f, indent=2)

    def get_state_hash(self, url: str, elements: List[Dict]) -> str:
        # Include visibility count in hash to detect modals opening
        structure = "|".join([f"{e['tag']}:{e['text']}" for e in elements[:40]])
        return hashlib.md5(f"{url}{structure}".encode()).hexdigest()

    def register_state(self, state_hash: str, url: str, elements: List[Dict]):
        if state_hash not in self.graph["states"]:
            logger.info(f"✨ DISCOVERY: New UI State {state_hash[:8]} found at {url}")
            self.graph["states"][state_hash] = {
                "url": url,
                "elements": {str(i): {"data": e, "visited": False, "no_op_count": 0} for i, e in enumerate(elements)},
                "fully_explored": False
            }
            self.save()

    def mark_visited(self, state_hash: str, element_idx: str):
        if state_hash in self.graph["states"]:
            self.graph["states"][state_hash]["elements"][str(element_idx)]["visited"] = True
            elems = self.graph["states"][state_hash]["elements"]
            if all(e["visited"] or e["no_op_count"] >= 3 for e in elems.values()):
                self.graph["states"][state_hash]["fully_explored"] = True
            self.save()

# ═══════════════════════════════════════════════════════════════
#  SYSTEM 1 & 3: BRAIN (Strict QA Mode)
# ═══════════════════════════════════════════════════════════════
class HybridBrain:
    def __init__(self, client: OpenAI):
        self.client = client

    async def plan_action(self, state_hash: str, memory: HybridMemory, ss_b64: str) -> Dict:
        state = memory.graph["states"][state_hash]
        unvisited = {i: v["data"] for i, v in state["elements"].items() 
                     if not v["visited"] and v.get("no_op_count", 0) < 3}

        if not unvisited:
            return {"action": "backtrack", "reason": "No actionable elements left."}

        prompt = f"""You are a Professional QA Automation Engineer.
CONTEXT URL: {state['url']}
UNVISITED ELEMENTS: {json.dumps(list(unvisited.values())[:30])}

RULES FOR REAL DATA:
1. When filling names, use real names (e.g., 'Mohan Kumar', 'Siti Aminah').
2. When filling addresses, use real cities/locations (e.g., 'Hyderabad', 'Mumbai', 'Jakarta').
3. Emails must be valid (e.g., 'mohan.qa@example.com').
4. Phone numbers must look real (e.g., '+91 9876543210').

RULES FOR EXHAUSTIVE CRAWLING:
1. You MUST interact with micro-elements: toggles, radio buttons, update icons, and delete buttons.
2. If you see an 'Edit' or 'Update' icon, click it to see the form.
3. Finish the entire Form/Modal context before backtracking.

Return JSON:
{{
  "element_index": "Integer (e.g. 5)",
  "action": "click|fill|select",
  "value": "Realistic data based on the field label",
  "reasoning": "Explain which specific feature you are testing"
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": [{"type": "text", "text": prompt},
                           {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{ss_b64}"}}]}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"🧠 Brain Error: {e}")
            return {"action": "backtrack"}

# ═══════════════════════════════════════════════════════════════
#  SYSTEM 4: ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════
class HybridOrchestrator:
    def __init__(self, api_key: str, auth_file: str = "auth.json"):
        self.client = OpenAI(api_key=api_key)
        self.memory = HybridMemory(datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.brain = HybridBrain(self.client)
        self.auth_file = Path(auth_file)

    async def _save_auth_state(self, page: Page, context: BrowserContext):
        cookies = await context.cookies()
        storage = await page.evaluate("""() => ({
            local: JSON.parse(JSON.stringify(localStorage)),
            session: JSON.parse(JSON.stringify(sessionStorage))
        })""")
        with open(self.auth_file, 'w') as f:
            json.dump({"cookies": cookies, "local_storage": storage['local'], 
                       "session_storage": storage['session']}, f, indent=2)
        logger.info("✅ Auth saved.")

    async def _inject_auth(self, page: Page, context: BrowserContext, target_url: str):
        if self.auth_file.exists():
            with open(self.auth_file, 'r') as f:
                auth = json.load(f)
            parsed = urlparse(target_url)
            homepage = f"{parsed.scheme}://{parsed.netloc}/"
            await page.goto(homepage)
            if auth.get("cookies"): await context.add_cookies(auth["cookies"])
            for s_type in ["local_storage", "session_storage"]:
                js = "localStorage" if s_type == "local_storage" else "sessionStorage"
                for k, v in auth.get(s_type, {}).items():
                    val = v if isinstance(v, str) else json.dumps(v)
                    await page.evaluate(f"window.{js}.setItem('{k}', `{val}`)")
            await page.goto(target_url, wait_until="networkidle")

        if "sign-in" in page.url or "login" in page.url:
            print("\n" + "="*50 + "\nMANUAL LOGIN REQUIRED\n" + "="*50)
            input("Log in manually, then press ENTER...")
            await self._save_auth_state(page, context)

    async def _get_elements(self, page: Page):
        """Micro-Interaction Observer: Finds SVG buttons, toggles, and radios."""
        return await page.evaluate("""() => {
            const modalSelectors = ['[role="dialog"]', '.modal', '.popup', '.chakra-modal__content'];
            let root = document.body;
            for (const s of modalSelectors) {
                const m = document.querySelector(s);
                if (m && window.getComputedStyle(m).display !== 'none') { root = m; break; }
            }

            // Expanded selector to catch small icons, toggles, and svgs inside buttons
            const selectors = 'button, a, input, select, [role="button"], [role="checkbox"], [role="radio"], .toggle, .switch, svg';
            
            return Array.from(root.querySelectorAll(selectors))
                .filter(el => {
                    const r = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    // Filter out non-visible and tiny non-clickable elements
                    return r.width > 2 && r.height > 2 && style.visibility !== 'hidden' && style.display !== 'none';
                })
                .map((el, i) => {
                    // Try to get text, but for SVGs/Icons get aria-label or parent text
                    let text = el.innerText || el.placeholder || el.value || el.ariaLabel || "";
                    if (!text && el.tagName === 'SVG') text = el.parentElement.ariaLabel || "icon-button";
                    
                    return {
                        index: i,
                        tag: el.tagName.toLowerCase(),
                        text: text.trim().slice(0, 40) || "unlabeled-element",
                        x: el.getBoundingClientRect().x,
                        y: el.getBoundingClientRect().y
                    };
                });
        }""")

    async def run(self, start_url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1280, 'height': 800})
            page = await context.new_page()
            await self._inject_auth(page, context, start_url)

            for step in range(150): # Increased steps for exhaustive exploration
                logger.info(f"--- ⏩ STEP {step} ---")
                
                # Auto-scroll to trigger lazy loads
                await page.evaluate("window.scrollBy(0, 400)")
                await asyncio.sleep(1)

                elements = await self._get_elements(page)
                curr_hash = self.memory.get_state_hash(page.url, elements)
                self.memory.register_state(curr_hash, page.url, elements)

                ss = await self._get_ss(page)
                plan = await self.brain.plan_action(curr_hash, self.memory, ss)
                logger.info(f"💡 AI LOGIC: {plan.get('reasoning')} | ACTION: {plan.get('action')} on '{plan.get('element_index')}'")

                if plan["action"] == "backtrack":
                    if self.memory.graph["stack"]:
                        prev = self.memory.graph["stack"].pop()
                        await page.go_back()
                        continue
                    break

                try:
                    idx_str = str(plan.get("element_index"))
                    target = elements[int(idx_str)]
                    
                    await self._do_action(page, target, plan)
                    
                    await asyncio.sleep(2) 
                    new_elements = await self._get_elements(page)
                    new_hash = self.memory.get_state_hash(page.url, new_elements)

                    if curr_hash == new_hash:
                        self.memory.graph["states"][curr_hash]["elements"][idx_str]["no_op_count"] += 1
                    else:
                        self.memory.mark_visited(curr_hash, idx_str)
                        self.memory.graph["stack"].append(curr_hash)
                        
                except Exception as e:
                    logger.error(f"⚠️ Step Failed: {e}")
                    continue

            await browser.close()

    async def _do_action(self, page: Page, target: Dict, plan: Dict):
        center_x, center_y = target['x'] + 5, target['y'] + 5
        await page.mouse.click(center_x, center_y)
        if plan["action"] == "fill":
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(str(plan["value"]), delay=60)
            await page.keyboard.press("Enter")
        elif plan["action"] == "select":
            await page.keyboard.type(str(plan["value"]))
            await page.keyboard.press("Enter")

    async def _get_ss(self, page: Page):
        ss = await page.screenshot(type="jpeg", quality=50)
        return base64.b64encode(ss).decode()

if __name__ == "__main__":
    API_KEY = os.getenv("OPENAI_API_KEY")
    TARGET = "https://staging.isalaam.me/dashboard"
    explorer = HybridOrchestrator(api_key=API_KEY)
    asyncio.run(explorer.run(TARGET))