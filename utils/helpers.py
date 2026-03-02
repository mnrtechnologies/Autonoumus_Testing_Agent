"""
Helper utilities for the Robo-Tester
"""
import base64
from pathlib import Path
from datetime import datetime


def encode_image_to_base64(image_path: str) -> str:
    """
    Convert an image file to Base64 string for LLM vision input.
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Base64 encoded string of the image
    """
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def save_screenshot(screenshot_bytes: bytes, step_num: int, output_dir: str = "semantic_test_output") -> str:
    """
    Save a screenshot to disk with timestamped filename.
    
    Args:
        screenshot_bytes: Raw screenshot bytes
        step_num: Current step number
        output_dir: Directory to save screenshots
        
    Returns:
        Path to saved screenshot
    """
    Path(output_dir).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"step_{step_num:03d}_{timestamp}.png"
    filepath = Path(output_dir) / filename
    
    with open(filepath, "wb") as f:
        f.write(screenshot_bytes)
    
    return str(filepath)


def load_js_file(filename: str) -> str:
    """
    Load JavaScript code from the utils directory.
    
    Args:
        filename: Name of the JS file (e.g., 'tagger.js')
        
    Returns:
        JavaScript code as string
    """
    js_path = Path(__file__).parent / filename
    with open(js_path, 'r') as f:
        return f.read()


def format_action_history(history: list) -> str:
    """
    Format the action history into a readable string for the LLM.
    
    Args:
        history: List of action descriptions
        
    Returns:
        Formatted string of action history
    """
    if not history:
        return "No actions taken yet."
    
    # Limit to last 10 actions to keep context manageable
    recent_history = history[-10:] if len(history) > 10 else history
    
    if len(history) > 10:
        formatted = [f"... ({len(history) - 10} earlier actions omitted) ..."]
    else:
        formatted = []
    
    formatted.extend(recent_history)
    
    return "\n".join(formatted)