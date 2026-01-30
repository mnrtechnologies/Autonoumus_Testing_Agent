"""
Orchestrator - UPGRADED to v3.0 - Data-Driven Determinism
NOW: Implements Diagnostic Loop with repair selector generation
TRIGGERS: After 2 consecutive failures on same element
MEMORY: Saves working repair selectors per-domain
"""
from engines.browser_engine import BrowserEngine
from engines.vision_engine import VisionEngine, ElementProfile
from engines.brain_engine import BrainEngine, AgentDecision
from engines.selector_memory import SelectorMemory
from typing import List, Dict
import json
from datetime import datetime
from pathlib import Path
from engines.assertion_engine import AssertionEngine
import os


class Orchestrator:
    """
    The main controller that runs the testing loop.
    VERSION 3.0: Implements Diagnostic Loop for intelligent failure recovery.
    """
    
    def __init__(self, api_key: str, headless: bool = False):
        """
        Initialize the orchestrator with all engines.
        
        Args:
            api_key: Anthropic API key for Claude
            headless: Whether to run browser in headless mode
        """
        self.browser = BrowserEngine(headless=headless)
        self.vision = VisionEngine()
        self.brain = BrainEngine(api_key=api_key)
        self.memory = SelectorMemory()  # NEW: Selector memory system
        
        self.action_history: List[str] = []
        self.step_count = 0
        self.max_steps = 50  # Safety limit
        self.current_url = ""  # Track current URL for memory
        self.latest_screenshot = None # For Realtime Streaming
        self.waiting_for_input = False
        self.waiting_input_payload = None
        self.assertions: List[str] = []
        self.summary: str = ""


        self.assertion_engine = AssertionEngine(
            api_key=os.getenv("OPENAI_API_KEY")
        )
        self.events: List[Dict] = []

        # Diagnostic Loop constants
        self.FAILURE_THRESHOLD = 2  # Trigger diagnostic after 2 failures
        
        # Login tracking - to avoid asking for credentials multiple times
        self.login_page_handled = False  # Have we already asked for credentials?
        self.login_page_url = None  # Track which URL we asked for credentials on
        self.collected_credentials = {}  # Store the credentials we collected
        self.login_goal_in_progress = False  # Are we executing a login goal?
        self.waiting_for_input = False
        self.waiting_input_payload = None

        # Loop detection - prevent clicking same element repeatedly
        self.recent_actions: List[tuple] = []  # Track (element_id, action_type) tuples
        self.LOOP_THRESHOLD = 4  # If same element clicked 4+ times, ask user for help
    
    def run(self, url: str, goal: str) -> Dict:
        """
        Run the autonomous testing loop with Diagnostic Loop support.
        
        Args:
            url: Website URL to test
            goal: Testing goal description
            
        Returns:
            Dictionary with test results
        """
        # Reset detailed steps for new test
        from test_modes import ReportGenerator
        ReportGenerator.detailed_steps = []
        
        print("=" * 60)
        print("🤖 ROBO-TESTER v3.0 - DATA-DRIVEN DETERMINISM")
        print("=" * 60)
        print(f"🎯 Goal: {goal}")
        print(f"🌐 URL: {url}")
        print(f"📊 Max steps: {self.max_steps}")
        print(f"🔧 Diagnostic Loop: Enabled (triggers after {self.FAILURE_THRESHOLD} failures)")
        
        # Show memory stats
        stats = self.memory.get_stats()
        print(f"💾 Memory: {stats['total_selectors']} selectors across {stats['total_domains']} domains")
        print("=" * 60)
        
        self.current_url = url
         
        # Step 1: Initialize browser (ONLY if not already running)
        if not self.browser.page:
            print(f"🚀 Launching new browser session...")
            if not self.browser.start(url):
                return self._generate_report(success=False, error="Failed to start browser")
        else:
            print(f"🔄 Continuing in existing browser session at: {self.browser.page.url}")
        
        try:
            # Step 2: Main testing loop
            while self.step_count < self.max_steps:
                self.step_count += 1
                print(f"\n{'='*60}")
                print(f"STEP {self.step_count}/{self.max_steps}")
                print('='*60)
                
                # Observe: Capture current state with Ground Truth
                page = self.browser.get_page()
                
                try:
                    screenshot_path, element_profiles = self.vision.capture_state(page)
                    self.latest_screenshot = screenshot_path

                except Exception as capture_error:
                    print(f"❌ Error capturing state: {str(capture_error)}")
                    import traceback
                    traceback.print_exc()
                    print("⚠️  Waiting and retrying...")
                    self.action_history.append(f"Step {self.step_count}: Failed to capture state - {str(capture_error)}")
                    continue
                
                if not screenshot_path or not element_profiles:
                    print("⚠️  Failed to capture state, waiting and retrying...")
                    self.action_history.append(f"Step {self.step_count}: Failed to capture state")
                    continue
                
                # Update browser with new element map
                try:
                    self.browser.update_element_map(element_profiles)
                except Exception as update_error:
                    print(f"❌ Error updating element map: {str(update_error)}")
                    import traceback
                    traceback.print_exc()
                    continue
                
                # Think: Ask Claude what to do (using Ground Truth data!)
                # NOTE: Form detection is removed - Claude will navigate autonomously first
                # Forms will be filled when Claude reaches them
                try:
                    decision = self.brain.decide_next_action(
                        screenshot_path=screenshot_path,
                        element_profiles=element_profiles,  # Now passing profiles!
                        action_history=self.action_history,
                        goal=goal,
                        max_steps=self.max_steps,
                        current_step=self.step_count
                    )
                except Exception as brain_error:
                    print(f"❌ Error getting decision from Claude: {str(brain_error)}")
                    import traceback
                    traceback.print_exc()
                    continue
                
                # Check if Claude is asking for user input for a form field
                if decision.need_user_input:
                    self.waiting_for_input = True

                    self.waiting_input_payload = {
                        "type": "form_input",
                        "element_id": str(decision.element_id),
                        "field_label": decision.field_label,
                        "step": self.step_count
                    }

                    print("⏸️ Waiting for user input via API...")

                    # BLOCK HERE (do NOT return)
                    import time
                    while self.waiting_for_input:
                        time.sleep(0.2)

                    # After input is received, tell Claude to type
                    decision.action = "type"
                    decision.value = self.collected_credentials.get(str(decision.element_id))

                    

                # Check if done
                if decision.action == "done" or decision.status == "done":
                    print(f"\n✅ Testing complete! Reason: {decision.thought}")
                    self.action_history.append(
                        f"Step {self.step_count}: Completed - {decision.thought}"
                    )
                    return self._generate_report(success=True)
                
                # Act: Execute the decision (with Diagnostic Loop support!)
                try:
                    result = self._execute_with_diagnostic_loop(decision, element_profiles)
                except Exception as action_error:
                    print(f"❌ Error executing action: {str(action_error)}")
                    import traceback
                    traceback.print_exc()
                    result = {"success": False, "message": str(action_error)}
                
                # Record the action
                action_description = self._format_action_description(decision, result)
                self.action_history.append(action_description)
                

                self.events.append({
                    "step": self.step_count,
                    "action": decision.action,
                    "element": (
                        element_profiles.get(str(decision.element_id)).to_dict()
                        if decision.element_id and str(decision.element_id) in element_profiles
                        else None
                    ),
                    "page_url": page.url,
                    "goal": goal,
                    "thought": decision.thought,
                    "success": result.get("success", False)
                })

                if self.step_count % 3 == 0:
                    print(f"🔄 Updating live assertions for UI...")
                    self.update_live_assertions()

                # Check for loops (same element clicked multiple times)
                loop_detected, loop_count = self._check_for_loop(decision)
                if loop_detected:
                    print(f"\n⚠️  LOOP DETECTED: Clicked element {decision.element_id} {loop_count} times without progress")
                    print(f"    The system seems stuck. Let me ask for clarification...\n")
                    
                    # Ask user for help
                    new_instruction = self._ask_user_for_instruction()
                    if new_instruction:
                        # Update goal with user's instruction
                        goal = new_instruction
                        print(f"\n✅ New instruction received: {goal}")
                        print(f"   Continuing with updated goal...\n")
                        # Continue to next iteration with new goal
                        continue
                    else:
                        # User chose to cancel
                        return self._generate_report(
                            success=False,
                            error="User cancelled test due to system being stuck"
                        )
                
                # Also record detailed step narrative for human-readable report
                from test_modes import ReportGenerator
                
                # Get observation from elements we saw
                observation = self._get_observation_text(element_profiles)
                
                # Record step details
                ReportGenerator.add_step_detail(
                    step_number=self.step_count,
                    observation=observation,
                    decision=decision.thought,
                    action_taken=self._get_action_text(decision, result),
                    result=result.get("message", "Action completed"),
                    success=result.get("success", False),
                    error=result.get("error") if not result.get("success") else None
                )
                
                print(f"   📝 {action_description}")
            
            # Reached max steps
            print(f"\n⚠️  Reached maximum steps ({self.max_steps})")
            return self._generate_report(
                success=False, 
                error=f"Reached maximum steps without completing goal"
            )
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Testing interrupted by user")
            return self._generate_report(success=False, error="Interrupted by user")
        
        except Exception as e:
            print(f"\n❌ Unexpected error: {str(e)}")
            import traceback
            traceback.print_exc()
            return self._generate_report(success=False, error=str(e))
        
        finally:
            # Clean up
            print("Keep-alive: Browser remains open for the next task.")


    def update_live_assertions(self):
            if len(self.events) > 0:
                try:
                    # Get the latest human-readable version of events
                    self.assertions = self.assertion_engine.generate_assertions(self.events)
                except Exception as e:
                    print(f"⚠️ Live assertion update failed: {e}")
    
    def _execute_with_diagnostic_loop(self, 
                                     decision: AgentDecision, 
                                     element_profiles: Dict[str, ElementProfile]) -> Dict:
        """
        Execute an action with Diagnostic Loop support.
        
        DIAGNOSTIC LOOP LOGIC:
        1. Try normal execution
        2. If it fails, check failure count
        3. If failure count >= FAILURE_THRESHOLD:
           a. Check memory for repair selector
           b. If not in memory, generate new repair selector using Ground Truth
           c. Try action with repair selector
           d. If successful, save to memory
        
        Args:
            decision: The AgentDecision from Claude
            element_profiles: Dictionary of element profiles with Ground Truth
            
        Returns:
            Result dictionary from browser engine
        """
        element_id = decision.element_id
        
        # Step 1: Check if we have a repair selector in memory (OPTIMIZATION)
        if element_id and element_id in element_profiles:
            profile = element_profiles[str(element_id)]
            element_text = profile.text
            
            # Try memory first if element has text
            if element_text:
                memory_selector = self.memory.get_repair_selector(self.current_url, element_text)
                if memory_selector:
                    print(f"   🎯 Using memorized repair selector for '{element_text}'")
                    result = self.browser.execute_action(
                        action_type=decision.action,
                        element_id=element_id,
                        value=decision.value,
                        repair_selector=memory_selector
                    )
                    if result["success"]:
                        return result
                    else:
                        print(f"   ⚠️  Memorized selector failed, falling back to normal flow")
        
        # Step 2: Try normal execution
        result = self.browser.execute_action(
            action_type=decision.action,
            element_id=element_id,
            value=decision.value
        )
        
        # Step 3: If successful, we're done!
        if result["success"]:
            return result
        
        # Step 4: FAILURE - Check if we should trigger Diagnostic Loop
        if not element_id or decision.action in ["wait", "scroll"]:
            # Can't diagnose actions without element_id
            return result
        
        failure_count = self.browser.get_failure_count(str(element_id))
        
        print(f"   ⚠️  Action failed (attempt {failure_count}/{self.FAILURE_THRESHOLD})")
        
        # Step 5: TRIGGER DIAGNOSTIC LOOP if threshold reached
        if failure_count >= self.FAILURE_THRESHOLD:
            print(f"\n{'🔧'*30}")
            print(f"🔧 DIAGNOSTIC LOOP ACTIVATED (Element {element_id})")
            print(f"{'🔧'*30}")
            
            # Get element profile and error details
            profile = element_profiles.get(str(element_id))
            if not profile:
                print(f"   ❌ Cannot diagnose: No profile found for element {element_id}")
                return result
            
            last_error = self.browser.get_last_error(str(element_id))
            failed_selector = profile.get_selector()
            
            print(f"   📊 DIAGNOSIS:")
            print(f"   - Failed Selector: {failed_selector}")
            print(f"   - Ground Truth: {profile}")
            print(f"   - Error: {last_error}")
            
            # Generate repair selector using Ground Truth
            print(f"\n   🧠 Asking Claude to generate repair selector...")
            repair_selector = self.brain.generate_repair_selector(
                element_profile=profile,
                failed_selector=failed_selector,
                error_message=last_error or "Unknown error"
            )
            
            if not repair_selector:
                print(f"   ❌ Failed to generate repair selector")
                return result
            
            # Try action with repair selector
            print(f"\n   🔧 Attempting action with repair selector...")
            repair_result = self.browser.execute_action(
                action_type=decision.action,
                element_id=element_id,
                value=decision.value,
                repair_selector=repair_selector
            )
            
            # If repair worked, save to memory!
            if repair_result["success"]:
                print(f"\n   ✅ REPAIR SUCCESSFUL!")
                
                # Save to memory if element has text
                if profile.text:
                    self.memory.save_repair_selector(
                        url=self.current_url,
                        element_text=profile.text,
                        tag=profile.tag,
                        repair_selector=repair_selector
                    )
                    print(f"   💾 Repair selector saved to memory for future use")
                
                print(f"{'🔧'*30}\n")
                return repair_result
            else:
                print(f"\n   ❌ Repair selector also failed: {repair_result['message']}")
                print(f"{'🔧'*30}\n")
                return repair_result
        
        # Not at threshold yet, return original failure
        return result
    
    def _build_auto_fill_goal(self, form_values: Dict[str, str], input_fields: Dict[str, str]) -> str:
        """
        Build a form-filling goal from collected values.
        Works for ANY form (login, contact, feedback, registration, etc).
        
        Args:
            form_values: Dictionary of {field_id: value} collected from user
            input_fields: Dictionary of {field_id: field_label}
            
        Returns:
            Goal string for the agent to fill the form
        """
        instructions = ["FILL THE FORM WITH PROVIDED VALUES:"]
        
        for field_id, value in form_values.items():
            field_label = input_fields.get(field_id, f"Field {field_id}")
            instructions.append(f"- Fill field [{field_id}] '{field_label}' with: '{value}' (type exactly as provided)")
        
        instructions.append("- Look for and click the Submit button (could be named 'Submit', 'Send', 'Login', 'Register', 'Continue', 'Next', etc.)")
        instructions.append("- Wait for the form to be processed and navigate to the next page")
        
        return "\n".join(instructions)
    
    def _build_auto_login_goal(self, credentials: Dict[str, str], element_profiles: Dict) -> str:
        """
        DEPRECATED: Use _build_auto_fill_goal instead.
        Kept for backward compatibility.
        """
        return self._build_auto_fill_goal(
            credentials,
            {k: k.title() for k, v in credentials.items()}  # Create simple field labels
        )
    
    def _format_action_description(self, decision: AgentDecision, result: Dict) -> str:
        """Format an action into a readable description."""
        success_emoji = "✅" if result.get("success") else "❌"
        
        if decision.action == "click":
            return f"Step {self.step_count}: {success_emoji} Clicked element {decision.element_id}"
        elif decision.action == "type":
            return f"Step {self.step_count}: {success_emoji} Typed '{decision.value}' into element {decision.element_id}"
        elif decision.action == "wait":
            return f"Step {self.step_count}: ⏳ Waited for page to load"
        elif decision.action == "scroll":
            return f"Step {self.step_count}: 📜 Scrolled down the page"
        else:
            return f"Step {self.step_count}: {decision.action}"
    
    def _get_observation_text(self, element_profiles: Dict[str, ElementProfile]) -> str:
        """
        Generate human-readable observation of what Claude saw on the page.
        
        Args:
            element_profiles: Dictionary of element profiles
            
        Returns:
            Human-readable observation text
        """
        if not element_profiles:
            return "Page has no interactive elements detected."
        
        # Count and categorize elements
        buttons = []
        inputs = []
        links = []
        
        for elem_id, profile in element_profiles.items():
            tag = profile.tag.lower()
            text = profile.text.strip()[:50]  # Truncate long text
            
            if tag == 'button' or profile.attributes.get('role') == 'button':
                buttons.append(text)
            elif tag in ['input', 'textarea', 'select']:
                field_type = profile.attributes.get('type', 'text')
                inputs.append(f"{text} (type: {field_type})")
            elif tag == 'a':
                links.append(text)
        
        observations = []
        if buttons:
            observations.append(f"Buttons: {', '.join(buttons[:3])}")
        if inputs:
            observations.append(f"Form fields: {', '.join(inputs[:3])}")
        if links:
            observations.append(f"Links: {', '.join(links[:3])}")
        
        if not observations:
            observations.append(f"Found {len(element_profiles)} interactive elements on page")
        
        return " | ".join(observations)
    
    def _get_action_text(self, decision: AgentDecision, result: Dict) -> str:
        """
        Generate human-readable description of what action was taken.
        
        Args:
            decision: The AgentDecision from Claude
            result: Result of executing the action
            
        Returns:
            Human-readable action description
        """
        action = decision.action
        
        if action == "click":
            return f"Clicked on element {decision.element_id}"
        elif action == "type":
            masked_value = decision.value if len(decision.value) < 20 else decision.value[:20] + "..."
            return f"Typed '{masked_value}' in element {decision.element_id}"
        elif action == "wait":
            if decision.need_user_input:
                return f"Requested user input for field {decision.element_id} ({decision.field_label})"
            return "Waited for page to load"
        elif action == "scroll":
            return "Scrolled page"
        elif action == "done":
            return "Marked test as done"
        else:
            return f"Performed action: {action}"
    
    def _check_for_loop(self, decision: AgentDecision) -> tuple:
        """
        Check if the system is stuck in a loop (clicking same element repeatedly).
        
        Args:
            decision: The AgentDecision just executed
            
        Returns:
            Tuple of (loop_detected: bool, loop_count: int)
        """
        # Only track click actions on elements
        if decision.action == "click" and decision.element_id:
            action_key = (str(decision.element_id), "click")
            
            # Add to recent actions (keep last N)
            self.recent_actions.append(action_key)
            if len(self.recent_actions) > 10:
                self.recent_actions.pop(0)
            
            # Count consecutive occurrences of this action
            count = 0
            for recent_action in reversed(self.recent_actions):
                if recent_action == action_key:
                    count += 1
                else:
                    break
            
            # If clicked same element 4+ times, loop detected
            if count >= self.LOOP_THRESHOLD:
                return (True, count)
        
        return (False, 0)
    
    def _ask_user_for_instruction(self) -> str:
        """
        Ask user to provide a more detailed instruction or goal clarification.
        Called when system detects it's stuck in a loop.
        
        Returns:
            New instruction from user, or empty string if cancelled
        """
        print("\n" + "="*70)
        print("🆘 HELP NEEDED - SYSTEM STUCK IN LOOP")
        print("="*70)
        print("\nThe system appears to be clicking the same element repeatedly")
        print("without making progress. This usually means:")
        print("  - The goal is unclear or too vague")
        print("  - A form field or input is required but not detected")
        print("  - The system is on the wrong page\n")
        
        print("Options:")
        print("  1. Provide a more specific instruction/goal")
        print("  2. Describe what you see on screen and what you want to do next")
        print("  3. Type 'cancel' to stop the test\n")
        
    
    def _generate_report(self, success: bool, error: str = None) -> Dict:
            # 1. Initialize with default values
            assertions = []
            summary = "No actions were recorded during the test."
            
            # 2. Generate actual data if events exist
            if self.events:
                try:
                    # Use the correct method names from assertion_engine.py
                    assertions = self.assertion_engine.generate_assertions(self.events)
                    summary = self.assertion_engine.generate_summary(assertions)
                except Exception as e:
                    print(f"⚠️ Assertion Engine failed: {e}")
                    summary = f"Test finished, but summary generation failed: {str(e)}"

            # 3. Create the report dictionary AFTER data is ready
            report = {
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "total_steps": self.step_count,
                "max_steps": self.max_steps,
                "assertions": assertions,
                "summary": summary,
                "memory_stats": self.memory.get_stats()
            }

            if error:
                report["error"] = error

            # 4. Save and Print
            report_path = Path("test_report.json")
            with open(report_path, "w") as f:
                json.dump(report, f, indent=2)

            print(f"\n{'='*60}")
            print("📊 TEST REPORT")
            print('='*60)
            print(summary)
            print('='*60)

            return report