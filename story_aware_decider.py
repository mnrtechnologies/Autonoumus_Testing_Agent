"""
story_aware_decider.py
──────────────────────
Drop-in replacement Decider class + _test_loop integration patch.

Changes vs original Decider:
  1. Accepts story_tracker reference
  2. Calls story_tracker.get_value_for_field(field_name) to look up
     generated story values before falling back to hardcoded defaults
  3. Generates a new test story whenever it sees unfilled form fields
     and no active story exists

Integration:
  Import and use StoryAwareDecider instead of Decider in SemanticTester.
  Pass story_tracker=self.story_tracker when constructing.
  Add 4 lines to _test_loop (marked with # ← ADD).
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, List

from openai import OpenAI
from test_story_engine import (
    TestStoryGenerator, TestStoryTracker, TestStory,
    StoryStatus, ReportGenerator
)


# Re-export so callers only need to import from this file
__all__ = ["StoryAwareDecider", "build_story_tester"]


class StoryAwareDecider:
    """
    Extends the original Decider with test-story awareness.

    Key differences:
    - Holds a reference to TestStoryTracker
    - Before deciding what value to fill, checks if the active story
      has a generated value for that field
    - Triggers story generation when form fields appear and no story is active
    """

    def __init__(
        self,
        openai_client: OpenAI,
        tester_ref=None,
        story_tracker: Optional[TestStoryTracker] = None
    ):
        self.openai        = openai_client
        self.tester        = tester_ref
        self.story_tracker = story_tracker
        self._pending_gen  = False   # guard against concurrent generation

    async def maybe_generate_story(
        self,
        page,
        elements: List[Dict],
        screenshot_b64: str,
        context_type: str,
        url: str
    ):
        """
        Called at the top of each OMDE iteration.
        Generates a new story if:
          - There are fillable fields on screen
          - No story is currently active
        """
        if not self.story_tracker:
            return
        if self.story_tracker.active_story:
            return
        if self._pending_gen:
            return

        fillable = [
            e for e in elements
            if e.get("element_type") in ("input", "textarea", "select", "custom-select")
               and not e.get("blocked", False)
        ]
        if not fillable:
            return   # No form fields → no story needed

        self._pending_gen = True
        try:
            gen   = self.story_tracker._generator
            if not gen:
                return
            story = await gen.generate(
                url           = url,
                elements      = fillable,
                screenshot_b64= screenshot_b64,
                context_type  = context_type
            )
            self.story_tracker.start_story(story)
        except Exception as e:
            print(f"  ⚠️  Story generation error: {e}")
        finally:
            self._pending_gen = False

    async def decide(
        self,
        screenshot_b64: str,
        context_frame,
        elements: List[Dict],
        last_action: Dict = None,
        new_elements: List[Dict] = None
    ) -> Dict:
        if not elements:
            return {"action": "done", "reasoning": "All elements tested"}

        prompt = self._build_prompt(context_frame.context_type, elements, last_action=last_action, new_elements=new_elements)

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
            raw      = response.choices[0].message.content
            # response = self.openai.messages.create(
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
            # raw = response.content[0].text
            print(f"  🧠 Decider raw response:\n{raw}\n")
            decision = json.loads(self._extract_json(raw))

            # ── Story value override ──────────────────────────────────────
            # If the LLM chose to fill/select a field, check if we have
            # a story-generated value for it — override the LLM's generic value
            action      = decision.get("action", "")
            target_name = decision.get("target_name", "")

            if action in ("fill", "select") and self.story_tracker:
                story_val = self.story_tracker.get_value_for_field(target_name)
                if story_val:
                    original = decision.get("test_value", "")
                    decision["test_value"] = story_val
                    if original != story_val:
                        print(f"  📖 Story value override: '{original}' → '{story_val}' "
                              f"for field '{target_name}'")

            return decision

        except Exception as e:
            print(f"  ⚠️  Decision failed: {e}")
            if elements:
                elem = elements[0]
                return {
                    "action":       "click",
                    "target_name":  elem.get("text", "element"),
                    "element_type": elem.get("tag", "button"),
                    "reasoning":    "Fallback"
                }
            return {"action": "wait"}

    def _build_prompt(self, context_type, elements: List[Dict], last_action: Dict = None, new_elements: List[Dict] = None) -> str:
        # Gather story context to inject into the prompt
        story_context = ""
        if self.story_tracker and self.story_tracker.active_story:
            s = self.story_tracker.active_story
            story_context = f"""
