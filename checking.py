"""
main_orchestrator.py
====================
Top-level entry point that:
  1. Runs Phase 1 (TwoTierCrawler) — exploration only, no testing
  2. Reads the saved action plan JSON
  3. Extracts unique target_url values from link-type features
  4. Feeds them one-by-one to fresh SemanticTester instances (Phase 2)
     — every URL gets a completely isolated test session (no shared state)
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import List
from openai import OpenAI
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from openai import AsyncOpenAI
# ── Phase 1 ──────────────────────────────────────────────────────────────────
from main_phase1 import TwoTierCrawler   # exploration only (testing stripped out)

# ── Phase 2 ──────────────────────────────────────────────────────────────────
from hello import SemanticTester   # per-URL tester
load_dotenv()

console = Console()

OPENAI_KEY = "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"
BASE_URL   = "https://staging.isalaam.me/dashboard"
AUTH_FILE  = "auth.json"


# -----------------------------------------------------------------------------
#  STEP 1 -- Run Phase 1 exploration (testing stripped out of main.py)
# -----------------------------------------------------------------------------

# async def run_phase1_exploration() -> Path:
async def run_phase1_exploration(base_url: str) -> Path:
    """
    Runs Phase 1 crawler (exploration only).
    Returns the path to the latest saved action plan JSON.
    """
    console.print(Panel.fit(
        "[bold cyan]PHASE 1 -- Exploration[/bold cyan]\n"
        "Building knowledge graph, no testing.",
        border_style="cyan"
    ))

    crawler = TwoTierCrawler(
        # base_url=BASE_URL,
        base_url=base_url,
        auth_file=AUTH_FILE,
        max_depth=2,
        openai_api_key=OPENAI_KEY
    )
    latest_plan = await crawler.run()

    if not latest_plan:
        raise FileNotFoundError("Phase 1 finished but no action plan was saved.")

    console.print(f"\n[green]Phase 1 complete. Plan: {latest_plan}[/green]\n")
    return latest_plan

# -----------------------------------------------------------------------------
#  STEP 2 -- Extract unique target URLs from the action plan
# -----------------------------------------------------------------------------

def extract_target_urls(plan_path: Path) -> List[str]:
    """
    Reads the action plan JSON and returns a deduplicated list of
    target_url values found on steps where feature.type == 'link'.
    """
    with open(plan_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    seen = set()
    urls = []

    for step in data.get("steps", []):
        feature = step.get("feature", {})

        if feature.get("type") != "link":
            continue

        target_url = feature.get("target_url")
        if not target_url:
            continue

        if target_url in seen:
            continue

        seen.add(target_url)
        urls.append(target_url)

    console.print(f"[cyan]Extracted {len(urls)} unique URLs from plan.[/cyan]")
    for i, url in enumerate(urls, 1):
        console.print(f"   {i:>3}. {url}")

    return urls


# -----------------------------------------------------------------------------
#  STEP 3 -- Run Phase 2 testing, one URL at a time, fully isolated
# -----------------------------------------------------------------------------

async def run_phase2_for_url(url: str, index: int, total: int):
    tester = SemanticTester(
        openai_api_key=OPENAI_KEY,
        auth_file=AUTH_FILE
    )
    tester._interactive = False
    # ✅ FIX: Override session_id to include URL index
    # This prevents story/result files from different URLs overwriting each other
    tester.session_id = f"{tester.session_id}_url{index:03d}"

    try:
        await tester.run(url)
        console.print(f"[green][{index}/{total}] Done: {url}[/green]\n")

    except Exception as e:
        console.print(f"[red][{index}/{total}] Failed: {url}[/red]")
        console.print(f"[red]   Error: {e}[/red]\n")

        # Log the failure so nothing is silently lost
        _log_url_failure(url, index, str(e))


def _log_url_failure(url: str, index: int, error: str):
    """Appends a failed-URL entry to a shared failures log."""
    failures_file = Path("semantic_test_output") / "phase2_failures.jsonl"
    failures_file.parent.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "url_index": index,
        "url": url,
        "error": error
    }
    with open(failures_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
#=============================================================================
async def generate_goals_from_json(stories_data: dict) -> List[dict]:
    """
    Parses raw technical stories and uses an LLM to generate 
    professional QA goals for each unique URL in JSON format.
    """
    client = AsyncOpenAI(api_key=OPENAI_KEY)
    
    # Extract unique URLs and their technical steps to reduce token usage
    simplified_context = []
    seen_urls = set()
    
    for story in stories_data.get("stories", []):
        url = story.get("url")
        if url not in seen_urls:
            steps_summary = [f"{s['action']} {s['target']}" for s in story.get('steps', [])]
            simplified_context.append({
                "url": url,
                "technical_steps": steps_summary,
                "description": story.get("description")
            })
            seen_urls.add(url)

    # 1. Added "in JSON format" below to satisfy OpenAI requirements
    # 2. Included a specific key-value structure instruction for better reliability
    prompt = f"""
    You are a Senior QA Strategist. Based on the following technical crawl data, 
    generate a single, professional "goal" paragraph for each URL.

    Return ONLY a JSON object with a single key "url_goals" whose value is a list of objects.
    Each object must have exactly two keys: "url" (string) and "goal" (string).

    Example format:
    {{"url_goals": [{{"url": "https://example.com/page", "goal": "Navigate to..."}}]}}

    The goal should:
    1. Describe a comprehensive user journey.
    2. Include navigation, element verification, and CRUD operations if applicable.
    3. Be written as one continuous, professional instruction.

    Input Data: {json.dumps(simplified_context)}
    """

    # response_format requires the prompt above to contain the word "json"
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={ "type": "json_object" } 
    )
    
    # Parse the resulting JSON string back into a Python object
    result = json.loads(response.choices[0].message.content)
    
    # Handle both list and object-wrapped-list return styles
# Replace the last return line in generate_goals_from_json:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        # Try common wrapper keys
        for key in ("url_goals", "output", "goals", "data", "results"):
            if key in result and isinstance(result[key], list):
                return result[key]
        # Last resort: find the first list value
        for v in result.values():
            if isinstance(v, list):
                return v
    raise ValueError(f"Unexpected response structure: {result}")

#=============================================================================

# -----------------------------------------------------------------------------
#  MAIN ENTRY POINT
# -----------------------------------------------------------------------------

async def main():
    if not Path(AUTH_FILE).exists():
        console.print(f"[red]{AUTH_FILE} not found[/red]")
        return

    start = datetime.now()

    # -- Phase 1: Explore -----------------------------------------------------
    plan_path = await run_phase1_exploration()

    # -- Extract URLs ---------------------------------------------------------
    urls = extract_target_urls(plan_path)

    if not urls:
        console.print("[yellow]No testable URLs found in plan. Exiting.[/yellow]")
        return

    # -- Phase 2: Test each URL in isolation ----------------------------------
    console.print(Panel.fit(
        f"[bold green]PHASE 2 -- Starting {len(urls)} URL test sessions[/bold green]",
        border_style="green"
    ))

    for i, url in enumerate(urls, 1):
        await run_phase2_for_url(url, index=i, total=len(urls))

    # -- Summary --------------------------------------------------------------
    elapsed = datetime.now() - start
    console.print(Panel.fit(
        f"[bold cyan]ALL DONE[/bold cyan]\n"
        f"URLs tested : {len(urls)}\n"
        f"Total time  : {elapsed}",
        border_style="cyan"
    ))


if __name__ == "__main__":
    asyncio.run(main())


# For API Endpoints --------------
class CheckingPipeline:

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.status = "running"
        self.current_url = None
        self.latest_screenshot = None
        self.total_urls = 0
        self.completed_urls = 0
        self.error = None

    async def run(self):
        try:
            plan_path = await run_phase1_exploration(self.base_url)
            urls = extract_target_urls(plan_path)

            self.total_urls = len(urls)

            for i, url in enumerate(urls, 1):
                self.current_url = url
                tester = SemanticTester(
                    openai_api_key=OPENAI_KEY,
                    auth_file=AUTH_FILE
                )

                # IMPORTANT: attach screenshot hook
                tester.external_pipeline_ref = self

                await tester.run(url)

                self.completed_urls += 1

            self.status = "completed"

        except Exception as e:
            self.status = "failed"
            self.error = str(e)