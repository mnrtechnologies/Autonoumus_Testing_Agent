"""
TWO-TIER PLANNING ARCHITECTURE WITH KNOWLEDGE GRAPH + COMPREHENSIVE LOGGING
Discovery First, Execution Second — with Path-Aware Testing

ENHANCED FEATURES:
- Complete interactive element handling (toggles, radios, checkboxes, forms)
- Depth-first exploration (complete each section before moving to next)
- Form completion with submit button handling
- Wait for all actions to complete before backtracking
- Complete logging of all actions to file
- Plan versioning (saves every update to main action plan)
- Separate files for assumption plan and main action plan
- Timestamped log entries for debugging
"""

import asyncio
import json
import hashlib
import os
import base64
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urlparse
from datetime import datetime
from io import BytesIO
import logging

from playwright.async_api import async_playwright, Page
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.tree import Tree

from openai import OpenAI

console = Console()


# =============================================================================
# NEW: COMPREHENSIVE LOGGER CLASS
# =============================================================================

class CrawlerLogger:
    """
    Handles all logging operations:
    - Action logs (every click, navigation, detection)
    - Plan versioning (saves every update to plans)
    - Error logs
    - Statistics tracking
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)

        # Create timestamped session directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.output_dir / f"session_{timestamp}"
        self.session_dir.mkdir(exist_ok=True)

        # Initialize log files
        self.main_log_file = self.session_dir / "crawler_log.txt"
        self.action_log_file = self.session_dir / "actions_log.jsonl"  # JSON Lines format
        self.error_log_file = self.session_dir / "errors_log.txt"

        # Plan tracking
        self.plans_dir = self.session_dir / "plans"
        self.plans_dir.mkdir(exist_ok=True)
        self.main_action_plan_versions = []
        self.assumption_plan_saved = False

        # Initialize action counter
        self.action_counter = 0

        # Set up Python logging
        self._setup_python_logging()

        self.log_info("=" * 80)
        self.log_info(f"CRAWLER SESSION STARTED: {timestamp}")
        self.log_info("=" * 80)

    def _setup_python_logging(self):
        """Configure Python's logging module for error tracking"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.error_log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def log_info(self, message: str):
        """Log informational message to main log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {message}\n"
        with open(self.main_log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)

    def log_action(self, action_type: str, details: Dict):
        """Log structured action data in JSON Lines format"""
        self.action_counter += 1
        action_entry = {
            "action_id": self.action_counter,
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "details": details
        }

        with open(self.action_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(action_entry, ensure_ascii=False) + '\n')

        # Also log to main log for easy reading
        self.log_info(f"ACTION #{self.action_counter}: {action_type} - {json.dumps(details, ensure_ascii=False)}")

    def log_error(self, error_type: str, error_message: str, context: Dict = None):
        """Log error with context"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        error_entry = f"\n[{timestamp}] ERROR: {error_type}\n"
        error_entry += f"Message: {error_message}\n"
        if context:
            error_entry += f"Context: {json.dumps(context, indent=2, ensure_ascii=False)}\n"
        error_entry += "-" * 80 + "\n"

        with open(self.error_log_file, 'a', encoding='utf-8') as f:
            f.write(error_entry)

        self.logger.error(f"{error_type}: {error_message}")

    def save_assumption_plan(self, plan: List[Dict]):
        """Save assumption plan (only once)"""
        if not self.assumption_plan_saved:
            plan_file = self.plans_dir / "assumption_plan.json"
            with open(plan_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "plan_type": "assumption_discovery",
                    "created_at": datetime.now().isoformat(),
                    "total_steps": len(plan),
                    "steps": plan
                }, f, indent=2, ensure_ascii=False)

            self.log_info(f"Saved assumption plan: {len(plan)} steps")
            self.assumption_plan_saved = True

    def save_main_action_plan_version(self, plan: List[Dict], reason: str = "initial"):
        """Save a new version of the main action plan"""
        version_num = len(self.main_action_plan_versions) + 1
        self.main_action_plan_versions.append({
            "version": version_num,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "step_count": len(plan)
        })

        # Save this version
        version_file = self.plans_dir / f"main_action_plan_v{version_num}.json"
        with open(version_file, 'w', encoding='utf-8') as f:
            json.dump({
                "version": version_num,
                "reason": reason,
                "created_at": datetime.now().isoformat(),
                "total_steps": len(plan),
                "steps": plan
            }, f, indent=2, ensure_ascii=False)

        self.log_info(f"Saved main action plan version {version_num}: {reason} ({len(plan)} steps)")

        # Also save version history
        history_file = self.plans_dir / "plan_version_history.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump({
                "total_versions": len(self.main_action_plan_versions),
                "versions": self.main_action_plan_versions
            }, f, indent=2, ensure_ascii=False)

    def log_vision_analysis(self, url: str, analysis: Dict):
        """Log GPT-4 Vision analysis results"""
        self.log_action("vision_analysis", {
            "url": url,
            "page_type": analysis.get("page_type"),
            "containers_found": len(analysis.get("containers", [])),
            "features_found": len(analysis.get("features", [])),
            "analysis": analysis
        })

    def log_container_expansion(self, container: Dict, success: bool, changes: List[Dict] = None):
        """Log container expansion attempt"""
        self.log_action("container_expansion", {
            "container_id": container.get("semantic_id"),
            "container_text": container.get("text"),
            "success": success,
            "dom_changes": len(changes) if changes else 0,
            "change_details": changes[:5] if changes else []  # First 5 changes
        })

    def log_feature_test(self, feature: Dict, success: bool, navigation_occurred: bool = False, new_url: str = None):
        """Log feature testing attempt"""
        self.log_action("feature_test", {
            "feature_id": feature.get("semantic_id"),
            "feature_text": feature.get("text"),
            "feature_type": feature.get("type"),
            "success": success,
            "navigation_occurred": navigation_occurred,
            "new_url": new_url
        })

    def log_path_resolution(self, feature_id: str, feature_text: str, path_steps: int, restoration_needed: int, success: bool):
        """Log path resolution before feature click"""
        self.log_action("path_resolution", {
            "feature_id": feature_id,
            "feature_text": feature_text,
            "total_path_steps": path_steps,
            "restoration_steps_needed": restoration_needed,
            "success": success
        })

    def log_state_change(self, from_url: str, to_url: str, breadcrumb: str):
        """Log navigation state change"""
        self.log_action("state_change", {
            "from_url": from_url,
            "to_url": to_url,
            "breadcrumb": breadcrumb
        })

    def save_final_summary(self, stats: Dict, kg_summary: Dict):
        """Save final exploration summary"""
        summary_file = self.session_dir / "exploration_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump({
                "session_ended": datetime.now().isoformat(),
                "statistics": stats,
                "knowledge_graph_summary": kg_summary,
                "total_actions": self.action_counter,
                "plan_versions": len(self.main_action_plan_versions)
            }, f, indent=2, ensure_ascii=False)

        self.log_info("=" * 80)
        self.log_info("SESSION COMPLETED")
        self.log_info(f"Total actions logged: {self.action_counter}")
        self.log_info(f"Plan versions saved: {len(self.main_action_plan_versions)}")
        self.log_info("=" * 80)


# =============================================================================
# LAYER 1: GPT-4 Vision Analyzer (with logging)
# =============================================================================

