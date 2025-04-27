"""
PresetManager - Manages connection presets
"""

import os
import json
from PyQt6.QtWidgets import QMessageBox

class PresetManager:
    """
    Manages connection presets for the Cables application.
    
    This class handles saving, loading, and deleting presets, which store
    connection configurations that users can quickly apply.
    """
    
    def __init__(self):
        """Initialize the PresetManager."""
        self.config_dir = os.path.expanduser('~/.config/cable')
        self.presets_dir = os.path.join(self.config_dir, 'presets')
        
        # Ensure presets directory exists
        if not os.path.exists(self.presets_dir):
            try:
                # Create parent config dir first if it doesn't exist
                if not os.path.exists(self.config_dir):
                    os.makedirs(self.config_dir)
                os.makedirs(self.presets_dir)  # Then create presets dir
            except OSError as e:
                print(f"Error creating presets directory {self.presets_dir}: {e}")
    
    def load_presets(self):
        """
        Loads all presets from individual files in the presets directory.
        
        Returns:
            dict: A dictionary mapping preset names to their connection lists
        """
        presets = {}
        if not os.path.exists(self.presets_dir):
            return presets  # Return empty if directory doesn't exist
        
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".json"):
                preset_name = filename[:-5]  # Remove .json extension
                filepath = os.path.join(self.presets_dir, filename)
                try:
                    with open(filepath, 'r') as f:
                        preset_data = json.load(f)
                        # Add basic validation if needed (e.g., check if it's a list)
                        if isinstance(preset_data, list):
                            presets[preset_name] = preset_data
                        else:
                            print(f"Warning: Preset file {filename} does not contain a valid list. Skipping.")
                except json.JSONDecodeError:
                    print(f"Error decoding JSON from {filepath}. Skipping preset '{preset_name}'.")
                except Exception as e:
                    print(f"Error loading preset '{preset_name}' from {filepath}: {e}")
        return presets
    
    def get_preset_names(self):
        """
        Returns a sorted list of preset names by scanning the presets directory.
        
        Returns:
            list: A sorted list of preset names
        """
        names = []
        if not os.path.exists(self.presets_dir):
            return names
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".json"):
                names.append(filename[:-5])  # Remove .json extension
        return sorted(names)
    
    def get_preset(self, name):
        """
        Loads and returns the connection list for a specific preset name from its file.
        
        Args:
            name: The name of the preset to load
            
        Returns:
            list: The connection list for the preset, or None if not found
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.json")
        if not os.path.exists(preset_file):
            print(f"Preset file not found: {preset_file}")
            return None
        try:
            with open(preset_file, 'r') as f:
                preset_data = json.load(f)
                # Add validation if needed
                if isinstance(preset_data, list):
                    return preset_data
                else:
                    print(f"Warning: Preset file {preset_file} does not contain a valid list.")
                    return None
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {preset_file}.")
            return None
        except Exception as e:
            print(f"Error loading preset '{name}' from {preset_file}: {e}")
            return None
    
    def save_preset(self, name, connection_list, parent_widget=None, confirm_overwrite=True):
        """
        Saves a specific preset to its own JSON file, asking for overwrite confirmation.
        
        Args:
            name: The name of the preset to save
            connection_list: The list of connections to save
            parent_widget: The parent widget for dialog boxes
            confirm_overwrite: Whether to confirm before overwriting an existing preset
            
        Returns:
            bool: True if the preset was saved successfully, False otherwise
        """
        if not name:  # Prevent saving with empty names
            QMessageBox.warning(parent_widget, "Save Error", "Preset name cannot be empty.")
            return False
        if not isinstance(connection_list, list):
            QMessageBox.warning(parent_widget, "Save Error", 
                               f"Invalid data type for connection_list for preset '{name}'. Must be a list.")
            return False
        
        preset_file = os.path.join(self.presets_dir, f"{name}.json")
        
        # --- Overwrite Check ---
        if confirm_overwrite and os.path.exists(preset_file):
            reply = QMessageBox.question(parent_widget, 'Confirm Overwrite',
                                        f"A preset named '{name}' already exists.\nDo you want to overwrite it?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)  # Default to No
            if reply == QMessageBox.StandardButton.No:
                print(f"Overwrite cancelled for preset '{name}'.")
                return False  # User chose not to overwrite
        # --- End Overwrite Check ---
        
        try:
            with open(preset_file, 'w') as f:
                json.dump(connection_list, f, indent=4)  # Save only the list
            print(f"Preset '{name}' saved to {preset_file}")
            return True
        except Exception as e:
            error_message = f"Error saving preset '{name}' to {preset_file}: {e}"
            print(error_message)
            QMessageBox.critical(parent_widget, "Save Error", error_message)
            return False
    
    def delete_preset(self, name):
        """
        Deletes a specific preset file.
        
        Args:
            name: The name of the preset to delete
            
        Returns:
            bool: True if the preset was deleted successfully, False otherwise
        """
        preset_file = os.path.join(self.presets_dir, f"{name}.json")
        if os.path.exists(preset_file):
            try:
                os.remove(preset_file)
                print(f"Preset '{name}' deleted from {preset_file}")
                return True
            except OSError as e:
                print(f"Error deleting preset file {preset_file}: {e}")
                return False
        else:
            print(f"Preset file not found for deletion: {preset_file}")
            return False  # Or True if not finding it is acceptable
