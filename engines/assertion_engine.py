from openai import OpenAI
import json

class AssertionEngine:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def generate_assertions(self, events: list) -> list[str]:
        prompt = f"""
You are a senior QA engineer.

Convert the following execution events into **human-readable QA assertions**.

Rules:
- Focus on user-visible behavior
- No element IDs
- No automation terms
- Write each assertion starting with ✔
- One assertion per line

Events:
{json.dumps(events, indent=2)}
"""

        resp = self.client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        return [
            line.strip()
            for line in resp.choices[0].message.content.splitlines()
            if line.strip()
        ]

    def generate_summary(self, assertions: list[str]) -> str:
        prompt = f"""
Write a concise QA summary (2–3 sentences) based on these assertions.

Assertions:
{chr(10).join(assertions)}
"""

        resp = self.client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        return resp.choices[0].message.content.strip()
