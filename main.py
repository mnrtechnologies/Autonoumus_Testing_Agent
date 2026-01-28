"""
Robo-Tester - Autonomous Web Testing Agent
Entry point for running tests
"""
import argparse
import os
from dotenv import load_dotenv
from engines.orchestrator import Orchestrator


def main():
    """Main entry point for the Robo-Tester."""
    # Load environment variables
    load_dotenv()
    
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Robo-Tester: Autonomous web testing with AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
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
        help="Maximum number of steps before giving up (default: 20)"
    )
    
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (or set ANTHROPIC_API_KEY environment variable)"
    )
    parser.add_argument(
    "--no-diagnostics",
    action="store_true",
    help="Disable AI-powered diagnostic mode (faster but less adaptive)"
)
    
    args = parser.parse_args()
    
    # Get API key from args or environment
    api_key = args.api_key or os.getenv("ANTHROPIC_API_KEY")
    
    if not api_key:
        print("❌ Error: No API key provided!")
        print("   Set ANTHROPIC_API_KEY environment variable or use --api-key argument")
        print("   Get your API key at: https://console.anthropic.com/")
        return
    
    # Validate URL
    if not args.url.startswith(("http://", "https://")):
        print("❌ Error: URL must start with http:// or https://")
        return
    
    # Create and run orchestrator
    orchestrator = Orchestrator(api_key=api_key, headless=args.headless)
    orchestrator.max_steps = args.max_steps
    orchestrator.diagnostic_mode = not args.no_diagnostics

    if orchestrator.diagnostic_mode:
        print("🔍 Diagnostic mode: ENABLED (AI will analyze failures)")
    else:
        print("⚡ Diagnostic mode: DISABLED (faster but less adaptive)")
    try:
        result = orchestrator.run(url=args.url, goal=args.goal)
        
        # Exit with appropriate code
        exit(0 if result["success"] else 1)
        
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        exit(130)


if __name__ == "__main__":
    main()
