"""
Configuration keys for Cable application.

All config key strings used with ConfigManager should be defined here
as constants to avoid magic strings scattered across the codebase.
"""

__all__ = [
    # Audio Settings
    "QUANTUM_VALUES",
    "SAMPLE_RATE_VALUES",
    "QUANTUM",
    "SAMPLE_RATE",
    "VIRTUAL_SINK_MODULE_IDS",
    "UNIFIED_VIRTUAL_SINKS",
    "VIRTUAL_SINKS_RECREATE_AT_AUTOSTART",
    # App Settings
    "TRAY_ENABLED",
    "TRAY_CLICK_OPENS_CABLES",
    "REMEMBER_SETTINGS",
    "RESTORE_ONLY_MINIMIZED",
    "APPLY_QUANTUM_SAMPLE_RATE_INSTANTANEOUSLY",
    "SHOW_QUANTUM_SAMPLE_RATE_CONFIRMATION",
    "SAVED_QUANTUM",
    "SAVED_SAMPLE_RATE",
    "AUTOSTART_ENABLED",
    "CHECK_UPDATES_AT_START",
    "APPIMAGE_PATH",
    "INTEGRATE_CABLE_AND_CABLES",
    "VERBOSE_OUTPUT",
    # UI Settings
    "AUTO_REFRESH_ENABLED",
    "COLLAPSE_ALL_ENABLED",
    "PORT_LIST_FONT_SIZE",
    "MAX_FONT_SIZE",
    "MIN_FONT_SIZE",
    "UNTANGLE_MODE",
    "LAST_ACTIVE_TAB",
    "LOAD_PRESET_STRICT_MODE",
    "LOAD_PRESET_DAEMON_MODE",
    "LOAD_PRESET_RESTORE_LAYOUT",
    "MIDI_SPLITTER_SIZES",
    "MIDI_MATRIX_SPLITTER_SIZES",
    "MIDI_MATRIX_V_SPLITTER_SIZES",
    "MIDI_MATRIX_ZOOM_LEVEL",
    "ENABLE_MIDI_MATRIX",
    "AUDIO_MATRIX_SPLITTER_SIZES",
    "AUDIO_MATRIX_V_SPLITTER_SIZES",
    "AUDIO_MATRIX_ZOOM_LEVEL",
    "ENABLE_AUDIO_MATRIX",
    # Window Geometry
    "MAIN_WINDOW_GEOMETRY",
    "CONN_MANAGER_GEOMETRY",
    "EMBEDDED_COLUMN_WIDTH",
    "EMBEDDED_SETTINGS_VISIBLE",
    # Graph Settings
    "GRAPH_SPLIT_AUDIO_MIDI_CLIENTS",
    "GRAPH_UNTANGLE_VALUES",
    "GRAPH_AUTO_LAYOUT_SPLIT",
    "GRAPH_COLORED_CONNECTIONS",
    "GRAPH_WALLPAPER_PATH",
    "GRAPH_WALLPAPER_LAST_DIR",
    # Connection Settings
    "USE_STRAIGHT_LINES",
    "HIDE_MATRIX_SPLITTERS",
    "CONNECTION_LINE_THICKNESS",
    "CONNECTION_VIEW_INITIAL_WIDTH",
    "PWTOP_FONT_SIZE_PT",
    # Preset Settings
    "STARTUP_PRESET",
    "ACTIVE_PRESET",
    # Confirmation Dialogs
    "SHOW_HIDE_NODE_CONFIRMATION",
    "SHOW_UNLOAD_ALL_SINKS_CONFIRMATION",
    "DEFAULT_PRESET_SKIP_CONFIRMATION",
    # Migration Status
    "MIGRATION_DIALOG_SHOWN",
    "QUICK_SETTINGS",
    # Mixer Settings
    "ALSA_MIXER_ZOOM_LEVEL",
    "LAST_ALSA_MIXER_CARD_INDEX",
    # Tab Types
    "TAB_AUDIO",
    "TAB_MIDI",
    "TAB_MIDI_MATRIX",
    "TAB_AUDIO_MATRIX",
    "TAB_GRAPH",
    "TAB_PWTOP",
    "TAB_ALSA_MIXER",
    "TAB_LATENCY",
    "TAB_CABLE",
    "TAB_UNKNOWN",
    "TAB_DISPLAY_MAP",
]

# --- Audio Settings ---
QUANTUM_VALUES = "quantum_values"
SAMPLE_RATE_VALUES = "sample_rate_values"
QUANTUM = "quantum"
SAMPLE_RATE = "sample_rate"
VIRTUAL_SINK_MODULE_IDS = "virtual_sink_module_ids"
UNIFIED_VIRTUAL_SINKS = "unified_virtual_sinks"
VIRTUAL_SINKS_RECREATE_AT_AUTOSTART = "virtual_sinks_recreate_at_autostart"

# --- App Settings ---
TRAY_ENABLED = "tray_enabled"
TRAY_CLICK_OPENS_CABLES = "tray_click_opens_cables"
REMEMBER_SETTINGS = "remember_settings"
RESTORE_ONLY_MINIMIZED = "restore_only_minimized"
APPLY_QUANTUM_SAMPLE_RATE_INSTANTANEOUSLY = "apply_quantum_sample_rate_instantaneously"
SHOW_QUANTUM_SAMPLE_RATE_CONFIRMATION = "show_quantum_sample_rate_confirmation"
SAVED_QUANTUM = "saved_quantum"
SAVED_SAMPLE_RATE = "saved_sample_rate"
AUTOSTART_ENABLED = "autostart_enabled"
CHECK_UPDATES_AT_START = "check_updates_at_start"
APPIMAGE_PATH = "appimage_path"
INTEGRATE_CABLE_AND_CABLES = "integrate_cable_and_cables"
VERBOSE_OUTPUT = "verbose_output"

