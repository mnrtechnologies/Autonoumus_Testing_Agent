"""
Test Mode Handler - Supports both Whitebox and Blackbox Testing
Handles interactive user input and credential collection
"""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TestCase:
    """Represents a complete test case"""
    mode: str  # 'whitebox' or 'blackbox'
    url: str
    goal: str
    steps: List[str]  # For whitebox testing
    started_at: datetime = None
    completed_at: datetime = None
    success: bool = False
    error_message: str = None
    action_history: List[str] = None
    credentials_collected: Dict[str, str] = None
    
    def __post_init__(self):
        self.started_at = datetime.now()
        self.action_history = []
        self.credentials_collected = {}


class TestModeHandler:
    """
    Interactive handler for test mode selection and credential collection
    """
    
    @staticmethod
    def show_main_menu() -> str:
        """
        Display main menu and get user choice.
        
        Returns:
            User's choice: 'whitebox', 'blackbox', or 'exit'
        """
        print("\n" + "="*70)
        print("🤖 ROBO-TESTER v3.0 - TEST MODE SELECTION")
        print("="*70)
        print("\nChoose your testing mode:\n")
        print("1️⃣  WHITEBOX TESTING")
        print("   └─ You provide detailed step-by-step instructions")
        print("   └─ Perfect for: Testing predefined flows, regression testing")
        print("   └─ Example: Click Login → Enter credentials → Verify success\n")
        
        print("2️⃣  BLACKBOX TESTING")
        print("   └─ You provide URL and high-level intent (user story)")
        print("   └─ AI navigates autonomously using vision + reasoning")
        print("   └─ Perfect for: Exploratory testing, new feature discovery")
        print("   └─ Example: 'Test the Virtual Lab experiment feature'\n")
        
        print("3️⃣  EXIT")
        print("   └─ Close the application\n")
        
        while True:
            choice = input("Enter your choice (1/2/3): ").strip()
            if choice == '1':
                return 'whitebox'
            elif choice == '2':
                return 'blackbox'
            elif choice == '3':
                return 'exit'
            else:
                print("❌ Invalid choice. Please enter 1, 2, or 3.")
    
    @staticmethod
    def collect_whitebox_test_case() -> Optional[TestCase]:
        """
        Collect whitebox test case details from command-line arguments or interactive input.
        
        Returns:
            TestCase object or None if cancelled
        """
        import sys
        
        # Check for command-line arguments first
        if len(sys.argv) > 1:
            # Parse command-line args: --url "..." --goal "..."
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
            
            # If both url and goal provided via command-line, use them directly
            if url and goal:
                print("\n" + "="*70)
                print("📝 WHITEBOX TEST CASE")
                print("="*70)
                print(f"\n✅ Test case from command-line:")
                print(f"   URL: {url}")
                print(f"   Goal: {goal}")
                
                return TestCase(
                    mode='whitebox',
                    url=url,
                    goal=goal,
                    steps=[goal]  # Single step: execute the goal
                )
        
        # Interactive fallback if no command-line args
        print("\n" + "="*70)
        print("📝 WHITEBOX TEST CASE SETUP")
        print("="*70)
        
        # Get URL
        url = input("\n🌐 Enter the website URL (http:// or https://): ").strip()
        if not url.startswith(("http://", "https://")):
            print("❌ URL must start with http:// or https://")
            return None
        
        # Get test goal
        goal = input("\n🎯 Enter the main testing goal: ").strip()
        if not goal:
            print("❌ Goal cannot be empty")
            return None
        
        # Confirmation
        print(f"\n✅ Test case created:")
        print(f"   URL: {url}")
        print(f"   Goal: {goal}")
        
        return TestCase(
            mode='whitebox',
            url=url,
            goal=goal,
            steps=[goal]
        )
    
    @staticmethod
    def collect_blackbox_test_case() -> Optional[TestCase]:
        """
        Collect blackbox test case details from command-line arguments or interactive input.
        
        Returns:
            TestCase object or None if cancelled
        """
        import sys
        
        # Check for command-line arguments first
        if len(sys.argv) > 1:
            # Parse command-line args: --url "..." --goal "..."
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
            
            # If both url and goal provided via command-line, use them directly
            if url and goal:
                print("\n" + "="*70)
                print("🔍 BLACKBOX TEST CASE")
                print("="*70)
                print(f"\n✅ Test case from command-line:")
                print(f"   URL: {url}")
                print(f"   Goal: {goal}")
                print(f"\n⏳ Generating floor plan...")
                
                return TestCase(
                    mode='blackbox',
                    url=url,
                    goal=goal,
                    steps=[]
                )
        
        # Interactive fallback if no command-line args
        print("\n" + "="*70)
        print("🔍 BLACKBOX TEST CASE SETUP")
        print("="*70)
        
        # Get URL
        url = input("\n🌐 Enter the website URL (http:// or https://): ").strip()
        if not url.startswith(("http://", "https://")):
            print("❌ URL must start with http:// or https://")
            return None
        
        # Get user story/intention
        goal = input("\n📖 Enter your user story or testing intention:\n   (e.g., 'Login and test Virtual Lab')\n   >>> ").strip()
        if not goal:
            print("❌ Intention cannot be empty")
            return None
        
        # Confirmation
        print(f"\n✅ Blackbox test case created:")
        print(f"   URL: {url}")
        print(f"   Intention: {goal}")
        print(f"\n⏳ Generating floor plan...")
        
        return TestCase(
            mode='blackbox',
            url=url,
            goal=goal,
            steps=[]
        )
    
    @staticmethod
    def ask_for_form_values(input_fields: Dict[str, str]) -> Dict[str, str]:
        """
        Ask user to provide values for detected form fields.
        Works for ANY form (login, contact, feedback, registration, etc).
        
        Args:
            input_fields: Dictionary of {field_id: field_label}
            Example: {'1': 'Email address', '2': 'Password', '3': 'Message'}
            
        Returns:
            Dictionary of {field_id: user_value}
        """
        print("\n" + "="*70)
        print("📝 FORM FIELD VALUES REQUIRED")
        print("="*70)
        print("\n🤖 The system detected the following input fields:\n")
        
        # Display the fields
        for field_id, field_label in input_fields.items():
            print(f"   [{field_id}] {field_label}")
        
        print("\n📋 Please provide values for each field:\n")
        
        collected_values = {}
        
        # Ask for each field
        for field_id, field_label in input_fields.items():
            while True:
                value = input(f"   [{field_id}] {field_label}: ").strip()
                
                # Allow empty values for optional fields
                if value or TestModeHandler.confirm_action(f"   Leave '{field_label}' empty?"):
                    collected_values[field_id] = value
                    break
        
        print(f"\n✅ Collected values for {len(collected_values)} fields")
        return collected_values
    
    @staticmethod
    def ask_for_credentials(page_context: str) -> Dict[str, str]:
        """
        DEPRECATED: Use ask_for_form_values instead.
        Kept for backward compatibility.
        """
        print("\n" + "="*70)
        print("🔐 LOGIN REQUIRED")
        print("="*70)
        print(f"\n📋 Page Context: {page_context}")
        print("\n🤖 Vision engine detected a login page.")
        print("Please provide the following information:\n")
        
        credentials = {}
        
        # Ask for username/email
        username = input("👤 Username or Email: ").strip()
        if username:
            credentials['username'] = username
        
        # Ask for password
        password = input("🔑 Password: ").strip()
        if password:
            credentials['password'] = password
        
        # Ask for OTP if needed
        print("\n❓ Is an OTP (One-Time Password) required?")
        needs_otp = input("   Enter 'y' for yes, 'n' for no: ").strip().lower()
        
        if needs_otp == 'y':
            otp = input("   🔐 Enter OTP: ").strip()
            if otp:
                credentials['otp'] = otp
        
        # Ask for any other credentials
        print("\n❓ Are there other credentials needed? (e.g., security questions)")
        other = input("   Enter them or leave blank to skip: ").strip()
        if other:
            credentials['other'] = other
        
        print(f"\n✅ Credentials collected: {', '.join(credentials.keys())}")
        return credentials
    
    @staticmethod
    def ask_for_login_form_fields() -> Dict[str, str]:
        """
        Ask user to identify login form fields visually.
        This is called when the vision engine needs help mapping credentials to fields.
        
        Returns:
            Dictionary mapping field names to values
        """
        print("\n" + "="*70)
        print("🔍 HELP: IDENTIFYING LOGIN FIELDS")
        print("="*70)
        print("\n📸 Can you see the login form on the screen?")
        print("Please identify where to enter your credentials:\n")
        
        fields = {}
        
        print("Examples:")
        print("  - 'Username/Email field': [Look for input field labeled 'Username', 'Email', 'User ID', etc.]")
        print("  - 'Password field': [Look for input field labeled 'Password', 'Pass', etc.]\n")
        
        field_count = 1
        while True:
            field_name = input(f"Field {field_count} name (or leave blank to finish): ").strip()
            if not field_name:
                break
            
            field_value = input(f"   What to enter in '{field_name}': ").strip()
            if field_value:
                fields[field_name] = field_value
                field_count += 1
        
        return fields
    
    @staticmethod
    def confirm_action(prompt: str) -> bool:
        """
        Ask user to confirm an action.
        
        Args:
            prompt: Confirmation prompt
            
        Returns:
            True if user confirms, False otherwise
        """
        while True:
            response = input(f"\n{prompt} (y/n): ").strip().lower()
            if response == 'y':
                return True
            elif response == 'n':
                return False
            else:
                print("❌ Please enter 'y' or 'n'")
    
    @staticmethod
    def display_floor_plan(floor_plan: List[str]):
        """
        Display the generated floor plan to user with clear visual formatting.
        
        Args:
            floor_plan: List of high-level steps
        """
        print("\n" + "█"*80)
        print("█" + " "*78 + "█")
        print("█" + "  📋 GENERATED FLOOR PLAN - STEP-BY-STEP EXECUTION GUIDE  ".center(78) + "█")
        print("█" + " "*78 + "█")
        print("█"*80)
        
        print("\n  The system will execute the following steps:\n")
        
        # Display steps with visual formatting
        for i, step in enumerate(floor_plan, 1):
            # Add arrow and step number
            print(f"  ► Step {i}:")
            print(f"    └─ {step}\n")
        
        print("█"*80)
        print("█" + " "*78 + "█")
        print("█" + "  ℹ️ INTERACTIVE PROMPTS  ".ljust(78) + "█")
        print("█" + " "*78 + "█")
        print("█  If the system encounters:                                                  █")
        print("█    • Form fields (text boxes, inputs)  → You'll be asked to provide values  █")
        print("█    • Dropdowns or selections           → You'll be asked which option       █")
        print("█    • OTP or verification codes         → You'll be asked to enter them      █")
        print("█    • Any blocking element              → You'll get clear instructions      █")
        print("█" + " "*78 + "█")
        print("█"*80)


