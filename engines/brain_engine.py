"""
BrainEngine - UPGRADED to v3.0 - Data-Driven Determinism
NOW: Sends exact element text/attributes to Claude (no more guessing from pixels!)
INCLUDES: Repair selector generation for failed actions
"""
from anthropic import Anthropic
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Union
import json
from utils.helpers import encode_image_to_base64, format_action_history
from engines.vision_engine import ElementProfile


class AgentDecision(BaseModel):
    """
    Structured format that the LLM must respond with.
    Uses Pydantic for validation.
    """
    thought: str = Field(description="Your reasoning about what to do next")
    action: str = Field(description="Action type: 'click', 'type', 'wait', 'scroll', or 'done'")
    element_id: Optional[Union[int, str]] = Field(
        default=None, 
        description="ID of element to interact with (can be numeric like 1 or alphanumeric like '10a')"
    )
    value: Optional[str] = Field(default=None, description="Text to type (for 'type' action)")
    status: str = Field(default="in_progress", description="'in_progress' or 'done'")


class RepairSelector(BaseModel):
    """
    Structured format for Claude's repair selector generation.
    """
    reasoning: str = Field(description="Why the original selector failed")
    xpath_selector: str = Field(description="New XPath selector using normalize-space()")
    css_fallback: Optional[str] = Field(default=None, description="Optional CSS fallback selector")


class BrainEngine:
    """
    Communicates with Claude API to make testing decisions.
    VERSION 3.0: Uses Ground Truth element profiles instead of visual guessing.
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
                          element_profiles: Dict[str, ElementProfile],
                          action_history: List[str],
                          goal: str,
                          max_steps: int,
                          current_step: int) -> AgentDecision:
        """
        Ask Claude to decide what to do next based on Ground Truth data.
        
        Args:
            screenshot_path: Path to the current screenshot
            element_profiles: Dictionary of element IDs to ElementProfile objects
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
            system_prompt = self._build_system_prompt(goal, max_steps, current_step)
            
            # Build the user message with Ground Truth data
            user_message = self._build_user_message(
                image_base64, 
                element_profiles,  # Now passing profiles, not just selectors!
                action_history
            )
            
            print(f"🧠 Asking Claude to decide next action (using Ground Truth data)...")
            
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
    
    def generate_repair_selector(self,
                                 element_profile: ElementProfile,
                                 failed_selector: str,
                                 error_message: str) -> Optional[str]:
        """
        UPGRADE C: Generate a repair selector using Ground Truth data.
        Uses XPath with normalize-space() to handle whitespace issues.
        
        Args:
            element_profile: The ElementProfile with exact text/attributes
            failed_selector: The selector that failed
            error_message: The error message from the failure
            
        Returns:
            New XPath selector string, or None if generation fails
        """
        try:
            print(f"🔧 Generating repair selector for failed element...")
            print(f"   Failed selector: {failed_selector}")
            print(f"   Ground Truth: {element_profile}")
            
            # Build repair prompt
            system_prompt = """You are an expert at generating robust XPath selectors.
Your task is to create a selector that will reliably find an element using its exact text content.

CRITICAL RULES:
1. Use XPath with normalize-space() to handle whitespace issues
2. The normalize-space() function removes leading/trailing whitespace and collapses multiple spaces
3. Use contains() for partial text matching when appropriate
4. Prefer //tagname[normalize-space()='exact text'] format

Return ONLY valid JSON with this structure:
{
    "reasoning": "Brief explanation of why the original failed",
    "xpath_selector": "//button[normalize-space()='Class 10']",
    "css_fallback": "button.class-btn (optional)"
}"""

            user_prompt = f"""The agent tried to interact with an element but failed.

FAILED SELECTOR: {failed_selector}

ERROR MESSAGE: {error_message}

GROUND TRUTH DATA (from actual DOM):
- Tag: {element_profile.tag}
- Exact Text: "{element_profile.text}"
- Attributes: {json.dumps(element_profile.attributes, indent=2)}

Generate a robust XPath selector using normalize-space() that will match this element reliably.
Focus on the exact text "{element_profile.text}" from the Ground Truth data."""

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            response_text = response.content[0].text
            repair_data = json.loads(response_text)
            repair = RepairSelector(**repair_data)
            
            print(f"   ✅ Generated repair selector: {repair.xpath_selector}")
            print(f"   💭 Reasoning: {repair.reasoning}")
            
            return repair.xpath_selector
            
        except Exception as e:
            print(f"❌ Failed to generate repair selector: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _build_system_prompt(self, goal: str, max_steps: int, current_step: int) -> str:
        """Build the system prompt that defines the agent's role."""
        return f"""You are an expert QA testing agent. Your job is to test websites by interacting with them like a human would.

TESTING GOAL: {goal}

CURRENT PROGRESS: Step {current_step}/{max_steps}

YOUR CAPABILITIES:
- You can see screenshots of web pages with numbered red boxes on interactive elements
- You receive EXACT TEXT CONTENT for each element (no guessing from pixels needed!)
- You can click elements, type text, wait for pages to load, or scroll
- You must respond ONLY with valid JSON (no markdown, no explanations outside JSON)

CRITICAL: USE THE EXACT TEXT PROVIDED IN THE ELEMENT DATA
- Each element has a "text" field showing the EXACT text from the DOM
- Do NOT try to read text from the screenshot - use the provided text data
- Example: If element 14 shows text="Class 10", that is the EXACT text with the space
- This eliminates ambiguity from visual guessing

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
6. Trust the provided element text data over visual interpretation
7. CRITICAL: If multiple elements have the same text (e.g., "Launch Experiment →"), you MUST use a unique selector.
8. To target a specific element among many identical ones, describe its position (e.g., "the first one") in your thought and use the exact element_id assigned to it.
9. If a direct text click fails, look for unique parent containers or sibling text to distinguish the target.

Remember: Your ENTIRE response must be valid JSON and nothing else."""

    def _build_user_message(self, 
                           image_base64: str,
                           element_profiles: Dict[str, ElementProfile],
                           action_history: List[str]) -> List[Dict]:
        """
        Build the user message with image and Ground Truth element data.
        VERSION 3.0: Now includes complete element profiles with exact text.
        """
        
        # Format available elements WITH GROUND TRUTH DATA
        available_elements = []
        for elem_id, profile in sorted(element_profiles.items()):
            # Create human-readable profile string
            profile_str = profile.get_display_text()
            available_elements.append(f"  ID {elem_id}: {profile_str}")
        
        elements_text = "\n".join(available_elements)
        
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

AVAILABLE ELEMENTS (Ground Truth Data):
The screenshot shows red numbered boxes. Here is the EXACT data for each element:

{elements_text}

IMPORTANT: 
- Use the EXACT text shown above, not what you see in the screenshot!
For example, if ID 14 shows 'text="Class 10"', the actual text is "Class 10" (with space).
- If you see multiple elements with the same text in the list above, do not use a generic selector. 
Pick the specific element_id that corresponds to the correct item (e.g., if you want the first experiment, pick the ID of its specific button).

PREVIOUS ACTIONS:
{history_text}

What should I do next to achieve the goal? Respond with JSON only."""
            }
        ]
        
        return content