from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node_item import NodeItem
    # ConfigManager will be imported locally in methods where needed to avoid circularity if NodeItem also imports it.

class NodeFoldHandler:
    """Handles folding and unfolding logic for a NodeItem."""

    def __init__(self, node_item: NodeItem):
        """
        Initializes the fold handler.
        Args:
            node_item: The NodeItem instance this handler is associated with.
        """
        self.node_item = node_item
        # Fold state attributes (is_folded, input_part_folded, output_part_folded)
        # are stored on the node_item itself and manipulated by this handler.

    def toggle_main_fold_state(self):
        """Toggles the folded state of a non-split, non-part node."""
        ni = self.node_item
        if ni.is_split_origin or ni.is_split_part:
            # This action is only for regular, unsplit nodes.
            # Split parts use toggle_input_part_fold or toggle_output_part_fold.
            return

        ni.is_folded = not ni.is_folded
        self._after_fold_change_for_node(ni)
        self._save_state_for_node(ni)

    def toggle_input_part_fold(self, fold_state: bool | None = None):
        """
        Toggles or sets the folded state of an input split part.
        This method is called on the fold_handler of the input part NodeItem.
        """
        ni = self.node_item # This ni is the input part itself
        if not ni.is_split_part or \
           not (ni.input_ports and not ni.output_ports):
            # Ensure this is actually an input part
            return

        if fold_state is None:
            ni.input_part_folded = not ni.input_part_folded
        else:
            ni.input_part_folded = bool(fold_state)
        
        self._after_fold_change_for_node(ni, is_input_part=True)
        # Saving state is triggered on the origin node for parts
        self._save_state_for_node(ni, is_part=True)

    def toggle_output_part_fold(self, fold_state: bool | None = None):
        """
        Toggles or sets the folded state of an output split part.
        This method is called on the fold_handler of the output part NodeItem.
        """
        ni = self.node_item # This ni is the output part itself
        if not ni.is_split_part or \
           not (ni.output_ports and not ni.input_ports):
            # Ensure this is actually an output part
            return

        if fold_state is None:
            ni.output_part_folded = not ni.output_part_folded
        else:
            ni.output_part_folded = bool(fold_state)

        self._after_fold_change_for_node(ni, is_output_part=True)
        # Saving state is triggered on the origin node for parts
        self._save_state_for_node(ni, is_part=True)

    def _after_fold_change_for_node(self, node: NodeItem, is_input_part: bool = False, is_output_part: bool = False):
        """
        Common actions after a fold state changes for the given node.
        Args:
            node: The NodeItem whose fold state changed (could be main or a part).
            is_input_part: True if 'node' is an input split part.
            is_output_part: True if 'node' is an output split part.
        """
        node.layout_ports() # This node (part or main) recalculates its layout
        node.update()       # Request repaint for this node

        # Determine if the node/part was just unfolded to update connections
        just_unfolded = False
        if is_input_part:
            just_unfolded = not node.input_part_folded
        elif is_output_part:
            just_unfolded = not node.output_part_folded
        else: # Main, non-split node
            just_unfolded = not node.is_folded
        
        if just_unfolded:
            # Collect ports whose connections need updating
            ports_to_update = []
            if is_input_part: # 'node' is an input part
                ports_to_update.extend(node.input_ports.values())
            elif is_output_part: # 'node' is an output part
                ports_to_update.extend(node.output_ports.values())
            else: # 'node' is a main, unsplit node
                ports_to_update.extend(node.input_ports.values())
                ports_to_update.extend(node.output_ports.values())
            
            for port_item in ports_to_update:
                if port_item: # Ensure port_item exists
                    for conn in port_item.connections:
                        conn.update_path()

    def _save_state_for_node(self, node: NodeItem, is_part: bool = False):
        """
        Saves the state of the relevant node (origin if 'node' is a part).
        Args:
            node: The NodeItem that underwent a fold change.
            is_part: True if 'node' is a split part.
        """
        node_to_trigger_save_on = node
        if is_part and node.split_origin_node:
            node_to_trigger_save_on = node.split_origin_node
        
        if node_to_trigger_save_on.scene() and \
           hasattr(node_to_trigger_save_on.scene(), 'request_specific_node_save'):
            # The scene's method will get all relevant state from node_to_trigger_save_on
            node_to_trigger_save_on.scene().request_specific_node_save(node_to_trigger_save_on)

    def apply_fold_config(self, config: dict, is_currently_split_origin: bool, is_currently_split_part: bool):
        """
        Applies fold state from a configuration dictionary.
        This method is called by NodeItem.apply_configuration.
        Args:
            config: The configuration dictionary for the node.
            is_currently_split_origin: True if self.node_item is currently a split origin.
            is_currently_split_part: True if self.node_item is currently a split part.
        """
        # Local import to avoid potential early import issues if NodeItem also imports it.
        from .config_utils import ConfigManager

        ni = self.node_item

        if is_currently_split_origin:
            # This handler is on the ORIGIN node. The config applies to its PARTS.
            # The origin node itself doesn't have a direct 'is_folded' state when split.
            # Its parts (split_input_node, split_output_node) will have their fold states applied.
            if ni.split_input_node:
                # Default to current part's state if key missing (current state might be from inheritance in _split_node)
                loaded_input_folded = config.get(ConfigManager.INPUT_PART_FOLDED_KEY, ni.split_input_node.input_part_folded)
                if ni.split_input_node.input_part_folded != loaded_input_folded:
                    ni.split_input_node.input_part_folded = loaded_input_folded
                    ni.split_input_node.layout_ports() # The part's layout uses its new fold state

            if ni.split_output_node:
                loaded_output_folded = config.get(ConfigManager.OUTPUT_PART_FOLDED_KEY, ni.split_output_node.output_part_folded)
                if ni.split_output_node.output_part_folded != loaded_output_folded:
                    ni.split_output_node.output_part_folded = loaded_output_folded
                    ni.split_output_node.layout_ports()

        elif is_currently_split_part:
            # This handler is on a SPLIT PART. Apply its own fold state from the config.
            # The config passed here is the main config for the original node.
            is_input_part_type = bool(ni.input_ports and not ni.output_ports)
            is_output_part_type = bool(ni.output_ports and not ni.input_ports)

            if is_input_part_type:
                current_fold_state = ni.input_part_folded
                config_key = ConfigManager.INPUT_PART_FOLDED_KEY
                loaded_fold_state = config.get(config_key, current_fold_state)
                if current_fold_state != loaded_fold_state:
                    ni.input_part_folded = loaded_fold_state
                    ni.layout_ports() # Update layout of this part
            elif is_output_part_type:
                current_fold_state = ni.output_part_folded
                config_key = ConfigManager.OUTPUT_PART_FOLDED_KEY
                loaded_fold_state = config.get(config_key, current_fold_state)
                if current_fold_state != loaded_fold_state:
                    ni.output_part_folded = loaded_fold_state
                    ni.layout_ports() # Update layout of this part
        
        else: # This handler is on a NORMAL, UNSPLIT node
            # If IS_FOLDED_KEY is present in config, use its value.
            # ni.is_folded might have been set to False by split_handler._unsplit_node if it just ran.
            if ConfigManager.IS_FOLDED_KEY in config: # Check presence of key
                is_folded_from_config = config.get(ConfigManager.IS_FOLDED_KEY) # Get value
                if ni.is_folded != is_folded_from_config:
                    ni.is_folded = is_folded_from_config
                    ni.layout_ports() # Update layout of this node
            # If key not in config, ni.is_folded (e.g., False if just unsplit) is maintained.
            # No explicit layout_ports call here if state doesn't change, as NodeItem.apply_configuration
            # will likely call it at the end anyway. Or, if it changed, it's called above.
            
        # After applying config, ensure state is saved
        self._save_state_for_node(ni)