import logging
from typing import Any, Dict, Set, List
from .base import LayoutStrategy

logger = logging.getLogger(__name__)

class UntangleStrategy(LayoutStrategy):
    """
    Layout strategy that organizes the graph nodes to reduce visual clutter.
    Arranges nodes in a logical flow:
    1. Starts with nodes that only have output ports (source nodes)
    2. Places connected nodes in a pattern that reduces connection crossing
    3. Groups disconnected nodes separately
    """
    
    def apply(self, layouter: 'GraphLayouter', scene: 'JackGraphScene', **kwargs: Any) -> bool:
        max_nodes_per_row = kwargs.get('max_nodes_per_row', 6)
        
        if not scene.nodes:
            return True  # No nodes to untangle
            
        # Identify original nodes and their split parts, exclude origins from direct layout
        layout_nodes, original_node_parts = layouter._identify_nodes_and_splits()

        if not layout_nodes:
            return True # No visible nodes to untangle
            
        # Initialize tracking variables
        placed_nodes: Set[str] = set()
        node_count = 0
            
        # Track positions and sizes of placed nodes
        node_positions = []  # List of (node, rect) tuples
        
        # Calculate a reasonable starting point
        start_x = 50.0
        start_y = 50.0
        current_row_height = 0.0
        
        # Find source nodes (nodes with only output ports or no connections)
        source_nodes, connected_nodes = layouter._find_source_nodes(layout_nodes, original_node_parts)
        
        # Place source nodes first
        x = start_x
        y = start_y
        row_nodes: List['NodeItem'] = []
        
        for node in source_nodes:
            if node.client_name in placed_nodes:
                continue
                
            # Handle split nodes and their siblings
            from graph import constants
            if node.is_split_part and node.split_origin_node:
                origin = node.split_origin_node
                is_current_node_input_part = (node == origin.split_input_node) or node.client_name.endswith(constants.SPLIT_INPUT_SUFFIX)
                is_current_node_output_part = (node == origin.split_output_node) or node.client_name.endswith(constants.SPLIT_OUTPUT_SUFFIX)

                sibling_part = None
                if is_current_node_input_part and origin.split_output_node:
                    sibling_part = origin.split_output_node
                elif is_current_node_output_part and origin.split_input_node:
                    sibling_part = origin.split_input_node

                # If the current node is an input part, but its output sibling is a better source (has outputs, no inputs)
                # and hasn't been placed, prioritize the output sibling.
                if is_current_node_input_part and sibling_part and sibling_part.client_name not in placed_nodes:
                    # Check if sibling is a "truer" source
                    sib_has_inputs = any(p for p in sibling_part.input_ports.values() if p.connections)
                    sib_has_outputs = any(p for p in sibling_part.output_ports.values() if p.connections)
                    if sib_has_outputs and not sib_has_inputs:
                        # This sibling is a better source, add it to source nodes if not already there
                        if sibling_part not in source_nodes:
                            source_nodes.insert(0, sibling_part)
            
            x, y, current_row_height = layouter._place_node(
                node, x, y, max_nodes_per_row, row_nodes, 
                current_row_height, node_positions, placed_nodes, start_x=start_x
            )
            
            # Update node configuration for persistence
            if node.client_name in scene.node_configs:
                scene.node_configs[node.client_name]['pos'] = (node.scenePos().x(), node.scenePos().y())
                
            node_count += 1
        
        # Now place connected nodes in sequence
        # Move to next row for connected nodes
        y += current_row_height + layouter.min_vertical_spacing * 2
        x = start_x  # Always start from the left
        row_nodes = []
        current_row_height = 0.0
        
        # Process all already placed nodes to find their connections
        processed = set()
        to_process = list(placed_nodes)
        
        while to_process:
            current_client_name = to_process.pop(0)
            if current_client_name in processed:
                continue
                
            processed.add(current_client_name)
            current_node = layout_nodes.get(current_client_name)
            
            if not current_node:
                continue
                
            # Get nodes connected to this one
            connected_list: List['NodeItem'] = []
            unconnected_list: List['NodeItem'] = []
            next_nodes = layouter._get_next_nodes(current_node, placed_nodes, connected_list, unconnected_list)
            
            # Try to place sibling part next if it hasn't been placed
            if current_node.is_split_part and current_node.split_origin_node:
                origin = current_node.split_origin_node
                sibling_to_place_next = None
                is_current_input = origin.split_input_node == current_node
                
                if is_current_input and origin.split_output_node and origin.split_output_node.client_name not in placed_nodes:
                    sibling_to_place_next = origin.split_output_node
                elif not is_current_input and origin.split_input_node and origin.split_input_node.client_name not in placed_nodes: # current is output
                    sibling_to_place_next = origin.split_input_node
                
                if sibling_to_place_next and sibling_to_place_next not in next_nodes:
                    is_sibling_pending = any(item == sibling_to_place_next.client_name for item in to_process)
                    if not is_sibling_pending:
                        next_nodes.insert(0, sibling_to_place_next) # Prioritize sibling

            for node in next_nodes:
                if node.client_name in placed_nodes:
                    continue
                    
                x, y, current_row_height = layouter._place_node(
                    node, x, y, max_nodes_per_row, row_nodes, 
                    current_row_height, node_positions, placed_nodes, start_x=start_x
                )
                
                if node.client_name not in processed and node.client_name not in to_process:
                    to_process.append(node.client_name)
                
                # Update node configuration
                if node.client_name in scene.node_configs:
                    if node.is_split_part and node.split_origin_node:
                        origin_name = node.split_origin_node.client_name
                        if origin_name not in scene.node_configs: 
                            scene.node_configs[origin_name] = {}
                        from graph import constants
                        pos_key = "split_input_pos" if (node == node.split_origin_node.split_input_node or node.client_name.endswith(constants.SPLIT_INPUT_SUFFIX)) else "split_output_pos"
                        scene.node_configs[origin_name][pos_key] = (node.scenePos().x(), node.scenePos().y()) # Store tuple
                    elif not node.is_split_origin: # Normal non-split node
                        if node.client_name not in scene.node_configs: 
                            scene.node_configs[node.client_name] = {}
                        scene.node_configs[node.client_name]['pos'] = (node.scenePos().x(), node.scenePos().y()) # Store tuple

                node_count += 1
        
        # Finally, place any remaining unconnected nodes
        layouter._place_unconnected_nodes(
            layout_nodes, placed_nodes, max_nodes_per_row, 
            node_positions, start_x, y, current_row_height
        )
        
        # Update all connection paths
        scene.connection_mgr.update_all_connection_paths()
        
        # Save the new node positions to config
        scene.save_node_states()
        
        return True
