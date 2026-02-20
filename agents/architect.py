"""
Agent 2: The Architect
Analyzes the scraped content and generates functional user stories
"""

import json
from pathlib import Path
from typing import List, Dict
from openai import OpenAI
from rich.console import Console
from pydantic import BaseModel

from config import Config

console = Console()


class UserStory(BaseModel):
    """Represents a functional user story"""
    id: int
    role: str
    action: str
    benefit: str
    feature: str
    priority: str  # high, medium, low
    page_url: str


class ArchitectAgent:
    """Agent responsible for analyzing content and generating user stories"""
    
    def __init__(self, knowledge_base: Dict):
        Config.validate()
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.knowledge_base = knowledge_base
        self.user_stories = []
    
    def _create_analysis_prompt(self, content_sample: str) -> str:
        """Modified prompt to generate detailed execution-style actions"""
        return f"""You are a QA Automation Engineer creating detailed test cases.

    Website: {self.knowledge_base['base_url']}
    Credentials: User: '{Config.AUTH_USERNAME}', Pass: '{Config.AUTH_PASSWORD}', OTP: '999999'

    CONTENT MAP:
    {content_sample}

    Your task:
    Generate 8-12 functional test scenarios. 

    CRITICAL FORMAT REQUIREMENT:
    The 'action' field MUST be a detailed, step-by-step instruction string exactly like this:
    "Login with username '{Config.AUTH_USERNAME}' and password '{Config.AUTH_PASSWORD}' and use the otp 999999 then go to the [Module Name] select [Dropdown 1] as [Value] then select [Dropdown 2] as [Value] and [Final Action]"

    REQUIREMENTS:
    1. Use the specific dropdown options (like 'Class 10', 'Chemistry', 'Economics') found in the content map.
    2. Ensure the sequence follows the cascading logic discovered (e.g., Subject -> Chapter).
    3. Every action must start with the login sequence.

    Return ONLY a JSON object:
    {{
    "stories": [
        {{
        "role": "teacher",
        "action": "Login with username '{Config.AUTH_USERNAME}' and password '{Config.AUTH_PASSWORD}' and use the otp 999999 then go to the Virtual Lab Module Select class as 10 and then select as Chemistry and then select Acid And base experiment and perform it",
        "benefit": "I can demonstrate chemical reactions virtually",
        "feature": "Virtual Lab",
        "priority": "high",
        "page_url": "{self.knowledge_base['base_url']}"
        }}
    ]
    }}
    """    
    def _prepare_content_sample(self, max_chars: int = 15000) -> str:
        """Prepare a representative sample of site content for analysis"""
        content_parts = []
        char_count = 0
        
        # FIX: Use 'feature_hierarchy' or 'main_pages' instead of 'content'
        pages = self.knowledge_base.get('feature_hierarchy', [])
        
        for page in pages:
            if char_count >= max_chars:
                break
            
            url = page.get('url', 'Unknown URL')
            name = page.get('name', 'Unnamed Page')
            features = page.get('features', [])
            
            # Create a summary of the features for the LLM
            feature_summary = "\n".join([f"- {f['type']}: {f['label']}" for f in features])
            
            page_content = f"## Page: {name} ({url})\nFeatures Found:\n{feature_summary}\n\n"
            content_parts.append(page_content)
            char_count += len(page_content)
        
        return "\n".join(content_parts)
    
    def generate_user_stories(self) -> List[UserStory]:
        """
        Use LLM to generate user stories from the website content
        """
        console.print("[cyan]ðŸ—ï¸  Generating user stories from website content[/cyan]")
        
        # Prepare content sample
        content_sample = self._prepare_content_sample()
        
        # Create prompt
        prompt = self._create_analysis_prompt(content_sample)
        
        try:
            # Call GPT-4o mini
            console.print(f"[cyan]Calling {Config.MODEL}...[/cyan]")
            response = self.client.chat.completions.create(
                model=Config.MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert Product Manager skilled at analyzing websites and creating functional user stories for testing."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            # Parse response
            result = response.choices[0].message.content
            
            # Clean up response - sometimes LLM adds markdown
            cleaned_result = result.strip()
            if cleaned_result.startswith('```json'):
                cleaned_result = cleaned_result[7:]
            if cleaned_result.startswith('```'):
                cleaned_result = cleaned_result[3:]
            if cleaned_result.endswith('```'):
                cleaned_result = cleaned_result[:-3]
            cleaned_result = cleaned_result.strip()
            
            stories_data = json.loads(cleaned_result)
            
            # Handle different response formats
            if isinstance(stories_data, dict) and 'stories' in stories_data:
                stories_list = stories_data['stories']
            elif isinstance(stories_data, list):
                stories_list = stories_data
            else:
                stories_list = [stories_data]
            
            # Convert to UserStory objects with validation
            for idx, story_data in enumerate(stories_list, 1):
                # Validate story completeness
                role = story_data.get('role', '').strip()
                action = story_data.get('action', '').strip()
                benefit = story_data.get('benefit', '').strip()
                
                # Skip incomplete stories
                if not action or not benefit or not role:
                    console.print(f"[yellow]âš  Skipping incomplete story #{idx}: missing action or benefit[/yellow]")
                    continue
                
                # Skip stories that are clearly placeholders
                if action.lower() in ['to', 'action', 'todo'] or benefit.lower() in ['that', 'benefit', 'todo']:
                    console.print(f"[yellow]âš  Skipping placeholder story #{idx}[/yellow]")
                    continue
                
                story = UserStory(
                    id=len(self.user_stories) + 1,  # Use actual count for IDs
                    role=role,
                    action=action,
                    benefit=benefit,
                    feature=story_data.get('feature', 'General').strip(),
                    priority=story_data.get('priority', 'medium').lower(),
                    page_url=story_data.get('page_url', self.knowledge_base['base_url']).strip()
                )
                self.user_stories.append(story)
            
            console.print(f"[green]âœ“ Generated {len(self.user_stories)} user stories[/green]")
            
            # Validate we got at least some stories
            if len(self.user_stories) == 0:
                console.print("[red]âš  Warning: No valid stories generated. Retrying with simplified prompt...[/red]")
                # This is a fallback - could implement retry logic here if needed
                raise ValueError("No valid user stories generated - all were incomplete or invalid")
            
        except json.JSONDecodeError as e:
            console.print(f"[red]Error parsing JSON response: {str(e)}[/red]")
            console.print(f"[yellow]Raw response: {result[:500]}...[/yellow]")
            raise
        except Exception as e:
            console.print(f"[red]Error generating user stories: {str(e)}[/red]")
            raise
        
        return self.user_stories
    
    def save_user_stories(self, filepath: str = None):
        """Save user stories to JSON file"""
        if filepath is None:
            filepath = Config.USER_STORIES_FILE
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        stories_dict = [story.model_dump() for story in self.user_stories]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(stories_dict, f, indent=2)
        
        console.print(f"[green]âœ“ User stories saved to {filepath}[/green]")
    
    def display_user_stories(self):
        """Display user stories in a readable format"""
        console.print("\n[bold cyan]ðŸ“‹ Generated User Stories:[/bold cyan]\n")
        
        for story in self.user_stories:
            priority_color = {
                'high': 'red',
                'medium': 'yellow',
                'low': 'green'
            }.get(story.priority, 'white')
            
            console.print(f"[bold]{story.id}. [{priority_color}]{story.priority.upper()}[/{priority_color}] - {story.feature}[/bold]")
            console.print(f"   As a [cyan]{story.role}[/cyan],")
            console.print(f"   I want to [yellow]{story.action}[/yellow]")
            console.print(f"   So that [green]{story.benefit}[/green]")
            console.print(f"   ðŸ“ {story.page_url}\n")
    
    def run(self) -> List[UserStory]:
        """
        Execute the Architect agent workflow
        """
        console.print("[bold cyan]ðŸš€ Agent 2: The Architect - Starting[/bold cyan]")
        
        # Generate user stories
        stories = self.generate_user_stories()
        
        # Display them
        self.display_user_stories()
        
        # Save to file
        self.save_user_stories()
        
        return stories


def main():
    """Test the Architect Agent"""
    # Load knowledge base from Explorer
    with open(Path(Config.OUTPUT_DIR) / 'knowledge_base.json', 'r') as f:
        knowledge_base = json.load(f)
    
    architect = ArchitectAgent(knowledge_base)
    architect.run()


if __name__ == "__main__":
    main()