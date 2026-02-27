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
import os
# ── Phase 1 ──────────────────────────────────────────────────────────────────
from main import TwoTierCrawler   # exploration only (testing stripped out)

# ── Phase 2 ──────────────────────────────────────────────────────────────────
from hello import SemanticTester   # per-URL tester
load_dotenv()

console = Console()

BASE_API_URL = os.getenv("BASE_API_URL", "http://127.0.0.1:8000")

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL   = "https://staging.isalaam.me/dashboard"
AUTH_FILE  = "auth.json"


# -----------------------------------------------------------------------------
#  STEP 1 -- Run Phase 1 exploration (testing stripped out of main.py)
# -----------------------------------------------------------------------------

# async def run_phase1_exploration() -> Path:
async def run_phase1_exploration(base_url: str, pipeline_ref=None) -> Path:
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

    if pipeline_ref:
        crawler.external_pipeline_ref = pipeline_ref

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
    URLs, checking multiple possible keys where the crawler might save them.
    """
    import json
    from rich.console import Console
    console = Console()
    
    with open(plan_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    seen = set()
    urls = []

    # Handle both cases: if data is a dict with "steps", or just a list directly
    steps = data.get("steps", data) if isinstance(data, dict) else data

    for step in steps:
        feature = step.get("feature", {})

        # Check all possible keys where the crawler might have saved the deep link
        target_url = feature.get("target_url") or feature.get("url") or feature.get("href")

        # Skip if no URL was found, or if it's not a valid http link
        if not target_url or not str(target_url).startswith("http"):
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
        
# -----------------------------------------------------------------------------
#  MAIN ENTRY POINT
# -----------------------------------------------------------------------------

# async def main():
#     if not Path(AUTH_FILE).exists():
#         console.print(f"[red]{AUTH_FILE} not found[/red]")
#         return

#     start = datetime.now()

#     # -- Phase 1: Explore -----------------------------------------------------
#     plan_path = await run_phase1_exploration()

#     # -- Extract URLs ---------------------------------------------------------
#     urls = extract_target_urls(plan_path)

#     if not urls:
#         console.print("[yellow]No testable URLs found in plan. Exiting.[/yellow]")
#         return

#     # -- Phase 2: Test each URL in isolation ----------------------------------
#     console.print(Panel.fit(
#         f"[bold green]PHASE 2 -- Starting {len(urls)} URL test sessions[/bold green]",
#         border_style="green"
#     ))

#     for i, url in enumerate(urls, 1):
#         await run_phase2_for_url(url, index=i, total=len(urls))

#     # -- Summary --------------------------------------------------------------
#     elapsed = datetime.now() - start
#     console.print(Panel.fit(
#         f"[bold cyan]ALL DONE[/bold cyan]\n"
#         f"URLs tested : {len(urls)}\n"
#         f"Total time  : {elapsed}",
#         border_style="cyan"
#     ))


# if __name__ == "__main__":
#     asyncio.run(main())


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
        self.session_id = None
        self.completed_reports = []
        self.ws_messages = []

    # async def run(self):
    #     try:
    #         import base64
    #         plan_path = await run_phase1_exploration(self.base_url, pipeline_ref=self)
    #         urls = extract_target_urls(plan_path)

    #         self.total_urls = len(urls)

    #         EXCLUDED_URLS = {
    #             "https://staging.isalaam.me/events"
    #         }

    #         filtered_urls = [u for u in urls if u not in EXCLUDED_URLS]

    #         self.total_urls = len(filtered_urls)
            
    #         console.print(f"[cyan]Extracted {len(filtered_urls)} filtered unique URLs from plan.[/cyan]")

    #         for i, url in enumerate(filtered_urls, 1):
    #             self.current_url = url

    #             tester = SemanticTester(
    #                 openai_api_key=OPENAI_KEY,
    #                 auth_file=AUTH_FILE
    #             )

    #             # Disables the "Press Enter" prompt
    #             tester._interactive = False
                
    #             # Capture the session_id from the first tester session
    #             if not self.session_id:
    #                 self.session_id = tester.session_id

    #             # IMPORTANT: attach screenshot hook
    #             tester.external_pipeline_ref = self

    #             await tester.run(url)

    #             await asyncio.sleep(2)

    #             self.completed_urls += 1


    #             # 👇 NEW: Capture the Excel report for this specific URL run
    #             report_filename = f"test_report_{tester.session_id}.xlsx"
    #             report_path = Path("semantic_test_output") / report_filename

    #             excel_b64 = None
    #             if report_path.exists():
    #                 with open(report_path, "rb") as f:
    #                     excel_b64 = base64.b64encode(f.read()).decode("utf-8")

    #             # Determine the next URL
    #             next_url = filtered_urls[i] if i < len(filtered_urls) else None
                
    #             if next_url:
    #                 msg_text = f"Exploration done for this {url}, excel sheet and proceeding to {next_url}"
    #             else:
    #                 msg_text = f"Exploration done for this {url}, excel sheet generated!"

    #             # Append to the queue
    #             self.ws_messages.append({
    #                 "type": "url_report",
    #                 "message": msg_text,
    #                 "url": url,
    #                 "next_url": next_url,
    #                 "excel_filename": report_filename,
    #                 "excel_base64": excel_b64
    #             })

    #         self.status = "completed"

    #     except Exception as e:
    #         self.status = "failed"
    #         self.error = str(e)



    async def run(self):
        try:
            import base64
            # 1. Phase 1 Start Message
            self.ws_messages.append({"type": "status", "message": "🚀 Phase 1: Deep Exploration Started"})
            
            plan_path = await run_phase1_exploration(self.base_url, pipeline_ref=self)
            
            # 2. Phase 1 Complete / Transition Message
            self.ws_messages.append({
                "type": "status", 
                "message": "✅ Phase 1 complete. Moving forward to Phase 2 !!!"
            })

            urls = extract_target_urls(plan_path)
            EXCLUDED_URLS = {"https://staging.isalaam.me/events",
                             "https://staging.isalaam.me/mosque/profile"}
#             EXCLUDED_URLS = {
#   "https://staging.isalaam.me/events",
#   "https://staging.isalaam.me/gallery",
#   "https://staging.isalaam.me/reports",
#   "https://staging.isalaam.me/techsupport",
#   "https://staging.isalaam.me/mosque/controlcenter",
#   "https://staging.isalaam.me/mosque/profile",
#   "https://staging.isalaam.me/mosque/inventory",
#   "https://staging.isalaam.me/mosque/pthreshold",
#   "https://staging.isalaam.me/mosque/payment-transactions",
#   "https://staging.isalaam.me/mosque/pay-outs",
#   "https://staging.isalaam.me/mosque/keymembers"
# }
            filtered_urls = [u for u in urls if u not in EXCLUDED_URLS]
            self.total_urls = len(filtered_urls)
            console.print(f"[cyan]Extracted {len(filtered_urls)} filtered unique URLs from plan.[/cyan]")

            # 3. Sequential Phase 2 Loop
            for i, url in enumerate(filtered_urls, 1):
                self.current_url = url
                next_url = filtered_urls[i] if i < len(filtered_urls) else None
                
                # Message for starting a specific URL
                self.ws_messages.append({
                    "type": "status", 
                    "message": f"🔍 Started exploring {url} ({i}/{self.total_urls})"
                })

                tester = SemanticTester(openai_api_key=OPENAI_KEY, auth_file=AUTH_FILE)
                tester._interactive = False
                tester.external_pipeline_ref = self # Required for image streaming
                
                await tester.run(url)
                self.completed_urls += 1

                # ✅ Track the completed session for Phase 3
                self.completed_reports.append({
                    "session_id": tester.session_id,
                    "url": url
                })

                # 4. Immediate Excel Capture
                report_filename = f"test_report_{tester.session_id}.xlsx"
                report_path = Path("semantic_test_output") / report_filename
                excel_b64 = None
                
                if report_path.exists():
                    with open(report_path, "rb") as f:
                        excel_b64 = base64.b64encode(f.read()).decode("utf-8")

                # Final URL Report with download links and data
                msg_text = f"✅ Exploration done for {url}. Excel generated."
                if next_url:
                    msg_text += f" Proceeding to next URL: {next_url}"

                self.ws_messages.append({
                    "type": "url_report",
                    "message": msg_text,
                    "url": url,
                    "session_id": tester.session_id,
                    "download_url": f"{BASE_API_URL}/semantic/{tester.session_id}/download-report",
                    "excel_filename": report_filename,
                    "excel_base64": excel_b64
                })

            self.status = "validating"
            self.ws_messages.append({"type": "status", "message": "🎊 Phase 2 Exploration Completed!, 🚀 Phase 3: Validation Auto-Starting..."})

            from app import trigger_phase3_logic
            await trigger_phase3_logic(self)
            print("Phase 3 Triggered!")

            self.status = "completed"
            self.ws_messages.append({"type": "status", "message": "🏁 Phase 3 Validation Complete!"})


        except Exception as e:
            self.status = "failed"
            self.error = str(e)
            self.ws_messages.append({"type": "error", "message": f"Pipeline failed: {str(e)}"})