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
import random
from math import sqrt
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
        if getattr(scene, 'nodes', None) is None or getattr(scene, 'connections', None) is None:
            raise TypeError("Scene must be a JackGraphScene with 'nodes' and 'connections' attributes")
            
        self.scene = scene
        self.min_horizontal_spacing = constants.MIN_NODE_H_SPACING
        self.min_vertical_spacing = constants.MIN_NODE_V_SPACING
        
        # Constants for node layout with type hints
        self.NODE_PADDING: float = 5.0
        self.NODE_VMARGIN: float = 2.0
        self.NODE_TITLE_HEIGHT: float = 24.0
        self.NODE_BULK_AREA_HPADDING: float = 2.0
        self.NODE_BULK_AREA_HEIGHT: float = 10.0
        self.NODE_BULK_PAIR_AREA_HEIGHT: float = 12.0
        self.NODE_CONTENT_PADDING: float = 2.0
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
                'NODE_BULK_PAIR_AREA_HEIGHT',
                'NODE_CONTENT_PADDING',
                'PORT_HEIGHT', 'PORT_WIDTH_MIN'
            ]:
                value = getattr(scene_constants, const_name, None)
                if value is not None:
                    setattr(self, const_name, value)
                    
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
        content_pad = constants.NODE_CONTENT_PADDING  # Inset to keep content clear of node border
    
        if node.is_split_origin:
            node_width = max(DEFAULT_NODE_WIDTH,
                             max_in_width + max_out_width + 2 * self.NODE_PADDING + 2 * content_pad)
        elif node.is_split_part:
            if node.input_ports and not node.output_ports: # Input part
                node_width = max(DEFAULT_NODE_WIDTH,
                                 max_in_width + 2 * self.NODE_PADDING + 2 * content_pad)
            elif node.output_ports and not node.input_ports: # Output part
                node_width = max(DEFAULT_NODE_WIDTH,
                                 max_out_width + 2 * self.NODE_PADDING + 2 * content_pad)
            else: # Fallback for unexpected split part state
                node_width = max(DEFAULT_NODE_WIDTH,
                                 max_in_width + max_out_width + 2 * self.NODE_PADDING + 2 * content_pad)
        else: # Normal node
            node_width = max(DEFAULT_NODE_WIDTH,
                             max_in_width + max_out_width + 2 * self.NODE_PADDING + 2 * content_pad)
        
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
    
        y_in_final, y_out_final = self._layout_individual_ports(node, node_width, y_current)
    
        # Calculate the height based on the maximum extent of ports (bulk areas
        # are now interleaved above their paired ports, so their height is
        # already included in y_in_final / y_out_final).
        max_y_ports = 0
        if node.input_ports or node.output_ports:
            max_y_ports = max(y_in_final, y_out_final) - self.NODE_VMARGIN # Remove last margin
        else: # No ports
            max_y_ports = y_current
    
        content_bottom_y = max_y_ports
    
        # If there's no content below the title, ensure a minimum content height.
        has_bulk_areas = bool(node.input_bulk_areas or node.output_bulk_areas)
        if not (node.input_ports or node.output_ports or has_bulk_areas):
            # Only title is visible, or node is empty after title
            final_node_height = title_height + self.NODE_PADDING # Minimal padding below title
        else:
            final_node_height = content_bottom_y + self.NODE_PADDING + constants.NODE_CONTENT_PADDING

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
        for bulk in node.input_bulk_areas:
            if bulk.isVisible():
                bulk.hide()
        for bulk in node.output_bulk_areas:
            if bulk.isVisible():
                bulk.hide()

    def _show_all_ports_and_bulk_areas(self, node: 'NodeItem') -> None:
        """
        Shows all port items and bulk area items for the given node.

        Args:
            node: The NodeItem to update
        """
        for port in list(node.input_ports.values()) + list(node.output_ports.values()):
            if not port.isVisible():
                port.show()
        for bulk in node.input_bulk_areas:
            if not bulk.isVisible():
                bulk.show()
        for bulk in node.output_bulk_areas:
            if not bulk.isVisible():
                bulk.show()

    def _layout_individual_ports(self, node: 'NodeItem', current_node_width: float,
                                 y_start_ports: float) -> Tuple[float, float]:
        """Positions port items with interleaved per-pair bulk areas above their stereo pairs.

        Bulk areas are placed directly above their paired ports.  Unpaired
        ports receive no bulk area.  The layout walks ports in visual order
        (audio first, then MIDI, each naturally sorted); when the first port
        of a detected stereo pair is encountered, its BulkAreaItem is placed
        at the current y-offset, then both paired ports follow.

        Additionally:
        - Each bulk group's bounding rect (header + 2 ports) is recorded on
          the node for visual enclosure rendering in ``NodeItem.paint()``.
        - Extra vertical gap is inserted at bulk↔non-bulk transitions (both
          directions) but not between consecutive bulk groups.

        Args:
            node: The NodeItem to update
            current_node_width: Current width of the node
            y_start_ports: Y-coordinate to start placing ports

        Returns:
            Tuple[float, float]: Final y-offsets for input and output ports
        """
        from .node_item import natural_sort_key

        # Pre-calculate all port widths so bulk areas can reference their
        # paired ports' widths even before those ports are positioned.
        for port_item in node.input_ports.values():
            port_item.calculated_width = port_item._calculate_required_width()
        for port_item in node.output_ports.values():
            port_item.calculated_width = port_item._calculate_required_width()

        # Separate and sort audio ports first, then MIDI ports
        input_audio_ports = sorted(
            [p for p in node.input_ports.values() if not p.port_obj.is_midi],
            key=natural_sort_key)
        input_midi_ports = sorted(
            [p for p in node.input_ports.values() if p.port_obj.is_midi],
            key=natural_sort_key)
        output_audio_ports = sorted(
            [p for p in node.output_ports.values() if not p.port_obj.is_midi],
            key=natural_sort_key)
        output_midi_ports = sorted(
            [p for p in node.output_ports.values() if p.port_obj.is_midi],
            key=natural_sort_key)

        pad = self.NODE_BULK_AREA_HPADDING
        bulk_h = self.NODE_BULK_PAIR_AREA_HEIGHT
        sep_gap = constants.NODE_BULK_SEPARATOR_GAP
        content_pad = constants.NODE_CONTENT_PADDING  # Inset to keep content clear of node border
    
        # Will collect QRectF for each bulk group (input + output sides)
        bulk_group_rects: list[QRectF] = []
    
        # --- Input side ---
        placed_in_bulks: set[int] = set() # ids of already-placed bulk areas
        y_in = y_start_ports
        prev_was_bulked_in = False # whether previous port belonged to any bulk pair
        all_input_ports = input_audio_ports + input_midi_ports
        for port_item in all_input_ports:
            bulk_area = node._port_to_bulk_area.get(port_item.port_name)
            is_bulked = bulk_area is not None
    
            # Detect bulk↔non-bulk transitions for extra gap
            if prev_was_bulked_in and not is_bulked:
                y_in += sep_gap
            elif not prev_was_bulked_in and is_bulked and port_item != all_input_ports[0]:
                y_in += sep_gap
    
            if bulk_area is not None and id(bulk_area) not in placed_in_bulks:
                # Record start of this bulk group
                bulk_group_y_start = y_in
    
                # Place bulk area above this stereo pair
                paired_widths = [p.calculated_width for p in bulk_area.paired_ports]
                bulk_area._bounding_rect.setWidth(max(max(paired_widths), 1.0))
                bulk_area.setPos(content_pad, y_in)
                y_in += bulk_h + self.NODE_VMARGIN
                placed_in_bulks.add(id(bulk_area))
    
                # Place both paired ports
                for paired_port in bulk_area.paired_ports:
                    paired_port.setPos(content_pad, y_in)
                    paired_port._bounding_rect = QRectF(
                        0, 0, paired_port.calculated_width, self.PORT_HEIGHT)
                    y_in += self.PORT_HEIGHT + self.NODE_VMARGIN
    
                # Record the bulk group rect (from header top to bottom of last port)
                group_width = max(paired_widths)
                group_height = y_in - bulk_group_y_start - self.NODE_VMARGIN
                bulk_group_rects.append(QRectF(content_pad, bulk_group_y_start, group_width, group_height))
            elif bulk_area is None:
                # Non-bulked port — position normally
                port_item.setPos(content_pad, y_in)
                port_item._bounding_rect = QRectF(
                    0, 0, port_item.calculated_width, self.PORT_HEIGHT)
                y_in += self.PORT_HEIGHT + self.NODE_VMARGIN
            # else: port is part of a bulk pair already placed — skip (already positioned above)
    
            prev_was_bulked_in = is_bulked
    
        # --- Output side ---
        placed_out_bulks: set[int] = set()
        y_out = y_start_ports
        prev_was_bulked_out = False
        all_output_ports = output_audio_ports + output_midi_ports
        for port_item in all_output_ports:
            bulk_area = node._port_to_bulk_area.get(port_item.port_name)
            is_bulked = bulk_area is not None
    
            # Detect bulk↔non-bulk transitions for extra gap
            if prev_was_bulked_out and not is_bulked:
                y_out += sep_gap
            elif not prev_was_bulked_out and is_bulked and port_item != all_output_ports[0]:
                y_out += sep_gap
    
            if bulk_area is not None and id(bulk_area) not in placed_out_bulks:
                # Record start of this bulk group
                bulk_group_y_start = y_out
    
                # Place bulk area above this stereo pair (right-aligned)
                paired_widths = [p.calculated_width for p in bulk_area.paired_ports]
                bulk_area._bounding_rect.setWidth(max(max(paired_widths), 1.0))
                out_x = current_node_width - max(paired_widths) - content_pad
                if node.is_split_part and node.input_ports:
                    out_x = content_pad
                bulk_area.setPos(out_x, y_out)
                y_out += bulk_h + self.NODE_VMARGIN
                placed_out_bulks.add(id(bulk_area))
    
                # Place both paired ports
                for paired_port in bulk_area.paired_ports:
                    x_pos = current_node_width - paired_port.calculated_width - content_pad
                    if node.is_split_part and node.input_ports:
                        x_pos = content_pad
                    paired_port.setPos(x_pos, y_out)
                    paired_port._bounding_rect = QRectF(
                        0, 0, paired_port.calculated_width, self.PORT_HEIGHT)
                    y_out += self.PORT_HEIGHT + self.NODE_VMARGIN
    
                # Record the bulk group rect (right-aligned)
                group_width = max(paired_widths)
                group_height = y_out - bulk_group_y_start - self.NODE_VMARGIN
                group_x = current_node_width - group_width - content_pad
                if node.is_split_part and node.input_ports:
                    group_x = content_pad
                bulk_group_rects.append(QRectF(group_x, bulk_group_y_start, group_width, group_height))
            elif bulk_area is None:
                # Non-bulked port — position normally
                x_pos = current_node_width - port_item.calculated_width - content_pad
                if node.is_split_part and node.input_ports:
                    x_pos = content_pad
                port_item.setPos(x_pos, y_out)
                port_item._bounding_rect = QRectF(
                    0, 0, port_item.calculated_width, self.PORT_HEIGHT)
                y_out += self.PORT_HEIGHT + self.NODE_VMARGIN
            # else: port is part of a bulk pair already placed — skip
    
            prev_was_bulked_out = is_bulked

        # Store the computed bulk group rects on the node for painting
        node._bulk_group_rects = bulk_group_rects

        return y_in, y_out
    
    def untangle_graph(self, max_nodes_per_row: int = 6) -> None:
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
        from cable_core.layout_strategies.untangle_strategy import UntangleStrategy
        try:
            strategy = UntangleStrategy()
            strategy.apply(self, self.scene, max_nodes_per_row=max_nodes_per_row)
        except Exception as e:
            logger.error("Error in untangle_graph strategy: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())

    def untangle_graph_auto(self, auto_split: bool = True) -> bool:
        """Auto-layout using Graphviz dot engine to minimize connection crossings.

        Delegates to AutoLayoutManager which handles splitting decisions,
        Graphviz graph construction, layout computation, and position application.

        Args:
            auto_split: If True, automatically split/unsplit nodes for optimal
                layout. If False, preserve current split state.

        Returns:
            True on success, False if graphviz is unavailable or layout fails.
        """
        from cable_core.layout_strategies.auto_strategy import AutoLayoutStrategy
        strategy = AutoLayoutStrategy()
        return strategy.apply(self, self.scene, auto_split=auto_split)

    def untangle_graph_by_io(self) -> None:
        """
        Automatically organizes the graph nodes into columns, separating Audio/Mixed and MIDI nodes.
        
        Order of columns (groups):
        1. Connected Audio/Mixed Outputs
        2. Connected Audio/Mixed Inputs
        3. Unconnected Audio/Mixed Outputs
        4. Unconnected Audio/Mixed Inputs
        5. Connected MIDI Outputs
        6. Connected MIDI Inputs
        7. Unconnected MIDI Outputs
        8. Unconnected MIDI Inputs
        """
        from cable_core.layout_strategies.io_strategy import IOLayoutStrategy
        try:
            strategy = IOLayoutStrategy()
            strategy.apply(self, self.scene)
        except Exception as e:
            logger.error("Error in untangle_graph_by_io strategy: %s", e)
            import traceback
            logger.error("Traceback: %s", traceback.format_exc())
    
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
                   node_positions: list, placed_nodes: set, start_x: float = 50.0) -> tuple[float, float, float]:
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
        
        # Find non-overlapping position using linear search
        attempt_count = 0
        original_x_attempt, original_y_attempt = x, y
        new_x, new_y = x, y

        while self._position_causes_overlap(node, new_x, new_y, node_positions) and attempt_count < 10:
            new_x += self.min_horizontal_spacing
            attempt_count += 1
            
            if attempt_count >= 5:
                new_x = original_x_attempt
                new_y += self.min_vertical_spacing
        
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
        node_positions.append((node, node_rect))
        
        # Calculate next position
        if len(row_nodes) >= max_nodes_per_row:
            # Move to next row
            next_x = start_x  # Start of row
            next_y = node_rect[3] + self.min_vertical_spacing
            next_row_height = 0
            row_nodes.clear()
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
            current_client_name = getattr(current_node, 'client_name', '')
            is_current_input = (origin.split_input_node == current_node) or \
                             (current_client_name and
                              constants.SPLIT_INPUT_SUFFIX in current_client_name)
            
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
                    (getattr(node, 'client_name', '') == sibling_to_place.client_name)
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

    # --- Overlap Detection Helpers ---

    def get_scene_node_positions(self, exclude_node: Optional['NodeItem'] = None) -> list:
        """
        Get current positions of all nodes in the scene for overlap checking.
        
        Args:
            exclude_node: Optional node to exclude from the list (usually the one being moved)
            
        Returns:
            List of tuples: (node, (x1, y1, x2, y2))
        """
        positions = []
        if not self.scene or getattr(self.scene, 'nodes', None) is None:
            return positions
            
        # We need to import NodeItem here to avoid circular imports if possible, 
        # or rely on the fact that self.scene.nodes contains NodeItems.
        # The type hint uses string forward reference.
        
        for node in self.scene.nodes.values():
            if node == exclude_node:
                continue

            # Skip hidden split origins — their visible split parts are collected below
            if node.is_split_origin and not node.isVisible():
                # Collect the visible split parts instead
                for part in (node.split_input_node, node.split_output_node):
                    if part and part != exclude_node and part.isVisible():
                        pos = part.scenePos()
                        width, height = self._get_node_size(part)
                        positions.append((part, (pos.x(), pos.y(), pos.x() + width, pos.y() + height)))
                continue
            
            # Use actual scene position
            pos = node.scenePos()
            
            # _get_node_size returns size including padding
            width, height = self._get_node_size(node)
            
            rect = (pos.x(), pos.y(), pos.x() + width, pos.y() + height)
            positions.append((node, rect))
            
        return positions

    def find_non_overlapping_position(self, node: 'NodeItem', x: float, y: float, exclude_sibling: Optional['NodeItem'] = None) -> Tuple[float, float]:
        """
        Find a position for the node that doesn't overlap with existing nodes in the scene.
        This is a public wrapper around _find_non_overlapping_position that gathers current scene positions.
        
        Args:
            node: The node to place
            x: Desired X coordinate
            y: Desired Y coordinate
            exclude_sibling: Optional node to exclude from overlap checking (e.g., the other part of a split node)
            
        Returns:
            Tuple[float, float]: The non-overlapping (x, y) coordinates
        """
        node_positions = self.get_scene_node_positions(exclude_node=node)
        
        # If exclude_sibling is provided, also exclude it from overlap checking
        if exclude_sibling:
            node_positions = [(n, r) for n, r in node_positions if n != exclude_sibling]
        
        return self._find_non_overlapping_position(node, x, y, node_positions)

    def get_overlapping_nodes(self, node: 'NodeItem', x: float, y: float) -> list['NodeItem']:
        """
        Find all nodes that overlap with the given node at position (x, y).
        
        Args:
            node: The node to check for overlaps (the aggressor)
            x: The x coordinate of the node
            y: The y coordinate of the node
            
        Returns:
            List of NodeItem instances that overlap
        """
        overlapping_nodes = []
        node_positions = self.get_scene_node_positions(exclude_node=node)
        
        node_width, node_height = self._get_node_size(node)
        node_rect = (x, y, x + node_width, y + node_height)
        
        for pos_node, pos_rect in node_positions:
            if (node_rect[0] < pos_rect[2] and node_rect[2] > pos_rect[0] and
                node_rect[1] < pos_rect[3] and node_rect[3] > pos_rect[1]):
                overlapping_nodes.append(pos_node)
                
        return overlapping_nodes

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
        """
        Find a position for the node that doesn't overlap with existing nodes.
        Uses a spiral search pattern to find the nearest available spot.
        """
        if not self._position_causes_overlap(node, x, y, node_positions):
            return x, y

        # Spiral search parameters
        step_x = self.min_horizontal_spacing
        step_y = self.min_vertical_spacing
        max_steps = 500  # Increased to handle small spacing/large nodes
        
        # Directions: Right, Down, Left, Up
        directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        
        current_x, current_y = x, y
        steps_in_leg = 1
        direction_idx = 0
        
        total_steps = 0
        while total_steps < max_steps * 4: # Heuristic limit
            for _ in range(2): # Change leg length every 2 directions
                dx, dy = directions[direction_idx]
                for _ in range(steps_in_leg):
                    current_x += dx * step_x
                    current_y += dy * step_y
                    
                    if not self._position_causes_overlap(node, current_x, current_y, node_positions):
                        return current_x, current_y
                        
                direction_idx = (direction_idx + 1) % 4
            steps_in_leg += 1
            total_steps += 1
            
        # Fallback if spiral fails (should be rare with high max_steps)
        return x + step_x * 5, y + step_y * 5

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
            if not current_node or getattr(self.scene, 'connections', None) is None:
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
                current_client_name = getattr(current_node, 'client_name', '')
                is_input_part = (current_node == origin.split_input_node) or \
                              (current_client_name and
                               constants.SPLIT_INPUT_SUFFIX in current_client_name)
                
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
            current_client_name = getattr(current_node, 'client_name', '')
            is_current_input = (origin.split_input_node == current_node) or \
                             (current_client_name and
                              constants.SPLIT_INPUT_SUFFIX in current_client_name)

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
                    (getattr(node, 'client_name', '') == sibling_to_place.client_name)
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
                placed_nodes=placed_nodes,
                start_x=start_x
            )
