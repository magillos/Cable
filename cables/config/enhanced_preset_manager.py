"""
Enhanced PresetManager - Manages connection presets with layout information
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PyQt6.QtWidgets import QMessageBox, QWidget
from .preset_manager import PresetManager

import logging
logger = logging.getLogger(__name__)


class EnhancedPresetManager(PresetManager):
    """
    Enhanced preset manager that extends the base PresetManager to include layout information storage.
    
    This manager handles both connection data (via aj-snapshot) and visual layout data (stored as JSON).
    Layout data includes node positions, split/fold states, node visibility settings, and graph zoom level.
    """
    
    def __init__(self) -> None:
        """Initialize the EnhancedPresetManager."""
        super().__init__()
        self.layout_presets_dir = os.path.join(self.config_dir, 'layout_presets')
        
        # Ensure layout presets directory exists
        if not os.path.exists(self.layout_presets_dir):
            try:
                os.makedirs(self.layout_presets_dir)
            except OSError as e:
                logger.error(f"Error creating layout presets directory {self.layout_presets_dir}: {e}")
    
    def get_preset_names(self) -> List[str]:
        """
        Get preset names without visual indicators.
        
        Returns:
            list: Sorted list of preset names
        """
        names = []
        if not os.path.exists(self.presets_dir):
            return names
            
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".snap"):
                preset_name = filename[:-5]
                names.append(preset_name)
                    
        return sorted(names)
    
    def _get_clean_preset_name(self, display_name: str) -> str:
        """
        Extract the clean preset name from a display name.
        
        Args:
            display_name (str): Display name (now just the preset name)
            
        Returns:
            str: Clean preset name
        """
        # No longer need to handle [+Layout] suffix, but keep method for compatibility
        return display_name
    
    def save_preset_with_layout(self, name: str, node_states: Optional[Dict[str, Any]] = None, graph_zoom_level: Optional[float] = None, node_visibility_data: Optional[Dict[str, Any]] = None, parent_widget: Optional[QWidget] = None, confirm_overwrite: bool = True) -> bool:
        """
        Save both connection preset (via aj-snapshot) and layout data.
        
        Args:
            name (str): Preset name
            node_states (dict, optional): Node state data from scene.get_node_states()
            graph_zoom_level (float, optional): Current graph zoom level
            node_visibility_data (dict, optional): Node visibility settings
            parent_widget: Parent widget for dialogs
            confirm_overwrite (bool): Whether to confirm overwrite of existing presets
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not name:
            QMessageBox.warning(parent_widget, "Save Error", "Preset name cannot be empty.")
            return False
        
        # Clean the name in case it has the [+Layout] suffix
        clean_name = self._get_clean_preset_name(name)
        
        # First save the connection preset using the base class
        logger.debug(f"EnhancedPresetManager: About to call base class save_preset for '{clean_name}'")
        if not super().save_preset(clean_name, parent_widget, confirm_overwrite):
            logger.debug(f"EnhancedPresetManager: Base class save_preset failed for '{clean_name}'")
            return False
        logger.debug(f"EnhancedPresetManager: Base class save_preset succeeded for '{clean_name}'")
        
        # Then save the layout data if provided
        if node_states is not None or node_visibility_data is not None:
            logger.debug(f"EnhancedPresetManager: Saving layout data for '{clean_name}'")
            layout_file = os.path.join(self.layout_presets_dir, f"{clean_name}.json")
            
            try:
                unified_clients = {}
                if node_states:
                    for client_name, state in node_states.items():
                        if state.get('is_input_unified') or state.get('is_output_unified'):
                            unified_clients[client_name] = {
                                'is_input_unified': state.get('is_input_unified', False),
                                'is_output_unified': state.get('is_output_unified', False),
                                'unified_input_sink_name': state.get('unified_input_sink_name'),
                                'unified_output_sink_name': state.get('unified_output_sink_name'),
                                'channel_map': 'stereo'
                            }

                layout_data = {
                    'node_states': node_states,
                    'graph_zoom_level': graph_zoom_level,
                    'node_visibility': node_visibility_data,
                    'unified_clients': unified_clients
                }
                
                logger.debug(f"EnhancedPresetManager: Writing JSON to {layout_file}")
                with open(layout_file, 'w') as f:
                    json.dump(layout_data, f, indent=4, default=self._json_serializer)
                    
                logger.info(f"Layout data for preset '{clean_name}' saved to {layout_file}")
                
            except Exception as e:
                error_message = f"Connection preset saved, but error saving layout data for '{clean_name}': {e}"
                logger.debug(error_message)
                import traceback
                traceback.print_exc()
                QMessageBox.warning(parent_widget, "Layout Save Warning", error_message)
                # Don't return False here - connection preset was saved successfully
        else:
            logger.debug(f"EnhancedPresetManager: No layout data to save for '{clean_name}'")
        
        return True
    
    def load_and_apply_preset_with_layout(self, name: str, strict_mode: bool = False, daemon_mode: bool = False, apply_layout: bool = True) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Load and apply both connection preset and layout data.
        
        Args:
            name (str): Preset name (may include [+Layout] suffix)
            strict_mode (bool): Whether to use strict mode for aj-snapshot
            daemon_mode (bool): Whether to use daemon mode for aj-snapshot
            apply_layout (bool): Whether to apply layout data if available
            
        Returns:
            tuple: (success, layout_data) where success is bool and layout_data is dict or None
        """
        # Clean the name in case it has the [+Layout] suffix
        clean_name = self._get_clean_preset_name(name)
        
        # First load the connection preset using the base class
        connection_success = super().load_and_apply_preset(clean_name, strict_mode, daemon_mode)
        
        layout_data = None
        
        # Then load layout data if requested and available
        if apply_layout:
            layout_file = os.path.join(self.layout_presets_dir, f"{clean_name}.json")
            
            if os.path.exists(layout_file):
                try:
                    with open(layout_file, 'r') as f:
                        layout_data = json.load(f)
                    
                    # Convert position data back to QPointF objects
                    layout_data = self._deserialize_layout_data(layout_data)
                    
                    logger.info(f"Layout data for preset '{clean_name}' loaded from {layout_file}")
                    
                except Exception as e:
                    logger.error(f"Error loading layout data for preset '{clean_name}': {e}")
                    # Don't fail the entire operation if layout loading fails
            else:
                logger.debug(f"No layout data found for preset '{clean_name}'")
        
        return connection_success, layout_data
    
    def delete_preset_with_layout(self, name: str) -> bool:
        """
        Delete both connection preset and layout data.
        
        Args:
            name (str): Preset name (may include [+Layout] suffix)
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Clean the name in case it has the [+Layout] suffix
        clean_name = self._get_clean_preset_name(name)
        
        # Delete the connection preset using the base class
        connection_deleted = super().delete_preset(clean_name)
        
        # Delete the layout data if it exists
        layout_file = os.path.join(self.layout_presets_dir, f"{clean_name}.json")
        layout_deleted = True
        
        if os.path.exists(layout_file):
            try:
                os.remove(layout_file)
                logger.info(f"Layout data for preset '{clean_name}' deleted from {layout_file}")
            except OSError as e:
                logger.error(f"Error deleting layout file {layout_file}: {e}")
                layout_deleted = False
        
        return connection_deleted and layout_deleted
    
    def _json_serializer(self, obj: Any) -> Any:
        """
        Custom JSON serializer for Qt objects.
        
        Args:
            obj: Object to serialize
            
        Returns:
            Serializable representation of the object
        """
        # Handle QPointF objects
        if hasattr(obj, 'x') and hasattr(obj, 'y') and callable(obj.x) and callable(obj.y):
            return {"x": obj.x(), "y": obj.y()}
        
        # Handle other Qt objects by converting to string
        if hasattr(obj, '__class__') and 'PyQt' in str(obj.__class__):
            return str(obj)
        
        # Fallback for other non-serializable objects
        return str(obj)
    
    def _deserialize_layout_data(self, layout_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Convert serialized position data back to QPointF objects.
        
        Args:
            layout_data (dict): Layout data loaded from JSON
            
        Returns:
            dict: Layout data with QPointF objects restored
        """
        from PyQt6.QtCore import QPointF
        
        if not layout_data or 'node_states' not in layout_data:
            return layout_data
        
        # Process each node's state data
        for client_name, node_config in layout_data['node_states'].items():
            # Convert position data to QPointF
            if 'pos' in node_config and isinstance(node_config['pos'], dict):
                if 'x' in node_config['pos'] and 'y' in node_config['pos']:
                    node_config['pos'] = QPointF(node_config['pos']['x'], node_config['pos']['y'])
            
            # Convert split position data to QPointF
            if 'split_input_pos' in node_config and isinstance(node_config['split_input_pos'], dict):
                if 'x' in node_config['split_input_pos'] and 'y' in node_config['split_input_pos']:
                    node_config['split_input_pos'] = QPointF(
                        node_config['split_input_pos']['x'], 
                        node_config['split_input_pos']['y']
                    )
            
            if 'split_output_pos' in node_config and isinstance(node_config['split_output_pos'], dict):
                if 'x' in node_config['split_output_pos'] and 'y' in node_config['split_output_pos']:
                    node_config['split_output_pos'] = QPointF(
                        node_config['split_output_pos']['x'], 
                        node_config['split_output_pos']['y']
                    )
        
        return layout_data