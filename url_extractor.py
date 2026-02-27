"""
url_extractor.py
────────────────
Scans the output/ session directories to find the LATEST versioned
main_action_plan_vN.json file, extracts all unique target_url values
from 'link' type features, and returns them in order.

Usage (standalone):
    python url_extractor.py

Usage (as module):
    from url_extractor import get_urls_from_latest_plan
    urls = get_urls_from_latest_plan()          # auto-detect latest
    urls = get_urls_from_latest_plan(plan_path) # explicit path
"""

import json
import re
from pathlib import Path
from typing import List, Optional
from rich.console import Console

console = Console()


def _find_latest_plan_file(output_dir: Path = Path("semantic_test_output")) -> Optional[Path]:
    """
    Walk all session_* subdirectories under output/ and return the
    plans/main_action_plan_vN.json with the highest version number.
    """
    best_file: Optional[Path]    = None
    best_version: int            = -1
    best_mtime: float            = -1.0

    if not output_dir.exists():
        return None

    # Collect every main_action_plan_vN.json across ALL sessions
    for plan_file in output_dir.rglob("main_action_plan_v*.json"):
        # Extract version number from filename
        match = re.search(r"main_action_plan_v(\d+)\.json$", plan_file.name)
        if not match:
            continue
        version = int(match.group(1))
        mtime   = plan_file.stat().st_mtime

        # Prefer highest version; break ties by most recently modified
        if version > best_version or (version == best_version and mtime > best_mtime):
            best_version = version
            best_mtime   = mtime
            best_file    = plan_file

    return best_file


def extract_target_urls(data: dict) -> List[str]:
    """
    Return deduplicated, ordered target_url values from link-type features.
    Preserves first-seen order; silently skips non-link or URL-less steps.
    """
    seen: set        = set()
    urls: List[str]  = []

    for step in data.get("steps", []):
        feature    = step.get("feature", {})
        feat_type  = feature.get("type", "")
        target_url = feature.get("target_url")

        # Only process link features that have a real URL
        if feat_type != "link":
            continue
        if not target_url:
            continue
        # Deduplicate
        if target_url in seen:
            continue

        seen.add(target_url)
        urls.append(target_url)

    return urls


def get_urls_from_latest_plan(
    plan_path: Optional[str] = None,
    output_dir: Path = Path("semantic_test_output")
) -> List[str]:
    """
    Main entry point.

    Args:
        plan_path:  Explicit path to a plan JSON file. If None, the latest
                    main_action_plan_vN.json is auto-detected from semantic_test_output/.
        output_dir: Root directory to search when plan_path is None.

    Returns:
        Ordered, deduplicated list of target_url strings.
    """
    # ── Resolve plan file ────────────────────────────────────────────────────
    if plan_path:
        resolved = Path(plan_path)
    else:
        resolved = _find_latest_plan_file(output_dir)

    if resolved is None or not resolved.exists():
        console.print("[red]❌ No main_action_plan file found.[/red]")
        console.print(f"[yellow]   Searched in: {output_dir.resolve()}[/yellow]")
        return []

    console.print(f"\n[cyan]📄 Reading plan: {resolved}[/cyan]")

    # ── Load JSON ────────────────────────────────────────────────────────────
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        console.print(f"[red]❌ Failed to read plan file: {e}[/red]")
        return []

    total_steps = len(data.get("steps", []))
    console.print(f"[dim]   Plan version : {data.get('version', '?')}[/dim]")
    console.print(f"[dim]   Total steps  : {total_steps}[/dim]")

    # ── Extract URLs ─────────────────────────────────────────────────────────
    urls = extract_target_urls(data)

    console.print(f"[green]   ✅ Extracted {len(urls)} unique link URLs "
                  f"(from {total_steps} steps)[/green]")

    for i, url in enumerate(urls, 1):
        console.print(f"[dim]   {i:>3}. {url}[/dim]")

    return urls


# ── Standalone usage ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result   = get_urls_from_latest_plan(plan_path=path_arg)
    print(f"\nTotal URLs: {len(result)}")