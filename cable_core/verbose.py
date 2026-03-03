"""
Verbose output control module.
When verbose output is disabled, all print statements are suppressed.
"""

import sys
import os
import configparser
import builtins
from typing import Any

_original_print = builtins.print
_verbose_enabled = True


def _load_verbose_setting() -> bool:
    """Load verbose setting from config file."""
    config_file = os.path.expanduser("~/.config/cable/config.ini")
    if os.path.exists(config_file):
        try:
            config = configparser.ConfigParser()
            config.read(config_file, encoding='utf-8')
            if config.has_option('DEFAULT', 'verbose_output'):
                return config.getboolean('DEFAULT', 'verbose_output')
        except (configparser.Error, ValueError):
            pass
    return False  # Default to verbose off


def _silent_print(*args: Any, **kwargs: Any) -> None:
    """Silent print function that does nothing."""
    pass


def init_verbose_mode() -> None:
    """Initialize verbose mode based on config setting.
    Call this early in the application startup.
    """
    global _verbose_enabled
    _verbose_enabled = _load_verbose_setting()
    if not _verbose_enabled:
        builtins.print = _silent_print


def is_verbose() -> bool:
    """Check if verbose mode is enabled."""
    return _verbose_enabled
