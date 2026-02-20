import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from rich.console import Console
from .logger import CrawlerLogger

console = Console()

class KnowledgeGraph:
    def __init__(self, logger: CrawlerLogger):
        self.nodes: Dict[str, Dict] = {}
        self.edges: List[Dict] = []
        self.paths: Dict[str, List[Dict]] = {}
        self.graph_file = Path('output') / 'knowledge_graph.json'
        self.logger = logger

    def add_node(
        self,
        semantic_id: str,
        text: str,
        node_type: str,
        location: str,
        anchor_url: str,
        element_type: str,
        confidence: str = 'vision_only',
        target_url: Optional[str] = None  # NEW: Optional deep link URL
    ):
        if semantic_id not in self.nodes:
            self.nodes[semantic_id] = {
                'semantic_id': semantic_id,
                'text': text,
                'node_type': node_type,
                'location': location,
                'anchor_url': anchor_url,
                'element_type': element_type,
                'confidence': confidence,
                'target_url': target_url,  # NEW: Store the deep link
                'discovered_at': datetime.now().isoformat()
            }
            
            # Enhanced logging
            log_msg = f"📍 KG Node added: {semantic_id} ({confidence})"
            if target_url:
                log_msg += f" → {target_url}"
                console.print(f"[dim]   {log_msg}[/dim]")
            else:
                console.print(f"[dim]   {log_msg}[/dim]")
            
            self.logger.log_action("kg_node_added", {
                "semantic_id": semantic_id,
                "text": text,
                "node_type": node_type,
                "confidence": confidence,
                "has_target_url": bool(target_url),
                "target_url": target_url
            })

    def upgrade_confidence(self, semantic_id: str):
        if semantic_id in self.nodes:
            self.nodes[semantic_id]['confidence'] = 'dom_confirmed'
            self.logger.log_action("kg_confidence_upgraded", {
                "semantic_id": semantic_id,
                "new_confidence": "dom_confirmed"
            })

    def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        anchor_url: str,
        confidence: str = 'vision_only',
        target_url: Optional[str] = None  # NEW: Optional - can track navigation flows
    ):
        for existing in self.edges:
            if existing['from_id'] == from_id and existing['to_id'] == to_id:
                return

        edge = {
            'from_id': from_id,
            'to_id': to_id,
            'edge_type': edge_type,
            'anchor_url': anchor_url,
            'confidence': confidence,
            'target_url': target_url  # NEW: Optional navigation target
        }
        self.edges.append(edge)
        
        edge_display = f"{from_id} --[{edge_type}]--> {to_id}"
        if target_url:
            edge_display += f" → {target_url}"
        console.print(f"[dim]   🔗 KG Edge: {edge_display}[/dim]")
        
        self.logger.log_action("kg_edge_added", {
            "from_id": from_id,
            "to_id": to_id,
            "edge_type": edge_type,
            "confidence": confidence,
            "has_target_url": bool(target_url)
        })

    def build_path_for_feature(
        self,
        feature_id: str,
        parent_container_id: Optional[str],
    ):
        if feature_id in self.paths:
            console.print(f"[dim]   ⏭️  Path already exists for {feature_id}[/dim]")
            return
        
        node = self.nodes.get(feature_id)
        if not node:
            console.print(f"[red]   ❌ Cannot build path: node {feature_id} not found[/red]")
            self.logger.log_error("path_build_failed", f"Node {feature_id} not found", {"feature_id": feature_id})
            return
        
        anchor_url = node.get('anchor_url')
        if not anchor_url:
            console.print(f"[red]   ❌ Node {feature_id} missing anchor_url[/red]")
            self.logger.log_error("path_build_failed", f"Node {feature_id} missing anchor_url", {"feature_id": feature_id})
            return
        
        steps = []

        # NEW: If this node has a target_url, we can use direct navigation!
        # But we still build the traditional path as a fallback
        steps.append({
            'step_type': 'ensure_url',
            'target_url': anchor_url,
            'description': f'Ensure browser is on {anchor_url}'
        })
        
        if parent_container_id:
            parent_path = self.paths.get(parent_container_id, [])
            for step in parent_path:
                if step['step_type'] != 'ensure_url':
                    steps.append(step)

            parent_node = self.nodes.get(parent_container_id, {})
            steps.append({
                'step_type': 'expand_container',
                'container_id': parent_container_id,
                'container_text': parent_node.get('text', ''),
                'container_location': parent_node.get('location', ''),
                'anchor_url': anchor_url,
                'description': f"Expand '{parent_node.get('text', '')}'"
            })

        self.paths[feature_id] = steps
        
        # Enhanced logging
        path_info = f"🗺️  Path created for {feature_id}: {len(steps)} steps"
        if node.get('target_url'):
            path_info += f" (⚡ DEEP LINK AVAILABLE: {node['target_url']})"
        console.print(f"[dim]   {path_info}[/dim]")
        
        self.logger.log_action("kg_path_created", {
            "feature_id": feature_id,
            "path_length": len(steps),
            "has_parent": parent_container_id is not None,
            "has_deep_link": bool(node.get('target_url'))
        })

    def get_path(self, feature_id: str) -> List[Dict]:
        return self.paths.get(feature_id, [])

    def get_parent_container_id(self, feature_id: str) -> Optional[str]:
        for edge in self.edges:
            if edge['to_id'] == feature_id and edge['edge_type'] == 'dom_action':
                return edge['from_id']
        return None
    
    def get_target_url(self, feature_id: str) -> Optional[str]:
        """
        NEW METHOD: Retrieve the direct deep link URL for a feature
        Returns None if no target_url exists (fallback to traditional clicking)
        """
        node = self.nodes.get(feature_id)
        if not node:
            return None
        return node.get('target_url')

    def save(self):
        self.graph_file.parent.mkdir(exist_ok=True)
        data = {
            'nodes': self.nodes,
            'edges': self.edges,
            'paths': self.paths,
            'saved_at': datetime.now().isoformat(),
            'stats': {
                'total_nodes': len(self.nodes),
                'nodes_with_deep_links': sum(1 for n in self.nodes.values() if n.get('target_url')),
                'total_edges': len(self.edges),
                'total_paths': len(self.paths)
            }
        }
        with open(self.graph_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        deep_link_count = data['stats']['nodes_with_deep_links']
        self.logger.log_info(
            f"Knowledge graph saved: {len(self.nodes)} nodes "
            f"({deep_link_count} with deep links), {len(self.edges)} edges"
        )

    def load(self):
        if self.graph_file.exists():
            with open(self.graph_file, 'r') as f:
                data = json.load(f)
            self.nodes = data.get('nodes', {})
            self.edges = data.get('edges', [])
            self.paths = data.get('paths', {})
            
            deep_link_count = sum(1 for n in self.nodes.values() if n.get('target_url'))
            console.print(
                f"[green]   ✅ Knowledge graph loaded: {len(self.nodes)} nodes "
                f"({deep_link_count} with deep links), {len(self.edges)} edges[/green]"
            )
            self.logger.log_info(
                f"Knowledge graph loaded: {len(self.nodes)} nodes "
                f"({deep_link_count} with deep links), {len(self.edges)} edges"
            )