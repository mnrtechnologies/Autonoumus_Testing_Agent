"""
Orchestrator - Main control loop that coordinates all engines
UPDATED: Better error handling for alphanumeric element IDs
"""
from engines.browser_engine import BrowserEngine
from engines.vision_engine import VisionEngine
from engines.brain_engine import BrainEngine, AgentDecision
from typing import List, Dict
import json
from datetime import datetime
from pathlib import Path
from engines.failure_tracker import FailureTracker
from engines.diagnostic_engine import DiagnosticEngine


class Orchestrator:
    """
    The main controller that runs the testing loop.
    Coordinates Browser, Vision, and Brain engines to autonomously test a website.
    """
    
    def __init__(self, api_key: str, headless: bool = False):
        """
        Initialize the orchestrator with all engines.
        
        Args:
            api_key: Anthropic API key for Claude
            headless: Whether to run browser in headless mode
        """
        self.browser = BrowserEngine(headless=headless)
        self.failure_tracker = FailureTracker()
        self.vision = VisionEngine()
        self.brain = BrainEngine(api_key=api_key)
        self.diagnostic = DiagnosticEngine(api_key=api_key)
        self.diagnostic_mode = True 
        
        self.action_history: List[str] = []
        self.step_count = 0
        self.max_steps = 50  # Safety limit

    def _retry_with_new_selector(self, decision, new_selector: str) -> Dict:
        """
        Retry an action with a different selector.
        
        Args:
            decision: Original AgentDecision
            new_selector: New selector to try
            
        Returns:
            Result dictionary
        """
        try:
            # Temporarily update the element map
            temp_element_map = self.browser.element_map.copy()
            temp_element_map[str(decision.element_id)] = new_selector
            
            # Swap in the new map
            old_map = self.browser.element_map
            self.browser.element_map = temp_element_map
            
            # Try the action
            result = self.browser.execute_action(
                action_type=decision.action,
                element_id=decision.element_id,
                value=decision.value
            )
            
            # Restore old map if it didn't work
            if not result.get("success"):
                self.browser.element_map = old_map
            
            return result
            
        except Exception as e:
            return {"success": False, "message": str(e)}    
    def run(self, url: str, goal: str) -> Dict:
        """
        Run the autonomous testing loop.
        
        Args:
            url: Website URL to test
            goal: Testing goal description
            
        Returns:
            Dictionary with test results
        """
        print("=" * 60)
        print("🤖 ROBO-TESTER STARTING")
        print("=" * 60)
        print(f"🎯 Goal: {goal}")
        print(f"🌐 URL: {url}")
        print(f"📊 Max steps: {self.max_steps}")
        print("=" * 60)
        
        # Step 1: Initialize browser
        if not self.browser.start(url):
            return self._generate_report(success=False, error="Failed to start browser")
        
        try:
            # Step 2: Main testing loop
            while self.step_count < self.max_steps:
                self.step_count += 1
                print(f"\n{'='*60}")
                print(f"STEP {self.step_count}/{self.max_steps}")
                print('='*60)
                
                # Observe: Capture current state
                page = self.browser.get_page()
                
                try:
                    screenshot_path, element_map = self.vision.capture_state(page)
                except Exception as capture_error:
                    print(f"❌ Error capturing state: {str(capture_error)}")
                    import traceback
                    traceback.print_exc()
                    print("⚠️  Waiting and retrying...")
                    self.action_history.append(f"Step {self.step_count}: Failed to capture state - {str(capture_error)}")
                    continue
                
                if not screenshot_path or not element_map:
                    print("⚠️  Failed to capture state, waiting and retrying...")
                    self.action_history.append(f"Step {self.step_count}: Failed to capture state")
                    continue
                
                # Update browser with new element map
                try:
                    self.browser.update_element_map(element_map)
                except Exception as update_error:
                    print(f"❌ Error updating element map: {str(update_error)}")
                    import traceback
                    traceback.print_exc()
                    continue
                
                # Think: Ask Claude what to do
                try:
                    decision = self.brain.decide_next_action(
                        screenshot_path=screenshot_path,
                        element_map=element_map,
                        action_history=self.action_history,
                        goal=goal,
                        max_steps=self.max_steps,
                        current_step=self.step_count,
                        failure_tracker=self.failure_tracker
                    )
                except Exception as brain_error:
                    print(f"❌ Error getting decision from Claude: {str(brain_error)}")
                    import traceback
                    traceback.print_exc()
                    continue
                
                # Check if done
                if decision.action == "done" or decision.status == "done":
                    print(f"\n✅ Testing complete! Reason: {decision.thought}")
                    self.action_history.append(
                        f"Step {self.step_count}: Completed - {decision.thought}"
                    )
                    return self._generate_report(success=True)
                
                # Act: Execute the decision
                # try:
                #     result = self._execute_decision(decision)
                # except Exception as action_error:
                #     print(f"❌ Error executing action: {str(action_error)}")
                #     import traceback
                #     traceback.print_exc()
                #     result = {"success": False, "message": str(action_error)}
                
                # # Record the action
                # action_description = self._format_action_description(decision, result)
                # self.action_history.append(action_description)
                
                # CHECK: Is this element blocked?
                if decision.element_id:
                    if self.failure_tracker.is_element_blocked(str(decision.element_id)):
                        print(f"⚠️  WARNING: Element {decision.element_id} is BLOCKED (failed 3+ times)")
                        print(f"   Asking Claude to find alternative approach...")
                        continue  # Skip to next iteration
                
                # Act: Execute the decision
                try:
                    result = self._execute_decision(decision)
                except Exception as action_error:
                    print(f"❌ Error executing action: {str(action_error)}")
                    import traceback
                    traceback.print_exc()
                    result = {"success": False, "message": str(action_error)}
                
                # ============================================
                # INITIALIZE action_description HERE (before any continue statements)
                # ============================================
                action_description = self._format_action_description(decision, result)
                
                # Track the result
                if result.get("success"):
                    if decision.element_id:
                        self.failure_tracker.record_success(str(decision.element_id), decision.action)
                else:
                    if decision.element_id:
                        self.failure_tracker.record_failure(
                            str(decision.element_id), 
                            decision.action,
                            result.get("message", "Unknown error")
                        )
                    
                    # ============================================
                    # 🆕 NEW: TRIGGER DIAGNOSTIC ENGINE ON FAILURE
                    # ============================================
                    if self.diagnostic_mode and decision.element_id:
                        print(f"\n🔍 DIAGNOSTIC MODE: Analyzing failure for element {decision.element_id}...")
                        
                        # Get the selector that failed
                        failed_selector = self.browser.element_map.get(str(decision.element_id))
                        
                        if failed_selector:
                            # Run diagnostic analysis
                            diagnostic_result = self.diagnostic.diagnose_failure(
                                page=self.browser.get_page(),
                                element_id=str(decision.element_id),
                                failed_selector=failed_selector,
                                error_message=result.get("message", "Unknown error")
                            )
                            
                            # If we got diagnostic suggestions, add them to history
                            if diagnostic_result:
                                diagnostic_msg = f"\n🔍 DIAGNOSTIC ANALYSIS for element {decision.element_id}:\n"
                                diagnostic_msg += f"  📋 Diagnosis: {diagnostic_result.diagnosis}\n"
                                diagnostic_msg += f"  🎯 Root cause: {diagnostic_result.root_cause}\n"
                                diagnostic_msg += f"  💪 Confidence: {diagnostic_result.confidence}\n"
                                
                                if diagnostic_result.suggested_selectors:
                                    diagnostic_msg += f"\n  💡 Suggested alternative selectors:\n"
                                    for i, suggestion in enumerate(diagnostic_result.suggested_selectors[:3], 1):
                                        diagnostic_msg += f"    {i}. {suggestion['selector']} "
                                        diagnostic_msg += f"(reliability: {suggestion['reliability']})\n"
                                        diagnostic_msg += f"       Reason: {suggestion['reason']}\n"
                                
                                print(diagnostic_msg)
                                self.action_history.append(diagnostic_msg)
                                
                                # Optional: Try the best suggested selector automatically
                                if diagnostic_result.confidence == "high" and diagnostic_result.suggested_selectors:
                                    best_selector = diagnostic_result.suggested_selectors[0]['selector']
                                    print(f"\n🔄 Auto-retry: Trying best suggested selector: {best_selector}")
                                    
                                    retry_result = self._retry_with_new_selector(decision, best_selector)
                                    
                                    if retry_result.get("success"):
                                        print(f"   ✅ SUCCESS with diagnostic suggestion!")
                                        result = retry_result  # Update result to success
                                        # Update action_description to reflect the retry success
                                        action_description = f"Step {self.step_count}: ✅ Clicked element {decision.element_id} (succeeded with diagnostic retry)"
                                        self.action_history.append(action_description)
                                        # Update the element map with the working selector
                                        self.browser.element_map[str(decision.element_id)] = best_selector
                                        # Record success in failure tracker
                                        self.failure_tracker.record_success(str(decision.element_id), decision.action)
                                    else:
                                        print(f"   ❌ Retry also failed: {retry_result.get('message')}")
                            else:
                                print("   ⚠️  Diagnostic analysis did not produce suggestions")
                    
                    # If there's failure context from browser_engine, add it to history
                    if result.get("failure_context"):
                        context = result["failure_context"]
                        context_msg = f"\n⚠️ Element {decision.element_id} FAILURE CONTEXT:\n"
                        context_msg += f"  • Tried selector: {context.get('failed_selector')}\n"
                        context_msg += f"  • Searched for text: '{context.get('searched_for')}'\n"
                        context_msg += f"  • Found {len(context.get('similar_elements', []))} similar elements on page\n"
                        
                        for idx, elem in enumerate(context.get('similar_elements', [])[:2], 1):
                            context_msg += f"\n    Element {idx}:\n"
                            context_msg += f"      - innerText: '{elem.get('innerText')}'\n"
                            context_msg += f"      - textContent: '{elem.get('textContent')}'\n"
                            context_msg += f"      - visible: {elem.get('visible')}\n"
                        
                        if context.get('similar_elements'):
                            context_msg += "\n💡 The actual text on the page may differ from what you're searching for!\n"
                        
                        print(context_msg)
                        self.action_history.append(context_msg)
                
                # Check for loops
                loop_detected = self.failure_tracker.detect_loop()
                if loop_detected:
                    print(f"\n🔄 {loop_detected}")
                    print(self.failure_tracker.get_failure_summary())
                    
                    should_continue = self._handle_stuck_situation(goal, self.step_count)
                    if not should_continue:
                        print("\n❌ Claude determined the goal is not achievable with current approach")
                        return self._generate_report(
                            success=False,
                            error="Agent stuck in loop - no viable alternative found"
                        )
                
                # Record and print the action (action_description already initialized above)
                self.action_history.append(action_description)
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
            self.browser.cleanup()
    
    def _handle_stuck_situation(self, goal: str, current_step: int) -> bool:
        """
        Called when agent appears stuck in a loop.
        Asks Claude for a strategic re-evaluation.
        
        Returns:
            True if should continue, False if should abort
        """
        print("\n" + "="*60)
        print("🔄 STUCK LOOP DETECTED - REQUESTING STRATEGIC RE-EVALUATION")
        print("="*60)
        
        failure_summary = self.failure_tracker.get_failure_summary()
        
        print(failure_summary)
        print("\nAsking Claude to analyze the situation and suggest alternatives...")
        
        # Take a fresh screenshot
        page = self.browser.get_page()
        screenshot_path, element_map = self.vision.capture_state(page)
        
        if not screenshot_path:
            return False
        
        # Update element map
        self.browser.update_element_map(element_map)
        
        # Ask Claude for strategic thinking
        strategic_prompt = f"""
    SITUATION ANALYSIS REQUIRED

    You have been trying to accomplish this goal: {goal}

    However, you appear to be stuck. Here's what happened:

    {failure_summary}

    Recent action history:
    {chr(10).join(self.action_history[-10:])}

    Current step: {current_step}

    IMPORTANT: Look at the current screenshot and answer these questions in your JSON response:

    1. In "thought": Explain WHY you think the previous approach failed
    2. In "action": Suggest a COMPLETELY DIFFERENT approach (not the same failed action)
    3. Consider: 
    - Is there an alternative element to try?
    - Should you try a different sequence of actions?
    - Is there a prerequisite step you missed?
    - Should you report this as a blocking issue?

    You MUST try something different than what failed before.
    """

        # This is a strategic decision, so we'll modify the system prompt temporarily
        original_decide = self.brain.decide_next_action
        
        try:
            # Get strategic decision
            decision = self.brain.decide_next_action(
                screenshot_path=screenshot_path,
                element_map=element_map,
                action_history=[strategic_prompt],  # Override with strategic prompt
                goal=goal,
                max_steps=self.max_steps,
                current_step=current_step,
                failure_tracker=self.failure_tracker
            )
            
            print(f"\n💡 Claude's strategic analysis:")
            print(f"   {decision.thought}")
            print(f"   Suggested action: {decision.action}")
            
            if decision.action == "done":
                return False  # Claude says it's impossible
            
            return True  # Continue with new strategy
            
        except Exception as e:
            print(f"❌ Strategic analysis failed: {str(e)}")
            return False
    def _execute_decision(self, decision: AgentDecision) -> Dict:
        """
        Execute the action decided by the brain.
        
        Args:
            decision: The AgentDecision from Claude
            
        Returns:
            Result dictionary from browser engine
        """
        return self.browser.execute_action(
            action_type=decision.action,
            element_id=decision.element_id,
            value=decision.value
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
    
    def _generate_report(self, success: bool, error: str = None) -> Dict:
        """
        Generate a final test report.
        
        Args:
            success: Whether the test succeeded
            error: Error message if failed
            
        Returns:
            Report dictionary
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "total_steps": self.step_count,
            "max_steps": self.max_steps,
            "action_history": self.action_history,
        }
        
        if error:
            report["error"] = error
        
        # Save report to file
        report_path = Path("test_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{'='*60}")
        print("📊 TEST REPORT")
        print('='*60)
        print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}")
        print(f"Steps taken: {self.step_count}/{self.max_steps}")
        if error:
            print(f"Error: {error}")
        print(f"\n📄 Full report saved to: {report_path}")
        print('='*60)
        
        return report