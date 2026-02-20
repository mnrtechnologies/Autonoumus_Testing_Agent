"""
test_story_engine.py
────────────────────
Generates coherent user test stories from page context and tracks
pass/fail status in real-time.

Components:
  TestStory          — data model for one user test story
  TestStoryGenerator — calls GPT-4o to generate realistic field values
  TestStoryTracker   — tracks story execution, marks pass/fail
  ReportGenerator    — outputs console table + JSON + HTML report
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum

from openai import OpenAI
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


# ═══════════════════════════════════════════════════════════════
#  DATA MODELS
# ═══════════════════════════════════════════════════════════════

class StoryStatus(Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    PASSED   = "passed"
    FAILED   = "failed"
    SKIPPED  = "skipped"


@dataclass
class StoryStep:
    """One action within a test story."""
    step_num:    int
    action:      str          # fill / select / click / check
    target:      str          # field name or button label
    value:       str          # value used
    success:     bool
    error:       Optional[str] = None
    timestamp:   str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TestStory:
    """
    One coherent user test story for a form/modal/page.
    Generated once when empty fields are detected, then executed step by step.
    """
    story_id:        str
    url:             str
    context_name:    str          # e.g. "Create Store Form", "Add Bank Account Modal"
    user_persona:    str          # e.g. "Store owner adding a new outlet"
    description:     str          # short human-readable scenario
    field_values:    Dict[str, str]  # fieldname → value to use
    status:          StoryStatus = StoryStatus.PENDING
    steps:           List[StoryStep] = field(default_factory=list)
    failure_reason:  Optional[str] = None
    started_at:      Optional[str] = None
    finished_at:     Optional[str] = None

    def start(self):
        self.status     = StoryStatus.RUNNING
        self.started_at = datetime.now().isoformat()

    def pass_story(self):
        self.status      = StoryStatus.PASSED
        self.finished_at = datetime.now().isoformat()

    def fail_story(self, reason: str):
        self.status         = StoryStatus.FAILED
        self.failure_reason = reason
        self.finished_at    = datetime.now().isoformat()

    def add_step(self, action: str, target: str, value: str,
                 success: bool, error: Optional[str] = None):
        self.steps.append(StoryStep(
            step_num  = len(self.steps) + 1,
            action    = action,
            target    = target,
            value     = value,
            success   = success,
            error     = error
        ))

    def get_value_for(self, field_name: str) -> Optional[str]:
        """
        Look up a generated value by field name / formcontrolname / placeholder.
        Case-insensitive, partial match supported.
        """
        if not field_name:
            return None
        fn = field_name.lower().strip()

        # Exact match first
        for k, v in self.field_values.items():
            if k.lower() == fn:
                return v

        # Partial match
        for k, v in self.field_values.items():
            if fn in k.lower() or k.lower() in fn:
                return v

        return None

    def to_dict(self) -> Dict:
        return {
            "story_id":       self.story_id,
            "url":            self.url,
            "context_name":   self.context_name,
            "user_persona":   self.user_persona,
            "description":    self.description,
            "field_values":   self.field_values,
            "status":         self.status.value,
            "failure_reason": self.failure_reason,
            "started_at":     self.started_at,
            "finished_at":    self.finished_at,
            "steps": [
                {
                    "step":    s.step_num,
                    "action":  s.action,
                    "target":  s.target,
                    "value":   s.value,
                    "success": s.success,
                    "error":   s.error,
                    "timestamp": s.timestamp
                }
                for s in self.steps
            ]
        }


# ═══════════════════════════════════════════════════════════════
#  TEST STORY GENERATOR
# ═══════════════════════════════════════════════════════════════

class TestStoryGenerator:
    """
    Calls GPT-4o to generate a coherent user test story
    based on the detected form/page elements.
    """

    def __init__(self, openai_client: OpenAI):
        self.openai   = openai_client
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        ts = datetime.now().strftime("%H%M%S")
        return f"STORY-{ts}-{self._counter:03d}"

    async def generate(
        self,
        url:          str,
        elements:     List[Dict],
        screenshot_b64: str,
        context_type: str = "page"
    ) -> TestStory:
        """
        Given the current page elements and screenshot, generate a
        realistic user test story with field values.
        """

        print(f"\n{'='*60}")
        print(f"🔍 STORY GEN DEBUG:")
        print(f"   URL: {url}")
        print(f"   Context type: {context_type}")
        print(f"   Screenshot size (bytes): {len(screenshot_b64) if screenshot_b64 else 0}")
        print(f"   Fillable elements: {[e.get('formcontrolname') or e.get('text') for e in elements]}")
        print(f"{'='*60}\n")
        # Build element summary for the prompt
        fillable = [
            e for e in elements
            if e.get("element_type") in ("input", "textarea", "select", "custom-select")
        ]
        buttons = [
            e for e in elements
            if e.get("element_type") == "button"
        ]

        elem_summary = []
        for e in fillable:
            name = (e.get("formcontrolname") or e.get("placeholder") or
                    e.get("text") or e.get("name") or "unknown")
            elem_summary.append({
                "field":       name,
                "type":        e.get("element_type"),
                "input_type":  e.get("type", ""),
                "required":    e.get("required", False),
                "in_overlay":  e.get("in_overlay", False)
            })

        button_names = [b.get("text", "") for b in buttons if b.get("text")]

        prompt = f"""You are a QA engineer testing a web page. A screenshot is attached.

