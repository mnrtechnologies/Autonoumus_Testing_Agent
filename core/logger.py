
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict
class CrawlerLogger:
    """
    Handles all logging operations:
    - Action logs (every click, navigation, detection)
    - Plan versioning (saves every update to plans)
    - Error logs
    - Statistics tracking
    """
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
        
        # Create timestamped session directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = self.output_dir / f"session_{timestamp}"
        self.session_dir.mkdir(exist_ok=True)
        
        # Initialize log files
        self.main_log_file = self.session_dir / "crawler_log.txt"
        self.action_log_file = self.session_dir / "actions_log.jsonl"  # JSON Lines format
        self.error_log_file = self.session_dir / "errors_log.txt"
        
        # Plan tracking
        self.plans_dir = self.session_dir / "plans"
        self.plans_dir.mkdir(exist_ok=True)
        self.main_action_plan_versions = []
        self.assumption_plan_saved = False
        
        # Initialize action counter
        self.action_counter = 0
        
        # Set up Python logging
        self._setup_python_logging()
        
        self.log_info("=" * 80)
        self.log_info(f"CRAWLER SESSION STARTED: {timestamp}")
        self.log_info("=" * 80)
    
    def _setup_python_logging(self):
        """Configure Python's logging module for error tracking"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.error_log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def log_info(self, message: str):
        """Log informational message to main log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {message}\n"
        with open(self.main_log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def log_action(self, action_type: str, details: Dict):
        """Log structured action data in JSON Lines format"""
        self.action_counter += 1
        action_entry = {
            "action_id": self.action_counter,
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "details": details
        }
        
        with open(self.action_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(action_entry, ensure_ascii=False) + '\n')
        
        # Also log to main log for easy reading
        self.log_info(f"ACTION #{self.action_counter}: {action_type} - {json.dumps(details, ensure_ascii=False)}")
    
    def log_error(self, error_type: str, error_message: str, context: Dict = None):
        """Log error with context"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        error_entry = f"\n[{timestamp}] ERROR: {error_type}\n"
        error_entry += f"Message: {error_message}\n"
        if context:
            error_entry += f"Context: {json.dumps(context, indent=2, ensure_ascii=False)}\n"
        error_entry += "-" * 80 + "\n"
        
        with open(self.error_log_file, 'a', encoding='utf-8') as f:
            f.write(error_entry)
        
        self.logger.error(f"{error_type}: {error_message}")
    
    def save_assumption_plan(self, plan: List[Dict]):
        """Save assumption plan (only once)"""
        if not self.assumption_plan_saved:
            plan_file = self.plans_dir / "assumption_plan.json"
            with open(plan_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "plan_type": "assumption_discovery",
                    "created_at": datetime.now().isoformat(),
                    "total_steps": len(plan),
                    "steps": plan
                }, f, indent=2, ensure_ascii=False)
            
            self.log_info(f"Saved assumption plan: {len(plan)} steps")
            self.assumption_plan_saved = True
    
    def save_main_action_plan_version(self, plan: List[Dict], reason: str = "initial"):
        """Save a new version of the main action plan"""
        version_num = len(self.main_action_plan_versions) + 1
        self.main_action_plan_versions.append({
            "version": version_num,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "step_count": len(plan)
        })
        
        # Save this version
        version_file = self.plans_dir / f"main_action_plan_v{version_num}.json"
        with open(version_file, 'w', encoding='utf-8') as f:
            json.dump({
                "version": version_num,
                "reason": reason,
                "created_at": datetime.now().isoformat(),
                "total_steps": len(plan),
                "steps": plan
            }, f, indent=2, ensure_ascii=False)
        
        self.log_info(f"Saved main action plan version {version_num}: {reason} ({len(plan)} steps)")
        
        # Also save version history
        history_file = self.plans_dir / "plan_version_history.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump({
                "total_versions": len(self.main_action_plan_versions),
                "versions": self.main_action_plan_versions
            }, f, indent=2, ensure_ascii=False)
    
    def log_vision_analysis(self, url: str, analysis: Dict):
        """Log GPT-4 Vision analysis results"""
        self.log_action("vision_analysis", {
            "url": url,
            "page_type": analysis.get("page_type"),
            "containers_found": len(analysis.get("containers", [])),
            "features_found": len(analysis.get("features", [])),
            "analysis": analysis
        })
    
    def log_container_expansion(self, container: Dict, success: bool, changes: List[Dict] = None):
        """Log container expansion attempt"""
        self.log_action("container_expansion", {
            "container_id": container.get("semantic_id"),
            "container_text": container.get("text"),
            "success": success,
            "dom_changes": len(changes) if changes else 0,
            "change_details": changes[:5] if changes else []  # First 5 changes
        })
    
    def log_feature_test(self, feature: Dict, success: bool, navigation_occurred: bool = False, new_url: str = None):
        """Log feature testing attempt"""
        self.log_action("feature_test", {
            "feature_id": feature.get("semantic_id"),
            "feature_text": feature.get("text"),
            "feature_type": feature.get("type"),
            "success": success,
            "navigation_occurred": navigation_occurred,
            "new_url": new_url
        })
    
    def log_path_resolution(self, feature_id: str, feature_text: str, path_steps: int, restoration_needed: int, success: bool, method: str = "traditional"):
        """Log path resolution before feature click"""
        self.log_action("path_resolution", {
            "feature_id": feature_id,
            "feature_text": feature_text,
            "total_path_steps": path_steps,
            "restoration_steps_needed": restoration_needed,
            "success": success,
            "method": method 
        })
    
    def log_state_change(self, from_url: str, to_url: str, breadcrumb: str):
        """Log navigation state change"""
        self.log_action("state_change", {
            "from_url": from_url,
            "to_url": to_url,
            "breadcrumb": breadcrumb
        })
    
    def save_final_summary(self, stats: Dict, kg_summary: Dict):
        """Save final exploration summary"""
        summary_file = self.session_dir / "exploration_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump({
                "session_ended": datetime.now().isoformat(),
                "statistics": stats,
                "knowledge_graph_summary": kg_summary,
                "total_actions": self.action_counter,
                "plan_versions": len(self.main_action_plan_versions)
            }, f, indent=2, ensure_ascii=False)
        
        self.log_info("=" * 80)
        self.log_info("SESSION COMPLETED")
        self.log_info(f"Total actions logged: {self.action_counter}")
        self.log_info(f"Plan versions saved: {len(self.main_action_plan_versions)}")
        self.log_info("=" * 80)