class GPTVisionAnalyzer:
    def __init__(self, openai_client: OpenAI, logger: CrawlerLogger):
        self.client = openai_client
        self.analysis_cache = {}
        self.logger = logger

    async def analyze_page(self, page: Page, url: str) -> Dict:
        console.print("[cyan]📸 VISION: Taking screenshot and analyzing with GPT-4...[/cyan]")
        self.logger.log_info(f"Starting vision analysis for: {url}")

        screenshot_bytes = await page.screenshot(full_page=False, type='png')
        screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode('utf-8')

        screenshot_hash = hashlib.md5(screenshot_bytes).hexdigest()[:8]
        if screenshot_hash in self.analysis_cache:
            console.print("[yellow]   Using cached Vision analysis[/yellow]")
            self.logger.log_info("Using cached vision analysis")
            return self.analysis_cache[screenshot_hash]

        prompt = """You are analyzing a web application to help an automated testing agent explore it systematically.

**YOUR MISSION:**
Identify ALL interactive elements and classify them into two categories:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 CATEGORY 1: CONTAINERS (Things that HIDE other things)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A CONTAINER is any UI element that:
- Has a visual expansion indicator (>, ▶, ▼, ›, arrow icon, chevron)
- Shows/hides child elements when clicked
- Contains nested menu items that aren't currently visible

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 CATEGORY 2: FEATURES (Things that DO actions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A FEATURE is any UI element that:
- Performs a direct action (Save, Delete, Export, Download)
- Navigates to a page (Links that go somewhere)
- Accepts user input (Search boxes, form fields)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 CRITICAL RULE: CHARACTER-PERFECT TRANSCRIPTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**WHY THIS MATTERS:**
The testing agent will search the DOM using EXACT text matching. Even one wrong
character will cause the element detection to fail completely.

**TRANSCRIPTION RULES:**
1. Copy EVERY character exactly as it appears (including spaces, punctuation)
2. Preserve capitalization EXACTLY ("Sedekah" ≠ "sedekah")
3. Do NOT fix typos you see on screen - copy them as-is
4. Do NOT translate to English (keep original language)
5. Do NOT paraphrase or use similar words
6. Include diacritics/accents if present (é, ñ, etc.)

**EXAMPLES:**

✅ CORRECT TRANSCRIPTION:
  Screen shows: "Lihat semua"
  You write:    "Lihat semua"

❌ WRONG - Similar meaning but different text:
  Screen shows: "Lihat semua"
  You write:    "Lihat selengkapnya"  ← Different words!

❌ WRONG - Typo introduced:
  Screen shows: "Sedekah Sekarang"
  You write:    "Sedehak Sekarang"  ← Missing 'a'!

❌ WRONG - Translated:
  Screen shows: "Sedekah Sekarang"
  You write:    "Donate Now"  ← Wrong language!

❌ WRONG - Capitalization changed:
  Screen shows: "Buat Acara"
  You write:    "buat acara"  ← Wrong capitalization!

**DOUBLE-CHECK EACH TEXT FIELD BEFORE SUBMITTING YOUR RESPONSE**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return JSON in this EXACT format:

{
  "page_type": "dashboard|list|form|settings",
  "layout": { "has_sidebar": true|false, "has_header": true|false },
  "containers": [
    {
      "text": "CHARACTER-PERFECT copy from screen - verify each letter!",
      "type": "expandable_menu",
      "state": "collapsed|expanded",
      "location": "sidebar|header|main",
      "expected_children": [],
      "discovery_priority": 9,
      "expansion_indicator": "describe what you see"
    }
  ],
  "features": [
    {
      "text": "CHARACTER-PERFECT copy from screen - verify each letter!",
      "type": "button|link|form_field",
      "location": "sidebar|header|main",
      "test_priority": 1,
      "expected_behavior": "what happens when clicked"
    }
  ],
  "discovery_strategy": {
    "recommended_order": [],
    "reasoning": "why this order makes sense"
  }
}

**BEFORE RETURNING YOUR RESPONSE:**
1. Re-read each "text" field
2. Compare it character-by-character with what you see on screen
3. Verify capitalization matches exactly
4. Confirm no translation occurred

Return valid JSON only."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
                    ]
                }],
                max_tokens=4000
            )

            vision_text = response.choices[0].message.content.strip()

            console.print("\n" + "="*80)
            console.print("RAW GPT-4 VISION RESPONSE:")
            console.print(vision_text)
            console.print("="*80 + "\n")

            self.logger.log_info("Raw GPT-4 Vision Response:")
            self.logger.log_info(vision_text)

            if vision_text.startswith('```'):
                vision_text = vision_text.split('\n', 1)[1].rsplit('\n', 1)[0]
                if vision_text.startswith('json'):
                    vision_text = vision_text[4:].strip()

            analysis = json.loads(vision_text)
            self.analysis_cache[screenshot_hash] = analysis

            # Log the analysis
            self.logger.log_vision_analysis(url, analysis)

            console.print(f"[green]   ✅ Vision analysis complete[/green]")
            console.print(f"[yellow]   Page Type: {analysis.get('page_type', 'unknown')}[/yellow]")
            console.print(f"[yellow]   Containers found: {len(analysis.get('containers', []))}[/yellow]")
            console.print(f"[yellow]   Features found: {len(analysis.get('features', []))}[/yellow]")

            return analysis

        except Exception as e:
            console.print(f"[red]   ❌ Vision analysis failed: {e}[/red]")
            self.logger.log_error("vision_analysis_failed", str(e), {"url": url})
            import traceback
            console.print(f"[red]   {traceback.format_exc()}[/red]")
            return {
                "page_type": "unknown",
                "layout": {},
                "containers": [],
                "features": [],
                "discovery_strategy": {"recommended_order": [], "reasoning": "Vision failed"}
            }


# =============================================================================
# LAYER 2: KNOWLEDGE GRAPH (with logging)
# =============================================================================

class KnowledgeGraph:
    def __init__(self, logger: CrawlerLogger):
        self.nodes: Dict[str, Dict] = {}
        self.edges: List[Dict] = []
        self.paths: Dict[str, List[Dict]] = {}
        self.graph_file = Path('output') / 'knowledge_graph.json'
        self.logger = logger

    def add_node(
        self,
        semantic_id: str,
        text: str,
        node_type: str,
        location: str,
        anchor_url: str,
        element_type: str,
        confidence: str = 'vision_only'
    ):
        if semantic_id not in self.nodes:
            self.nodes[semantic_id] = {
                'semantic_id': semantic_id,
                'text': text,
                'node_type': node_type,
                'location': location,
                'anchor_url': anchor_url,
                'element_type': element_type,
                'confidence': confidence,
                'discovered_at': datetime.now().isoformat()
            }
            console.print(f"[dim]   📍 KG Node added: {semantic_id} ({confidence})[/dim]")
            self.logger.log_action("kg_node_added", {
                "semantic_id": semantic_id,
                "text": text,
                "node_type": node_type,
                "confidence": confidence
            })

    def upgrade_confidence(self, semantic_id: str):
        if semantic_id in self.nodes:
            self.nodes[semantic_id]['confidence'] = 'dom_confirmed'
            self.logger.log_action("kg_confidence_upgraded", {
                "semantic_id": semantic_id,
                "new_confidence": "dom_confirmed"
            })

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        anchor_url: str,
        confidence: str = 'vision_only'
    ):
        for existing in self.edges:
            if existing['from_id'] == from_id and existing['to_id'] == to_id:
                return

        edge = {
            'from_id': from_id,
            'to_id': to_id,
            'edge_type': edge_type,
            'anchor_url': anchor_url,
            'confidence': confidence
        }
        self.edges.append(edge)
        console.print(f"[dim]   🔗 KG Edge: {from_id} --[{edge_type}]--> {to_id}[/dim]")
        self.logger.log_action("kg_edge_added", {
            "from_id": from_id,
            "to_id": to_id,
            "edge_type": edge_type,
            "confidence": confidence
        })

    def build_path_for_feature(
        self,
        feature_id: str,
        parent_container_id: Optional[str],
    ):
        if feature_id in self.paths:
            console.print(f"[dim]   ⏭️  Path already exists for {feature_id}[/dim]")
            return

        node = self.nodes.get(feature_id)
        if not node:
            console.print(f"[red]   ❌ Cannot build path: node {feature_id} not found[/red]")
            self.logger.log_error("path_build_failed", f"Node {feature_id} not found", {"feature_id": feature_id})
            return

        anchor_url = node.get('anchor_url')
        if not anchor_url:
            console.print(f"[red]   ❌ Node {feature_id} missing anchor_url[/red]")
            self.logger.log_error("path_build_failed", f"Node {feature_id} missing anchor_url", {"feature_id": feature_id})
            return

        steps = []

        steps.append({
            'step_type': 'ensure_url',
            'target_url': anchor_url,
            'description': f'Ensure browser is on {anchor_url}'
        })

        if parent_container_id:
            parent_path = self.paths.get(parent_container_id, [])
            for step in parent_path:
                if step['step_type'] != 'ensure_url':
                    steps.append(step)

            parent_node = self.nodes.get(parent_container_id, {})
            steps.append({
                'step_type': 'expand_container',
                'container_id': parent_container_id,
                'container_text': parent_node.get('text', ''),
                'container_location': parent_node.get('location', ''),
                'anchor_url': anchor_url,
                'description': f"Expand '{parent_node.get('text', '')}'"
            })

        self.paths[feature_id] = steps
        console.print(f"[dim]   🗺️  Path created for {feature_id}: {len(steps)} steps[/dim]")

        self.logger.log_action("kg_path_created", {
            "feature_id": feature_id,
            "path_length": len(steps),
            "has_parent": parent_container_id is not None
        })

    def get_path(self, feature_id: str) -> List[Dict]:
        return self.paths.get(feature_id, [])

    def get_parent_container_id(self, feature_id: str) -> Optional[str]:
        for edge in self.edges:
            if edge['to_id'] == feature_id and edge['edge_type'] == 'dom_action':
                return edge['from_id']
        return None

    def save(self):
        self.graph_file.parent.mkdir(exist_ok=True)
        data = {
            'nodes': self.nodes,
            'edges': self.edges,
            'paths': self.paths,
            'saved_at': datetime.now().isoformat()
        }
        with open(self.graph_file, 'w') as f:
            json.dump(data, f, indent=2)
        self.logger.log_info(f"Knowledge graph saved: {len(self.nodes)} nodes, {len(self.edges)} edges")

    def load(self):
        if self.graph_file.exists():
            with open(self.graph_file, 'r') as f:
                data = json.load(f)
            self.nodes = data.get('nodes', {})
            self.edges = data.get('edges', [])
            self.paths = data.get('paths', {})
            console.print(f"[green]   ✅ Knowledge graph loaded: {len(self.nodes)} nodes, {len(self.edges)} edges[/green]")
            self.logger.log_info(f"Knowledge graph loaded: {len(self.nodes)} nodes, {len(self.edges)} edges")


# =============================================================================
# LAYER 3: GRAPH BUILDER (with logging)
# =============================================================================

class GraphBuilder:
    def __init__(self, knowledge_graph: KnowledgeGraph, logger: CrawlerLogger):
        self.kg = knowledge_graph
        self.logger = logger

    async def register_container(
        self,
        page: Page,
        container: Dict,
        current_url: str,
        parent_container_id: Optional[str] = None
    ):
        container_id = container['semantic_id']

        self.kg.add_node(
            semantic_id=container_id,
            text=container['text'],
            node_type='container',
            location=container.get('location', 'unknown'),
            anchor_url=current_url,
            element_type=container.get('type', 'expandable_menu'),
            confidence='vision_only'
        )

        if parent_container_id:
            self.kg.add_edge(
                from_id=parent_container_id,
                to_id=container_id,
                edge_type='dom_action',
                anchor_url=current_url,
                confidence='vision_only'
            )

        self.kg.build_path_for_feature(
            feature_id=container_id,
            parent_container_id=parent_container_id
        )

    async def register_discovered_feature(
        self,
        page: Page,
        feature: Dict,
        parent_container: Dict,
        current_url: str
    ):
        feature_id = feature['semantic_id']
        container_id = parent_container['semantic_id']

        self.kg.add_node(
            semantic_id=feature_id,
            text=feature['text'],
            node_type='feature',
            location=feature.get('location', 'unknown'),
            anchor_url=current_url,
            element_type=feature.get('type', 'unknown'),
            confidence='dom_confirmed'
        )

        is_dom_child = await self._check_dom_ancestry(
            page,
            parent_text=parent_container['text'],
            child_text=feature['text']
        )

        confidence = 'dom_confirmed' if is_dom_child else 'vision_only'

        if is_dom_child:
            self.kg.upgrade_confidence(feature_id)
            console.print(f"[green]   ✅ DOM confirmed: '{feature['text']}' is child of '{parent_container['text']}'[/green]")
            self.logger.log_action("dom_ancestry_confirmed", {
                "parent": parent_container['text'],
                "child": feature['text']
            })
        else:
            console.print(f"[yellow]   ⚠️  Vision only: '{feature['text']}' (could not confirm DOM ancestry)[/yellow]")
            self.logger.log_action("dom_ancestry_failed", {
                "parent": parent_container['text'],
                "child": feature['text']
            })

        self.kg.add_edge(
            from_id=container_id,
            to_id=feature_id,
            edge_type='dom_action',
            anchor_url=current_url,
            confidence='dom_confirmed'
        )

        self.kg.build_path_for_feature(
            feature_id=feature_id,
            parent_container_id=container_id
        )
        return True

    async def register_top_level_feature(
        self,
        page: Page,
        feature: Dict,
        current_url: str
    ):
        feature_id = feature['semantic_id']

        self.kg.add_node(
            semantic_id=feature_id,
            text=feature['text'],
            node_type='feature',
            location=feature.get('location', 'unknown'),
            anchor_url=current_url,
            element_type=feature.get('type', 'unknown'),
            confidence='dom_confirmed'
        )

        self.kg.build_path_for_feature(
            feature_id=feature_id,
            parent_container_id=None
        )

    async def _check_dom_ancestry(
        self,
        page: Page,
        parent_text: str,
        child_text: str
    ) -> bool:
        try:
            result = await page.evaluate("""
                ({parentText, childText}) => {
                    const allElements = Array.from(document.querySelectorAll('*'));

                    const parentEl = allElements.find(el => {
                        const directText = Array.from(el.childNodes)
                            .filter(n => n.nodeType === Node.TEXT_NODE)
                            .map(n => n.textContent.trim())
                            .join('');
                        return directText.includes(parentText) ||
                            el.textContent.trim().startsWith(parentText);
                    });

                    if (!parentEl) return false;

                    const containerEl = parentEl.closest('li, [class*="menu-item"], [class*="nav-item"]')
                                    || parentEl.parentElement;

                    if (!containerEl) return false;

                    const childEl = Array.from(containerEl.querySelectorAll('*'))
                        .find(el => {
                            const text = el.textContent?.trim() || '';
                            return text.includes(childText) || text.startsWith(childText);
                        });

                    if (!childEl) return false;

                    const childLocation = childEl.closest('[class*="sidebar"]') ? 'sidebar' :
                                        childEl.closest('[class*="header"]') ? 'header' :
                                        childEl.closest('main, [class*="content"]') ? 'main' : 'unknown';

                    const parentLocation = containerEl.closest('[class*="sidebar"]') ? 'sidebar' :
                                        containerEl.closest('[class*="header"]') ? 'header' : 'unknown';

                    if (childLocation === 'main' && parentLocation === 'sidebar') {
                        return false;
                    }

                    const isExpanded = parentEl.getAttribute('aria-expanded') === 'true';
                    const hasVisibleChildren = containerEl.querySelector('ul, [class*="submenu"], [class*="dropdown"]');

                    if (hasVisibleChildren) {
                        const collapsibleSection = childEl.closest('ul, [class*="submenu"], [class*="dropdown"]');
                        if (!collapsibleSection) return false;

                        if (!containerEl.contains(collapsibleSection)) return false;
                    }

                    return true;
                }
            """, {'parentText': parent_text, 'childText': child_text})

            return bool(result)

        except Exception as e:
            console.print(f"[dim]   DOM ancestry check failed: {e}[/dim]")
            self.logger.log_error("dom_ancestry_check_exception", str(e), {
                "parent_text": parent_text,
                "child_text": child_text
            })
            return False


# =============================================================================
# LAYER 4: DOM STATE VALIDATOR (with logging)
# =============================================================================

class DOMStateValidator:
    def __init__(self, logger: CrawlerLogger):
        self.logger = logger

    async def is_on_correct_url(self, page: Page, target_url: str) -> bool:
        current = page.url
        current_path = urlparse(current).path.rstrip('/')
        target_path = urlparse(target_url).path.rstrip('/')
        result = current_path == target_path

        self.logger.log_action("url_check", {
            "current_url": current,
            "target_url": target_url,
            "match": result
        })

        return result

    async def is_container_expanded(
        self,
        page: Page,
        container_text: str,
        container_location: str
    ) -> bool:
        try:
            result = await page.evaluate("""
                ({text, location}) => {
                    function findInLocation(text, location) {
                        let scope = document;
                        if (location === 'sidebar') {
                            scope = document.querySelector('aside, nav, [class*="sidebar"]') || document;
                        } else if (location === 'header') {
                            scope = document.querySelector('header') || document;
                        }

                        return Array.from(scope.querySelectorAll('*')).find(el => {
                            const t = el.textContent?.trim() || '';
                            return t === text || t.startsWith(text);
                        });
                    }

                    const el = findInLocation(text, location);
                    if (!el) return false;

                    if (el.getAttribute('aria-expanded') === 'true') return true;

                    const parent = el.closest('li, [class*="menu-item"]');
                    if (parent) {
                        const children = parent.querySelectorAll('ul li, [class*="submenu"] li, [class*="sub-item"]');
                        const visibleChildren = Array.from(children).filter(c => {
                            const rect = c.getBoundingClientRect();
                            return rect.height > 0 && rect.width > 0;
                        });
                        return visibleChildren.length > 0;
                    }

                    return false;
                }
            """, {'text': container_text, 'location': container_location})

            self.logger.log_action("container_expansion_check", {
                "container_text": container_text,
                "location": container_location,
                "is_expanded": bool(result)
            })

            return bool(result)

        except Exception as e:
            console.print(f"[dim]   DOM state check failed for '{container_text}': {e}[/dim]")
            self.logger.log_error("dom_state_check_failed", str(e), {
                "container_text": container_text,
                "location": container_location
            })
            return False


# =============================================================================
# LAYER 5: PATH RESOLVER (with logging)
# =============================================================================

class PathResolver:
    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        dom_validator: DOMStateValidator,
        semantic_selector,
        logger: CrawlerLogger
    ):
        self.kg = knowledge_graph
        self.validator = dom_validator
        self.selector = semantic_selector
        self.logger = logger

    async def prepare_for_click(self, page: Page, feature_id: str, feature: Dict) -> bool:
        console.print(f"\n[bold cyan]🗺️  PATH RESOLVER: Preparing to reach '{feature['text']}'[/bold cyan]")
        self.logger.log_info(f"PATH RESOLUTION START for '{feature['text']}'")

        path = self.kg.get_path(feature_id)

        if not path:
            console.print(f"[yellow]   No path in graph for {feature_id} — attempting direct click[/yellow]")
            self.logger.log_path_resolution(feature_id, feature['text'], 0, 0, True)
            return True

        console.print(f"[cyan]   Path has {len(path)} steps[/cyan]")

        restoration_queue = []

        for step in path:
            step_type = step['step_type']

            if step_type == 'ensure_url':
                on_correct_url = await self.validator.is_on_correct_url(
                    page, step['target_url']
                )
                if not on_correct_url:
                    console.print(f"[yellow]   ⚠️  Need to navigate to: {step['target_url']}[/yellow]")
                    restoration_queue.append(step)
                else:
                    console.print(f"[dim]   ✓ Already on correct URL[/dim]")

            elif step_type == 'expand_container':
                is_expanded = await self.validator.is_container_expanded(
                    page,
                    step['container_text'],
                    step.get('container_location', 'sidebar')
                )
                if not is_expanded:
                    console.print(f"[yellow]   ⚠️  Need to expand: '{step['container_text']}'[/yellow]")
                    restoration_queue.append(step)
                else:
                    console.print(f"[dim]   ✓ Already expanded: '{step['container_text']}'[/dim]")

        if not restoration_queue:
            console.print(f"[green]   ✅ All prerequisites satisfied — ready to click[/green]")
            self.logger.log_path_resolution(feature_id, feature['text'], len(path), 0, True)
            return True

        console.print(f"[cyan]   Executing {len(restoration_queue)} restoration steps...[/cyan]")
        success = await self._execute_restoration(page, restoration_queue)

        if success:
            console.print(f"[green]   ✅ Restoration complete — ready to click[/green]")
            self.logger.log_path_resolution(feature_id, feature['text'], len(path), len(restoration_queue), True)
        else:
            console.print(f"[red]   ❌ Restoration failed[/red]")
            self.logger.log_path_resolution(feature_id, feature['text'], len(path), len(restoration_queue), False)

        return success

    async def _execute_restoration(self, page: Page, queue: List[Dict]) -> bool:
        for step in queue:
            step_type = step['step_type']

            if step_type == 'ensure_url':
                target_url = step['target_url']
                console.print(f"[cyan]   🌐 Navigating to: {target_url}[/cyan]")
                self.logger.log_action("restoration_navigate", {"target_url": target_url})

                try:
                    await page.goto(target_url, wait_until='networkidle', timeout=30000)
                    await asyncio.sleep(2)
                    console.print(f"[green]   ✅ Navigated successfully[/green]")
                except Exception as e:
                    console.print(f"[red]   ❌ Navigation failed: {e}[/red]")
                    self.logger.log_error("restoration_navigation_failed", str(e), {"target_url": target_url})
                    return False

            elif step_type == 'expand_container':
                container_text = step['container_text']
                container_location = step.get('container_location', 'sidebar')
                console.print(f"[cyan]   🔓 Expanding: '{container_text}'[/cyan]")
                self.logger.log_action("restoration_expand", {
                    "container_text": container_text,
                    "location": container_location
                })

                container_component = {
                    'text': container_text,
                    'location': container_location,
                    'css_selector': f"text={container_text}",
                    'xpath': None
                }

                clicked = await self.selector.click_element(page, container_component)

                if not clicked:
                    console.print(f"[red]   ❌ Could not expand '{container_text}'[/red]")
                    self.logger.log_error("restoration_expand_failed", f"Could not expand '{container_text}'", {
                        "container_text": container_text
                    })
                    return False

                await asyncio.sleep(1.5)

                is_now_expanded = await self.validator.is_container_expanded(
                    page, container_text, container_location
                )
                if not is_now_expanded:
                    console.print(f"[yellow]   ⚠️  '{container_text}' may not have expanded, continuing anyway[/yellow]")

        return True


# =============================================================================
# LAYER 6: Component Detector (with logging)
# =============================================================================

class ComponentDetector:
    def __init__(self, logger: CrawlerLogger):
        self.logger = logger

    async def detect_containers(self, page: Page, vision_containers: List[Dict]) -> List[Dict]:
        console.print("[cyan]🔍 CONTAINER DETECTION: Mapping containers to DOM...[/cyan]")
        self.logger.log_info("Starting container detection")

        containers = []
        container_id = 1

        for container_data in vision_containers:
            text = container_data.get('text', '')
            container_type = container_data.get('type', 'unknown')
            location = container_data.get('location', 'unknown')

            if not text:
                continue

            dom_element = await self._find_element_by_semantics(page, text, location, container_type)

            if dom_element:
                container = {
                    'container_id': container_id,
                    'semantic_id': self._create_semantic_id(text, location, container_type),
                    'text': text,
                    'type': container_type,
                    'location': location,
                    'state': container_data.get('state', 'unknown'),
                    'expected_children': container_data.get('expected_children', []),
                    'discovery_priority': container_data.get('discovery_priority', 5),
                    'xpath': dom_element['xpath'],
                    'css_selector': dom_element['css_selector'],
                    'vision_data': container_data
                }
                containers.append(container)
                self.logger.log_action("container_detected", {
                    "container_id": container_id,
                    "text": text,
                    "type": container_type,
                    "location": location
                })
                container_id += 1

        console.print(f"[green]   ✅ Detected {len(containers)} containers[/green]")
        self.logger.log_info(f"Detected {len(containers)} containers")
        return containers

    async def detect_features(self, page: Page, vision_features: List[Dict]) -> List[Dict]:
        console.print("[cyan]🔍 FEATURE DETECTION: Mapping features to DOM...[/cyan]")
        self.logger.log_info("Starting feature detection")

        features = []
        feature_id = 1

        for feature_data in vision_features:
            text = feature_data.get('text', '')
            feature_type = feature_data.get('type', 'unknown')
            location = feature_data.get('location', 'unknown')

            if not text:
                continue

            dom_element = await self._find_element_by_semantics(page, text, location, feature_type)

            if dom_element:
                feature = {
                    'feature_id': feature_id,
                    'semantic_id': self._create_semantic_id(text, location, feature_type),
                    'text': text,
                    'type': feature_type,
                    'location': location,
                    'test_priority': feature_data.get('test_priority', 5),
                    'expected_behavior': feature_data.get('expected_behavior', ''),
                    'xpath': dom_element['xpath'],
                    'css_selector': dom_element['css_selector'],
                    'vision_data': feature_data
                }
                features.append(feature)
                self.logger.log_action("feature_detected", {
                    "feature_id": feature_id,
                    "text": text,
                    "type": feature_type,
                    "location": location
                })
                feature_id += 1

        console.print(f"[green]   ✅ Detected {len(features)} features[/green]")
        self.logger.log_info(f"Detected {len(features)} features")
        return features

    async def _find_element_by_semantics(self, page, text, location, elem_type) -> Optional[Dict]:
        console.print(f"[cyan]      🔎 Searching for: '{text}'[/cyan]")
        try:
            selectors_to_try = [f"text={text}", f"text=/{text}/i"]

            if location == 'sidebar':
                selectors_to_try.insert(0, f"aside >> text={text}")
                selectors_to_try.insert(0, f"nav >> text={text}")
            elif location == 'header':
                selectors_to_try.insert(0, f"header >> text={text}")

            for selector in selectors_to_try:
                try:
                    element = await page.wait_for_selector(selector, timeout=2000, state='visible')
                    if element:
                        console.print(f"[green]         ✅ Found with selector: {selector}[/green]")
                        return {
                            'found': True,
                            'xpath': f"//text()[contains(., '{text}')]/parent::*",
                            'css_selector': selector,
                            'actual_text': text
                        }
                except:
                    continue

            console.print(f"[red]         ❌ Not found[/red]")
            return None

        except Exception as e:
            console.print(f"[red]         Exception: {e}[/red]")
            return None

    def _create_semantic_id(self, text: str, location: str, elem_type: str) -> str:
        normalized = text.lower().replace(' ', '_').replace('-', '_')
        normalized = ''.join(c for c in normalized if c.isalnum() or c == '_')
        return f"{location}_{elem_type}_{normalized}"[:50]


# =============================================================================
# LAYER 7: DOM Observer (with logging)
# =============================================================================

class DOMObserver:
    def __init__(self, logger: CrawlerLogger):
        self.observer_injected = False
        self.logger = logger

    async def inject_observer(self, page: Page):
        if self.observer_injected:
            return

        console.print("[cyan]👁️ DOM OBSERVER: Injecting MutationObserver...[/cyan]")
        self.logger.log_info("Injecting DOM MutationObserver")

        await page.evaluate("""
            () => {
                window.__agentChangeLog = [];
                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        if (mutation.type === 'childList') {
                            mutation.addedNodes.forEach(node => {
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    window.__agentChangeLog.push({
                                        action: 'element_added',
                                        tag: node.tagName,
                                        text: node.textContent?.substring(0, 50),
                                        timestamp: Date.now()
                                    });
                                }
                            });
                            mutation.removedNodes.forEach(node => {
                                if (node.nodeType === Node.ELEMENT_NODE) {
                                    window.__agentChangeLog.push({
                                        action: 'element_removed',
                                        tag: node.tagName,
                                        timestamp: Date.now()
                                    });
                                }
                            });
                        } else if (mutation.type === 'attributes') {
                            window.__agentChangeLog.push({
                                action: 'attribute_changed',
                                attribute: mutation.attributeName,
                                old: mutation.oldValue,
                                new: mutation.target.getAttribute(mutation.attributeName),
                                timestamp: Date.now()
                            });
                        }
                    });
                });
                observer.observe(document.body, {
                    childList: true, attributes: true, attributeOldValue: true,
                    subtree: true, characterData: false
                });
                window.__agentObserver = observer;
            }
        """)

        self.observer_injected = True
        console.print("[green]   ✅ MutationObserver active[/green]")

    async def get_changes(self, page: Page) -> List[Dict]:
        try:
            return await page.evaluate("""
                () => {
                    const changes = window.__agentChangeLog || [];
                    window.__agentChangeLog = [];
                    return changes;
                }
            """)
        except:
            return []

    async def detect_change_type(self, changes: List[Dict]) -> str:
        if not changes:
            return "no_change"

        added = sum(1 for c in changes if c.get('action') == 'element_added')
        removed = sum(1 for c in changes if c.get('action') == 'element_removed')

        for change in changes:
            if change.get('tag') in ['DIALOG', 'DIV'] and change.get('action') == 'element_added':
                text = change.get('text', '').lower()
                if 'modal' in text or 'dialog' in text:
                    return "modal_opened"

        if added >= 3:
            return "menu_expanded"
        if removed >= 3:
            return "menu_collapsed"

        for change in changes:
            if change.get('attribute') == 'aria-expanded':
                return "element_expanded" if change.get('new') == 'true' else "element_collapsed"

        return "content_changed"

    def reset(self):
        self.observer_injected = False


# =============================================================================
# LAYER 8: Semantic Selector (with logging)
# =============================================================================

class SemanticSelector:
    def __init__(self, logger: CrawlerLogger):
        self.logger = logger

    async def click_element(self, page: Page, component: Dict) -> bool:
        text = component.get('text', '')
        location = component.get('location', '')

        console.print(f"[cyan]👆 SEMANTIC CLICK: '{text}' in {location}[/cyan]")
        self.logger.log_action("click_attempt", {
            "text": text,
            "location": location
        })

        try:
            if location == 'sidebar':
                selector = f"aside >> text={text}"
            elif location == 'header':
                selector = f"header >> text={text}"
            else:
                selector = f"text={text}"
            await page.click(selector, timeout=5000)
            console.print(f"[green]   ✅ Clicked using text selector[/green]")
            self.logger.log_action("click_success", {
                "text": text,
                "method": "text_selector"
            })
            return True
        except:
            pass

        try:
            css_sel = component.get('css_selector')
            if css_sel:
                await page.click(css_sel, timeout=3000)
                console.print(f"[green]   ✅ Clicked using CSS selector[/green]")
                self.logger.log_action("click_success", {
                    "text": text,
                    "method": "css_selector"
                })
                return True
        except:
            pass

        try:
            xpath = component.get('xpath')
            if xpath:
                await page.click(f"xpath={xpath}", timeout=3000)
                console.print(f"[green]   ✅ Clicked using XPath[/green]")
                self.logger.log_action("click_success", {
                    "text": text,
                    "method": "xpath"
                })
                return True
        except:
            pass

        try:
            clicked = await page.evaluate("""
                ({text, location}) => {
                    function isInLocation(el, loc) {
                        if (loc === 'sidebar') return el.closest('aside, nav, [class*="sidebar"]') !== null;
                        if (loc === 'header') return el.closest('header') !== null;
                        return true;
                    }
                    const allElements = Array.from(document.querySelectorAll('a, button, div, span, li'));
                    for (const el of allElements) {
                        const elText = el.textContent?.trim() || '';
                        if ((elText === text || elText.includes(text)) && isInLocation(el, location)) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }
            """, {'text': text, 'location': location})

            if clicked:
                console.print(f"[green]   ✅ Clicked using manual search[/green]")
                self.logger.log_action("click_success", {
                    "text": text,
                    "method": "manual_search"
                })
                return True
        except:
            pass

        console.print(f"[red]   ❌ Could not click element[/red]")
        self.logger.log_action("click_failed", {
            "text": text,
            "location": location
        })
        return False


# =============================================================================
# LAYER 9: Two-Tier Planner (with plan versioning)
# =============================================================================

class TwoTierPlanner:
    def __init__(self, logger: CrawlerLogger):
        self.assumption_plan = []
        self.main_action_plan = []
        self.logger = logger

    def create_assumption_plan(self, containers: List[Dict], vision_strategy: Dict) -> List[Dict]:
        console.print("[cyan]📋 TIER 1 PLANNER: Creating Assumption Plan (Discovery)...[/cyan]")
        self.logger.log_info("Creating assumption plan")

        plan = []
        step_id = 1

        containers_sorted = sorted(containers, key=lambda x: x.get('discovery_priority', 5), reverse=True)
        recommended_order = vision_strategy.get('recommended_order', [])

        if recommended_order:
            ordered = []
            for rec_name in recommended_order:
                for c in containers_sorted:
                    if rec_name.lower() in c['text'].lower() and c not in ordered:
                        ordered.append(c)
                        break
            for c in containers_sorted:
                if c not in ordered:
                    ordered.append(c)
            containers_sorted = ordered

        for container in containers_sorted:
            plan.append({
                'step_id': step_id,
                'tier': 'assumption',
                'action': 'discover',
                'hypothesis': f"{container['text']} contains hidden features",
                'container': container,
                'expected_children': container.get('expected_children', []),
                'priority': container.get('discovery_priority', 5),
                'reason': f"Expand {container['text']} to discover sub-items"
            })
            step_id += 1

        self.assumption_plan = plan
        console.print(f"[green]   ✅ Assumption Plan: {len(plan)} steps[/green]")

        # Save assumption plan
        self.logger.save_assumption_plan(plan)

        return plan

    def create_main_action_plan(self, features: List[Dict]) -> List[Dict]:
        console.print("[cyan]📋 TIER 2 PLANNER: Creating Main Action Plan (Testing)...[/cyan]")
        self.logger.log_info("Creating main action plan")

        plan = []
        step_id = 1

        for feature in sorted(features, key=lambda x: x.get('test_priority', 5), reverse=True):
            plan.append({
                'step_id': step_id,
                'tier': 'main_action',
                'action': 'test',
                'feature': feature,
                'feature_id': feature['semantic_id'],
                'test_type': self._determine_test_type(feature),
                'priority': feature.get('test_priority', 5),
                'reason': f"Test {feature['text']} functionality"
            })
            step_id += 1

        self.main_action_plan = plan
        console.print(f"[green]   ✅ Main Action Plan: {len(plan)} steps[/green]")

        # Save initial version of main action plan
        self.logger.save_main_action_plan_version(plan, "initial_creation")

        return plan

    def add_discovered_features_to_main_plan(self, new_features: List[Dict]):
        console.print(f"[cyan]➕ Adding {len(new_features)} discovered features to Main Action Plan...[/cyan]")
        self.logger.log_info(f"Adding {len(new_features)} discovered features to main action plan")

        next_id = len(self.main_action_plan) + 1

        for feature in new_features:
            self.main_action_plan.append({
                'step_id': next_id,
                'tier': 'main_action',
                'action': 'test',
                'feature': feature,
                'feature_id': feature['semantic_id'],
                'test_type': self._determine_test_type(feature),
                'priority': feature.get('test_priority', 5),
                'reason': f"Test {feature['text']} (discovered during exploration)",
                'discovered': True
            })
            next_id += 1

        self.main_action_plan.sort(key=lambda x: x.get('priority', 5), reverse=True)
        for idx, action in enumerate(self.main_action_plan, 1):
            action['step_id'] = idx

        console.print(f"[green]   ✅ Main Action Plan now has {len(self.main_action_plan)} steps[/green]")

        # Save updated version
        self.logger.save_main_action_plan_version(
            self.main_action_plan,
            f"added_{len(new_features)}_discovered_features"
        )

    def _determine_test_type(self, feature: Dict) -> str:
        t = feature.get('type', '').lower()
        if 'button' in t:    return 'functional_test'
        if 'link' in t:      return 'navigation_test'
        if 'form' in t or 'input' in t: return 'input_validation'
        return 'general_test'


# =============================================================================
# LAYER 10: State Manager (with logging)
# =============================================================================

class StateManager:
    def __init__(self, logger: CrawlerLogger):
        self.states = {}
        self.current_state_hash = None
        self._navigation_occurred = False
        self.logger = logger

    async def calculate_state_hash(self, page: Page) -> str:
        state_data = await page.evaluate("""
            () => ({
                url: window.location.pathname,
                title: document.title,
                main_headings: Array.from(document.querySelectorAll('h1, h2, h3'))
                    .map(h => h.textContent?.trim()).filter(t => t).join('|'),
                interactive_count: document.querySelectorAll('a, button').length
            })
        """)
        hash_string = f"{state_data['url']}::{state_data['main_headings']}::{state_data['interactive_count']}"
        return hashlib.sha256(hash_string.encode()).hexdigest()[:12]

    def is_state_visited(self, state_hash: str) -> bool:
        return state_hash in self.states

    def record_state(self, state_hash, url, breadcrumb, containers, features):
        if state_hash not in self.states:
            self.states[state_hash] = {
                'hash': state_hash,
                'url': url,
                'breadcrumb': breadcrumb,
                'container_count': len(containers),
                'feature_count': len(features),
                'visited_at': datetime.now().isoformat()
            }
            self.logger.log_action("state_recorded", {
                "state_hash": state_hash,
                "url": url,
                "breadcrumb": breadcrumb
            })

    def signal_navigation(self):
        self._navigation_occurred = True
        self.logger.log_action("navigation_signal", {"status": "navigation_occurred"})

    def acknowledge_navigation(self):
        self._navigation_occurred = False

    @property
    def navigation_occurred(self) -> bool:
        return self._navigation_occurred


# =============================================================================
# MAIN ORCHESTRATOR: TwoTierCrawler (with comprehensive logging)
# =============================================================================

class TwoTierCrawler:
    def __init__(
        self,
        base_url: str,
        auth_file: str = "auth.json",
        max_depth: int = 2,
        openai_api_key: Optional[str] = None
    ):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        self.max_depth = max_depth

        with open(auth_file, 'r') as f:
            self.auth_data = json.load(f)

        if openai_api_key:
            self.openai = OpenAI(api_key=openai_api_key)
        else:
            self.openai = OpenAI()

        # Initialize logger FIRST
        self.logger = CrawlerLogger(Path('output'))

        # Initialize all layers with logger
        self.vision             = GPTVisionAnalyzer(self.openai, self.logger)
        self.knowledge_graph    = KnowledgeGraph(self.logger)
        self.dom_validator      = DOMStateValidator(self.logger)
        self.graph_builder      = GraphBuilder(self.knowledge_graph, self.logger)
        self.component_detector = ComponentDetector(self.logger)
        self.dom_observer       = DOMObserver(self.logger)
        self.semantic_selector  = SemanticSelector(self.logger)
        self.planner            = TwoTierPlanner(self.logger)
        self.state_manager      = StateManager(self.logger)

        self.path_resolver = PathResolver(
            self.knowledge_graph,
            self.dom_validator,
            self.semantic_selector,
            self.logger
        )

        self.stats = {
            'pages_explored': 0,
            'containers_found': 0,
            'features_found': 0,
            'discovery_clicks': 0,
            'test_clicks': 0,
            'vision_calls': 0,
            'states_discovered': 0,
            'modals_detected': 0,
            'menus_expanded': 0,
            'features_tested': 0,
            'path_restorations': 0,
            'path_restoration_failures': 0,
            'forms_filled': 0,
            'interactive_elements_handled': 0
        }

        self.memory_file = Path('output') / 'two_tier_memory.json'
        self.exploration_memory = self._load_memory()

        self.knowledge_graph.load()

    def _load_memory(self) -> Dict:
        if self.memory_file.exists():
            with open(self.memory_file, 'r') as f:
                return json.load(f)
        return {
            'explored_containers': {},
            'explored_features': {},
            'discovered_features': {},
            'forms_completed': {}
        }

    def _save_memory(self):
        self.memory_file.parent.mkdir(exist_ok=True)
        self.exploration_memory['last_run'] = datetime.now().isoformat()
        with open(self.memory_file, 'w') as f:
            json.dump(self.exploration_memory, f, indent=2)
        self.knowledge_graph.save()

    async def run(self):
        console.print(Panel.fit(
            "[bold cyan]🔬 ENHANCED TWO-TIER CRAWLER + COMPLETE INTERACTION HANDLING[/bold cyan]\n"
            f"[yellow]Target: {self.base_url}[/yellow]\n"
            f"[yellow]Max Depth: {self.max_depth}[/yellow]\n"
            "[green]Phase 1: Discovery → builds Knowledge Graph[/green]\n"
            "[green]Phase 2: Testing  → PathResolver ensures state before each click[/green]\n"
            "[green]Phase 3: Forms → Complete all interactive elements before moving[/green]\n"
            f"[cyan]Session Directory: {self.logger.session_dir}[/cyan]",
            border_style="cyan"
        ))

        self.logger.log_info(f"Starting crawler for {self.base_url}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1200, 'height': 700})
            page = await context.new_page()

            try:
                await self._setup_auth(page, context)
                await self.dom_observer.inject_observer(page)
                await self._two_tier_exploration(page, depth=0, breadcrumb="Root")
            except Exception as e:
                self.logger.log_error("crawler_exception", str(e), {
                    "url": page.url,
                    "traceback": __import__('traceback').format_exc()
                })
                raise
            finally:
                await browser.close()

        self._show_results()
        self._save_exploration_data()

    async def _setup_auth(self, page: Page, context):
        console.print("\n[cyan]🔑 Setting up authentication...[/cyan]")
        self.logger.log_info("Setting up authentication")

        parsed = urlparse(self.base_url)
        homepage = f"{parsed.scheme}://{parsed.netloc}/"
        await page.goto(homepage)
        await page.wait_for_load_state('networkidle')

        for key, value in self.auth_data.get('local_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"window.localStorage.setItem('{key}', '{val}')")
                console.print(f"  ✓ localStorage: {key}")
                self.logger.log_action("auth_localStorage_set", {"key": key})
            except Exception as e:
                console.print(f"  ✗ localStorage: {key} — {e}")
                self.logger.log_error("auth_localStorage_failed", str(e), {"key": key})

        for key, value in self.auth_data.get('session_storage', {}).items():
            try:
                val = value if isinstance(value, str) else json.dumps(value)
                await page.evaluate(f"window.sessionStorage.setItem('{key}', '{val}')")
                console.print(f"  ✓ sessionStorage: {key}")
                self.logger.log_action("auth_sessionStorage_set", {"key": key})
            except Exception as e:
                console.print(f"  ✗ sessionStorage: {key}")
                self.logger.log_error("auth_sessionStorage_failed", str(e), {"key": key})

        cookies = self.auth_data.get('cookies', [])
        if cookies:
            try:
                await context.add_cookies(cookies)
                console.print(f"  ✓ Cookies: {len(cookies)} added")
                self.logger.log_action("auth_cookies_added", {"count": len(cookies)})
            except Exception as e:
                console.print(f"  ✗ Cookies: {e}")
                self.logger.log_error("auth_cookies_failed", str(e))

        console.print("[green]✅ Auth injected[/green]")

        await page.goto(self.base_url, wait_until='networkidle', timeout=30000)
        await asyncio.sleep(2)

        if 'login' in page.url.lower():
            raise Exception("Authentication failed — still on login page")

        console.print("[green]✅ Authenticated!\n[/green]")
        self.logger.log_info("Authentication successful")

    async def scroll_to_bottom(self, page: Page):
        """
        Scrolls the page to the bottom to trigger lazy-loading 
        and ensure all elements are rendered.
        """
        console.print("[cyan]📜 Scrolling to load all content...[/cyan]")
        await page.evaluate("""
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    let distance = 100;
                    let timer = setInterval(() => {
                        let scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if(totalHeight >= scrollHeight){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        """)
        await asyncio.sleep(2)

    async def handle_all_interactive_elements(self, page: Page, breadcrumb: str):
        """
        Comprehensive handling of ALL interactive elements including:
        - Text inputs, textareas
        - Radio buttons, checkboxes
        - Toggles/switches
        - Dropdowns/selects
        - Submit buttons (with completion wait)
        """
        console.print("[cyan]🎯 INTERACTIVE ELEMENTS: Comprehensive exploration...[/cyan]")
        self.logger.log_info("Starting comprehensive interactive element handling")

        # Check if we've already completed forms on this page
        page_hash = hashlib.md5(page.url.encode()).hexdigest()[:12]
        if page_hash in self.exploration_memory.get('forms_completed', {}):
            console.print("[yellow]   ⏭️  Forms already completed on this page[/yellow]")
            return

        try:
            # 1. Capture ALL interactive elements with their complete context
            elements_data = await page.evaluate("""() => {
                const allElements = [];
                
                // Text inputs and textareas
                document.querySelectorAll('input[type="text"], input[type="email"], input[type="password"], input[type="search"], input[type="tel"], input[type="url"], input[type="number"], textarea').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
                        const label = document.querySelector(`label[for="${el.id}"]`)?.textContent || 
                                    el.closest('label')?.textContent || 
                                    el.previousElementSibling?.textContent || 
                                    el.getAttribute('aria-label') || "";
                        allElements.push({
                            type: 'text_input',
                            id: el.id || el.name || `input_${allElements.length}`,
                            inputType: el.type,
                            tagName: el.tagName,
                            placeholder: el.placeholder,
                            label: label.trim(),
                            required: el.required
                        });
                    }
                });

                // Radio buttons (group them)
                const radioGroups = {};
                document.querySelectorAll('input[type="radio"]').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const groupName = el.name || 'unnamed_radio_group';
                        if (!radioGroups[groupName]) {
                            radioGroups[groupName] = {
                                type: 'radio_group',
                                name: groupName,
                                options: []
                            };
                        }
                        const label = document.querySelector(`label[for="${el.id}"]`)?.textContent || 
                                    el.closest('label')?.textContent || 
                                    el.nextElementSibling?.textContent || "";
                        radioGroups[groupName].options.push({
                            id: el.id,
                            value: el.value,
                            label: label.trim(),
                            checked: el.checked
                        });
                    }
                });
                Object.values(radioGroups).forEach(group => allElements.push(group));

                // Checkboxes
                document.querySelectorAll('input[type="checkbox"]:not(.toggle)').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const label = document.querySelector(`label[for="${el.id}"]`)?.textContent || 
                                    el.closest('label')?.textContent || 
                                    el.nextElementSibling?.textContent || "";
                        allElements.push({
                            type: 'checkbox',
                            id: el.id || el.name || `checkbox_${allElements.length}`,
                            label: label.trim(),
                            checked: el.checked,
                            value: el.value
                        });
                    }
                });

                // Toggles/Switches (common patterns)
                document.querySelectorAll('[role="switch"], .toggle, .switch, input[type="checkbox"].toggle').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const label = el.getAttribute('aria-label') || 
                                    el.closest('label')?.textContent || 
                                    el.previousElementSibling?.textContent || "";
                        allElements.push({
                            type: 'toggle',
                            id: el.id || `toggle_${allElements.length}`,
                            label: label.trim(),
                            checked: el.getAttribute('aria-checked') === 'true' || el.checked,
                            role: el.getAttribute('role')
                        });
                    }
                });

                // Dropdowns/Selects
                document.querySelectorAll('select').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const label = document.querySelector(`label[for="${el.id}"]`)?.textContent || 
                                    el.closest('label')?.textContent || 
                                    el.previousElementSibling?.textContent || "";
                        const options = Array.from(el.options).map(opt => ({
                            value: opt.value,
                            text: opt.text,
                            selected: opt.selected
                        }));
                        allElements.push({
                            type: 'select',
                            id: el.id || el.name || `select_${allElements.length}`,
                            label: label.trim(),
                            options: options,
                            multiple: el.multiple
                        });
                    }
                });

                // Submit/Action buttons
                document.querySelectorAll('button[type="submit"], input[type="submit"], button:not([type="button"]):not([type="reset"])').forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        allElements.push({
                            type: 'submit_button',
                            id: el.id || `submit_${allElements.length}`,
                            text: el.textContent?.trim() || el.value || 'Submit',
                            formAction: el.form?.action || ''
                        });
                    }
                });

                return allElements;
            }""")

            if not elements_data:
                console.print("[yellow]   No interactive elements found[/yellow]")
                self.exploration_memory.setdefault('forms_completed', {})[page_hash] = {
                    'completed_at': datetime.now().isoformat(),
                    'elements_count': 0
                }
                self._save_memory()
                return

            console.print(f"[green]   ✅ Found {len(elements_data)} interactive elements[/green]")
            self.logger.log_action("interactive_elements_found", {"count": len(elements_data)})
            self.stats['interactive_elements_handled'] += len(elements_data)

            # 2. Get LLM guidance for filling ALL elements
            fill_plan = await self._get_llm_fill_plan(elements_data, breadcrumb, page.url)

            # 3. Execute in order: inputs → radios → checkboxes → toggles → selects → submit
            await self._execute_text_inputs(page, elements_data, fill_plan)
            await asyncio.sleep(0.5)
            
            await self._execute_radio_buttons(page, elements_data, fill_plan)
            await asyncio.sleep(0.5)
            
            await self._execute_checkboxes(page, elements_data, fill_plan)
            await asyncio.sleep(0.5)
            
            await self._execute_toggles(page, elements_data, fill_plan)
            await asyncio.sleep(0.5)
            
            await self._execute_selects(page, elements_data, fill_plan)
            await asyncio.sleep(1)
            
            # 4. Click submit and WAIT for completion
            await self._execute_submit_buttons(page, elements_data)

            # Mark this page as completed
            self.exploration_memory.setdefault('forms_completed', {})[page_hash] = {
                'completed_at': datetime.now().isoformat(),
                'elements_count': len(elements_data),
                'breadcrumb': breadcrumb
            }
            self.stats['forms_filled'] += 1
            self._save_memory()

        except Exception as e:
            self.logger.log_error("interactive_elements_handling_failed", str(e))

    async def _get_llm_fill_plan(self, elements_data: List[Dict], breadcrumb: str, url: str) -> Dict:
        """Get LLM to create a comprehensive fill plan for all interactive elements"""
        prompt = f"""
        ROLE: Expert QA Test Data Engineer
        MISSION: Create complete test data for ALL interactive elements on this page.

        CONTEXT:
        - Page: {url}
        - Breadcrumb: {breadcrumb}
        - Elements: {json.dumps(elements_data, indent=2)}

        INSTRUCTIONS:

        1. TEXT INPUTS: Provide realistic, contextual data
           - Names: Use culturally appropriate full names
           - Emails: test_{{timestamp}}@example.com format
           - Phones: Valid format with country code
           - Searches: Context-appropriate terms
           - Numbers: Realistic values

        2. RADIO GROUPS: Select ONE option per group
           - Choose the most common/default option
           - Return as {{"group_name": "option_value"}}

        3. CHECKBOXES: Decide which to check
           - Check required/important ones
           - Return as {{"checkbox_id": true/false}}

        4. TOGGLES: Decide on/off state
           - Return as {{"toggle_id": true/false}}

        5. SELECTS: Choose appropriate option(s)
           - Single: Pick one value
           - Multiple: Pick 1-2 values as array
           - Return as {{"select_id": "value"}} or {{"select_id": ["val1", "val2"]}}

        OUTPUT FORMAT (JSON):
        {{
            "text_inputs": {{"field_id": "value"}},
            "radio_groups": {{"group_name": "selected_value"}},
            "checkboxes": {{"checkbox_id": true/false}},
            "toggles": {{"toggle_id": true/false}},
            "selects": {{"select_id": "value" or ["value1", "value2"]}}
        }}

        Return ONLY valid JSON, no markdown.
        """

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            self.logger.log_error("llm_fill_plan_failed", str(e))
            return {"text_inputs": {}, "radio_groups": {}, "checkboxes": {}, "toggles": {}, "selects": {}}

    async def _execute_text_inputs(self, page: Page, elements: List[Dict], fill_plan: Dict):
        """Fill all text inputs"""
        text_inputs = [e for e in elements if e['type'] == 'text_input']
        if not text_inputs:
            return

        console.print(f"[cyan]   📝 Filling {len(text_inputs)} text inputs...[/cyan]")
        
        for element in text_inputs:
            field_id = element['id']
            value = fill_plan.get('text_inputs', {}).get(field_id)
            
            if not value:
                continue
                
            try:
                selector = f"[id='{field_id}'], [name='{field_id}']"
                await page.locator(selector).first.fill(str(value))
                console.print(f"[green]      ✓ {element.get('label', field_id)}: {value}[/green]")
                self.logger.log_action("text_input_filled", {"field": field_id, "value": value})
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.log_error("text_input_fill_failed", str(e), {"field": field_id})

    async def _execute_radio_buttons(self, page: Page, elements: List[Dict], fill_plan: Dict):
        """Select radio buttons"""
        radio_groups = [e for e in elements if e['type'] == 'radio_group']
        if not radio_groups:
            return

        console.print(f"[cyan]   🔘 Selecting {len(radio_groups)} radio groups...[/cyan]")
        
        for group in radio_groups:
            group_name = group['name']
            selected_value = fill_plan.get('radio_groups', {}).get(group_name)
            
            if not selected_value:
                # Select first option by default
                selected_value = group['options'][0]['value'] if group['options'] else None
            
            if selected_value:
                try:
                    await page.check(f"input[name='{group_name}'][value='{selected_value}']")
                    console.print(f"[green]      ✓ {group_name}: {selected_value}[/green]")
                    self.logger.log_action("radio_selected", {"group": group_name, "value": selected_value})
                    await asyncio.sleep(0.3)
                except Exception as e:
                    self.logger.log_error("radio_selection_failed", str(e), {"group": group_name})

    async def _execute_checkboxes(self, page: Page, elements: List[Dict], fill_plan: Dict):
        """Check/uncheck checkboxes"""
        checkboxes = [e for e in elements if e['type'] == 'checkbox']
        if not checkboxes:
            return

        console.print(f"[cyan]   ☑️  Setting {len(checkboxes)} checkboxes...[/cyan]")
        
        for checkbox in checkboxes:
            checkbox_id = checkbox['id']
            should_check = fill_plan.get('checkboxes', {}).get(checkbox_id, False)
            
            try:
                selector = f"[id='{checkbox_id}'], [name='{checkbox_id}']"
                if should_check:
                    await page.check(selector)
                    console.print(f"[green]      ✓ Checked: {checkbox.get('label', checkbox_id)}[/green]")
                else:
                    await page.uncheck(selector)
                    console.print(f"[dim]      ○ Unchecked: {checkbox.get('label', checkbox_id)}[/dim]")
                
                self.logger.log_action("checkbox_set", {"id": checkbox_id, "checked": should_check})
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.log_error("checkbox_set_failed", str(e), {"id": checkbox_id})

    async def _execute_toggles(self, page: Page, elements: List[Dict], fill_plan: Dict):
        """Toggle switches"""
        toggles = [e for e in elements if e['type'] == 'toggle']
        if not toggles:
            return

        console.print(f"[cyan]   🔀 Setting {len(toggles)} toggles...[/cyan]")
        
        for toggle in toggles:
            toggle_id = toggle['id']
            should_enable = fill_plan.get('toggles', {}).get(toggle_id, False)
            
            try:
                selector = f"[id='{toggle_id}']"
                
                # Try different toggle methods
                if toggle.get('role') == 'switch':
                    await page.click(selector)
                else:
                    if should_enable:
                        await page.check(selector)
                    else:
                        await page.uncheck(selector)
                
                state = "ON" if should_enable else "OFF"
                console.print(f"[green]      ✓ Toggle {state}: {toggle.get('label', toggle_id)}[/green]")
                self.logger.log_action("toggle_set", {"id": toggle_id, "enabled": should_enable})
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.log_error("toggle_set_failed", str(e), {"id": toggle_id})

    async def _execute_selects(self, page: Page, elements: List[Dict], fill_plan: Dict):
        """Select dropdown options"""
        selects = [e for e in elements if e['type'] == 'select']
        if not selects:
            return

        console.print(f"[cyan]   📋 Setting {len(selects)} dropdowns...[/cyan]")
        
        for select in selects:
            select_id = select['id']
            value = fill_plan.get('selects', {}).get(select_id)
            
            if not value and select.get('options'):
                # Select first non-empty option by default
                value = next((opt['value'] for opt in select['options'] if opt['value']), None)
            
            if value:
                try:
                    selector = f"[id='{select_id}'], [name='{select_id}']"
                    
                    if isinstance(value, list):
                        # Multiple select
                        for v in value:
                            await page.select_option(selector, v)
                    else:
                        await page.select_option(selector, value)
                    
                    console.print(f"[green]      ✓ {select.get('label', select_id)}: {value}[/green]")
                    self.logger.log_action("select_option_set", {"id": select_id, "value": value})
                    await asyncio.sleep(0.3)
                except Exception as e:
                    self.logger.log_error("select_option_failed", str(e), {"id": select_id})

    async def _execute_submit_buttons(self, page: Page, elements: List[Dict]):
        """Click submit buttons and WAIT for completion"""
        submit_buttons = [e for e in elements if e['type'] == 'submit_button']
        if not submit_buttons:
            return

        console.print(f"[cyan]   🎯 Found {len(submit_buttons)} submit buttons...[/cyan]")
        
        for button in submit_buttons:
            button_id = button['id']
            button_text = button.get('text', 'Submit')
            
            console.print(f"[yellow]   ⏳ Clicking submit: '{button_text}'...[/yellow]")
            
            try:
                # Get URL before submit
                url_before = page.url
                
                # Click submit with SHORT timeout
                try:
                    if button_id and button_id.startswith('submit_'):
                        # Use text-based selector
                        await page.click(f"button:has-text('{button_text}')", timeout=5000)  # 5s not 30s!
                    else:
                        await page.click(f"[id='{button_id}']", timeout=5000)  # 5s not 30s!
                except Exception as e:
                    console.print(f"[yellow]      ⚠️  Submit click timeout: {e}[/yellow]")
                    self.logger.log_error("submit_click_timeout", str(e), {"button": button_text})
                    # Continue anyway - don't block exploration
                    continue
                
                self.logger.log_action("submit_clicked", {"button": button_text, "id": button_id})
                
                # WAIT for one of these to happen:
                # 1. URL changes (navigation)
                # 2. Success message appears
                # 3. Error message appears
                # 4. Timeout after 5 seconds
                
                console.print(f"[yellow]      ⏳ Waiting for form submission result...[/yellow]")
                
                await asyncio.sleep(2)  # Initial wait for processing
                
                # Check for navigation
                url_after = page.url
                if url_after != url_before:
                    console.print(f"[green]      ✅ Form submitted - navigated to: {url_after}[/green]")
                    self.logger.log_action("form_submit_navigation", {
                        "from": url_before,
                        "to": url_after
                    })
                    await asyncio.sleep(2)  # Wait for new page to stabilize
                    return
                
                # Check for success/error messages
                messages = await page.evaluate("""() => {
                    const successSelectors = ['.success', '.alert-success', '[role="alert"]', '.toast', '.notification'];
                    const errorSelectors = ['.error', '.alert-error', '.alert-danger', '.error-message'];
                    
                    let found = null;
                    for (const sel of successSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim()) {
                            found = {type: 'success', message: el.textContent.trim()};
                            break;
                        }
                    }
                    if (!found) {
                        for (const sel of errorSelectors) {
                            const el = document.querySelector(sel);
                            if (el && el.textContent.trim()) {
                                found = {type: 'error', message: el.textContent.trim()};
                                break;
                            }
                        }
                    }
                    return found;
                }""")
                
                if messages:
                    console.print(f"[{'green' if messages['type'] == 'success' else 'red'}]      {messages['type'].upper()}: {messages['message'][:100]}[/{'green' if messages['type'] == 'success' else 'red'}]")
                    self.logger.log_action("form_submit_message", messages)
                else:
                    console.print(f"[yellow]      ⚠️  No clear feedback message found[/yellow]")
                
                # Wait a bit more for any async operations
                await asyncio.sleep(2)
                
                console.print(f"[green]      ✅ Submit completed[/green]")
                
            except Exception as e:
                console.print(f"[red]      ❌ Submit failed: {e}[/red]")
                self.logger.log_error("submit_button_failed", str(e), {"button": button_text})


    async def _two_tier_exploration(self, page: Page, depth: int, breadcrumb: str):
        if depth > self.max_depth:
            console.print(f"[yellow]⚠️ Max depth {self.max_depth} reached[/yellow]")
            self.logger.log_info(f"Max depth {self.max_depth} reached")
            return

        console.print(f"\n{'='*80}")
        console.print(f"[bold cyan]📍 DEPTH {depth}: {breadcrumb}[/bold cyan]")
        console.print(f"{'='*80}\n")
        self.logger.log_info(f"Exploring at depth {depth}: {breadcrumb}")

        # Scroll to load all content
        await self.scroll_to_bottom(page)
        await page.evaluate("window.scrollTo(0, 0)")
        console.print("[yellow]⏳ Waiting for DOM to settle after scroll...[/yellow]")
        await asyncio.sleep(3)
        
        # Handle all interactive elements first
        await self.handle_all_interactive_elements(page, breadcrumb)
        await asyncio.sleep(2)
        
        current_url = page.url
        state_hash = await self.state_manager.calculate_state_hash(page)

        # Don't skip too aggressively - allow re-exploration if at different depths
        if self.state_manager.is_state_visited(state_hash) and depth > 1:
            console.print(f"[yellow]♻️ State visited before, but continuing exploration at depth {depth}[/yellow]")
            # Continue anyway to explore newly visible elements
        
        console.print("\n[bold yellow]🔍 INITIAL SCAN: Understanding page structure...[/bold yellow]")
        vision_analysis = await self.vision.analyze_page(page, current_url)
        self.stats['vision_calls'] += 1

        containers = await self.component_detector.detect_containers(
            page, vision_analysis.get('containers', [])
        )
        features = await self.component_detector.detect_features(
            page, vision_analysis.get('features', [])
        )

        self.stats['containers_found'] += len(containers)
        self.stats['features_found'] += len(features)

        if not containers and not features:
            console.print("[yellow]No components detected, ending exploration[/yellow]")
            self.logger.log_info("No components detected, ending exploration")
            return

        self.state_manager.record_state(state_hash, current_url, breadcrumb, containers, features)
        self.stats['states_discovered'] += 1
        self.stats['pages_explored'] += 1

        for container in containers:
            await self.graph_builder.register_container(page, container, current_url)

        for feature in features:
            await self.graph_builder.register_top_level_feature(page, feature, current_url)

        assumption_plan = self.planner.create_assumption_plan(
            containers, vision_analysis.get('discovery_strategy', {})
        )
        main_action_plan = self.planner.create_main_action_plan(features)

        console.print("\n" + "="*80)
        console.print("[bold green]🎯 PHASE 1: DISCOVERY — Executing Assumption Plan[/bold green]")
        console.print("="*80 + "\n")
        self.logger.log_info("Starting Phase 1: Discovery")

        await self._execute_assumption_plan(page, assumption_plan, current_url, depth, breadcrumb)

        console.print("\n" + "="*80)
        console.print("[bold green]🎯 PHASE 2: TESTING — Executing Main Action Plan[/bold green]")
        console.print("="*80 + "\n")
        self.logger.log_info("Starting Phase 2: Testing")

        await self._execute_main_action_plan(page, main_action_plan, depth, breadcrumb)


    async def _execute_assumption_plan(
        self,
        page: Page,
        plan: List[Dict],
        current_url: str,
        depth: int,
        breadcrumb: str
    ):
        if not plan:
            console.print("[yellow]No discovery steps needed[/yellow]")
            return

        for step in plan:
            container = step['container']
            container_id = container['semantic_id']

            if container_id in self.exploration_memory.get('explored_containers', {}):
                if self.exploration_memory['explored_containers'][container_id].get('expanded'):
                    console.print(f"\n[yellow]⏭️  SKIPPING discovery: '{container['text']}' — already expanded[/yellow]")
                    self.logger.log_info(f"Skipping already expanded container: {container['text']}")
                    continue

            console.print(f"\n[bold yellow]🔓 DISCOVERY STEP {step['step_id']}: {step['reason']}[/bold yellow]")
            self.logger.log_info(f"Discovery step {step['step_id']}: {step['reason']}")

            await self.dom_observer.get_changes(page)

            try:
                clicked = await self.semantic_selector.click_element(page, container)

                if not clicked:
                    console.print("[red]   Discovery failed — skipping to next container[/red]")
                    self.logger.log_error("discovery_click_failed", f"Could not click {container['text']}", {
                        "container_id": container_id
                    })
                    continue  # CONTINUE to next container, don't stop entire discovery!

                self.stats['discovery_clicks'] += 1

                self.exploration_memory.setdefault('explored_containers', {})[container_id] = {
                    'text': container.get('text'),
                    'expanded': True,
                    'expanded_at': datetime.now().isoformat(),
                    'type': container.get('type')
                }

                await asyncio.sleep(2)

                changes = await self.dom_observer.get_changes(page)
                change_type = await self.dom_observer.detect_change_type(changes)

                console.print(f"[cyan]   Change detected: {change_type} ({len(changes)} DOM mutations)[/cyan]")
                self.logger.log_container_expansion(container, True, changes)

                if change_type in ["menu_expanded", "element_expanded", "modal_opened"]:
                    await self._rescan_and_register(page, container, current_url, depth, breadcrumb)
                    self.stats['menus_expanded'] += 1

                    if change_type == "modal_opened":
                        self.stats['modals_detected'] += 1
                        await self._close_modal(page)

            except Exception as e:
                console.print(f"[red]   ❌ Exception during discovery: {e}[/red]")
                self.logger.log_error("discovery_exception", str(e), {"container": container['text']})
                # CONTINUE to next container
                continue

            self._save_memory()

    async def _rescan_and_register(
        self,
        page: Page,
        parent_container: Dict,
        current_url: str,
        depth: int,
        breadcrumb: str
    ):
        console.print("[cyan]🔍 Re-scanning for newly visible features...[/cyan]")
        self.logger.log_info(f"Re-scanning after expanding: {parent_container['text']}")

        vision_analysis = await self.vision.analyze_page(page, page.url)
        self.stats['vision_calls'] += 1

        raw_vision_features = vision_analysis.get('features', [])

        for container in vision_analysis.get('containers', []):
            is_target = container['text'].lower() in parent_container['text'].lower()
            if (container.get('state') == 'expanded' or is_target) and container.get('expected_children'):
                console.print(f"[yellow]   Extracting children from '{container['text']}'...[/yellow]")
                for child_text in container['expected_children']:
                    raw_vision_features.append({
                        "text": child_text,
                        "type": "link",
                        "location": "sidebar_child",
                        "test_priority": 8,
                        "expected_behavior": "Navigate to sub-page"
                    })

        new_features = await self.component_detector.detect_features(page, raw_vision_features)

        all_known_ids = set(self.exploration_memory.get('explored_features', {}).keys()) | \
                        set(self.exploration_memory.get('discovered_features', {}).keys()) | \
                        set(self.knowledge_graph.nodes.keys())

        truly_new = [f for f in new_features if f['semantic_id'] not in all_known_ids]

        if not truly_new:
            console.print("[yellow]   No new features found[/yellow]")
            self.logger.log_info("No new features found during rescan")
            return

        console.print(f"[green]   ✨ Found {len(truly_new)} new features![/green]")
        self.logger.log_info(f"Found {len(truly_new)} new features")

        successfully_registered = []
        for feature in truly_new:
            feature_id = feature['semantic_id']

            success = await self.graph_builder.register_discovered_feature(
                page, feature, parent_container, current_url
            )
            if not success:
                console.print(f"[red]   Failed to register '{feature['text']}' in Knowledge Graph[/red]")
                continue
            successfully_registered.append(feature)

            self.exploration_memory.setdefault('discovered_features', {})[feature_id] = {
                'text': feature.get('text'),
                'discovered_from': parent_container.get('text'),
                'discovered_from_id': parent_container.get('semantic_id'),
                'anchor_url': current_url,
                'discovered_at': datetime.now().isoformat()
            }

            console.print(f"[green]      + {feature['text']}[/green]")

        self.planner.add_discovered_features_to_main_plan(successfully_registered)
        self.stats['features_found'] += len(truly_new)

    async def _execute_main_action_plan(
        self,
        page: Page,
        plan: List[Dict],
        depth: int,
        breadcrumb: str
    ):
        if not plan:
            console.print("[yellow]No test steps[/yellow]")
            return

        for step in plan:
            feature    = step['feature']
            feature_id = step.get('feature_id', feature.get('semantic_id', ''))

            if feature_id in self.exploration_memory.get('explored_features', {}):
                if self.exploration_memory['explored_features'][feature_id].get('tested'):
                    console.print(f"\n[yellow]⏭️  SKIPPING: '{feature['text']}' — already tested[/yellow]")
                    self.logger.log_info(f"Skipping already tested feature: {feature['text']}")
                    continue

            console.print(f"\n[bold yellow]🧪 TEST STEP {step['step_id']}: {step['reason']}[/bold yellow]")
            console.print(f"[cyan]   Test Type: {step['test_type']}[/cyan]")
            self.logger.log_info(f"Test step {step['step_id']}: {step['reason']}")

            try:
                ready = await self.path_resolver.prepare_for_click(page, feature_id, feature)

                if not ready:
                    console.print(f"[red]   ❌ PathResolver could not prepare state — trying direct click anyway[/red]")
                    self.stats['path_restoration_failures'] += 1
                    # Don't skip - try direct click!

                if self.state_manager.navigation_occurred:
                    await self.dom_observer.inject_observer(page)
                    self.state_manager.acknowledge_navigation()

                url_before = page.url

                # Try clicking with retries
                clicked = False
                for attempt in range(3):
                    try:
                        clicked = await self.semantic_selector.click_element(page, feature)
                        if clicked:
                            break
                        await asyncio.sleep(1)
                    except:
                        if attempt < 2:
                            console.print(f"[yellow]   Retry {attempt + 2}...[/yellow]")
                            await asyncio.sleep(1)
                        continue

                if not clicked:
                    console.print("[red]   Test failed — could not click (continuing to next feature)[/red]")
                    self.logger.log_feature_test(feature, False)
                    continue  # CONTINUE to next feature

                self.stats['test_clicks'] += 1
                self.stats['features_tested'] += 1

                self.exploration_memory.setdefault('explored_features', {})[feature_id] = {
                    'text': feature.get('text'),
                    'tested': True,
                    'tested_at': datetime.now().isoformat(),
                    'test_type': step['test_type']
                }

                await asyncio.sleep(2)

                url_after = page.url

                if url_after != url_before:
                    console.print(f"[green]   🌐 Navigation: {url_after}[/green]")
                    self.logger.log_feature_test(feature, True, True, url_after)
                    self.logger.log_state_change(url_before, url_after, breadcrumb)

                    self.state_manager.signal_navigation()

                    new_breadcrumb = f"{breadcrumb} > {feature['text'][:30]}"
                    
                    # DEPTH-FIRST: Complete exploration of this new page before returning
                    await self._two_tier_exploration(page, depth + 1, new_breadcrumb)

                    console.print("[yellow]   ⬅️  Going back...[/yellow]")
                    try:
                        await page.go_back(wait_until='networkidle', timeout=10000)
                        await asyncio.sleep(2)
                        self.dom_observer.reset()
                        await self.dom_observer.inject_observer(page)
                        self.state_manager.signal_navigation()
                        self.logger.log_action("navigation_back", {"from_url": url_after, "to_url": url_before})
                    except Exception as e:
                        console.print(f"[red]   Failed to go back: {e}[/red]")
                        self.logger.log_error("navigation_back_failed", str(e), {
                            "from_url": url_after,
                            "to_url": url_before
                        })
                else:
                    self.logger.log_feature_test(feature, True, False)

            except Exception as e:
                console.print(f"[red]   ❌ Exception during feature test: {e}[/red]")
                self.logger.log_error("feature_test_exception", str(e), {"feature": feature['text']})
                # CONTINUE to next feature
                continue

            self._save_memory()

    async def _close_modal(self, page: Page):
        for selector in [
            'button[aria-label="Close"]', 'button.close',
            '[data-dismiss="modal"]', 'button:has-text("Close")',
            'button:has-text("Cancel")', '.modal-close'
        ]:
            try:
                await page.click(selector, timeout=2000)
                await asyncio.sleep(0.5)
                console.print("[green]   ✅ Modal closed[/green]")
                self.logger.log_action("modal_closed", {"method": "button_click"})
                return
            except:
                continue
        try:
            await page.keyboard.press('Escape')
            console.print("[green]   ✅ Modal closed with ESC[/green]")
            self.logger.log_action("modal_closed", {"method": "escape_key"})
        except:
            console.print("[yellow]   ⚠️  Could not close modal[/yellow]")
            self.logger.log_error("modal_close_failed", "Could not close modal")

    def _show_results(self):
        console.print("\n" + "="*80)
        console.print(Panel.fit("[bold green]✅ ENHANCED TWO-TIER + KNOWLEDGE GRAPH COMPLETE[/bold green]", border_style="green"))

        table = Table(title="Exploration Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="yellow")
        for key, value in self.stats.items():
            table.add_row(key.replace('_', ' ').title(), str(value))
        console.print(table)

        kg_table = Table(title="Knowledge Graph")
        kg_table.add_column("Metric", style="cyan")
        kg_table.add_column("Value", style="yellow")
        kg_table.add_row("Total Nodes", str(len(self.knowledge_graph.nodes)))
        kg_table.add_row("Total Edges", str(len(self.knowledge_graph.edges)))
        kg_table.add_row("DOM-Confirmed Edges", str(
            sum(1 for e in self.knowledge_graph.edges if e.get('confidence') == 'dom_confirmed')
        ))
        kg_table.add_row("Paths Computed", str(len(self.knowledge_graph.paths)))
        dom_action_edges = sum(1 for e in self.knowledge_graph.edges if e['edge_type'] == 'dom_action')
        nav_edges = sum(1 for e in self.knowledge_graph.edges if e['edge_type'] == 'navigation')
        kg_table.add_row("DOM Action Edges", str(dom_action_edges))
        kg_table.add_row("Navigation Edges", str(nav_edges))
        console.print(kg_table)

        console.print(f"\n  Discovery Steps: {len(self.planner.assumption_plan)}")
        console.print(f"  Testing Steps:   {len(self.planner.main_action_plan)}")

        # Save final summary
        kg_summary = {
            "total_nodes": len(self.knowledge_graph.nodes),
            "total_edges": len(self.knowledge_graph.edges),
            "dom_confirmed_edges": sum(1 for e in self.knowledge_graph.edges if e.get('confidence') == 'dom_confirmed'),
            "paths_computed": len(self.knowledge_graph.paths),
            "dom_action_edges": dom_action_edges,
            "navigation_edges": nav_edges
        }
        self.logger.save_final_summary(self.stats, kg_summary)

    def _save_exploration_data(self):
        output_dir = Path('output')
        output_dir.mkdir(exist_ok=True)

        data = {
            'metadata': {
                'base_url': self.base_url,
                'timestamp': datetime.now().isoformat(),
                'stats': self.stats,
                'architecture': 'enhanced_two_tier_with_complete_interaction_handling',
                'session_directory': str(self.logger.session_dir)
            },
            'knowledge_graph': {
                'nodes': self.knowledge_graph.nodes,
                'edges': self.knowledge_graph.edges,
                'paths': self.knowledge_graph.paths
            },
            'assumption_plan': self.planner.assumption_plan,
            'main_action_plan': self.planner.main_action_plan,
            'states': {
                h: {k: v for k, v in s.items()}
                for h, s in self.state_manager.states.items()
            }
        }

        output_file = output_dir / f'kg_exploration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.print(f"\n[bold green]💾 Saved: {output_file}[/bold green]")
        console.print(f"[bold green]💾 Knowledge Graph: output/knowledge_graph.json[/bold green]")
        console.print(f"[bold green]📁 Session Directory: {self.logger.session_dir}[/bold green]")
        console.print(f"[bold green]   ├─ crawler_log.txt (main log)[/bold green]")
        console.print(f"[bold green]   ├─ actions_log.jsonl (structured actions)[/bold green]")
        console.print(f"[bold green]   ├─ errors_log.txt (errors)[/bold green]")
        console.print(f"[bold green]   └─ plans/ (all plan versions)[/bold green]")


# =============================================================================
# Entry point
# =============================================================================

async def main():
    if not Path('auth.json').exists():
        console.print("[red]❌ auth.json not found![/red]")
        return

    openai_key = "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"
    if not openai_key:
        console.print("[red]❌ OPENAI_API_KEY not set[/red]")
        return

    crawler = TwoTierCrawler(
        base_url="https://staging.isalaam.me/dashboard",
        auth_file="auth.json",
        max_depth=99,
        openai_api_key=openai_key
    )

    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())