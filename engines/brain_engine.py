"""
BrainEngine - Handles communication with Claude LLM for decision making
"""
from anthropic import Anthropic
from pydantic import BaseModel, Field
from typing import Optional, List, Dict,Union
import json
from utils.helpers import encode_image_to_base64, format_action_history


class AgentDecision(BaseModel):
    """
    Structured format that the LLM must respond with.
    Uses Pydantic for validation.
    """
    thought: str = Field(description="Your reasoning about what to do next")
    action: str = Field(description="Action type: 'click', 'type', 'wait', 'scroll', or 'done'")
    # element_id: Optional[str] = Field(default=None, description="ID of element to interact with")
    element_id: Optional[Union[int, str]] = Field(
    default=None, 
    description="ID of element to interact with (can be numeric like 1 or alphanumeric like '10a')"
)
    value: Optional[str] = Field(default=None, description="Text to type (for 'type' action)")
    status: str = Field(default="in_progress", description="'in_progress' or 'done'")


class BrainEngine:
    """
    Communicates with Claude API to make testing decisions.
    Enforces structured JSON responses.
    """
    
    def __init__(self, api_key: str):
        """
        Initialize the brain engine with API credentials.
        
        Args:
            api_key: Anthropic API key
        """
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
    
    def decide_next_action(self, 
                          screenshot_path: str,
                          element_map: Dict[int, str],
                          action_history: List[str],
                          goal: str,
                          max_steps: int,
                          current_step: int,
                          failure_tracker = None) ->   AgentDecision:
        """
        Ask Claude to decide what to do next based on the current state.
        
        Args:
            screenshot_path: Path to the current screenshot
            element_map: Dictionary of available element IDs
            action_history: List of previous actions taken
            goal: The testing goal
            max_steps: Maximum number of steps allowed
            current_step: Current step number
            
        Returns:
            AgentDecision object with the LLM's decision
        """
        try:
            # Encode the screenshot
            image_base64 = encode_image_to_base64(screenshot_path)
            
            # Build the system prompt
            failure_summary = None
            if failure_tracker:
                failure_summary = failure_tracker.get_failure_summary()
                
                # Add specific recommendations for problematic elements
                if failure_tracker.problematic_elements or failure_tracker.blocked_elements:
                    failure_summary += "\n\n"
                    for elem_id in failure_tracker.problematic_elements | failure_tracker.blocked_elements:
                        recommendations = failure_tracker.get_recommendations(elem_id)
                        if recommendations:
                            failure_summary += f"\nElement {elem_id} recommendations:\n"
                            for rec in recommendations:
                                failure_summary += f"  • {rec}\n"

            # Build the system prompt WITH failure context
            system_prompt = self._build_system_prompt(goal, max_steps, current_step, failure_summary)
            
            # Build the user message
            user_message = self._build_user_message(
                image_base64, 
                element_map, 
                action_history
            )
            
            print(f"🧠 Asking Claude to decide next action...")
            
            # Call Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            
            # Extract the text response
            response_text = response.content[0].text
            print(f"   Claude's response: {response_text[:200]}...")
            
            # Parse JSON response
            decision_data = json.loads(response_text)
            decision = AgentDecision(**decision_data)
            
            print(f"   💭 Thought: {decision.thought}")
            print(f"   🎯 Action: {decision.action}")
            
            return decision
            
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse LLM response as JSON: {str(e)}")
            print(f"   Raw response: {response_text}")
            # Return a default "wait" decision if parsing fails
            return AgentDecision(
                thought="Failed to parse response, waiting...",
                action="wait",
                status="in_progress"
            )
        
        except Exception as e:
            print(f"❌ Error calling LLM: {str(e)}")
            return AgentDecision(
                thought=f"Error occurred: {str(e)}",
                action="done",
                status="error"
            )
    
    def _build_system_prompt(self, goal: str, max_steps: int, current_step: int, 
                         failure_summary: str = None) -> str:
    
        base_prompt = f"""You are an expert QA testing agent. Your job is to test websites by interacting with them like a human would.

    TESTING GOAL: {goal}

    CURRENT PROGRESS: Step {current_step}/{max_steps}

    YOUR CAPABILITIES:
    - You can see screenshots of web pages with numbered red boxes on interactive elements
    - You can click elements, type text, wait for pages to load, or scroll
    - You must respond ONLY with valid JSON (no markdown, no explanations outside JSON)

    RESPONSE FORMAT (strict JSON only):
    {{
        "thought": "Brief explanation of your reasoning",
        "action": "click|type|wait|scroll|done",
        "element_id": 12,
        "value": "text to type (only for 'type' action)",
        "status": "in_progress|done"
    }}

    RULES:
    1. ONLY output valid JSON - no markdown code blocks, no extra text
    2. Use "done" action when the goal is achieved or impossible
    3. Set status to "done" when you've completed the task
    4. If an element is covered or not clickable, try a different approach
    5. Be patient - wait for pages to load when needed
    6. Look at the screenshot carefully before deciding"""

        # ADD FAILURE CONTEXT IF AVAILABLE
        if failure_summary:
            base_prompt += f"""

    ⚠️  IMPORTANT - PREVIOUS FAILURES DETECTED:
    {failure_summary}

    CRITICAL INSTRUCTIONS WHEN FAILURES ARE PRESENT:
    - DO NOT repeat the same action on blocked elements (failed 3+ times)
    - If you want to interact with a problematic element, explain why this time will be different
    - Consider alternative approaches: different elements, scrolling, waiting, or different sequence of actions
    - If stuck, try exploring other parts of the page or report the blocking issue"""

        return base_prompt

    def _build_user_message(self, 
                           image_base64: str,
                           element_map: Dict[int, str],
                           action_history: List[str]) -> List[Dict]:
        """Build the user message with image and context."""
        
        # Format available elements
        available_elements = "\n".join([
            f"  ID {elem_id}: {xpath[:80]}..." 
            for elem_id, xpath in sorted(element_map.items())
        ])
        
        # Format history
        history_text = format_action_history(action_history) if action_history else "No previous actions"
        
        # Build the message
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_base64
                }
            },
            {
                "type": "text",
                "text": f"""Here is the current state of the webpage.

AVAILABLE ELEMENTS (numbered in red boxes on the image):
{available_elements}

PREVIOUS ACTIONS:
{history_text}

What should I do next to achieve the goal? Respond with JSON only."""
            }
        ]
        
        return content
