"""
Main Orchestrator (with Authentication Support)
Coordinates the three-agent workflow: Explorer → Architect → Operator
NOW WITH: Automatic authentication handling
"""

import asyncio
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.explorer import ExplorerAgent
from agents.architect import ArchitectAgent
from agents.operator import OperatorAgent
from agents.auth_handler import AuthHandler
from config import Config

console = Console()


class AIWebAgent:
    """Main orchestrator for the three-agent system with authentication support"""
    
    def __init__(
        self, 
        target_url: str, 
        requires_auth: bool = False,
        login_url: str = None,
        execute_stories: bool = True, 
        max_stories_to_execute: int = None
    ):
        """
        Initialize the AI Web Agent system
        
        Args:
            target_url: The website to crawl (e.g., https://example.com/dashboard)
            requires_auth: Set to True if the site requires login
            login_url: URL of the login page (defaults to target_url if not provided)
            execute_stories: Whether to execute user stories with Operator agent
            max_stories_to_execute: Limit number of stories to execute (None = all)
        """
        self.target_url = target_url
        self.requires_auth = requires_auth
        self.login_url = login_url or target_url  # Default to target_url if not specified
        self.execute_stories = execute_stories
        self.max_stories_to_execute = max_stories_to_execute
        
        self.auth_data = None
        self.knowledge_base = None
        self.user_stories = None
        self.execution_results = None
    
    async def handle_authentication(self) -> dict:
        """
        Handle authentication flow
        - Check if auth.json exists
        - If yes: load and reuse
        - If no: launch browser for manual login
        
        Returns: auth_data dict
        """
        console.print("\n" + "="*80)
        console.print("[bold]AUTHENTICATION PHASE[/bold]")
        console.print("="*80 + "\n")
        
        auth_handler = AuthHandler(self.login_url, auth_file="auth.json")
        
        # Smart auth: reuse existing or create new
        self.auth_data = await auth_handler.get_or_create_auth()
        
        return self.auth_data
    
    async def run(self):
        """Execute the complete three-agent workflow with optional authentication"""
        
        console.print(Panel.fit(
            "[bold cyan]🤖 AI Web Agent System[/bold cyan]\n"
            f"Target: {self.target_url}\n"
            f"Authentication: {'🔐 ENABLED' if self.requires_auth else '🔓 DISABLED'}\n"
            "Three-Agent Architecture:\n"
            "  1️⃣  Explorer (Crawl4AI) - Maps the site\n"
            "  2️⃣  Architect (GPT-4o-mini) - Generates user stories\n"
            "  3️⃣  Operator (Playwright + GPT) - Executes stories",
            title="🏗️ Starting System"
        ))
        
        # Validate configuration
        try:
            Config.validate()
        except ValueError as e:
            console.print(f"[red]Configuration error: {e}[/red]")
            console.print("\n[yellow]Please create a .env file with:[/yellow]")
            console.print("OPENAI_API_KEY=your_api_key_here")
            return
        
        # ============================================================
        # AUTHENTICATION PHASE (if required)
        # ============================================================
        if self.requires_auth:
            await self.handle_authentication()
        else:
            console.print("\n[cyan]🔓 No authentication required, proceeding directly to exploration[/cyan]")
        
        # ============================================================
        # Phase 1: Explorer Agent
        # ============================================================
        console.print("\n" + "="*80)
        console.print("[bold]PHASE 1: EXPLORATION[/bold]")
        console.print("="*80 + "\n")
        
        # Pass auth_data to Explorer (None if no auth required)
        explorer = ExplorerAgent(self.target_url, auth_data=self.auth_data)
        self.knowledge_base = await explorer.run()
        
        # ============================================================
        # Phase 2: Architect Agent
        # ============================================================
        console.print("\n" + "="*80)
        console.print("[bold]PHASE 2: ARCHITECTURE[/bold]")
        console.print("="*80 + "\n")
        
        architect = ArchitectAgent(self.knowledge_base)
        self.user_stories = architect.run()
        
        # ============================================================
        # Phase 3: Operator Agent (optional)
        # ============================================================
        if self.execute_stories:
            console.print("\n" + "="*80)
            console.print("[bold]PHASE 3: OPERATION[/bold]")
            console.print("="*80 + "\n")
            
            # Convert UserStory objects to dicts
            stories_dict = [story.model_dump() for story in self.user_stories]
            
            operator = OperatorAgent(stories_dict, auth_data=self.auth_data)
            await operator.run(limit=self.max_stories_to_execute)
            self.execution_results = operator.execution_results
        else:
            console.print("\n[yellow]⏭️  Skipping execution phase (execute_stories=False)[/yellow]")
        
        # ============================================================
        # Final Summary
        # ============================================================
        self._display_final_summary()
    
    def _display_final_summary(self):
        """Display final summary of the entire workflow"""
        console.print("\n" + "="*80)
        console.print("[bold cyan]FINAL SUMMARY[/bold cyan]")
        console.print("="*80 + "\n")
        
        console.print(f"[cyan]🎯 Target Site:[/cyan] {self.target_url}")
        console.print(f"[cyan]🔐 Authentication:[/cyan] {'Enabled ✓' if self.requires_auth else 'Disabled'}")
        console.print(f"[cyan]📄 Pages Crawled:[/cyan] {self.knowledge_base['total_pages']}")
        console.print(f"[cyan]📋 User Stories Generated:[/cyan] {len(self.user_stories)}")
        
        if self.execution_results:
            successful = sum(1 for r in self.execution_results if r.success)
            total = len(self.execution_results)
            console.print(f"[cyan]✅ Stories Executed:[/cyan] {successful}/{total} successful")
        
        console.print("\n[bold green]✓ All phases complete![/bold green]")
        console.print("\n[cyan]Output files:[/cyan]")
        console.print(f"  • Knowledge Base: {Config.OUTPUT_DIR}/knowledge_base.json")
        console.print(f"  • Markdown Content: {Config.MARKDOWN_DIR}/")
        console.print(f"  • User Stories: {Config.USER_STORIES_FILE}")
        if self.requires_auth:
            console.print(f"  • Auth Tokens: auth.json")
        if self.execution_results:
            console.print(f"  • Execution Log: {Config.EXECUTION_LOG}")


