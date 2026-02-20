import asyncio
import json
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple, Set
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from enum import Enum

from playwright.async_api import async_playwright, Page, Locator, FrameLocator
from openai import OpenAI

class ContextType(Enum):
    PAGE = "page"
    MODAL = "modal"
    FORM = "form"
    DROPDOWN = "dropdown"
    TABLE = "table"
    CONFIRMATION = "confirmation"


@dataclass
class ContextFrame:
    context_type: ContextType
    description: str
    timestamp: str
    url: str
    dom_hash: str
    overlay_selector: Optional[str] = None
class Decider:

    def __init__(self, openai_client: OpenAI, tester_ref=None):
        self.openai = openai_client
        self.tester = tester_ref  # Reference to SemanticTester for history access

    async def decide(
        self,
        screenshot_b64: str,
        context_frame: ContextFrame,
        elements: List[Dict]
    ) -> Dict:
        if not elements:
            return {"action": "done", "reasoning": "All elements tested"}

        prompt = self._build_prompt(context_frame.context_type, elements)

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                    ]
                }],
                max_tokens=1500,
                temperature=0.2
            )
            raw = response.choices[0].message.content
            return json.loads(self._extract_json(raw))

        except Exception as e:
            print(f"  ⚠️  Decision failed: {e}")
            if elements:
                elem = elements[0]
                return {
                    "action": "click",
                    "target_name": elem.get('text', 'element'),
                    "element_type": elem.get('tag', 'button'),
                    "reasoning": "Fallback"
                }
            return {"action": "wait"}

    def _build_prompt(self, context_type: ContextType, elements: List[Dict]) -> str:
        
        # FIX 3: Add recent history context to prevent LLM hallucination
        recent_history = []
        if self.tester and hasattr(self.tester, 'history'):
            recent_history = self.tester.history[-5:]
        
        history_summary = ""
        if recent_history:
            history_summary = "\n\nRECENT ACTIONS (last 5 steps):\n"
            for h in recent_history:
                action = h.get('decision', {}).get('action', '')
                target = h.get('decision', {}).get('target_name', '')
                success = h.get('result', {}).get('success', False)
                status = "✓" if success else "✗"
                history_summary += f"  {status} {action} → {target}\n"
            history_summary += "\nDO NOT repeat these exact actions unless the element appears in UNTESTED list.\n"

        prompt = f"""You are a QA engineer creating a realistic user test story for a web form.
CONTEXT: {context_type.value}
{history_summary}

UNTESTED ELEMENTS ({len(elements)} remaining):
{json.dumps(elements[:15], indent=2)}

STRICT RULES — follow in this exact order:

**MOST IMPORTANT RULE — READ THE SCREENSHOT CAREFULLY:**
- The screenshot shows the CURRENT STATE of the page.
- If you can see ANY table rows with data, you MUST use those exact values.
- Look at every row in the table visible in the screenshot.
- Use the FIRST ROW's actual data for search fields:
  * If you see a name like "Ramlaxman" in the table → use "Ramlaxman" for fullName field.
  * If you see a role like "Super Admin" → use "Super Admin" for roleName field.  
  * If you see an email → use that exact email for emailId field.
- If NO table data is visible yet, leave search fields EMPTY string ("") so the search returns ALL results.
- NEVER invent names, emails, or phone numbers that aren't visible on screen.
- NEVER use "Ahmad Subekti", "Agus Santoso" or any made-up Indonesian names.
- FOR SEARCH/FILTER FIELDS (fullName, emailId, phoneNumber, roleName, userStatus):
  Use ONLY values visible in the screenshot table. If not visible, use "" (empty string).

1. **FIRST STEP OF EXPLORATION** — Always start by clicking the **three‑dot menu** (if present) before any other action.

2. **FILL / SELECT BEFORE TRIGGER (CRITICAL)**
   - If the list contains BOTH input/select fields AND a submit/save button (Cari, Search, Filter, Simpan, Tambah, Perbarui, Save, Submit, TAMBAH), fill/select ALL fields first before clicking the button.
   - Never click search/filter when input fields are still untested.
   - Never click submit/save when any input or select is still untested.
   - If submit button shows enabled:false, fill all fields first – it will become enabled.

3. **CORRECT ACTION PER ELEMENT TYPE (CRITICAL - Follow element_type from list above)**
   - element_type "input" or "textarea"  → action = "fill"
   - element_type "select"               → action = "select", test_value = a valid option
   - element_type "custom-select"        → action = "select", test_value = a valid option
     (custom-select = Angular mat-select, ng-select, PrimeNG, Ant Design, Vue-select, React-select — NEVER use "fill" for these, always "select")
   - element_type "button"               → action = "click"
   - element_type "link"                 → action = "click"
   - element_type "checkbox" or "radio"  → action = "check"

4. **REALISTIC VALUES** (use appropriate value based on field name/placeholder):
   For INPUT fields (action="fill"):
   - phone/HP/contact: 08123456789
   - email: test@example.com
   - name/nama: Test Name
   - address/alamat: 123 Test Street
   - description: This is a test description
   - code/kode: 001
   - number/angka: 100
   - postal/zip: 12345
   - swift: TESTBANK1
   - npwp/tax: 123456789012345
   - bankType/tipe rekening: Savings
   - accountType: Business
   - **FOR DATE/TIME FIELDS - CRITICAL:**
        - If field is named 'eventDate', 'date', 'datetime', or has calendar icon in screenshot
        - ALWAYS include BOTH date AND time in format: **DD/MM/YYYY, HH:MM**
        - Example: "19/02/2026, 17:25"
        - NEVER use date-only format like "16/02/2026"
   
   For SELECT/CUSTOM-SELECT fields (action="select"):
   - Look at screenshot for exact dropdown options first.
   - If not visible, use sensible defaults:
     * status → "Active"
     * category/kategori → "General"
     * gender/jenis kelamin → "Male"
     * accountType → "Savings"
     * isPrimaryAccount → "Yes"

5. **SUBMIT BEFORE CANCEL (CRITICAL IN FORMS)**
   - In forms/modals, ALWAYS test submit/save buttons BEFORE cancel/back buttons.
   - Common submit button text: Simpan, Save, Submit, Tambah, TAMBAH, Perbarui, Update.
   - Common cancel button text: Batal, Cancel, Tutup, Close.
   - If submit button is disabled (enabled:false), fill all fields first.
   - Only click cancel if there is NO submit button in the element list.

6. **EXACT TARGET NAMES**
   - target_name = EXACT text or formcontrolname from the list. No asterisks, no quotes.

7. **SKIP DISABLED BUTTONS** (unless they're submit buttons that will enable after filling fields)
   - Skip buttons with enabled:false UNLESS they are submit/save buttons.
   - Submit buttons often start disabled and enable after form is valid.

8. **CLEAR SEARCH FIELDS AFTER USE (CRITICAL)**
   - After you have **filled any search/filter field** (e.g., "cari", fullName, emailId, phoneNumber, roleName, userStatus) and **performed the intended search action** (e.g., clicking "Cari", "Filter", or simply letting the field filter the table), you **MUST immediately clear that field** before moving on to test any other element.
   - Clearing is done by filling the field with an **empty string (`""`)**.
   - This ensures that subsequent actions (clicking buttons like "Tambah", "Edit", etc.) are not executed within a filtered view and that the test story remains realistic and independent.
   - **Exception:** If the next action is part of the same filter group (e.g., you are filling multiple search fields in sequence before clicking the search button), do not clear until after the search button is clicked.
   - **Always reset the page state** after testing a search/filter interaction.

9. **ONLY choose from UNTESTED ELEMENTS list above** – do not hallucinate elements.
"""

        if context_type == ContextType.CONFIRMATION:
            prompt += "CURRENT CONTEXT: Confirmation — click confirm/yes unless data loss risk, then cancel.\n"
        elif context_type == ContextType.FORM:
            prompt += "CURRENT CONTEXT: Form — fill/select ALL fields before clicking submit. Required fields first.\n"
        elif context_type == ContextType.MODAL:
            prompt += "CURRENT CONTEXT: Modal — test all elements inside before closing.\n"
        elif context_type == ContextType.TABLE:
            prompt += "CURRENT CONTEXT: Table — fill search inputs first, click search, then row actions, then create.\n"
        else:
            prompt += "CURRENT CONTEXT: Page — fill/select fields before clicking their trigger buttons.\n"

        prompt += """
Return ONLY valid JSON, no markdown:
{
  "action": "click|fill|select|check",
  "target_name": "exact text or formcontrolname from the list",
  "element_type": "button|input|link|select|textarea|custom-select",
  "test_value": "value if filling/selecting, empty string for clicks",
  "reasoning": "one sentence"
}"""
        return prompt

    def _extract_json(self, text: str) -> str:
        if "```json" in text:
            start = text.find("```json") + 7
            end   = text.find("```", start)
            return text[start:end].strip()
        if "```" in text:
            start = text.find("```") + 3
            end   = text.find("```", start)
            return text[start:end].strip()
        return text.strip()
