#!/usr/bin/env python3
"""
Cables - A JACK/PipeWire connection manager
"""

import sys
import argparse
import os
import types
import jack
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QCheckBox,
    QPushButton,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QToolBar,
    QToolButton,
)
from PyQt6.QtCore import (
    Qt,
    QMimeData,
    QPointF,
    QRectF,
    QTimer,
    QSize,
    QRect,
    QProcess,
    QPoint,
    pyqtSlot,
    QObject,
    QEvent,
    QFileSystemWatcher,
)
from PyQt6.QtGui import (
    QGuiApplication,
    QColor,
    QPalette,
    QFont,
    QKeySequence,
    QAction,
    QTextCursor,
    QPen,
    QBrush,
)
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Union, Set, Tuple

import logging

logger = logging.getLogger(__name__)

# Import our modules
from cable_core.config import ConfigManager
from cables.config.enhanced_preset_manager import EnhancedPresetManager
from cables.features.connection_history import ConnectionHistory
from cables.features.preset_handler import PresetHandler
from cables.ui.tab_ui_manager import TabUIManager
from cables.jack_connection_handler import JackConnectionHandler
from cables.highlight_manager import HighlightManager
from cables.ui_state_manager import UIStateManager
from cables.action_manager import ActionManager
from cables.port_manager import PortManager
from cables.interaction_manager import InteractionManager
from cables.tab_manager import TabManager
from cables.unified_sink_manager import UnifiedSinkManager
from cable_core import app_config
from cable_core import config_keys as keys
from cable_core.theme import get_theme_manager
from cables.features.mixer import AlsMixerApp
from cables.features.node_visibility_manager import NodeVisibilityManager
from cables.ui.ui_manager import UIManager
from cables.connection_visualizer import ConnectionVisualizer
from cables import selection_utils as sel
from cables import window_state as win_state
from cables import connection_operations as conn_ops
from cables import stylesheet_manager as styles
from cables import fullscreen_controller as fs_ctrl
from cables.cm_window_chrome import WindowChromeController
from cables.cm_theme_sync import ThemeSyncController
from cables.cm_port_refresh import PortRefreshController
from cables.cm_boot import BootOrchestrator

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QTreeWidgetItem, QGraphicsScene, QGraphicsView


