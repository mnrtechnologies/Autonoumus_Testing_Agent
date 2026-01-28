"""
DiagnosticEngine - Uses LLM to diagnose why element interactions fail
"""
from anthropic import Anthropic
from playwright.sync_api import Page
from typing import Dict, List, Optional
import json


class ElementDiagnostic:
    """Stores diagnostic information about a failed element interaction."""
    
    def __init__(self, element_id: str, selector: str, error_message: str):
        self.element_id = element_id
        self.selector = selector
        self.error_message = error_message
        self.element_html: Optional[str] = None
        self.inner_text: Optional[str] = None
        self.text_content: Optional[str] = None
        self.computed_styles: Dict = {}
        self.is_visible: Optional[bool] = None
        self.is_enabled: Optional[bool] = None
        self.bounding_box: Optional[Dict] = None
        self.nearby_elements: List[str] = []


class DiagnosticSuggestion:
    """Represents a suggested fix from the diagnostic LLM."""
    
    def __init__(self, data: Dict):
        self.diagnosis = data.get("diagnosis", "")
        self.root_cause = data.get("root_cause", "unknown")
        self.suggested_selectors = data.get("suggested_selectors", [])
        self.confidence = data.get("confidence", "medium")


class DiagnosticEngine:
    """
    Intelligent diagnostic system that uses LLM to figure out why element interactions fail.
    """
    
    def __init__(self, api_key: str):
        """
        Initialize the diagnostic engine.
        
        Args:
            api_key: Anthropic API key
        """
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
        
        # Cache successful fixes to avoid re-diagnosing same issues
        self.fix_cache: Dict[str, str] = {}  # old_selector -> new_selector
        
    def diagnose_failure(self, 
                        page: Page,
                        element_id: str, 
                        failed_selector: str,
                        error_message: str) -> Optional[DiagnosticSuggestion]:
        """
        Diagnose why an element interaction failed and suggest fixes.
        
        Args:
            page: Playwright page object
            element_id: The element ID that failed
            failed_selector: The selector that didn't work
            error_message: The error message from the failure
            
        Returns:
            DiagnosticSuggestion with recommended fixes, or None if diagnosis fails
        """
        print(f"\n🔍 DIAGNOSTIC MODE: Analyzing why element {element_id} failed...")
        
        # Step 1: Gather detailed information about the element
        diagnostic_info = self._gather_element_info(page, failed_selector)
        
        if not diagnostic_info:
            print("   ❌ Could not gather element information for diagnosis")
            return None
        
        # Step 2: Ask LLM to diagnose the issue
        suggestion = self._ask_llm_for_diagnosis(diagnostic_info)
        
        if suggestion:
            print(f"   🎯 Diagnosis: {suggestion.diagnosis}")
            print(f"   🔧 Root cause: {suggestion.root_cause}")
            print(f"   💡 Suggested fixes: {len(suggestion.suggested_selectors)} alternatives")
            
            # Cache the best suggestion
            if suggestion.suggested_selectors:
                best_selector = suggestion.suggested_selectors[0]["selector"]
                self.fix_cache[failed_selector] = best_selector
        
        return suggestion
    
    def _gather_element_info(self, page: Page, selector: str) -> Optional[ElementDiagnostic]:
        """
        Gather detailed information about the failed element.
        
        Args:
            page: Playwright page
            selector: The selector that failed
            
        Returns:
            ElementDiagnostic object with gathered info
        """
        try:
            # Create diagnostic object
            diag = ElementDiagnostic("", selector, "Element interaction failed")
            
            # ============================================
            # FIX: Extract search text from Playwright selector
            # instead of using it directly with querySelector
            # ============================================
            search_text = None
            base_tag = "button"  # default
            
            # Check if it's a Playwright :has-text() selector
            if ":has-text(" in selector:
                import re
                text_match = re.search(r':has-text\(["\']([^"\']+)["\']\)', selector)
                if text_match:
                    search_text = text_match.group(1)
                
                # Extract the base tag (e.g., "button" from "button:has-text(...)")
                base_tag = selector.split(':')[0] if ':' in selector else 'button'
            
            # If we couldn't extract text, return None
            if not search_text:
                print(f"   ⚠️  Could not extract search text from selector: {selector}")
                return None
            
            print(f"   🔍 Searching for elements with tag '{base_tag}' containing text '{search_text}'...")
            
            # ============================================
            # NEW: Use JavaScript to find elements by text content
            # instead of trying to use the Playwright selector
            # ============================================
            element_info = page.evaluate(f"""
                (function() {{
                    const searchText = "{search_text}";
                    const baseTag = "{base_tag}";
                    
                    // Find all elements of the base tag type
                    const allElements = document.querySelectorAll(baseTag);
                    let targetElement = null;
                    
                    // Search for element containing the text
                    for (let elem of allElements) {{
                        const innerText = (elem.innerText || '').trim();
                        const textContent = (elem.textContent || '').trim();
                        
                        // Check for exact match or contains
                        if (innerText === searchText || textContent === searchText ||
                            innerText.includes(searchText) || textContent.includes(searchText)) {{
                            targetElement = elem;
                            break;  // Take the first match
                        }}
                    }}
                    
                    if (!targetElement) {{
                        console.log('Could not find element with text:', searchText);
                        return null;
                    }}
                    
                    // Gather comprehensive info about the element
                    const rect = targetElement.getBoundingClientRect();
                    const styles = window.getComputedStyle(targetElement);
                    
                    return {{
                        html: targetElement.outerHTML,
                        innerText: targetElement.innerText || '',
                        textContent: targetElement.textContent || '',
                        tagName: targetElement.tagName,
                        className: targetElement.className,
                        id: targetElement.id,
                        visible: !!(rect.width && rect.height && styles.display !== 'none' && styles.visibility !== 'hidden'),
                        enabled: !targetElement.disabled,
                        boundingBox: {{
                            x: rect.x,
                            y: rect.y,
                            width: rect.width,
                            height: rect.height
                        }},
                        computedStyles: {{
                            display: styles.display,
                            visibility: styles.visibility,
                            opacity: styles.opacity,
                            pointerEvents: styles.pointerEvents,
                            zIndex: styles.zIndex
                        }},
                        attributes: Array.from(targetElement.attributes).map(attr => ({{
                            name: attr.name,
                            value: attr.value
                        }}))
                    }};
                }})()
            """)
            
            if not element_info:
                print("   ⚠️  Could not find element with given text")
                return None
            
            # Populate diagnostic object
            diag.element_html = element_info["html"]
            diag.inner_text = element_info["innerText"]
            diag.text_content = element_info["textContent"]
            diag.computed_styles = element_info["computedStyles"]
            diag.is_visible = element_info["visible"]
            diag.is_enabled = element_info["enabled"]
            diag.bounding_box = element_info["boundingBox"]
            
            print(f"   ✅ Successfully gathered info for element")
            print(f"      - innerText: '{diag.inner_text}'")
            print(f"      - textContent: '{diag.text_content}'")
            print(f"      - visible: {diag.is_visible}, enabled: {diag.is_enabled}")
            
            return diag
            
        except Exception as e:
            print(f"   ❌ Error gathering element info: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _get_base_selector(self, selector: str) -> str:
        """
        Extract base tag from complex selector.
        
        Examples:
            button:has-text("Class10") -> button
            div.class-name -> div
            input[type="text"] -> input
        """
        # Simple extraction - get the tag name before any special characters
        base = selector.split(':')[0].split('[')[0].split('.')[0].split('#')[0]
        return base if base else '*'
    
    def _escape_selector(self, selector: str) -> str:
        """Escape selector for JavaScript eval."""
        # For now, just escape single quotes
        return selector.replace("'", "\\'")
    
    def _ask_llm_for_diagnosis(self, diagnostic_info: ElementDiagnostic) -> Optional[DiagnosticSuggestion]:
        """
        Ask the LLM to diagnose the failure and suggest fixes.
        
        Args:
            diagnostic_info: Gathered information about the element
            
        Returns:
            DiagnosticSuggestion with recommended fixes
        """
        try:
            # Build the diagnostic prompt
            prompt = self._build_diagnostic_prompt(diagnostic_info)
            
            print(f"   🧠 Asking diagnostic LLM for analysis...")
            
            # Call Claude for diagnosis
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=self._get_diagnostic_system_prompt(),
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Parse response
            response_text = response.content[0].text
            
            # Extract JSON from response
            diagnostic_data = json.loads(response_text)
            suggestion = DiagnosticSuggestion(diagnostic_data)
            
            return suggestion
            
        except json.JSONDecodeError as e:
            print(f"   ❌ Failed to parse diagnostic response: {str(e)}")
            print(f"   Raw response: {response_text[:200]}...")
            return None
        
        except Exception as e:
            print(f"   ❌ Error calling diagnostic LLM: {str(e)}")
            return None
    
    def _get_diagnostic_system_prompt(self) -> str:
        """Get the system prompt for the diagnostic LLM."""
        return """You are an expert web automation debugger specializing in DOM inspection and selector troubleshooting.

Your job is to analyze why a Playwright selector failed to find or interact with an element, and suggest working alternatives.

You will be given:
1. The selector that failed
2. The error message
3. Detailed information about the element (if found)
4. HTML structure and computed styles

You must respond ONLY with valid JSON in this exact format:
{
    "diagnosis": "Brief explanation of why the selector failed",
    "root_cause": "text_mismatch|selector_syntax|element_covered|not_visible|timing_issue|wrong_element_type|no_element_found",
    "confidence": "high|medium|low",
    "suggested_selectors": [
        {
            "selector": "working Playwright selector",
            "reliability": "high|medium|low",
            "reason": "why this selector should work"
        }
    ]
}

CRITICAL RULES:
1. Provide 2-3 alternative selectors, ranked by reliability
2. Use Playwright-compatible selectors (CSS, XPath, or text-based)
3. Consider: exact text vs partial text, case sensitivity, whitespace
4. For text matching, check if innerText differs from textContent
5. Suggest multiple strategies: CSS selectors, XPath, text selectors, attribute selectors
6. Your response must be ONLY the JSON object - no markdown, no explanation outside JSON"""

    def _build_diagnostic_prompt(self, diag: ElementDiagnostic) -> str:
        """Build the prompt for diagnostic LLM."""
        
        # Truncate HTML if too long
        html_preview = diag.element_html[:500] + "..." if diag.element_html and len(diag.element_html) > 500 else diag.element_html
        
        prompt = f"""A web automation tool failed to interact with an element. Please diagnose the issue and suggest fixes.

FAILED SELECTOR:
{diag.selector}

ERROR MESSAGE:
{diag.error_message}

ELEMENT INFORMATION (if found):
"""
        
        if diag.element_html:
            prompt += f"""
HTML:
{html_preview}

PROPERTIES:
- innerText: "{diag.inner_text}"
- textContent: "{diag.text_content}"
- Visible: {diag.is_visible}
- Enabled: {diag.is_enabled}

COMPUTED STYLES:
{json.dumps(diag.computed_styles, indent=2)}

BOUNDING BOX:
{json.dumps(diag.bounding_box, indent=2)}
"""
        else:
            prompt += "\nElement could not be found with the given selector."
        
        prompt += """

TASK:
Analyze why the selector failed and suggest 2-3 alternative selectors that would work.
Consider differences between innerText and textContent, whitespace issues, and element visibility.

Respond with JSON only."""
        
        return prompt
    
    def check_cache(self, selector: str) -> Optional[str]:
        """
        Check if we've already diagnosed this selector before.
        
        Args:
            selector: The selector to check
            
        Returns:
            Cached working selector, or None if not in cache
        """
        return self.fix_cache.get(selector)