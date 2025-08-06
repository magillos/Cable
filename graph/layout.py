"""
Graph layout algorithms for the Cable application.

This module contains the GraphLayouter class which handles automatic node arrangement
in the graph view to reduce visual clutter and improve readability.
"""

from __future__ import annotations
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Optional, Any, TYPE_CHECKING, Deque
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsTextItem, QStyleOptionGraphicsItem
from PyQt6.QtGui import QFont, QPainter, QColor
import math
import logging
from functools import singledispatchmethod
from . import constants

# Set up logging
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .node_item import NodeItem
    from .port_item import PortItem
    from .bulk_area_item import BulkAreaItem
    from . import constants
    from .jack_graph_scene import JackGraphScene  # For type checking only

# Type aliases for better readability
NodeRect = Tuple[float, float, float, float]  # x1, y1, x2, y2
NodePosition = Tuple[float, float]  # x, y

class GraphLayouter:
    """
    Handles automatic layout of nodes and their internal components in the graph.
    """
    def __init__(self, scene: 'JackGraphScene') -> None:
        """
        Initialize the GraphLayouter with a reference to the scene.
        
        Args:
            scene: The JackGraphScene instance that contains the nodes to be laid out.
            
        Raises:
            TypeError: If scene is not a valid JackGraphScene instance
        """
        if not hasattr(scene, 'nodes') or not hasattr(scene, 'connections'):
            raise TypeError("Scene must be a JackGraphScene with 'nodes' and 'connections' attributes")
            
        self.scene = scene
        self.min_horizontal_spacing = 30.0
        self.min_vertical_spacing = 30.0
        
        # Constants for node layout with type hints
        self.NODE_PADDING: float = 5.0
        self.NODE_VMARGIN: float = 2.0
        self.NODE_TITLE_HEIGHT: float = 24.0
        self.NODE_BULK_AREA_HPADDING: float = 2.0
        self.NODE_BULK_AREA_HEIGHT: float = 10.0
        self.PORT_HEIGHT: float = 18.0
        self.PORT_WIDTH_MIN: float = 60.0
        
        # Cache for node sizes to avoid repeated calculations
        self._node_size_cache: Dict[str, Tuple[float, float]] = {}
        
        # Initialize with default values that can be overridden by the scene's constants
        self._init_constants()
        
        logger.debug("GraphLayouter initialized with scene: %s", scene)
    
    def _init_constants(self) -> None:
        """
        Initialize constants from the scene's constants module if available.
        
        This method attempts to import the scene's constants module and override
        the default layout constants with any values defined there.
        """
        try:
            from . import constants as scene_constants
            
            # Update each constant if it exists in the scene's constants
            for const_name in [
                'NODE_PADDING', 'NODE_VMARGIN', 'NODE_TITLE_HEIGHT',
                'NODE_BULK_AREA_HPADDING', 'NODE_BULK_AREA_HEIGHT',
                'PORT_HEIGHT', 'PORT_WIDTH_MIN'
            ]:
                if hasattr(scene_constants, const_name):
                    setattr(self, const_name, getattr(scene_constants, const_name))
                    
            logger.debug("Initialized layout constants from scene")
            
        except ImportError as e:
            logger.debug("Could not import scene constants, using defaults: %s", str(e))
        except Exception as e:
            logger.warning("Error initializing layout constants: %s", str(e), exc_info=True)
            
    # --- Node Layout Methods ---
    
    def layout_node_ports(self, node: 'NodeItem') -> None:
        """
        Positions port items vertically and updates node height and width.
        
        Args:
            node: The NodeItem to lay out
        """
        node.prepareGeometryChange()

        max_in_width = max((port.calculated_width for port in node.input_ports.values()), 
                          default=self.PORT_WIDTH_MIN)
        max_out_width = max((port.calculated_width for port in node.output_ports.values()), 
                           default=self.PORT_WIDTH_MIN)

        # Default minimum node width if not specified
        DEFAULT_NODE_WIDTH = 150.0
        
        if node.is_split_origin:
            node_width = max(DEFAULT_NODE_WIDTH, 
                           max_in_width + max_out_width + 2 * self.NODE_PADDING)
        elif node.is_split_part:
            if node.input_ports and not node.output_ports:  # Input part
                node_width = max(DEFAULT_NODE_WIDTH, 
                               max_in_width + 2 * self.NODE_PADDING)
            elif node.output_ports and not node.input_ports:  # Output part
                node_width = max(DEFAULT_NODE_WIDTH, 
                               max_out_width + 2 * self.NODE_PADDING)
            else:  # Fallback for unexpected split part state
                node_width = max(DEFAULT_NODE_WIDTH, 
                               max_in_width + max_out_width + 2 * self.NODE_PADDING)
        else:  # Normal node
            node_width = max(DEFAULT_NODE_WIDTH, 
                           max_in_width + max_out_width + 2 * self.NODE_PADDING)
        
        node._bounding_rect.setWidth(node_width)
        title_height = self._calculate_and_set_title_geometry(node, node_width)

        if node.is_split_origin:
            node._bounding_rect.setHeight(title_height)
            self._hide_all_ports_and_bulk_areas(node)
            node.update()
            return

        if self._is_node_effectively_folded(node):
            node._bounding_rect.setHeight(title_height)
            self._hide_all_ports_and_bulk_areas(node)
            for port_list in [node.input_ports, node.output_ports]:
                for port_item in port_list.values():
                    for conn in port_item.connections:
                        conn.update_path()
            node.update()
            return

        self._show_all_ports_and_bulk_areas(node)

        y_current = title_height + self.NODE_VMARGIN
        self._layout_bulk_areas(node, node_width, max_in_width, max_out_width, y_current)

        if node.input_area_item or node.output_area_item:
            y_current += self.NODE_BULK_AREA_HEIGHT + self.NODE_VMARGIN
        
        y_in_final, y_out_final = self._layout_individual_ports(node, node_width, y_current)

        # Calculate the height based on the maximum extent of ports or bulk areas
        max_y_ports = 0
        if node.input_ports or node.output_ports:
            max_y_ports = max(y_in_final, y_out_final) - self.NODE_VMARGIN  # Remove last margin
        else:  # No ports, height is determined by bulk areas or just title
            max_y_ports = y_current  # This is the y_start_offset for ports

        max_y_bulk = 0
        if node.input_area_item or node.output_area_item:
            max_y_bulk = title_height + self.NODE_VMARGIN + self.NODE_BULK_AREA_HEIGHT
        else:  # No bulk areas
            max_y_bulk = title_height
            
        content_bottom_y = max(max_y_ports, max_y_bulk)
        
        # If there's no content below the title (e.g., only title, or title + empty bulk area space)
        # ensure a minimum content height for padding.
        if not (node.input_ports or node.output_ports or 
                node.input_area_item or node.output_area_item):
            # Only title is visible, or node is empty after title
            final_node_height = title_height + self.NODE_PADDING  # Minimal padding below title
        else:
            final_node_height = content_bottom_y + self.NODE_PADDING

        node._bounding_rect.setHeight(final_node_height)
        node.update()
    
    def _is_node_effectively_folded(self, node: 'NodeItem') -> bool:
        """
        Determines if the node should be treated as folded, considering its split state.
        
        Args:
            node: The NodeItem to check
            
        Returns:
            bool: True if the node should be treated as folded
        """
        if node.is_split_origin:
            return False  # Split origins are always collapsed/hidden
        if node.is_split_part:
            # For split parts, check their own fold state
            if node.input_ports and not node.output_ports:  # This is an input part
                return node.input_part_folded
            elif node.output_ports and not node.input_ports:  # This is an output part
                return node.output_part_folded
            # Fallback for unexpected split part with both input/output, or neither
            return False
        # For normal nodes, use the node's fold state
        return node.is_folded
    
    def _calculate_and_set_title_geometry(self, node: 'NodeItem', node_width: float) -> float:
        """
        Calculates and sets the title item's geometry and returns the calculated title height.
        
        Args:
            node: The NodeItem to update
            node_width: The width of the node
            
        Returns:
            float: The calculated title height
        """
        title_width = node_width - 2 * self.NODE_PADDING
        node.title_item.setTextWidth(title_width)
        node.title_item.setPos(self.NODE_PADDING, self.NODE_PADDING)
        doc_height = node.title_item.document().size().height()
        calculated_title_height = max(self.NODE_TITLE_HEIGHT, 
                                    doc_height + self.NODE_PADDING * 2)
        node._calculated_title_height = calculated_title_height
        node._header_rect = QRectF(0, 0, node._bounding_rect.width(), 
                                 calculated_title_height)
        return calculated_title_height
    
    def _hide_all_ports_and_bulk_areas(self, node: 'NodeItem') -> None:
        """
        Hides all port items and bulk area items for the given node.
        
        Args:
            node: The NodeItem to update
        """
        for port in list(node.input_ports.values()) + list(node.output_ports.values()):
            if port.isVisible():
                port.hide()
        if node.input_area_item and node.input_area_item.isVisible():
            node.input_area_item.hide()
        if node.output_area_item and node.output_area_item.isVisible():
            node.output_area_item.hide()
    
    def _show_all_ports_and_bulk_areas(self, node: 'NodeItem') -> None:
        """
        Shows all port items and bulk area items for the given node.
        
        Args:
            node: The NodeItem to update
        """
        for port in list(node.input_ports.values()) + list(node.output_ports.values()):
            if not port.isVisible():
                port.show()
        if node.input_area_item and not node.input_area_item.isVisible():
            node.input_area_item.show()
        if node.output_area_item and not node.output_area_item.isVisible():
            node.output_area_item.show()
    
    def _layout_bulk_areas(self, node: 'NodeItem', current_node_width: float, 
                         max_in_width: float, max_out_width: float, 
                         y_start_bulk: float) -> None:
        """
        Positions the bulk area items for the given node.
        
        Args:
            node: The NodeItem to update
            current_node_width: Current width of the node
            max_in_width: Maximum width of input ports
            max_out_width: Maximum width of output ports
            y_start_bulk: Y-coordinate to start placing bulk areas
        """
        pad = self.NODE_BULK_AREA_HPADDING
        if node.input_area_item:
            bulk_in_width = max_in_width - 2 * pad
            node.input_area_item._bounding_rect.setWidth(bulk_in_width)
            node.input_area_item.setPos(pad, y_start_bulk)
        
        if node.output_area_item:
            bulk_out_width = max_out_width - 2 * pad
            node.output_area_item._bounding_rect.setWidth(bulk_out_width)
            out_x = pad if (node.is_split_part and node.input_ports) else \
                   (current_node_width - max_out_width + pad)
            node.output_area_item.setPos(out_x, y_start_bulk)
    
    def _layout_individual_ports(self, node: 'NodeItem', current_node_width: float, 
                              y_start_ports: float) -> Tuple[float, float]:
        """
        Positions individual port items and returns the final y-offsets for inputs and outputs.
        
        Args:
            node: The NodeItem to update
            current_node_width: Current width of the node
            y_start_ports: Y-coordinate to start placing ports
            
        Returns:
            Tuple[float, float]: Final y-offsets for input and output ports
        """
        from .node_item import natural_sort_key
        
        # Separate and sort audio ports first, then MIDI ports
        input_audio_ports = [p for p in node.input_ports.values() 
                            if not p.port_obj.is_midi]
        input_midi_ports = [p for p in node.input_ports.values() 
                           if p.port_obj.is_midi]
        output_audio_ports = [p for p in node.output_ports.values() 
                             if not p.port_obj.is_midi]
        output_midi_ports = [p for p in node.output_ports.values() 
                            if p.port_obj.is_midi]

        y_in = y_start_ports
        # Layout audio input ports first
        for port_item in sorted(input_audio_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            port_item.setPos(0, y_in)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, 
                                            self.PORT_HEIGHT)
            y_in += self.PORT_HEIGHT + self.NODE_VMARGIN
            
        # Then MIDI input ports
        for port_item in sorted(input_midi_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            port_item.setPos(0, y_in)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, 
                                            self.PORT_HEIGHT)
            y_in += self.PORT_HEIGHT + self.NODE_VMARGIN

        y_out = y_start_ports
        # Layout audio output ports first
        for port_item in sorted(output_audio_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            x_pos = current_node_width - port_item.calculated_width
            port_item.setPos(x_pos, y_out)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, 
                                            self.PORT_HEIGHT)
            y_out += self.PORT_HEIGHT + self.NODE_VMARGIN
            
        # Then MIDI output ports
        for port_item in sorted(output_midi_ports, key=natural_sort_key):
            port_item.calculated_width = port_item._calculate_required_width()
            x_pos = current_node_width - port_item.calculated_width
            port_item.setPos(x_pos, y_out)
            port_item._bounding_rect = QRectF(0, 0, port_item.calculated_width, 
                                            self.PORT_HEIGHT)
            y_out += self.PORT_HEIGHT + self.NODE_VMARGIN
            
        return y_in, y_out
    
    def untangle_graph(self, max_nodes_per_row=6):
        """
        Automatically organizes the graph nodes to reduce visual clutter.
        This method arranges nodes in a logical flow based on their connections:
        1. Starts with nodes that only have output ports (source nodes)
        2. Places connected nodes in a pattern that reduces connection crossing
        3. Groups disconnected nodes separately
        
        Args:
            max_nodes_per_row (int): Maximum number of nodes to place in a row before
                                     starting a new row. Default is 6.
        """
        if not self.scene.nodes:
            return  # No nodes to untangle
            
        # Identify original nodes and their split parts, exclude origins from direct layout
        layout_nodes = {}
        original_node_parts = defaultdict(lambda: {'input': None, 'output': None})
        for client_name, node in self.scene.nodes.items():
            if node.is_split_origin:
                if node.split_input_node:
                    original_node_parts[node.client_name]['input'] = node.split_input_node
                if node.split_output_node:
                    original_node_parts[node.client_name]['output'] = node.split_output_node
                # Exclude split origins from direct layout, their parts will be handled
                continue
            layout_nodes[client_name] = node

        if not layout_nodes:
            return # No visible nodes to untangle
            
        # Initialize tracking variables
        placed_nodes = set()
        row = 0
        col = 0
        node_count = 0
        
        # Define a minimum spacing based on node bounding rectangles
        self.min_horizontal_spacing = 30  # Minimum gap between nodes horizontally
        self.min_vertical_spacing = 30    # Minimum gap between nodes vertically
            
        # Track positions and sizes of placed nodes
        node_positions = []  # List of (node, rect) tuples
        
        # Calculate a reasonable starting point
        start_x = 50
        start_y = 50
        current_row_height = 0
        
        # Find source nodes (nodes with only output ports or no connections)
        source_nodes, connected_nodes = self._find_source_nodes(layout_nodes, original_node_parts)
        
        # Place source nodes first
        x = start_x
        y = start_y
        row_nodes = []
        
        for node in source_nodes:
            if node.client_name in placed_nodes:
                continue
                
            # Handle split nodes and their siblings
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
            
            # Place the node
            node_width, node_height = self._get_node_size(node)
            current_row_height = max(current_row_height, node_height)
            
            # If this would exceed max_nodes_per_row, move to next row
            if len(row_nodes) >= max_nodes_per_row:
                x = start_x
                y += current_row_height + self.min_vertical_spacing
                row_nodes = []
                current_row_height = node_height
            
            # Check if the node would overlap with any placed node
            attempt_count = 0
            original_x, original_y = x, y
            
            while self._position_causes_overlap(node, x, y, node_positions) and attempt_count < 10:
                x += self.min_horizontal_spacing
                attempt_count += 1
                
                if attempt_count >= 5:
                    x = original_x
                    y += self.min_vertical_spacing
            
            # Set node position
            node.setPos(x, y)
            placed_nodes.add(node.client_name)
            node_positions.append((node, (x, y, x + node_width, y + node_height)))
            row_nodes.append(node)
            
            # Update position for next node
            x += node_width + self.min_horizontal_spacing
            
            # Update node configuration for persistence
            if node.client_name in self.scene.node_configs:
                self.scene.node_configs[node.client_name]['pos'] = (x, y)
                
            node_count += 1
        
        # Now place connected nodes in sequence
        # Move to next row for connected nodes
        y += current_row_height + self.min_vertical_spacing * 2
        x = start_x  # Always start from the left
        row_nodes = []
        current_row_height = 0
        
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
            connected_nodes = []
            unconnected_nodes = []
            next_nodes = self._get_next_nodes(current_node, placed_nodes, connected_nodes, unconnected_nodes)
            
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
                    
                # Get node dimensions
                node_width, node_height = self._get_node_size(node)
                current_row_height = max(current_row_height, node_height)
                
                # If this would exceed max_nodes_per_row, move to next row
                if len(row_nodes) >= max_nodes_per_row:
                    x = start_x
                    y += current_row_height + self.min_vertical_spacing
                    row_nodes = []
                    current_row_height = node_height
                
                # Check if the node would overlap with any placed node
                attempt_count = 0
                original_x_attempt, original_y_attempt = x, y
                temp_x, temp_y = x, y

                while self._position_causes_overlap(node, temp_x, temp_y, node_positions) and attempt_count < 10:
                    # Try adjusting position slightly - always move right now
                    temp_x += self.min_horizontal_spacing
                    attempt_count += 1
                    
                    if attempt_count >= 5:
                        temp_x = original_x_attempt # Reset x for this attempt
                        temp_y += self.min_vertical_spacing # Try moving vertically

                # Update main x, y with the non-overlapping position
                x, y = temp_x, temp_y
                
                # Set node position
                node.setPos(x, y)
                placed_nodes.add(node.client_name)
                if node.client_name not in processed and node.client_name not in to_process:
                    to_process.append(node.client_name)
                node_positions.append((node, (x, y, x + node_width, y + node_height)))
                row_nodes.append(node)
                
                # Update position for next node in the current row - always left to right
                x += node_width + self.min_horizontal_spacing
                
                # Update node configuration
                if node.client_name in self.scene.node_configs:
                    if node.is_split_part and node.split_origin_node:
                        origin_name = node.split_origin_node.client_name
                        if origin_name not in self.scene.node_configs: 
                            self.scene.node_configs[origin_name] = {}
                        pos_key = "split_input_pos" if (node == node.split_origin_node.split_input_node or node.client_name.endswith(constants.SPLIT_INPUT_SUFFIX)) else "split_output_pos"
                        self.scene.node_configs[origin_name][pos_key] = (x, y) # Store tuple
                    elif not node.is_split_origin: # Normal non-split node
                        if node.client_name not in self.scene.node_configs: 
                            self.scene.node_configs[node.client_name] = {}
                        self.scene.node_configs[node.client_name]['pos'] = (x, y) # Store tuple

                node_count += 1
        
        # Finally, place any remaining unconnected nodes
        # Move to next row with extra spacing
        y += current_row_height + self.min_vertical_spacing * 3
        x = start_x
        row_nodes = []
        current_row_height = 0
        
        for client_name, node in layout_nodes.items():
            if client_name in placed_nodes:
                continue
                
            # Get node dimensions
            node_width, node_height = self._get_node_size(node)
            current_row_height = max(current_row_height, node_height)
            
            # If this would exceed max_nodes_per_row, move to next row
            if len(row_nodes) >= max_nodes_per_row:
                x = start_x
                y += current_row_height + self.min_vertical_spacing
                row_nodes = []
                current_row_height = node_height
            
            # Check if the node would overlap with any placed node
            attempt_count = 0
            original_x, original_y = x, y
            
            while self._position_causes_overlap(node, x, y, node_positions) and attempt_count < 10:
                # Try adjusting position slightly
                x += self.min_horizontal_spacing
                attempt_count += 1
                
                # If we've tried several times horizontally, try moving vertically
                if attempt_count >= 5:
                    x = original_x
                    y += self.min_vertical_spacing
            
            # Set node position
            node.setPos(x, y)
            node_positions.append((node, (x, y, x + node_width, y + node_height)))
            row_nodes.append(node)
            
            # Update position for next node
            x += node_width + self.min_horizontal_spacing
            
            # Update node configuration
            if client_name in self.scene.node_configs:
                self.scene.node_configs[client_name]['pos'] = (x, y)
        
        # Update all connection paths
        self.scene.update_all_connection_paths()
        
        # Save the new node positions to config
        self.scene.save_node_states()
    
    def _identify_nodes_and_splits(self) -> tuple:
        """Identify original nodes and their split parts."""
        layout_nodes = {}
        original_node_parts = defaultdict(lambda: {'input': None, 'output': None})
        
        for client_name, node in self.scene.nodes.items():
            if node.is_split_origin:
                if node.split_input_node:
                    original_node_parts[node.client_name]['input'] = node.split_input_node
                if node.split_output_node:
                    original_node_parts[node.client_name]['output'] = node.split_output_node
                continue
            layout_nodes[client_name] = node
            
        return layout_nodes, original_node_parts
    
    def _find_source_nodes(self, layout_nodes: dict, original_node_parts: dict) -> tuple:
        """Find source nodes (nodes with only output ports or no connections)."""
        source_nodes = []
        connected_nodes = set()
        
        # First, identify all nodes that participate in connections
        for connection_key in self.scene.connections:
            out_port, in_port = connection_key
            out_node_candidate_name = out_port.split(':')[0]
            in_node_candidate_name = in_port.split(':')[0]

            out_node_item = self.scene.nodes.get(out_node_candidate_name)
            in_node_item = self.scene.nodes.get(in_node_candidate_name)

            if out_node_item:
                actual_out_client = out_node_item.original_client_name if out_node_item.is_split_part else out_node_item.client_name
                if actual_out_client:
                    connected_nodes.add(actual_out_client)
            
            if in_node_item:
                actual_in_client = in_node_item.original_client_name if in_node_item.is_split_part else in_node_item.client_name
                if actual_in_client:
                    connected_nodes.add(actual_in_client)
        
        # Find nodes with only output ports or ones that are starting points
        for client_name, node in layout_nodes.items():
            effective_client_name = node.original_client_name if node.is_split_part else client_name
            has_inputs, has_outputs = self._get_port_connection_states(node)
            
            if (has_outputs and not has_inputs) or (not has_inputs and not has_outputs and effective_client_name in connected_nodes):
                source_nodes.append(node)
        
        # If no source nodes found, use any connected node as starting point
        if not source_nodes and connected_nodes:
            self._find_alternative_source_nodes(connected_nodes, layout_nodes, original_node_parts, source_nodes)
            
        return source_nodes, connected_nodes
    
    def _get_port_connection_states(self, node: 'NodeItem') -> tuple:
        """
        Check if a node has connected input and output ports.
        
        Args:
            node: The node to check for port connections
            
        Returns:
            Tuple of (has_connected_inputs, has_connected_outputs)
        """
        has_inputs = False
        if node.is_split_part:
            # For split parts, check connections based on the part type
            is_input_part = bool(node.input_ports)
            is_output_part = bool(node.output_ports)
            
            # Check if any connections exist for this part
            has_conns = False
            ports_to_check = node.input_ports if is_input_part else node.output_ports
            for port in ports_to_check.values():
                if port.connections:
                    has_conns = True
                    break
                    
            return (has_conns if is_input_part else False, 
                    has_conns if is_output_part else False)
                    
        # For regular nodes or split origins
        has_inputs = any(port.connections for port in node.input_ports.values())
        has_outputs = any(port.connections for port in node.output_ports.values())
        
        return has_inputs, has_outputs
            
    def _find_alternative_source_nodes(self, connected_nodes: set, layout_nodes: dict, 
                                     original_node_parts: dict, source_nodes: list) -> None:
        """Find alternative source nodes when no obvious sources are found."""
        for client_name in connected_nodes:
            found_node_for_source = None
            if client_name in layout_nodes:
                found_node_for_source = layout_nodes[client_name]
            elif client_name in original_node_parts:
                if original_node_parts[client_name]['output']:
                    found_node_for_source = original_node_parts[client_name]['output']
                elif original_node_parts[client_name]['input']:
                    found_node_for_source = original_node_parts[client_name]['input']
            
            if found_node_for_source and found_node_for_source not in source_nodes:
                source_nodes.append(found_node_for_source)

    def _place_node(self, node: 'NodeItem', x: float, y: float, max_nodes_per_row: int, 
                   row_nodes: list, current_row_height: float, 
                   node_positions: list, placed_nodes: set) -> tuple[float, float, float]:
        """
        Place a single node in the graph at the specified position, avoiding overlaps.
        
        Args:
            node: The node to place
            x: Desired x-coordinate
            y: Desired y-coordinate
            max_nodes_per_row: Maximum nodes allowed per row
            row_nodes: List of nodes in the current row
            current_row_height: Height of the current row
            node_positions: List of (x1, y1, x2, y2) for all placed nodes
            placed_nodes: Set of node client names that have been placed
            
        Returns:
            Tuple of (new_x, new_y, new_row_height) after placement
        """
        if not node:
            return x, y, current_row_height
            
        # Get node dimensions
        node_width, node_height = self._get_node_size(node)
        
        # Find non-overlapping position
        new_x, new_y = self._find_non_overlapping_position(node, x, y, node_positions)
        
        # Update node position
        node.setPos(new_x, new_y)
        
        # Add to placed nodes
        placed_nodes.add(node.client_name)
        
        # Update row tracking
        row_nodes.append(node)
        
        # Update current row height if this node is taller
        new_row_height = max(current_row_height, node_height)
        
        # Add to node positions for overlap detection
        node_rect = (
            new_x - self.min_horizontal_spacing,
            new_y - self.min_vertical_spacing,
            new_x + node_width + self.min_horizontal_spacing,
            new_y + node_height + self.min_vertical_spacing
        )
        node_positions.append(node_rect)
        
        # Calculate next position
        if len(row_nodes) >= max_nodes_per_row:
            # Move to next row
            next_x = node_rect[0]  # Start of row
            next_y = node_rect[3] + self.min_vertical_spacing
            next_row_height = 0
        else:
            # Move right in current row
            next_x = node_rect[2] + self.min_horizontal_spacing
            next_y = y
            next_row_height = new_row_height
            
        return next_x, next_y, next_row_height

    def _handle_split_sibling_placement(self, current_node: 'NodeItem', 
                                     next_nodes: List['NodeItem'], 
                                     placed_nodes: Set[str], 
                                     original_node_parts: Dict[str, 'NodeItem']) -> None:
        """
        Handle placement of split node siblings to keep them visually grouped.
        
        Args:
            current_node: The node currently being placed
            next_nodes: List of nodes to be placed next (modified in place)
            placed_nodes: Set of node client names that have been placed
            original_node_parts: Dictionary mapping original node names to their split parts
        """
        try:
            if not current_node or not current_node.is_split_part or not current_node.split_origin_node:
                return
                
            origin = current_node.split_origin_node
            
            # Determine if current node is the input or output part
            is_current_input = (origin.split_input_node == current_node) or \
                             (hasattr(current_node, 'client_name') and 
                              constants.SPLIT_INPUT_SUFFIX in current_node.client_name)
            
            # Find the sibling that should be placed next
            sibling_to_place = None
            if is_current_input and origin.split_output_node:
                sibling_to_place = origin.split_output_node
            elif not is_current_input and origin.split_input_node:
                sibling_to_place = origin.split_input_node
                
            # Add sibling to next_nodes if it hasn't been placed yet
            if (sibling_to_place and 
                sibling_to_place.client_name not in placed_nodes and
                sibling_to_place not in next_nodes):
                
                # Check if sibling is already in the queue to be placed
                is_sibling_pending = any(
                    node == sibling_to_place or 
                    (hasattr(node, 'client_name') and 
                     node.client_name == sibling_to_place.client_name)
                    for node in next_nodes
                )
                
                if not is_sibling_pending:
                    # Insert at beginning to prioritize placing the sibling next
                    next_nodes.insert(0, sibling_to_place)
                    logger.debug("Added split sibling %s to placement queue", 
                                sibling_to_place.client_name)
                                    
        except Exception as e:
            logger.error("Error handling split sibling placement: %s", str(e), exc_info=True)

    def _place_unconnected_nodes(self, layout_nodes: Dict, placed_nodes: Set, 
                               max_nodes_per_row: int, node_positions: List, 
                               start_x: float, start_y: float, 
                               start_row_height: float) -> None:
        """
        Place any remaining unconnected nodes.
        
        Args:
            layout_nodes: Dictionary of all nodes to potentially place
            placed_nodes: Set of node client names that have already been placed
            max_nodes_per_row: Maximum number of nodes to place in a single row
            node_positions: List of tuples containing node and its position (x1, y1, x2, y2)
            start_x: X-coordinate to start placing nodes
            start_y: Y-coordinate to start placing nodes
            start_row_height: Height of the current row
        """
        y = start_y + start_row_height + self.min_vertical_spacing * 3
        x = start_x
        row_nodes = []
        current_row_height = 0
        
        for client_name, node in layout_nodes.items():
            if client_name in placed_nodes:
                continue
                
            # Get node dimensions
            node_width, node_height = self._get_node_size(node)
            
            # If this would exceed max_nodes_per_row, move to next row
            if len(row_nodes) >= max_nodes_per_row:
                x = start_x
                y = max(y + current_row_height + self.min_vertical_spacing, 
                       start_y + start_row_height + self.min_vertical_spacing * 3)
                row_nodes = []
                current_row_height = 0
            
            # Place the node
            x, y, current_row_height = self._place_node(
                node, x, y, max_nodes_per_row, row_nodes, 
                current_row_height, node_positions, placed_nodes
            )
            
            # Update node configuration for persistence
            if node.client_name in self.scene.node_configs:
                self.scene.node_configs[node.client_name]['pos'] = (x, y)
        
        return x, y, current_row_height

    def _get_node_size(self, node: 'NodeItem') -> tuple[float, float]:
        """
        Get the size of a node, including all its ports and margins.
        
        Args:
            node: The node to measure
            
        Returns:
            Tuple of (width, height) in scene coordinates
        """
        if not node:
            return 100.0, 100.0  # Default size if node is invalid
            
        # Get the node's bounding rectangle in scene coordinates
        rect = node.boundingRect()
        
        # Add some padding around the node
        padding = self.min_horizontal_spacing / 2
        width = rect.width() + padding * 2
        height = rect.height() + padding * 2
        
        return width, height
        
    def _find_non_overlapping_position(self, node: 'NodeItem', x: float, y: float, 
                                     node_positions: list) -> tuple:
        """Find a position for the node that doesn't overlap with existing nodes."""
        node_width, node_height = self._get_node_size(node)
        original_x, original_y = x, y
        attempt_count = 0
        
        while self._position_causes_overlap(node, x, y, node_positions) and attempt_count < 10:
            x += self.min_horizontal_spacing
            attempt_count += 1
            
            if attempt_count >= 5:
                x = original_x
                y += self.min_vertical_spacing
        
        return x, y

    def _position_causes_overlap(self, node: 'NodeItem', x: float, y: float, 
                               existing_positions: list) -> bool:
        """Check if placing a node at (x,y) would cause an overlap."""
        node_width, node_height = self._get_node_size(node)
        node_rect = (x, y, x + node_width, y + node_height)
        
        for pos_node, pos_rect in existing_positions:
            if pos_node == node:
                continue
                
            if (node_rect[0] < pos_rect[2] and node_rect[2] > pos_rect[0] and
                node_rect[1] < pos_rect[3] and node_rect[3] > pos_rect[1]):
                return True
                
        return False

    def _get_next_nodes(self, current_node: 'NodeItem', placed_nodes: set, 
                      connected_nodes: list, unconnected_nodes: list) -> list['NodeItem']:
        """
        Get nodes connected to the current node that haven't been placed yet.
        
        Args:
            current_node: The node to find connections from
            placed_nodes: Set of node client names that have already been placed
            connected_nodes: List to track connected nodes (modified in place)
            unconnected_nodes: List to track unconnected nodes (modified in place)
            
        Returns:
            List of NodeItem instances that are connected to current_node and not yet placed
        """
        try:
            if not current_node or not hasattr(self.scene, 'connections'):
                return []
                
            next_nodes = []
            current_client_name = current_node.client_name
            
            # Find nodes that receive input from this node
            for connection_key in self.scene.connections:
                if not isinstance(connection_key, tuple) or len(connection_key) != 2:
                    continue
                    
                out_port, in_port = connection_key
                
                # Extract client names from port names (format: "client_name:port_name")
                try:
                    out_client_part_name = out_port.split(':', 1)[0]
                    in_client_part_name = in_port.split(':', 1)[0]
                except (AttributeError, IndexError):
                    logger.warning("Invalid port format in connection: %s -> %s", 
                                 out_port, in_port)
                    continue
                
                # Check if this connection originates from the current node
                if out_client_part_name == current_client_name and in_client_part_name not in placed_nodes:
                    target_node = self.scene.nodes.get(in_client_part_name)
                    if target_node and target_node not in next_nodes:
                        next_nodes.append(target_node)
                        if target_node in unconnected_nodes:
                            unconnected_nodes.remove(target_node)
                        if target_node not in connected_nodes:
                            connected_nodes.append(target_node)
            
            # Handle split node siblings
            if current_node.is_split_part and current_node.split_origin_node:
                origin = current_node.split_origin_node
                is_input_part = (current_node == origin.split_input_node) or \
                              (hasattr(current_node, 'client_name') and 
                               constants.SPLIT_INPUT_SUFFIX in current_node.client_name)
                
                if is_input_part and origin.split_output_node:
                    output_sibling = origin.split_output_node
                    if (output_sibling.client_name not in placed_nodes and 
                        output_sibling not in next_nodes):
                        # Insert at beginning to prioritize placing output sibling next
                        next_nodes.insert(0, output_sibling)
                        
            return next_nodes
            
        except Exception as e:
            logger.error("Error getting next nodes: %s", str(e), exc_info=True)
            return []

    def _handle_split_sibling_placement(self, current_node: 'NodeItem', 
                                     next_nodes: List['NodeItem'], 
                                     placed_nodes: Set[str], 
                                     original_node_parts: Dict[str, 'NodeItem']) -> None:
        """
        Handle placement of split node siblings to keep them visually grouped.
        
        Args:
            current_node: The node currently being placed
            next_nodes: List of nodes to be placed next (modified in place)
            placed_nodes: Set of node client names that have been placed
            original_node_parts: Dictionary mapping original node names to their split parts
        """
        try:
            if not current_node or not current_node.is_split_part or not current_node.split_origin_node:
                return
                
            origin = current_node.split_origin_node
            
            # Determine if current node is the input or output part
            is_current_input = (origin.split_input_node == current_node) or \
                             (hasattr(current_node, 'client_name') and 
                              constants.SPLIT_INPUT_SUFFIX in current_node.client_name)
            
            # Find the sibling that should be placed next
            sibling_to_place = None
            if is_current_input and origin.split_output_node:
                sibling_to_place = origin.split_output_node
            elif not is_current_input and origin.split_input_node:
                sibling_to_place = origin.split_input_node
                
            # Add sibling to next_nodes if it hasn't been placed yet
            if (sibling_to_place and 
                sibling_to_place.client_name not in placed_nodes and
                sibling_to_place not in next_nodes):
                
                # Check if sibling is already in the queue to be placed
                is_sibling_pending = any(
                    node == sibling_to_place or 
                    (hasattr(node, 'client_name') and 
                     node.client_name == sibling_to_place.client_name)
                    for node in next_nodes
                )
                
                if not is_sibling_pending:
                    # Insert at beginning to prioritize placing the sibling next
                    next_nodes.insert(0, sibling_to_place)
                    logger.debug("Added split sibling %s to placement queue", 
                                sibling_to_place.client_name)
                                
        except Exception as e:
            logger.error("Error handling split sibling placement: %s", str(e), exc_info=True)

    def _place_unconnected_nodes(self, layout_nodes: Dict, placed_nodes: Set, 
                               max_nodes_per_row: int, node_positions: List, 
                               start_x: float, start_y: float, 
                               start_row_height: float) -> None:
        """
        Place any remaining unconnected nodes.
        
        Args:
            layout_nodes: Dictionary of all nodes to potentially place
            placed_nodes: Set of node client names that have already been placed
            max_nodes_per_row: Maximum number of nodes to place in a single row
            node_positions: List of tuples containing node and its position (x1, y1, x2, y2)
            start_x: X-coordinate to start placing nodes
            start_y: Y-coordinate to start placing nodes
            start_row_height: Height of the current row
        """
        y = start_y + start_row_height + self.min_vertical_spacing * 3
        x = start_x
        row_nodes = []
        current_row_height = 0
        
        # Place each unplaced node in a grid-like pattern
        for client_name, node in layout_nodes.items():
            if client_name in placed_nodes:
                continue
                
            # Place the node
            x, y, current_row_height = self._place_node(
                node=node,
                x=x,
                y=y,
                max_nodes_per_row=max_nodes_per_row,
                row_nodes=row_nodes,
                current_row_height=current_row_height,
                node_positions=node_positions,
                placed_nodes=placed_nodes
            )
            
            # Reset for next row if needed
            if len(row_nodes) >= max_nodes_per_row:
                x = start_x
                row_nodes = []
                current_row_height = 0
