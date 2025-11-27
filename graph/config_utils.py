#!/usr/bin/env python3

import os
import json
from pathlib import Path
from PyQt6.QtCore import QPointF

class ConfigManager:
    """Manages saving and loading app configuration, including node positions and split states."""

    # Define constants for special keys to avoid typos
    IS_SPLIT_KEY = "::is_split"
    SPLIT_INPUT_POS_KEY = "::split_input_pos"
    SPLIT_OUTPUT_POS_KEY = "::split_output_pos"
    GRAPH_ZOOM_LEVEL_KEY = "::graph_zoom_level" # Added for zoom level
    CURRENT_UNTANGLE_SETTING_KEY = "::current_untangle_setting" # Added for current untangle layout
    IS_FOLDED_KEY = "::is_folded" # Added for fold state
    INPUT_PART_FOLDED_KEY = "::input_part_folded"
    OUTPUT_PART_FOLDED_KEY = "::output_part_folded"
    MANUAL_SPLIT_KEY = "::manual_split" # Added for manual split flag
    IS_UNIFIED_KEY = "::is_unified"
    UNIFIED_SINK_NAME_KEY = "::unified_sink_name"
    UNIFIED_MODULE_ID_KEY = "::unified_module_id"
    UNIFIED_PORTS_TYPE_KEY = "::unified_ports_type"
    
    # New keys for split unification
    IS_INPUT_UNIFIED_KEY = "::is_input_unified"
    IS_OUTPUT_UNIFIED_KEY = "::is_output_unified"
    UNIFIED_INPUT_SINK_NAME_KEY = "::unified_input_sink_name"
    UNIFIED_OUTPUT_SINK_NAME_KEY = "::unified_output_sink_name"
    UNIFIED_INPUT_MODULE_ID_KEY = "::unified_input_module_id"
    UNIFIED_OUTPUT_MODULE_ID_KEY = "::unified_output_module_id"
 
    def __init__(self):
        self.config_dir = Path.home() / ".config" / "cable"
        self.node_positions_file = self.config_dir / "node_positions.json"
        self.graph_settings_file = self.config_dir / "graph_settings.json"  # Separate file for graph settings

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
 
    def save_node_states(self, nodes_dict, graph_zoom_level=None, current_untangle_setting=None):
        """Save node positions, split states, fold states (including parts), graph zoom level, and current untangle setting.
 
        Args:
            nodes_dict: Dict of {client_name: NodeItem} from JackGraphScene.
            graph_zoom_level (float, optional): The current zoom level of the graph view.
            current_untangle_setting (int, optional): The current untangle layout setting.
        """
        # Load existing data first to preserve old entries
        loaded_data = {}
        if self.node_positions_file.exists():
            try:
                with open(self.node_positions_file, 'r') as f:
                    loaded_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not decode JSON from {self.node_positions_file}. Starting with empty config for save.")
            except Exception as e:
                print(f"Warning: Error loading node states file {self.node_positions_file}: {e}. Starting with empty config for save.")
 
        data_to_save = loaded_data.copy() # Work with a copy of the loaded data, preserving existing entries

        saved_count = 0 # Counts nodes processed (updated or added) in this call
        split_nodes_currently = 0 # Counts split nodes processed in this call
        nodes_with_split_history = 0 # Counts nodes with split history processed in this call

        for client_name, node in nodes_dict.items():
            # Skip saving split *parts* directly, only save based on original nodes
            if node.is_split_part:
                continue

            saved_count += 1
            node_data = data_to_save.get(client_name, {})

            # 1. Save the normal position (position of the original node, even if hidden)
            pos = node.scenePos()
            node_data["pos"] = {"x": pos.x(), "y": pos.y()}

            # 2. Save the current split state
            is_currently_split = node.is_split_origin # Rely on the node's flag
            
            node_data["is_split"] = is_currently_split
            if is_currently_split:
                split_nodes_currently += 1
                
            # Save the manual split flag if it exists in the node's config
            if hasattr(node, 'config') and node.config and 'manual_split' in node.config:
                node_data[self.MANUAL_SPLIT_KEY] = node.config['manual_split']
            # If the node is split but we don't have the flag in the config, check the scene.node_configs
            elif is_currently_split and hasattr(node.scene(), 'node_configs'):
                scene_node_config = node.scene().node_configs.get(client_name, {})
                if 'manual_split' in scene_node_config:
                    node_data[self.MANUAL_SPLIT_KEY] = scene_node_config['manual_split']

            # 3. Save the last known positions of split parts IF they exist
            # These might exist even if is_split_origin is False, if it was split then unsplit
            input_part_pos = None
            output_part_pos = None

            if node.split_input_node: # Check if the reference exists
                input_part_pos = node.split_input_node.scenePos()
                node_data["split_input_pos"] = {"x": input_part_pos.x(), "y": input_part_pos.y()}

            if node.split_output_node: # Check if the reference exists
                output_part_pos = node.split_output_node.scenePos()
                node_data["split_output_pos"] = {"x": output_part_pos.x(), "y": output_part_pos.y()}

            if input_part_pos or output_part_pos:
                nodes_with_split_history += 1

            # 4. Save the current fold state
            node_data[self.IS_FOLDED_KEY] = node.is_folded # Fold state for unsplit node

            # 5. If the node is split, save fold states of its parts
            if is_currently_split:
                if node.split_input_node:
                    node_data[self.INPUT_PART_FOLDED_KEY] = node.split_input_node.input_part_folded
                if node.split_output_node:
                    node_data[self.OUTPUT_PART_FOLDED_KEY] = node.split_output_node.output_part_folded

            # 6. Save unified state (Legacy and New)
            if hasattr(node, 'is_unified') and node.is_unified:
                # Legacy support: save as generic unified if it was generic
                node_data[self.IS_UNIFIED_KEY] = True
                node_data[self.UNIFIED_SINK_NAME_KEY] = node.unified_virtual_sink_name
                node_data[self.UNIFIED_MODULE_ID_KEY] = node.unified_module_id
                node_data[self.UNIFIED_PORTS_TYPE_KEY] = node.unified_ports_type

            # New split unification state
            if hasattr(node, 'is_input_unified') and node.is_input_unified:
                node_data[self.IS_INPUT_UNIFIED_KEY] = True
                node_data[self.UNIFIED_INPUT_SINK_NAME_KEY] = node.unified_input_sink_name
                node_data[self.UNIFIED_INPUT_MODULE_ID_KEY] = node.unified_input_module_id
            
            if hasattr(node, 'is_output_unified') and node.is_output_unified:
                node_data[self.IS_OUTPUT_UNIFIED_KEY] = True
                node_data[self.UNIFIED_OUTPUT_SINK_NAME_KEY] = node.unified_output_sink_name
                node_data[self.UNIFIED_OUTPUT_MODULE_ID_KEY] = node.unified_output_module_id
 
            # Store all collected data for this client_name
            data_to_save[client_name] = node_data
 
        # Save graph zoom level at the top level of the JSON
        if graph_zoom_level is not None:
            data_to_save[self.GRAPH_ZOOM_LEVEL_KEY] = graph_zoom_level
        
        # Save current untangle setting to a separate file to maintain backward compatibility
        if current_untangle_setting is not None:
            self._save_graph_settings(current_untangle_setting)


        try:
            with open(self.node_positions_file, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            # Count total node entries in the file (excluding the zoom level key)
            total_node_entries_in_file = len([
                k for k, v in data_to_save.items()
                if k not in [self.GRAPH_ZOOM_LEVEL_KEY] and isinstance(v, dict) # Exclude only zoom key for count
            ])
            # print(f"Processed {saved_count} active node configurations ({split_nodes_currently} currently split).")
            # print(f"Total {total_node_entries_in_file} node configurations and zoom level now stored in {self.node_positions_file}")
        except Exception as e:
            print(f"Error saving node states: {e}")
 
 
    def load_node_states(self):
        """Load node positions, split states, fold states (including parts), and graph zoom level.
        
        The current untangle setting is stored in the returned config dict under the key '::current_untangle_setting'.
 
        Returns:
            tuple: A tuple containing:
                - loaded_node_config (dict): Dict of node configurations. May contain special key '::current_untangle_setting'.
                - loaded_zoom_level (float or None): The loaded graph zoom level, or None if not found.
        """
        loaded_config = {}
        loaded_zoom_level = None # Default to None
 
        if not self.node_positions_file.exists():
            print(f"No node states file found at {self.node_positions_file}")
            return loaded_config, loaded_zoom_level

        try:
            with open(self.node_positions_file, 'r') as f:
                raw_data = json.load(f)

            # New format: keys are client_names, values are dicts
            for client_name, node_data in raw_data.items():
                # Check if this key is our special zoom level key
                if client_name == self.GRAPH_ZOOM_LEVEL_KEY:
                    if isinstance(node_data, (float, int)): # Basic type check
                        loaded_zoom_level = float(node_data)
                    continue # Move to the next item

                config = {}
                if "pos" in node_data:
                    config["pos"] = QPointF(node_data["pos"]["x"], node_data["pos"]["y"])
                if "is_split" in node_data:
                    config["is_split"] = bool(node_data["is_split"])
                if "split_input_pos" in node_data:
                    config["split_input_pos"] = QPointF(node_data["split_input_pos"]["x"], node_data["split_input_pos"]["y"])
                if "split_output_pos" in node_data:
                    config["split_output_pos"] = QPointF(node_data["split_output_pos"]["x"], node_data["split_output_pos"]["y"])
                if self.IS_FOLDED_KEY in node_data: # Load fold state
                    config[self.IS_FOLDED_KEY] = bool(node_data.get(self.IS_FOLDED_KEY, False)) # Use the constant key
                if self.MANUAL_SPLIT_KEY in node_data: # Load manual split flag
                    config["manual_split"] = bool(node_data.get(self.MANUAL_SPLIT_KEY, False))
 
                # If the node is marked as split, load part fold states
                if config.get("is_split", False):
                    config[self.INPUT_PART_FOLDED_KEY] = bool(node_data.get(self.INPUT_PART_FOLDED_KEY, False))
                    config[self.OUTPUT_PART_FOLDED_KEY] = bool(node_data.get(self.OUTPUT_PART_FOLDED_KEY, False))

                # Load unified state (Legacy)
                if self.IS_UNIFIED_KEY in node_data and node_data[self.IS_UNIFIED_KEY]:
                    config['is_unified'] = True
                    config['virtual_sink_name'] = node_data.get(self.UNIFIED_SINK_NAME_KEY)
                    config['unified_module_id'] = node_data.get(self.UNIFIED_MODULE_ID_KEY)
                    config['unified_ports_type'] = node_data.get(self.UNIFIED_PORTS_TYPE_KEY)

                # Load unified state (New Split)
                if self.IS_INPUT_UNIFIED_KEY in node_data and node_data[self.IS_INPUT_UNIFIED_KEY]:
                    config['is_input_unified'] = True
                    config['unified_input_sink_name'] = node_data.get(self.UNIFIED_INPUT_SINK_NAME_KEY)
                    config['unified_input_module_id'] = node_data.get(self.UNIFIED_INPUT_MODULE_ID_KEY)

                if self.IS_OUTPUT_UNIFIED_KEY in node_data and node_data[self.IS_OUTPUT_UNIFIED_KEY]:
                    config['is_output_unified'] = True
                    config['unified_output_sink_name'] = node_data.get(self.UNIFIED_OUTPUT_SINK_NAME_KEY)
                    config['unified_output_module_id'] = node_data.get(self.UNIFIED_OUTPUT_MODULE_ID_KEY)
 
                if config: # Only add if we loaded something
                    loaded_config[client_name] = config
 
            # Load the untangle setting from separate file and store in config dict
            untangle_setting = self._load_graph_settings()
            if untangle_setting is not None:
                loaded_config[self.CURRENT_UNTANGLE_SETTING_KEY] = untangle_setting
            
            # print(f"Loaded configurations for {len(loaded_config)} nodes and zoom level {loaded_zoom_level} from {self.node_positions_file}")
            return loaded_config, loaded_zoom_level
        except Exception as e:
            print(f"Error loading node states: {e}")
            return {}, None # Return empty dict and None for zoom on error

    def _save_graph_settings(self, current_untangle_setting):
        """Save graph settings (like current untangle setting) to a separate file.
        
        Args:
            current_untangle_setting (int): The current untangle layout setting.
        """
        try:
            settings = {
                'current_untangle_setting': current_untangle_setting
            }
            with open(self.graph_settings_file, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving graph settings: {e}")
    
    def _load_graph_settings(self):
        """Load graph settings from the separate settings file.
        
        Returns:
            int or None: The current untangle setting, or None if not found.
        """
        if not self.graph_settings_file.exists():
            return None
        
        try:
            with open(self.graph_settings_file, 'r') as f:
                settings = json.load(f)
                return settings.get('current_untangle_setting')
        except Exception as e:
            print(f"Error loading graph settings: {e}")
            return None
    
    def save_node_states_as_default(self, node_states, graph_zoom_level=None):
        """Save provided node states directly to the node_positions.json file.
        This is used for saving the current layout as the default.
        
        Args:
            node_states (dict): Dict of node configurations from get_node_states().
            graph_zoom_level (float, optional): The current zoom level of the graph view.
                If None, will attempt to preserve the current zoom level from the file.
        """
        # Load existing data first to get the zoom level if not provided
        loaded_data = {}
        existing_zoom_level = None
        if self.node_positions_file.exists():
            try:
                with open(self.node_positions_file, 'r') as f:
                    loaded_data = json.load(f)
                    # Extract existing zoom level if not provided
                    if graph_zoom_level is None and self.GRAPH_ZOOM_LEVEL_KEY in loaded_data:
                        existing_zoom_level = loaded_data[self.GRAPH_ZOOM_LEVEL_KEY]
            except Exception as e:
                print(f"Warning: Error loading node states file {self.node_positions_file}: {e}. Starting with empty config.")
        
        # Create the new data to save
        data_to_save = {}
        
        # Add the node states
        for client_name, config in node_states.items():
            node_data = {}
            
            # Convert QPointF positions to serializable format
            if "pos" in config:
                pos = config["pos"]
                node_data["pos"] = {"x": pos.x(), "y": pos.y()}
                
            # Set split state
            if "is_split" in config:
                node_data["is_split"] = bool(config["is_split"])
                
            # Convert split positions
            if "split_input_pos" in config:
                pos = config["split_input_pos"]
                node_data["split_input_pos"] = {"x": pos.x(), "y": pos.y()}
                
            if "split_output_pos" in config:
                pos = config["split_output_pos"]
                node_data["split_output_pos"] = {"x": pos.x(), "y": pos.y()}
                
            # Copy fold states
            if self.IS_FOLDED_KEY in config:
                node_data[self.IS_FOLDED_KEY] = bool(config[self.IS_FOLDED_KEY])
                
            if self.MANUAL_SPLIT_KEY in config:
                node_data[self.MANUAL_SPLIT_KEY] = bool(config[self.MANUAL_SPLIT_KEY])
                
            # Copy part fold states if the node is split
            if config.get("is_split", False):
                if self.INPUT_PART_FOLDED_KEY in config:
                    node_data[self.INPUT_PART_FOLDED_KEY] = bool(config[self.INPUT_PART_FOLDED_KEY])
                if self.OUTPUT_PART_FOLDED_KEY in config:
                    node_data[self.OUTPUT_PART_FOLDED_KEY] = bool(config[self.OUTPUT_PART_FOLDED_KEY])
            
            # Store the node data
            data_to_save[client_name] = node_data
        
        # Add the zoom level
        if graph_zoom_level is not None:
            data_to_save[self.GRAPH_ZOOM_LEVEL_KEY] = graph_zoom_level
        elif existing_zoom_level is not None:
            data_to_save[self.GRAPH_ZOOM_LEVEL_KEY] = existing_zoom_level
            
        # Save to file
        try:
            with open(self.node_positions_file, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            print(f"Saved {len(data_to_save) - (1 if self.GRAPH_ZOOM_LEVEL_KEY in data_to_save else 0)} node configurations as default layout.")
        except Exception as e:
            print(f"Error saving node states as default: {e}")
