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
        
        # Diagnostic Loop constants
        self.FAILURE_THRESHOLD = 2  # Trigger diagnostic after 2 failures
        
    def run(self, url: str, goal: str) -> Dict:
        """
        Run the autonomous testing loop with Diagnostic Loop support.
        
        Args:
            url: Website URL to test
            goal: Testing goal description
            
        Returns:
            Dictionary with test results
        """
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
                
                # Observe: Capture current state with Ground Truth
                page = self.browser.get_page()
                
                try:
                    screenshot_path, element_profiles = self.vision.capture_state(page)
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
        
        # Add memory stats
        stats = self.memory.get_stats()
        report["memory_stats"] = stats
        
        # Save report to file
        report_path = Path("test_report.json")
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{'='*60}")
        print("📊 TEST REPORT")
        print('='*60)
        print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}")
        print(f"Steps taken: {self.step_count}/{self.max_steps}")
        print(f"Memory: {stats['total_selectors']} selectors across {stats['total_domains']} domains")
        if error:
            print(f"Error: {error}")
        print(f"\n📄 Full report saved to: {report_path}")
        print('='*60)
        
        return report