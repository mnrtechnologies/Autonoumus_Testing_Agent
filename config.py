"""
Configuration settings for AI Web Agent
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Central configuration class"""
    
    # API Keys
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    
    # Model settings
    MODEL = "gpt-4o-mini"
    
    # Authentication settings
    AUTH_USERNAME = os.getenv('AUTH_USERNAME', 'teacher@mnrtechnologies.com')
    AUTH_PASSWORD = os.getenv('AUTH_PASSWORD', 'Mnrtech@123456')
    STORAGE_STATE_FILE = "semantic_test_output/storage_state.json"
    
    # Crawler settings
    MAX_PAGES_TO_CRAWL = 10
    CRAWL_TIMEOUT = 30000  # milliseconds
    
    # Browser settings (for Operator agent)
    BROWSER_HEADLESS = True
    VIEWPORT_WIDTH = 1280
    VIEWPORT_HEIGHT = 720
    
    # Output directories
    OUTPUT_DIR = Path("semantic_test_output")
    MARKDOWN_DIR = OUTPUT_DIR / "markdown"
    USER_STORIES_FILE = OUTPUT_DIR / "user_stories.json"
    EXECUTION_LOG = OUTPUT_DIR / "execution_log.json"
    
    @classmethod
    def validate(cls):
        """Validate that required configuration is present"""
        if not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")