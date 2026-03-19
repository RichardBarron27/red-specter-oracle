"""ORACLE Component Graph Engine — networkx-based graph ported from IDRIS."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from oracle.db.database import Database

logger = logging.getLogger("oracle.graph.engine")

# Component type colours for visualisation
TYPE_COLOURS = {
    "mcu": "#FF6B35", "soc": "#FF6B35", "fpga": "#FF6B35",
    "memory": "#4ECDC4", "sensor": "#45B7D1", "connector": "#96CEB4",
    "ic": "#FFEAA7", "passive": "#DFE6E9", "power": "#E17055",
    "interface": "#00B894", "protocol": "#6C5CE7", "bus": "#6C5CE7",
    "firmware": "#A29BFE", "os": "#FD79A8", "driver": "#FDCB6E",
    "software": "#E84393", "library": "#E84393",
    "other": "#B2BEC3",
}

VALID_RELATIONSHIP_TYPES = {
    "CONNECTS_TO", "DEPENDS_ON", "CONTROLS", "COMMUNICATES_VIA",
    "CONTAINS", "RUNS_ON",
}

LAYER_ORDER = ["hardware", "firmware", "os", "application", "protocol"]


@dataclass
class BlastRadiusResult:
    """Blast radius analysis for a component."""
    component_id: str = ""
    component_name: str = ""
    directly_connected: int = 0
    transitively_reachable: int = 0
    affected_components: list[dict[str, Any]] = field(default_factory=list)
    trust_chain_depth: int = 0
    risk_level: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "component_name": self.component_name,
            "directly_connected": self.directly_connected,
            "transitively_reachable": self.transitively_reachable,
            "affected_components": self.affected_components,
            "trust_chain_depth": self.trust_chain_depth,
            "risk_level": self.risk_level,
        }


class ComponentGraph:
    """Component knowledge graph — ported from IDRIS IdentityGraph."""

    def __init__(self, db: Database):
        self.db = db
        self._graph = nx.DiGraph()
        self._components: dict[str, dict[str, Any]] = {}

    def build_from_session(self, session_id: str) -> dict[str, Any]:
        """Build the graph from components and relationships stored in SQLite."""
        self._graph = nx.DiGraph()
        self._components.clear()

        components = self.db.list_components(session_id)
        relationships = self.db.list_relationships(session_id)

        # Add component nodes
        for comp in components:
            cid = comp["component_id"]
            self._components[cid] = comp
            self._graph.add_node(
                cid,
                name=comp["name"],
                component_type=comp["component_type"],
                part_number=comp.get("part_number", ""),
                manufacturer=comp.get("manufacturer", ""),
                version=comp.get("version", ""),
                layer=comp.get("layer", "hardware"),
                confidence=comp.get("confidence", 0.5),
                source_doc=comp.get("source_doc", ""),
                colour=TYPE_COLOURS.get(comp["component_type"], TYPE_COLOURS["other"]),
            )

        # Add relationship edges
        for rel in relationships:
            src = rel["source_component"]
            tgt = rel["target_component"]
            if src in self._graph and tgt in self._graph:
                self._graph.add_edge(
                    src, tgt,
                    relationship_type=rel["relationship_type"],
                    evidence=rel.get("evidence", ""),
                    source_doc=rel.get("source_doc", ""),
                    confidence=rel.get("confidence", 0.5),
                )

        stats = {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "components_by_type": self._count_by_type(),
            "components_by_layer": self._count_by_layer(),
        }

        # Save snapshot
        self.db.save_graph_snapshot(session_id, json.dumps(self.to_dict()))

        logger.info(f"Built graph for session {session_id}: "
                     f"{stats['nodes']} nodes, {stats['edges']} edges")
        return stats

    def calculate_blast_radius(self, component_id: str) -> BlastRadiusResult:
        """Calculate blast radius if a component is compromised."""
        result = BlastRadiusResult(component_id=component_id)

        comp = self._components.get(component_id)
        if comp:
            result.component_name = comp["name"]

        if component_id not in self._graph:
            return result

        # Direct connections
        direct = set(self._graph.successors(component_id)) | set(self._graph.predecessors(component_id))
        result.directly_connected = len(direct)

        # Transitive reachability (both directions for hardware)
        reachable = set()
        try:
            reachable = nx.descendants(self._graph, component_id)
        except nx.NetworkXError:
            pass
        # Also check ancestors (upstream impact)
        try:
            reachable |= nx.ancestors(self._graph, component_id)
        except nx.NetworkXError:
            pass

        result.transitively_reachable = len(reachable)

        # Affected components detail
        for node_id in reachable:
            comp_data = self._components.get(node_id, {})
            result.affected_components.append({
                "component_id": node_id,
                "name": comp_data.get("name", "unknown"),
                "type": comp_data.get("component_type", "unknown"),
                "layer": comp_data.get("layer", "unknown"),
            })

        # Trust chain depth
        try:
            paths = nx.single_source_shortest_path_length(self._graph, component_id)
            result.trust_chain_depth = max(paths.values()) if paths else 0
        except nx.NetworkXError:
            pass

        # Risk level based on blast radius
        total = result.transitively_reachable
        if total >= 10:
            result.risk_level = "critical"
        elif total >= 5:
            result.risk_level = "high"
        elif total >= 3:
            result.risk_level = "medium"
        elif total >= 1:
            result.risk_level = "low"

        return result

    def get_critical_nodes(self, top_n: int = 10) -> list[dict[str, Any]]:
        """Find most critical components by centrality."""
        if self._graph.number_of_nodes() == 0:
            return []

        centrality = nx.degree_centrality(self._graph)
        sorted_nodes = sorted(centrality.items(), key=lambda x: x[1], reverse=True)

        results = []
        for node_id, score in sorted_nodes[:top_n]:
            comp = self._components.get(node_id, {})
            results.append({
                "component_id": node_id,
                "name": comp.get("name", "unknown"),
                "component_type": comp.get("component_type", "unknown"),
                "layer": comp.get("layer", "unknown"),
                "centrality_score": round(score, 4),
                "degree": self._graph.degree(node_id),
            })

        return results

    def get_trust_chain(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Build the full trust chain from hardware through software layers."""
        layers: dict[str, list[dict[str, Any]]] = {l: [] for l in LAYER_ORDER}

        for node_id, comp in self._components.items():
            layer = comp.get("layer", "hardware")
            if layer in layers:
                layers[layer].append({
                    "component_id": node_id,
                    "name": comp["name"],
                    "component_type": comp["component_type"],
                    "part_number": comp.get("part_number"),
                    "confidence": comp.get("confidence", 0.5),
                    "source_doc": comp.get("source_doc"),
                })

        # Find cross-layer edges
        cross_layer_edges = []
        for src, tgt, data in self._graph.edges(data=True):
            src_layer = self._components.get(src, {}).get("layer", "hardware")
            tgt_layer = self._components.get(tgt, {}).get("layer", "hardware")
            if src_layer != tgt_layer:
                cross_layer_edges.append({
                    "source": self._components.get(src, {}).get("name", src),
                    "target": self._components.get(tgt, {}).get("name", tgt),
                    "source_layer": src_layer,
                    "target_layer": tgt_layer,
                    "relationship": data.get("relationship_type", "unknown"),
                    "evidence": data.get("evidence", ""),
                    "verified": data.get("confidence", 0) > 0.6,
                })

        # Flag unverified links
        unverified = [e for e in cross_layer_edges if not e["verified"]]

        return {
            "layers": {k: v for k, v in layers.items() if v},
            "cross_layer_edges": cross_layer_edges,
            "unverified_links": unverified,
            "total_components": self._graph.number_of_nodes(),
            "total_cross_layer": len(cross_layer_edges),
        }

    def get_version_conflicts(self) -> list[dict[str, Any]]:
        """Find components with conflicting version information."""
        conflicts = []
        name_versions: dict[str, list[dict[str, Any]]] = {}

        for cid, comp in self._components.items():
            name = comp["name"]
            if name not in name_versions:
                name_versions[name] = []
            name_versions[name].append({
                "component_id": cid,
                "version": comp.get("version"),
                "source_doc": comp.get("source_doc"),
            })

        for name, versions in name_versions.items():
            unique_versions = set(v["version"] for v in versions if v["version"])
            if len(unique_versions) > 1:
                conflicts.append({
                    "component_name": name,
                    "versions_found": list(unique_versions),
                    "sources": versions,
                })

        return conflicts

    def to_dict(self) -> dict[str, Any]:
        """Export graph for serialisation and visualisation."""
        nodes = []
        for node_id in self._graph.nodes():
            data = dict(self._graph.nodes[node_id])
            data["id"] = node_id
            nodes.append(data)

        edges = []
        for src, tgt, data in self._graph.edges(data=True):
            edge = dict(data)
            edge["source"] = src
            edge["target"] = tgt
            edges.append(edge)

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "by_type": self._count_by_type(),
                "by_layer": self._count_by_layer(),
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def _count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for comp in self._components.values():
            t = comp.get("component_type", "other")
            counts[t] = counts.get(t, 0) + 1
        return counts

    def _count_by_layer(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for comp in self._components.values():
            layer = comp.get("layer", "hardware")
            counts[layer] = counts.get(layer, 0) + 1
        return counts

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()
