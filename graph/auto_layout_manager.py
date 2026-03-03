"""
Graphviz-based automatic graph layout manager.

Uses the Graphviz dot engine to compute optimal node positions that minimize
connection line crossings and improve graph readability. Automatically splits
nodes with connections on both sides to further reduce visual clutter.

Requires: python-graphviz package and graphviz system tools (dot command).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Tuple, Optional

from . import constants

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .gui_scene import JackGraphScene
    from .node_item import NodeItem


class AutoLayoutManager:
    """Computes optimal node layout using the Graphviz dot engine.

    The layout process:
    1. Unsplits all nodes for a clean starting state
    2. Identifies nodes that benefit from splitting (connections on both sides)
    3. Splits those nodes into input/output parts
    4. Builds a directed graph for Graphviz with actual node dimensions
    5. Runs the dot layout engine to compute positions
    6. Applies the computed positions to scene nodes
    """

    GV_DPI = 72.0
    START_OFFSET = 50.0

    def __init__(self, scene: 'JackGraphScene') -> None:
        """Initialize with a reference to the graph scene.

        Args:
            scene: The JackGraphScene containing the nodes and connections.
        """
        self.scene = scene

    def compute_and_apply(self, auto_split: bool = True) -> bool:
        """Compute and apply the auto layout.

        Args:
            auto_split: If True, automatically split nodes with connections on
                both sides for optimal layout. If False, preserve the current
                split/unsplit state of nodes.

        Returns:
            True on success, False if graphviz is unavailable or layout fails.
        """
        import traceback
        try:
            import graphviz  # noqa: F401
        except ImportError:
            logger.error(
                "python-graphviz is not installed. "
                "Install it."
            )
            return False
        except Exception as e:
            logger.error("Error importing graphviz: %s", e)
            logger.error("Traceback: %s", traceback.format_exc())
            return False

        if auto_split:
            # Clean slate — unsplit everything, then re-split optimally
            self.scene.unsplit_all_nodes(save_state=False)

            candidates = self._find_split_candidates()
            for node in candidates:
                node.split_handler.split_node(save_state=False)

        # 3. Collect all visible nodes
        visible_nodes = self._collect_visible_nodes()
        if not visible_nodes:
            logger.warning("No visible nodes for auto layout")
            return False

        # Identify connected and unconnected nodes
        connected_names = set()
        for conn_item in self.scene.connections.values():
            if not conn_item or not conn_item.source_port or not conn_item.dest_port:
                continue
            src_node = conn_item.source_port.parent_node
            dst_node = conn_item.dest_port.parent_node
            connected_names.add(src_node.client_name)
            connected_names.add(dst_node.client_name)

        connected_nodes = {k: v for k, v in visible_nodes.items() if k in connected_names}
        unconnected_nodes = {k: v for k, v in visible_nodes.items() if k not in connected_names}

        # 4-5. Build graph and compute layout for connected nodes
        positions = {}
        if connected_nodes:
            positions = self._compute_graphviz_layout(connected_nodes)
            if positions is None:
                return False

        # Compute layout for unconnected nodes
        start_y = 50.0
        start_x = 50.0
        if positions:
            # find max x and place unconnected to the right
            max_x = max(x + visible_nodes[name].boundingRect().width()
                        for name, (x, y) in positions.items())
            start_x = max_x + 100.0

        unconnected_audio = []
        unconnected_midi = []
        for name, node in unconnected_nodes.items():
            all_ports = list(node.input_ports.values()) + list(node.output_ports.values())
            has_midi = any(p.port_obj.is_midi for p in all_ports)
            has_audio = any(p.port_obj.is_audio for p in all_ports)
            if has_midi and not has_audio:
                unconnected_midi.append(node)
            else:
                unconnected_audio.append(node)

        unconnected_audio.sort(key=lambda n: n.client_name.lower())
        unconnected_midi.sort(key=lambda n: n.client_name.lower())

        current_x = start_x
        current_y = start_y

        if unconnected_audio:
            max_w = 0.0
            for node in unconnected_audio:
                positions[node.client_name] = (current_x, current_y)
                r = node.boundingRect()
                current_y += r.height() + 30.0
                max_w = max(max_w, r.width())
            
            # Reset Y and advance X for MIDI
            current_x += max_w + 100.0
            current_y = start_y

        if unconnected_midi:
            for node in unconnected_midi:
                positions[node.client_name] = (current_x, current_y)
                r = node.boundingRect()
                current_y += r.height() + 30.0

        # 6. Apply positions
        for name, (x, y) in positions.items():
            node = visible_nodes.get(name)
            if node:
                node.setPos(x, y)

        # 7. Finalize
        self.scene.connection_mgr.update_all_connection_paths()
        self.scene.save_node_states()

        return True

    def _find_split_candidates(self) -> List['NodeItem']:
        """Identify nodes that should be split for better layout.

        A node is a split candidate if it has both input and output ports
        AND has actual connections on both sides. Splitting lets the dot
        engine place input and output parts independently, reducing crossings.

        Returns:
            List of NodeItem instances that should be split.
        """
        candidates = []
        for name, node in self.scene.nodes.items():
            if node.is_split_origin or node.is_split_part:
                continue
            if not node.isVisible():
                continue
            if not node.input_ports or not node.output_ports:
                continue

            has_in_conns = any(p.connections for p in node.input_ports.values())
            has_out_conns = any(p.connections for p in node.output_ports.values())

            if has_in_conns and has_out_conns:
                candidates.append(node)

        return candidates

    def _collect_visible_nodes(self) -> Dict[str, 'NodeItem']:
        """Collect all visible, non-origin NodeItems from the scene.

        Returns:
            Dict mapping client_name to NodeItem for all visible layout nodes.
        """
        from .node_item import NodeItem

        visible: Dict[str, 'NodeItem'] = {}
        for item in self.scene.items():
            if (isinstance(item, NodeItem)
                    and item.isVisible()
                    and not item.is_split_origin):
                visible[item.client_name] = item
        return visible

    def _compute_graphviz_layout(
        self, visible_nodes: Dict[str, 'NodeItem']
    ) -> Optional[Dict[str, Tuple[float, float]]]:
        """Build a Graphviz digraph, run dot, and parse resulting positions.

        Args:
            visible_nodes: Dict of client_name -> NodeItem for all visible nodes.

        Returns:
            Dict of client_name -> (x, y) pixel positions, or None on failure.
        """
        import graphviz as gv
        import os

        logger.debug("Graphviz DOT path: %s", os.environ.get('GRAPHVIZ_DOT', 'not set'))
        logger.debug("LD_LIBRARY_PATH: %s", os.environ.get('LD_LIBRARY_PATH', 'not set'))

        dot = gv.Digraph(engine='dot', format='plain')
        dot.attr(
            rankdir='LR',
            nodesep='0.5',
            ranksep='1.2',
            splines='false',
        )

        # Create stable ID mapping (avoids special-char issues in DOT names)
        id_to_name: Dict[str, str] = {}
        name_to_id: Dict[str, str] = {}

        for i, (name, node) in enumerate(visible_nodes.items()):
            gv_id = f"n{i}"
            id_to_name[gv_id] = name
            name_to_id[name] = gv_id

            rect = node.boundingRect()
            dot.node(
                gv_id,
                shape='box',
                fixedsize='true',
                width=str(rect.width() / self.GV_DPI),
                height=str(rect.height() / self.GV_DPI),
            )

        # Aggregate edges by source/dest node pair, weighted by connection count
        edge_weights: Dict[Tuple[str, str], int] = {}
        for conn_item in self.scene.connections.values():
            if not conn_item or not conn_item.source_port or not conn_item.dest_port:
                continue

            src_node = conn_item.source_port.parent_node
            dst_node = conn_item.dest_port.parent_node
            src_id = name_to_id.get(src_node.client_name)
            dst_id = name_to_id.get(dst_node.client_name)

            if src_id and dst_id and src_id != dst_id:
                key = (src_id, dst_id)
                edge_weights[key] = edge_weights.get(key, 0) + 1

        for (src, dst), weight in edge_weights.items():
            dot.edge(src, dst, weight=str(weight))

        # Run layout
        try:
            raw = dot.pipe(format='plain').decode('utf-8')
        except Exception as e:
            logger.error("Graphviz dot layout failed: %s", e)
            # Log more details for debugging
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
            return None

        return self._parse_plain_output(raw, id_to_name)

    def _parse_plain_output(
        self, raw: str, id_to_name: Dict[str, str]
    ) -> Optional[Dict[str, Tuple[float, float]]]:
        """Parse the Graphviz 'plain' output format and return node positions.

        The plain format outputs coordinates in inches with Y increasing upward.
        This method converts to Qt scene pixels (Y increasing downward).

        Args:
            raw: Raw text output from ``dot -Tplain``.
            id_to_name: Mapping from graphviz node IDs to client names.

        Returns:
            Dict of client_name -> (x, y) in scene pixels, or None if empty.
        """
        positions: Dict[str, Tuple[float, float]] = {}
        graph_height = 0.0

        for line in raw.strip().split('\n'):
            tokens = line.split()
            if not tokens:
                continue

            if tokens[0] == 'graph':
                graph_height = float(tokens[3])
            elif tokens[0] == 'node':
                gv_id = tokens[1].strip('"')
                cx = float(tokens[2])
                cy = float(tokens[3])
                w = float(tokens[4])
                h = float(tokens[5])

                name = id_to_name.get(gv_id)
                if name:
                    # Convert center coords (inches, Y-up) to top-left (pixels, Y-down)
                    px = (cx - w / 2) * self.GV_DPI + self.START_OFFSET
                    py = (graph_height - cy - h / 2) * self.GV_DPI + self.START_OFFSET
                    positions[name] = (px, py)

        return positions if positions else None
