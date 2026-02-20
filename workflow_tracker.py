"""
workflow_tracker.py
===================
Real-time workflow story generator that watches Phase 2 actions
and creates plain English test cases with URL tracking.

Generates human-readable test instructions without touching existing code.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
from enum import Enum
from urllib.parse import urlparse


class WorkflowStatus(Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowTracker:
    """
    Silently observes test execution and generates plain English test cases.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Current workflow being tracked
        self.current_workflow: Optional[Dict] = None
        self.completed_workflows: List[Dict] = []
        
        # Context tracking
        self.context_stack_depth = 1
        self.last_context_type = "PAGE"
        
        # Action buffer for grouping
        self.action_buffer: List[Dict] = []
        
        # Workflow counter
        self.workflow_counter = 0
        
        # URL-based test organization
        self.tests_by_url: Dict[str, List[Dict]] = {}
        
        # Output files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.text_file = self.output_dir / f"test_cases_{timestamp}.txt"
        self.json_file = self.output_dir / f"test_cases_{timestamp}.json"
        self.url_index_file = self.output_dir / f"test_index_by_url_{timestamp}.txt"
        
        # Initialize files
        self._write_header()
        
        print(f"\n📖 Workflow Tracker initialized")
        print(f"   Test cases: {self.text_file.name}")
        print(f"   URL index : {self.url_index_file.name}")

    def track_action(
        self,
        decision: Dict,
        result: Dict,
        context_frame,
        url: str,
        step_number: int
    ) -> Optional[Dict]:
        """
        Called after each action in Phase 2.
        Returns completed workflow if one was just finished, None otherwise.
        """
        
        action = decision.get("action", "")
        target = decision.get("target_name", "")
        element_type = decision.get("element_type", "")
        test_value = decision.get("test_value", "")
        success = result.get("success", False)
        
        # Track context changes
        current_context = context_frame.context_type.value
        context_changed = (current_context != self.last_context_type)
        
        # Create action record
        action_record = {
            "step": step_number,
            "action": action,
            "target": target,
            "element_type": element_type,
            "test_value": test_value,
            "success": success,
            "context": current_context,
            "url": url,
            "timestamp": datetime.now().isoformat()
        }
        
        # Add to buffer
        self.action_buffer.append(action_record)
        
        # Detect workflow completion triggers
        should_complete = self._should_complete_workflow(
            action_record, 
            context_changed,
            current_context
        )
        
        if should_complete:
            completed = self._complete_current_workflow()
            self.last_context_type = current_context
            return completed
        
        # Start new workflow if needed
        if not self.current_workflow:
            self._start_new_workflow(action_record, current_context)
        
        self.last_context_type = current_context
        return None

    def _should_complete_workflow(
        self, 
        action_record: Dict,
        context_changed: bool,
        current_context: str
    ) -> bool:
        """
        Determine if current workflow should be completed.
        """
        
        # No workflow to complete
        if not self.action_buffer or len(self.action_buffer) < 2:
            return False
        
        # Trigger 1: Context returned to base (modal/form closed)
        if context_changed and current_context == "PAGE" and self.last_context_type != "PAGE":
            return True
        
        # Trigger 2: Submit/Save button clicked successfully
        if action_record["action"] == "click" and action_record["success"]:
            target_lower = action_record["target"].lower()
            submit_keywords = ["save", "submit", "simpan", "tambah", "perbarui", "update", "confirm", "ya", "yes"]
            if any(kw in target_lower for kw in submit_keywords):
                return True
        
        # Trigger 3: Navigation (URL changed significantly)
        if len(self.action_buffer) >= 2:
            prev_url = self.action_buffer[-2]["url"]
            curr_url = action_record["url"]
            if prev_url != curr_url and "/dashboard" not in curr_url:
                return True
        
        # Trigger 4: Long sequence (10+ actions without completion)
        if len(self.action_buffer) >= 10:
            return True
        
        return False

    def _start_new_workflow(self, first_action: Dict, context: str):
        """Start tracking a new workflow."""
        self.workflow_counter += 1
        self.current_workflow = {
            "id": self.workflow_counter,
            "started_at": datetime.now().isoformat(),
            "first_action": first_action,
            "context": context
        }

    def _complete_current_workflow(self) -> Optional[Dict]:
        """
        Complete the current workflow and generate test case.
        """
        
        if not self.action_buffer or len(self.action_buffer) < 2:
            self.action_buffer = []
            return None
        
        # Build workflow data
        workflow = {
            "id": self.workflow_counter,
            "actions": self.action_buffer.copy(),
            "started_at": self.action_buffer[0]["timestamp"],
            "completed_at": datetime.now().isoformat(),
            "total_steps": len(self.action_buffer),
            "success_rate": sum(1 for a in self.action_buffer if a["success"]) / len(self.action_buffer)
        }
        
        # Generate test case
        test_case = self._generate_test_case(workflow)
        workflow["test_case"] = test_case
        
        # Organize by URL
        main_url = test_case["main_page_url"]
        if main_url not in self.tests_by_url:
            self.tests_by_url[main_url] = []
        self.tests_by_url[main_url].append(test_case)
        
        # Save
        self.completed_workflows.append(workflow)
        self._write_test_case(test_case)
        self._save_json()
        self._update_url_index()
        
        # Print to console
        self._print_test_case(test_case)
        
        # Clear buffer
        self.action_buffer = []
        self.current_workflow = None
        
        return workflow

    def _generate_test_case(self, workflow: Dict) -> Dict:
        """
        Generate plain English test case from workflow actions.
        """
        
        actions = workflow["actions"]
        
        # Detect test case type and generate title
        title = self._detect_workflow_title(actions)
        
        # Generate steps in plain English
        steps = self._generate_plain_steps(actions)
        
        # Determine status
        all_success = all(a["success"] for a in actions)
        status = "✅ Passed" if all_success else "⚠️ Partial"
        
        # Calculate duration
        start = datetime.fromisoformat(workflow["started_at"])
        end = datetime.fromisoformat(workflow["completed_at"])
        duration = (end - start).total_seconds()
        
        # Extract all unique URLs involved in this workflow
        urls_involved = []
        seen_urls = set()
        for action in actions:
            url = action.get("url", "")
            if url and url not in seen_urls:
                urls_involved.append(url)
                seen_urls.add(url)
        
        # Determine the main page (first URL)
        main_page_url = actions[0]["url"] if actions else ""
        
        return {
            "id": workflow["id"],
            "title": title,
            "steps": steps,
            "status": status,
            "duration_seconds": round(duration, 1),
            "total_actions": len(actions),
            "success_count": sum(1 for a in actions if a["success"]),
            "main_page_url": main_page_url,  # Primary page where test started
            "all_urls": urls_involved,        # All pages visited during test
            "page_name": self._extract_page_name(main_page_url)  # Friendly name
        }

    def _extract_page_name(self, url: str) -> str:
        """Extract friendly page name from URL."""
        if not url:
            return "Unknown Page"
        
        try:
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            
            if not path or path == 'dashboard':
                return "Dashboard"
            
            # Extract last meaningful segment
            segments = [s for s in path.split('/') if s]
            if segments:
                page = segments[-1].replace('-', ' ').replace('_', ' ').title()
                return page
            
            return "Dashboard"
        except Exception:
            return "Unknown Page"

    def _detect_workflow_title(self, actions: List[Dict]) -> str:
        """
        Detect what the workflow is doing and generate a title.
        """
        
        # Look at action targets to determine intent
        targets = [a["target"].lower() for a in actions]
        action_types = [a["action"] for a in actions]
        
        # Deletion flow
        if any(word in " ".join(targets) for word in ["delete", "hapus", "remove"]):
            return "Delete Item with Confirmation"
        
        # Creation flow (multiple fills + submit)
        fill_count = sum(1 for a in action_types if a == "fill")
        has_submit = any(word in " ".join(targets) for word in ["save", "submit", "simpan", "tambah"])
        if fill_count >= 2 and has_submit:
            return "Create New Item"
        
        # Edit flow
        if any(word in " ".join(targets) for word in ["edit", "update", "perbarui"]):
            return "Edit Item Details"
        
        # Search flow
        if any(word in " ".join(targets) for word in ["search", "cari", "filter"]):
            return "Search and Filter"
        
        # View flow
        if any(word in " ".join(targets) for word in ["view", "detail", "show"]):
            return "View Item Details"
        
        # Form interaction
        if fill_count >= 3:
            return "Fill Form Fields"
        
        # Menu navigation
        if any(word in " ".join(targets) for word in ["menu", "3-dot", "options"]):
            return "Navigate Menu Options"
        
        # Generic
        return "Interact with Page Elements"

    def _generate_plain_steps(self, actions: List[Dict]) -> List[str]:
        """
        Convert actions to plain English steps.
        """
        steps = []
        
        for idx, action in enumerate(actions, 1):
            action_type = action["action"]
            target = action["target"]
            value = action.get("test_value", "")
            element_type = action.get("element_type", "")
            
            if action_type == "fill":
                if value:
                    step = f'Fill in "{target}" with "{value}"'
                else:
                    step = f'Fill in the "{target}" field'
            
            elif action_type == "select":
                if value:
                    step = f'Select "{value}" from "{target}" dropdown'
                else:
                    step = f'Select an option from "{target}" dropdown'
            
            elif action_type == "click":
                if element_type == "button":
                    step = f'Click the "{target}" button'
                elif element_type == "link":
                    step = f'Click on "{target}" link'
                else:
                    step = f'Click on "{target}"'
            
            elif action_type == "check":
                step = f'Check the "{target}" checkbox'
            
            else:
                step = f'{action_type.title()} "{target}"'
            
            # Add success indicator
            if not action["success"]:
                step += " ⚠️"
            
            steps.append(step)
        
        return steps

    def _write_header(self):
        """Write file headers."""
        header = f"""
═══════════════════════════════════════════════════
        AUTOMATED TEST CASES
═══════════════════════════════════════════════════
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Session: {self.text_file.stem}

These test cases were automatically generated by
observing real user interactions with the application.
═══════════════════════════════════════════════════

"""
        with open(self.text_file, "w", encoding="utf-8") as f:
            f.write(header)

    def _write_test_case(self, test_case: Dict):
        """Append test case to text file."""
        
        output = f"""
{'='*70}
TEST CASE #{test_case['id']}: {test_case['title']}
{'='*70}

Page: {test_case['page_name']}
URL:  {test_case['main_page_url']}

Steps to test:
"""
        
        for idx, step in enumerate(test_case['steps'], 1):
            output += f"  {idx}. {step}\n"
        
        if len(test_case['all_urls']) > 1:
            output += f"\nPages visited during test:\n"
            for url in test_case['all_urls']:
                output += f"  → {url}\n"
        
        output += f"""
Result: {test_case['status']}
Time: {test_case['duration_seconds']} seconds
Actions: {test_case['success_count']}/{test_case['total_actions']} successful

{'='*70}

"""
        
        with open(self.text_file, "a", encoding="utf-8") as f:
            f.write(output)

    def _print_test_case(self, test_case: Dict):
        """Print test case to console."""
        print(f"\n{'='*70}")
        print(f"📖 TEST CASE COMPLETED: {test_case['title']}")
        print(f"{'='*70}")
        print(f"Page: {test_case['page_name']}")
        print(f"Steps: {len(test_case['steps'])}")
        print(f"Status: {test_case['status']}")
        print(f"Duration: {test_case['duration_seconds']}s")
        print(f"{'='*70}\n")

    def _update_url_index(self):
        """Update the URL index file showing which tests belong to which pages."""
        
        output = f"""
═══════════════════════════════════════════════════
        TEST CASES BY PAGE/URL
═══════════════════════════════════════════════════
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total Pages: {len(self.tests_by_url)}
Total Tests: {len(self.completed_workflows)}
═══════════════════════════════════════════════════

"""
        
        for url, tests in self.tests_by_url.items():
            page_name = self._extract_page_name(url)
            output += f"\n{'─'*70}\n"
            output += f"📄 PAGE: {page_name}\n"
            output += f"   URL: {url}\n"
            output += f"   Tests: {len(tests)}\n"
            output += f"{'─'*70}\n\n"
            
            for test in tests:
                status_icon = "✅" if "✅" in test['status'] else "⚠️"
                output += f"  {status_icon} Test #{test['id']}: {test['title']}\n"
                output += f"     Steps: {len(test['steps'])} | Duration: {test['duration_seconds']}s\n\n"
        
        output += f"\n{'='*70}\n"
        output += f"SUMMARY:\n"
        output += f"  Total pages tested: {len(self.tests_by_url)}\n"
        output += f"  Total test cases: {len(self.completed_workflows)}\n"
        
        passed = sum(1 for w in self.completed_workflows 
                    if "✅" in w['test_case']['status'])
        output += f"  Passed: {passed}\n"
        output += f"  Partial: {len(self.completed_workflows) - passed}\n"
        output += f"{'='*70}\n"
        
        with open(self.url_index_file, "w", encoding="utf-8") as f:
            f.write(output)

    def _save_json(self):
        """Save JSON format for machine parsing."""
        data = {
            "session_timestamp": datetime.now().isoformat(),
            "total_workflows": len(self.completed_workflows),
            "tests_by_url": {
                url: [t for t in tests]
                for url, tests in self.tests_by_url.items()
            },
            "all_workflows": [
                {
                    "id": w["id"],
                    "test_case": w["test_case"],
                    "started_at": w["started_at"],
                    "completed_at": w["completed_at"],
                    "total_steps": w["total_steps"],
                    "success_rate": w["success_rate"]
                }
                for w in self.completed_workflows
            ]
        }
        
        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def finalize(self):
        """Call this at the end of testing session."""
        print(f"\n{'='*70}")
        print(f"📊 WORKFLOW TRACKING COMPLETE")
        print(f"{'='*70}")
        print(f"Total test cases generated: {len(self.completed_workflows)}")
        print(f"Pages tested: {len(self.tests_by_url)}")
        print(f"\nOutput files:")
        print(f"  📄 Test cases: {self.text_file}")
        print(f"  📄 URL index : {self.url_index_file}")
        print(f"  📄 JSON data : {self.json_file}")
        print(f"{'='*70}\n")