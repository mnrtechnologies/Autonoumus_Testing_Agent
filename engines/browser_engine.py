"""
BrowserEngine - UPDATED - Handles both CSS and XPath selectors + Dropdown Options
"""
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
from typing import Optional, Dict
import time
import re


class BrowserEngine:
    """
    Wraps Playwright to provide simple browser control methods.
    NOW SUPPORTS: CSS selectors, XPath, Playwright text selectors, and dropdown options
    """
    
    def __init__(self, headless: bool = False):
        """
        Initialize the browser engine.
        
        Args:
            headless: If True, browser runs without GUI (invisible)
        """
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.element_map: Dict[int, str] = {}  # Maps element IDs to CSS selectors
        
    def start(self, url: str) -> bool:
        """
        Launch the browser and navigate to the target URL.
        
        Args:
            url: The website URL to test
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=self.headless)
            self.context = self.browser.new_context(
                viewport={'width': 1280, 'height': 720}
            )
            self.page = self.context.new_page()
            
            # Navigate to URL
            print(f"🌐 Navigating to {url}...")
            self.page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2)  # Allow page to settle
            
            print("✅ Browser started successfully")
            return True
            
        except Exception as e:
            print(f"❌ Failed to start browser: {str(e)}")
            return False
    
    def update_element_map(self, new_map: Dict):
        """
        Update the internal mapping of element IDs to CSS selectors.
        This is called after each screenshot when new tags are generated.
        Now handles both numeric IDs and alphanumeric IDs (like "10a", "10b").
        
        Args:
            new_map: Dictionary mapping element IDs to CSS selectors
        """
        # Convert keys to strings if they're integers (for consistency)
        self.element_map = {str(k): v for k, v in new_map.items()}
        print(f"📍 Updated element map with {len(new_map)} elements")
    
    def _get_locator(self, selector: str):
        """
        Get a Playwright locator for the given selector.
        Handles CSS, XPath, and Playwright text selectors.
        
        Args:
            selector: CSS selector, XPath, or text selector
            
        Returns:
            Playwright locator
        """
        # Check if it's an XPath
        if selector.startswith('/') or selector.startswith('('):
            return self.page.locator(f"xpath={selector}")
        
        # Check if it's a Playwright text selector
        elif ':has-text(' in selector:
            return self.page.locator(selector)
        
        # Otherwise treat as CSS selector
        else:
            return self.page.locator(selector)
    
    def execute_action(self, action_type: str, element_id: Optional[str] = None, 
                  value: Optional[str] = None) -> Dict:
        """
        Execute a browser action based on the LLM's decision.
        NOW SUPPORTS: Dropdown option selection (e.g., element_id="10a")
        
        Args:
            action_type: Type of action ('click', 'type', 'wait', 'scroll')
            element_id: The ID of the element to interact with (can be "10" or "10a")
            value: Text value (for 'type' actions)
            
        Returns:
            Dictionary with success status and message
        """
        try:
            if action_type == "wait":
                print(f"⏳ Waiting for 2 seconds...")
                time.sleep(2)
                return {"success": True, "message": "Waited 2 seconds"}
            
            if action_type == "scroll":
                print(f"📜 Scrolling down...")
                self.page.evaluate("window.scrollBy(0, 500)")
                time.sleep(1)
                return {"success": True, "message": "Scrolled down"}
            
            # For actions that need an element
            if element_id is None:
                return {"success": False, "message": "No element ID provided"}
            
            # Convert element_id to string for consistent lookup
            element_id_str = str(element_id)
            
            # Get the selector for this element
            selector = self.element_map.get(element_id_str)
            if not selector:
                return {
                    "success": False, 
                    "message": f"Element ID {element_id} not found in current map"
                }
            
            # Execute the specific action
            if action_type == "click":
                print(f"🖱️  Clicking element {element_id} ({selector[:80]}...)...")
                locator = self._get_locator(selector)

                try:
                    # Check if element is visible
                    is_visible = locator.is_visible(timeout=2000)
                    if not is_visible:
                        return {
                            "success": False,
                            "message": f"Element {element_id} exists but is not visible (may be hidden or off-screen)"
                        }
                    is_enabled = locator.is_enabled(timeout=2000)
                    if not is_enabled:
                        return {
                            "success": False,
                            "message": f"Element {element_id} is disabled (cannot be clicked)"
                        }
                except Exception as check_error:
                    print(f"   ⚠️  Pre-flight check warning: {str(check_error)}")    
                
                # ============================================
                # NEW: Check if this is a dropdown option
                # ============================================
                if " option[" in selector:
                    # This is a <select> option - use select_option instead of click
                    print(f"   📋 Detected dropdown option, using select method...")
                    
                    # Extract the parent select selector (everything before " option[")
                    select_selector = selector.split(" option[")[0]
                    
                    # Extract value from option[value="..."]
                    value_match = re.search(r'option\[value="([^"]+)"\]', selector)
                    
                    if value_match:
                        option_value = value_match.group(1)
                        select_locator = self._get_locator(select_selector)
                        
                        # Scroll into view first
                        select_locator.scroll_into_view_if_needed(timeout=5000)
                        time.sleep(0.3)
                        
                        print(f"   ✅ Selecting option with value '{option_value}'...")
                        select_locator.select_option(value=option_value, timeout=5000)
                        time.sleep(1)
                        
                        return {
                            "success": True, 
                            "message": f"Selected option '{option_value}' in dropdown {element_id}"
                        }
                    else:
                        # Fallback: couldn't parse value, try regular click
                        print(f"   ⚠️  Could not parse option value, trying regular click...")
                        locator = self._get_locator(selector)
                        locator.click(timeout=5000)
                        time.sleep(1)
                        return {"success": True, "message": f"Clicked element {element_id}"}
                
                # ============================================
                # Regular element click (not a dropdown option)
                # ============================================
                else:
                    locator = self._get_locator(selector)

                    try:
                        # Scroll element into view first
                        locator.scroll_into_view_if_needed(timeout=5000)
                        time.sleep(0.3)  # Wait for scroll animation
                        locator.click(timeout=15000, force=False)
                        time.sleep(1)  # Allow page to respond
                        return {"success": True, "message": f"Clicked element {element_id}"}
                        
                    except Exception as e:
                        error_message = str(e)
                        
                        # ============================================
                        # 👇 NEW: Fetch actual DOM context when click fails
                        # ============================================
                        print(f"   🔍 Fetching actual element context...")
                        
                        actual_context = self._fetch_failure_context(selector)
                        
                        if "timeout" in error_message.lower():
                            return {
                                "success": False,
                                "message": f"Element {element_id} timed out - may be covered by another element or not clickable",
                                "failure_context": actual_context
                            }
                        elif "not visible" in error_message.lower():
                            return {
                                "success": False,
                                "message": f"Element {element_id} is not visible on screen",
                                "failure_context": actual_context
                            }
                        else:
                            return {
                                "success": False,
                                "message": f"Failed to click element {element_id}: {error_message}",
                                "failure_context": actual_context
                            }
            
            elif action_type == "type":
                if not value:
                    return {"success": False, "message": "No value provided for typing"}
                
                print(f"⌨️  Typing '{value}' into element {element_id}...")
                locator = self._get_locator(selector)
                locator.fill(value, timeout=5000)
                time.sleep(0.5)
                return {"success": True, "message": f"Typed '{value}' into element {element_id}"}
            
            else:
                return {"success": False, "message": f"Unknown action type: {action_type}"}
        
        except Exception as e:
            error_msg = f"Failed to {action_type} element {element_id}: {str(e)}"
            print(f"❌ {error_msg}")
            return {"success": False, "message": error_msg}


    def _fetch_failure_context(self, failed_selector: str) -> Dict:
        """
        Fetch actual DOM context when a selector fails.
        Finds similar elements and returns their real properties.
        
        Args:
            failed_selector: The selector that didn't work
            
        Returns:
            Dict with information about actual elements on the page
        """
        try:
            # Extract search text from Playwright selector
            search_text = None
            if ":has-text(" in failed_selector:
                import re
                text_match = re.search(r':has-text\(["\']([^"\']+)["\']\)', failed_selector)
                if text_match:
                    search_text = text_match.group(1)
            
            if not search_text:
                return {"failed_selector": failed_selector, "similar_elements": []}
            
            # Find similar elements on the page
            similar_elements = self.page.evaluate(f"""
                (function() {{
                    const searchText = "{search_text}";
                    const allButtons = document.querySelectorAll('button');
                    const matches = [];
                    
                    allButtons.forEach(btn => {{
                        const innerText = (btn.innerText || '').trim();
                        const textContent = (btn.textContent || '').trim();
                        
                        // Check if text contains what we're looking for
                        if (innerText.toLowerCase().includes(searchText.toLowerCase()) ||
                            textContent.toLowerCase().includes(searchText.toLowerCase())) {{
                            
                            matches.push({{
                                innerText: innerText,
                                textContent: textContent,
                                className: btn.className,
                                visible: btn.offsetParent !== null
                            }});
                        }}
                    }});
                    
                    return matches;
                }})()
            """)
            
            print(f"   📊 Found {len(similar_elements)} similar elements")
            
            return {
                "failed_selector": failed_selector,
                "searched_for": search_text,
                "similar_elements": similar_elements
            }
            
        except Exception as e:
            print(f"   ⚠️  Could not fetch context: {str(e)}")
            return {"failed_selector": failed_selector, "error": str(e)}
    
    def get_page(self) -> Optional[Page]:
        """
        Get the current Playwright page object.
        Used by VisionEngine to take screenshots.
        """
        return self.page
    
    def cleanup(self):
        """
        Close the browser and clean up resources.
        """
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            print("🧹 Browser cleaned up")
        except Exception as e:
            print(f"⚠️  Error during cleanup: {str(e)}")