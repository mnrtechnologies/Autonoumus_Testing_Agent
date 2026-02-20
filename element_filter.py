"""
element_filter.py
─────────────────
Uses GPT-4o to filter out irrelevant interactive elements
before they reach the Decider.

Sits between Observer and Memory in the OMDE loop.
"""

import json
import asyncio
from typing import List, Dict, Optional
from openai import OpenAI
import anthropic


class ElementFilter:

    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client

    async def filter(
        self,
        elements:       List[Dict],
        screenshot_b64: str,
        url:            str,
        context_type:   str
    ) -> List[Dict]:
        """
        Send all elements + screenshot to GPT-4o.
        Returns only the relevant elements.
        """
        if not elements:
            return elements

        # Build a simplified version for the prompt (avoid huge payloads)
        simplified = []
        for i, e in enumerate(elements):
            simplified.append({
                "index":           i,
                "tag":             e.get("tag", ""),
                "element_type":    e.get("element_type", ""),
                "text":            e.get("text", "")[:80],
                "formcontrolname": e.get("formcontrolname", ""),
                "classes":         e.get("classes", [])[:3],
                "id":              e.get("id", ""),
                "in_overlay":      e.get("in_overlay", False),
                "type":            e.get("type", ""),
            })

        prompt = f"""You are a QA engineer reviewing interactive elements detected on a web page.
Your job is to filter out elements that should NOT be tested.

URL: {url}
CONTEXT: {context_type}

DETECTED ELEMENTS ({len(simplified)} total):
{json.dumps(simplified, indent=2)}

KEEP these elements:
- Input fields (with or without formcontrolname)
- Select/dropdown fields (with or without formcontrolname) — cascade parent dropdowns like Kategori, Sub-Kategori MUST be kept even without formcontrolname
- Textarea fields (with or without formcontrolname)
- Buttons: Submit, Save, Simpan, Tambah, Search, Cari, Cancel, Batal,
           Reset, Atur Ulang, Export, Ekspor, Perbarui, Update
- Pagination: Next page, Previous page, First page, Last page
more_vert — ALWAYS KEEP, no exceptions, regardless of context
- Row action buttons: Edit, Delete, View, Sunting, Mengedit, Hapus
- Tab buttons that switch form sections


REMOVE these elements:
- Google Maps controls: Map, Satellite, Terrain, Toggle fullscreen,
  Map camera controls, Zoom in, Zoom out, Pegman/Street view
- Any element with classes containing: gm-control, gm-fullscreen,
  gm-svpc, gm-compass, gm-bundled-control
- Calendar internals: day numbers, month navigation, year picker,
  Previous month, Next month, date cells
- Datepicker backdrop or overlay controls
- Embedded iframe controls
- Third party widget buttons not part of the main form
- Navigation links to other pages (already filtered by scope)
- Language switcher buttons
- Pagination controls: Next page, Previous page, First page, Last page,
   Items per page dropdown — ANY combobox or mat-select whose
  visible text is a number like "10", "25", "50", "100"
- ANY element inside mat-paginator
- ANY element with text that is ONLY a number and no other label

SCREENSHOT is attached — use it to visually confirm what is part of
the main form vs embedded widgets.

Return ONLY valid JSON, no markdown:
{{
  "keep_indices": [0, 1, 2, ...],
  "removed": [
    {{"index": 5, "text": "Satellite", "reason": "Google Maps control"}},
    ...
  ]
}}

keep_indices must be the exact index values from the DETECTED ELEMENTS list.
"""

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {
                             "url": f"data:image/png;base64,{screenshot_b64}"
                         }}
                    ]
                }],
                max_tokens=2000,
                temperature=0.1
            )
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

            raw  = response.choices[0].message.content
            data = json.loads(self._extract_json(raw))

            keep_indices = set(data.get("keep_indices", []))
            removed      = data.get("removed", [])

            # Log what was removed
            if removed:
                print(f"  🧹 ElementFilter removed {len(removed)} irrelevant elements:")
                for r in removed:
                    print(f"     ✂️  [{r.get('index')}] {r.get('text','?')[:40]} "
                          f"— {r.get('reason','?')}")

            # Return only kept elements
            filtered = [e for i, e in enumerate(elements) if i in keep_indices]
            print(f"  ✅ ElementFilter: {len(elements)} → {len(filtered)} elements kept")
            return filtered

        except Exception as e:
            print(f"  ⚠️  ElementFilter failed: {e} — returning all elements unfiltered")
            return elements

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