"""
BrainEngine - UPGRADED to v3.0 - Data-Driven Determinism
NOW: Sends exact element text/attributes to Claude (no more guessing from pixels!)
INCLUDES: Repair selector generation for failed actions
UPGRADED v3.1: Login page detection and credential collection support
"""
from anthropic import Anthropic
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Union, Tuple
import json
from utils.helpers import encode_image_to_base64, format_action_history
from engines.vision_engine import ElementProfile


class AgentDecision(BaseModel):
    """
    Structured format that the LLM must respond with.
    Uses Pydantic for validation.
    """
    thought: str = Field(description="Your reasoning about what to do next")
    action: str = Field(description="Action type: 'click', 'type', 'wait', 'scroll', 'ask_user', or 'done'")
    element_id: Optional[Union[int, str]] = Field(
        default=None, 
        description="ID of element to interact with (can be numeric like 1 or alphanumeric like '10a')"
    )
    value: Optional[str] = Field(default=None, description="Text to type (for 'type' action)")
    status: str = Field(default="in_progress", description="'in_progress' or 'done'")
    need_user_input: bool = Field(default=False, description="True if asking user for input for a form field")
    field_label: Optional[str] = Field(default=None, description="Label of field when asking user for input")


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
    UPGRADED: Includes login page detection for credential collection
    """
    
    def __init__(self, api_key: str):
        """
        Initialize the brain engine with API credentials.
        
        Args:
            api_key: Anthropic API key
        """
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
        self.login_detected = False
        self.credentials_needed = {}
    
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

⚠️  CRITICAL FOR CREDENTIALS: 
- FIRST: Check if the goal mentions specific credential values (username, password, OTP, email, phone, etc.)
- If YES in goal → Use EXACTLY those values WITHOUT asking the user again
- If NO in goal → ASK the user to provide the value
- Do NOT modify or interpret credentials - type them exactly as provided
- Example: If goal says "use the otp 999999" → Type 999999 when you see OTP field
- Example: If goal says "with password 'Mnrtech@123456'" → Type that when you see password field
- Example: If goal does NOT mention OTP → Ask the user "What OTP should I enter?"
- Special characters are important - include all symbols, numbers, and letters exactly

🔍 NAVIGATION FIRST APPROACH:
- Your job is to NAVIGATE to find the right page/section based on your goal
- Look for navigation menus, links, buttons that match your goal
- Example: Goal is "contact these guys" → Look for "Contact", "Get in Touch", "Contact Us" button/link
- Click and navigate FIRST before asking to fill forms
- Fill forms ONLY after you reach the right destination

📝 CRITICAL: HANDLING ALL FORM FIELDS (generalized for any input):
- For ANY text input field (email, username, OTP, phone, name, message, etc.):
  1. FIRST: Check if the GOAL mentions the value for this field
  2. If YES → Use that value from the goal
  3. If NO → Ask the user to provide the value
- Do NOT guess or auto-fill values
- Do NOT use placeholder values (like "123456" in an OTP field)
- Do NOT skip asking the user
- Use need_user_input: true with the actual element_id to ask the user
- Examples of this working across different websites:
  - Website A: OTP field → Goal says "use otp 999999" → Type 999999
  - Website B: OTP field → Goal doesn't mention OTP → Ask user "What OTP should I enter?"
  - Website C: Password field → Goal says "password 'secret123'" → Type secret123
  - Website D: Password field → Goal doesn't mention password → Ask user "What is your password?"
  - Website E: Message field → Goal doesn't mention message → Ask user "What message do you want to send?"
  - Website F: Dropdown → Goal doesn't mention selection → Ask user "Which option should I select?"

RESPONSE FORMAT (strict JSON only):
{{
    "thought": "Brief explanation of your reasoning",
    "action": "click|type|wait|scroll|done",
    "element_id": 12,
    "value": "text to type (only for 'type' action)",
    "status": "in_progress|done",
    "need_user_input": false
}}

⚠️  SPECIAL: ASK FOR USER INPUT BEFORE FILLING ANY FORM FIELD:
- NEVER fill text fields, textareas, otp, or dropdowns without user input
- FIRST: Identify the field (get its element_id and label)
- THEN: Ask the user what to fill
- THEN: Use their response to fill the field
- Examples of correct flow:
  1. See Name field (element 10) → Ask "What is your name?"
  2. See Message textarea (element 15) → Ask "What message do you want to send?"
  3. See Service dropdown (element 14) → Ask "Which service are you interested in?"
  
Correct response when encountering a form field:
{{
    "thought": "I found the Name field (element 10). I need to ask the user what name to enter.",
    "action": "wait",
    "element_id": "10",
    "field_label": "Name",
    "status": "in_progress",
    "need_user_input": true
}}

NEVER respond like this (WRONG - auto-filling):
{{
    "thought": "I'll type a default name",
    "action": "type",
    "element_id": "10",
    "value": "John Doe"  # ❌ WRONG! Don't guess!
}}

RULES:
1. ONLY output valid JSON - no markdown code blocks, no extra text
2. Use "done" action when the goal is achieved or impossible
3. Set status to "done" when you've completed the task
4. NAVIGATE FIRST: Click navigation links to get to the right page - this is your priority
5. After navigating, WAIT for page to load (wait action), then capture the new state
6. ⭐ ALWAYS ask user for input before filling ANY form field:
   - Text fields → Ask what to enter
   - Textareas → Ask what message to send
   - Dropdowns/Select → Ask which option to select
   - DO NOT auto-fill or guess values
7. Only fill form fields with values that the user provided
8. If an element is covered or not clickable, try a different approach
9. Be patient - wait for pages to load when needed
10. Trust the provided element text data over visual interpretation
11. CRITICAL: If multiple elements have the same text, use repair selectors or unique identifiers
12. When asking for user input: element_id MUST be a valid number or string, NEVER null/None
13. Don't fill form fields until you have explicitly asked the user and received their input
14. FOR CREDENTIAL FIELDS: When typing passwords or sensitive data, always use the EXACT value from the goal
15. FLOW: Navigate → Wait → Observe Form → Ask for Each Field → Fill with User Values → Submit

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
    
    def detect_input_form(self, 
                         element_profiles: Dict[str, ElementProfile],
                         screenshot_path: str = None) -> tuple:
        """
        Detect any form with input fields on the page (login, contact, feedback, etc).
        Analyzes labels, placeholders, and field names to understand what each field is asking for.
        
        Args:
            element_profiles: Dictionary of element profiles
            screenshot_path: Optional path to screenshot for additional context
            
        Returns:
            Tuple of (has_input_form, input_fields_dict)
            where input_fields_dict = {field_id: field_label/description}
        """
        input_fields = {}
        
        # Scan for all input fields
        for elem_id, profile in element_profiles.items():
            tag = profile.tag.lower()
            
            # Look for input fields or textareas
            if tag in ['input', 'textarea', 'select']:
                input_type = profile.attributes.get('type', 'text').lower()
                
                # Skip buttons, hidden fields, etc
                if input_type in ['button', 'submit', 'hidden', 'checkbox', 'radio']:
                    continue
                
                # Try to get field label
                field_label = self._extract_field_label(elem_id, profile, element_profiles)
                
                if field_label:
                    input_fields[str(elem_id)] = field_label
        
        # If we found input fields, treat it as a form that needs filling
        has_form = len(input_fields) > 0
        
        return has_form, input_fields
    
    def _extract_field_label(self, elem_id: str, profile: ElementProfile, 
                            element_profiles: Dict[str, ElementProfile]) -> str:
        """
        Extract what a field is asking for by looking at:
        1. Placeholder text
        2. Field name attribute
        3. Label text nearby
        4. Aria-label
        
        Args:
            elem_id: Element ID
            profile: Element profile
            element_profiles: All element profiles (to find nearby labels)
            
        Returns:
            Human-readable field description
        """
        # Priority 1: Placeholder text (most explicit)
        placeholder = profile.attributes.get('placeholder', '').strip()
        if placeholder:
            return placeholder
        
        # Priority 2: aria-label
        aria_label = profile.attributes.get('aria-label', '').strip()
        if aria_label:
            return aria_label
        
        # Priority 3: Field name attribute
        name = profile.attributes.get('name', '').strip()
        if name:
            # Clean up field names like "user_email" -> "User Email"
            cleaned_name = name.replace('_', ' ').replace('-', ' ').title()
            return cleaned_name
        
        # Priority 4: Look for nearby label elements
        input_type = profile.attributes.get('type', 'text').lower()
        
        # Common field type patterns
        type_hints = {
            'email': 'Email address',
            'password': 'Password',
            'tel': 'Phone number',
            'number': 'Number',
            'date': 'Date',
            'url': 'Website URL'
        }
        
        if input_type in type_hints:
            return type_hints[input_type]
        
        # Default for text fields
        return 'Text'
    
    def detect_login_page(self, 
                         element_profiles: Dict[str, ElementProfile],
                         screenshot_path: str = None) -> tuple:
        """
        DEPRECATED: Use detect_input_form instead.
        Kept for backward compatibility.
        """
        return self.detect_input_form(element_profiles, screenshot_path)
    
    def ask_user_for_credentials(self) -> Dict[str, str]:
        """
        DEPRECATED: Use ask_user_for_form_values instead.
        Kept for backward compatibility.
        """
        from test_modes import TestModeHandler
        return TestModeHandler.ask_for_credentials("Form detected")
    
    def ask_user_for_form_values(self, input_fields: Dict[str, str]) -> Dict[str, str]:
        """
        Ask user to provide values for detected input fields.
        Works for ANY form (login, contact, feedback, etc).
        
        Args:
            input_fields: Dictionary of {field_id: field_label}
            Example: {'1': 'Email address', '2': 'Password', '3': 'Message'}
            
        Returns:
            Dictionary of {field_id: user_value}
        """
        from test_modes import TestModeHandler
        return TestModeHandler.ask_for_form_values(input_fields)
    
    def generate_floor_plan(self, goal: str) -> List[str]:
        """
        Generate floor plan by parsing the goal string directly.
        Extracts steps from natural language instructions.
        
        Args:
            goal: The testing goal/intention with instructions
            Example: "then go to Virtual Lab Module Select class as 10 and then select Chemistry..."
            
        Returns:
            List of extracted steps from the goal
        """
        import re
        
        steps = []
        
        # Clean up the goal text
        goal_cleaned = goal.strip()
        
        # Split by common connectors: "then", "and then", "next", "after that"
        # This keeps the action text intact
        delimiters = r'\b(?:then|and then|next|after that|finally|first|then|step \d+:?)\b'
        parts = re.split(delimiters, goal_cleaned, flags=re.IGNORECASE)
        
        # Process each part
        for part in parts:
            part = part.strip()
            
            # Skip empty parts
            if not part:
                continue
            
            # Remove common phrases and clean up
            part = re.sub(r'^\s*[,\s]+', '', part)  # Remove leading punctuation/spaces
            part = part.strip()
            
            if part:
                # Capitalize first letter if needed
                if part and part[0].islower():
                    part = part[0].upper() + part[1:]
                
                # Remove trailing "and" or "then"
                part = re.sub(r'\s+(?:and|then|or)\s*$', '', part, flags=re.IGNORECASE)
                
                if part:
                    steps.append(part)
        
        # If parsing didn't extract steps well, fall back to sentence splitting
        if len(steps) < 2:
            steps = []
            # Split by periods or multiple spaces indicating separate instructions
            sentences = re.split(r'[.!?]+|\s{2,}', goal_cleaned)
            for sent in sentences:
                sent = sent.strip()
                if sent and len(sent) > 3:
                    if sent and sent[0].islower():
                        sent = sent[0].upper() + sent[1:]
                    steps.append(sent)
        
        # If still no steps, return the goal as a single step
        if not steps:
            steps = [goal_cleaned if goal_cleaned else "Execute the provided goal"]
        
        return steps
