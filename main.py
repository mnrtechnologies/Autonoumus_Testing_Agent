"""
Robo-Tester v3.0 - Data-Driven Determinism
Autonomous Web Testing Agent with Ground Truth Extraction
Entry point for running tests
"""
import os
import sys
from dotenv import load_dotenv
from engines.orchestrator import Orchestrator
from test_modes import TestModeHandler, TestCase, ReportGenerator


def show_banner():
    """Display the main banner."""
    print("\n" + "="*70)
    print("🤖 ROBO-TESTER v3.1 - INTERACTIVE TESTING SUITE")
    print("="*70)
    print("✨ Ground Truth extraction eliminates visual guessing")
    print("🔧 Diagnostic Loop auto-repairs failing selectors")
    print("💾 Per-domain memory learns from repairs")
    print("🎯 NEW: Whitebox & Blackbox testing modes")
    print("🔐 NEW: Interactive credential collection")
    print("📊 NEW: Detailed JSON reporting")
    print("="*70 + "\n")


def run_whitebox_test(orchestrator: Orchestrator, test_case: TestCase) -> TestCase:
    """
    Run a whitebox test with step-by-step instructions.
    
    Args:
        orchestrator: The Orchestrator instance
        test_case: TestCase object with steps
        
    Returns:
        Updated TestCase with results
    """
    print("\n" + "="*70)
    print("⚪ WHITEBOX TESTING - STEP BY STEP EXECUTION")
    print("="*70)
    print(f"\n📋 Test Plan ({len(test_case.steps)} steps):")
    for i, step in enumerate(test_case.steps, 1):
        print(f"   {i}. {step}")
    
    print("\n⏳ Starting execution...")
    
    try:
        # For whitebox testing, we combine all steps into a comprehensive goal
        combined_goal = f"Execute the following steps:\n" + "\n".join(
            [f"{i}. {step}" for i, step in enumerate(test_case.steps, 1)]
        )
        
        # Run the orchestrator
        result = orchestrator.run(url=test_case.url, goal=combined_goal)
        
        # Update test case
        test_case.success = result.get('success', False)
        test_case.error_message = result.get('error')
        test_case.action_history = result.get('action_history', [])
        
        return test_case
        
    except Exception as e:
        print(f"\n❌ Error during whitebox test: {str(e)}")
        test_case.success = False
        test_case.error_message = str(e)
        return test_case


def run_blackbox_test(orchestrator: Orchestrator, test_case: TestCase) -> TestCase:
    """
    Run a blackbox test with autonomous navigation.
    
    Args:
        orchestrator: The Orchestrator instance
        test_case: TestCase object with user story
        
    Returns:
        Updated TestCase with results
    """
    print("\n" + "="*70)
    print("⚫ BLACKBOX TESTING - AUTONOMOUS NAVIGATION")
    print("="*70)
    print(f"\n📖 User Story: {test_case.goal}")
    print(f"🌐 Target URL: {test_case.url}")
    
    # Generate and display floor plan
    try:
        floor_plan = orchestrator.brain.generate_floor_plan(test_case.goal)
        TestModeHandler.display_floor_plan(floor_plan)
    except Exception as e:
        print(f"⚠️  Could not generate floor plan: {str(e)}\n")
    
    print("⏳ Starting autonomous navigation...")
    print("   The system will detect forms and ask for field values as needed.\n")
    
    try:
        # Run the orchestrator
        result = orchestrator.run(url=test_case.url, goal=test_case.goal)
        
        # Update test case
        test_case.success = result.get('success', False)
        test_case.error_message = result.get('error')
        test_case.action_history = result.get('action_history', [])
        
        return test_case
        
    except Exception as e:
        print(f"\n❌ Error during blackbox test: {str(e)}")
        test_case.success = False
        test_case.error_message = str(e)
        return test_case