# --- UI Settings ---
AUTO_REFRESH_ENABLED = "auto_refresh_enabled"
COLLAPSE_ALL_ENABLED = "collapse_all_enabled"
PORT_LIST_FONT_SIZE = "port_list_font_size"
MAX_FONT_SIZE = "max_font_size"
MIN_FONT_SIZE = "min_font_size"
UNTANGLE_MODE = "untangle_mode"
LAST_ACTIVE_TAB = "last_active_tab"
LOAD_PRESET_STRICT_MODE = "load_preset_strict_mode"
LOAD_PRESET_DAEMON_MODE = "load_preset_daemon_mode"
LOAD_PRESET_RESTORE_LAYOUT = "load_preset_restore_layout"
MIDI_SPLITTER_SIZES = "midi_splitter_sizes"
MIDI_MATRIX_SPLITTER_SIZES = "midi_matrix_splitter_sizes"
MIDI_MATRIX_V_SPLITTER_SIZES = "midi_matrix_input_labels_splitter_sizes"
MIDI_MATRIX_ZOOM_LEVEL = "midi_matrix_zoom_level"
ENABLE_MIDI_MATRIX = "enable_midi_matrix"
AUDIO_MATRIX_SPLITTER_SIZES = "audio_matrix_splitter_sizes"
AUDIO_MATRIX_V_SPLITTER_SIZES = "audio_matrix_input_labels_splitter_sizes"
AUDIO_MATRIX_ZOOM_LEVEL = "audio_matrix_zoom_level"
ENABLE_AUDIO_MATRIX = "enable_audio_matrix"

# --- Window Geometry ---
MAIN_WINDOW_GEOMETRY = "MAIN_WINDOW_GEOMETRY"
CONN_MANAGER_GEOMETRY = "CONN_MANAGER_GEOMETRY"
EMBEDDED_COLUMN_WIDTH = "EMBEDDED_COLUMN_WIDTH"
EMBEDDED_SETTINGS_VISIBLE = "EMBEDDED_SETTINGS_VISIBLE"

# --- Graph Settings ---
GRAPH_SPLIT_AUDIO_MIDI_CLIENTS = "GRAPH_SPLIT_AUDIO_MIDI_CLIENTS"
GRAPH_UNTANGLE_VALUES = "GRAPH_UNTANGLE_VALUES"
GRAPH_AUTO_LAYOUT_SPLIT = "GRAPH_AUTO_LAYOUT_SPLIT"
GRAPH_COLORED_CONNECTIONS = "GRAPH_COLORED_CONNECTIONS"
GRAPH_WALLPAPER_PATH = "_graph_wallpaper_path"
GRAPH_WALLPAPER_LAST_DIR = "_graph_wallpaper_last_dir"

# --- Connection Settings ---
USE_STRAIGHT_LINES = "use_straight_lines"
HIDE_MATRIX_SPLITTERS = "hide_matrix_splitters"
CONNECTION_LINE_THICKNESS = "CONNECTION_LINE_THICKNESS"
CONNECTION_VIEW_INITIAL_WIDTH = "CONNECTION_VIEW_INITIAL_WIDTH"
PWTOP_FONT_SIZE_PT = "PWTOP_FONT_SIZE_PT"

# --- Preset Settings ---
STARTUP_PRESET = "startup_preset"
ACTIVE_PRESET = "active_preset"

# --- Confirmation Dialogs ---
SHOW_HIDE_NODE_CONFIRMATION = "show_hide_node_confirmation"
SHOW_UNLOAD_ALL_SINKS_CONFIRMATION = "show_unload_all_sinks_confirmation"
DEFAULT_PRESET_SKIP_CONFIRMATION = "default_preset_skip_confirmation"

# --- Quick Settings ---
QUICK_SETTINGS = "quick_settings"

# --- Mixer Settings ---
ALSA_MIXER_ZOOM_LEVEL = "alsa_mixer_zoom_level"
LAST_ALSA_MIXER_CARD_INDEX = "last_alsa_mixer_card_index"

# --- Migration Status ---
MIGRATION_DIALOG_SHOWN = "migration_dialog_shown"

# --- Tab Types ---
TAB_AUDIO = "audio"
TAB_MIDI = "midi"
TAB_MIDI_MATRIX = "midi_matrix"
TAB_AUDIO_MATRIX = "audio_matrix"
TAB_GRAPH = "graph"
TAB_PWTOP = "pwtop"
TAB_ALSA_MIXER = "alsa_mixer"
TAB_LATENCY = "latency"
TAB_CABLE = "cable"
TAB_UNKNOWN = "unknown"

# Mapping from display tab names to internal tab type constants
TAB_DISPLAY_MAP = {
    "Audio": TAB_AUDIO,
    "MIDI": TAB_MIDI,
    "MIDI Matrix": TAB_MIDI_MATRIX,
    "Audio Matrix": TAB_AUDIO_MATRIX,
    "Graph": TAB_GRAPH,
    "pw-top": TAB_PWTOP,
    "ALSA Mixer": TAB_ALSA_MIXER,
    "Latency Test": TAB_LATENCY,
    "Cable": TAB_CABLE,
}
