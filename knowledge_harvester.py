"""
knowledge_harvester.py
──────────────────────
Phase 2: Exploration & Story Generation

Silently accumulates everything the explorer discovers during the test loop.
At the end, generate_stories() sends the full history + all harvested data
to OpenAI in one call and gets back rich, realistic test stories.

FIXES IN THIS VERSION:
1. ✅ Stories are complete end-to-end workflows, not single-action splits
2. ✅ expected_outcome is specific and validates real data, not generic text
3. ✅ Each story has a validation_check field so Phase 3 knows what to assert
4. ✅ History-driven — no hardcoded keyword guessing
5. ✅ No duplicate reporting — write_excel called exactly once
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from openai import OpenAI
from test_story_engine import TestStory, StoryStatus, ExcelReportGenerator


class KnowledgeHarvester:

    def __init__(self, output_dir: Path, session_id: str, openai_client: OpenAI):
        self.output_dir  = output_dir
        self.session_id  = session_id
        self.openai      = openai_client

        self.page_url:          str        = ""
        self.dropdown_options:  Dict       = {}   # fieldName → [opt1, opt2...]
        self.forms_discovered:  Dict       = {}   # formName  → [field dicts]
        self.screenshots:       List[str]  = []   # b64, max 5
        self.raw_elements:      List[Dict] = []   # every unique element seen
        self.execution_history: List[Dict] = []   # full step-by-step history

        self._story_counter = 0

    # ═══════════════════════════════════════════════════════════
    #  HARVEST METHODS — called from _test_loop
    # ═══════════════════════════════════════════════════════════

    def harvest_page(self, url: str, screenshot_b64: str, elements_data: Dict):
        """Called every iteration. Stores URL, screenshot, unique elements."""
        self.page_url = url

        if screenshot_b64 and len(self.screenshots) < 5:
            self.screenshots.append(screenshot_b64)

        active = elements_data.get("active_elements", [])
        for elem in active:
            key = elem.get("formcontrolname") or elem.get("text", "")
            already = any(
                (e.get("formcontrolname") or e.get("text", "")) == key
                for e in self.raw_elements
            )
            if not already and key:
                self.raw_elements.append(elem)

    def harvest_dropdown(self, field_name: str, options: List[str]):
        """Called after every dropdown execution with all_options from executor."""
        if not field_name or not options:
            return
        clean = [o for o in options if o and o.strip()]
        if clean:
            self.dropdown_options[field_name] = clean
            print(f"  📦 Harvested dropdown '{field_name}': {clean}")

    def harvest_form(self, overlay_type: str, fields: List[Dict], screenshot_b64: str):
        """Called when a modal opens — stores scoped_elements (real form fields)."""
        if not fields:
            return
        form_name = f"{overlay_type or 'modal'}_{len(self.forms_discovered) + 1}"
        field_summaries = []
        for f in fields:
            field_summaries.append({
                "name":       f.get("formcontrolname") or f.get("text", ""),
                "type":       f.get("element_type", ""),
                "input_type": f.get("type", ""),
                "required":   f.get("required", False),
            })
        self.forms_discovered[form_name] = field_summaries
        if screenshot_b64 and len(self.screenshots) < 5:
            self.screenshots.append(screenshot_b64)
        print(f"  📦 Harvested form '{form_name}': {[f['name'] for f in field_summaries]}")

    def harvest_actions(self, elements: List[Dict]):
        """No-op — history replaces hardcoded keyword detection."""
        pass

    def harvest_history(self, history: List[Dict]):
        """Receives full self.history from SemanticTester at end of session."""
        self.execution_history = []
        for h in history:
            decision = h.get("decision", {})
            result   = h.get("result", {})
            self.execution_history.append({
                "step":    h.get("step"),
                "action":  decision.get("action"),
                "target":  decision.get("target_name"),
                "value":   decision.get("test_value", ""),
                "success": result.get("success", False),
                "error":   result.get("error"),
                "options": h.get("all_options"),
            })
        print(f"  📦 History loaded: {len(self.execution_history)} steps")

    # ═══════════════════════════════════════════════════════════
    #  STORY GENERATION — called once at end of session
    # ═══════════════════════════════════════════════════════════

    async def generate_stories(self, history: List[Dict] = None) -> List[TestStory]:
        """
        Main entry point. Pass self.history from SemanticTester.
        Sends everything to OpenAI, gets back stories, writes Excel once.
        """
        if history:
            self.harvest_history(history)

        print(f"\n{'='*70}")
        print(f"🧠 GENERATING STORIES FROM HARVESTED KNOWLEDGE")
        print(f"{'='*70}")
        print(f"  Execution steps:  {len(self.execution_history)}")
        print(f"  Dropdown fields:  {len(self.dropdown_options)}")
        print(f"  Forms discovered: {len(self.forms_discovered)}")
        print(f"  Screenshots:      {len(self.screenshots)}")

        if not self.execution_history and not self.forms_discovered:
            print("  ⚠️  Nothing harvested — skipping")
            return []

        prompt  = self._build_generation_prompt()
        content = [{"type": "text", "text": prompt}]
        for ss in self.screenshots[:3]:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{ss}"}
            })

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": content}],
                max_tokens=4000,
                temperature=0.3   # lower temp = more consistent structured output
            )
            raw  = response.choices[0].message.content
            print(f"\n🤖 Response preview:\n{raw[:600]}...\n")
            data = json.loads(self._extract_json(raw))
            stories = self._build_story_objects(data.get("stories", []))

            # Write Excel and JSON exactly once
            self._save_knowledge_json(stories)
            self._write_excel(stories)
            return stories

        except Exception as e:
            print(f"  ❌ Story generation failed: {e}")
            import traceback
            traceback.print_exc()
            return []

    # ═══════════════════════════════════════════════════════════
    #  PROMPT BUILDER
    # ═══════════════════════════════════════════════════════════

    def _build_generation_prompt(self) -> str:
        history_text  = json.dumps(self.execution_history, indent=2, ensure_ascii=False)
        forms_text    = json.dumps(self.forms_discovered,  indent=2, ensure_ascii=False)
        dropdown_text = json.dumps(
            {k: v[:10] for k, v in self.dropdown_options.items()},
            indent=2, ensure_ascii=False
        )
        elements_text = self._summarise_elements()

        return f"""You are a senior QA engineer writing a professional test plan.

