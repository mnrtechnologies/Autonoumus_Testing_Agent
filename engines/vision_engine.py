"""
VisionEngine - UPGRADED to v3.0 - Data-Driven Determinism
NOW RETURNS: Element profiles with {selector, text, tag, attributes}
PRESERVES: Alphanumeric element IDs (like "10a", "10b")
"""
from playwright.sync_api import Page
from typing import Dict, Tuple, Optional
import json
from pathlib import Path
from utils.helpers import save_screenshot, load_js_file


class ElementProfile:
    """
    Data class representing the complete "Ground Truth" profile of an element.
    This eliminates visual guessing by providing exact DOM data.
    """
    def __init__(self,profile_dict: dict):
        self.selector = profile_dict.get('selector', '')
        self.text = profile_dict.get('text', '')
        self.tag = profile_dict.get('tag', '')
        self.attributes = profile_dict.get('attributes', {})
    
    def __repr__(self):
        return f"<{self.tag}> text=\"{self.text}\" {self.attributes}"
    
    def get_selector(self) -> str:
        """Get the CSS/XPath selector for this element."""
        return self.selector
    
    def get_display_text(self) -> str:
        """Get readable text for displaying to Claude."""
        attrs_str = ', '.join([f'{k}="{v}"' for k, v in self.attributes.items()])
        text_part = f' text="{self.text}"' if self.text else ''
        attr_part = f' [{attrs_str}]' if attrs_str else ''
        return f"<{self.tag}>{text_part}{attr_part}"
    
    def to_dict(self):
        return {
            "tag": self.tag,
            "text": self.text,
            "attributes": self.attributes,
            "selector": self.get_selector()
        }


class VisionEngine:
    """
    Handles the 'vision' part of the agent:
    1. Injects JavaScript to tag interactive elements with IDs
    2. Extracts complete "Ground Truth" profiles for each element
    3. Takes a screenshot with the tags visible
    4. Removes the tags to keep the page clean
    5. Returns both the screenshot and the element profiles
    
    VERSION 3.0: Returns element profiles instead of just selectors
    """
    
    def __init__(self):
        """Initialize the vision engine."""
        self.tagger_js = load_js_file('tagger.js')
        self.screenshot_counter = 0
    
    def capture_state(self, page: Page, save_to_disk: bool = True) -> Tuple[Optional[str], Dict[str, ElementProfile]]:
        """
        Capture the current page state with tagged elements AND their Ground Truth profiles.
        
        Args:
            page: Playwright page object
            save_to_disk: Whether to save screenshot to disk
            
        Returns:
            Tuple of (screenshot_path, element_profiles)
            - screenshot_path: Path to saved screenshot file
            - element_profiles: Dictionary mapping element IDs (strings) to ElementProfile objects
        """
        try:
            self.screenshot_counter += 1
            
            # Step 1: Inject the tagging JavaScript (now returns profiles, not just selectors!)
            print(f"👁️  Capturing state with Ground Truth extraction (screenshot #{self.screenshot_counter})...")
            element_map_json = page.evaluate(self.tagger_js)
            
            # Parse the element map
            element_map_raw = json.loads(element_map_json)
            
            # Convert to ElementProfile objects
            element_profiles = {}
            for elem_id, profile_data in element_map_raw.items():
                # Handle both old format (string) and new format (dict)
                if isinstance(profile_data, str):
                    # Backward compatibility: old format was just selector string
                    element_profiles[str(elem_id)] = ElementProfile({
                        'selector': profile_data,
                        'text': '',
                        'tag': 'unknown',
                        'attributes': {}
                    })
                else:
                    # New format: full profile dictionary
                    element_profiles[str(elem_id)] = ElementProfile(profile_data)
            
            print(f"   ✅ Found {len(element_profiles)} interactive elements with Ground Truth data")
            
            # Log sample of extracted text (for debugging)
            sample_count = min(3, len(element_profiles))
            for i, (elem_id, profile) in enumerate(list(element_profiles.items())[:sample_count]):
                print(f"   📊 Sample {elem_id}: {profile}")
            
            # Step 2: Take the screenshot with tags visible
            screenshot_bytes = page.screenshot(timeout=5000,full_page=False)
            
            # Step 3: Remove the tags immediately
            page.evaluate("""
                document.querySelectorAll('.robo-tester-tag').forEach(tag => tag.remove());
            """)
            
            # Step 4: Save to disk if requested
            screenshot_path = None
            if save_to_disk:
                screenshot_path = save_screenshot(screenshot_bytes, self.screenshot_counter)
                print(f"   💾 Saved to {screenshot_path}")
            
            return screenshot_path, element_profiles
            
        except Exception as e:
            print(f"❌ Failed to capture state: {str(e)}")
            import traceback
            traceback.print_exc()
            return None, {}
    
    def get_selector_from_profile(self, profile: ElementProfile) -> str:
        """
        Extract just the selector string from a profile.
        Used for backward compatibility with browser engine.
        
        Args:
            profile: ElementProfile object
            
        Returns:
            CSS/XPath selector string
        """
        return profile.get_selector()
    
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