def handle_multiple_tests(api_key: str, headless: bool = False):
    """
    Handle running multiple tests in sequence.
    
    Args:
        api_key: Anthropic API key
        headless: Whether to run browser in headless mode
    """
    orchestrator = None
    test_results = []
    
    try:
        while True:
            # Show main menu
            choice = TestModeHandler.show_main_menu()
            
            if choice == 'exit':
                break
            
            # Collect test case
            test_case = None
            if choice == 'whitebox':
                test_case = TestModeHandler.collect_whitebox_test_case()
            else:  # blackbox
                test_case = TestModeHandler.collect_blackbox_test_case()
            
            if not test_case:
                print("⚠️  Test case collection cancelled. Returning to menu.")
                continue
            
            # Create orchestrator if needed (reuse for multiple tests)
            if orchestrator is None:
                orchestrator = Orchestrator(api_key=api_key, headless=headless)
                orchestrator.max_steps = 50
                
                # Start browser only once
                if not orchestrator.browser.start(test_case.url):
                    print("❌ Failed to start browser. Exiting.")
                    return
            
            # Run the appropriate test
            if test_case.mode == 'whitebox':
                test_case = run_whitebox_test(orchestrator, test_case)
            else:
                test_case = run_blackbox_test(orchestrator, test_case)
            
            # Generate and display report
            report = ReportGenerator.generate_report(test_case)
            ReportGenerator.print_report(report)
            
            # Save report
            report_path = ReportGenerator.save_report(report)
            print(f"💾 Report saved to: {report_path}\n")
            
            # Store results
            test_results.append({
                'test_case': test_case,
                'report': report,
                'report_path': report_path
            })
            
            # Ask if user wants to run another test
            another = TestModeHandler.confirm_action("\n🔄 Run another test?")
            if not another:
                break
        
        # Final summary
        if test_results:
            print("\n" + "="*70)
            print("📊 FINAL SUMMARY")
            print("="*70)
            print(f"\nTotal tests executed: {len(test_results)}")
            passed = sum(1 for r in test_results if r['test_case'].success)
            failed = len(test_results) - passed
            print(f"✅ Passed: {passed}")
            print(f"❌ Failed: {failed}")
            print(f"\nReports saved:")
            for r in test_results:
                print(f"  - {r['report_path']}")
            print("="*70 + "\n")
    
    except KeyboardInterrupt:
        print("\n\n👋 Test session interrupted by user.")
    
    finally:
        # Close browser
        if orchestrator and orchestrator.browser:
            orchestrator.browser.cleanup()
            print("✅ Browser closed.")


def main():
    """Main entry point for the Robo-Tester v3.1."""
    # Load environment variables
    load_dotenv()
    
    # Show banner
    show_banner()
    
    # Get API key
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    if not api_key:
        print("❌ Error: No API key provided!")
        print("   Please set the ANTHROPIC_API_KEY environment variable")
        print("   Get your API key at: https://console.anthropic.com/\n")
        print("   Quick setup:")
        print("   1. Create a .env file in the current directory")
        print("   2. Add: ANTHROPIC_API_KEY=your_api_key_here")
        print("   3. Run this script again\n")
        return
    
    print("✅ API key loaded from environment\n")
    
    # Check for command-line arguments (--url and --goal for direct execution)
    if len(sys.argv) > 1:
        # Try to parse command-line args
        url = None
        goal = None
        
        i = 1
        while i < len(sys.argv):
            if sys.argv[i] == '--url' and i + 1 < len(sys.argv):
                url = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == '--goal' and i + 1 < len(sys.argv):
                goal = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        
        # If command-line args provided, run directly without interactive menu
        if url and goal:
            print("=" * 70)
            print("🚀 DIRECT EXECUTION MODE")
            print("=" * 70)
            
            # Auto-detect if it's blackbox or whitebox (blackbox if goal is a story/intention)
            # Simple heuristic: if goal mentions navigation/actions across pages, it's blackbox
            is_blackbox = any(keyword in goal.lower() for keyword in ['then', 'and', 'go to', 'select', 'perform'])
            
            test_case = TestCase(
                mode='blackbox' if is_blackbox else 'whitebox',
                url=url,
                goal=goal,
                steps=[goal] if not is_blackbox else []
            )
            
            print(f"\n📋 Mode: {test_case.mode.upper()}")
            print(f"🌐 URL: {url}")
            print(f"📖 Goal: {goal}\n")
            
            # Create orchestrator
            orchestrator = Orchestrator(api_key=api_key, headless=False)
            orchestrator.max_steps = 50
            
            if not orchestrator.browser.start(test_case.url):
                print("❌ Failed to start browser. Exiting.")
                return
            
            # Run test
            if test_case.mode == 'whitebox':
                test_case = run_whitebox_test(orchestrator, test_case)
            else:
                test_case = run_blackbox_test(orchestrator, test_case)
            
            # Generate and display report
            report = ReportGenerator.generate_report(test_case)
            ReportGenerator.print_report(report)
            
            # Save report
            report_path = ReportGenerator.save_report(report)
            print(f"💾 Report saved to: {report_path}\n")
            
            # Cleanup
            orchestrator.browser.cleanup()
            return
    
    # Interactive mode (no command-line args)
    handle_multiple_tests(api_key=api_key, headless=False)
    
    print("👋 Thank you for using Robo-Tester v3.1!")


if __name__ == "__main__":
    main()
