#!/usr/bin/env python3
"""
Graph configuration persistence — node positions, split states, and layout preferences.
"""

import os
import json
import atexit
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from PyQt6.QtCore import QPointF

import logging
logger = logging.getLogger(__name__)

class GraphConfigManager:
    """Manages saving and loading graph configuration, including node positions and split states.
    
    Uses a dirty flag pattern to minimize disk writes - changes are kept in memory
    and only written to disk on exit or explicit flush.
    
    Note: This is separate from cable_core.config.ConfigManager which handles app settings.
    """

    # Define constants for special keys to avoid typos
    IS_SPLIT_KEY = "::is_split"
    SPLIT_INPUT_POS_KEY = "::split_input_pos"
    SPLIT_OUTPUT_POS_KEY = "::split_output_pos"
    GRAPH_ZOOM_LEVEL_KEY = "::graph_zoom_level"
    CURRENT_UNTANGLE_SETTING_KEY = "::current_untangle_setting"
    IS_FOLDED_KEY = "::is_folded"
    INPUT_PART_FOLDED_KEY = "::input_part_folded"
    OUTPUT_PART_FOLDED_KEY = "::output_part_folded"
    MANUAL_SPLIT_KEY = "::manual_split"
    
    # Keys for split unification
    IS_INPUT_UNIFIED_KEY = "::is_input_unified"
    IS_OUTPUT_UNIFIED_KEY = "::is_output_unified"
    UNIFIED_INPUT_SINK_NAME_KEY = "::unified_input_sink_name"
    UNIFIED_OUTPUT_SINK_NAME_KEY = "::unified_output_sink_name"
    UNIFIED_INPUT_MODULE_ID_KEY = "::unified_input_module_id"
    UNIFIED_OUTPUT_MODULE_ID_KEY = "::unified_output_module_id"
 
    def __init__(self) -> None:
        self.config_dir = Path.home() / ".config" / "cable"
        self.node_positions_file = self.config_dir / "node_positions.json"
        self.graph_settings_file = self.config_dir / "graph_settings.json"

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Dirty flag pattern for deferred writes
        self._dirty = False
        self._cached_data = None
        self._graph_settings_dirty = False
        self._cached_graph_settings = None
        
        # Load existing data into cache
        self._load_cache()
        
        # Register flush on exit
        atexit.register(self.flush)

    def _load_cache(self) -> None:
        """Load existing data into memory cache."""
        if self.node_positions_file.exists():
            try:
                with open(self.node_positions_file, 'r') as f:
                    self._cached_data = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Warning: Could not load {self.node_positions_file}: {e}")
                self._cached_data = {}
        else:
            self._cached_data = {}
        
        if self.graph_settings_file.exists():
            try:
                with open(self.graph_settings_file, 'r') as f:
                    self._cached_graph_settings = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Warning: Could not load {self.graph_settings_file}: {e}")
                self._cached_graph_settings = {}
        else:
            self._cached_graph_settings = {}

    def flush(self) -> None:
        """Write cached data to disk if there are unsaved changes."""
        if self._dirty and self._cached_data is not None:
            try:
                with open(self.node_positions_file, 'w') as f:
                    json.dump(self._cached_data, f, indent=4)
                self._dirty = False
            except Exception as e:
                logger.error(f"Error saving node states: {e}")
        
        if self._graph_settings_dirty and self._cached_graph_settings is not None:
            try:
                with open(self.graph_settings_file, 'w') as f:
                    json.dump(self._cached_graph_settings, f, indent=4)
                self._graph_settings_dirty = False
            except Exception as e:
                logger.error(f"Error saving graph settings: {e}")
 
    def save_node_states(self, nodes_dict: Dict[str, Any], graph_zoom_level: Optional[float] = None, current_untangle_setting: Optional[int] = None) -> None:
        """Save node positions, split states, fold states (including parts), graph zoom level, and current untangle setting.
   
        Args:
            nodes_dict: Dict of {client_name: NodeItem} from JackGraphScene.
            graph_zoom_level (float, optional): The current zoom level of the graph view.
            current_untangle_setting (int, optional): The current untangle layout setting.
        """
        if self._cached_data is None:
            self._cached_data = {}

        for client_name, node in nodes_dict.items():
            # Skip saving split *parts* directly, only save based on original nodes
            if node.is_split_part:
                continue

            node_data = self._save_node_data(client_name, node)
            self._cached_data[client_name] = node_data
  
        # Save graph zoom level at the top level
        if graph_zoom_level is not None:
            self._cached_data[self.GRAPH_ZOOM_LEVEL_KEY] = graph_zoom_level
        
        # Save current untangle setting to a separate cache
        if current_untangle_setting is not None:
            self._save_graph_settings(current_untangle_setting)

        # Mark as dirty instead of writing immediately
        self._dirty = True

    def _save_node_data(self, client_name: str, node: Any) -> Dict[str, Any]:
        """Extract and return all state data for a single node.

        Args:
            client_name: The client name
            node: The NodeItem to save

        Returns:
            Dict containing all node state data
        """
        node_data = self._cached_data.get(client_name, {})

        # Save position
        pos = node.scenePos()
        node_data["pos"] = {"x": pos.x(), "y": pos.y()}

        # Save split state
        self._save_split_state(node_data, node)

        # Save fold states
        self._save_fold_states(node_data, node)

        # Save unification state
        self._save_unified_state(node_data, node)

        return node_data

    def _save_split_state(self, node_data: Dict[str, Any], node: Any) -> None:
        """Save split-related state for a node.

        Args:
            node_data: The node data dict to update
            node: The NodeItem to save state from
        """
        is_currently_split = node.is_split_origin
        node_data["is_split"] = is_currently_split

        # Save the manual split flag if it exists
        if getattr(node, 'config', None) is not None and 'manual_split' in node.config:
            node_data[self.MANUAL_SPLIT_KEY] = node.config['manual_split']
        elif is_currently_split and getattr(node.scene(), 'node_configs', None) is not None:
            scene_node_config = node.scene().node_configs.get(client_name, {})
            if 'manual_split' in scene_node_config:
                node_data[self.MANUAL_SPLIT_KEY] = scene_node_config['manual_split']

        # Save split part positions
        if node.split_input_node:
            input_part_pos = node.split_input_node.scenePos()
            node_data["split_input_pos"] = {"x": input_part_pos.x(), "y": input_part_pos.y()}

        if node.split_output_node:
            output_part_pos = node.split_output_node.scenePos()
            node_data["split_output_pos"] = {"x": output_part_pos.x(), "y": output_part_pos.y()}

    def _save_fold_states(self, node_data: Dict[str, Any], node: Any) -> None:
        """Save fold states for a node and its split parts.

        Args:
            node_data: The node data dict to update
            node: The NodeItem to save state from
        """
        node_data[self.IS_FOLDED_KEY] = node.is_folded

        # If the node is split, save fold states of its parts
        if node.is_split_origin:
            if node.split_input_node:
                node_data[self.INPUT_PART_FOLDED_KEY] = node.split_input_node.input_part_folded
            if node.split_output_node:
                node_data[self.OUTPUT_PART_FOLDED_KEY] = node.split_output_node.output_part_folded

    def _save_unified_state(self, node_data: Dict[str, Any], node: Any) -> None:
        """Save unification state for a node.

        This is authoritative for the full-save path: when a node is no longer
        unified, any previously saved unified keys are removed. Without this,
        a stale ``::is_input_unified``/``::is_output_unified`` flag could linger
        in the cache and be resurrected on the next save, causing a node to
        reappear as unified after an application restart even though the user
        had unchecked "Unify input/output ports".

        Args:
            node_data: The node data dict to update
            node: The NodeItem to save state from
        """
        if getattr(node, 'is_input_unified', False):
            node_data[self.IS_INPUT_UNIFIED_KEY] = True
            node_data[self.UNIFIED_INPUT_SINK_NAME_KEY] = node.unified_input_sink_name
            node_data[self.UNIFIED_INPUT_MODULE_ID_KEY] = node.unified_input_module_id
        else:
            node_data.pop(self.IS_INPUT_UNIFIED_KEY, None)
            node_data.pop(self.UNIFIED_INPUT_SINK_NAME_KEY, None)
            node_data.pop(self.UNIFIED_INPUT_MODULE_ID_KEY, None)

        if getattr(node, 'is_output_unified', False):
            node_data[self.IS_OUTPUT_UNIFIED_KEY] = True
            node_data[self.UNIFIED_OUTPUT_SINK_NAME_KEY] = node.unified_output_sink_name
            node_data[self.UNIFIED_OUTPUT_MODULE_ID_KEY] = node.unified_output_module_id
        else:
            node_data.pop(self.IS_OUTPUT_UNIFIED_KEY, None)
            node_data.pop(self.UNIFIED_OUTPUT_SINK_NAME_KEY, None)
            node_data.pop(self.UNIFIED_OUTPUT_MODULE_ID_KEY, None)
  
    def load_node_states(self) -> Tuple[Dict[str, Any], Optional[float]]:
        """Load node positions, split states, fold states (including parts), and graph zoom level.
        
        The current untangle setting is stored in the returned config dict under the key '::current_untangle_setting'.
  
        Returns:
            tuple: A tuple containing:
                - loaded_node_config (dict): Dict of node configurations. May contain special key '::current_untangle_setting'.
                - loaded_zoom_level (float or None): The loaded graph zoom level, or None if not found.
        """
        loaded_config = {}
        loaded_zoom_level = None

        # Use cached data if available
        raw_data = self._cached_data if self._cached_data else {}
        
        if not raw_data and not self.node_positions_file.exists():
            logger.debug(f"No node states file found at {self.node_positions_file}")
            return loaded_config, loaded_zoom_level

        try:
            # Process each node's data
            for client_name, node_data in raw_data.items():
                # Check if this key is our special zoom level key
                if client_name == self.GRAPH_ZOOM_LEVEL_KEY:
                    if isinstance(node_data, (float, int)):
                        loaded_zoom_level = float(node_data)
                    continue

                config = self._load_single_node_config(client_name, node_data)
                if config:
                    loaded_config[client_name] = config
  
            # Load the untangle setting from cache and store in config dict
            untangle_setting = self._load_graph_settings()
            if untangle_setting is not None:
                loaded_config[self.CURRENT_UNTANGLE_SETTING_KEY] = untangle_setting
            
            return loaded_config, loaded_zoom_level
        except Exception as e:
            logger.error(f"Error loading node states: {e}")
            return {}, None

    def _load_single_node_config(self, client_name: str, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """Load configuration for a single node from raw data.

        Args:
            client_name: The client name
            node_data: Raw node data from the config file

        Returns:
            Dict containing the loaded node configuration
        """
        config = {}

        # Load position
        if "pos" in node_data:
            config["pos"] = QPointF(node_data["pos"]["x"], node_data["pos"]["y"])

        # Load split state
        if "is_split" in node_data:
            config["is_split"] = bool(node_data["is_split"])

        # Load split part positions
        if "split_input_pos" in node_data:
            config["split_input_pos"] = QPointF(node_data["split_input_pos"]["x"], node_data["split_input_pos"]["y"])
        if "split_output_pos" in node_data:
            config["split_output_pos"] = QPointF(node_data["split_output_pos"]["x"], node_data["split_output_pos"]["y"])

        # Load fold states
        if self.IS_FOLDED_KEY in node_data:
            config[self.IS_FOLDED_KEY] = bool(node_data.get(self.IS_FOLDED_KEY, False))
        if self.MANUAL_SPLIT_KEY in node_data:
            config["manual_split"] = bool(node_data.get(self.MANUAL_SPLIT_KEY, False))

        # If the node is marked as split, load part fold states
        if config.get("is_split", False):
            config[self.INPUT_PART_FOLDED_KEY] = bool(node_data.get(self.INPUT_PART_FOLDED_KEY, False))
            config[self.OUTPUT_PART_FOLDED_KEY] = bool(node_data.get(self.OUTPUT_PART_FOLDED_KEY, False))

        # Load split unified state
        self._load_unified_state(config, node_data)

        return config

    def _load_unified_state(self, config: Dict[str, Any], node_data: Dict[str, Any]) -> None:
        """Load unification state from node data.

        Args:
            config: The config dict to update
            node_data: Raw node data from the config file
        """
        if self.IS_INPUT_UNIFIED_KEY in node_data and node_data[self.IS_INPUT_UNIFIED_KEY]:
            config['is_input_unified'] = True
            config['unified_input_sink_name'] = node_data.get(self.UNIFIED_INPUT_SINK_NAME_KEY)
            config['unified_input_module_id'] = node_data.get(self.UNIFIED_INPUT_MODULE_ID_KEY)

        if self.IS_OUTPUT_UNIFIED_KEY in node_data and node_data[self.IS_OUTPUT_UNIFIED_KEY]:
            config['is_output_unified'] = True
            config['unified_output_sink_name'] = node_data.get(self.UNIFIED_OUTPUT_SINK_NAME_KEY)
            config['unified_output_module_id'] = node_data.get(self.UNIFIED_OUTPUT_MODULE_ID_KEY)

    def _save_graph_settings(self, current_untangle_setting: int, keep_untangled: Optional[bool] = None) -> None:
        """Save graph settings to cache (will be written on flush).
        
        Args:
            current_untangle_setting (int): The current untangle layout setting.
            keep_untangled (bool, optional): Whether to keep the graph untangled when nodes change.
        """
        if self._cached_graph_settings is None:
            self._cached_graph_settings = {}
        self._cached_graph_settings['current_untangle_setting'] = current_untangle_setting
        if keep_untangled is not None:
            self._cached_graph_settings['keep_untangled'] = keep_untangled
        self._graph_settings_dirty = True
    
    def save_keep_untangled(self, keep_untangled: bool) -> None:
        """Save the keep_untangled setting to cache.
        
        Args:
            keep_untangled (bool): Whether to keep the graph untangled when nodes change.
        """
        if self._cached_graph_settings is None:
            self._cached_graph_settings = {}
        self._cached_graph_settings['keep_untangled'] = keep_untangled
        self._graph_settings_dirty = True
    
    def load_keep_untangled(self) -> bool:
        """Load the keep_untangled setting from cache.
        
        Returns:
            bool: True if keep_untangled is enabled, False otherwise.
        """
        if self._cached_graph_settings:
            return self._cached_graph_settings.get('keep_untangled', False)
        return False

    # --- Family-level unification state ---
    #
    # Some clients recreate themselves per stream/recording, producing a fresh
    # JACK client with a numeric rename suffix each time (e.g. "Application",
    # "Application-119", "Application-89").  Unified sinks for such clients are
    # tracked per *family base name* so that a newly appearing sibling node can
    # be auto-unified without the user toggling it again.

    _FAMILY_UNIFIED_KEY = "unified_families"

    def get_family_unified_state(self, base_name: str) -> Optional[Dict[str, Any]]:
        """Return the persisted unified state for a client family base name.

        Args:
            base_name: The client family base name (see ``client_family_base``).

        Returns:
            A dict with ``is_input_unified``/``is_output_unified`` and their
            associated sink names, or ``None`` if the family is not unified.
        """
        if not base_name or not self._cached_graph_settings:
            return None
        families = self._cached_graph_settings.get(self._FAMILY_UNIFIED_KEY)
        if not isinstance(families, dict):
            return None
        return families.get(base_name)

    def set_family_unified_state(
        self,
        base_name: str,
        is_input_unified: bool,
        is_output_unified: bool,
        unified_input_sink_name: Optional[str] = None,
        unified_output_sink_name: Optional[str] = None,
    ) -> None:
        """Persist the unified state for a client family base name.

        When neither direction is unified the family entry is removed, which
        allows a subsequent node of the same family to appear normally.
        """
        if not base_name:
            return
        if self._cached_graph_settings is None:
            self._cached_graph_settings = {}
        families = self._cached_graph_settings.get(self._FAMILY_UNIFIED_KEY)
        if not isinstance(families, dict):
            families = {}

        if not is_input_unified and not is_output_unified:
            families.pop(base_name, None)
        else:
            families[base_name] = {
                'is_input_unified': bool(is_input_unified),
                'is_output_unified': bool(is_output_unified),
                'unified_input_sink_name': unified_input_sink_name,
                'unified_output_sink_name': unified_output_sink_name,
            }

        self._cached_graph_settings[self._FAMILY_UNIFIED_KEY] = families
        self._graph_settings_dirty = True
    
    def _load_graph_settings(self) -> Optional[int]:
        """Load graph settings from cache.
        
        Returns:
            int or None: The current untangle setting, or None if not found.
        """
        if self._cached_graph_settings:
            return self._cached_graph_settings.get('current_untangle_setting')
        return None
    
    def save_node_states_as_default(self, node_states: Dict[str, Any], graph_zoom_level: Optional[float] = None) -> None:
        """Save provided node states directly to the node_positions.json file.
        This is used for saving the current layout as the default.
        
        Args:
            node_states (dict): Dict of node configurations from get_node_states().
            graph_zoom_level (float, optional): The current zoom level of the graph view.
                If None, will attempt to preserve the current zoom level from the cache.
        """
        # Get existing zoom level if not provided
        existing_zoom_level = None
        if graph_zoom_level is None and self._cached_data:
            existing_zoom_level = self._cached_data.get(self.GRAPH_ZOOM_LEVEL_KEY)
        
        data_to_save = self._serialize_node_states(node_states)
        
        # Add the zoom level
        if graph_zoom_level is not None:
            data_to_save[self.GRAPH_ZOOM_LEVEL_KEY] = graph_zoom_level
        elif existing_zoom_level is not None:
            data_to_save[self.GRAPH_ZOOM_LEVEL_KEY] = existing_zoom_level
        
        # Update cache and mark dirty
        self._cached_data = data_to_save
        self._dirty = True
        
        logger.debug(f"Queued {len(data_to_save) - (1 if self.GRAPH_ZOOM_LEVEL_KEY in data_to_save else 0)} node configurations as default layout.")

    def _serialize_node_states(self, node_states: Dict[str, Any]) -> Dict[str, Any]:
        """Convert node state configs into the serializable on-disk format."""
        data_to_save = {}

        # Add the node states
        for client_name, config in node_states.items():
            node_data = self._serialize_node_state(config)
            data_to_save[client_name] = node_data

        return data_to_save

    @staticmethod
    def _copy_point_field(config: Dict[str, Any], node_data: Dict[str, Any], key: str) -> None:
        """Serialize a QPointF-valued config field into ``{"x": .., "y": ..}``."""
        if key in config:
            pos = config[key]
            node_data[key] = {"x": pos.x(), "y": pos.y()}

    @staticmethod
    def _copy_bool_field(config: Dict[str, Any], node_data: Dict[str, Any], key: str) -> None:
        """Copy a boolean-valued config field into the serialized node data."""
        if key in config:
            node_data[key] = bool(config[key])

    def _serialize_node_state(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a single node's state config into the on-disk format."""
        node_data = {}

        # Convert QPointF positions to serializable format
        self._copy_point_field(config, node_data, "pos")

        # Set split state
        self._copy_bool_field(config, node_data, "is_split")

        # Convert split positions
        self._copy_point_field(config, node_data, "split_input_pos")
        self._copy_point_field(config, node_data, "split_output_pos")

        # Copy fold states
        self._copy_bool_field(config, node_data, self.IS_FOLDED_KEY)
        self._copy_bool_field(config, node_data, self.MANUAL_SPLIT_KEY)

        # Copy part fold states if the node is split
        if config.get("is_split", False):
            self._copy_bool_field(config, node_data, self.INPUT_PART_FOLDED_KEY)
            self._copy_bool_field(config, node_data, self.OUTPUT_PART_FOLDED_KEY)

        return node_data
