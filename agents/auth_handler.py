"""
Authentication Handler
Manages authentication for websites that require login
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from rich.console import Console

console = Console()


class AuthHandler:
    """Handles authentication flow for protected websites"""
    
    def __init__(self, login_url: str, auth_file: str = "auth.json"):
        self.login_url = login_url
        self.auth_file = Path(auth_file)
        self.auth_data = None
    
    async def capture_auth(self) -> dict:
        """
        Launch browser for manual login and capture authentication data
        Returns: dict with local_storage, session_storage, and cookies
        """
        console.print(f"[cyan]🔐 Launching browser for manual authentication...[/cyan]")
        console.print(f"[cyan]📍 Login URL: {self.login_url}[/cyan]")
        
        async with async_playwright() as p:
            # Launch browser in headed mode so user can login
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Navigate to login page
            await page.goto(self.login_url)
            
            # Wait for user to complete login
            console.print("\n" + "="*60)
            console.print("[bold yellow]🔴 ACTION REQUIRED:[/bold yellow]")
            console.print("1. Complete the login process in the browser window")
            console.print("   (Enter username, password, OTP, etc.)")
            console.print("2. Wait until you reach the dashboard/home page")
            console.print("3. Return here and press ENTER to continue")
            console.print("="*60 + "\n")
            
            input("Press ENTER after successful login... ")
            
            # Extract authentication data
            console.print("[cyan]📦 Capturing authentication tokens...[/cyan]")
            
            # Get localStorage
            local_storage = await page.evaluate("() => JSON.stringify(window.localStorage)")
            
            # Get sessionStorage (some sites use this)
            session_storage = await page.evaluate("() => JSON.stringify(window.sessionStorage)")
            
            # Get cookies
            cookies = await context.cookies()
            
            # Get current URL (post-login)
            current_url = page.url
            
            # Store authentication data
            self.auth_data = {
                "local_storage": json.loads(local_storage),
                "session_storage": json.loads(session_storage),
                "cookies": cookies,
                "post_login_url": current_url
            }
            
            # Save to file
            with open(self.auth_file, "w") as f:
                json.dump(self.auth_data, f, indent=2)
            
            console.print(f"[green]✅ Authentication data saved to {self.auth_file}[/green]")
            console.print(f"[dim]Captured: {len(self.auth_data['local_storage'])} localStorage items, "
                         f"{len(self.auth_data['cookies'])} cookies[/dim]")
            
            await browser.close()
            
        return self.auth_data
    
    def load_auth(self) -> dict:
        """
        Load existing authentication data from file
        Returns: dict with local_storage and cookies, or None if file doesn't exist
        """
        if not self.auth_file.exists():
            console.print(f"[yellow]⚠️  {self.auth_file} not found[/yellow]")
            return None
        
        with open(self.auth_file, "r") as f:
            self.auth_data = json.load(f)
        
        console.print(f"[green]✅ Loaded authentication data from {self.auth_file}[/green]")
        console.print(f"[dim]Found: {len(self.auth_data.get('local_storage', {}))} localStorage items, "
                     f"{len(self.auth_data.get('cookies', []))} cookies[/dim]")
        
        return self.auth_data
    
    def auth_exists(self) -> bool:
        """Check if auth file exists"""
        return self.auth_file.exists()
    
    async def get_or_create_auth(self) -> dict:
        """
        Smart method: Load existing auth or create new one
        Returns: authentication data
        """
        if self.auth_exists():
            console.print("[cyan]🔄 Found existing authentication data[/cyan]")
            return self.load_auth()
        else:
            console.print("[cyan]🆕 No existing auth found, starting manual login...[/cyan]")
            return await self.capture_auth()


if __name__ == "__main__":
    # Test the auth handler
    async def test():
        handler = AuthHandler("https://www.mnr-pst.com/login")
        auth_data = await handler.get_or_create_auth()
        print(f"Auth data keys: {auth_data.keys()}")
    
    asyncio.run(test())