Below is the COMPLETE automated exploration of a web page.
Every action taken, every form field seen, every dropdown option discovered is listed.
Use this to generate complete end-to-end user test stories.

PAGE URL: {self.page_url}

STEP-BY-STEP EXPLORATION HISTORY:
{history_text}

FORM FIELDS DISCOVERED (inside modals/dialogs):
{forms_text}

DROPDOWN OPTIONS (real values discovered):
{dropdown_text}

ALL INTERACTIVE ELEMENTS SEEN:
{elements_text}

Screenshots attached for visual context.

═══════════════════════════════════════════════
YOUR TASK: Generate 4–6 test stories.
═══════════════════════════════════════════════

CRITICAL RULE 1 — COMPLETE WORKFLOWS ONLY:
Each story must be a complete end-to-end user workflow, NOT a single button click.

BAD examples (too small, will be rejected):
  ✗ "User clicks Export button" — this is one step, not a story
  ✗ "User clicks Reset" — this is one step, not a story
  ✗ "User opens menu" — this is one step, not a story

GOOD examples (complete workflows):
  ✓ "Admin filters users by role and date range, then exports filtered results"
     Steps: fill fullName → select roleName → set date range → click Cari → verify results → click Ekspor
  ✓ "Admin edits a user record and saves changes"
     Steps: click more_vert → click Sunting → fill fields → click Perbarui → verify toast message
  ✓ "Admin searches for inactive users and resets filters"
     Steps: select userStatus=Inactive → click Cari → verify results shown → click Atur Ulang → verify filters cleared

Group related single-button actions into one story.
Reset, Export, Search should be combined into ONE workflow story, not separate stories.

CRITICAL RULE 2 — SPECIFIC VALIDATION IN EVERY STORY:
Every story MUST have a specific, testable expected_outcome and validation_check.

BAD expected_outcome (too generic, untestable):
  ✗ "Form submits successfully"
  ✗ "Page loads correctly"
  ✗ "Action completes"

GOOD expected_outcome (specific, testable):
  ✓ "Table refreshes and shows only users with role 'Super Admin' registered after 28/08/2023"
  ✓ "Success toast message appears: 'Data berhasil diperbarui'"
  ✓ "Exported file downloads with .xlsx extension containing filtered user data"
  ✓ "All filter fields reset to empty/default state and table shows all 1415 users"

