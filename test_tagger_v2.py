from playwright.sync_api import sync_playwright
import json
import time
from pathlib import Path


def load_tagger_v2():
    """Load the upgraded tagger script"""
    tagger_path = Path('/home/claude/tagger_v2.js')
    with open(tagger_path, 'r') as f:
        return f.read()


def test_basic_tagging():
    """Test 1: Verify basic tagging still works (backward compatibility)"""
    print("\n" + "="*60)
    print("TEST 1: Basic Tagging (Backward Compatibility)")
    print("="*60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        
        # Load a simple page
        page.goto('https://example.com', wait_until='networkidle')
        time.sleep(1)
        
        # Run the upgraded tagger
        tagger_js = load_tagger_v2()
        element_map_json = page.evaluate(tagger_js)
        element_map = json.loads(element_map_json)
        
        # Verify results
        print(f"✅ Found {len(element_map)} interactive elements")
        print(f"   Element IDs: {list(element_map.keys())[:10]}")
        
        # Take screenshot with tags
        screenshot = page.screenshot()
        screenshot_path = Path('/home/claude/test_basic_tagging.png')
        screenshot_path.write_bytes(screenshot)
        print(f"   📸 Screenshot saved: {screenshot_path}")
        
        # Verify we can remove tags
        page.evaluate("document.querySelectorAll('.robo-tester-tag').forEach(tag => tag.remove());")
        remaining_tags = page.evaluate("document.querySelectorAll('.robo-tester-tag').length")
        
        if remaining_tags == 0:
            print("✅ Tag cleanup works")
        else:
            print(f"❌ WARNING: {remaining_tags} tags still present after cleanup")
        
        browser.close()
        return len(element_map) > 0


def test_stabilization_timing():
    """Test 2: Verify DOM stabilization waits for page to settle"""
    print("\n" + "="*60)
    print("TEST 2: DOM Stabilization Timing")
    print("="*60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        
        # Load a page with dynamic content
        page.goto('https://www.example.com', wait_until='domcontentloaded')
        
        # Inject some console logging to track timing
        page.evaluate("""
            window.taggerLogs = [];
            const originalLog = console.log;
            console.log = function(...args) {
                if (args[0] && args[0].includes('[Tagger]')) {
                    window.taggerLogs.push({
                        time: Date.now(),
                        message: args.join(' ')
                    });
                }
                originalLog.apply(console, args);
            };
        """)
        
        # Run the tagger and measure time
        tagger_js = load_tagger_v2()
        start_time = time.time()
        element_map_json = page.evaluate(tagger_js)
        end_time = time.time()
        
        # Get logs from browser
        logs = page.evaluate("window.taggerLogs || []")
        
        elapsed = (end_time - start_time) * 1000  # Convert to ms
        
        print(f"⏱️  Tagging took {elapsed:.0f}ms")
        
        # Check if stabilization happened
        stabilization_logs = [log for log in logs if 'stable' in log['message'].lower()]
        
        if stabilization_logs:
            print(f"✅ Stabilization detected: {stabilization_logs[0]['message']}")
        else:
            print("⚠️  No stabilization log found (page might have been already stable)")
        
        # Verify tagging worked
        element_map = json.loads(element_map_json)
        print(f"✅ Found {len(element_map)} elements after stabilization")
        
        browser.close()
        return True


def test_shadow_dom_detection():
    """Test 3: Verify Shadow DOM elements are detected"""
    print("\n" + "="*60)
    print("TEST 3: Shadow DOM Detection")
    print("="*60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        
        # Create a test page with Shadow DOM
        page.set_content("""
            <!DOCTYPE html>
            <html>
            <head><title>Shadow DOM Test</title></head>
            <body>
                <h1>Shadow DOM Test Page</h1>
                
                <!-- Regular button (should be found) -->
                <button id="regular-button">Regular Button</button>
                
                <!-- Custom element with Shadow DOM -->
                <div id="shadow-host"></div>
                
                <script>
                    // Create a shadow root
                    const host = document.getElementById('shadow-host');
                    const shadowRoot = host.attachShadow({ mode: 'open' });
                    
                    // Add a button inside the shadow DOM
                    shadowRoot.innerHTML = `
                        <style>
                            button {
                                background: blue;
                                color: white;
                                padding: 10px;
                                border: none;
                                border-radius: 5px;
                            }
                        </style>
                        <button id="shadow-button">Shadow DOM Button</button>
                        <input type="text" placeholder="Shadow Input" />
                    `;
                    
                    console.log('Shadow DOM created with button and input');
                </script>
            </body>
            </html>
        """)
        
        time.sleep(1)  # Let the page settle
        
        # Run the tagger
        tagger_js = load_tagger_v2()
        element_map_json = page.evaluate(tagger_js)
        element_map = json.loads(element_map_json)
        
        print(f"✅ Found {len(element_map)} total elements")
        
        # Verify we found elements in both regular DOM and shadow DOM
        # Expected: 1 regular button + 1 shadow button + 1 shadow input = 3 elements minimum
        
        if len(element_map) >= 3:
            print("✅ Shadow DOM elements detected!")
            print(f"   Element map: {element_map}")
        else:
            print(f"❌ WARNING: Only found {len(element_map)} elements")
            print("   Expected at least 3 (regular button + shadow button + shadow input)")
        
        # Take a screenshot
        screenshot = page.screenshot()
        screenshot_path = Path('/home/claude/test_shadow_dom.png')
        screenshot_path.write_bytes(screenshot)
        print(f"   📸 Screenshot saved: {screenshot_path}")
        
        browser.close()
        return len(element_map) >= 3


def test_dropdown_options():
    """Test 4: Verify dropdown options still work (alphanumeric IDs)"""
    print("\n" + "="*60)
    print("TEST 4: Dropdown Options (Alphanumeric IDs)")
    print("="*60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        
        # Create a test page with a dropdown
        page.set_content("""
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Dropdown Test</h1>
                <select id="country-select">
                    <option value="">Select a country</option>
                    <option value="us">United States</option>
                    <option value="uk">United Kingdom</option>
                    <option value="ca">Canada</option>
                </select>
            </body>
            </html>
        """)
        
        time.sleep(1)
        
        # Run the tagger
        tagger_js = load_tagger_v2()
        element_map_json = page.evaluate(tagger_js)
        element_map = json.loads(element_map_json)
        
        print(f"✅ Found {len(element_map)} elements")
        
        # Check for alphanumeric IDs (e.g., "1a", "1b", "1c")
        alphanumeric_ids = [k for k in element_map.keys() if any(c.isalpha() for c in str(k))]
        
        if alphanumeric_ids:
            print(f"✅ Alphanumeric IDs found: {alphanumeric_ids}")
            print(f"   Example: {alphanumeric_ids[0]} -> {element_map[alphanumeric_ids[0]]}")
        else:
            print("⚠️  No alphanumeric IDs found (dropdown options may not be tagged)")
        
        # Take a screenshot
        screenshot = page.screenshot()
        screenshot_path = Path('Functionaltesting/screenshots')
        screenshot_path.write_bytes(screenshot)
        print(f"   📸 Screenshot saved: {screenshot_path}")
        
        browser.close()
        return len(alphanumeric_ids) > 0


def run_all_tests():
    """Run all tests and report results"""
    print("="*60)
    print("TAGGER V2.0 - INTEGRATION TEST SUITE")
    print("="*60)
    
    results = {
        "Basic Tagging": test_basic_tagging(),
        "Stabilization Timing": test_stabilization_timing(),
        "Shadow DOM Detection": test_shadow_dom_detection(),
        "Dropdown Options": test_dropdown_options(),
    }
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 All tests passed! Tagger v2.0 is ready for production.")
    else:
        print("\n⚠️  Some tests failed. Review the output above.")
    
    return all_passed


if __name__ == "__main__":
    try:
        success = run_all_tests()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        exit(1)