class ReportGenerator:
    """
    Generates detailed JSON reports with human-readable narrative
    """
    
    # Class variable to track detailed step-by-step narrative
    detailed_steps = []
    
    @classmethod
    def add_step_detail(cls, step_number: int, observation: str, decision: str, 
                       action_taken: str, result: str, success: bool, error: str = None):
        """
        Add detailed information about a single step for human-readable narrative.
        
        Args:
            step_number: Step number
            observation: What Claude observed on the page
            decision: Why Claude decided to take this action
            action_taken: What action was executed
            result: What happened after the action
            success: Whether the action succeeded
            error: Error message if failed
        """
        cls.detailed_steps.append({
            "step": step_number,
            "observation": observation,
            "decision": decision,
            "action": action_taken,
            "result": result,
            "success": success,
            "error": error
        })
    
    @staticmethod
    def generate_report(test_case: TestCase) -> Dict:
        """
        Generate a detailed report of the test execution.
        
        Args:
            test_case: TestCase object with execution details
            
        Returns:
            Dictionary containing the full report
        """
        test_case.completed_at = datetime.now()
        duration = (test_case.completed_at - test_case.started_at).total_seconds()
        
        report = {
            "test_metadata": {
                "mode": test_case.mode.upper(),
                "url": test_case.url,
                "goal": test_case.goal,
                "timestamp": test_case.started_at.isoformat(),
                "duration_seconds": round(duration, 2),
                "status": "PASSED" if test_case.success else "FAILED"
            },
            "execution_details": {
                "total_steps": len(test_case.action_history),
                "steps_executed": test_case.action_history,
                "success": test_case.success,
                "error": test_case.error_message
            },
            "whitebox_details": {
                "planned_steps": test_case.steps if test_case.mode == 'whitebox' else []
            } if test_case.mode == 'whitebox' else {},
            "credentials_used": {
                k: v if k != 'password' else '***' for k, v in test_case.credentials_collected.items()
            } if test_case.credentials_collected else {},
            "detailed_narrative": ReportGenerator._generate_detailed_narrative(),
            "summary": ReportGenerator._generate_summary(test_case)
        }
        
        return report
    
    @staticmethod
    def _generate_detailed_narrative() -> List[Dict]:
        """
        Generate a human-readable step-by-step narrative of what happened.
        
        Returns:
            List of step details in narrative form
        """
        return ReportGenerator.detailed_steps
    
    @staticmethod
    def _generate_summary(test_case: TestCase) -> str:
        """Generate a text summary of the test."""
        if test_case.success:
            return f"✅ Test completed successfully in {len(test_case.action_history)} steps"
        else:
            return f"❌ Test failed: {test_case.error_message}"
    
    @staticmethod
    def save_report(report: Dict, filename: str = None) -> str:
        """
        Save report to JSON file and also create a human-readable narrative file.
        
        Args:
            report: Report dictionary
            filename: Optional custom filename
            
        Returns:
            Path to saved report file
        """
        import json
        from pathlib import Path
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_report_{timestamp}.json"
        
        # Save JSON report
        filepath = Path(filename)
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Also save human-readable narrative version
        txt_filename = filename.replace('.json', '_narrative.txt')
        txt_filepath = Path(txt_filename)
        
        with open(txt_filepath, 'w', encoding='utf-8') as f:
            # Write header
            f.write("="*80 + "\n")
            f.write("TEST EXECUTION NARRATIVE REPORT\n")
            f.write("="*80 + "\n\n")
            
            # Write metadata
            metadata = report.get('test_metadata', {})
            f.write(f"Mode: {metadata.get('mode')}\n")
            f.write(f"URL: {metadata.get('url')}\n")
            f.write(f"Goal: {metadata.get('goal')}\n")
            f.write(f"Status: {metadata.get('status')}\n")
            f.write(f"Duration: {metadata.get('duration_seconds')} seconds\n")
            f.write(f"Timestamp: {metadata.get('timestamp')}\n")
            f.write("\n" + "-"*80 + "\n\n")
            
            # Write detailed narrative
            detailed = report.get('detailed_narrative', [])
            if detailed:
                f.write("STEP-BY-STEP EXECUTION DETAILS\n")
                f.write("-"*80 + "\n\n")
                
                for step in detailed:
                    step_num = step.get('step', '?')
                    status = "✓ SUCCESS" if step.get('success') else "✗ FAILED"
                    
                    f.write(f"STEP {step_num}: {status}\n")
                    f.write("-" * 40 + "\n")
                    
                    observation = step.get('observation', 'N/A')
                    f.write(f"What Claude Observed:\n")
                    f.write(f"  {observation}\n\n")
                    
                    decision = step.get('decision', 'N/A')
                    f.write(f"Why Claude Decided:\n")
                    f.write(f"  {decision}\n\n")
                    
                    action = step.get('action', 'N/A')
                    f.write(f"Action Taken:\n")
                    f.write(f"  {action}\n\n")
                    
                    result = step.get('result', 'N/A')
                    f.write(f"Result:\n")
                    f.write(f"  {result}\n")
                    
                    if not step.get('success') and step.get('error'):
                        error = step.get('error', 'N/A')
                        f.write(f"\nError Details:\n")
                        f.write(f"  {error}\n")
                    
                    f.write("\n" + "="*80 + "\n\n")
            
            # Write summary
            f.write("SUMMARY\n")
            f.write("-"*80 + "\n")
            f.write(report.get('summary', 'N/A') + "\n")
            
            if metadata.get('status') == 'FAILED':
                execution = report.get('execution_details', {})
                if execution.get('error'):
                    f.write(f"\nFailure Reason: {execution.get('error')}\n")
        
        print(f"\n✅ Reports saved:")
        print(f"   JSON: {filepath}")
        print(f"   Narrative: {txt_filepath}\n")
        
        return str(filepath)
    
    @staticmethod
    def print_report(report: Dict):
        """Print a formatted report to console."""
        import json
        
        print("\n" + "="*80)
        print("📊 TEST REPORT")
        print("="*80)
        
        metadata = report.get('test_metadata', {})
        print(f"\n🎯 Mode: {metadata.get('mode')}")
        print(f"📍 URL: {metadata.get('url')}")
        print(f"🎯 Goal: {metadata.get('goal')}")
        print(f"⏱️  Duration: {metadata.get('duration_seconds')}s")
        print(f"📋 Status: {metadata.get('status')}")
        
        execution = report.get('execution_details', {})
        print(f"\n📈 Total Steps: {execution.get('total_steps')}")
        
        # Print detailed narrative if available
        detailed = report.get('detailed_narrative', [])
        if detailed:
            print("\n" + "-"*80)
            print("📝 DETAILED STEP-BY-STEP NARRATIVE")
            print("-"*80)
            
            for step in detailed:
                step_num = step.get('step', '?')
                status_icon = "✅" if step.get('success') else "❌"
                
                print(f"\n{status_icon} STEP {step_num}")
                print(f"   What Claude Observed:")
                print(f"      {step.get('observation', 'N/A')}")
                print(f"   Why Claude Decided:")
                print(f"      {step.get('decision', 'N/A')}")
                print(f"   Action Taken:")
                print(f"      {step.get('action', 'N/A')}")
                print(f"   Result:")
                print(f"      {step.get('result', 'N/A')}")
                
                if not step.get('success') and step.get('error'):
                    print(f"   Error:")
                    print(f"      {step.get('error', 'N/A')}")
        
        # Print standard action history
        if execution.get('steps_executed'):
            print("\n" + "-"*80)
            print("📋 ACTION HISTORY")
            print("-"*80)
            for i, step in enumerate(execution.get('steps_executed', []), 1):
                print(f"   {i}. {step}")
        
        if execution.get('error'):
            print(f"\n❌ Overall Error: {execution.get('error')}")
        
        print(f"\n📝 Summary: {report.get('summary')}")
        print("="*70 + "\n")
