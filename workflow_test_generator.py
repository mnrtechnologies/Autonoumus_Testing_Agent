"""
workflow_test_generator.py
───────────────────────────
AI-powered test case generator that creates FEATURE-BASED test cases.

Instead of:
  "Step 1: Click button, Step 2: Fill field..."

Generates:
  "TEST CASE 1: Search Mosque by Name
   1. Go to Onboard Requests
   2. Enter 'MASJID AL MISYKAH' in search
   3. Click Search
   4. Verify mosque appears
   
   TEST CASE 2: Activate Mosque Request
   1. Search for mosque
   2. Click 3-dot menu
   3. Select 'Activate'
   4. Confirm activation"
"""

import json
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
from openai import OpenAI
import asyncio


class WorkflowTestGenerator:
    """Generates workflow-based test cases using AI to identify features."""
    
    def __init__(self, openai_client: OpenAI):
        self.openai = openai_client
        
    async def generate_from_history(
        self, 
        history: List[Dict], 
        url_results: List[Dict]
    ) -> List[Dict]:
        """
        Generate feature-based test cases from execution history.
        AI identifies workflows and groups actions into business features.
        """
        print("\n" + "="*80)
        print("🎯 WORKFLOW-BASED TEST CASE GENERATION")
        print("="*80)
        print("AI will identify business features and create test cases...")
        
        all_test_cases = []
        
        # Group steps by URL
        from collections import defaultdict
        url_groups = defaultdict(list)
        
        for step in history:
            url = step.get("url", "unknown")
            url_groups[url].append(step)
        
        # Generate workflow-based test cases for each URL
        for idx, url_result in enumerate(url_results, 1):
            url = url_result.get("url", "")
            steps = url_groups.get(url, [])
            
            if not steps:
                continue
            
            print(f"\n📋 Analyzing URL {idx}/{len(url_results)}: {url}")
            print(f"   Found {len(steps)} actions to analyze...")
            
            # AI analyzes all steps and identifies distinct workflows/features
            workflows = await self._identify_workflows_with_ai(url, steps)
            
            if workflows:
                print(f"   ✅ Identified {len(workflows)} distinct workflows/features")
                for workflow in workflows:
                    print(f"      • {workflow.get('feature_name', 'Unknown')}")
                
                all_test_cases.extend(workflows)
            else:
                print(f"   ⚠️  No clear workflows identified")
        
        return all_test_cases
    
    async def _identify_workflows_with_ai(
        self,
        url: str,
        steps: List[Dict]
    ) -> List[Dict]:
        """
        Use AI to analyze steps and identify distinct business workflows.
        Returns multiple test cases, one per identified workflow/feature.
        """
        
        # Prepare execution data
        actions_summary = []
        for step in steps:
            decision = step.get("decision", {})
            result = step.get("result", {})
            
            actions_summary.append({
                "action": decision.get("action", ""),
                "target": decision.get("target_name", ""),
                "element_type": decision.get("element_type", ""),
                "value": decision.get("test_value", ""),
                "success": result.get("success", False),
                "selected_option": result.get("selected_value"),
                "available_options": result.get("all_options", [])
            })
        
        # Create AI prompt
        prompt = f"""You are analyzing automated test execution to identify DISTINCT BUSINESS WORKFLOWS/FEATURES.

URL: {url}

Actions Performed:
{json.dumps(actions_summary, indent=2)}

Your task:
1. Analyze these actions and identify SEPARATE BUSINESS FEATURES/WORKFLOWS
2. Each workflow is a complete user journey to accomplish ONE specific goal
3. Group related actions together into workflows

Examples of workflows:
- "Search for item by name"
- "Activate a request via menu"
- "Send follow-up email"
- "Check status of an item"
- "Create new entry with form"
- "Delete/Cancel an item"

For EACH identified workflow, create a test case in this JSON format:

{{
  "workflows": [
    {{
      "feature_name": "Clear, descriptive name of the business feature (e.g., 'Search Mosque Onboard Request by Name')",
      "test_case_id": "TC_FEATURE_001",
      "objective": "What business goal does this test validate",
      "preconditions": ["What must be set up before testing"],
      "test_data": {{
        "field_name": "actual value used"
      }},
      "steps": [
        {{
          "step_number": 1,
          "action": "Navigate/Search/Click/etc",
          "description": "Plain English - what to do (include ACTUAL values like mosque name)",
          "expected_result": "What should happen"
        }}
      ],
      "final_verification": "What confirms this workflow succeeded",
      "edge_cases": ["Potential issues or variations to test"]
    }}
  ]
}}

IMPORTANT RULES:
1. Each workflow should be INDEPENDENT and test ONE feature
2. Use ACTUAL data from the actions (mosque names, email addresses, etc.)
3. If you see: Search → Menu Click → Select Option - that's ONE workflow
4. Be SPECIFIC with names and values used
5. Group related actions (e.g., all steps to activate a request = 1 workflow)
6. Create MULTIPLE workflows if actions serve different purposes

Identify all distinct workflows now:"""

        try:
            # Call OpenAI
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert QA analyst who identifies business workflows from user actions.
You excel at recognizing patterns and grouping actions into meaningful test cases.
You always use specific, real data from the execution.
You create separate test cases for separate features.
Output ONLY valid JSON."""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=3000
            )
            
            # Parse response
            ai_content = response.choices[0].message.content.strip()
            
            # Clean markdown if present
            if ai_content.startswith("```json"):
                ai_content = ai_content[7:]
            if ai_content.startswith("```"):
                ai_content = ai_content[3:]
            if ai_content.endswith("```"):
                ai_content = ai_content[:-3]
            
            result = json.loads(ai_content.strip())
            workflows = result.get("workflows", [])
            
            # Add metadata to each workflow
            for i, workflow in enumerate(workflows, 1):
                workflow["url"] = url
                workflow["generated_at"] = datetime.now().isoformat()
                workflow["ai_generated"] = True
                
                # Calculate success rate from original steps
                successful = sum(1 for s in steps if s.get("result", {}).get("success"))
                workflow["execution_stats"] = {
                    "total_actions": len(steps),
                    "successful": successful,
                    "failed": len(steps) - successful
                }
            
            return workflows
            
        except Exception as e:
            print(f"   ❌ AI analysis failed: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def save_test_cases(
        self,
        test_cases: List[Dict],
        output_path: str = "workflow_test_cases.md"
    ):
        """Save workflow-based test cases to Markdown."""
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            # Header
            f.write("# Workflow-Based Test Cases 🎯\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Total Test Cases:** {len(test_cases)}\n\n")
            f.write("*Test cases organized by business features and workflows*\n\n")
            
            # Summary table
            f.write("## Test Case Summary\n\n")
            f.write("| ID | Feature Name | Steps | URL |\n")
            f.write("|----|--------------|-------|-----|\n")
            
            for tc in test_cases:
                tc_id = tc.get('test_case_id', 'N/A')
                name = tc.get('feature_name', 'Unknown')
                steps = len(tc.get('steps', []))
                url = tc.get('url', 'N/A')
                url_short = url.split('/')[-1] if url else 'N/A'
                
                f.write(f"| {tc_id} | {name} | {steps} | {url_short} |\n")
            
            f.write("\n---\n\n")
            
            # Detailed test cases
            for tc in test_cases:
                self._write_workflow_test_case(f, tc)
        
        print(f"\n✅ Workflow test cases saved to: {output_file.resolve()}")
    
    def _write_workflow_test_case(self, file, test_case: Dict):
        """Write a single workflow test case."""
        
        tc_id = test_case.get('test_case_id', 'Unknown')
        feature = test_case.get('feature_name', 'Unknown Feature')
        
        file.write(f"## {tc_id}: {feature}\n\n")
        
        # Objective
        if test_case.get('objective'):
            file.write(f"**Objective:** {test_case['objective']}\n\n")
        
        # URL
        file.write(f"**URL:** `{test_case.get('url', 'N/A')}`\n\n")
        
        # Preconditions
        preconditions = test_case.get('preconditions', [])
        if preconditions:
            file.write("### Preconditions\n\n")
            for i, precond in enumerate(preconditions, 1):
                file.write(f"{i}. {precond}\n")
            file.write("\n")
        
        # Test Data
        test_data = test_case.get('test_data', {})
        if test_data:
            file.write("### Test Data Used\n\n")
            file.write("| Field | Value |\n")
            file.write("|-------|-------|\n")
            for field, value in test_data.items():
                file.write(f"| {field} | `{value}` |\n")
            file.write("\n")
        
        # Test Steps
        file.write("### Test Steps\n\n")
        
        steps = test_case.get('steps', [])
        for step in steps:
            num = step.get('step_number', '?')
            action = step.get('action', '')
            desc = step.get('description', '')
            expected = step.get('expected_result', '')
            
            file.write(f"**Step {num}: {action}**\n")
            file.write(f"- **Action:** {desc}\n")
            file.write(f"- **Expected Result:** {expected}\n\n")
        
        # Final Verification
        if test_case.get('final_verification'):
            file.write(f"### Final Verification\n\n")
            file.write(f"{test_case['final_verification']}\n\n")
        
        # Edge Cases
        edge_cases = test_case.get('edge_cases', [])
        if edge_cases:
            file.write("### Edge Cases to Consider\n\n")
            for edge in edge_cases:
                file.write(f"- {edge}\n")
            file.write("\n")
        
        # Execution Stats
        stats = test_case.get('execution_stats', {})
        if stats:
            file.write("### Execution Statistics\n\n")
            file.write(f"- Total Actions: {stats.get('total_actions', 0)}\n")
            file.write(f"- Successful: {stats.get('successful', 0)}\n")
            file.write(f"- Failed: {stats.get('failed', 0)}\n\n")
        
        file.write("---\n\n")
    
    def save_test_cases_plain_text(
        self,
        test_cases: List[Dict],
        output_path: str = "workflow_test_cases.txt"
    ):
        """Save workflow test cases in plain text."""
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("="*80 + "\n")
            f.write("WORKFLOW-BASED TEST CASES\n")
            f.write("="*80 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Test Cases: {len(test_cases)}\n\n")
            
            for tc in test_cases:
                tc_id = tc.get('test_case_id', 'Unknown')
                feature = tc.get('feature_name', 'Unknown')
                
                f.write("="*80 + "\n")
                f.write(f"{tc_id}: {feature}\n")
                f.write("="*80 + "\n\n")
                
                if tc.get('objective'):
                    f.write(f"Objective: {tc['objective']}\n\n")
                
                f.write(f"URL: {tc.get('url', 'N/A')}\n\n")
                
                # Preconditions
                preconditions = tc.get('preconditions', [])
                if preconditions:
                    f.write("Preconditions:\n")
                    for i, p in enumerate(preconditions, 1):
                        f.write(f"  {i}. {p}\n")
                    f.write("\n")
                
                # Test Data
                test_data = tc.get('test_data', {})
                if test_data:
                    f.write("Test Data:\n")
                    for field, value in test_data.items():
                        f.write(f"  - {field}: {value}\n")
                    f.write("\n")
                
                # Steps
                f.write("Test Steps:\n")
                f.write("-"*80 + "\n\n")
                
                for step in tc.get('steps', []):
                    num = step.get('step_number', '?')
                    action = step.get('action', '')
                    desc = step.get('description', '')
                    expected = step.get('expected_result', '')
                    
                    f.write(f"Step {num}: {action}\n")
                    f.write(f"  Action:   {desc}\n")
                    f.write(f"  Expected: {expected}\n\n")
                
                # Final verification
                if tc.get('final_verification'):
                    f.write(f"Final Verification:\n")
                    f.write(f"  {tc['final_verification']}\n\n")
                
                # Edge cases
                edge_cases = tc.get('edge_cases', [])
                if edge_cases:
                    f.write("Edge Cases:\n")
                    for edge in edge_cases:
                        f.write(f"  - {edge}\n")
                    f.write("\n")
        
        print(f"✅ Plain text workflow test cases saved to: {output_file.resolve()}")


# Example usage
if __name__ == "__main__":
    import os
    
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        print("Error: OPENAI_API_KEY not set")
        exit(1)
    
    client = OpenAI(api_key=openai_key)
    
    # Sample: Actions that represent "Search and Activate" workflow
    sample_history = [
        {
            "step": 1,
            "url": "https://staging.isalaam.me/onboard-requests",
            "decision": {
                "action": "fill",
                "target_name": "Mosque Name",
                "test_value": "MASJID AL MISYKAH",
                "element_type": "input"
            },
            "result": {"success": True}
        },
        {
            "step": 2,
            "url": "https://staging.isalaam.me/onboard-requests",
            "decision": {
                "action": "click",
                "target_name": "Search",
                "element_type": "button"
            },
            "result": {"success": True}
        },
        {
            "step": 3,
            "url": "https://staging.isalaam.me/onboard-requests",
            "decision": {
                "action": "click",
                "target_name": "3-dot menu",
                "element_type": "button"
            },
            "result": {"success": True}
        },
        {
            "step": 4,
            "url": "https://staging.isalaam.me/onboard-requests",
            "decision": {
                "action": "click",
                "target_name": "Activate",
                "element_type": "menu-item"
            },
            "result": {"success": True}
        }
    ]
    
    sample_url_results = [{
        "url": "https://staging.isalaam.me/onboard-requests",
        "index": 1,
        "steps_taken": 4,
        "tested_at": datetime.now().isoformat()
    }]
    
    async def demo():
        generator = WorkflowTestGenerator(client)
        workflows = await generator.generate_from_history(sample_history, sample_url_results)
        generator.save_test_cases(workflows, "demo_workflow_tests.md")
        generator.save_test_cases_plain_text(workflows, "demo_workflow_tests.txt")
    
    asyncio.run(demo())