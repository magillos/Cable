import os
import configparser
from PyQt6.QtCore import Qt

# Import the constant from the main module using relative import
# Assuming Cable.py is in the parent directory relative to config.py
try:
    from ..Cable import EDIT_LIST_TEXT
except ImportError:
    # Fallback if relative import fails (e.g., running config.py directly)
    EDIT_LIST_TEXT = "Edit List..."

class ConfigManager:
    def __init__(self, app=None): # Make app optional for standalone use in dialog
        self.app = app
        self.config_path = os.path.expanduser("~/.config/cable/config.ini")

    def _get_config_parser(self):
        """Helper to get a ConfigParser instance, loading existing config."""
        config = configparser.ConfigParser()
        if os.path.exists(self.config_path):
            try:
                config.read(self.config_path)
            except configparser.ParsingError as e:
                print(f"Warning: Could not parse existing config file {self.config_path}. Error: {e}")
        return config

    def _write_config(self, config):
        """Helper method to write config."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as configfile:
                config.write(configfile)
        except Exception as e:
            print(f"Error writing config file {self.config_path}: {e}")

    def get_int_setting(self, key, default_value):
        """Gets an integer setting from the config file."""
        config = self._get_config_parser()
        try:
            return config.getint('DEFAULT', key, fallback=default_value)
        except ValueError:
            print(f"Warning: Invalid integer value for '{key}' in config. Using default: {default_value}")
            return default_value
        except Exception as e:
            print(f"Error reading int setting '{key}' from config: {e}. Using default: {default_value}")
            return default_value

    def set_int_setting(self, key, value):
        """Sets an integer setting in the config file."""
        config = self._get_config_parser()
        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}
        config['DEFAULT'][key] = str(value)
        self._write_config(config)

    def clear_settings(self, keys_to_clear):
        """Removes specific keys from the config file."""
        config = self._get_config_parser()
        if 'DEFAULT' in config:
            for key in keys_to_clear:
                if key in config['DEFAULT']:
                    del config['DEFAULT'][key]
                    print(f"Cleared setting: {key}")
            self._write_config(config)

    def load_settings(self):
        """Load saved settings from config file"""
        config = self._get_config_parser() # Use the new helper method

        # Default settings
        tray_enabled = False
        tray_click_opens_cables = True
        self.app.remember_settings = False
        self.app.saved_quantum = 0
        self.app.saved_sample_rate = 0
        self.app.autostart_enabled = False
        self.app.check_updates_at_start = False # Default value
        self.app.restore_only_minimized = False # Default value for the new setting
        self.app.appimage_path = None # Default value for AppImage path

        if os.path.exists(self.config_path):
            try:
                config.read(self.config_path)
                # Load tray enabled state
                tray_enabled = config.getboolean('DEFAULT', 'tray_enabled', fallback=False)
                # Load default app setting
                tray_click_opens_cables = config.getboolean(
                    'DEFAULT', 'tray_click_opens_cables', fallback=True
                )
                # Load audio settings
                self.app.remember_settings = config.getboolean('DEFAULT', 'remember_settings', fallback=False)
                self.app.restore_only_minimized = config.getboolean('DEFAULT', 'restore_only_minimized', fallback=False) # Load new setting

                # Load saved audio settings if they exist
                has_saved_quantum = 'DEFAULT' in config and 'saved_quantum' in config['DEFAULT']
                has_saved_sample_rate = 'DEFAULT' in config and 'saved_sample_rate' in config['DEFAULT']

                if has_saved_quantum:
                    self.app.saved_quantum = config.getint('DEFAULT', 'saved_quantum', fallback=0)
                if has_saved_sample_rate:
                    self.app.saved_sample_rate = config.getint('DEFAULT', 'saved_sample_rate', fallback=0)

                # Only mark settings as not reset if we actually have saved values
                if has_saved_quantum:
                    self.app.quantum_was_reset = False
                if has_saved_sample_rate:
                    self.app.sample_rate_was_reset = False

                # Load autostart setting
                self.app.autostart_enabled = config.getboolean('DEFAULT', 'autostart_enabled', fallback=False)
                # Load startup update check setting
                self.app.check_updates_at_start = config.getboolean('DEFAULT', 'check_updates_at_start', fallback=False)

                # Load AppImage path setting
                self.app.appimage_path = config.get('DEFAULT', 'appimage_path', fallback=None)
                if self.app.appimage_path and not os.path.exists(self.app.appimage_path):
                    print(f"Warning: Configured AppImage path does not exist: {self.app.appimage_path}")
                    self.app.appimage_path = None

                print(f"Loaded tray_click_opens_cables from config: {tray_click_opens_cables}")
                print(f"Loaded remember_settings: {self.app.remember_settings}")
                print(f"Loaded autostart_enabled: {self.app.autostart_enabled}")
                print(f"Loaded check_updates_at_start: {self.app.check_updates_at_start}")
                print(f"Loaded restore_only_minimized: {self.app.restore_only_minimized}") # Print loaded value
                print(f"Loaded appimage_path: {self.app.appimage_path}")

                # Sync autostart file with config
                if self.app.autostart_enabled != self.app.autostart_manager.is_autostart_enabled():
                    if self.app.autostart_enabled:
                        self.app.autostart_manager.enable_autostart()
                    else:
                        self.app.autostart_manager.disable_autostart()
            except Exception as e:
                print(f"Error loading settings: {e}")

        # Set the checkbox states
        self.app.tray_toggle_checkbox.setChecked(tray_enabled)
        # Block signals temporarily while setting the state based on config
        self.app.remember_settings_checkbox.blockSignals(True)
        self.app.remember_settings_checkbox.setChecked(self.app.remember_settings)
        self.app.remember_settings_checkbox.blockSignals(False) # Unblock signals

        # Set state and enable/disable the new checkbox based on loaded settings
        self.app.restore_only_minimized_checkbox.blockSignals(True)
        self.app.restore_only_minimized_checkbox.setChecked(self.app.restore_only_minimized)
        self.app.restore_only_minimized_checkbox.setEnabled(self.app.remember_settings) # Enable only if remember_settings is checked
        self.app.restore_only_minimized_checkbox.blockSignals(False)

        self.app.tray_click_opens_cables = tray_click_opens_cables

        if tray_enabled:
            # Remove the old tray icon first if it exists (via manager)
            if self.app.tray_manager.tray_icon:
                self.app.tray_manager.tray_icon.hide()
                self.app.tray_manager.tray_icon = None
            # Then create a new one with updated settings (via manager)
            self.app.tray_manager.toggle_tray_icon(Qt.CheckState.Checked) # Call tray_manager's method

        # Block signals while potentially setting combo indices during load
        self.app.quantum_combo.blockSignals(True)
        self.app.sample_rate_combo.blockSignals(True)

        # Apply saved audio settings if enabled AND the conditions for restoring are met
        should_restore = self.app.remember_settings and (
            not self.app.restore_only_minimized or
            (self.app.restore_only_minimized and self.app.is_minimized_startup)
        )

        if should_restore:
            try:
                # Only apply saved settings if they exist and are non-zero
                if self.app.saved_quantum > 0:
                    quantum_str = str(self.app.saved_quantum)
                    print(f"Applying saved quantum: {quantum_str}")
                    index = self.app.quantum_combo.findText(quantum_str)
                    if index >= 0:
                       self.app.quantum_combo.setCurrentIndex(index)
                       self.app.last_valid_quantum_index = index
                    else:
                        edit_item_index = self.app.quantum_combo.count() - 1
                        if edit_item_index >= 0:
                            self.app.quantum_combo.insertItem(edit_item_index, quantum_str)
                            self.app.quantum_combo.setCurrentIndex(edit_item_index)
                            self.app.last_valid_quantum_index = edit_item_index
                            print(f"Inserted saved quantum '{quantum_str}' into dropdown.")
                        else:
                             print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert saved quantum '{quantum_str}' before.")
                    self.app.pipewire_manager.apply_quantum_settings(skip_save=True) # Use pipewire_manager

                if self.app.saved_sample_rate > 0:
                    sample_rate_str = str(self.app.saved_sample_rate)
                    print(f"Applying saved sample rate: {sample_rate_str}")
                    index = self.app.sample_rate_combo.findText(sample_rate_str)
                    if index >= 0:
                       self.app.sample_rate_combo.setCurrentIndex(index)
                       self.app.last_valid_sample_rate_index = index
                    else:
                        edit_item_index = self.app.sample_rate_combo.count() - 1
                        if edit_item_index >= 0:
                            self.app.sample_rate_combo.insertItem(edit_item_index, sample_rate_str)
                            self.app.sample_rate_combo.setCurrentIndex(edit_item_index)
                            self.app.last_valid_sample_rate_index = edit_item_index
                            print(f"Inserted saved sample rate '{sample_rate_str}' into dropdown.")
                        else:
                             print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert saved sample rate '{sample_rate_str}' before.")
                    self.app.pipewire_manager.apply_sample_rate_settings(skip_save=True) # Use pipewire_manager
            except Exception as e:
                print(f"Error applying saved audio settings: {e}")
        else:
             current_quantum_index = self.app.quantum_combo.currentIndex()
             if current_quantum_index >= 0 and self.app.quantum_combo.itemText(current_quantum_index) != EDIT_LIST_TEXT:
                 self.app.last_valid_quantum_index = current_quantum_index
             elif self.app.quantum_combo.count() > 1:
                 self.app.last_valid_quantum_index = 0
                 self.app.quantum_combo.setCurrentIndex(0)
             else:
                 self.app.last_valid_quantum_index = -1

             current_sample_rate_index = self.app.sample_rate_combo.currentIndex()
             if current_sample_rate_index >= 0 and self.app.sample_rate_combo.itemText(current_sample_rate_index) != EDIT_LIST_TEXT: # Use imported constant
                 self.app.last_valid_sample_rate_index = current_sample_rate_index
             elif self.app.sample_rate_combo.count() > 1:
                 self.app.last_valid_sample_rate_index = 0
                 self.app.sample_rate_combo.setCurrentIndex(0)
             else:
                 self.app.last_valid_sample_rate_index = -1

        # Unblock signals after potentially setting indices
        self.app.quantum_combo.blockSignals(False)
        self.app.sample_rate_combo.blockSignals(False)

        # Manually call update_latency_display after potentially changing indices without signals
        self.app.update_latency_display() # Call app's method


    def save_settings(self):
        """Save UI settings to config file (does not save audio settings)"""
        config = self._get_config_parser() # Use the new helper method

        # Load existing config if it exists
        if os.path.exists(self.config_path):
            config.read(self.config_path)

        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}

        # Update UI settings
        config['DEFAULT'].update({
            'tray_enabled': str(self.app.tray_toggle_checkbox.isChecked()),
            'tray_click_opens_cables': str(self.app.tray_click_opens_cables),
            'remember_settings': str(self.app.remember_settings),
            'restore_only_minimized': str(self.app.restore_only_minimized), # Save the new setting
            'autostart_enabled': str(self.app.autostart_enabled),
            'check_updates_at_start': str(self.app.check_updates_at_start), # Save the new setting
            'appimage_path': str(self.app.appimage_path) if self.app.appimage_path else '' # Save AppImage path
        })

        # Use the helper method to write the config
        self._write_config(config) # Internal call uses self

    def toggle_remember_settings(self, state):
        """Handle remember settings checkbox state changes"""
        remember = bool(state)
        self.app.remember_settings = remember

        # Enable/disable the "Restore only when auto-started" checkbox
        self.app.restore_only_minimized_checkbox.setEnabled(remember)

        # Update config
        config = self._get_config_parser() # Use the new helper method

        if os.path.exists(self.config_path):
            config.read(self.config_path)

        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}

        if remember:
            # Save current settings immediately when enabling
            config['DEFAULT']['remember_settings'] = 'True'

            current_quantum = self.app.quantum_combo.currentText()
            if current_quantum and not self.app.quantum_was_reset:
                config['DEFAULT']['saved_quantum'] = current_quantum
                print(f"Remember settings: Saved quantum {current_quantum}")

            current_sample_rate = self.app.sample_rate_combo.currentText()
            if current_sample_rate and not self.app.sample_rate_was_reset:
                config['DEFAULT']['saved_sample_rate'] = current_sample_rate
                print(f"Remember settings: Saved sample rate {current_sample_rate}")

            print("Audio settings will be remembered and restored on startup")
        else:
            # Remove saved audio settings when disabling
            config['DEFAULT']['remember_settings'] = 'False'
            if 'saved_quantum' in config['DEFAULT']:
                del config['DEFAULT']['saved_quantum']
            if 'saved_sample_rate' in config['DEFAULT']:
                del config['DEFAULT']['saved_sample_rate']
            # Also disable and uncheck the "Restore only when auto-started" checkbox and save its state
            self.app.restore_only_minimized_checkbox.setChecked(False)
            self.app.restore_only_minimized = False
            if 'restore_only_minimized' in config['DEFAULT']:
                 del config['DEFAULT']['restore_only_minimized']

            print("Audio settings will not be remembered")

        # Save other settings that might exist
        if 'tray_enabled' in config['DEFAULT']:
            config['DEFAULT']['tray_enabled'] = str(self.app.tray_toggle_checkbox.isChecked())
        if 'tray_click_opens_cables' in config['DEFAULT']:
            config['DEFAULT']['tray_click_opens_cables'] = str(self.app.tray_click_opens_cables)

        # Use the helper method to write the config
        self._write_config(config) # Internal call uses self

    def toggle_restore_only_minimized(self, state):
        """Handle restore only when auto-started checkbox state changes"""
        self.app.restore_only_minimized = bool(state)
        print(f"Set restore_only_minimized to: {self.app.restore_only_minimized}")
        self.save_settings() # Call ConfigManager's save_settings

    def ensure_config_lists(self):
        """Ensure config.ini contains quantum_values and sample_rate_values keys."""
        config = self._get_config_parser() # Use the new helper method

        if os.path.exists(self.config_path):
            try:
                config.read(self.config_path)
            except configparser.ParsingError as e:
                print(f"Warning: Could not parse existing config file {self.config_path}. It might be overwritten. Error: {e}")
                config = configparser.ConfigParser(allow_no_value=True)
        else:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}

        default_section = config['DEFAULT']
        config_updated = False

        # Use app's constants
        if 'quantum_values' not in default_section:
            default_section['quantum_values'] = ','.join(str(x) for x in self.app.DEFAULT_QUANTUM_VALUES)
            config_updated = True

        if 'sample_rate_values' not in default_section:
            default_section['sample_rate_values'] = ','.join(str(x) for x in self.app.DEFAULT_SAMPLE_RATE_VALUES)
            config_updated = True

        if config_updated:
            self._write_config(config) # Internal call uses self
            print("Added missing default list(s) to config.ini")

    def get_list_from_config(self, key, default_values):
        """Gets a list of integers from a comma-separated config value, ignoring comments."""
        config = self._get_config_parser() # Use the new helper method
        try:
            if os.path.exists(self.config_path):
                config.read(self.config_path)
                raw = config['DEFAULT'].get(key, None)
                if raw is not None:
                    parts = [x.strip() for x in raw.split(',')]
                    vals = []
                    for p in parts:
                        if p and not p.startswith('#'): # Ignore empty strings and commented out values
                            try:
                                vals.append(int(p))
                            except ValueError:
                                print(f"Invalid integer '{p}' in config key '{key}'")
                    if vals:
                        return vals
        except Exception as e:
            print(f"Error reading '{key}' from config: {e}")

        return default_values # Return the passed default_values

    def _save_audio_setting(self, setting_name, config_key, combo_box, was_reset_attr):
        """Helper method to save quantum or sample rate setting to config file."""
        was_reset = getattr(self.app, was_reset_attr) # Get attribute from app
        # Don't save if we've explicitly reset the value and haven't changed it
        if was_reset:
            print(f"Skipping save of {setting_name} setting after reset")
            return

        config = self._get_config_parser() # Use the new helper method

        # Load existing config if it exists
        if os.path.exists(self.config_path):
            try:
                config.read(self.config_path)
            except configparser.ParsingError as e:
                 print(f"Warning: Could not parse config file {self.config_path} during save. Error: {e}")

        if 'DEFAULT' not in config:
            config['DEFAULT'] = {}

        # Save the specific setting
        current_value = combo_box.currentText() # Use passed combo_box (from app)
        # Ensure we don't save empty strings or the edit text
        if current_value and current_value != EDIT_LIST_TEXT: # Use imported constant
            config['DEFAULT'][config_key] = current_value
            print(f"Saved {setting_name} setting: {current_value}")
        elif config_key in config['DEFAULT']:
            # If the current value is invalid/empty/edit text, remove the key if it exists
            del config['DEFAULT'][config_key]
            print(f"Removed invalid/empty {setting_name} setting ({config_key}) from config")

        # Use the helper method to write the config
        self._write_config(config) # Internal call uses self

    def save_quantum_setting(self):
        """Save only the quantum setting to config file"""
        self._save_audio_setting( # Internal call uses self
            setting_name="quantum",
            config_key='saved_quantum',
            combo_box=self.app.quantum_combo, # Pass app's combo box
            was_reset_attr='quantum_was_reset' # Attribute name on app
        )

    def save_sample_rate_setting(self):
        """Save only the sample rate setting to config file"""
        self._save_audio_setting( # Internal call uses self
            setting_name="sample rate",
            config_key='saved_sample_rate',
            combo_box=self.app.sample_rate_combo, # Pass app's combo box
            was_reset_attr='sample_rate_was_reset' # Attribute name on app
        )

    def toggle_startup_check(self, checked):
        """Updates the startup check setting and saves it."""
        self.app.check_updates_at_start = checked
        print(f"Set check_updates_at_start to: {self.app.check_updates_at_start}")
        self.save_settings() # Call ConfigManager's save_settings

    def save_appimage_path(self, appimage_path):
        """Save the AppImage path to config and update autostart manager."""
        self.app.appimage_path = appimage_path
        if appimage_path:
            # Update autostart manager with new AppImage path
            self.app.autostart_manager = AutostartManager(self.app.flatpak_env, appimage_path)
        self.save_settings()
        print(f"Saved AppImage path: {appimage_path}")