class JackConnectionManager(QMainWindow):
    """
    Main application window for the JACK/PipeWire connection manager.

    This class manages the UI and functionality for connecting and
    disconnecting JACK/PipeWire ports, as well as managing presets.
    """

    def __init__(self, load_startup_preset: bool = False, integrated_override: Optional[bool] = None) -> None:
        """Initialize the JackConnectionManager.

        Args:
            load_startup_preset: If True, load the configured startup preset on init.
                                 Should be True for --minimized and headless modes.
            integrated_override: If not None, overrides the config-based integrated-mode
                                 setting (True = show Cable tab, None = read from config).
        """
        super().__init__()
        self._load_startup_preset = load_startup_preset
        self._integrated_override: Optional[bool] = integrated_override

        self._is_fullscreen = False
        self._widgets_original_visibility = {}  # For storing visibility of main UI chrome

        # Seam 4 collaborator: window-chrome behaviour (fullscreen, geometry,
        # visibility dialog, the ActivationChange branch of changeEvent).
        # Holds a reference to self so its methods see the same attributes
        # external callers do — no state duplication. Instantiated here, at
        # the very top of __init__, so it's available before any _init_*
        # method (e.g. _init_window -> _restore_window_geometry) delegates
        # to it.
        self._window_chrome = WindowChromeController(self)

        # Seam 3 collaborator: theme-sync behaviour (on_theme_changed 8-step
        # orchestrator, config-watcher debounce + reload, palette-change
        # branch of changeEvent). Instantiated before _connect_internal_signals
        # runs, since that wires theme_manager.theme_changed ->
        # self._on_theme_changed (which now delegates here).
        self._theme_sync = ThemeSyncController(self)

        # Seam 2 collaborator: port-tree refresh behaviour (refresh_ports,
        # _refresh_single_port_type, _on_jack_reconnected, _on_port_registered/
        # unregistered, _connect_jack_signals_to_connection_views,
        # refresh_visualizations, update_connections/midi, unified sink helpers).
        # Instantiated alongside _window_chrome and _theme_sync so all
        # seam methods are available before _init_* runs.
        self._port_refresh = PortRefreshController(self)

        # Seam 1 collaborator: boot-orchestration behaviour (_connect_internal_signals
        # decomposed into 3 sub-methods, _post_init_cleanup, _recreate_virtual_sinks,
        # _load_startup_preset, _init_interaction_handlers, _activate_jack,
        # _connect_action_manager_signals). Instantiated before _init_* calls.
        self._boot = BootOrchestrator(self)

        # Pre-initialize component references (set to actual values in _init_* methods)
        self.config_manager: Optional[ConfigManager] = None
        self.preset_manager: Optional[EnhancedPresetManager] = None
        self.preset_handler: Optional[PresetHandler] = None
        self.ui_manager: Optional[UIManager] = None
        self.connection_visualizer: Optional[ConnectionVisualizer] = None
        self.jack_handler: Optional[JackConnectionHandler] = None
        self.action_manager: Optional[ActionManager] = None
        self.tab_manager: Optional[TabManager] = None
        self.ui_state_manager: Optional[UIStateManager] = None
        self.highlight_manager: Optional[HighlightManager] = None
        self.port_manager: Optional[PortManager] = None
        self.connection_history: Optional[ConnectionHistory] = None
        self.unified_sink_manager: Optional[UnifiedSinkManager] = None
        self.node_visibility_manager: Optional[NodeVisibilityManager] = None
        self.graph_main_window = None
        self.midi_matrix_widget = None
        self.audio_matrix_widget = None
        self.midi_matrix_controls_widget = None
        self.audio_matrix_controls_widget = None
        self.pwtop_monitor = None
        self.latency_tester = None
        self.alsa_mixer_app = None
        self.cable_widget = None
        self.interaction_manager = None
        self.input_tree = None
        self.output_tree = None
        self.midi_input_tree = None
        self.midi_output_tree = None
        self.connection_view = None
        self.midi_connection_view = None
        self._jack_service = None
        self.graph_scene = None

        # Initialize all components in logical groups
        logger.info("JackConnectionManager.__init__: starting config managers init...")
        self._init_config_managers()
        logger.info("JackConnectionManager.__init__: starting window init...")
        self._init_window()
        logger.info("JackConnectionManager.__init__: starting jack client init...")
        self._init_jack_client()
        logger.info("JackConnectionManager.__init__: starting core services init...")
        self._init_core_services()
        logger.info("JackConnectionManager.__init__: starting ui manager init...")
        self._init_ui_manager()
        logger.info("JackConnectionManager.__init__: starting action manager init...")
        self._init_action_manager()
        logger.info("JackConnectionManager.__init__: starting ui components init...")
        self._init_ui_components()
        logger.info("JackConnectionManager.__init__: starting managers init...")
        self._init_managers()
        logger.info("JackConnectionManager.__init__: starting connect internal signals...")
        self._connect_internal_signals()
        logger.info("JackConnectionManager.__init__: starting activate jack...")
        self._activate_jack()
        logger.info("JackConnectionManager.__init__: starting post init cleanup...")
        self._post_init_cleanup()
        logger.info("JackConnectionManager.__init__: starting recreate virtual sinks if autostart...")
        self._recreate_virtual_sinks_if_autostart()
        logger.info("JackConnectionManager.__init__: starting load startup preset if configured...")
        self._load_startup_preset_if_configured()
        logger.info("JackConnectionManager.__init__: starting init interaction handlers...")
        self._init_interaction_handlers()
        logger.info("JackConnectionManager.__init__: starting init node visibility...")
        self._init_node_visibility()
        logger.info("JackConnectionManager.__init__: logical groups initialization completed.")

        # Post-startup theme-reactive wiring: palette-settle timer, config.ini
        # watcher, and the debounce timer that re-reads the theme after a burst
        # of writes. Extracted to a helper for cohesion; see
        # _init_theme_timers_and_watcher.
        self._init_theme_timers_and_watcher()
        logger.info("JackConnectionManager.__init__: config watcher for live theme sync started.")

    def _init_theme_timers_and_watcher(self) -> None:
        """Set up the post-startup palette-settle timer and the config.ini watcher.

        Creates three ``self`` attributes:

        - ``_post_startup_theme_timer``: one-shot 1.5s timer that asks the theme
          manager to re-check the system palette after startup, correcting any
          wrong initial theme detection.
        - ``_theme_config_watcher``: ``QFileSystemWatcher`` watching
          ``~/.config/cable/config.ini`` (when it exists) so live forced-theme
          changes made by Cable (non-integrated mode) are picked up immediately.
        - ``_theme_reload_timer``: one-shot 500ms debounce timer so a burst of
          writes to config.ini triggers a single theme re-read.

        Behavior is identical to the equivalent block previously inlined in
        ``__init__``; it was extracted only for cohesion. Reads no parameters
        beyond ``self`` and returns nothing.
        """
        # Post-startup palette-settle timer: correct wrong initial theme detection
        self._post_startup_theme_timer = QTimer(self)
        self._post_startup_theme_timer.setSingleShot(True)
        self._post_startup_theme_timer.setInterval(1500)
        self._post_startup_theme_timer.timeout.connect(
            lambda: get_theme_manager().check_theme_changed()
        )
        self._post_startup_theme_timer.start()
        logger.info("JackConnectionManager.__init__: post-startup palette-settle timer started.")

        # Watch config.ini for live theme changes from Cable (non-integrated mode).
        # When Cable changes the forced theme via Other Settings, it writes to
        # config.ini.  This watcher detects the write so Cables can re-read and
        # apply the new theme immediately, keeping both windows in sync.
        self._theme_config_watcher = QFileSystemWatcher(self)
        self._theme_config_watcher.fileChanged.connect(self._on_config_file_changed)
        config_ini_path = os.path.expanduser("~/.config/cable/config.ini")
        if os.path.exists(config_ini_path):
            self._theme_config_watcher.addPath(config_ini_path)

        # Debounce timer: config.ini may be written in quick bursts (save +
        # flush).  We wait 500ms of silence before re-reading the theme.
        self._theme_reload_timer = QTimer(self)
        self._theme_reload_timer.setSingleShot(True)
        self._theme_reload_timer.setInterval(500)
        self._theme_reload_timer.timeout.connect(self._reload_theme_from_config)

    def _init_config_managers(self) -> None:
        """Initialize configuration and preset managers."""
        self.config_manager = ConfigManager()
        self.config_manager.load_defaults()

        # Check if migration happened and show dialog if needed
        self.config_manager.show_migration_dialog_if_needed(parent_widget=self)

        self.preset_manager = EnhancedPresetManager()
        self.preset_handler = PresetHandler(self)

    def _init_window(self) -> None:
        """Set up the main window geometry and properties."""
        self.setWindowTitle("Cables")
        self._restore_window_geometry()
        self.initial_middle_width = 250
        self.port_type = keys.TAB_AUDIO

    def _init_jack_client(self) -> None:
        """Initialize JACK client and connection handler."""
        self.client = jack.Client("ConnectionManager")
        self.jack_handler = JackConnectionHandler(self.client, self)

        # Share client with JackService and let it handle callbacks
        from cables.jack_service import get_jack_service

        self._jack_service = get_jack_service()
        self._jack_service.set_client(self.client, setup_callbacks=True)

    def _init_core_services(self) -> None:
        """Initialize core services: history, environment detection, unified sink manager."""
        self.connection_history = ConnectionHistory()
        self.flatpak_env = os.path.exists("/.flatpak-info")
        self.unified_sink_manager = UnifiedSinkManager(self.config_manager)

    def _init_ui_manager(self) -> None:
        """Initialize UI Manager and Connection Visualizer."""
        self.ui_manager = UIManager(self, self.config_manager)
        self.connection_visualizer = ConnectionVisualizer(
            self.client, self.ui_manager, self.config_manager
        )

    def _init_action_manager(self) -> None:
        """Initialize the action manager for shortcuts and actions."""
        self.ui_elements = {}

        # Create callbacks for ActionManager (decoupled from main_window reference)
        def get_current_tab_type() -> str:
            """Get the current tab type as a string."""
            if self.ui_manager is None or not self.ui_manager.tab_widget:
                return keys.TAB_UNKNOWN
            current_index = self.ui_manager.tab_widget.currentIndex()
            tab_text = self.ui_manager.tab_widget.tabText(current_index)
            return keys.TAB_DISPLAY_MAP.get(tab_text, keys.TAB_UNKNOWN)

        def get_colors() -> dict:
            """Get the current color scheme."""
            return {
                "text": self.ui_manager.text_color,
                "highlight": self.ui_manager.highlight_color,
                "background": self.ui_manager.background_color,
            }

        self.action_manager = ActionManager(
            connection_handler=self.jack_handler,
            preset_handler=self.preset_handler,
            get_current_tab_type=get_current_tab_type,
            get_graph_main_window=self._get_graph_main_window,
            get_colors=get_colors,
            get_connection_history=lambda: self.connection_history,
            notify_history_changed=self.notify_connection_history_changed,
        )

    def _init_ui_components(self) -> None:
        """Initialize UI components: UI setup, highlight manager, tab manager, port manager."""
        # Initialize UI Manager first to create UI elements
        self.ui_manager._setup_ui()

        # Initialize highlight manager with UI manager colors
        self.highlight_manager = HighlightManager(
            input_tree=None,
            output_tree=None,
            midi_input_tree=None,
            midi_output_tree=None,
            client=self.client,
            colors={
                "text": self.ui_manager.text_color,
                "background": self.ui_manager.background_color,
                "highlight": self.ui_manager.highlight_color,
                "auto_highlight": self.ui_manager.auto_highlight_color,
                "drag_highlight": self.ui_manager.drag_highlight_color,
            },
        )

        # Initialize Tab Manager to set up tabs and create tree widgets
        self.tab_manager = TabManager(self)
        self.tab_manager.setup_tabs(integrated_override=self._integrated_override)

        # Now create Port Manager after trees are available
        self.port_manager = PortManager(
            connection_manager=self,
            jack_client=self.client,
            input_filter_edit=self.ui_manager.input_filter_edit,
            output_filter_edit=self.ui_manager.output_filter_edit,
        )

        # Set the tree references created by TabManager
        self.port_manager.set_trees(
            input_tree=self.input_tree,
            output_tree=self.output_tree,
            midi_input_tree=self.midi_input_tree,
            midi_output_tree=self.midi_output_tree,
        )

        # Update highlight_manager with the created trees
        self.highlight_manager.set_trees(
            input_tree=self.input_tree,
            output_tree=self.output_tree,
            midi_input_tree=self.midi_input_tree,
            midi_output_tree=self.midi_output_tree,
        )

    def _init_managers(self) -> None:
        """Initialize UI state manager and update UI elements."""
        # Initialize UI State Manager after trees are set up
        # Use callbacks instead of main_window reference for decoupling
        self.ui_state_manager = UIStateManager(
            parent=self,
            config_manager=self.config_manager,
            collapse_checkbox=self.ui_manager.collapse_all_button,
            untangle_button=self.ui_manager.untangle_button,
            increase_font_button=self.ui_manager.zoom_in_button,
            decrease_font_button=self.ui_manager.zoom_out_button,
            input_tree=self.input_tree,
            output_tree=self.output_tree,
            midi_input_tree=self.midi_input_tree,
            midi_output_tree=self.midi_output_tree,
            connection_view=self.connection_view,
            midi_connection_view=self.midi_connection_view,
            refresh_visualizations_callback=self.refresh_visualizations,
            refresh_ports_callback=self.refresh_ports,
            animate_button_callback=self._animate_button_press,
            get_port_type=lambda: self.port_type,
        )

    def _connect_internal_signals(self) -> None:
        """Connect internal signals between components.

        Delegates to :class:`cables.cm_boot.BootOrchestrator` which
        decomposes the CCN-14 body into ``_connect_jack_signals``,
        ``_connect_ui_signals``, and ``_connect_action_signals``.
        """
        self._boot.connect_internal_signals()

    def _activate_jack(self) -> None:
        """Delegates to :class:`cables.cm_boot.BootOrchestrator`."""
        self._boot.activate_jack()

    def _post_init_cleanup(self) -> None:
        """Delegates to :class:`cables.cm_boot.BootOrchestrator`."""
        self._boot.post_init_cleanup()

    def _recreate_virtual_sinks_if_autostart(self) -> None:
        """Delegates to :class:`cables.cm_boot.BootOrchestrator`."""
        self._boot.recreate_virtual_sinks_if_autostart()

    def _update_virtual_sink_module_id(self, sink_name: str, module_id: str) -> None:
        """Update the module ID in VIRTUAL_SINK_MODULE_IDS config.

        Delegates to ``UnifiedSinkManager.update_module_id()``.
        """
        self.unified_sink_manager.update_module_id(
            sink_name, module_id, self.config_manager
        )

    def _load_startup_preset_if_configured(self) -> None:
        """Delegates to :class:`cables.cm_boot.BootOrchestrator`."""
        self._boot.load_startup_preset_if_configured()

    def _init_interaction_handlers(self) -> None:
        """Delegates to :class:`cables.cm_boot.BootOrchestrator`."""
        self._boot.init_interaction_handlers()

    def _init_node_visibility(self) -> None:
        """Initialize node visibility manager and connect tree signals."""
        self.node_visibility_manager = NodeVisibilityManager(self, self.config_manager)

        # Pass node visibility manager to port_manager
        if self.port_manager is not None:
            self.port_manager.set_node_visibility_manager(self.node_visibility_manager)

        # Pass node visibility manager to midi_matrix_widget
        if self.midi_matrix_widget is not None:
            self.midi_matrix_widget.set_node_visibility_manager(
                self.node_visibility_manager
            )

        # Pass node visibility manager to audio_matrix_widget
        if self.audio_matrix_widget is not None:
            self.audio_matrix_widget.set_node_visibility_manager(
                self.node_visibility_manager
            )

        self._connect_tree_click_handlers()

    def _connect_tree_click_handlers(self) -> None:
        """Connect audio and MIDI tree clicks to the interaction manager."""
        tree_handlers = (
            (self.input_tree, False),
            (self.output_tree, False),
            (self.midi_input_tree, True),
            (self.midi_output_tree, True),
        )
        for tree, is_midi in tree_handlers:
            if tree is not None:
                tree.itemClicked.connect(
                    lambda item, col, tree=tree, is_midi=is_midi: self.interaction_manager.handle_port_click(
                        item, tree, is_midi
                    )
                )

    # === Graph Access Helper Methods ===
    # These methods simplify the common hasattr guard patterns used throughout the codebase

    def _get_graph_main_window(self) -> Optional[Any]:
        """Get the graph main window if available, None otherwise.

        Returns:
            The graph_main_window instance if available and valid, None otherwise.
        """
        if self.graph_main_window is not None:
            return self.graph_main_window
        return None

    def _get_graph_scene(self) -> Optional[Any]:
        """Get the graph scene if available, None otherwise.

        Returns:
            The graph_main_window.scene instance if available and valid, None otherwise.
        """
        graph_window = self._get_graph_main_window()
        if graph_window:
            scene = getattr(graph_window, "scene", None)
            if scene:
                return scene
        return None

    def _get_graph_view(self) -> Optional[Any]:
        """Get the graph view if available, None otherwise.

        Returns:
            The graph_main_window.view instance if available and valid, None otherwise.
        """
        graph_window = self._get_graph_main_window()
        if graph_window:
            view = getattr(graph_window, "view", None)
            if view:
                return view
        return None

    def _has_graph_scene(self) -> bool:
        """Check if the graph scene is available.

        Returns:
            True if graph_main_window.scene is available, False otherwise.
        """
        return self._get_graph_scene() is not None

    def _handle_unified_port_added(
        self,
        port_name: str,
        client_name: str,
        flags: int,
        type_str: str,
        is_input: bool,
    ) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.handle_unified_port_added(
            port_name, client_name, flags, type_str, is_input
        )

    def disconnect_all_unified(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.disconnect_all_unified()

    def reconnect_all_unified(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.reconnect_all_unified()

    def _restore_window_geometry(self) -> None:
        """Restore saved window geometry, or apply first-launch defaults.

        Delegates to :class:`cables.cm_window_chrome.WindowChromeController`
        (Seam 4 extraction). Body preserved byte-identical inside the
        controller; this is now a thin delegator for the frozen public API.
        """
        self._window_chrome.restore_window_geometry()

    def _save_window_geometry(self) -> None:
        """Persist current window geometry to config.

        Delegates to :class:`cables.cm_window_chrome.WindowChromeController`
        (Seam 4 extraction). Thin delegator for the frozen public API.
        """
        self._window_chrome.save_window_geometry()

    def closeEvent(self, event: Any) -> None:
        """Handle window close event - hide to tray if Cable is embedded and tray is enabled."""
        self._save_window_geometry()
        # Check if Cable is embedded and has tray enabled
        if self.cable_widget is not None:
            cable = self.cable_widget
            if (
                cable.tray_enabled
                and cable.tray_manager.tray_icon
                and cable.tray_manager.tray_icon.isVisible()
            ):
                # Hide to tray instead of closing
                event.ignore()
                self.hide()
                return

        # Stop aj-snapshot daemon on quit
        self._cleanup_on_quit()

        # Otherwise, close normally
        event.accept()

    def _cleanup_on_quit(self) -> None:
        """Cleanup resources when the application is quitting."""
        # Close JackService before Qt tears down QObjects to stop JACK callbacks
        if self._jack_service is not None:
            try:
                self._jack_service.close()
            except Exception:
                pass
        if self.preset_manager is not None:
            self.preset_manager.stop_daemon_mode()
        if self.config_manager is not None:
            self.config_manager.flush()
        # Flush graph node positions
        if self.graph_scene is not None:
            node_config_mgr = getattr(self.graph_scene, "node_config_manager", None)
            if node_config_mgr:
                node_config_mgr.flush()

    def _connect_action_manager_signals(self) -> None:
        """Delegates to :class:`cables.cm_boot.BootOrchestrator`."""
        self._boot.connect_action_manager_signals()

    def _on_connect_requested(self, is_midi: bool) -> None:
        """Handle connect request from ActionManager."""
        if is_midi:
            self.make_midi_connection_selected()
        else:
            self.make_connection_selected()

    def _on_disconnect_requested(self, is_midi: bool) -> None:
        """Handle disconnect request from ActionManager."""
        if is_midi:
            self.break_midi_connection_selected()
        else:
            self.break_connection_selected()

    def _on_jack_reconnected(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.on_jack_reconnected()

    def _connect_jack_signals_to_connection_views(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.connect_jack_signals_to_connection_views()

    def refresh_visualizations(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.refresh_visualizations()

    def _update_global_zoom_action_state(self, current_tab_index: int) -> None:
        """Enable/disable global zoom actions based on the active tab."""
        tab_widget = getattr(self.ui_manager, "tab_widget", None)
        if not tab_widget or self.action_manager is None:
            return

        current_widget = tab_widget.widget(current_tab_index)
        alsa_mixer_tab = getattr(self.ui_manager, "alsa_mixer_tab_widget", None)
        is_alsa_mixer_tab_active = current_widget == alsa_mixer_tab

        zoom_in_action = getattr(self.action_manager, "zoom_in_action", None)
        if zoom_in_action:
            zoom_in_action.setEnabled(not is_alsa_mixer_tab_active)
        zoom_out_action = getattr(self.action_manager, "zoom_out_action", None)
        if zoom_out_action:
            zoom_out_action.setEnabled(not is_alsa_mixer_tab_active)

    @property
    def text_color(self) -> QColor:
        return self.ui_manager.text_color

    @property
    def background_color(self) -> QColor:
        return self.ui_manager.background_color

    @property
    def highlight_color(self) -> QColor:
        return self.ui_manager.highlight_color

    @property
    def button_color(self) -> QColor:
        return self.ui_manager.button_color

    @property
    def dark_mode(self) -> bool:
        return self.ui_manager.dark_mode

    def _refresh_single_port_type(self, port_type_to_refresh: str) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.refresh_single_port_type(port_type_to_refresh)

    def refresh_ports(
        self, refresh_all: bool = False, from_shortcut: bool = False
    ) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.refresh_ports(refresh_all=refresh_all, from_shortcut=from_shortcut)

    def _get_selected_item_info(
        self, tree_widget: QTreeWidget
    ) -> Tuple[Optional[str], Optional[bool]]:
        return sel.get_selected_item_info(tree_widget)

    def _restore_selection(
        self,
        tree_widget: QTreeWidget,
        selection_info: Tuple[Optional[str], Optional[bool]],
    ) -> None:
        sel.restore_selection(tree_widget, selection_info)

    def start_startup_refresh(self) -> None:
        self.startup_refresh_count = 0
        self.startup_refresh_timer = QTimer()
        self.startup_refresh_timer.timeout.connect(self.startup_refresh)
        self.startup_refresh_timer.start(1)

    def startup_refresh(self) -> None:
        original_port_type = self.port_type

        self.port_type = keys.TAB_AUDIO
        self.refresh_ports()

        self.port_type = keys.TAB_MIDI
        self.refresh_ports()

        self.port_type = original_port_type

        self.refresh_visualizations()

        self.startup_refresh_count += 1
        if self.startup_refresh_count >= 3:
            self.startup_refresh_timer.stop()

            self.ui_state_manager.apply_collapse_state_to_all_trees(
                collapse=self.ui_state_manager.collapse_checkbox.isChecked()
            )

    def changeEvent(self, event: Any) -> None:
        # Dispatch to the appropriate Seam collaborator.
        # - ActivationChange → WindowChromeController (Seam 4)
        # - PaletteChange / ApplicationPaletteChange → ThemeSyncController (Seam 3)
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange:
            self._window_chrome.on_activation_change()
        elif event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self._theme_sync.on_palette_change()

    def _on_theme_changed(self) -> None:
        """Full theme-change orchestrator — called once per confirmed change.

        Delegates to :class:`cables.cm_theme_sync.ThemeSyncController`
        (Seam 3 extraction). The 8-step body is preserved byte-identical
        inside the controller; this is now a thin delegator for the frozen
        public API (wired into ``theme_manager.theme_changed`` during
        ``_connect_internal_signals``).
        """
        self._theme_sync.on_theme_changed()
        if getattr(self, 'latency_raw_output_checkbox', None) is not None:
            self.latency_raw_output_checkbox.update()

    def _on_config_file_changed(self, path: str) -> None:
        """Called by QFileSystemWatcher when config.ini is modified.

        Delegates to :class:`cables.cm_theme_sync.ThemeSyncController`
        (Seam 3 extraction). Thin delegator for the QFileSystemWatcher slot.
        """
        self._theme_sync.on_config_file_changed(path)

    def _reload_theme_from_config(self) -> None:
        """Re-read force_theme from config.ini and apply if changed.

        Delegates to :class:`cables.cm_theme_sync.ThemeSyncController`
        (Seam 3 extraction). Thin delegator for the debounce-timer slot.
        """
        self._theme_sync.reload_theme_from_config()

    def _refresh_tab_stylesheets(self) -> None:
        """Re-apply every tab stylesheet that stores colors at init time.

        Delegates to :class:`cables.cm_theme_sync.ThemeSyncController`
        (Seam 3 extraction). Thin delegator for the frozen public API
        (also called externally by other tab components).
        """
        self._theme_sync.refresh_tab_stylesheets()

    def _animate_button_press(self, button: Optional[QPushButton]) -> None:
        """Animate a UI button press.

        Delegates to :class:`cables.cm_theme_sync.ThemeSyncController`
        (Seam 3 extraction). Thin delegator.
        """
        self._theme_sync.animate_button_press(button)

    def _on_port_registered(self, port_name: str, is_input: bool) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.on_port_registered(port_name, is_input)

    def _on_port_unregistered(self, port_name: str, is_input: bool) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.on_port_unregistered(port_name, is_input)

    def make_connection_selected(self) -> None:
        sel.make_connection_selected(self)

    def make_midi_connection_selected(self) -> None:
        sel.make_midi_connection_selected(self)

    def break_connection_selected(self) -> None:
        sel.break_connection_selected(self)

    def break_midi_connection_selected(self) -> None:
        sel.break_midi_connection_selected(self)

    def _get_ports_from_selected_items(self, tree_widget: QTreeWidget) -> List[str]:
        return sel.get_ports_from_selected_items(tree_widget)

    def _analyze_tree_selection(
        self, tree_widget: QTreeWidget
    ) -> Dict[str, Any]:
        return sel.analyze_tree_selection(tree_widget)

    def _compute_sequential_pairs(
        self,
        output_info: Dict[str, Any],
        input_info: Dict[str, Any],
        output_tree: QTreeWidget,
        input_tree: QTreeWidget,
    ) -> Optional[List[Tuple[str, str]]]:
        return sel.compute_sequential_pairs(
            output_info, input_info, output_tree, input_tree
        )

    def update_connection_buttons(self) -> None:
        sel.update_port_connection_buttons(
            self,
            self.input_tree,
            self.output_tree,
            self.connect_button,
            self.disconnect_button,
            connect_action=getattr(self.action_manager, "audio_connect_action", None),
            disconnect_action=getattr(
                self.action_manager, "audio_disconnect_action", None
            ),
        )

    def update_midi_connection_buttons(self) -> None:
        sel.update_port_connection_buttons(
            self,
            self.midi_input_tree,
            self.midi_output_tree,
            self.midi_connect_button,
            self.midi_disconnect_button,
            connect_action=getattr(self.action_manager, "midi_connect_action", None),
            disconnect_action=getattr(
                self.action_manager, "midi_disconnect_action", None
            ),
        )

    def update_undo_redo_buttons(self) -> None:
        """Update undo/redo action enabled state (buttons are per-tab, driven by actions)."""
        global_undo_action = getattr(self.action_manager, "global_undo_action", None)
        if global_undo_action:
            global_undo_action.setEnabled(self.connection_history.can_undo())
        global_redo_action = getattr(self.action_manager, "global_redo_action", None)
        if global_redo_action:
            global_redo_action.setEnabled(self.connection_history.can_redo())

    def _get_current_visibility_port_type(self) -> str:
        """Get the port type for the current tab's visibility dialog.

        Delegates to :class:`cables.cm_window_chrome.WindowChromeController`
        (Seam 4 extraction). Thin delegator for the frozen public API
        (called externally by the visibility dialog wiring).
        """
        return self._window_chrome.get_current_visibility_port_type()

    def disconnect_node(self, node_name: str) -> None:
        self.jack_handler.disconnect_node(node_name)

    def update_connections(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.update_connections()

    def update_midi_connections(self) -> None:
        """Delegates to :class:`cables.cm_port_refresh.PortRefreshController`."""
        self._port_refresh.update_midi_connections()

    def disconnect_selected_groups(self, group_items: List[QTreeWidgetItem]) -> None:
        sel.disconnect_selected_groups(self.jack_handler, group_items)

    def _get_current_connections(self) -> List[Dict[str, str]]:
        return self.jack_handler._get_current_connections()

    def notify_connection_history_changed(self) -> None:
        self.update_undo_redo_buttons()

        graph_window = self._get_graph_main_window()
        if graph_window:
            update_func = getattr(
                graph_window, "_update_graph_undo_redo_buttons_state", None
            )
            if update_func:
                update_func()

    @pyqtSlot()
    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode for the current tab.

        Delegates to :class:`cables.cm_window_chrome.WindowChromeController`
        (Seam 4 extraction). The ``@pyqtSlot()`` decorator is preserved so
        Qt signal/slot wiring (e.g. from ``tab_manager``'s
        ``fullscreen_request_signal``) keeps working without re-compilation.
        """
        self._window_chrome.toggle_fullscreen()

    def show_node_visibility_dialog(self, tab_type: str = "graph") -> None:
        """Show the node visibility configuration dialog.

        Delegates to :class:`cables.cm_window_chrome.WindowChromeController`
        (Seam 4 extraction). Thin delegator for the frozen public API.
        """
        self._window_chrome.show_node_visibility_dialog(tab_type)
