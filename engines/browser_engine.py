"""
BrowserEngine - UPGRADED to v3.0 - Diagnostic Loop Support
NOW: Tracks failures and supports repair selectors with XPath normalize-space()
PRESERVES: CSS/XPath/Playwright selector support, dropdown options
"""
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
from typing import Optional, Dict
import time
import re


class BrowserEngine:
    """
    Wraps Playwright to provide simple browser control methods.
    VERSION 3.0: Tracks element failures and supports repair selectors
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
        self.element_map: Dict[str, str] = {}  # Maps element IDs to selectors
        
        # NEW V3.0: Failure tracking for Diagnostic Loop
        self.failure_counts: Dict[str, int] = {}  # Track consecutive failures per element
        self.last_error: Dict[str, str] = {}  # Track last error message per element
        
    def start(self, url: str) -> bool:
            """
            Launch a PERSISTENT browser and navigate to the target URL.
            This saves cookies and session data to a local folder.
            """
            try:
                self.playwright = sync_playwright().start()
                
                # Define a folder to store the browser profile (cookies, local storage, etc.)
                user_data_dir = "./browser_session"
                
                print(f"📂 Using persistent session in: {user_data_dir}")
                
                # launch_persistent_context combines browser launch and context creation
                self.context = self.playwright.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=self.headless,
                    viewport={'width': 1280, 'height': 720},
                    # This ensures the browser doesn't close between steps if you don't want it to
                    no_viewport=False 
                )
                
                # In a persistent context, a page is often already open
                if len(self.context.pages) > 0:
                    self.page = self.context.pages[0]
                else:
                    self.page = self.context.new_page()
                
                # Navigate to URL
                print(f"🌐 Navigating to {url}...")
                self.page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(2) 
                
                print("✅ Persistent browser started successfully")
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
            new_map: Dictionary mapping element IDs to selectors (or ElementProfile objects)
        """
        # Handle both old format (selector strings) and new format (ElementProfile objects)
        self.element_map = {}
        for elem_id, value in new_map.items():
            elem_id_str = str(elem_id)
            
            # Check if value is an ElementProfile object or a string
            if hasattr(value, 'get_selector'):
                # It's an ElementProfile object
                self.element_map[elem_id_str] = value.get_selector()
            else:
                # It's a string selector (backward compatibility)
                self.element_map[elem_id_str] = str(value)
        
        print(f"📍 Updated element map with {len(self.element_map)} elements")
    
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
    
    def get_failure_count(self, element_id: str) -> int:
        """
        Get the number of consecutive failures for an element.
        
        Args:
            element_id: The element ID
            
        Returns:
            Number of consecutive failures
        """
        return self.failure_counts.get(str(element_id), 0)
    
    def get_last_error(self, element_id: str) -> Optional[str]:
        """
        Get the last error message for an element.
        
        Args:
            element_id: The element ID
            
        Returns:
            Last error message or None
        """
        return self.last_error.get(str(element_id))
    
    def reset_failure_count(self, element_id: str):
        """
        Reset the failure count for an element (after success).
        
        Args:
            element_id: The element ID
        """
        elem_id_str = str(element_id)
        if elem_id_str in self.failure_counts:
            del self.failure_counts[elem_id_str]
        if elem_id_str in self.last_error:
            del self.last_error[elem_id_str]
    
    def _record_failure(self, element_id: str, error_message: str):
        """
        Record a failure for an element.
        
        Args:
            element_id: The element ID
            error_message: The error message
        """
        elem_id_str = str(element_id)
        self.failure_counts[elem_id_str] = self.failure_counts.get(elem_id_str, 0) + 1
        self.last_error[elem_id_str] = error_message
        
        failure_count = self.failure_counts[elem_id_str]
        print(f"   ⚠️  Failure #{failure_count} for element {element_id}")
    
    def execute_action(self, action_type: str, element_id: Optional[str] = None, 
                      value: Optional[str] = None, repair_selector: Optional[str] = None) -> Dict:
        """
        Execute a browser action based on the LLM's decision.
        VERSION 3.0: Supports repair selectors for failed actions.
        
        Args:
            action_type: Type of action ('click', 'type', 'wait', 'scroll')
            element_id: The ID of the element to interact with (can be "10" or "10a")
            value: Text value (for 'type' actions)
            repair_selector: Optional repair XPath selector to use instead of normal selector
            
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
            
            # Determine which selector to use
            if repair_selector:
                print(f"   🔧 Using REPAIR SELECTOR: {repair_selector}")
                selector = repair_selector
            else:
                # Get the normal selector for this element
                selector = self.element_map.get(element_id_str)
                if not selector:
                    return {
                        "success": False, 
                        "message": f"Element ID {element_id} not found in current map"
                    }
            
            # Execute the specific action
            if action_type == "click":
                print(f"🖱️  Clicking element {element_id} ({selector[:80]}...)...")
                
                # ============================================
                # Check if this is a dropdown option
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
                        
                        # SUCCESS: Reset failure count
                        self.reset_failure_count(element_id_str)
                        
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
                        
                        # SUCCESS: Reset failure count
                        self.reset_failure_count(element_id_str)
                        
                        return {"success": True, "message": f"Clicked element {element_id}"}
                
                # ============================================
                # Regular element click (not a dropdown option)
                # ============================================
                else:
                    locator = self._get_locator(selector)
                    
                    # Scroll element into view first
                    locator.scroll_into_view_if_needed(timeout=5000)
                    time.sleep(0.3)  # Wait for scroll animation
                    
                    # Click with retry logic
                    try:
                        locator.click(timeout=15000, force=False)
                    except Exception as e:
                        # If normal click fails, try force click
                        print(f"   ⚠️  Normal click failed, trying force click...")
                        locator.click(timeout=5000, force=True)
                    
                    time.sleep(1)  # Allow page to respond
                    
                    # SUCCESS: Reset failure count
                    self.reset_failure_count(element_id_str)
                    
                    return {"success": True, "message": f"Clicked element {element_id}"}
            
            elif action_type == "type":
                if not value:
                    return {"success": False, "message": "No value provided for typing"}
                
                print(f"⌨️  Typing '{value}' into element {element_id}...")
                locator = self._get_locator(selector)
                locator.fill(value, timeout=5000)
                time.sleep(0.5)
                
                # SUCCESS: Reset failure count
                self.reset_failure_count(element_id_str)
                
                return {"success": True, "message": f"Typed '{value}' into element {element_id}"}
            
            else:
                return {"success": False, "message": f"Unknown action type: {action_type}"}
        
        except Exception as e:
            error_msg = str(e)
            
            # FAILURE: Record it
            if element_id:
                self._record_failure(str(element_id), error_msg)
            
            full_error = f"Failed to {action_type} element {element_id}: {error_msg}"
            print(f"❌ {full_error}")
            
            return {"success": False, "message": full_error}
    
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