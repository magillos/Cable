#!/usr/bin/env python3
"""
Cables - A JACK/PipeWire connection manager
"""

import sys
import argparse
import os
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
from cables.features.mixer import AlsMixerApp
from cables.features.node_visibility_manager import NodeVisibilityManager
from cables.ui.ui_manager import UIManager
from cables.connection_visualizer import ConnectionVisualizer

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
        self._init_config_managers()
        self._init_window()
        self._init_jack_client()
        self._init_core_services()
        self._init_ui_manager()
        self._init_action_manager()
        self._init_ui_components()
        self._init_managers()
        self._connect_internal_signals()
        self._activate_jack()
        self._post_init_cleanup()
        self._recreate_virtual_sinks_if_autostart()
        self._load_startup_preset_if_configured()
        self._init_interaction_handlers()
        self._init_node_visibility()

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
        """Connect internal signals between components."""
        # Connect JackService signals directly for port registration UI updates
        self._jack_service.port_registered.connect(self._on_port_registered)
        self._jack_service.port_unregistered.connect(self._on_port_unregistered)

        # Connect UI state manager signals
        collapse_btn = getattr(self.ui_manager, "collapse_all_button", None)
        if collapse_btn:
            collapse_btn.toggled.connect(self.ui_state_manager.toggle_collapse_all)
        untangle_btn = getattr(self.ui_manager, "untangle_button", None)
        if untangle_btn:
            untangle_btn.clicked.connect(self.ui_state_manager.toggle_untangle_sort)
        zoom_in_btn = getattr(self.ui_manager, "zoom_in_button", None)
        if zoom_in_btn:
            zoom_in_btn.clicked.connect(self.ui_state_manager.increase_font_size)
        zoom_out_btn = getattr(self.ui_manager, "zoom_out_button", None)
        if zoom_out_btn:
            zoom_out_btn.clicked.connect(self.ui_state_manager.decrease_font_size)

        tab_widget = getattr(self.ui_manager, "tab_widget", None)
        if tab_widget:
            self.tab_manager.switch_tab(tab_widget.currentIndex())

        # Connect TabManager tab_changed signal to ActionManager FIRST
        # This must happen before handling any pending tab switch
        if self.tab_manager is not None and self.action_manager is not None:
            self.tab_manager.tab_changed.connect(self.action_manager.update_tab_state)

        # Handle any pending tab switch from initial setup
        pending_switch = getattr(self.tab_manager, "_pending_tab_switch", None)
        if pending_switch is not None:
            pending_index = pending_switch
            self.tab_manager._pending_tab_switch = None
            self.tab_manager.switch_tab(pending_index)

        # Update UI elements dictionary
        self.ui_elements.update(
            {
                "tab_widget": self.ui_manager.tab_widget,
                "connect_button": getattr(self, "connect_button", None),
                "disconnect_button": getattr(self, "disconnect_button", None),
                "midi_connect_button": getattr(self, "midi_connect_button", None),
                "midi_disconnect_button": getattr(self, "midi_disconnect_button", None),
                "bottom_presets_button": self.ui_manager.bottom_presets_button,
                "bottom_visibility_button": self.ui_manager.bottom_visibility_button,
                "collapse_all_checkbox": self.ui_manager.collapse_all_button,
                "output_tree": getattr(self, "output_tree", None),
                "input_tree": getattr(self, "input_tree", None),
                "midi_output_tree": getattr(self, "midi_output_tree", None),
                "midi_input_tree": getattr(self, "midi_input_tree", None),
                "graph_main_window": getattr(self, "graph_main_window", None),
                "midi_matrix_widget": getattr(self, "midi_matrix_widget", None),
            }
        )

        if self.action_manager is not None and self.ui_state_manager is not None:
            self.action_manager.complete_setup(
                state_manager=self.ui_state_manager, add_action_callback=self.addAction
            )

        # Initialize undo/redo button state (should be disabled when history is empty)
        self.update_undo_redo_buttons()

        if self.ui_manager.bottom_presets_button:
            presets_action = getattr(self.action_manager, "presets_action", None)
            if presets_action:
                self.ui_manager.bottom_presets_button.setDefaultAction(presets_action)
            self.ui_manager.bottom_presets_button.setPopupMode(
                QToolButton.ToolButtonPopupMode.InstantPopup
            )
        if self.ui_manager.bottom_visibility_button:
            self.ui_manager.bottom_visibility_button.clicked.connect(
                lambda: self.show_node_visibility_dialog(
                    self._get_current_visibility_port_type()
                )
            )

        # Connect ActionManager signals to handlers
        self._connect_action_manager_signals()

        # Connect JACK signals to connection view refresh for event-driven updates
        self._connect_jack_signals_to_connection_views()

    def _activate_jack(self) -> None:
        """Activate the JACK client."""
        self.client.activate()

    def _post_init_cleanup(self) -> None:
        """Perform post-initialization cleanup tasks."""
        # Clean up orphaned unified sinks immediately on startup (before any UI)
        orphaned_count = self.unified_sink_manager.cleanup_orphaned_unified_sinks(
            self._jack_service.get_ports()
        )
        if orphaned_count > 0:
            logger.info(
                f"Cleaned up {orphaned_count} orphaned unified sinks on startup."
            )

        save_preset_action = getattr(self.action_manager, "save_preset_action", None)
        if save_preset_action:
            save_preset_action.setEnabled(bool(self.preset_handler.current_preset_name))

    def _recreate_virtual_sinks_if_autostart(self) -> None:
        """Recreate stored virtual sinks when running in autostart mode (--headless/--minimized)."""
        if not self._load_startup_preset:
            return

        import json
        import subprocess

        try:
            data = json.loads(
                self.config_manager.get_str(
                    keys.VIRTUAL_SINKS_RECREATE_AT_AUTOSTART, "{}"
                )
                or "{}"
            )
        except (json.JSONDecodeError, Exception):
            return

        if not data:
            return

        logger.info(f"Recreating {len(data)} virtual sink(s) for autostart...")

        for _client_key, sink_info in data.items():
            sink_name = sink_info.get("sink_name", "")
            channel_map = sink_info.get("channel_map", "front-left,front-right")
            if not sink_name:
                logger.warning(
                    f"Skipping autostart sink entry with no sink_name: {_client_key}"
                )
                continue
            try:
                # Check if sink already exists
                existing = subprocess.run(
                    ["pactl", "list", "short", "sinks"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                already_exists = False
                for line in existing.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2 and parts[1].strip() == sink_name:
                        already_exists = True
                        break

                if already_exists:
                    logger.info(
                        f"Virtual sink '{sink_name}' already exists, skipping creation."
                    )
                    # Update module ID in config for unload tracking
                    module_id = (
                        self.unified_sink_manager.find_module_id_for_external_sink(
                            sink_name
                        )
                    )
                    if module_id:
                        self._update_virtual_sink_module_id(sink_name, str(module_id))
                    continue

                # Create the sink
                result = subprocess.run(
                    [
                        "pactl",
                        "load-module",
                        "module-null-sink",
                        f"sink_name={sink_name}",
                        f"channel_map={channel_map}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                module_id = result.stdout.strip()
                self._update_virtual_sink_module_id(sink_name, module_id)
                logger.info(
                    f"Recreated virtual sink '{sink_name}' (module {module_id})"
                )

            except Exception as e:
                logger.error(f"Error recreating virtual sink '{sink_name}': {e}")

    def _update_virtual_sink_module_id(self, sink_name: str, module_id: str) -> None:
        """Update the module ID in VIRTUAL_SINK_MODULE_IDS config."""
        import json

        try:
            module_ids = json.loads(
                self.config_manager.get_str(keys.VIRTUAL_SINK_MODULE_IDS, "{}") or "{}"
            )
            module_ids[sink_name] = module_id
            self.config_manager.set_str(
                keys.VIRTUAL_SINK_MODULE_IDS, json.dumps(module_ids)
            )
        except Exception as e:
            logger.error(f"Error updating module ID for {sink_name}: {e}")

    def _load_startup_preset_if_configured(self) -> None:
        """Load startup preset if configured and requested."""
        if (
            self._load_startup_preset
            and self.preset_handler.startup_preset_name
            and self.preset_handler.startup_preset_name != "None"
        ):
            startup_preset = self.preset_handler.startup_preset_name
            logger.info(f"Loading startup preset '{startup_preset}'...")
            # Load the preset without showing a success message (is_startup=True)
            self.preset_handler.load_selected_preset(startup_preset, is_startup=True)

    def _init_interaction_handlers(self) -> None:
        """Initialize interaction manager and connect tree click handlers."""
        self.interaction_manager = InteractionManager(
            highlight_manager=self.highlight_manager,
            update_connection_buttons_func=self.update_connection_buttons,
            update_midi_connection_buttons_func=self.update_midi_connection_buttons,
        )

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

        # Connect tree click handlers
        if self.input_tree is not None:
            self.input_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.input_tree, False
                )
            )
        if self.output_tree is not None:
            self.output_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.output_tree, False
                )
            )
        if self.midi_input_tree is not None:
            self.midi_input_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.midi_input_tree, True
                )
            )
        if self.midi_output_tree is not None:
            self.midi_output_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.midi_output_tree, True
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
        scene = self._get_graph_scene()
        if not scene:
            return

        scene = self.graph_main_window.scene
        unified_nodes = scene.get_unified_nodes()

        for node in unified_nodes:
            if node.client_name == client_name:
                logger.debug(
                    f"New port {port_name} for unified client {client_name}. Reconnecting to sink."
                )
                # Use unified sink manager to reconnect ports
                all_ports = self._jack_service.get_ports()
                self.unified_sink_manager.connect_ports_to_unified_sink(
                    node, self.jack_handler, all_ports
                )
                break

    def disconnect_all_unified(self) -> None:
        scene = self._get_graph_scene()
        if not scene:
            return
        unified_nodes = scene.get_unified_nodes()

        for node in unified_nodes:
            for port_item in list(node.output_ports.values()):
                for conn_item in list(port_item.connections):
                    if conn_item and conn_item.source_port and conn_item.dest_port:
                        try:
                            self.jack_handler.break_connection(
                                conn_item.source_port.port_name,
                                conn_item.dest_port.port_name,
                            )
                        except Exception as e:
                            logger.error(
                                f"Error breaking output connection for {port_item.port_name} of {node.client_name}: {e}"
                            )

    def reconnect_all_unified(self) -> None:
        scene = self._get_graph_scene()
        if not scene:
            return
        unified_nodes = scene.get_unified_nodes()
        all_ports = self._jack_service.get_ports()

        for node in unified_nodes:
            self.unified_sink_manager.connect_ports_to_unified_sink(
                node, self.jack_handler, all_ports
            )

    def _restore_window_geometry(self) -> None:
        """Restore saved window geometry, or apply first-launch defaults."""
        saved = self.config_manager.get_str_setting(keys.CONN_MANAGER_GEOMETRY, "")
        if saved:
            from PyQt6.QtCore import QByteArray
            import base64

            self.restoreGeometry(QByteArray(base64.b64decode(saved)))
        else:
            self.resize(
                app_config.CONN_MANAGER_INITIAL_WIDTH,
                app_config.CONN_MANAGER_INITIAL_HEIGHT,
            )

    def _save_window_geometry(self) -> None:
        """Persist current window geometry to config."""
        import base64

        data = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        self.config_manager.set_str_setting(keys.CONN_MANAGER_GEOMETRY, data)

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
        """Connect ActionManager signals to their handlers."""
        if self.action_manager is None:
            return

        # Connect/disconnect requests
        self.action_manager.connect_requested.connect(self._on_connect_requested)
        self.action_manager.disconnect_requested.connect(self._on_disconnect_requested)

        # Refresh request
        self.action_manager.refresh_requested.connect(
            lambda: self.refresh_ports(from_shortcut=True)
        )

        # Zoom request
        self.action_manager.zoom_requested.connect(self.tab_manager.handle_zoom_request)

        # Tab switch request
        self.action_manager.tab_switch_requested.connect(
            self.tab_manager.handle_tab_switch_request
        )

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

    def _connect_jack_signals_to_connection_views(self) -> None:
        """
        Connect JackService signals to connection view refresh.

        This enables event-driven refresh when connections change,
        ensuring the visualization updates without constant polling.
        """
        jack_service = self._jack_service

        # Audio connection view: refresh on any connection change
        if self.connection_view is not None:
            jack_service.connection_made.connect(
                lambda out, inp: self.connection_view.request_refresh()
            )
            jack_service.connection_broken.connect(
                lambda out, inp: self.connection_view.request_refresh()
            )
            jack_service.port_added.connect(
                lambda *args: self.connection_view.request_refresh()
            )
            jack_service.port_removed.connect(
                lambda *args: self.connection_view.request_refresh()
            )

        # MIDI connection view: refresh on any connection change
        if self.midi_connection_view is not None:
            jack_service.connection_made.connect(
                lambda out, inp: self.midi_connection_view.request_refresh()
            )
            jack_service.connection_broken.connect(
                lambda out, inp: self.midi_connection_view.request_refresh()
            )
            jack_service.port_added.connect(
                lambda *args: self.midi_connection_view.request_refresh()
            )
            jack_service.port_removed.connect(
                lambda *args: self.midi_connection_view.request_refresh()
            )

    def refresh_visualizations(self) -> None:
        if self.port_type == "audio":
            self.update_connections()
        else:
            self.update_midi_connections()

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
        if port_type_to_refresh == "audio":
            input_tree = self.input_tree
            output_tree = self.output_tree
            update_visuals = self.update_connections
            update_buttons = self.update_connection_buttons
            is_midi = False
        elif port_type_to_refresh == "midi":
            input_tree = self.midi_input_tree
            output_tree = self.midi_output_tree
            update_visuals = self.update_midi_connections
            update_buttons = self.update_midi_connection_buttons
            is_midi = True
        else:
            logger.warning(
                f"Warning: Invalid port_type '{port_type_to_refresh}' passed to _refresh_single_port_type"
            )
            return

        input_filter_edit = getattr(self.ui_manager, "input_filter_edit", None)
        current_input_filter = input_filter_edit.text() if input_filter_edit else ""
        output_filter_edit = getattr(self.ui_manager, "output_filter_edit", None)
        current_output_filter = output_filter_edit.text() if output_filter_edit else ""

        selected_input_info = self._get_selected_item_info(input_tree)
        selected_output_info = self._get_selected_item_info(output_tree)

        input_tree.clear()
        output_tree.clear()

        input_ports, output_ports = self.port_manager._get_ports(is_midi_tab=is_midi)

        input_tree.populate_tree(input_ports)
        output_tree.populate_tree(output_ports)

        self.port_manager.filter_ports(input_tree, current_input_filter)
        self.port_manager.filter_ports(output_tree, current_output_filter)

        self._restore_selection(input_tree, selected_input_info)
        self._restore_selection(output_tree, selected_output_info)

        update_visuals()
        if is_midi:
            self.highlight_manager.clear_midi_highlights()
        else:
            self.highlight_manager.clear_highlights()
        update_buttons()

        restored_input_item = input_tree.currentItem()
        restored_output_item = output_tree.currentItem()

        if restored_input_item:
            self.highlight_manager.apply_highlights_for_selection(
                restored_input_item, input_tree, is_midi
            )

        if restored_output_item:
            if restored_output_item != restored_input_item:
                self.highlight_manager.apply_highlights_for_selection(
                    restored_output_item, output_tree, is_midi
                )

        if self.port_type == port_type_to_refresh:
            self.ui_state_manager.apply_collapse_state_to_current_trees()

    def refresh_ports(
        self, refresh_all: bool = False, from_shortcut: bool = False
    ) -> None:
        if refresh_all:
            self._refresh_single_port_type("audio")
            self._refresh_single_port_type("midi")
        else:
            self._refresh_single_port_type(self.port_type)

        # Apply node visibility settings after refreshing ports
        if self.node_visibility_manager is not None:
            self.node_visibility_manager.apply_visibility_settings()

    def _get_selected_item_info(
        self, tree_widget: QTreeWidget
    ) -> Tuple[Optional[str], Optional[bool]]:
        if not getattr(tree_widget, "currentItem", None):
            return None, None
        item = tree_widget.currentItem()
        if not item:
            return None, None

        is_group = item.childCount() > 0
        if is_group:
            return item.text(0), True
        else:
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            return port_name, False

    def _restore_selection(
        self,
        tree_widget: QTreeWidget,
        selection_info: Tuple[Optional[str], Optional[bool]],
    ) -> None:
        if not selection_info or not getattr(tree_widget, "port_items", None):
            return

        name_or_text, is_group = selection_info
        if name_or_text is None:
            return

        item_to_select = None
        if is_group:
            for i in range(tree_widget.topLevelItemCount()):
                group_item = tree_widget.topLevelItem(i)
                if group_item.text(0) == name_or_text:
                    item_to_select = group_item
                    break
        else:
            item_to_select = tree_widget.port_items.get(name_or_text)

        if item_to_select and not item_to_select.isHidden():
            tree_widget.setCurrentItem(item_to_select)

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
        super().changeEvent(event)
        if event.type() == event.Type.ActivationChange:
            is_focused = self.isActiveWindow()
            if self.ui_state_manager is not None:
                self.ui_state_manager.handle_focus_change(is_focused)

            # Refresh embedded Cable settings when window gains focus
            if is_focused and self.cable_widget is not None:
                current_tab_index = self.ui_manager.tab_widget.currentIndex()
                current_tab_text = self.ui_manager.tab_widget.tabText(current_tab_index)
                if current_tab_text == "Cable":
                    self.cable_widget._apply_current_settings()
                    self.cable_widget._apply_devices()
                    self.cable_widget._apply_nodes()
                    self.cable_widget.update_latency_display()

            # Manage ALSA mixer updates based on focus and active tab
            tab_widget = getattr(self.ui_manager, "tab_widget", None)
            alsa_mixer_tab = getattr(self.ui_manager, "alsa_mixer_tab_widget", None)
            if tab_widget and alsa_mixer_tab and self.alsa_mixer_app is not None:
                current_tab_index = tab_widget.currentIndex()
                current_widget = tab_widget.widget(current_tab_index)
                is_alsa_mixer_tab_active = current_widget == alsa_mixer_tab

                if is_alsa_mixer_tab_active:
                    if is_focused:
                        self.alsa_mixer_app.start_updates()
                    else:
                        self.alsa_mixer_app.stop_updates()

    def _animate_button_press(self, button: Optional[QPushButton]) -> None:
        if not button:
            return

        original_style = button.styleSheet()

        if "inset" in original_style:
            return

        color_scheme = self.ui_manager.get_color_scheme()
        pressed_style = f"""
            QPushButton {{
                background-color: {color_scheme["highlight"].name()};
                color: {color_scheme["text"].name()};
                border: 2px inset {color_scheme["highlight"].darker(120).name()};
            }}
        """
        button.setStyleSheet(pressed_style)

        QTimer.singleShot(150, lambda: button.setStyleSheet(original_style))

    def _on_port_registered(self, port_name: str, is_input: bool) -> None:
        if not self.ui_state_manager.are_callbacks_enabled():
            return

        if self.latency_tester is not None and (
            port_name == "jack_delay:in" or port_name == "jack_delay:out"
        ):
            logger.debug(
                f"Detected registration of {port_name}, attempting latency auto-connection via LatencyTester..."
            )
            QTimer.singleShot(50, self.latency_tester._attempt_latency_auto_connection)

        self.refresh_ports(refresh_all=True)

    def _on_port_unregistered(self, port_name: str, is_input: bool) -> None:
        if not self.ui_state_manager.are_callbacks_enabled():
            return
        self.refresh_ports(refresh_all=True)

    def make_connection_selected(self) -> None:
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            logger.debug(
                "Make Connection: Select at least one input and one output item (port or group)."
            )
            return

        logger.debug(
            f"Making connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}"
        )
        self.jack_handler.make_multiple_connections(selected_outputs, selected_inputs)

    def make_midi_connection_selected(self) -> None:
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            logger.debug(
                "Make MIDI Connection: Select at least one input and one output item (port or group)."
            )
            return

        logger.debug(
            f"Making MIDI connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}"
        )
        self.jack_handler.make_multiple_connections(selected_outputs, selected_inputs)

    def break_connection_selected(self) -> None:
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            logger.debug(
                "Break Connection: Select at least one input and one output port."
            )
            return

        logger.debug(
            f"Breaking connections for: Outputs={selected_outputs}, Inputs={selected_inputs}"
        )
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                self.jack_handler.break_connection(out_port, in_port)

    def break_midi_connection_selected(self) -> None:
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            logger.debug(
                "Break MIDI Connection: Select at least one input and one output MIDI port."
            )
            return

        logger.debug(
            f"Breaking MIDI connections for: Outputs={selected_outputs}, Inputs={selected_inputs}"
        )
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                self.jack_handler.break_midi_connection(out_port, in_port)

    def _get_ports_from_selected_items(self, tree_widget: QTreeWidget) -> List[str]:
        """
        Extract port names from selected items in a tree widget.

        Args:
            tree_widget: The tree widget to extract ports from

        Returns:
            List of port names
        """
        port_names = set()
        for item in tree_widget.selectedItems():
            if not item:
                continue

            if item.childCount() == 0:
                # Leaf item (port)
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    port_names.add(port_name)
            else:
                # Parent item (client/group) - get all child ports
                for i in range(item.childCount()):
                    child = item.child(i)
                    port_name = child.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        port_names.add(port_name)
        return list(port_names)

    def update_connection_buttons(self) -> None:
        self._update_port_connection_buttons(
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
        self._update_port_connection_buttons(
            self.midi_input_tree,
            self.midi_output_tree,
            self.midi_connect_button,
            self.midi_disconnect_button,
            connect_action=getattr(self.action_manager, "midi_connect_action", None),
            disconnect_action=getattr(
                self.action_manager, "midi_disconnect_action", None
            ),
        )

    def _update_port_connection_buttons(
        self,
        input_tree: QTreeWidget,
        output_tree: QTreeWidget,
        connect_button: QPushButton,
        disconnect_button: QPushButton,
        connect_action: Optional[QAction] = None,
        disconnect_action: Optional[QAction] = None,
    ) -> None:
        selected_input_ports = self._get_ports_from_selected_items(input_tree)
        selected_output_ports = self._get_ports_from_selected_items(output_tree)

        ports_selected = bool(selected_input_ports and selected_output_ports)

        can_connect = False
        can_disconnect = False

        if ports_selected:
            possible_connections = set()
            for out_p in selected_output_ports:
                for in_p in selected_input_ports:
                    possible_connections.add((out_p, in_p))

            is_midi = input_tree in (
                getattr(self, "midi_input_tree", None),
            ) or output_tree in (getattr(self, "midi_output_tree", None),)
            existing_connections = self.jack_handler._get_existing_connections_between(
                selected_output_ports,
                selected_input_ports,
                is_midi=is_midi,
            )

            # Port-to-port / group-to-port / port-to-group: allow Connect if there exists at least
            # one not-yet-existing connection in the selected cross-product.
            #
            # Group-to-group (multiple outputs and multiple inputs) is treated as a single logical
            # connection operation (suffix/sequential pairing), not as a full cross-product.
            # If any connections already exist between the selected groups, we consider them
            # "connected" for UI purposes and disable Connect.
            is_group_to_group = (
                len(selected_output_ports) > 1 and len(selected_input_ports) > 1
            )

            if is_group_to_group:
                can_connect = len(existing_connections) == 0
                can_disconnect = len(existing_connections) > 0
            else:
                if (
                    len(possible_connections) > 0
                    and possible_connections != existing_connections
                ):
                    can_connect = True
                if len(existing_connections) > 0:
                    can_disconnect = True

        connect_button.setEnabled(can_connect)
        disconnect_button.setEnabled(can_disconnect)

        # Do not disable the underlying QActions here.
        # Global shortcuts call QAction.trigger() on these actions; if the action is disabled,
        # trigger() becomes a no-op and shortcuts stop working.

    def update_undo_redo_buttons(self) -> None:
        """Update undo/redo action enabled state (buttons are per-tab, driven by actions)."""
        global_undo_action = getattr(self.action_manager, "global_undo_action", None)
        if global_undo_action:
            global_undo_action.setEnabled(self.connection_history.can_undo())
        global_redo_action = getattr(self.action_manager, "global_redo_action", None)
        if global_redo_action:
            global_redo_action.setEnabled(self.connection_history.can_redo())

    def _get_current_visibility_port_type(self) -> str:
        """Get the port type for the current tab's visibility dialog."""
        if self.ui_manager is None or not self.ui_manager.tab_widget:
            return keys.TAB_AUDIO
        current_index = self.ui_manager.tab_widget.currentIndex()
        tab_text = self.ui_manager.tab_widget.tabText(current_index)
        return keys.TAB_DISPLAY_MAP.get(tab_text, keys.TAB_AUDIO)

    def disconnect_node(self, node_name: str) -> None:
        self.jack_handler.disconnect_node(node_name)

    def update_connections(self) -> None:
        self.connection_visualizer.update_connection_graphics(
            self.connection_scene,
            self.connection_view,
            self.output_tree,
            self.input_tree,
            is_midi=False,
        )

    def update_midi_connections(self) -> None:
        self.connection_visualizer.update_connection_graphics(
            self.midi_connection_scene,
            self.midi_connection_view,
            self.midi_output_tree,
            self.midi_input_tree,
            is_midi=True,
        )

    def disconnect_selected_groups(self, group_items: List[QTreeWidgetItem]) -> None:
        ports_to_disconnect = set()

        for group_item in group_items:
            if group_item and group_item.childCount() > 0:
                for i in range(group_item.childCount()):
                    port_item = group_item.child(i)
                    port_name = port_item.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        ports_to_disconnect.add(port_name)

        if not ports_to_disconnect:
            return

        for port_name in ports_to_disconnect:
            self.jack_handler.disconnect_node(port_name)

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
        tab_widget = getattr(self.ui_manager, "tab_widget", None)
        if not tab_widget:
            logger.error("Error: Tab widget not found.")
            return

        current_tab_widget = tab_widget.currentWidget()
        if not current_tab_widget:
            logger.debug("Fullscreen toggle requested, but no active tab found.")
            return

        self._is_fullscreen = not self._is_fullscreen

        components_to_manage = []
        if self.menuBar():
            components_to_manage.append(self.menuBar())
        if self.statusBar():
            components_to_manage.append(self.statusBar())

        for toolbar in self.findChildren(QToolBar):
            if toolbar.parent() == self:
                components_to_manage.append(toolbar)

        tab_bar_method = getattr(self.ui_manager.tab_widget, "tabBar", None)
        if tab_bar_method:
            tab_bar = tab_bar_method()
            if tab_bar:
                components_to_manage.append(tab_bar)

        for pt in ["midi", "audio"]:
            ctrl = getattr(self, f"{pt}_matrix_controls_widget", None)
            if ctrl:
                components_to_manage.append(ctrl)

        if self._is_fullscreen:
            self._widgets_original_visibility.clear()

            for widget in components_to_manage:
                if widget:
                    # Matrix controls should always be restored to shown state; 
                    # their parent tab's visibility will handle actual on-screen presence.
                    is_matrix_ctrl = widget in [self.midi_matrix_controls_widget, self.audio_matrix_controls_widget]
                    self._widgets_original_visibility[widget] = True if is_matrix_ctrl else widget.isVisible()
                    widget.hide()

            self.tab_manager.show_bottom_controls(False)

            for i in range(self.ui_manager.tab_widget.count()):
                tab_page_widget = self.ui_manager.tab_widget.widget(i)
                if tab_page_widget != current_tab_widget:
                    if tab_page_widget not in self._widgets_original_visibility:
                        self._widgets_original_visibility[tab_page_widget] = (
                            self.ui_manager.tab_widget.isTabEnabled(i)
                        )
                    self.ui_manager.tab_widget.setTabEnabled(i, False)

            # Special case for graph tab internal controls
            if current_tab_widget == getattr(self.ui_manager, "graph_tab_widget", None):
                graph_window = self._get_graph_main_window()
                if graph_window:
                    toggle_func = getattr(graph_window, "toggle_internal_controls", None)
                    if toggle_func:
                        toggle_func(False)

            self.showFullScreen()

        else:
            self.showNormal()

            # Special case for graph tab internal controls
            if current_tab_widget == getattr(self.ui_manager, "graph_tab_widget", None):
                graph_window = self._get_graph_main_window()
                if graph_window:
                    toggle_func = getattr(graph_window, "toggle_internal_controls", None)
                    if toggle_func:
                        toggle_func(True)

            chrome_widgets_managed_on_exit = []
            if self.menuBar():
                chrome_widgets_managed_on_exit.append(self.menuBar())
            if self.statusBar():
                chrome_widgets_managed_on_exit.append(self.statusBar())
            for toolbar in self.findChildren(QToolBar):
                if toolbar.parent() == self:
                    chrome_widgets_managed_on_exit.append(toolbar)
            tab_bar_method = getattr(self.ui_manager.tab_widget, "tabBar", None)
            if tab_bar_method:
                tab_bar = tab_bar_method()
                if tab_bar:
                    chrome_widgets_managed_on_exit.append(tab_bar)

            for pt in ["midi", "audio"]:
                ctrl = getattr(self, f"{pt}_matrix_controls_widget", None)
                if ctrl:
                    chrome_widgets_managed_on_exit.append(ctrl)

            for (
                item_widget,
                original_state,
            ) in self._widgets_original_visibility.items():
                if item_widget in chrome_widgets_managed_on_exit:
                    if item_widget and original_state:
                        item_widget.show()
                else:
                    tab_index_to_restore = -1
                    for i in range(self.ui_manager.tab_widget.count()):
                        if self.ui_manager.tab_widget.widget(i) == item_widget:
                            tab_index_to_restore = i
                            break

                    if (
                        tab_index_to_restore != -1
                        and self.ui_manager.tab_widget.widget(tab_index_to_restore)
                        != current_tab_widget
                    ):
                        if original_state:
                            self.ui_manager.tab_widget.setTabEnabled(
                                tab_index_to_restore, True
                            )

            self._widgets_original_visibility.clear()

        if self.centralWidget() and self.centralWidget().layout():
            self.centralWidget().layout().activate()
        if (
            current_tab_widget
            and current_tab_widget.layout()
        ):
            current_tab_widget.layout().activate()

    def show_node_visibility_dialog(self, tab_type: str = "graph") -> None:
        """Show the node visibility configuration dialog."""
        if self.node_visibility_manager is not None:
            self.node_visibility_manager.show_configuration_dialog(self, tab_type)

            # After dialog closes, pass node visibility manager to graph_main_window.scene if needed
            scene = self._get_graph_scene()
            if scene:
                scene.set_node_visibility_manager(self.node_visibility_manager)
                # Refresh the graph view
                scene.full_graph_refresh()
