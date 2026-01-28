"""
VisionEngine - Captures screenshots and tags interactive elements
FIXED: Now handles alphanumeric element IDs (like "10a", "10b")
"""
from playwright.sync_api import Page
from typing import Dict, Tuple, Optional, Union
import json
from pathlib import Path
from utils.helpers import save_screenshot, load_js_file


class VisionEngine:
    """
    Handles the 'vision' part of the agent:
    1. Injects JavaScript to tag interactive elements with IDs
    2. Takes a screenshot with the tags visible
    3. Removes the tags to keep the page clean
    4. Returns both the screenshot and the element mapping
    
    NOW SUPPORTS: Alphanumeric element IDs for dropdown options (e.g., "10a", "10b")
    """
    
    def __init__(self):
        """Initialize the vision engine."""
        self.tagger_js = load_js_file('tagger.js')
        self.screenshot_counter = 0
    
    def capture_state(self, page: Page, save_to_disk: bool = True) -> Tuple[Optional[str], Dict[str, str]]:
        """
        Capture the current page state with tagged elements.
        
        Args:
            page: Playwright page object
            save_to_disk: Whether to save screenshot to disk
            
        Returns:
            Tuple of (screenshot_path, element_map)
            - screenshot_path: Path to saved screenshot file
            - element_map: Dictionary mapping element IDs (strings) to selectors
        """
        try:
            self.screenshot_counter += 1
            
            # Step 1: Inject the tagging JavaScript
            print(f"👁️  Capturing state (screenshot #{self.screenshot_counter})...")
            element_map_json = page.evaluate(self.tagger_js)
            
            # Parse the element map
            element_map = json.loads(element_map_json)
            
            # ============================================
            # CRITICAL FIX: Don't convert keys to integers!
            # Keys can be "10", "10a", "10b" etc.
            # Keep them as strings for consistency
            # ============================================
            # OLD CODE (BROKEN):
            # element_map = {int(k): v for k, v in element_map.items()}
            # This fails on "10a" because int("10a") raises ValueError
            
            # NEW CODE (FIXED):
            # Just ensure both keys and values are strings
            element_map = {str(k): str(v) for k, v in element_map.items()}
            
            print(f"   Found {len(element_map)} interactive elements")
            
            # Step 2: Take the screenshot with tags visible
            screenshot_bytes = page.screenshot(full_page=False)
            
            # Step 3: Remove the tags immediately
            page.evaluate("""
                document.querySelectorAll('.robo-tester-tag').forEach(tag => tag.remove());
            """)
            
            # Step 4: Save to disk if requested
            screenshot_path = None
            if save_to_disk:
                screenshot_path = save_screenshot(screenshot_bytes, self.screenshot_counter)
                print(f"   💾 Saved to {screenshot_path}")
            
            return screenshot_path, element_map
            
        except Exception as e:
            print(f"❌ Failed to capture state: {str(e)}")
            import traceback
            traceback.print_exc()
            return None, {}
    
    def remove_all_tags(self, page: Page):
        """
        Clean up any leftover tags from the page.
        
        Args:
            page: Playwright page object
        """
        try:
            page.evaluate("""
                document.querySelectorAll('.robo-tester-tag').forEach(tag => tag.remove());
            """)
        except Exception as e:
            print(f"⚠️  Warning: Could not remove tags: {str(e)}")
