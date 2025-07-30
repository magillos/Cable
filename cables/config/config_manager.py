"""
ConfigManager - Manages application configuration settings
"""

import os
import configparser

class ConfigManager:
    """
    Manages application configuration settings.
    
    This class handles reading and writing configuration settings to a config file,
    providing methods to get and set various types of configuration values.
    """
    
    def __init__(self):
        """Initialize the ConfigManager."""
        self.config_path = os.path.expanduser('~/.config/cable/config.ini')
        self.config = self._get_config_parser()
        self.load_defaults() # Load defaults after initializing config

    def _get_config_parser(self):
        """Helper to get a ConfigParser instance, loading existing config."""
        config = configparser.ConfigParser()
        config_dir = os.path.dirname(self.config_path)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
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

    def load_defaults(self):
        """Load default settings if not present."""
        if 'DEFAULT' not in self.config:
            self.config['DEFAULT'] = {}
        
        defaults = {
            'tray_enabled': 'True',
            'tray_click_opens_cables': 'True',
            'auto_refresh_enabled': 'True',
            'collapse_all_enabled': 'False',
            'port_list_font_size': '10',
            'untangle_mode': '0',
            'last_active_tab': '0',
            'load_preset_strict_mode': 'False', # New setting for strict mode
            'load_preset_daemon_mode': 'False' # New setting for daemon mode
        }
        
        for key, value in defaults.items():
            if key not in self.config['DEFAULT']:
                self.config['DEFAULT'][key] = value
        
        self._write_config(self.config) # Use internal helper

    def get_bool(self, key, default=True):
        """
        Get a boolean value from the configuration.
        
        Args:
            key: The configuration key
            default: Default value if the key doesn't exist
            
        Returns:
            bool: The configuration value
        """
        return self.config['DEFAULT'].getboolean(key, default)
    
    def set_bool(self, key, value):
        """
        Set a boolean value in the configuration.
        
        Args:
            key: The configuration key
            value: The boolean value to set
        """
        self.config['DEFAULT'][key] = 'True' if value else 'False'
        self._write_config(self.config) # Use internal helper
    
    def get_int(self, key, default=0):
        """
        Get an integer value from the configuration.
        
        Args:
            key: The configuration key
            default: Default value if the key doesn't exist
            
        Returns:
            int: The configuration value
        """
        return self.config['DEFAULT'].getint(key, default)
    
    def set_int(self, key, value):
        """
        Set an integer value in the configuration.
        
        Args:
            key: The configuration key
            value: The integer value to set
        """
        self.config['DEFAULT'][key] = str(value)
        self._write_config(self.config) # Use internal helper

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
    
    def get_str(self, key, default=None):
        """
        Get a string value from the configuration.
        
        Args:
            key: The configuration key
            default: Default value if the key doesn't exist
            
        Returns:
            str: The configuration value
        """
        return self.config['DEFAULT'].get(key, default)
    
    def set_str(self, key, value):
        """
        Set a string value in the configuration.
        
        Args:
            key: The configuration key
            value: The string value to set
        """
        self.config['DEFAULT'][key] = str(value) if value is not None else ''
        self._write_config(self.config) # Use internal helper
