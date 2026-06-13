"""
Configuration management using INI format with dirty-flag writes.
Central config for both Cable and Cables apps.
"""

import os
import logging
import configparser
import json
import atexit
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from . import config_keys as keys

logger = logging.getLogger(__name__)

__all__ = ["ConfigManager"]

# Version marker key introduced in 0.9.29
_VERSION_MARKER_KEY = "main_window_geometry"


class ConfigManager:
    def __init__(self, parent: Optional[Any] = None) -> None:
        self.parent = parent
        self.config_file = os.path.expanduser("~/.config/cable/config.ini")
        self.config_dir = os.path.expanduser("~/.config/cable")
        self._dirty = False
        self._changed_keys = set()  # Track changed keys
        self._config = None  # Cached config
        self._migration_performed = False  # Track if migration happened
        # Run migration before loading any existing config
        self._migrate_if_needed()
        self._ensure_config_exists()
        atexit.register(self.flush)

    def _get_cached_config(self) -> configparser.ConfigParser:
        """Get cached config, loading from disk if needed."""
        if self._config is None:
            self._config = configparser.ConfigParser(allow_no_value=True)
            if os.path.exists(self.config_file):
                self._config.read(self.config_file, encoding="utf-8")
        return self._config

    def _migrate_if_needed(self) -> None:
        """
        Migrate config from pre-0.9.29 versions.

        If the existing config doesn't have the _VERSION_MARKER_KEY ('main_window_geometry'),
        it's from an older version. Back up the old config and remove it to trigger
        fresh defaults for the new version.
        """
        config_file = os.path.expanduser("~/.config/cable/config.ini")

        # Check if config file exists
        if not os.path.exists(config_file):
            logger.debug("No existing config file, no migration needed")
            return

        # Check for version marker key
        try:
            test_config = configparser.ConfigParser(allow_no_value=True)
            test_config.read(config_file, encoding="utf-8")

            if test_config.has_option("DEFAULT", _VERSION_MARKER_KEY):
                logger.debug("Config version marker found, no migration needed")
                return
        except Exception as e:
            logger.warning(f"Could not read existing config for migration check: {e}")
            # If we can't read it, proceed with migration to be safe

        # Migration needed - backup and remove old config
        logger.info("Old config detected (pre-0.9.29), performing migration...")
        self._migration_performed = True

        backup_dir = os.path.expanduser("~/.config/cable.backup")

        try:
            # Remove existing backup if present
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)
                logger.info(f"Removed existing backup directory: {backup_dir}")

            # Backup old config directory
            config_dir = os.path.expanduser("~/.config/cable")
            shutil.copytree(config_dir, backup_dir)
            logger.info(f"Backed up old config to: {backup_dir}")

            # Remove old config directory
            shutil.rmtree(config_dir)
            logger.info(f"Removed old config directory: {config_dir}")

            # Create fresh config with version marker to prevent re-migration
            self._create_fresh_config_with_marker()

            logger.info("Config migration completed successfully")

        except Exception as e:
            logger.error(f"Error during config migration: {e}")
            # Continue anyway - worst case is user loses old config without backup

    def _create_fresh_config_with_marker(self) -> None:
        """Create fresh config with version marker after migration."""
        # Create directory
        config_dir = os.path.expanduser("~/.config/cable")
        os.makedirs(config_dir, exist_ok=True)

        # Create fresh config with version marker
        config = configparser.ConfigParser()
        config["DEFAULT"] = {
            keys.QUANTUM_VALUES: "16,32,48,64,96,128,144,192,240,256,512,1024,2048,4096,8192",
            keys.SAMPLE_RATE_VALUES: "44100,48000,88200,96000,176400,192000",
            keys.QUANTUM: "1024",
            keys.SAMPLE_RATE: "48000",
            keys.VIRTUAL_SINK_MODULE_IDS: "{}",
            # Version marker - this marks the config as v0.9.29+
            # Use empty string so _restore_window_geometry won't crash on base64 decode
            _VERSION_MARKER_KEY: "",
        }

        config_file = os.path.expanduser("~/.config/cable/config.ini")
        try:
            with open(config_file, "w") as f:
                config.write(f)
            logger.info(f"Created fresh config with version marker at {config_file}")
        except Exception as e:
            logger.error(f"Error creating fresh config: {e}")

    def migration_performed(self) -> bool:
        """Return True if config migration was performed on this launch."""
        return self._migration_performed

    def is_migration_dialog_shown(self) -> bool:
        """Return True if migration dialog has been shown to user (to avoid showing again)."""
        return self.get_bool_setting(keys.MIGRATION_DIALOG_SHOWN, False)

    def set_migration_dialog_shown(self) -> None:
        """Mark migration dialog as shown so it won't appear again."""
        self.set_bool_setting(keys.MIGRATION_DIALOG_SHOWN, True)
        self.flush()

    def show_migration_dialog_if_needed(
        self, parent_widget: Optional[Any] = None
    ) -> None:
        """Show migration dialog if config was migrated from an older version.

        Args:
            parent_widget: Parent widget for the QMessageBox (typically the main window).
        """
        if self._migration_performed and not self.is_migration_dialog_shown():
            from PyQt6.QtWidgets import QMessageBox

            backup_path = os.path.expanduser("~/.config/cable.backup")
            msg = (
                "This version is not compatible with the old config files.\n\n"
                f"Your existing config (~/.config/cable) has been backed up to\n{backup_path}.\n\n"
                "You won't see this message again."
            )
            QMessageBox.information(parent_widget, "Config Migration", msg)
            self.set_migration_dialog_shown()

    def _ensure_config_exists(self) -> None:
        """Ensure the config file exists with default values."""
        os.makedirs(self.config_dir, exist_ok=True)

        config = self._get_cached_config()

        default_values = {
            keys.QUANTUM_VALUES: "16,32,48,64,96,128,144,192,240,256,512,1024,2048,4096,8192",
            keys.SAMPLE_RATE_VALUES: "44100,48000,88200,96000,176400,192000",
            keys.QUANTUM: "1024",
            keys.SAMPLE_RATE: "48000",
            keys.VIRTUAL_SINK_MODULE_IDS: "{}",
        }

        added_defaults = False
        for key, value in default_values.items():
            if not config.has_option("DEFAULT", key):
                config.set("DEFAULT", key, value)
                self._changed_keys.add(key)
                added_defaults = True

        if added_defaults:
            self._dirty = True

    def ensure_config_exists(self) -> None:
        """Public method for compatibility."""
        self._ensure_config_exists()

    def _mark_dirty(self) -> None:
        """Mark config as having unsaved changes."""
        self._dirty = True

    def flush(self) -> None:
        """Write config to disk if there are unsaved changes."""
        if self._dirty and self._config is not None:
            # Merge specific changes to disk
            try:
                disk_config = configparser.ConfigParser(allow_no_value=True)
                if os.path.exists(self.config_file):
                    disk_config.read(self.config_file, encoding="utf-8")

                if "DEFAULT" not in disk_config:
                    disk_config["DEFAULT"] = {}

                for key in self._changed_keys:
                    if self._config.has_option("DEFAULT", key):
                        disk_config["DEFAULT"][key] = self._config.get("DEFAULT", key)
                    else:
                        if disk_config.has_option("DEFAULT", key):
                            disk_config.remove_option("DEFAULT", key)

                self._write_config_to_disk(disk_config)
                self._dirty = False
                self._changed_keys.clear()
            except Exception as e:
                logger.error(f"Error flushing config: {e}")

    def _write_config_to_disk(self, config: configparser.ConfigParser) -> None:
        """Actually write config to disk."""
        try:
            with open(self.config_file, "w", encoding="utf-8") as configfile:
                config.write(configfile)
        except Exception as e:
            logger.error(f"Error writing config file {self.config_file}: {e}")

    def write_config(self, config: configparser.ConfigParser) -> None:
        """Write configuration - now just marks dirty and updates cache."""
        self._config = config
        # Assumption: If write_config is called, we assume EVERYTHING might have changed or we rely on explicit set_* for tracking.
        # But legacy code might modify config object directly and pass it here.
        # Ideally we should diff, but for now let's assume this is mostly for full saves or initialization.
        # If this is used for partial updates, we might loose tracking.
        # However, looking at usage, it's mostly used internally or in specific save methods.
        # We will iterate over all keys in the new config and mark them as changed to be safe,
        # effectively doing a full overwrite of these keys on flush.
        if "DEFAULT" in config:
            for key in config["DEFAULT"]:
                self._changed_keys.add(key)
        self._dirty = True

    def get_list_from_config(self, key: str, default_list: List[int]) -> List[int]:
        """Get a list of active values from config (excluding commented out values), with fallback to default.

        Note: Uses the in-memory cache. If an external process modifies config.ini,
        changes won't be visible until the cache is reloaded (restart).
        """
        config = self._get_cached_config()

        if config.has_option("DEFAULT", key):
            value = config.get("DEFAULT", key)
            if value:
                parts = [item.strip() for item in value.split(",") if item.strip()]
                vals = []
                for p in parts:
                    if p and not p.startswith("#"):  # Ignore commented out values
                        try:
                            vals.append(int(p))
                        except ValueError:
                            continue
                if vals:
                    return vals
        return default_list

    def get_all_values_from_config(
        self, key: str, default_list: List[int]
    ) -> List[int]:
        """Get all values from config including commented out ones, with fallback to default list.

        Note: Uses the in-memory cache. See get_list_from_config for caching details.
        """
        config = self._get_cached_config()

        if config.has_option("DEFAULT", key):
            value = config.get("DEFAULT", key)
            if value:
                parts = [item.strip() for item in value.split(",") if item.strip()]
                vals = []
                for p in parts:
                    clean_val = p.lstrip("#")  # Remove leading # if present
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
            config = self._get_cached_config()
            if config.has_option("DEFAULT", key):
                return config.getint("DEFAULT", key)
        except (configparser.Error, ValueError):
            logger.debug("Failed to read config key '%s'", key)
        return default

    def get_str_setting(self, key: str, default: str = "") -> str:
        """Get string setting from config."""
        try:
            config = self._get_cached_config()
            if config.has_option("DEFAULT", key):
                return config.get("DEFAULT", key)
        except (configparser.Error, ValueError):
            logger.debug("Failed to read config key '%s'", key)
        return default

    def get_bool_setting(self, key: str, default: bool = False) -> bool:
        """Get boolean setting from config."""
        try:
            config = self._get_cached_config()
            if config.has_option("DEFAULT", key):
                return config.getboolean("DEFAULT", key)
        except (configparser.Error, ValueError):
            logger.debug("Failed to read config key '%s'", key)
        return default

    def set_int_setting(self, key: str, value: int) -> None:
        """Set integer setting in config."""
        config = self._get_cached_config()
        config["DEFAULT"][key] = str(value)
        self._changed_keys.add(key)
        self._mark_dirty()

    def set_str_setting(self, key: str, value: str) -> None:
        """Set string setting in config."""
        config = self._get_cached_config()
        config["DEFAULT"][key] = str(value) if value is not None else ""
        self._changed_keys.add(key)
        self._mark_dirty()

    def set_bool_setting(self, key: str, value: bool) -> None:
        """Set boolean setting in config."""
        config = self._get_cached_config()
        config["DEFAULT"][key] = "1" if value else "0"
        self._changed_keys.add(key)
        self._mark_dirty()

    def clear_settings(self, keys_to_clear: List[str]) -> None:
        """Removes specific keys from the config."""
        config = self._get_cached_config()
        if "DEFAULT" in config:
            for key in keys_to_clear:
                if key in config["DEFAULT"]:
                    del config["DEFAULT"][key]
                    self._changed_keys.add(key)
                    logger.info(f"Cleared setting: {key}")
        self._mark_dirty()

    def get_float_setting(self, key: str, default: float = 0.0) -> float:
        """Get float setting from config."""
        try:
            config = self._get_cached_config()
            if config.has_option("DEFAULT", key):
                return config.getfloat("DEFAULT", key)
        except (configparser.Error, ValueError):
            logger.debug("Failed to read config key '%s'", key)
        return default

    def set_float_setting(self, key: str, value: float) -> None:
        """Set float setting in config."""
        config = self._get_cached_config()
        config["DEFAULT"][key] = str(value)
        self._changed_keys.add(key)
        self._mark_dirty()

    # Short-name aliases used by Cables code
    get_bool = get_bool_setting
    set_bool = set_bool_setting
    get_int = get_int_setting
    set_int = set_int_setting
    set_str = set_str_setting

    def get_str(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get string setting, returning default (which may be None) if not found."""
        try:
            config = self._get_cached_config()
            if config.has_option("DEFAULT", key):
                return config.get("DEFAULT", key)
        except (configparser.Error, ValueError):
            logger.debug("Failed to read config key '%s'", key)
        return default

    def load_defaults(self) -> None:
        """Load Cables-specific defaults if not already present."""
        config = self._get_cached_config()
        if "DEFAULT" not in config:
            config["DEFAULT"] = {}

        cables_defaults = {
            keys.AUTO_REFRESH_ENABLED: "True",
            keys.COLLAPSE_ALL_ENABLED: "False",
            keys.PORT_LIST_FONT_SIZE: "10",
            keys.UNTANGLE_MODE: "0",
            keys.LAST_ACTIVE_TAB: "0",
            keys.LOAD_PRESET_STRICT_MODE: "False",
            keys.LOAD_PRESET_DAEMON_MODE: "False",
            keys.LOAD_PRESET_RESTORE_LAYOUT: "True",
            keys.MIDI_SPLITTER_SIZES: "400,300",
            keys.MIDI_MATRIX_SPLITTER_SIZES: "150,600",
            keys.MIDI_MATRIX_ZOOM_LEVEL: "10",
            keys.ENABLE_MIDI_MATRIX: "False",
            keys.AUDIO_MATRIX_SPLITTER_SIZES: "150,600",
            keys.AUDIO_MATRIX_ZOOM_LEVEL: "10",
            keys.ENABLE_AUDIO_MATRIX: "False",
        }

        added = False
        for key, value in cables_defaults.items():
            if not config.has_option("DEFAULT", key):
                config["DEFAULT"][key] = value
                self._changed_keys.add(key)
                added = True

        if added:
            self._mark_dirty()

    def _get_config_parser(self) -> configparser.ConfigParser:
        """Helper to get a ConfigParser instance, loading existing config."""
        config = configparser.ConfigParser()
        if os.path.exists(self.config_file):
            try:
                config.read(self.config_file)
            except configparser.ParsingError as e:
                logger.warning(
                    f"Warning: Could not parse existing config file {self.config_file}. Error: {e}"
                )
        return config

    def _write_config(self, config: configparser.ConfigParser) -> None:
        """Helper method to write config."""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, "w") as configfile:
                config.write(configfile)
        except Exception as e:
            logger.error(f"Error writing config file {self.config_file}: {e}")

    # Add DEFAULT_QUANTUM/SAMPLE_RATE_VALUES for compatibility
    DEFAULT_QUANTUM_VALUES = [
        16,
        32,
        48,
        64,
        96,
        128,
        144,
        192,
        240,
        256,
        512,
        1024,
        2048,
        4096,
        8192,
    ]
    DEFAULT_SAMPLE_RATE_VALUES = [44100, 48000, 88200, 96000, 176400, 192000]

    def load_settings(self) -> Dict[str, Any]:
        """Load saved settings from config file and return a dict."""
        settings = {
            "tray_enabled": False,
            "tray_click_opens_cables": True,
            "remember_settings": False,
            "restore_only_minimized": False,
            "apply_quantum_sample_rate_instantaneously": False,
            "show_setting_confirmation": False,
            "saved_quantum": 0,
            "saved_sample_rate": 0,
            "has_saved_quantum": False,
            "has_saved_sample_rate": False,
            "autostart_enabled": False,
            "check_updates_at_start": False,
            "appimage_path": None,
        }

        if os.path.exists(self.config_file):
            try:
                config = self._get_cached_config()

                settings["tray_enabled"] = config.getboolean(
                    "DEFAULT", keys.TRAY_ENABLED, fallback=False
                )
                settings["tray_click_opens_cables"] = config.getboolean(
                    "DEFAULT", keys.TRAY_CLICK_OPENS_CABLES, fallback=True
                )
                settings["remember_settings"] = config.getboolean(
                    "DEFAULT", keys.REMEMBER_SETTINGS, fallback=False
                )
                settings["restore_only_minimized"] = config.getboolean(
                    "DEFAULT", keys.RESTORE_ONLY_MINIMIZED, fallback=False
                )
                settings["apply_quantum_sample_rate_instantaneously"] = config.getboolean(
                    "DEFAULT",
                    keys.APPLY_QUANTUM_SAMPLE_RATE_INSTANTANEOUSLY,
                    fallback=False,
                )
                settings["show_setting_confirmation"] = config.getboolean(
                    "DEFAULT",
                    keys.SHOW_SETTING_CONFIRMATION,
                    fallback=False,
                )

                has_saved_quantum = config.has_option("DEFAULT", keys.SAVED_QUANTUM)
                has_saved_sample_rate = config.has_option(
                    "DEFAULT", keys.SAVED_SAMPLE_RATE
                )
                settings["has_saved_quantum"] = has_saved_quantum
                settings["has_saved_sample_rate"] = has_saved_sample_rate

                if has_saved_quantum:
                    settings["saved_quantum"] = config.getint(
                        "DEFAULT", keys.SAVED_QUANTUM, fallback=0
                    )
                if has_saved_sample_rate:
                    settings["saved_sample_rate"] = config.getint(
                        "DEFAULT", keys.SAVED_SAMPLE_RATE, fallback=0
                    )

                settings["autostart_enabled"] = config.getboolean(
                    "DEFAULT", keys.AUTOSTART_ENABLED, fallback=False
                )
                settings["check_updates_at_start"] = config.getboolean(
                    "DEFAULT", keys.CHECK_UPDATES_AT_START, fallback=False
                )

                appimage_path = config.get("DEFAULT", keys.APPIMAGE_PATH, fallback=None)
                if appimage_path and not os.path.exists(appimage_path):
                    logger.warning(
                        f"Warning: Configured AppImage path does not exist: {appimage_path}"
                    )
                    appimage_path = None
                settings["appimage_path"] = appimage_path

                logger.info(
                    f"Loaded tray_click_opens_cables from config: {settings['tray_click_opens_cables']}"
                )
                logger.info(
                    f"Loaded remember_settings: {settings['remember_settings']}"
                )
                logger.info(
                    f"Loaded autostart_enabled: {settings['autostart_enabled']}"
                )
                logger.info(
                    f"Loaded check_updates_at_start: {settings['check_updates_at_start']}"
                )
                logger.info(
                    f"Loaded restore_only_minimized: {settings['restore_only_minimized']}"
                )
                logger.info(
                    f"Loaded apply_quantum_sample_rate_instantaneously: {settings['apply_quantum_sample_rate_instantaneously']}"
                )
                logger.info(
                    f"Loaded show_setting_confirmation: {settings['show_setting_confirmation']}"
                )
                logger.info(f"Loaded appimage_path: {settings['appimage_path']}")
            except Exception as e:
                logger.error(f"Error loading settings: {e}")

        return settings

    def save_settings(self, settings_dict: Dict[str, Any]) -> None:
        """Save UI settings to config file (does not save audio settings)."""
        config = self._get_cached_config()

        if "DEFAULT" not in config:
            config["DEFAULT"] = {}

        config["DEFAULT"].update(
            {
                keys.TRAY_ENABLED: str(settings_dict.get("tray_enabled", False)),
                keys.TRAY_CLICK_OPENS_CABLES: str(
                    settings_dict.get("tray_click_opens_cables", True)
                ),
                keys.REMEMBER_SETTINGS: str(
                    settings_dict.get("remember_settings", False)
                ),
                keys.RESTORE_ONLY_MINIMIZED: str(
                    settings_dict.get("restore_only_minimized", False)
                ),
                keys.APPLY_QUANTUM_SAMPLE_RATE_INSTANTANEOUSLY: str(
                    settings_dict.get("apply_quantum_sample_rate_instantaneously", False)
                ),
                keys.SHOW_SETTING_CONFIRMATION: str(
                    settings_dict.get("show_setting_confirmation", False)
                ),
                keys.AUTOSTART_ENABLED: str(
                    settings_dict.get("autostart_enabled", False)
                ),
                keys.CHECK_UPDATES_AT_START: str(
                    settings_dict.get("check_updates_at_start", False)
                ),
                keys.APPIMAGE_PATH: str(settings_dict.get("appimage_path") or ""),
            }
        )

        for key in [
            keys.TRAY_ENABLED,
            keys.TRAY_CLICK_OPENS_CABLES,
            keys.REMEMBER_SETTINGS,
            keys.RESTORE_ONLY_MINIMIZED,
            keys.APPLY_QUANTUM_SAMPLE_RATE_INSTANTANEOUSLY,
            keys.SHOW_SETTING_CONFIRMATION,
            keys.AUTOSTART_ENABLED,
            keys.CHECK_UPDATES_AT_START,
            keys.APPIMAGE_PATH,
        ]:
            self._changed_keys.add(key)

        self._mark_dirty()
        self.flush()

    def toggle_remember_settings(
        self,
        remember: bool,
        current_quantum: Optional[int] = None,
        current_sample_rate: Optional[int] = None,
        quantum_was_reset: bool = False,
        sample_rate_was_reset: bool = False,
        tray_enabled: bool = False,
        tray_click_opens_cables: bool = True,
    ) -> Dict[str, Any]:
        """Handle remember settings toggle and persist to config."""
        config = self._get_cached_config()

        if "DEFAULT" not in config:
            config["DEFAULT"] = {}

        if remember:
            config["DEFAULT"][keys.REMEMBER_SETTINGS] = "True"

            if current_quantum and not quantum_was_reset:
                config["DEFAULT"][keys.SAVED_QUANTUM] = str(current_quantum)
                logger.info(f"Remember settings: Saved quantum {current_quantum}")

            if current_sample_rate and not sample_rate_was_reset:
                config["DEFAULT"][keys.SAVED_SAMPLE_RATE] = str(current_sample_rate)
                logger.info(
                    f"Remember settings: Saved sample rate {current_sample_rate}"
                )

            logger.info("Audio settings will be remembered and restored on startup")
        else:
            config["DEFAULT"][keys.REMEMBER_SETTINGS] = "False"
            if keys.SAVED_QUANTUM in config["DEFAULT"]:
                del config["DEFAULT"][keys.SAVED_QUANTUM]
            if keys.SAVED_SAMPLE_RATE in config["DEFAULT"]:
                del config["DEFAULT"][keys.SAVED_SAMPLE_RATE]
            if keys.RESTORE_ONLY_MINIMIZED in config["DEFAULT"]:
                del config["DEFAULT"][keys.RESTORE_ONLY_MINIMIZED]

            logger.info("Audio settings will not be remembered")

        config["DEFAULT"][keys.TRAY_ENABLED] = str(tray_enabled)
        config["DEFAULT"][keys.TRAY_CLICK_OPENS_CABLES] = str(tray_click_opens_cables)

        self._changed_keys.add(keys.TRAY_ENABLED)
        self._changed_keys.add(keys.TRAY_CLICK_OPENS_CABLES)
        self._changed_keys.add(keys.REMEMBER_SETTINGS)
        self._changed_keys.add(keys.SAVED_QUANTUM)
        self._changed_keys.add(keys.SAVED_SAMPLE_RATE)
        if not remember:
            self._changed_keys.add(keys.RESTORE_ONLY_MINIMIZED)

        self._mark_dirty()
        self.flush()

        return {"remember": remember, "clear_restore_only_minimized": not remember}

    def toggle_restore_only_minimized(self, restore_only_minimized: bool) -> None:
        """Handle restore only when auto-started checkbox state changes."""
        self.set_bool_setting(keys.RESTORE_ONLY_MINIMIZED, restore_only_minimized)
        self.flush()
        logger.info(f"Set restore_only_minimized to: {restore_only_minimized}")

    def ensure_config_lists(self) -> None:
        """Ensure config.ini contains quantum_values and sample_rate_values keys."""
        config = self._get_cached_config()

        if "DEFAULT" not in config:
            config["DEFAULT"] = {}

        config_updated = False

        if not config.has_option("DEFAULT", keys.QUANTUM_VALUES):
            config["DEFAULT"][keys.QUANTUM_VALUES] = ",".join(
                str(x) for x in self.DEFAULT_QUANTUM_VALUES
            )
            self._changed_keys.add(keys.QUANTUM_VALUES)
            config_updated = True

        if not config.has_option("DEFAULT", keys.SAMPLE_RATE_VALUES):
            config["DEFAULT"][keys.SAMPLE_RATE_VALUES] = ",".join(
                str(x) for x in self.DEFAULT_SAMPLE_RATE_VALUES
            )
            self._changed_keys.add(keys.SAMPLE_RATE_VALUES)
            config_updated = True

        if config_updated:
            self._mark_dirty()
            logger.info("Added missing default list(s) to config.ini")

    def toggle_startup_check(self, checked: bool) -> None:
        """Updates the startup check setting and saves it."""
        self.set_bool_setting(keys.CHECK_UPDATES_AT_START, checked)
        self.flush()
        logger.info(f"Set check_updates_at_start to: {checked}")

    def save_appimage_path(self, appimage_path: Optional[str]) -> None:
        """Save the AppImage path to config."""
        self.set_str_setting(keys.APPIMAGE_PATH, appimage_path or "")
        self.flush()
        logger.info(f"Saved AppImage path: {appimage_path}")

    def _save_audio_setting(
        self,
        setting_name: str,
        config_key: str,
        current_value: Optional[int],
        was_reset: bool,
    ) -> None:
        """Helper method to save quantum or sample rate setting to config file."""
        try:
            if was_reset:
                logger.debug(f"Skipping save of {setting_name} setting after reset")
                return

            config = self._get_cached_config()

            if "DEFAULT" not in config:
                config["DEFAULT"] = {}

            if current_value and current_value != "Edit List...":
                config["DEFAULT"][config_key] = str(current_value)
                logger.info(f"Saved {setting_name} setting: {current_value}")
            else:
                if config.has_option("DEFAULT", config_key):
                    config.remove_option("DEFAULT", config_key)
                    logger.info(
                        f"Removed invalid/empty {setting_name} setting ({config_key}) from config"
                    )

            self._changed_keys.add(config_key)
            self._mark_dirty()
            self.flush()
        except Exception as e:
            logger.error(f"Error saving {setting_name} setting: {e}")

    def save_quantum_setting(
        self, current_value: Optional[int] = None, was_reset: bool = False
    ) -> None:
        """Save only the quantum setting to config file."""
        self._save_audio_setting(
            setting_name="quantum",
            config_key=keys.SAVED_QUANTUM,
            current_value=current_value,
            was_reset=was_reset,
        )

    def save_sample_rate_setting(
        self, current_value: Optional[int] = None, was_reset: bool = False
    ) -> None:
        """Save only the sample rate setting to config file."""
        self._save_audio_setting(
            setting_name="sample rate",
            config_key=keys.SAVED_SAMPLE_RATE,
            current_value=current_value,
            was_reset=was_reset,
        )
