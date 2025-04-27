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
        self.config = configparser.ConfigParser()
        self.config_dir = os.path.expanduser('~/.config/cable')
        self.config_file = os.path.join(self.config_dir, 'config.ini')
        self.load_config()
    
    def load_config(self):
        """Load configuration from file or create with defaults if it doesn't exist."""
        # Create directory if it doesn't exist
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
        
        # Load existing config or create with defaults
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
        
        # Ensure DEFAULT section exists
        if 'DEFAULT' not in self.config:
            self.config['DEFAULT'] = {}
        
        # Set defaults if not present
        defaults = {
            'tray_enabled': 'True',
            'tray_click_opens_cables': 'True',
            'auto_refresh_enabled': 'True',
            'collapse_all_enabled': 'False',
            'port_list_font_size': '10',
            'untangle_mode': '0',
            'last_active_tab': '0'
        }
        
        for key, value in defaults.items():
            if key not in self.config['DEFAULT']:
                self.config['DEFAULT'][key] = value
        
        self.save_config()
    
    def save_config(self):
        """Save configuration to file."""
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)
    
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
        self.save_config()
    
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
        self.save_config()
    
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
        self.save_config()