async def main():
    """Main entry point"""
    
    # ============================================================
    # CONFIGURATION - Customize these parameters
    # ============================================================
    
    # Example 1: Website WITHOUT authentication
    # TARGET_URL = "https://www.mnrpureai.com/"
    # REQUIRES_AUTH = False
    # LOGIN_URL = None
    
    # Example 2: Website WITH authentication
    TARGET_URL = "https://staging.isalaam.me/dashboard"  # The page you want to crawl
    REQUIRES_AUTH = True  # Set to True for protected sites
    LOGIN_URL = "https://staging.isalaam.me/sign-in"  # The login page URL
    
    EXECUTE_STORIES = True  # Set to False to skip execution
    MAX_STORIES = None  # Limit number of stories to execute (None for all)
    
    # ============================================================
    # Command line override (optional)
    # ============================================================
    if len(sys.argv) > 1:
        TARGET_URL = sys.argv[1]
        if len(sys.argv) > 2:
            REQUIRES_AUTH = sys.argv[2].lower() in ['true', '1', 'yes']
    
    # ============================================================
    # Run the system
    # ============================================================
    agent_system = AIWebAgent(
        target_url=TARGET_URL,
        requires_auth=REQUIRES_AUTH,
        login_url=LOGIN_URL,
        execute_stories=EXECUTE_STORIES,
        max_stories_to_execute=MAX_STORIES
    )
    
    await agent_system.run()


if __name__ == "__main__":
    asyncio.run(main())