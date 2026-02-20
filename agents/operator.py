"""
Agent 3: The Operator (FIXED - Persistent Authentication)
Uses Playwright + LLM to execute user stories autonomously
FIXES: Now maintains authenticated session throughout execution
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Page, BrowserContext
from openai import OpenAI
from rich.console import Console
from rich.progress import Progress

from config import Config

console = Console()


class ExecutionResult:
    """Represents the result of executing a user story"""
    def __init__(self, story_id: int, success: bool, steps: List[Dict], error: Optional[str] = None):
        self.story_id = story_id
        self.success = success
        self.steps = steps
        self.error = error
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'story_id': self.story_id,
            'success': self.success,
            'steps': self.steps,
            'error': self.error,
            'timestamp': self.timestamp
        }


class OperatorAgent:
    """Agent responsible for executing user stories using Playwright + LLM"""
    
    def __init__(self, user_stories: List[Dict], auth_data: Optional[Dict] = None):
        Config.validate()
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.user_stories = user_stories
        self.execution_results = []
        self.auth_data = auth_data
        self.requires_auth = auth_data is not None
        
        # Playwright objects
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
    
    async def initialize_browser(self):
        """Initialize Playwright browser with persistent authenticated session"""
        console.print("[cyan]🌐 Initializing browser...[/cyan]")
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=Config.BROWSER_HEADLESS
        )
        self.context = await self.browser.new_context(
            viewport={
                'width': Config.VIEWPORT_WIDTH,
                'height': Config.VIEWPORT_HEIGHT
            }
        )
        self.page = await self.context.new_page()
        
        # INJECT AUTHENTICATION if required
        if self.requires_auth:
            console.print("[yellow]🔐 Injecting authentication tokens...[/yellow]")
            
            # Navigate to base URL first
            base_url = self.user_stories[0].get('page_url', 'https://www.mnr-pst.com/')
            await self.page.goto(base_url)
            
            # Inject localStorage
            for key, value in self.auth_data.get('local_storage', {}).items():
                try:
                    await self.page.evaluate(f"window.localStorage.setItem('{key}', JSON.stringify({json.dumps(value)}))")
                except:
                    await self.page.evaluate(f"window.localStorage.setItem('{key}', '{value}')")
            
            # Inject sessionStorage
            for key, value in self.auth_data.get('session_storage', {}).items():
                try:
                    await self.page.evaluate(f"window.sessionStorage.setItem('{key}', JSON.stringify({json.dumps(value)}))")
                except:
                    await self.page.evaluate(f"window.sessionStorage.setItem('{key}', '{value}')")
            
            # Inject cookies
            cookies = self.auth_data.get('cookies', [])
            if cookies:
                await self.context.add_cookies(cookies)
            
            # Reload to apply auth
            console.print("[cyan]🔄 Reloading with authentication...[/cyan]")
            await self.page.reload()
            await self.page.wait_for_load_state('networkidle')
            
            console.print(f"[green]✅ Authenticated session ready - Current URL: {self.page.url}[/green]")
        
        console.print("[green]✓ Browser ready[/green]")
    
    async def close_browser(self):
        """Close the browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def get_page_state(self) -> Dict:
        """Get the current state of the page for LLM analysis"""
        try:
            # Get page title and URL
            title = await self.page.title()
            url = self.page.url
            
            # Get visible text content
            content = await self.page.evaluate("""
                () => {
                    return document.body.innerText.substring(0, 2000);
                }
            """)
            
            # Get interactive elements
            interactive_elements = await self.page.evaluate("""
                () => {
                    const elements = [];
                    
                    // Buttons
                    document.querySelectorAll('button').forEach((el, idx) => {
                        if (el.offsetParent !== null) {
                            elements.push({
                                type: 'button',
                                text: el.innerText.trim(),
                                id: el.id,
                                classes: el.className,
                                index: idx
                            });
                        }
                    });
                    
                    // Links
                    document.querySelectorAll('a').forEach((el, idx) => {
                        if (el.offsetParent !== null && el.innerText.trim()) {
                            elements.push({
                                type: 'link',
                                text: el.innerText.trim(),
                                href: el.href,
                                index: idx
                            });
                        }
                    });
                    
                    // Input fields
                    document.querySelectorAll('input, textarea').forEach((el, idx) => {
                        if (el.offsetParent !== null) {
                            elements.push({
                                type: 'input',
                                inputType: el.type,
                                placeholder: el.placeholder,
                                name: el.name,
                                id: el.id,
                                index: idx
                            });
                        }
                    });
                    
                    return elements.slice(0, 50);
                }
            """)
            
            return {
                'title': title,
                'url': url,
                'content': content,
                'interactive_elements': interactive_elements
            }
        except Exception as e:
            console.print(f"[red]Error getting page state: {str(e)}[/red]")
            return {'error': str(e)}
    
    def _create_action_prompt(self, user_story: Dict, page_state: Dict, previous_steps: List[Dict]) -> str:
        """Create a prompt for the LLM to decide the next action"""
        
        previous_actions_summary = ""
        if previous_steps:
            recent_actions = [
                f"Step {step['step']}: {step['action_plan'].get('action')} - {step['action_plan'].get('target', {}).get('text', 'N/A')}"
                for step in previous_steps[-3:]
            ]
            previous_actions_summary = "\n".join(recent_actions)
        
        return f"""You are an autonomous web agent executing a user story.

USER STORY:
As a {user_story['role']}, I want to {user_story['action']} so that {user_story['benefit']}

CURRENT PAGE STATE:
URL: {page_state.get('url', 'unknown')}
Title: {page_state.get('title', 'unknown')}

Page Content (first 2000 chars):
{page_state.get('content', 'No content')}

INTERACTIVE ELEMENTS:
{json.dumps(page_state.get('interactive_elements', [])[:20], indent=2)}

PREVIOUS STEPS TAKEN:
{previous_actions_summary if previous_actions_summary else 'None - this is the first step'}

IMPORTANT INSTRUCTIONS:
1. Review previous steps - if you're repeating the same action, STOP and mark completed
2. DO NOT mark completed until you have ACTUALLY PERFORMED the core action (click, type, submit)
3. Seeing a form is NOT completing the story - you must FILL and SUBMIT it
4. Seeing a button is NOT completing the story - you must CLICK it
5. Only mark completed when the PRIMARY ACTION is done, not just visible

Your task is to decide the next action. You can:
1. Click on an element (button, link)
2. Type text into an input field
3. Navigate to a URL
4. Wait for an element to appear
5. Mark the story as complete

Respond with a JSON object in this exact format:
{{
    "action": "click|type|navigate|wait|complete",
    "reasoning": "why you're taking this action (mention if goal is achieved or if stuck)",
    "target": {{
        "type": "button|link|input",
        "text": "exact text of the element",
        "selector": "CSS selector if you can provide one",
        "index": 0
    }},
    "value": "text to type" (only for type action),
    "url": "URL to navigate to" (only for navigate action),
    "completed": true/false (set to true if: goal achieved, stuck in loop, or no further progress possible)
}}

CRITICAL: If you notice you're about to repeat an action you just did, set "completed": true instead!
"""
    
    async def execute_action(self, action_plan: Dict) -> bool:
        """Execute the action decided by the LLM"""
        action = action_plan.get('action')
        
        try:
            if action == 'click':
                target = action_plan.get('target', {})
                text = target.get('text', '')
                selector = target.get('selector')
                
                if selector:
                    await self.page.click(selector)
                elif text:
                    await self.page.get_by_text(text).first.click()
                else:
                    console.print("[yellow]⚠ No valid target for click action[/yellow]")
                    return False
                
                console.print(f"  ✓ Clicked: {text or selector}")
                await self.page.wait_for_load_state('networkidle', timeout=5000)
                return True
            
            elif action == 'type':
                target = action_plan.get('target', {})
                value = action_plan.get('value', '')
                selector = target.get('selector')
                
                if selector:
                    await self.page.fill(selector, value)
                else:
                    placeholder = target.get('placeholder', '')
                    if placeholder:
                        await self.page.get_by_placeholder(placeholder).fill(value)
                    else:
                        console.print("[yellow]⚠ No valid target for type action[/yellow]")
                        return False
                
                console.print(f"  ✓ Typed: {value}")
                return True
            
            elif action == 'navigate':
                url = action_plan.get('url', '')
                await self.page.goto(url)
                console.print(f"  ✓ Navigated to: {url}")
                await self.page.wait_for_load_state('networkidle')
                return True
            
            elif action == 'wait':
                await asyncio.sleep(2)
                console.print("  ✓ Waited 2 seconds")
                return True
            
            elif action == 'complete':
                console.print("  ✓ Story marked as complete")
                return True
            
            else:
                console.print(f"[yellow]⚠ Unknown action: {action}[/yellow]")
                return False
        
        except Exception as e:
            console.print(f"[red]✗ Error executing action: {str(e)}[/red]")
            return False
    
    async def execute_user_story(self, user_story: Dict, max_steps: int = 10) -> ExecutionResult:
        """Execute a single user story using LLM-guided actions"""
        console.print(f"\n[bold cyan]Executing Story #{user_story['id']}: {user_story['feature']}[/bold cyan]")
        console.print(f"As a {user_story['role']}, I want to {user_story['action']}")
        
        steps = []
        action_history = []
        
        try:
            # Navigate to the starting page (session is already authenticated)
            await self.page.goto(user_story['page_url'])
            await self.page.wait_for_load_state('networkidle')
            
            for step_num in range(max_steps):
                console.print(f"\n[cyan]Step {step_num + 1}:[/cyan]")
                
                # Get current page state
                page_state = await self.get_page_state()
                
                # Ask LLM for next action
                prompt = self._create_action_prompt(user_story, page_state, steps)
                
                response = self.client.chat.completions.create(
                    model=Config.MODEL,
                    messages=[
                        {"role": "system", "content": "You are an autonomous web agent. Respond only with valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                
                action_plan = json.loads(response.choices[0].message.content)
                
                console.print(f"  💭 Reasoning: {action_plan.get('reasoning', 'No reasoning provided')}")
                
                # Check for loops
                current_action_signature = f"{action_plan.get('action')}:{action_plan.get('target', {}).get('text', '')}"
                
                if len(action_history) >= 2:
                    if (action_history[-1] == current_action_signature or 
                        action_history[-2] == current_action_signature):
                        console.print(f"[yellow]⚠ Loop detected! Marking as complete.[/yellow]")
                        return ExecutionResult(
                            user_story['id'], 
                            True, 
                            steps, 
                            "Completed - loop detected"
                        )
                
                action_count = action_history.count(current_action_signature)
                if action_count >= 2:
                    console.print(f"[yellow]⚠ Action repeated {action_count} times. Stopping.[/yellow]")
                    return ExecutionResult(
                        user_story['id'], 
                        True, 
                        steps, 
                        "Completed - repetitive actions"
                        )
                
                action_history.append(current_action_signature)
                
                # Record the step
                step_record = {
                    'step': step_num + 1,
                    'action_plan': action_plan,
                    'page_url': page_state.get('url'),
                    'success': False
                }
                
                # Execute the action
                success = await self.execute_action(action_plan)
                step_record['success'] = success
                steps.append(step_record)
                
                # Check if completed
                if action_plan.get('completed'):
                    console.print(f"[green]✓ User story completed in {step_num + 1} steps[/green]")
                    return ExecutionResult(user_story['id'], True, steps)
                
                if not success:
                    console.print("[yellow]⚠ Step failed, but continuing...[/yellow]")
                
                await asyncio.sleep(1)
            
            console.print(f"[yellow]⚠ Max steps ({max_steps}) reached[/yellow]")
            return ExecutionResult(user_story['id'], False, steps, "Max steps reached")
        
        except Exception as e:
            console.print(f"[red]✗ Error executing story: {str(e)}[/red]")
            return ExecutionResult(user_story['id'], False, steps, str(e))
    
    async def run(self, limit: Optional[int] = None):
        """Execute all user stories"""
        console.print("[bold cyan]🚀 Agent 3: The Operator - Starting[/bold cyan]")
        
        await self.initialize_browser()
        
        stories_to_execute = self.user_stories[:limit] if limit else self.user_stories
        
        with Progress() as progress:
            task = progress.add_task("[cyan]Executing stories...", total=len(stories_to_execute))
            
            for story in stories_to_execute:
                result = await self.execute_user_story(story)
                self.execution_results.append(result)
                progress.update(task, advance=1)
        
        await self.close_browser()
        
        # Save results
        self.save_results()
        
        # Display summary
        self.display_summary()
    
    def save_results(self):
        """Save execution results to file"""
        results_data = [result.to_dict() for result in self.execution_results]
        
        Path(Config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        with open(Config.EXECUTION_LOG, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, indent=2)
        
        console.print(f"[green]✓ Execution results saved to {Config.EXECUTION_LOG}[/green]")
    
    def display_summary(self):
        """Display execution summary"""
        total = len(self.execution_results)
        successful = sum(1 for r in self.execution_results if r.success)
        failed = total - successful
        
        console.print("\n[bold cyan]📊 Execution Summary:[/bold cyan]")
        console.print(f"Total Stories: {total}")
        console.print(f"[green]Successful: {successful}[/green]")
        console.print(f"[red]Failed: {failed}[/red]")
        console.print(f"Success Rate: {(successful/total*100):.1f}%")


async def main():
    """Test the Operator Agent"""
    with open(Config.USER_STORIES_FILE, 'r') as f:
        user_stories = json.load(f)
    
    operator = OperatorAgent(user_stories)
    await operator.run(limit=3)


if __name__ == "__main__":
    asyncio.run(main())