ACTIVE TEST STORY:
  ID      : {s.story_id}
  Context : {s.context_name}
  Persona : {s.user_persona}
  Scenario: {s.description}
  Generated field values (USE THESE — do not use generic placeholders):
{json.dumps(s.field_values, indent=4)}

"""
        input_elements = [
            e.get("formcontrolname") or e.get("text")
            for e in elements
            if e.get("element_type") in ("input", "textarea", "select", "custom-select")
        ]

        submit_elements = [
            e.get("text")
            for e in elements
            if e.get("element_type") == "button"
        ]

        hard_block = ""
        if input_elements and submit_elements:
            hard_block = f"""
    ⛔ YOU MUST FILL INPUTS FIRST — MANDATORY:
    These {len(input_elements)} fields are untested and MUST be filled before any button:
    {input_elements}
    Start with: "{input_elements[0]}"
    Do NOT click any of these buttons yet: {submit_elements}
    """

        # Recent history context
        recent_history = []
        if self.tester and hasattr(self.tester, "history"):
            recent_history = self.tester.history[-5:]

        delta_context = ""
        if last_action and new_elements:
            action = last_action.get('decision', {}).get('action', '')
            target = last_action.get('decision', {}).get('target_name', '')
            new_names = [e.get('formcontrolname') or e.get('text') for e in new_elements]
            if new_names:
                delta_context = f"""
        CAUSE AND EFFECT (CRITICAL):
        Last action performed : {action} → '{target}'
        Newly appeared elements: {new_names}

        ⚠️  MANDATORY RULE: These elements appeared DIRECTLY because of your last action.
        You MUST interact with these new elements FIRST before anything else on the page.
        DO NOT click Reset, Cari, or any pre-existing button.
        ONLY interact with: {new_names}

        """

        history_summary = ""
        if recent_history:
            history_summary = "\n\nRECENT ACTIONS (last 5 steps):\n"
            for h in recent_history:
                action  = h.get("decision", {}).get("action", "")
                target  = h.get("decision", {}).get("target_name", "")
                success = h.get("result", {}).get("success", False)
                status  = "✓" if success else "✗"
                history_summary += f"  {status} {action} → {target}\n"
            history_summary += "\nDO NOT repeat these exact actions unless element appears in UNTESTED list.\n"

        prompt = f"""{hard_block}
        {delta_context}
You are a QA engineer executing a user test story on a web application.
Choose ONE action from the UNTESTED ELEMENTS list below.

CONTEXT: {context_type.value}
{story_context}
{history_summary}

UNTESTED ELEMENTS ({len(elements)} remaining):

json
{json.dumps(elements[:15], indent=2)}

STRICT RULES — follow in this exact order

FIRST STEP OF EXPLORATION
Always start by clicking the three-dot menu (if present) before any other action.

USE STORY VALUES (IF PROVIDED)
If an ACTIVE TEST STORY is shown above, use its field values for test_value whenever applicable.

SCREENSHOT DATA RULE (for search/filter fields)

The screenshot shows the current state of the page.

If you see any table rows with data, you MUST use those exact values for the following search/filter fields:
fullName, emailId, phoneNumber, roleName, userStatus (or any visible search field).

→ Use the first row's actual data (e.g., if you see "Ramlaxman" in the table, use "Ramlaxman" for fullName).

If no table data is visible yet, leave these fields empty string ("") so the search returns all results.

NEVER invent names, emails, or phone numbers not visible on screen.

FILL / SELECT BEFORE TRIGGER (CRITICAL)

Fill/select ALL input, select, and custom-select fields before clicking any submit/save/search button.

If a submit button shows enabled:false, fill all required fields first – it will become enabled.

REALISTIC VALUES FOR NON-STORY FIELDS

For fields not covered by the story or screenshot rule, use sensible realistic values based on the field name/placeholder:

