"""
page_state_extractor.py
───────────────────────
Extracts a structured semantic summary of the current page state from a screenshot.
Called BEFORE and AFTER each action in the test loop.
The before/after pair is stored in history and later used by KnowledgeHarvester
to generate specific, testable validation_check fields in test stories.

Usage:
    extractor = PageStateExtractor(openai_client)
    state = await extractor.extract(screenshot_b64, url, action_context="clicked Next page")
"""

import json
from typing import Optional
from openai import OpenAI


class PageStateExtractor:

    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client

    async def extract(
        self,
        screenshot_b64: str,
        url: str,
        action_context: str = ""
    ) -> dict:
        """
        Send screenshot to GPT-4o-mini and extract a structured page state summary.
        Returns a dict. Never raises — returns empty dict on failure.
        """
        if not screenshot_b64:
            return {}

        prompt = self._build_prompt(url, action_context)

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}
                        }
                    ]
                }],
                max_tokens=600,
                temperature=0.0   # deterministic — we want consistent structured output
            )
            raw = response.choices[0].message.content
            return self._parse(raw)

        except Exception as e:
            print(f"  ⚠️  PageStateExtractor failed: {e}")
            return {}

    def _build_prompt(self, url: str, action_context: str) -> str:
        ctx = f"\nThis screenshot was taken AFTER: {action_context}" if action_context else ""
        return f"""You are a QA assistant analysing a web page screenshot.
URL: {url}{ctx}

Extract the current visible page state. Return ONLY valid JSON, no markdown.

Focus on what is VISIBLE and COUNTABLE in the screenshot right now.

{{
  "page_title": "text of the main heading visible on page, or null",
  "total_records": "number shown e.g. '13 Total Peran' → 13, or null if not visible",
  "current_page": "current pagination page number as integer, or null",
  "total_pages": "total pages if visible, or null",
  "pagination_text": "exact pagination text visible e.g. '1-10 of 13', or null",
  "visible_row_count": "number of data rows visible in the table right now as integer, or null",
  "visible_rows": ["list of up to 5 row identifiers visible — use first column text, e.g. role name or user name"],
  "active_filters": {{"field_name": "value applied"}} ,
  "search_value": "current value in search/filter input if visible, or null",
  "toast_message": "text of any toast/snackbar/alert visible, or null",
  "modal_open": "title of open modal/dialog if any, or null",
  "error_message": "any error text visible on page, or null",
  "empty_state": "text of empty state message if table is empty, or null"
}}

Rules:
- visible_rows: only list what you can actually read in the screenshot
- If the table is empty, set visible_row_count to 0 and visible_rows to []
- If pagination is not visible, set current_page and total_pages to null
- Be precise — do not guess values you cannot see
"""

    def _parse(self, text: str) -> dict:
        """Extract JSON from response, handle markdown fences."""
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:end].strip()
        else:
            text = text.strip()

        try:
            return json.loads(text)
        except Exception:
            return {}


def diff_states(before: dict, after: dict) -> dict:
    """
    Compare two page states and return a human-readable diff dict.
    Used by KnowledgeHarvester to build specific validation descriptions.
    """
    if not before or not after:
        return {}

    diff = {}

    # Pagination change
    if before.get("current_page") != after.get("current_page"):
        diff["page_changed"] = {
            "from": before.get("current_page"),
            "to": after.get("current_page")
        }

    # Row list change
    before_rows = set(before.get("visible_rows") or [])
    after_rows  = set(after.get("visible_rows") or [])
    if before_rows != after_rows:
        diff["rows_changed"] = {
            "before": list(before_rows),
            "after":  list(after_rows),
            "added":  list(after_rows - before_rows),
            "removed": list(before_rows - after_rows)
        }

    # Row count change
    before_count = before.get("visible_row_count")
    after_count  = after.get("visible_row_count")
    if before_count is not None and after_count is not None and before_count != after_count:
        diff["row_count_changed"] = {"from": before_count, "to": after_count}

    # Total records change
    if before.get("total_records") != after.get("total_records"):
        diff["total_records_changed"] = {
            "from": before.get("total_records"),
            "to":   after.get("total_records")
        }

    # Filter applied
    before_search = before.get("search_value")
    after_search  = after.get("search_value")
    if before_search != after_search:
        diff["search_changed"] = {"from": before_search, "to": after_search}

    # Active filters
    before_filters = before.get("active_filters") or {}
    after_filters  = after.get("active_filters") or {}
    if before_filters != after_filters:
        diff["filters_changed"] = {"from": before_filters, "to": after_filters}

    # Toast appeared
    after_toast = after.get("toast_message")
    if after_toast and after_toast != before.get("toast_message"):
        diff["toast_appeared"] = after_toast

    # Modal opened or closed
    before_modal = before.get("modal_open")
    after_modal  = after.get("modal_open")
    if before_modal != after_modal:
        diff["modal_changed"] = {"from": before_modal, "to": after_modal}

    # Error appeared
    after_error = after.get("error_message")
    if after_error and after_error != before.get("error_message"):
        diff["error_appeared"] = after_error

    # Empty state appeared
    after_empty = after.get("empty_state")
    if after_empty and after_empty != before.get("empty_state"):
        diff["empty_state_appeared"] = after_empty

    return diff