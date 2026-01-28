"""
SelectorMemory - Per-Domain Memory for Working Repair Selectors
Stores successfully repaired selectors to avoid re-diagnosing the same issues
"""
import json
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlparse


class SelectorMemory:
    """
    Manages a persistent memory of working repair selectors.
    Organized by domain to keep selectors relevant.
    
    Memory Structure:
    {
        "example.com": {
            "Class 10": {
                "selector": "//button[normalize-space()='Class 10']",
                "tag": "button",
                "success_count": 5,
                "last_used": "2026-01-28T10:30:00"
            }
        }
    }
    """
    
    def __init__(self, memory_file: str = "selector_memory.json"):
        """
        Initialize the selector memory system.
        
        Args:
            memory_file: Path to the JSON file storing the memory
        """
        self.memory_file = Path(memory_file)
        self.memory: Dict = self._load_memory()
    
    def _load_memory(self) -> Dict:
        """Load memory from disk or create new if doesn't exist."""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r') as f:
                    memory = json.load(f)
                    print(f"📚 Loaded selector memory with {len(memory)} domains")
                    return memory
            except Exception as e:
                print(f"⚠️  Failed to load memory file: {e}")
                return {}
        else:
            print("📚 Creating new selector memory")
            return {}
    
    def _save_memory(self):
        """Save memory to disk."""
        try:
            with open(self.memory_file, 'w') as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            print(f"⚠️  Failed to save memory file: {e}")
    
    def _extract_domain(self, url: str) -> str:
        """
        Extract domain from URL for memory key.
        
        Args:
            url: Full URL
            
        Returns:
            Domain string (e.g., "example.com")
        """
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        # Remove www. prefix for consistency
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    
    def get_repair_selector(self, url: str, element_text: str) -> Optional[str]:
        """
        Look up a working repair selector for a given element text on a domain.
        
        Args:
            url: Current page URL
            element_text: The exact text content of the element
            
        Returns:
            Repair selector string or None if not found
        """
        domain = self._extract_domain(url)
        
        if domain not in self.memory:
            return None
        
        domain_memory = self.memory[domain]
        
        if element_text not in domain_memory:
            return None
        
        entry = domain_memory[element_text]
        selector = entry.get('selector')
        
        if selector:
            print(f"   💾 Found repair selector in memory for '{element_text}': {selector}")
            
            # Update usage stats
            entry['success_count'] = entry.get('success_count', 0) + 1
            from datetime import datetime
            entry['last_used'] = datetime.now().isoformat()
            self._save_memory()
        
        return selector
    
    def save_repair_selector(self, 
                            url: str, 
                            element_text: str,
                            tag: str,
                            repair_selector: str):
        """
        Save a working repair selector to memory.
        
        Args:
            url: Current page URL
            element_text: The exact text content of the element
            tag: HTML tag name
            repair_selector: The working XPath selector
        """
        domain = self._extract_domain(url)
        
        # Initialize domain if needed
        if domain not in self.memory:
            self.memory[domain] = {}
        
        # Store the repair selector
        from datetime import datetime
        self.memory[domain][element_text] = {
            "selector": repair_selector,
            "tag": tag,
            "success_count": 1,
            "last_used": datetime.now().isoformat()
        }
        
        print(f"   💾 Saved repair selector to memory: '{element_text}' → {repair_selector}")
        
        self._save_memory()
    
    def clear_domain(self, url: str):
        """
        Clear all memory for a specific domain.
        
        Args:
            url: URL of the domain to clear
        """
        domain = self._extract_domain(url)
        if domain in self.memory:
            del self.memory[domain]
            self._save_memory()
            print(f"   🗑️  Cleared memory for domain: {domain}")
    
    def get_stats(self) -> Dict:
        """
        Get statistics about the memory.
        
        Returns:
            Dictionary with memory statistics
        """
        total_domains = len(self.memory)
        total_selectors = sum(len(entries) for entries in self.memory.values())
        
        return {
            "total_domains": total_domains,
            "total_selectors": total_selectors,
            "domains": list(self.memory.keys())
        }