phone/HP/contact: 08123456789
email: test@example.com
name/nama: Test Name
address/alamat: 123 Test Street
description: This is a test description
code/kode: 001
number/angka: 100
postal/zip: 12345
swift: TESTBANK1
npwp/tax: 123456789012345
bankType/tipe rekening: Savings
accountType: Business

For SELECT / CUSTOM-SELECT fields:

Look at the screenshot for actual dropdown options first.

If not visible, use sensible defaults:

status → Active
category/kategori → General
gender/jenis kelamin → Male
accountType → Savings
isPrimaryAccount → Yes

For DATE / TIME fields:

ALWAYS include both date and time in format: DD/MM/YYYY, HH:MM

Example: "19/02/2026, 17:25"

Never use date-only format.

CORRECT ACTION PER ELEMENT TYPE

element_type "input" or "textarea" → action = "fill"
element_type "select" → action = "select"
element_type "custom-select" (Angular mat-select, ng-select, PrimeNG, Ant Design, Vue-select, React-select) → action = "select"
element_type "button" → action = "click"
element_type "link" → action = "click"
element_type "checkbox" or "radio" → action = "check"

SUBMIT BEFORE CANCEL

In forms/modals, always test submit/save buttons before cancel/close buttons.

Common submit text: Simpan, Save, Submit, Tambah, TAMBAH, Perbarui, Update.
Common cancel text: Batal, Cancel, Tutup, Close.

If no submit button exists, then click cancel.

CLEAR SEARCH FIELDS AFTER USE (CRITICAL)

After you have filled any search/filter field (e.g., fullName, emailId, phoneNumber, roleName, userStatus, or a generic "cari" field) and performed the intended search action (clicking "Cari"/"Filter" or letting the field filter the table), you MUST immediately clear that field by filling it with empty string ("") before moving on to test any other element.

Exception: If the next action is part of the same filter group (e.g., filling multiple search fields before clicking the search button), do not clear until after the search button is clicked.

This ensures subsequent actions (like clicking "Tambah", "Edit", etc.) are not executed within a filtered view.

EXACT TARGET NAMES

target_name = the exact text or formcontrolname from the list above.

No asterisks, no extra quotes.

SKIP DISABLED BUTTONS (except submit/save)

Skip buttons with enabled:false unless they are submit/save buttons that will become enabled after filling fields.

ONLY CHOOSE FROM UNTESTED ELEMENTS

Do not hallucinate elements. Pick strictly from the list provided.
"""


        context_type_val = context_type.value if hasattr(context_type, "value") else str(context_type)
        if context_type_val == "confirmation":
            prompt += "CONTEXT: Confirmation dialog — click confirm/yes.\n"
        elif context_type_val == "form":
            prompt += "CONTEXT: Form — fill ALL fields before clicking submit.\n"
        elif context_type_val == "modal":
            prompt += "CONTEXT: Modal — test all elements inside.\n"
        elif context_type_val == "table":
            prompt += "CONTEXT: Table — search inputs first, then row actions, then create.\n"
        else:
            prompt += "CONTEXT: Page — fill fields before clicking trigger buttons.\n"

        prompt += """
Return ONLY valid JSON, no markdown:
{
  "action": "click|fill|select|check",
  "target_name": "exact text or formcontrolname from the list",
  "element_type": "button|input|link|select|textarea|custom-select",
  "test_value": "value from story or realistic default",
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


# ═══════════════════════════════════════════════════════════════
#  FACTORY — wires everything together
# ═══════════════════════════════════════════════════════════════

def build_story_tester(openai_client, output_dir, session_id) -> tuple:
    """
    Returns (story_tracker, report_generator, generator) ready to use.

    Usage in SemanticTester.__init__:
        from story_aware_decider import build_story_tester, StoryAwareDecider
        self.story_tracker, self.report_gen, self.story_gen = \\
            build_story_tester(self.openai, self.output_dir, self.session_id)

    Then in run() / run_all():
        self.decider = StoryAwareDecider(
            self.openai,
            tester_ref=self,
            story_tracker=self.story_tracker
        )
    """
    from pathlib import Path
    out = Path(output_dir)

    generator = TestStoryGenerator(openai_client)
    tracker   = TestStoryTracker(out)
    tracker.set_generator(generator)
    report    = ReportGenerator(out, session_id)

    return tracker, report, generator