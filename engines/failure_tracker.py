"""
FailureTracker - Tracks failed actions and detects repetitive patterns
"""
from typing import Dict, List, Optional
from collections import defaultdict

class FailureTracker:
    """
    Tracks which elements have failed and how many times.
    Detects when the agent is stuck in a loop.
    """
    
    def __init__(self):
        # Track failures per element: {"14": 3, "27": 1}
        self.element_failures: Dict[str, int] = defaultdict(int)
        
        # Track recent action history for pattern detection
        self.recent_actions: List[Dict] = []
        
        # Elements marked as "problematic" (failed 2+ times)
        self.problematic_elements: set = set()
        
        # Elements marked as "blocked" (failed 3+ times)
        self.blocked_elements: set = set()
        
    def record_failure(self, element_id: str, action_type: str, reason: str):
        """
        Record a failed action.
        
        Args:
            element_id: The element that failed
            action_type: Type of action (click, type, etc)
            reason: Why it failed
        """
        self.element_failures[element_id] += 1
        
        self.recent_actions.append({
            "element_id": element_id,
            "action": action_type,
            "result": "failed",
            "reason": reason
        })
        
        # Mark as problematic after 2 failures
        if self.element_failures[element_id] >= 2:
            self.problematic_elements.add(element_id)
        
        # Mark as blocked after 3 failures
        if self.element_failures[element_id] >= 3:
            self.blocked_elements.add(element_id)
    
    def record_success(self, element_id: str, action_type: str):
        """Record a successful action."""
        self.recent_actions.append({
            "element_id": element_id,
            "action": action_type,
            "result": "success"
        })
    
    def is_element_blocked(self, element_id: str) -> bool:
        """Check if an element has failed too many times."""
        return element_id in self.blocked_elements
    
    def is_element_problematic(self, element_id: str) -> bool:
        """Check if an element has failed multiple times."""
        return element_id in self.problematic_elements
    
    def get_failure_count(self, element_id: str) -> int:
        """Get number of times this element has failed."""
        return self.element_failures.get(element_id, 0)
    
    def detect_loop(self, window_size: int = 5) -> Optional[str]:
        """
        Detect if we're stuck in a repetitive loop.
        
        Args:
            window_size: How many recent actions to analyze
            
        Returns:
            Description of the loop if detected, None otherwise
        """
        if len(self.recent_actions) < window_size:
            return None
        
        recent = self.recent_actions[-window_size:]
        
        # Check if same element keeps failing
        failed_elements = [a["element_id"] for a in recent if a["result"] == "failed"]
        
        if len(failed_elements) >= 3:
            # Check if it's the same element
            if len(set(failed_elements[-3:])) == 1:
                element = failed_elements[-1]
                return f"Stuck in loop: Element {element} has failed {self.element_failures[element]} times in a row"
        
        return None
    
    def get_failure_summary(self) -> str:
        """
        Generate a human-readable summary of all failures.
        
        Returns:
            String summary of failures
        """
        if not self.element_failures:
            return "No failures recorded yet."
        
        summary_lines = ["FAILURE SUMMARY:"]
        
        # Blocked elements (critical)
        if self.blocked_elements:
            summary_lines.append("\n🚫 BLOCKED ELEMENTS (failed 3+ times):")
            for elem_id in sorted(self.blocked_elements):
                count = self.element_failures[elem_id]
                summary_lines.append(f"   - Element {elem_id}: Failed {count} times")
        
        # Problematic elements (warning)
        problematic_only = self.problematic_elements - self.blocked_elements
        if problematic_only:
            summary_lines.append("\n⚠️  PROBLEMATIC ELEMENTS (failed 2+ times):")
            for elem_id in sorted(problematic_only):
                count = self.element_failures[elem_id]
                summary_lines.append(f"   - Element {elem_id}: Failed {count} times")
        
        return "\n".join(summary_lines)
    
    def get_recommendations(self, element_id: str) -> List[str]:
        """
        Get recommendations for handling a problematic element.
        
        Args:
            element_id: The element to get recommendations for
            
        Returns:
            List of recommended alternative actions
        """
        failure_count = self.get_failure_count(element_id)
        
        if failure_count == 0:
            return []
        
        recommendations = []
        
        if failure_count == 1:
            recommendations.append("Try waiting for the page to fully load (action: 'wait')")
            recommendations.append("Try the same action again - might have been a timing issue")
        
        elif failure_count == 2:
            recommendations.append("Element has failed twice - try a different approach")
            recommendations.append("Check if you need to scroll to make the element visible")
            recommendations.append("Look for alternative elements that might accomplish the same goal")
        
        elif failure_count >= 3:
            recommendations.append("🚫 This element is BLOCKED after 3 failures")
            recommendations.append("MANDATORY: Try a completely different element or action")
            recommendations.append("Consider if there's a prerequisite step you missed")
            recommendations.append("Check if the page structure is different than expected")
        
        return recommendations