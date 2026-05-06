#!/usr/bin/env python3
"""
Tab Manager - Handles UI tab management for JackConnectionManager
"""

import sys
import os
from typing import Optional, TYPE_CHECKING, List, Set

import logging

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import QVBoxLayout, QTreeWidget
from PyQt6.QtCore import Qt, QObject, pyqtSignal
import jack

# Import core components
from cables.ui.tab_ui_manager import TabUIManager
from cables.features.mixer import AlsMixerApp
from cables.action_manager import ActionManager
from cable_core import config_keys as keys

if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager
    from PyQt6.QtWidgets import QTabWidget
    from cables.ui_manager import UIManager
    from cables.features.mixer import AlsMixerApp
    from cables.features.pwtop_monitor import PwTopMonitor
    from cables.features.latency_tester import LatencyTester
    from PipeWireSettingsApp import (
        PipeWireSettingsApp,
    )  # Although imported locally, for hinting it might be useful


class TabManager(QObject):
    """
    Manages all tab-related UI and state logic for the connection manager.

    This service handles:
    - Tab initialization and setup
    - Tab switching and state management
    - Bottom UI controls visibility
    - Global zoom action state coordination

    Signals:
        tab_changed(str): Emitted when tab changes, with tab type string
    """

    # Signal emitted when tab changes (tab_type: 'audio', 'midi', 'graph', etc.)
    tab_changed = pyqtSignal(str)

    def __init__(self, connection_manager: "JackConnectionManager") -> None:
        """
        Initialize TabManager with reference to main connection manager.

        Args:
            connection_manager: Reference to JackConnectionManager instance
        """
        super().__init__(connection_manager)

        self.connection_manager = connection_manager
        self.tab_ui_manager = TabUIManager()
        self.last_active_tab = 0
        self._pending_tab_switch = (
            None  # Store tab switch to handle after ui_state_manager is initialized
        )

        # UI element references (populated during setup)
        self.tab_widget = None
        self.cable_widget = None
        self.alsa_mixer_app = None
        self.pwtop_monitor = None
        self.latency_tester = None

    def setup_tabs(self, integrated_override: Optional[bool] = None) -> None:
        """Setup all tabs in the connection manager.

        Args:
            integrated_override: If not None, overrides the config value for
                                 integrated mode (True = always show Cable tab).
                                 None means read from config as normal.
        """

        # Get reference to tab widget from ui_manager
        self.tab_widget = self.connection_manager.ui_manager.tab_widget

        # Check if Cable should be integrated as the first tab
        if integrated_override is not None:
            self.integrated_mode = integrated_override
        else:
            self.integrated_mode = self.connection_manager.config_manager.get_bool(
                keys.INTEGRATE_CABLE_AND_CABLES, False
            )
        if self.integrated_mode:
            self._add_cable_tab()

        # Setup individual tabs
        self.tab_ui_manager.setup_port_tab(
            self.connection_manager,
            self.connection_manager.ui_manager.audio_tab_widget,
            "Audio",
            "audio",
        )
        self.tab_ui_manager.setup_port_tab(
            self.connection_manager,
            self.connection_manager.ui_manager.midi_tab_widget,
            "MIDI",
            "midi",
        )

        # Conditionally setup and add MIDI Matrix tab
        if self.connection_manager.config_manager.get_bool(
            keys.ENABLE_MIDI_MATRIX, False
        ):
            self.tab_ui_manager.setup_midi_matrix_tab(
                self.connection_manager,
                self.connection_manager.ui_manager.midi_matrix_tab_widget,
            )

        # Conditionally setup and add Audio Matrix tab
        if self.connection_manager.config_manager.get_bool(
            keys.ENABLE_AUDIO_MATRIX, False
        ):
            self.tab_ui_manager.setup_audio_matrix_tab(
                self.connection_manager,
                self.connection_manager.ui_manager.audio_matrix_tab_widget,
            )

        # Setup pw-top tab
        self.tab_ui_manager.setup_pwtop_tab(
            self.connection_manager, self.connection_manager.ui_manager.pwtop_tab_widget
        )
        self.connection_manager.pwtop_monitor = getattr(
            self.connection_manager, "pwtop_monitor", None
        )

        # Setup latency tab
        self.tab_ui_manager.setup_latency_tab(
            self.connection_manager,
            self.connection_manager.ui_manager.latency_tab_widget,
        )
        self.connection_manager.latency_tester = getattr(
            self.connection_manager, "latency_tester", None
        )

        # New Tab Order:
        # Audio (0), MIDI (1), MIDI Matrix (2), Graph (3), pw-top (4), Alsa Mixer (5), Latency Test (6)
        self.tab_widget.addTab(
            self.connection_manager.ui_manager.audio_tab_widget, "Audio"
        )  # Index 0
        self.tab_widget.addTab(
            self.connection_manager.ui_manager.midi_tab_widget, "MIDI"
        )  # Index 1

        if self.connection_manager.config_manager.get_bool(
            keys.ENABLE_MIDI_MATRIX, False
        ):
            self.tab_widget.addTab(
                self.connection_manager.ui_manager.midi_matrix_tab_widget, "MIDI Matrix"
            )  # Index 2

        if self.connection_manager.config_manager.get_bool(
            keys.ENABLE_AUDIO_MATRIX, False
        ):
            self.tab_widget.addTab(
                self.connection_manager.ui_manager.audio_matrix_tab_widget,
                "Audio Matrix",
            )

        self.tab_ui_manager.setup_graph_tab(
            self.connection_manager, self.connection_manager.ui_manager.graph_tab_widget
        )
        self.tab_widget.insertTab(
            self.tab_widget.count(),
            self.connection_manager.ui_manager.graph_tab_widget,
            "Graph",
        )

        self.tab_widget.addTab(
            self.connection_manager.ui_manager.pwtop_tab_widget, "pw-top"
        )

        # Alsa Mixer tab
        alsa_mixer_layout = QVBoxLayout(
            self.connection_manager.ui_manager.alsa_mixer_tab_widget
        )
        self.connection_manager.alsa_mixer_app = AlsMixerApp(
            config_manager=self.connection_manager.config_manager
        )  # Pass ConfigManager
        alsa_mixer_layout.addWidget(self.connection_manager.alsa_mixer_app)
        self.tab_widget.insertTab(
            self.tab_widget.count(),
            self.connection_manager.ui_manager.alsa_mixer_tab_widget,
            "ALSA Mixer",
        )

        self.tab_widget.addTab(
            self.connection_manager.ui_manager.latency_tab_widget, "Latency Test"
        )

        # Setup fullscreen functionality
        if (
            self.connection_manager.graph_main_window
            and self.connection_manager.graph_main_window.view
        ):
            self.connection_manager.graph_main_window.view.fullscreen_request_signal.connect(
                self.connection_manager.toggle_fullscreen
            )
            
        if getattr(self.connection_manager, 'midi_matrix_widget', None) is not None:
            self.connection_manager.midi_matrix_widget.fullscreen_request_signal.connect(
                self.connection_manager.toggle_fullscreen
            )

        if getattr(self.connection_manager, 'audio_matrix_widget', None) is not None:
            self.connection_manager.audio_matrix_widget.fullscreen_request_signal.connect(
                self.connection_manager.toggle_fullscreen
            )

        # Connect tab switching signal FIRST (before setting current index)
        # This ensures switch_tab is called when setCurrentIndex changes the tab
        self.tab_widget.currentChanged.connect(self.switch_tab)

        # Load last active tab from config
        self.last_active_tab = self.connection_manager.config_manager.get_int(
            keys.LAST_ACTIVE_TAB, 0
        )
        if 0 <= self.last_active_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(self.last_active_tab)

        # Set initial state for global zoom actions and tooltips
        current_tab = self.tab_widget.currentIndex()
        self._update_zoom_button_tooltips(current_tab)
        self._update_global_zoom_action_state(current_tab)



    def _add_cable_tab(self) -> None:
        """Add Cable (PipeWireSettingsApp) as the first tab when integrated mode is enabled."""
        # Use local import to avoid circular imports
        from Cable import PipeWireSettingsApp

        # Create Cable widget in embedded mode
        is_minimized = getattr(self.connection_manager, "_load_startup_preset", False)
        self.cable_widget = PipeWireSettingsApp(
            is_minimized_startup=is_minimized, embedded=True, parent=self.tab_widget
        )
        self.connection_manager.cable_widget = (
            self.cable_widget
        )  # Store reference on connection manager

        # Insert as the first tab
        self.tab_widget.insertTab(0, self.cable_widget, "Cable")
        logger.info("Added Cable tab in integrated mode")



    def switch_tab(self, index: int) -> None:
        """
        Handle tab switching.

        Args:
            index: The index of the tab to switch to
        """
        # Guard against accessing ui_state_manager before it's initialized
        # This can happen during initial setup before _init_managers() is called
        if self.connection_manager.ui_state_manager is None:
            # Store the tab to switch to and do it later in _connect_internal_signals
            self._pending_tab_switch = index
            return

        # New Tab Order:
        # Audio (0), MIDI (1), MIDI Matrix (2), Graph (3), pw-top (4), Alsa Mixer (5), Latency Test (6)

        # Stop pw-top monitor if switching away from it
        if (
            self.tab_widget.tabText(self.last_active_tab) == "pw-top"
            and self.connection_manager.pwtop_monitor is not None
        ):
            self.connection_manager.pwtop_monitor.stop()

        # Configure based on the new tab index
        current_tab_text = self.tab_widget.tabText(index)

        if current_tab_text in ["Audio", "MIDI"]:
            self.connection_manager.port_type = (
                keys.TAB_AUDIO if current_tab_text == "Audio" else keys.TAB_MIDI
            )
            self.connection_manager.ui_state_manager.apply_collapse_state_to_current_trees()
            self.connection_manager.refresh_visualizations()
            self.show_bottom_controls(True)
        elif current_tab_text == "MIDI Matrix":
            self.show_bottom_controls(False)
        elif current_tab_text == "Audio Matrix":
            self.show_bottom_controls(False)
        elif current_tab_text == "Graph":
            self.show_bottom_controls(False)
            if self.connection_manager.graph_main_window:
                if self.connection_manager.graph_main_window.scene:
                    self.connection_manager.graph_main_window.scene.full_graph_refresh()
        elif current_tab_text == "pw-top":
            if self.connection_manager.pwtop_monitor is not None:
                self.connection_manager.pwtop_monitor.start()
            self.show_bottom_controls(False)
        elif current_tab_text == "ALSA Mixer":
            self.show_bottom_controls(False)
            if self.connection_manager.alsa_mixer_app:
                if self.connection_manager.isActiveWindow():
                    self.connection_manager.alsa_mixer_app.start_updates()
        elif current_tab_text == "Latency Test":
            self.show_bottom_controls(False)
        elif current_tab_text == "Cable":
            self.show_bottom_controls(False)
            # Refresh Cable's pipewire settings when switching to Cable tab
            if self.cable_widget is not None:
                self.cable_widget._apply_current_settings()
                self.cable_widget._apply_devices()
                self.cable_widget._apply_nodes()
                self.cable_widget.update_latency_display()

        # Stop ALSA mixer updates when switching away from the tab
        if (
            self.tab_widget.tabText(self.last_active_tab) == "ALSA Mixer"
            and self.connection_manager.alsa_mixer_app
        ):
            self.connection_manager.alsa_mixer_app.stop_updates()

        self.last_active_tab = index
        self.connection_manager.config_manager.set_int(keys.LAST_ACTIVE_TAB, index)

        # Update zoom button tooltips based on tab
        self._update_zoom_button_tooltips(index)

        # Update global zoom action enabled state
        self._update_global_zoom_action_state(index)

        # Emit tab_changed signal for decoupled listeners (e.g., ActionManager)
        tab_type = keys.TAB_DISPLAY_MAP.get(current_tab_text, keys.TAB_UNKNOWN)
        self.tab_changed.emit(tab_type)

    def show_bottom_controls(self, visible: bool) -> None:
        """
        Show or hide bottom UI controls.

        Args:
            visible: Whether to show the controls
        """
        ui = self.connection_manager.ui_manager
        if ui.untangle_button:
            ui.untangle_button.setVisible(visible)
        if ui.collapse_all_button:
            ui.collapse_all_button.setVisible(visible)
        if ui.bottom_presets_button:
            ui.bottom_presets_button.setVisible(visible)
        if ui.bottom_visibility_button:
            ui.bottom_visibility_button.setVisible(visible)
        if ui.output_filter_edit:
            ui.output_filter_edit.setVisible(visible)
        if ui.input_filter_edit:
            ui.input_filter_edit.setVisible(visible)
        if ui.zoom_in_button:
            ui.zoom_in_button.setVisible(visible)
        if ui.zoom_out_button:
            ui.zoom_out_button.setVisible(visible)

    def _update_global_zoom_action_state(self, current_tab_index: int) -> None:
        """
        Enable/disable global zoom actions based on the active tab.

        Args:
            current_tab_index: Current tab index
        """
        if not self.tab_widget or not self.connection_manager.action_manager:
            return

        current_widget = self.tab_widget.widget(current_tab_index)
        is_alsa_mixer_tab_active = (
            current_widget == self.connection_manager.ui_manager.alsa_mixer_tab_widget
        )

        if self.connection_manager.action_manager.zoom_in_action:
            self.connection_manager.action_manager.zoom_in_action.setEnabled(
                not is_alsa_mixer_tab_active
            )
        if self.connection_manager.action_manager.zoom_out_action:
            self.connection_manager.action_manager.zoom_out_action.setEnabled(
                not is_alsa_mixer_tab_active
            )

    def _update_zoom_button_tooltips(self, current_tab_index: int) -> None:
        """
        Update zoom button tooltips based on the active tab.

        Args:
            current_tab_index: Current tab index
        """
        ui_manager = self.connection_manager.ui_manager

        current_tab_text = self.tab_widget.tabText(current_tab_index)

        if current_tab_text in ["Audio", "MIDI"]:
            if ui_manager.zoom_in_button:
                ui_manager.zoom_in_button.setToolTip(
                    "Increase port list font size <span style='color:grey'>Ctrl++</span>"
                )
            if ui_manager.zoom_out_button:
                ui_manager.zoom_out_button.setToolTip(
                    "Decrease port list font size <span style='color:grey'>Ctrl+-</span>"
                )
        elif current_tab_text == "MIDI Matrix":
            # The zoom buttons are in the tab, not in the bottom bar
            pass

    def handle_tab_switch_request(self, forwards: bool) -> None:
        """
        Handle tab switch request from ActionManager (Tab/Shift+Tab shortcuts).

        Switches focus between output and input trees on Audio/MIDI tabs,
        and selects connected ports when switching.

        Args:
            forwards: True for Tab (output→input), False for Shift+Tab (input→output)
        """
        if not self.tab_widget:
            return

        current_tab = self.tab_widget.currentIndex()
        current_tab_text = self.tab_widget.tabText(current_tab)

        # Get tree references
        output_tree = getattr(self.connection_manager, "output_tree", None)
        input_tree = getattr(self.connection_manager, "input_tree", None)
        midi_output_tree = getattr(self.connection_manager, "midi_output_tree", None)
        midi_input_tree = getattr(self.connection_manager, "midi_input_tree", None)

        # Determine which trees to use based on current tab name (not index)
        if current_tab_text == "Audio":
            trees = [output_tree, input_tree] if forwards else [input_tree, output_tree]
            is_midi = False
        elif current_tab_text == "MIDI":
            trees = (
                [midi_output_tree, midi_input_tree]
                if forwards
                else [midi_input_tree, midi_output_tree]
            )
            is_midi = True
        else:
            # Not on Audio or MIDI tab, do nothing
            return

        # Filter out None trees
        trees = [tree for tree in trees if tree]
        if not trees:
            return

        # Find which tree currently has focus
        current_tree = None
        for tree in trees:
            if tree and tree.hasFocus():
                current_tree = tree
                break

        if current_tree:
            # Switch to the other tree
            other_tree = trees[1] if current_tree == trees[0] else trees[0]
            if not other_tree:
                return

            # Get selected ports from current tree
            selected_ports = self.connection_manager._get_ports_from_selected_items(
                current_tree
            )
            if selected_ports:
                # Determine direction and get connected ports
                is_input_to_output = current_tree in (input_tree, midi_input_tree)
                connected_ports = self._get_connected_ports(
                    selected_ports, is_input_to_output, is_midi
                )

                # Select connected ports in the other tree
                other_tree.clearSelection()
                for port_name in connected_ports:
                    port_item = other_tree.port_items.get(port_name)
                    if port_item:
                        port_item.setSelected(True)

            # Move focus to the other tree
            other_tree.setFocus()

            # Update connection button states
            if is_midi:
                self.connection_manager.update_midi_connection_buttons()
            else:
                self.connection_manager.update_connection_buttons()
        elif trees[0]:
            # No tree has focus, focus the first one
            trees[0].setFocus()

    def handle_zoom_request(self, direction: int) -> None:
        """
        Handle zoom request from ActionManager (Ctrl+/Ctrl- shortcuts).

        Routes zoom to the appropriate component based on current tab:
        - Graph tab: zoom the graph view
        - MIDI Matrix tab: zoom the matrix widget
        - Audio/MIDI tabs: change port list font size
        - Other tabs: do nothing

        Args:
            direction: 1 for zoom in, -1 for zoom out
        """
        if not self.tab_widget:
            return

        current_tab = self.tab_widget.currentIndex()
        current_tab_text = self.tab_widget.tabText(current_tab)

        # Graph tab - zoom the graph view
        if current_tab_text == "Graph":
            graph_window = self.connection_manager._get_graph_main_window()
            if graph_window and getattr(graph_window, "view", None) is not None:
                if direction > 0:
                    graph_window.view.zoom_in()
                else:
                    graph_window.view.zoom_out()
            return

        # MIDI Matrix tab - zoom the matrix widget
        if current_tab_text == "MIDI Matrix":
            midi_matrix_widget = getattr(
                self.connection_manager, "midi_matrix_widget", None
            )
            if midi_matrix_widget is not None:
                if direction > 0:
                    midi_matrix_widget.zoom_in()
                else:
                    midi_matrix_widget.zoom_out()
            return

        # Audio Matrix tab - zoom the matrix widget
        if current_tab_text == "Audio Matrix":
            audio_matrix_widget = getattr(
                self.connection_manager, "audio_matrix_widget", None
            )
            if audio_matrix_widget is not None:
                if direction > 0:
                    audio_matrix_widget.zoom_in()
                else:
                    audio_matrix_widget.zoom_out()
            return

        # Audio/MIDI tabs - change port list font size
        if current_tab_text in ("Audio", "MIDI"):
            if direction > 0:
                self.connection_manager.ui_state_manager.increase_font_size()
            else:
                self.connection_manager.ui_state_manager.decrease_font_size()
            return

        # Other tabs (pw-top, ALSA Mixer, Latency, Cable) - no zoom action

    def _get_connected_ports(
        self, port_names: List[str], is_input_to_output: bool, is_midi: bool
    ) -> List[str]:
        """
        Get ports connected to the given port names.

        Args:
            port_names: List of port names to check connections for
            is_input_to_output: True if checking input→output, False for output→input
            is_midi: True if checking MIDI ports, False for audio

        Returns:
            List of connected port names
        """
        connected_ports = set()
        from cables.jack_service import get_jack_service

        jack_service = get_jack_service()

        try:
            if is_input_to_output:
                # Looking for outputs connected to the given inputs
                output_ports = jack_service.get_ports(is_output=True, is_midi=is_midi)
                for output_port in output_ports:
                    try:
                        connected_inputs = jack_service.get_all_connections(output_port)
                        if any(conn.name in port_names for conn in connected_inputs):
                            connected_ports.add(output_port.name)
                    except jack.JackError:
                        continue
            else:
                # Looking for inputs connected to the given outputs
                for port_name in port_names:
                    try:
                        connections = jack_service.get_all_connections(port_name)
                        connected_ports.update(conn.name for conn in connections)
                    except jack.JackError:
                        continue
        except jack.JackError as e:
            logger.error(f"Error getting connected ports: {e}")

        return list(connected_ports)
