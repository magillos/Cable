"""
Handler for splitting and restoring JACK client nodes into separate input/output nodes.
"""
from __future__ import annotations
import logging
import traceback
from typing import TYPE_CHECKING, Dict, Any, Optional, List

from PyQt6.QtCore import QPointF

from . import constants

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .node_item import NodeItem
    from .connection_item import ConnectionItem
    from .config_utils import GraphConfigManager
    # GraphJackHandler is part of jack_handler on NodeItem, no direct import needed here.
    # GuiScene is accessed via node_item.scene()

class NodeSplitHandler:
    """Handles splitting and unsplitting logic for a NodeItem."""

    def __init__(self, node_item: NodeItem) -> None:
        """
        Initializes the split handler.
        Args:
            node_item: The NodeItem instance this handler is associated with.
        """
        self.node_item = node_item
        # Split-related attributes (is_split_origin, is_split_part, etc.)
        # are stored on the node_item itself and manipulated by this handler.

    def split_node(self, save_state: bool = True) -> None:
        """
        Visually splits the associated node_item into two parts: one for inputs, one for outputs.
        Args:
            save_state (bool): If True, saves the node states after splitting.
        """
        ni = self.node_item
        # print(f"SplitHandler: Splitting node: {ni.client_name}") # Debug
        ni._internal_state_change_in_progress = True
        
        scene = ni.scene()
        if not scene:
            logger.error("NodeItem cannot access scene for splitting.")
            ni._internal_state_change_in_progress = False
            return

        if not ni.jack_handler or not ni.jack_handler.jack_client:
            logger.error(f"JACK handler or client not available for splitting {ni.client_name}.")
            ni._internal_state_change_in_progress = False
            return

        if ni.is_split_origin or ni.is_split_part:
            logger.warning(f"Node {ni.client_name} is already split or is a split part.")
            ni._internal_state_change_in_progress = False
            return

        original_pos = ni.scenePos()
        original_client_name = ni.client_name # Actual JACK client name

        # 1. Get original port data (name -> jack.Port object)
        input_ports_data = {}
        output_ports_data = {}
        all_original_port_items = list(ni.input_ports.values()) + list(ni.output_ports.values())
        
        for port_item in all_original_port_items:
            port_name = port_item.port_name
            # Use the jack_handler from the node_item
            port_obj = ni.jack_handler.get_port_by_name(port_name)
            if port_obj:
                if port_obj.is_input:
                    input_ports_data[port_name] = port_obj
                else:
                    output_ports_data[port_name] = port_obj
            else:
                logger.warning(f"Could not get port object for {port_name} during split.")

        if not input_ports_data or not output_ports_data:
            logger.warning(f"Node {ni.client_name} cannot be split: requires both input and output ports.")
            ni._internal_state_change_in_progress = False
            return

        # Local import for NodeItem to create parts
        from .node_item import NodeItem as NodeItemClass # Alias to avoid confusion with self.node_item
        
        # 2. Create new NodeItems for visual parts
        input_node_display_name = f"{original_client_name}{constants.SPLIT_INPUT_SUFFIX}"
        output_node_display_name = f"{original_client_name}{constants.SPLIT_OUTPUT_SUFFIX}"

        if not ni.config_manager:
            logger.error("self.node_item.config_manager is None. Cannot create split parts.")
            ni._internal_state_change_in_progress = False
            return

        input_node = NodeItemClass(input_node_display_name, ni.jack_handler, ni.config_manager, ports_to_add=input_ports_data)
        output_node = NodeItemClass(output_node_display_name, ni.jack_handler, ni.config_manager, ports_to_add=output_ports_data)

        input_node.is_split_part = True
        output_node.is_split_part = True
        input_node.original_client_name = original_client_name
        output_node.original_client_name = original_client_name
        input_node.split_origin_node = ni
        output_node.split_origin_node = ni

        scene.addItem(input_node)
        scene.addItem(output_node)

        # 4. Set DEFAULT positions for new nodes.
        input_node.layout_ports()
        output_node.layout_ports()
        
        # Force geometry update to ensure boundingRect is accurate
        input_node.prepareGeometryChange()
        input_node.update()
        output_node.prepareGeometryChange()
        output_node.update()
        
        # Set positions: input on left, output on right, both at same Y (horizontal alignment)
        # Place them close to the original node position
        input_x = original_pos.x()
        input_y = original_pos.y()
        output_x = original_pos.x() + input_node.boundingRect().width() + constants.NODE_HSPACING
        output_y = original_pos.y()
        
        # Check for overlaps and find non-overlapping positions.
        # IMPORTANT: When checking for overlaps, we need to exclude the sibling split part
        # from the check so both parts stay close together and horizontally aligned.
        if scene.layouter:
            # First, temporarily add both nodes to the scene for overlap checking
            # but don't set their final positions yet
            scene.addItem(input_node)
            scene.addItem(output_node)
            
            # Find non-overlapping position for input, excluding output from overlap check
            input_x, input_y = scene.layouter.find_non_overlapping_position(
                input_node, input_x, input_y, exclude_sibling=output_node)
            
            # Find non-overlapping position for output, excluding input from overlap check
            # Position output to the right of input (horizontal alignment)
            output_x = input_x + input_node.boundingRect().width() + constants.NODE_HSPACING
            output_y = input_y  # Keep same Y for horizontal alignment
            output_x, output_y = scene.layouter.find_non_overlapping_position(
                output_node, output_x, output_y, exclude_sibling=input_node)
            
            # After finding positions, ensure they are still horizontally aligned
            # If output was moved vertically, adjust input to match
            if output_y != input_y:
                output_y = input_y
        
        input_node.setPos(QPointF(input_x, input_y))
        output_node.setPos(QPointF(output_x, output_y))
        
        # Defer push-away check until after nodes are fully laid out
        # This is important for complex nodes with many ports
        if hasattr(scene, '_apply_push_away_for_node'):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: scene._apply_push_away_for_node(input_node))
            QTimer.singleShot(0, lambda: scene._apply_push_away_for_node(output_node))
        
        # 5. Mark original node as split, store references, and HIDE it
        ni.is_split_origin = True
        ni.split_input_node = input_node
        ni.split_output_node = output_node

        # Initialize fold state for split parts
        # Split parts start unfolded by default, regardless of original node state
        input_node.input_part_folded = False
        output_node.output_part_folded = False
        
        # If the original node was folded, we could inherit that state, but it's better
        # to start unfolded so users can see the ports after splitting
        if ni.is_folded:
            ni.is_folded = False # Origin itself is not "folded" in the same way

        input_node.layout_ports() # Update layout for potential fold
        output_node.layout_ports()

        ni.hide()

        # 6. Transfer visual connections
        # Local import for ConnectionItem
        from .connection_item import ConnectionItem

        unique_connections_to_transfer = set()
        for port_item in all_original_port_items:
            for conn in port_item.connections:
                unique_connections_to_transfer.add(conn)

        for conn_item in unique_connections_to_transfer:
            if not conn_item.source_port or not conn_item.dest_port:
                continue

            old_source_port_name = conn_item.source_port.port_name
            old_dest_port_name = conn_item.dest_port.port_name
            conn_key = (old_source_port_name, old_dest_port_name)

            new_source_item = None
            new_dest_item = None

            if conn_item.source_port.parent_node == ni:
                new_source_item = output_node.output_ports.get(old_source_port_name)
            else:
                new_source_item = conn_item.source_port

            if conn_item.dest_port.parent_node == ni:
                new_dest_item = input_node.input_ports.get(old_dest_port_name)
            else:
                new_dest_item = conn_item.dest_port
            
            scene.connections.pop(conn_key, None)
            conn_item.destroy()

            if new_source_item and new_dest_item:
                try:
                    new_conn = ConnectionItem(new_source_item, new_dest_item)
                    scene.addItem(new_conn)
                    scene.connections[conn_key] = new_conn
                except Exception as e:
                    logger.error(f"Error creating new ConnectionItem for {old_source_port_name} -> {old_dest_port_name}: {e}")
                    traceback.print_exc()
            else:
                logger.warning(f"Could not find port items to recreate connection: {old_source_port_name} -> {old_dest_port_name}")

        ni.layout_ports() # Recalculate original node size (title bar)
        ni.update()

        if hasattr(scene, 'node_configs'):
            if original_client_name not in scene.node_configs:
                scene.node_configs[original_client_name] = {}
            scene.node_configs[original_client_name]['is_split'] = True
            
            # If this is a manual split (save_state=True), mark it so it won't be auto-unsplit
            if save_state:
                scene.node_configs[original_client_name]['manual_split'] = True
                
                # Also update the node's own config
                if hasattr(ni, 'config'):
                    ni.config['manual_split'] = True
        
        ni.layout_ports()
        ni.update()
        if ni.split_input_node: ni.split_input_node.layout_ports(); ni.split_input_node.update()
        if ni.split_output_node: ni.split_output_node.layout_ports(); ni.split_output_node.update()

        ni._internal_state_change_in_progress = False
        if save_state and scene and hasattr(scene, 'request_specific_node_save'):
            scene.request_specific_node_save(ni) # Save state of the original node
        # Notify listeners that node states changed
        if save_state and scene and hasattr(scene, 'node_states_changed'):
            scene.node_states_changed.emit()

    def unsplit_node(self, save_state: bool = True) -> None:
        """
        Reverses the visual split, restoring the original node_item appearance.
        Args:
            save_state (bool): If True, saves the node states after unsplitting.
        """
        ni = self.node_item
        # print(f"SplitHandler: Unsplitting node: {ni.client_name}") # Debug
        ni._internal_state_change_in_progress = True

        scene = ni.scene()
        if not scene:
            logger.error("Cannot access scene for unsplitting.")
            ni._internal_state_change_in_progress = False
            return
        if not ni.is_split_origin or not ni.split_input_node or not ni.split_output_node:
            logger.error(f"Node {ni.client_name} is not in a valid split state to unsplit.")
            ni._internal_state_change_in_progress = False
            return

        input_part = ni.split_input_node
        output_part = ni.split_output_node

        # Determine the fold state of the unsplit node
        ni.is_folded = input_part.input_part_folded and output_part.output_part_folded

        # IMPORTANT: When unsplitting, we need to make both parts visible in the node_visibility_manager
        # Check if scene has node_visibility_manager
        if hasattr(scene, 'node_visibility_manager') and scene.node_visibility_manager:
            # Determine if this is a MIDI client
            is_midi = False
            for port_name in list(ni.input_ports.keys()) + list(ni.output_ports.keys()):
                port_obj = ni.jack_handler.get_port_by_name(port_name)
                if port_obj and hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                    is_midi = True
                    break
            
            # Update visibility settings - make both input and output visible
            client_name = ni.client_name
            
            if is_midi:
                scene.node_visibility_manager.midi_input_visibility[client_name] = True
                scene.node_visibility_manager.midi_output_visibility[client_name] = True
            else:
                scene.node_visibility_manager.audio_input_visibility[client_name] = True
                scene.node_visibility_manager.audio_output_visibility[client_name] = True
            
            # Save the updated visibility settings to the config file
            scene.node_visibility_manager.save_visibility_settings()
            
            logger.info(f"Restored visibility for both input and output of node {client_name}")

        # Transfer visual connections back
        # Local import for ConnectionItem
        from .connection_item import ConnectionItem
        
        unique_connections_to_transfer = set()
        for port_item in list(input_part.input_ports.values()):
            for conn in port_item.connections:
                unique_connections_to_transfer.add(conn)
        for port_item in list(output_part.output_ports.values()):
            for conn in port_item.connections:
                unique_connections_to_transfer.add(conn)

        for conn_item in unique_connections_to_transfer:
            if not conn_item.source_port or not conn_item.dest_port:
                continue

            old_source_port_name = conn_item.source_port.port_name
            old_dest_port_name = conn_item.dest_port.port_name
            conn_key = (old_source_port_name, old_dest_port_name)

            new_source_item = None
            new_dest_item = None

            if conn_item.source_port.parent_node == output_part:
                new_source_item = ni.output_ports.get(old_source_port_name)
            else:
                new_source_item = conn_item.source_port

            if conn_item.dest_port.parent_node == input_part:
                new_dest_item = ni.input_ports.get(old_dest_port_name)
            else:
                new_dest_item = conn_item.dest_port

            scene.connections.pop(conn_key, None)
            conn_item.destroy()

            if new_source_item and new_dest_item:
                try:
                    new_conn = ConnectionItem(new_source_item, new_dest_item)
                    scene.addItem(new_conn)
                    scene.connections[conn_key] = new_conn
                except Exception as e:
                    logger.error(f"Error creating new ConnectionItem for {old_source_port_name} -> {old_dest_port_name}: {e}")
                    traceback.print_exc()
            else:
                logger.warning(f"Could not find original port items to recreate connection: {old_source_port_name} -> {old_dest_port_name}")

        scene.removeItem(input_part)
        scene.removeItem(output_part)

        ni.is_split_origin = False
        ni.split_input_node = None
        ni.split_output_node = None
        # original_client_name remains on ni, it's not reset by unsplit.
        # is_split_part is on the parts, not ni.

        # Make sure all ports are visible
        for port_item in ni.input_ports.values(): port_item.show()
        for port_item in ni.output_ports.values(): port_item.show()
        if ni.input_area_item: ni.input_area_item.show()
        if ni.output_area_item: ni.output_area_item.show()

        ni.show()
        ni.layout_ports()
        ni.update()

        # Update node configs
        if hasattr(scene, 'node_configs') and ni.client_name in scene.node_configs:
            scene.node_configs[ni.client_name]['is_split'] = False
            
            # If this is a manual unsplit (save_state=True), clear the manual_split flag
            if save_state and 'manual_split' in scene.node_configs[ni.client_name]:
                scene.node_configs[ni.client_name]['manual_split'] = False
                
                # Also update the node's own config
                if hasattr(ni, 'config'):
                    ni.config['manual_split'] = False
        
        # Clean up and restore node state
        ni.layout_ports()
        ni.update()
        
        ni._internal_state_change_in_progress = False
        if save_state and scene and hasattr(scene, 'request_specific_node_save'):
            scene.request_specific_node_save(ni)
        # Notify listeners that node states changed
        if save_state and scene and hasattr(scene, 'node_states_changed'):
            scene.node_states_changed.emit()

    def apply_split_config(self, config: Dict[str, Any]) -> None:
        """
        Applies split state from a configuration dictionary.
        This method is called by NodeItem.apply_configuration.
        Args:
            config: The configuration dictionary for the node.
        """
        ni = self.node_item
        is_split_in_config = config.get("is_split", False)

        # Apply split/unsplit if current state differs from config
        if is_split_in_config and not ni.is_split_origin:
            # print(f"SplitHandler: Applying split for {ni.client_name} based on config.") # Debug
            self.split_node(save_state=False) # save_state=False as apply_config handles overall saving
        elif not is_split_in_config and ni.is_split_origin:
            # print(f"SplitHandler: Applying unsplit for {ni.client_name} based on config.") # Debug
            self.unsplit_node(save_state=False)
        
        # After split/unsplit, positions of parts or the main node are applied
        # by NodeItem.apply_configuration itself.
        # This handler ensures the correct split state is achieved first.