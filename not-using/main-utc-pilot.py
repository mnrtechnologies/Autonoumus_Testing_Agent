"""
Robo-Tester v3.0 - Data-Driven Determinism
Autonomous Web Testing Agent with Ground Truth Extraction
Entry point for running tests
"""
import argparse
import os
from dotenv import load_dotenv
from engines.orchestrator import Orchestrator


def main():
    """Main entry point for the Robo-Tester v3.0."""
    # Load environment variables
    load_dotenv()
    
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Robo-Tester v3.0: Data-Driven Determinism - No more visual guessing!",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
🎯 NEW IN v3.0: DATA-DRIVEN DETERMINISM
- Extracts exact text from DOM (no more "Class10" vs "Class 10" errors!)
- Diagnostic Loop automatically repairs failing selectors
- Per-domain memory learns from repairs

Examples:
  # Test a login flow
  python main.py --url "https://example.com/login" --goal "Login with username 'test@example.com' and password 'demo123'"
  
  # Test search functionality
  python main.py --url "https://example.com" --goal "Search for 'Python tutorials' and verify results appear"
  
  # Run in headless mode
  python main.py --url "https://example.com" --goal "Navigate to About page" --headless
        """
    )
    
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="The website URL to test (must include http:// or https://)"
    )
    
    parser.add_argument(
        "--goal",
        type=str,
        required=True,
        help="Description of what the agent should accomplish (e.g., 'Login as admin')"
    )
    
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible window)"
    )
    
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Maximum number of steps before giving up (default: 50)"
    )
    
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY environment variable)"
    )
    
    args = parser.parse_args()
    
    # Get API key from args or environment
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        print("❌ Error: No API key provided!")
        print("   Set ANTHROPIC_API_KEY environment variable or use --api-key argument")
        print("   Get your API key at: https://console.anthropic.com/")
        return
    
    # Validate URL
    if not args.url.startswith(("http://", "https://")):
        print("❌ Error: URL must start with http:// or https://")
        return
    
    # Banner
    print("\n" + "="*70)
    print("🤖 ROBO-TESTER v3.0 - DATA-DRIVEN DETERMINISM")
    print("="*70)
    print("✨ NEW: Ground Truth extraction eliminates visual guessing")
    print("🔧 NEW: Diagnostic Loop auto-repairs failing selectors")
    print("💾 NEW: Per-domain memory learns from repairs")
    print("="*70 + "\n")
    
    # Create and run orchestrator
    orchestrator = Orchestrator(api_key=api_key, headless=args.headless)
    orchestrator.max_steps = args.max_steps
    if not orchestrator.browser.start(args.url):
        return
    try:
        current_goal = args.goal 
        
        while True:
            # 2. IMPORTANT: Pass 'None' or handle the URL in a way that 
            # tells the Orchestrator NOT to call start() again
            orchestrator.run(url=orchestrator.browser.get_page().url, goal=current_goal)
            
            print("\n" + "="*70)
            print("🟢 TASK FINISHED. Browser is still open and waiting.")
            print("="*70)
            
            current_goal = input("\n WHAT IS THE NEXT TASK? (or type 'exit' to quit): ")
            if current_goal.lower() in ['exit', 'quit']:
                break
                
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    finally:
        # 4. Only close the browser when you actually exit the loop
        orchestrator.browser.cleanup()
        

if __name__ == "__main__":
    main()