URL: {url}
CONTEXT TYPE: {context_type}

FORM FIELDS DETECTED:
{json.dumps(elem_summary, indent=2)}

SUBMIT/ACTION BUTTONS:
{json.dumps(button_names, indent=2)}

YOUR TASK:
The CONTEXT TYPE tells you what to do:

If CONTEXT TYPE is "page":
- Look at the table in the screenshot
- Use EXACT values from the first row for search/filter fields
- This ensures search finds real existing records

If CONTEXT TYPE is "form" or "modal":
- DO NOT look at the screenshot for values
- ONLY use the FORM FIELDS DETECTED list above
- Generate completely NEW realistic values based on field names only
- Treat every field as empty and fill with fresh data
- NEVER copy anything visible in the screenshot

FIELD VALUE RULES:
- start → always "01/01/2025"
- end → always "17/02/2026"
- address/alamat → "Jl. Sudirman No. 45, Jakarta Selatan"

Return ONLY valid JSON:
{{
  "context_name": "short name of what this page does",
  "user_persona": "one sentence about who is doing this",
  "description": "2-sentence scenario",
  "field_values": {{
    "fieldname_or_formcontrolname": "value",
    ...
  }}
}}

Keys in field_values MUST match the 'field' values from FORM FIELDS DETECTED above exactly.
"""
        print(f"\n📝 PROMPT BEING SENT TO GPT:")
        print(prompt)
        print(f"\n{'='*60}\n")
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                    ]
                }],
                max_tokens=1500,
                temperature=0.7
            )
            raw  = response.choices[0].message.content
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
            print(f"\n{'='*60}")
            print(f"🤖 STORY GEN RAW OUTPUT:")
            print(raw)
            print(f"{'='*60}\n")
            data = json.loads(self._extract_json(raw))
            print(f"📋 PARSED FIELD VALUES: {json.dumps(data.get('field_values', {}), indent=2)}")

            story = TestStory(
                story_id     = self._next_id(),
                url          = url,
                context_name = data.get("context_name", f"Test on {context_type}"),
                user_persona = data.get("user_persona", "QA tester"),
                description  = data.get("description", ""),
                field_values = data.get("field_values", {})
            )

            console.print(Panel(
                f"[bold cyan]📖 TEST STORY GENERATED[/bold cyan]\n"
                f"[yellow]ID      :[/yellow] {story.story_id}\n"
                f"[yellow]Context :[/yellow] {story.context_name}\n"
                f"[yellow]Persona :[/yellow] {story.user_persona}\n"
                f"[yellow]Scenario:[/yellow] {story.description}\n"
                f"[green]Fields  :[/green] {len(story.field_values)} values generated",
                border_style="cyan"
            ))

            # Print the generated values
            t = Table(title="Generated Field Values", box=box.SIMPLE)
            t.add_column("Field", style="cyan")
            t.add_column("Value", style="green")
            for k, v in story.field_values.items():
                t.add_row(k, str(v))
            console.print(t)

            return story

        except Exception as e:
            console.print(f"[red]⚠️  Story generation failed: {e} — using fallback story[/red]")
            return self._fallback_story(url, elements, context_type)

    def _fallback_story(self, url: str, elements: List[Dict], context_type: str) -> TestStory:
        """Minimal fallback when GPT call fails."""
        field_values = {}
        for e in elements:
            name = (e.get("formcontrolname") or e.get("placeholder") or
                    e.get("text") or e.get("name") or "")
            if not name:
                continue
            t = e.get("type", "").lower()
            if "email" in name.lower():
                field_values[name] = "test@example.com"
            elif "phone" in name.lower() or "hp" in name.lower():
                field_values[name] = "081234567890"
            elif t == "number":
                field_values[name] = "100"
            else:
                field_values[name] = f"Test {name.title()}"

        return TestStory(
            story_id     = self._next_id(),
            url          = url,
            context_name = f"Test on {context_type}",
            user_persona = "QA tester (fallback)",
            description  = "Fallback story — GPT generation failed.",
            field_values = field_values
        )

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
#  TEST STORY TRACKER
# ═══════════════════════════════════════════════════════════════

class TestStoryTracker:
    """
    Manages active + completed test stories.
    Integrates with the OMDE loop to track each action against the current story.
    """

    FAIL_KEYWORDS = [
        "error", "gagal", "failed", "tidak valid", "invalid",
        "required", "wajib", "must", "salah", "wrong"
    ]

    def __init__(self, output_dir: Path):
        self.output_dir    = output_dir
        self.stories:      List[TestStory] = []
        self.active_story: Optional[TestStory] = None
        self._generator:   Optional[TestStoryGenerator] = None

    def set_generator(self, gen: TestStoryGenerator):
        self._generator = gen

    def start_story(self, story: TestStory):
        """Mark a story as active and running."""
        self.active_story = story
        self.stories.append(story)
        story.start()
        console.print(f"\n[bold green]▶ STORY STARTED:[/bold green] "
                      f"[cyan]{story.story_id}[/cyan] — {story.context_name}")

    def record_action(
        self,
        action:  str,
        target:  str,
        value:   str,
        success: bool,
        error:   Optional[str] = None
    ):
        """Record one executed action against the active story."""
        if not self.active_story:
            return

        story = self.active_story
        story.add_step(action, target, value, success, error)

        icon = "✅" if success else "❌"
        console.print(f"  {icon} [{story.story_id}] {action} → {target}"
                      + (f" = '{value}'" if value else "")
                      + (f"  ⚠️  {error}" if error and not success else ""))

        # Auto-fail conditions
        if not success and error:
            err_lower = error.lower()
            # Permanent failures (not transient)
            if any(k in err_lower for k in ["disabled", "not found", "timeout", "detached"]):
                pass  # These are handled by the main loop
            else:
                self._check_toast_failure(error)

    def _check_toast_failure(self, error: str):
        """Check if an error message looks like a server validation failure."""
        if any(kw in error.lower() for kw in self.FAIL_KEYWORDS):
            if self.active_story and self.active_story.status == StoryStatus.RUNNING:
                self.active_story.fail_story(f"Validation/server error: {error[:200]}")
                console.print(f"  [red]❌ STORY FAILED:[/red] {self.active_story.story_id}")

    def mark_loop_detected(self, target: str):
        """Loop detected = story stuck = fail."""
        if self.active_story and self.active_story.status == StoryStatus.RUNNING:
            reason = f"Loop detected on target: {target}"
            self.active_story.fail_story(reason)
            console.print(f"  [red]❌ STORY FAILED (loop):[/red] {self.active_story.story_id}")

    def mark_submit_failed(self, target: str, error: str):
        """Submit button click failed = story failed."""
        if self.active_story and self.active_story.status == StoryStatus.RUNNING:
            reason = f"Submit failed on '{target}': {error}"
            self.active_story.fail_story(reason)
            console.print(f"  [red]❌ STORY FAILED (submit):[/red] {self.active_story.story_id}")

    def complete_story(self, toast_text: str = ""):
        """
        Called when a form/modal context closes (submit succeeded or cancelled).
        Checks for error toasts before marking passed.
        """
        if not self.active_story:
            return

        story = self.active_story

        if story.status == StoryStatus.RUNNING:
            # Check if the page showed an error toast after submit
            if toast_text and any(kw in toast_text.lower() for kw in self.FAIL_KEYWORDS):
                story.fail_story(f"Error toast after submit: {toast_text[:200]}")
                console.print(f"  [red]❌ STORY FAILED (toast):[/red] {story.story_id}")
            else:
                story.pass_story()
                console.print(f"  [bold green]✅ STORY PASSED:[/bold green] "
                              f"[cyan]{story.story_id}[/cyan] — {story.context_name}")

        self.active_story = None
        self._print_story_summary(story)

    def abandon_story(self, reason: str = "Context changed"):
        """Called when we leave a page/context without completing the story."""
        if not self.active_story:
            return

        story = self.active_story
        if story.status == StoryStatus.RUNNING:
            if any(s.success for s in story.steps):
                # Had some successes — count as passed if no explicit failures
                story.pass_story()
                console.print(f"  [green]✅ STORY PASSED (partial):[/green] {story.story_id}")
            else:
                story.fail_story(reason)
                console.print(f"  [red]❌ STORY FAILED (abandoned):[/red] {story.story_id}")

        self.active_story = None

    def get_value_for_field(self, field_name: str) -> Optional[str]:
        """Get a generated story value for a field (used by Decider)."""
        if self.active_story:
            return self.active_story.get_value_for(field_name)
        return None

    def _print_story_summary(self, story: TestStory):
        icon    = "✅" if story.status == StoryStatus.PASSED else "❌"
        total   = len(story.steps)
        success = sum(1 for s in story.steps if s.success)

        console.print(Panel(
            f"{icon} [bold]{'PASSED' if story.status == StoryStatus.PASSED else 'FAILED'}[/bold]\n"
            f"[cyan]{story.context_name}[/cyan]\n"
            f"[yellow]Persona:[/yellow] {story.user_persona}\n"
            f"[yellow]Steps  :[/yellow] {success}/{total} succeeded"
            + (f"\n[red]Reason :[/red] {story.failure_reason}" if story.failure_reason else ""),
            border_style="green" if story.status == StoryStatus.PASSED else "red"
        ))


# ═══════════════════════════════════════════════════════════════
#  REPORT GENERATOR
# ═══════════════════════════════════════════════════════════════

class ReportGenerator:
    """Generates console summary + JSON + HTML report from completed stories."""

    def __init__(self, output_dir: Path, session_id: str):
        self.output_dir = output_dir
        self.session_id = session_id

    def generate_all(self, stories: List[TestStory]):
        """Generate all three report formats."""
        self._print_console(stories)
        json_path = self._save_json(stories)
        html_path = self._save_html(stories)
        console.print(f"\n[bold green]📁 Reports saved:[/bold green]")
        console.print(f"   JSON : {json_path}")
        console.print(f"   HTML : {html_path}")
        return json_path, html_path

    def _print_console(self, stories: List[TestStory]):
        passed  = [s for s in stories if s.status == StoryStatus.PASSED]
        failed  = [s for s in stories if s.status == StoryStatus.FAILED]
        skipped = [s for s in stories if s.status == StoryStatus.SKIPPED]

        console.print("\n")
        console.print(Panel.fit(
            f"[bold white]📊 TEST STORY REPORT[/bold white]\n"
            f"[green]✅ Passed : {len(passed)}[/green]   "
            f"[red]❌ Failed : {len(failed)}[/red]   "
            f"[yellow]⏭ Skipped: {len(skipped)}[/yellow]   "
            f"[cyan]Total  : {len(stories)}[/cyan]",
            border_style="white"
        ))

        t = Table(
            title="Test Story Results",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan"
        )
        t.add_column("Status",        width=10)
        t.add_column("Story ID",      width=20)
        t.add_column("Context",       width=30)
        t.add_column("Persona",       width=35)
        t.add_column("Steps",         width=10)
        t.add_column("Failure Reason",width=40)

        for s in stories:
            if s.status == StoryStatus.PASSED:
                status_str = "[bold green]✅ PASSED[/bold green]"
            elif s.status == StoryStatus.FAILED:
                status_str = "[bold red]❌ FAILED[/bold red]"
            else:
                status_str = "[yellow]⏭ SKIP[/yellow]"

            total   = len(s.steps)
            success = sum(1 for step in s.steps if step.success)
            steps_str = f"{success}/{total}"

            t.add_row(
                status_str,
                s.story_id,
                s.context_name,
                s.user_persona[:35],
                steps_str,
                (s.failure_reason or "—")[:40]
            )

        console.print(t)

        # Per-story detail for failed ones
        if failed:
            console.print("\n[bold red]❌ FAILED STORY DETAILS[/bold red]")
            for s in failed:
                detail_table = Table(
                    title=f"[red]{s.story_id} — {s.context_name}[/red]",
                    box=box.SIMPLE
                )
                detail_table.add_column("Step",    width=6)
                detail_table.add_column("Action",  width=10)
                detail_table.add_column("Target",  width=30)
                detail_table.add_column("Value",   width=25)
                detail_table.add_column("Result",  width=10)
                detail_table.add_column("Error",   width=35)

                for step in s.steps:
                    result_str = "[green]✓[/green]" if step.success else "[red]✗[/red]"
                    detail_table.add_row(
                        str(step.step_num),
                        step.action,
                        step.target[:30],
                        (step.value or "")[:25],
                        result_str,
                        (step.error or "")[:35]
                    )
                console.print(detail_table)

    def _save_json(self, stories: List[TestStory]) -> Path:
        passed  = sum(1 for s in stories if s.status == StoryStatus.PASSED)
        failed  = sum(1 for s in stories if s.status == StoryStatus.FAILED)

        data = {
            "session_id":    self.session_id,
            "generated_at":  datetime.now().isoformat(),
            "summary": {
                "total":   len(stories),
                "passed":  passed,
                "failed":  failed,
                "skipped": len(stories) - passed - failed
            },
            "stories": [s.to_dict() for s in stories]
        }
        path = self.output_dir / f"test_stories_{self.session_id}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path

    def _save_html(self, stories: List[TestStory]) -> Path:
        passed = sum(1 for s in stories if s.status == StoryStatus.PASSED)
        failed = sum(1 for s in stories if s.status == StoryStatus.FAILED)
        total  = len(stories)
        pct    = round((passed / total * 100) if total else 0)

        rows = ""
        for s in stories:
            success_steps = sum(1 for st in s.steps if st.success)
            total_steps   = len(s.steps)

            if s.status == StoryStatus.PASSED:
                badge = '<span class="badge pass">✅ PASSED</span>'
                row_class = "row-pass"
            elif s.status == StoryStatus.FAILED:
                badge = '<span class="badge fail">❌ FAILED</span>'
                row_class = "row-fail"
            else:
                badge = '<span class="badge skip">⏭ SKIP</span>'
                row_class = "row-skip"

            # Steps detail expandable
            steps_html = ""
            for st in s.steps:
                icon = "✅" if st.success else "❌"
                err  = f'<span class="err"> — {st.error}</span>' if st.error and not st.success else ""
                steps_html += (
                    f'<div class="step">{icon} '
                    f'<b>{st.action}</b> → {st.target}'
                    + (f' = <code>{st.value}</code>' if st.value else "")
                    + err + "</div>"
                )

            # Field values
            fv_html = "".join(
                f'<div class="fv"><span class="fk">{k}</span>: <span class="fv-val">{v}</span></div>'
                for k, v in s.field_values.items()
            )

            fail_reason = (
                f'<div class="fail-reason">⚠️ {s.failure_reason}</div>'
                if s.failure_reason else ""
            )

            rows += f"""
            <tr class="{row_class}">
              <td>{badge}</td>
              <td><code>{s.story_id}</code></td>
              <td><b>{s.context_name}</b></td>
              <td>{s.user_persona}</td>
              <td>
                <div class="scenario">{s.description}</div>
                {fail_reason}
                <details>
                  <summary>{success_steps}/{total_steps} steps</summary>
                  <div class="steps-detail">{steps_html}</div>
                </details>
                <details>
                  <summary>Field values ({len(s.field_values)})</summary>
                  <div class="fv-detail">{fv_html}</div>
                </details>
              </td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Test Story Report — {self.session_id}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f172a; color: #e2e8f0; padding: 24px;
    }}
    h1 {{ font-size: 1.8rem; color: #38bdf8; margin-bottom: 4px; }}
    .subtitle {{ color: #94a3b8; font-size: 0.9rem; margin-bottom: 24px; }}

    .summary-bar {{
      display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap;
    }}
    .stat {{
      background: #1e293b; border-radius: 10px; padding: 16px 24px;
      border: 1px solid #334155; min-width: 120px; text-align: center;
    }}
    .stat .num {{ font-size: 2rem; font-weight: 700; }}
    .stat .lbl {{ font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }}
    .stat.pass {{ border-color: #22c55e; }}
    .stat.pass .num {{ color: #22c55e; }}
    .stat.fail {{ border-color: #ef4444; }}
    .stat.fail .num {{ color: #ef4444; }}
    .stat.total {{ border-color: #38bdf8; }}
    .stat.total .num {{ color: #38bdf8; }}

    .progress-bar {{
      background: #1e293b; border-radius: 999px; height: 10px;
      margin-bottom: 28px; overflow: hidden;
    }}
    .progress-fill {{
      height: 100%; background: linear-gradient(90deg, #22c55e, #16a34a);
      border-radius: 999px; transition: width 0.5s;
      width: {pct}%;
    }}

    table {{
      width: 100%; border-collapse: collapse; background: #1e293b;
      border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }}
    th {{
      background: #0f172a; color: #94a3b8; font-size: 0.75rem;
      text-transform: uppercase; letter-spacing: 0.05em;
      padding: 12px 16px; text-align: left; border-bottom: 1px solid #334155;
    }}
    td {{ padding: 14px 16px; border-bottom: 1px solid #1e293b; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    .row-pass {{ border-left: 3px solid #22c55e; }}
    .row-fail {{ border-left: 3px solid #ef4444; }}
    .row-skip {{ border-left: 3px solid #f59e0b; }}
    tr:hover td {{ background: #172033; }}

    .badge {{
      display: inline-block; padding: 4px 10px; border-radius: 999px;
      font-size: 0.75rem; font-weight: 700;
    }}
    .badge.pass {{ background: #166534; color: #4ade80; }}
    .badge.fail {{ background: #7f1d1d; color: #f87171; }}
    .badge.skip {{ background: #78350f; color: #fcd34d; }}

    code {{ background: #0f172a; padding: 2px 6px; border-radius: 4px;
             font-size: 0.8rem; color: #7dd3fc; }}

    .scenario {{ font-size: 0.85rem; color: #94a3b8; margin-bottom: 8px; }}
    .fail-reason {{
      background: #3b1212; border: 1px solid #ef4444; border-radius: 6px;
      padding: 6px 10px; font-size: 0.8rem; color: #f87171;
      margin-bottom: 8px;
    }}

    details {{ margin-top: 6px; }}
    summary {{
      cursor: pointer; font-size: 0.8rem; color: #7dd3fc;
      padding: 4px 0; user-select: none;
    }}
    summary:hover {{ color: #38bdf8; }}

    .steps-detail, .fv-detail {{
      background: #0f172a; border-radius: 6px; padding: 10px;
      margin-top: 6px; font-size: 0.8rem;
    }}
    .step {{ padding: 3px 0; border-bottom: 1px solid #1e293b; }}
    .step:last-child {{ border-bottom: none; }}
    .err {{ color: #f87171; }}

    .fv {{ padding: 2px 0; }}
    .fk {{ color: #94a3b8; }}
    .fv-val {{ color: #4ade80; }}

    .footer {{
      margin-top: 24px; text-align: center;
      font-size: 0.75rem; color: #475569;
    }}
  </style>
</head>
<body>
  <h1>🧪 Test Story Report</h1>
  <div class="subtitle">Session: {self.session_id} &nbsp;·&nbsp;
    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>

  <div class="summary-bar">
    <div class="stat total"><div class="num">{total}</div><div class="lbl">Total</div></div>
    <div class="stat pass"><div class="num">{passed}</div><div class="lbl">Passed</div></div>
    <div class="stat fail"><div class="num">{failed}</div><div class="lbl">Failed</div></div>
    <div class="stat total"><div class="num">{pct}%</div><div class="lbl">Pass Rate</div></div>
  </div>

  <div class="progress-bar"><div class="progress-fill"></div></div>

  <table>
    <thead>
      <tr>
        <th>Status</th>
        <th>Story ID</th>
        <th>Context</th>
        <th>Persona</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>

  <div class="footer">
    Generated by Semantic Test Engine &nbsp;·&nbsp; {datetime.now().year}
  </div>
</body>
</html>"""

        path = self.output_dir / f"test_report_{self.session_id}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path