validation_check must describe EXACTLY what to assert after the story completes:
  ✓ "Assert: table row count changes after search. Assert: roleName filter shows 'Super Admin'"
  ✓ "Assert: toast message contains 'berhasil'. Assert: modal closes after save"
  ✓ "Assert: download dialog appears OR file appears in downloads folder"

CRITICAL RULE 3 — USE REAL VALUES:
  - Use actual dropdown options discovered: {list(self.dropdown_options.keys())}
  - Use real values from history (values that were actually typed/selected)
  - Domain is Islamic organization management system (Indonesian language UI)
  - User personas: Super Admin, Ministry Admin, Mosque Admin

Return ONLY valid JSON, no markdown:
{{
  "stories": [
    {{
      "story_id": "STORY-001",
      "context_name": "descriptive workflow name e.g. Filter and Export Users",
      "user_persona": "e.g. Super Admin filtering registered users",
      "description": "2-3 sentences describing the complete workflow and why",
      "field_values": {{
        "fieldName": "exact real value used"
      }},
      "expected_outcome": "specific observable result after story completes",
      "validation_check": "exact assertions to make: what element, what text, what state",
      "priority": "High|Medium|Low",
      "steps": [
        "Step 1: Navigate to Pengguna Terdaftar page",
        "Step 2: Fill [field] with [exact value]",
        "Step 3: Click [button]",
        "Step 4: Verify [specific observable thing]"
      ]
    }}
  ]
}}"""

    # ═══════════════════════════════════════════════════════════
    #  OBJECT BUILDERS
    # ═══════════════════════════════════════════════════════════

    def _summarise_elements(self) -> str:
        summary = [
            {
                "name": e.get("formcontrolname") or e.get("text", ""),
                "type": e.get("element_type", "")
            }
            for e in self.raw_elements[:30]
        ]
        return json.dumps(summary, indent=2, ensure_ascii=False)

    def _build_story_objects(self, raw_stories: List[Dict]) -> List[TestStory]:
        stories = []
        for s in raw_stories:
            self._story_counter += 1

            # Combine expected_outcome + validation_check into one clear string
            outcome   = s.get("expected_outcome", "")
            validation = s.get("validation_check", "")
            full_outcome = outcome
            if validation:
                full_outcome = f"{outcome}\n\nVALIDATION: {validation}"

            story = TestStory(
                story_id     = s.get("story_id", f"STORY-{self._story_counter:03d}"),
                url          = self.page_url,
                context_name = s.get("context_name", "Unknown"),
                user_persona = s.get("user_persona", "QA Tester"),
                description  = s.get("description", ""),
                field_values = s.get("field_values", {}),
                status       = StoryStatus.PENDING,
                # Store full outcome with validation in the story
                expected_outcome = full_outcome
            )

            for step_text in s.get("steps", []):
                story.add_step(
                    action  = "explore",
                    target  = step_text,
                    value   = "",
                    success = True
                )

            stories.append(story)
            print(f"  ✅ Story built: {story.story_id} — {story.context_name}")

        return stories

    # ═══════════════════════════════════════════════════════════
    #  OUTPUT WRITERS — called exactly once
    # ═══════════════════════════════════════════════════════════

    def _write_excel(self, stories: List[TestStory]):
        if not stories:
            print("  ⚠️  No stories to write")
            return
        report = ExcelReportGenerator(self.output_dir, self.session_id)
        path   = report.generate_all(stories)
        print(f"\n📊 Excel report saved: {path}")

    def _save_knowledge_json(self, stories: List[TestStory]):
        knowledge = {
            "session_id":        self.session_id,
            "page_url":          self.page_url,
            "generated_at":      datetime.now().isoformat(),
            "execution_history": self.execution_history,
            "dropdown_options":  self.dropdown_options,
            "forms_discovered":  self.forms_discovered,
            "stories_generated": len(stories),
            "stories": [
                {
                    "story_id":        s.story_id,
                    "context_name":    s.context_name,
                    "user_persona":    s.user_persona,
                    "description":     s.description,
                    "field_values":    s.field_values,
                    "expected_outcome": getattr(s, "expected_outcome", ""),
                    "status":          s.status.value,
                    "steps":           [st.__dict__ for st in s.steps]
                }
                for s in stories
            ]
        }
        path = self.output_dir / f"knowledge_{self.session_id}.json"
        with open(path, "w") as f:
            json.dump(knowledge, f, indent=2, ensure_ascii=False)
        print(f"  💾 Knowledge saved: {path}")

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