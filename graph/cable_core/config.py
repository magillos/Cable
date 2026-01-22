import os
import configparser
import json
import atexit
from pathlib import Path
from typing import Optional, Dict, Any
from PyQt6.QtCore import Qt

class ConfigManager:
    def __init__(self, parent=None):
        self.parent = parent
        self.config_file = os.path.expanduser("~/.config/cable/config.ini")
        self._dirty = False
        self._config = None  # Cached config
        self._ensure_config_exists()
        # For backward compatibility - some code expects Cable.py as app
        self.app = parent
        atexit.register(self.flush)

    def _get_cached_config(self):
        """Get cached config, loading from disk if needed."""
        if self._config is None:
            self._config = configparser.ConfigParser(allow_no_value=True)
            if os.path.exists(self.config_file):
                self._config.read(self.config_file, encoding='utf-8')
        return self._config

    def _ensure_config_exists(self):
        """Ensure the config file exists with default values."""
        config_dir = os.path.expanduser("~/.config/cable")
        os.makedirs(config_dir, exist_ok=True)

        config = self._get_cached_config()

        default_values = {
            'quantum_values': '16,32,48,64,96,128,144,192,240,256,512,1024,2048,4096,8192',
            'sample_rate_values': '44100,48000,88200,96000,176400,192000',
            'quantum': '1024',
            'sample_rate': '48000',
            'virtual_sink_module_ids': '{}'
        }

        added_defaults = False
        for key, value in default_values.items():
            if not config.has_option('DEFAULT', key):
                config.set('DEFAULT', key, value)
                added_defaults = True

        if added_defaults:
            self._dirty = True

    def ensure_config_exists(self):
        """Public method for compatibility."""
        self._ensure_config_exists()

    def _mark_dirty(self):
        """Mark config as having unsaved changes."""
        self._dirty = True

    def flush(self):
        """Write config to disk if there are unsaved changes."""
        if self._dirty and self._config is not None:
            self._write_config_to_disk(self._config)
            self._dirty = False

    def _write_config_to_disk(self, config):
        """Actually write config to disk."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
        except Exception as e:
            print(f"Error writing config file {self.config_file}: {e}")

    def write_config(self, config):
        """Write configuration - now just marks dirty and updates cache."""
        self._config = config
        self._dirty = True

    def get_list_from_config(self, key, default_list):
        """Get a list of active values from config (excluding commented out values), with fallback to default."""
        config = configparser.ConfigParser()
        config.read(self.config_file, encoding='utf-8')

        if config.has_option('DEFAULT', key):
            value = config.get('DEFAULT', key)
            if value:
                parts = [item.strip() for item in value.split(',') if item.strip()]
                vals = []
                for p in parts:
                    if p and not p.startswith('#'): # Ignore commented out values
                        try:
                            vals.append(int(p))
                        except ValueError:
                            continue
                if vals:
                    return vals
        return default_list

    def get_all_values_from_config(self, key, default_list):
        """Get all values from config including commented out ones, with fallback to default list."""
        config = configparser.ConfigParser()
        config.read(self.config_file, encoding='utf-8')

        if config.has_option('DEFAULT', key):
            value = config.get('DEFAULT', key)
            if value:
                parts = [item.strip() for item in value.split(',') if item.strip()]
                vals = []
                for p in parts:
                    clean_val = p.lstrip('#')  # Remove leading # if present
                    try:
                        vals.append(int(clean_val))
                    except ValueError:
                        continue
                if vals:
                    return vals
        return default_list

    def get_int_setting(self, key: str, default: int = 0) -> int:
        """Get integer setting from config."""
        try:
            config = configparser.ConfigParser()
            config.read(self.config_file, encoding='utf-8')
            if config.has_option('DEFAULT', key):
                return config.getint('DEFAULT', key)
        except (configparser.Error, ValueError):
            pass
        return default

    def get_str_setting(self, key: str, default: str = "") -> str:
        """Get string setting from config."""
        config = configparser.ConfigParser()
        config.read(self.config_file, encoding='utf-8')
        if config.has_option('DEFAULT', key):
            return config.get('DEFAULT', key)
        return default

    def get_bool_setting(self, key: str, default: bool = False) -> bool:
        """Get boolean setting from config."""
        try:
            config = configparser.ConfigParser()
            config.read(self.config_file, encoding='utf-8')
            if config.has_option('DEFAULT', key):
                return config.getboolean('DEFAULT', key)
        except (configparser.Error, ValueError):
            pass
        return default

    def set_int_setting(self, key: str, value: int):
        """Set integer setting in config."""
        config = self._get_cached_config()
        config['DEFAULT'][key] = str(value)
        self._mark_dirty()

    def set_str_setting(self, key: str, value: str):
        """Set string setting in config."""
        config = self._get_cached_config()
        config['DEFAULT'][key] = value
        self._mark_dirty()

    def set_bool_setting(self, key: str, value: bool):
        """Set boolean setting in config."""
        config = self._get_cached_config()
        config['DEFAULT'][key] = '1' if value else '0'
        self._mark_dirty()

    def clear_settings(self, keys_to_clear):
        """Removes specific keys from the config."""
        config = self._get_cached_config()
        if 'DEFAULT' in config:
            for key in keys_to_clear:
                if key in config['DEFAULT']:
                    del config['DEFAULT'][key]
                    print(f"Cleared setting: {key}")
        self._mark_dirty()

    # Backward compatibility methods for old code

    # Aliases for backward compatibility
    get_bool = get_bool_setting
    set_bool = set_bool_setting

    # Additional backward compatible methods that old code might expect
    def _get_config_parser(self):
        """Helper to get a ConfigParser instance, loading existing config."""
        config = configparser.ConfigParser()
        if os.path.exists(self.config_file):
            try:
                config.read(self.config_file)
            except configparser.ParsingError as e:
                print(f"Warning: Could not parse existing config file {self.config_file}. Error: {e}")
        return config

    def _write_config(self, config):
        """Helper method to write config."""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as configfile:
                config.write(configfile)
        except Exception as e:
            print(f"Error writing config file {self.config_file}: {e}")

    # Add DEFAULT_QUANTUM/SAMPLE_RATE_VALUES for compatibility
    DEFAULT_QUANTUM_VALUES = [16, 32, 48, 64, 96, 128, 144, 192, 240, 256, 512, 1024, 2048, 4096, 8192]
    DEFAULT_SAMPLE_RATE_VALUES = [44100, 48000, 88200, 96000, 176400, 192000]

    def load_settings(self):
        """Load saved settings from config file"""
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

        if os.path.exists(self.config_file):
            try:
                config = configparser.ConfigParser()
                config.read(self.config_file, encoding='utf-8')
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
                             print(f"Warning: Could not find 'Edit List...' to insert saved quantum '{quantum_str}' before.")
                    # Skip saving since we're loading
                    if hasattr(self.app, 'pipewire_manager'):
                        self.app.pipewire_manager.apply_quantum_settings(skip_save=True)

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
                             print(f"Warning: Could not find 'Edit List...' to insert saved sample rate '{sample_rate_str}' before.")
                    # Skip saving since we're loading
                    if hasattr(self.app, 'pipewire_manager'):
                        self.app.pipewire_manager.apply_sample_rate_settings(skip_save=True)
            except Exception as e:
                print(f"Error applying saved audio settings: {e}")
        else:
             current_quantum_index = self.app.quantum_combo.currentIndex()
             if current_quantum_index >= 0 and self.app.quantum_combo.itemText(current_quantum_index) != "Edit List...":
                 self.app.last_valid_quantum_index = current_quantum_index
             elif self.app.quantum_combo.count() > 1:
                 self.app.last_valid_quantum_index = 0
                 self.app.quantum_combo.setCurrentIndex(0)
             else:
                 self.app.last_valid_quantum_index = -1

             current_sample_rate_index = self.app.sample_rate_combo.currentIndex()
             if current_sample_rate_index >= 0 and self.app.sample_rate_combo.itemText(current_sample_rate_index) != "Edit List...":
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
        config = configparser.ConfigParser()
        if os.path.exists(self.config_file):
            config.read(self.config_file, encoding='utf-8')

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

        self.write_config(config)

    def toggle_remember_settings(self, state):
        """Handle remember settings checkbox state changes"""
        remember = bool(state)
        self.app.remember_settings = remember

        # Enable/disable the "Restore only when auto-started" checkbox
        self.app.restore_only_minimized_checkbox.setEnabled(remember)

        # Update config
        config = configparser.ConfigParser()
        if os.path.exists(self.config_file):
            config.read(self.config_file, encoding='utf-8')

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

        self.write_config(config)

    def toggle_restore_only_minimized(self, state):
        """Handle restore only when auto-started checkbox state changes"""
        self.app.restore_only_minimized = bool(state)
        print(f"Set restore_only_minimized to: {self.app.restore_only_minimized}")
        self.save_settings()

    def ensure_config_lists(self):
        """Ensure config.ini contains quantum_values and sample_rate_values keys."""
        config = configparser.ConfigParser(allow_no_value=True)
        if os.path.exists(self.config_file):
            try:
                config.read(self.config_file, encoding='utf-8')
            except configparser.ParsingError as e:
                print(f"Warning: Could not parse existing config file {self.config_file}. It might be overwritten. Error: {e}")
                config = configparser.ConfigParser(allow_no_value=True)
        else:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

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
            self.write_config(config)
            print("Added missing default list(s) to config.ini")

    def toggle_startup_check(self, checked):
        """Updates the startup check setting and saves it."""
        self.app.check_updates_at_start = checked
        print(f"Set check_updates_at_start to: {self.app.check_updates_at_start}")
        self.save_settings()

    def save_appimage_path(self, appimage_path):
        """Save the AppImage path to config and update autostart manager."""
        self.app.appimage_path = appimage_path
        if appimage_path:
            # Update autostart manager with new AppImage path
            self.app.autostart_manager = self.app.autostart_manager.__class__(self.app.flatpak_env, appimage_path)
        self.save_settings()
        print(f"Saved AppImage path: {appimage_path}")

    def _save_audio_setting(self, setting_name, config_key, combo_box, was_reset_attr):
        """Helper method to save quantum or sample rate setting to config file."""
        try:
            was_reset = getattr(self.app, was_reset_attr)
            if was_reset:
                print(f"Skipping save of {setting_name} setting after reset")
                return

            config = configparser.ConfigParser()
            config.read(self.config_file, encoding='utf-8')

            if 'DEFAULT' not in config:
                config['DEFAULT'] = {}

            current_value = combo_box.currentText()
            if current_value and current_value != "Edit List...":
                config['DEFAULT'][config_key] = current_value
                print(f"Saved {setting_name} setting: {current_value}")
            elif config_key in config['DEFAULT']:
                del config['DEFAULT'][config_key]
                print(f"Removed invalid/empty {setting_name} setting ({config_key}) from config")

            self.write_config(config)
        except Exception as e:
            print(f"Error saving {setting_name} setting: {e}")

    def save_quantum_setting(self):
        """Save only the quantum setting to config file"""
        if hasattr(self.app, 'quantum_combo') and hasattr(self.app, 'quantum_was_reset'):
            self._save_audio_setting(
                setting_name="quantum",
                config_key='saved_quantum',
                combo_box=self.app.quantum_combo,
                was_reset_attr='quantum_was_reset'
            )

    def save_sample_rate_setting(self):
        """Save only the sample rate setting to config file"""
        if hasattr(self.app, 'sample_rate_combo') and hasattr(self.app, 'sample_rate_was_reset'):
            self._save_audio_setting(
                setting_name="sample rate",
                config_key='saved_sample_rate',
                combo_box=self.app.sample_rate_combo,
                was_reset_attr='sample_rate_was_reset'
            )
