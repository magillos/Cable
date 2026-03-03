import logging
from typing import Any, List, Dict
from collections import defaultdict
from .base import LayoutStrategy

logger = logging.getLogger(__name__)

class IOLayoutStrategy(LayoutStrategy):
    """
    Layout strategy that organizes the graph nodes into columns, 
    separating Audio/Mixed and MIDI nodes.
    """
    
    def apply(self, layouter: 'GraphLayouter', scene: 'JackGraphScene', **kwargs: Any) -> bool:
        if not scene.nodes:
            return True

        # 1. Split nodes with both inputs and outputs
        nodes_to_process = list(scene.nodes.values())
        for node in nodes_to_process:
            if node.isVisible() and not node.is_split_origin:
                if node.input_ports and node.output_ports:
                    node.split_handler.split_node(save_state=False)

        # 2. Collect all visible NodeItems for layout
        from graph.node_item import NodeItem
        layout_nodes = [item for item in scene.items() if isinstance(item, NodeItem) and item.isVisible() and not item.is_split_origin]

        # 3. Categorize nodes
        # Groups:
        # 0: Connected Audio Outputs
        # 1: Connected Audio Inputs
        # 2: Unconnected Audio Outputs
        # 3: Unconnected Audio Inputs
        # 4: Connected MIDI Outputs
        # 5: Connected MIDI Inputs
        # 6: Unconnected MIDI Outputs
        # 7: Unconnected MIDI Inputs
        
        groups: List[List['NodeItem']] = [[] for _ in range(8)]

        def is_midi_node(node: 'NodeItem') -> bool:
            all_ports = list(node.input_ports.values()) + list(node.output_ports.values())
            if not all_ports: return False
            has_midi = any(p.port_obj.is_midi for p in all_ports)
            has_audio = any(p.port_obj.is_audio for p in all_ports)
            return has_midi and not has_audio

        for node in layout_nodes:
            has_conns = any(p.connections for p in node.input_ports.values()) or \
                        any(p.connections for p in node.output_ports.values())
            
            is_output_node = bool(node.output_ports) and not bool(node.input_ports)
            is_input_node = bool(node.input_ports) and not bool(node.output_ports)
            
            is_midi = is_midi_node(node)
            
            group_idx = -1
            
            if is_output_node:
                if has_conns:
                    group_idx = 4 if is_midi else 0
                else:
                    group_idx = 6 if is_midi else 2
            elif is_input_node:
                if has_conns:
                    group_idx = 5 if is_midi else 1
                else:
                    group_idx = 7 if is_midi else 3
            
            if group_idx != -1:
                groups[group_idx].append(node)

        # 4. Sort within groups
        for i in range(8):
            # Basic alphabetical sort for all groups first
            groups[i].sort(key=lambda n: n.client_name.lower())

        # Special sorting for connected inputs (groups 1 and 5) to align with their sources
        output_node_y_positions: Dict['NodeItem', float] = {} # Will be populated as we place output nodes

        def sort_key_connected_inputs(input_node: 'NodeItem') -> tuple:
            min_y = float('inf')
            is_connected = False
            for port in input_node.input_ports.values():
                for conn in port.connections:
                    source_node = conn.source_port.parentItem()
                    if source_node in output_node_y_positions:
                        is_connected = True
                        min_y = min(min_y, output_node_y_positions[source_node])
            
            # If connected to a placed node, use its Y. Otherwise put at end.
            if is_connected:
                return (0, min_y, input_node.client_name.lower())
            else:
                return (1, 0, input_node.client_name.lower())

        # 5. Layout columns
        start_x = 50.0
        start_y = 50.0
        col_spacing = 100.0
        group_spacing = 150.0 # Extra spacing between major sections (Audio vs MIDI, Connected vs Unconnected)
        
        current_x = start_x
        
        # We will process groups in pairs (Outputs, Inputs) to handle alignment
        # Pairs: (0,1), (2,3), (4,5), (6,7)
        
        pairs = [(0, 1), (2, 3), (4, 5), (6, 7)]
        
        for out_idx, in_idx in pairs:
            if not groups[out_idx] and not groups[in_idx]:
                continue
            
            # For connected pairs, use barycenter heuristic to minimize crossings
            if out_idx in [0, 4] and groups[out_idx] and groups[in_idx]:
                # Barycenter heuristic: iteratively sort each side by average position of connected nodes
                
                # Helper to calculate node heights for positioning
                def get_node_heights(node_list: List['NodeItem']) -> Dict['NodeItem', float]:
                    heights: Dict['NodeItem', float] = {}
                    for n in node_list:
                        _, h = layouter._get_node_size(n)
                        heights[n] = h
                    return heights
                
                out_heights = get_node_heights(groups[out_idx])
                in_heights = get_node_heights(groups[in_idx])
                
                # Helper to calculate Y center positions given an ordered list
                def calc_y_centers(node_list: List['NodeItem'], heights: Dict['NodeItem', float]) -> Dict['NodeItem', float]:
                    y_centers: Dict['NodeItem', float] = {}
                    y = start_y
                    for n in node_list:
                        y_centers[n] = y + heights[n] / 2  # Use center of node
                        y += heights[n] + layouter.min_vertical_spacing
                    return y_centers
                
                # Build connection map: output_node -> set of input_nodes
                out_to_in: Dict['NodeItem', set] = {n: set() for n in groups[out_idx]}
                in_to_out: Dict['NodeItem', set] = {n: set() for n in groups[in_idx]}
                
                for out_node in groups[out_idx]:
                    for port in out_node.output_ports.values():
                        for conn in port.connections:
                            in_node = conn.dest_port.parentItem()
                            if in_node in in_to_out:
                                out_to_in[out_node].add(in_node)
                                in_to_out[in_node].add(out_node)
                
                # Barycenter iterations
                for _ in range(5):  # Usually converges in 2-3 iterations
                    # Calculate output Y centers based on current order
                    out_y = calc_y_centers(groups[out_idx], out_heights)
                    
                    # Sort inputs by barycenter (average Y of connected outputs)
                    def in_barycenter(in_node: 'NodeItem') -> tuple:
                        connected = in_to_out[in_node]
                        if connected:
                            avg_y = sum(out_y[o] for o in connected) / len(connected)
                            return (0, avg_y, in_node.client_name.lower())
                        return (1, 0, in_node.client_name.lower())
                    
                    groups[in_idx].sort(key=in_barycenter)
                    
                    # Calculate input Y centers based on new order
                    in_y = calc_y_centers(groups[in_idx], in_heights)
                    
                    # Sort outputs by barycenter (average Y of connected inputs)
                    def out_barycenter(out_node: 'NodeItem') -> tuple:
                        connected = out_to_in[out_node]
                        if connected:
                            avg_y = sum(in_y[i] for i in connected) / len(connected)
                            return (0, avg_y, out_node.client_name.lower())
                        return (1, 0, out_node.client_name.lower())
                    
                    groups[out_idx].sort(key=out_barycenter)
            
            # --- Output Column ---
            max_w_out = 0.0
            current_y = start_y
            
            for node in groups[out_idx]:
                node_width, node_height = layouter._get_node_size(node)
                max_w_out = max(max_w_out, node_width)
                node.setPos(current_x, current_y)
                output_node_y_positions[node] = current_y
                current_y += node_height + layouter.min_vertical_spacing

            # Advance X for Input Column
            input_col_x = current_x + max_w_out + col_spacing if groups[out_idx] else current_x
            
            # --- Input Column ---
            # Re-sort inputs if they are connected types (1 or 5) and not already sorted above
            if in_idx in [1, 5] and out_idx not in [0, 4]:
                groups[in_idx].sort(key=sort_key_connected_inputs)
            
            max_w_in = 0.0
            current_y = start_y
            
            for node in groups[in_idx]:
                node_width, node_height = layouter._get_node_size(node)
                max_w_in = max(max_w_in, node_width)
                node.setPos(input_col_x, current_y)
                current_y += node_height + layouter.min_vertical_spacing
            
            # Advance X for next pair
            block_width = 0.0
            if groups[out_idx]:
                block_width += max_w_out
            if groups[in_idx]:
                if groups[out_idx]: block_width += col_spacing
                block_width += max_w_in
                
            current_x += block_width + group_spacing

        # 6. Update paths and save
        scene.connection_mgr.update_all_connection_paths()
        scene.save_node_states()
        return True
