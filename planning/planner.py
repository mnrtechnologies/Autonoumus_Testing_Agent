from typing import List, Dict
from rich.console import Console
from core.logger import CrawlerLogger

console = Console()

class TwoTierPlanner:
    def __init__(self, logger: CrawlerLogger):
        self.assumption_plan = []
        self.main_action_plan = []
        self.logger = logger

    def create_assumption_plan(self, containers: List[Dict], vision_strategy: Dict) -> List[Dict]:
        console.print("[cyan]📋 TIER 1 PLANNER: Creating Assumption Plan (Discovery)...[/cyan]")
        self.logger.log_info("Creating assumption plan")
        
        plan = []
        step_id = 1

        containers_sorted = sorted(containers, key=lambda x: x.get('discovery_priority', 5), reverse=True)
        recommended_order = vision_strategy.get('recommended_order', [])

        if recommended_order:
            ordered = []
            for rec_name in recommended_order:
                for c in containers_sorted:
                    if rec_name.lower() in c['text'].lower() and c not in ordered:
                        ordered.append(c)
                        break
            for c in containers_sorted:
                if c not in ordered:
                    ordered.append(c)
            containers_sorted = ordered

        for container in containers_sorted:
            plan.append({
                'step_id': step_id,
                'tier': 'assumption',
                'action': 'discover',
                'hypothesis': f"{container['text']} contains hidden features",
                'container': container,
                'expected_children': container.get('expected_children', []),
                'priority': container.get('discovery_priority', 5),
                'reason': f"Expand {container['text']} to discover sub-items"
            })
            step_id += 1

        self.assumption_plan = plan
        console.print(f"[green]   ✅ Assumption Plan: {len(plan)} steps[/green]")
        
        # Save assumption plan
        self.logger.save_assumption_plan(plan)
        
        return plan

    def create_main_action_plan(self, features: List[Dict]) -> List[Dict]:
        console.print("[cyan]📋 TIER 2 PLANNER: Creating Main Action Plan (Testing)...[/cyan]")
        self.logger.log_info("Creating main action plan")
        
        plan = []
        step_id = 1

        for feature in sorted(features, key=lambda x: x.get('test_priority', 5), reverse=True):
            plan.append({
                'step_id': step_id,
                'tier': 'main_action',
                'action': 'test',
                'feature': feature,
                'feature_id': feature['semantic_id'],
                'test_type': self._determine_test_type(feature),
                'priority': feature.get('test_priority', 5),
                'reason': f"Test {feature['text']} functionality"
            })
            step_id += 1

        self.main_action_plan = plan
        console.print(f"[green]   ✅ Main Action Plan: {len(plan)} steps[/green]")
        
        # Save initial version of main action plan
        self.logger.save_main_action_plan_version(plan, "initial_creation")
        
        return plan

    def add_discovered_features_to_main_plan(self, new_features: List[Dict]):
        console.print(f"[cyan]➕ Adding {len(new_features)} discovered features to Main Action Plan...[/cyan]")
        self.logger.log_info(f"Adding {len(new_features)} discovered features to main action plan")
        
        next_id = len(self.main_action_plan) + 1

        for feature in new_features:
            self.main_action_plan.append({
                'step_id': next_id,
                'tier': 'main_action',
                'action': 'test',
                'feature': feature,
                'feature_id': feature['semantic_id'],
                'test_type': self._determine_test_type(feature),
                'priority': feature.get('test_priority', 5),
                'reason': f"Test {feature['text']} (discovered during exploration)",
                'discovered': True
            })
            next_id += 1

        self.main_action_plan.sort(key=lambda x: x.get('priority', 5), reverse=True)
        for idx, action in enumerate(self.main_action_plan, 1):
            action['step_id'] = idx

        console.print(f"[green]   ✅ Main Action Plan now has {len(self.main_action_plan)} steps[/green]")
        
        # Save updated version
        self.logger.save_main_action_plan_version(
            self.main_action_plan, 
            f"added_{len(new_features)}_discovered_features"
        )

    def _determine_test_type(self, feature: Dict) -> str:
        t = feature.get('type', '').lower()
        if 'button' in t:    return 'functional_test'
        if 'link' in t:      return 'navigation_test'
        if 'form' in t or 'input' in t: return 'input_validation'
        return 'general_test'
