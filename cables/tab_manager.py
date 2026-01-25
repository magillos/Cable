#!/usr/bin/env python3
"""
Tab Manager - Handles UI tab management for JackConnectionManager
"""

import sys
import os
from typing import Optional, TYPE_CHECKING

from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtCore import Qt

# Import core components
from cables.ui.tab_ui_manager import TabUIManager
from cables.features.mixer import AlsMixerApp
from cables.action_manager import ActionManager

if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager


class TabManager:
    """
    Manages all tab-related UI and state logic for the connection manager.

    This service handles:
    - Tab initialization and setup
    - Tab switching and state management
    - Bottom UI controls visibility
    - Global zoom action state coordination
    """

    def __init__(self, connection_manager: 'JackConnectionManager'):
        """
        Initialize TabManager with reference to main connection manager.

        Args:
            connection_manager: Reference to JackConnectionManager instance
        """

        self.connection_manager = connection_manager
        self.tab_ui_manager = TabUIManager()
        self.last_active_tab = 0

        # UI element references (populated during setup)
        self.tab_widget = None
        self.alsa_mixer_app = None
        self.pwtop_monitor = None
        self.latency_tester = None

    def setup_tabs(self):
        """Setup all tabs in the connection manager."""

        # Get reference to tab widget from ui_manager
        self.tab_widget = self.connection_manager.ui_manager.tab_widget

        # Check if Cable should be integrated as the first tab
        self.integrated_mode = self.connection_manager.config_manager.get_bool('integrate_cable_and_cables', False)
        if self.integrated_mode:
            self._add_cable_tab()

        # Setup individual tabs
        self.tab_ui_manager.setup_port_tab(
            self.connection_manager, self.connection_manager.ui_manager.audio_tab_widget, "Audio", 'audio'
        )
        self.tab_ui_manager.setup_port_tab(
            self.connection_manager, self.connection_manager.ui_manager.midi_tab_widget, "MIDI", 'midi'
        )

        # Conditionally setup and add MIDI Matrix tab
        if self.connection_manager.config_manager.get_bool('enable_midi_matrix', False):
            self.tab_ui_manager.setup_midi_matrix_tab(
                self.connection_manager, self.connection_manager.ui_manager.midi_matrix_tab_widget
            )

        # Setup pw-top tab
        self.tab_ui_manager.setup_pwtop_tab(self.connection_manager, self.connection_manager.ui_manager.pwtop_tab_widget)
        self.connection_manager.pwtop_monitor = getattr(self.connection_manager, 'pwtop_monitor', None)

        # Setup latency tab
        self.tab_ui_manager.setup_latency_tab(self.connection_manager, self.connection_manager.ui_manager.latency_tab_widget)
        self.connection_manager.latency_tester = getattr(self.connection_manager, 'latency_tester', None)

        # New Tab Order:
        # Audio (0), MIDI (1), MIDI Matrix (2), Graph (3), pw-top (4), Alsa Mixer (5), Latency Test (6)
        self.tab_widget.addTab(self.connection_manager.ui_manager.audio_tab_widget, "Audio") # Index 0
        self.tab_widget.addTab(self.connection_manager.ui_manager.midi_tab_widget, "MIDI")   # Index 1
        
        if self.connection_manager.config_manager.get_bool('enable_midi_matrix', False):
            self.tab_widget.addTab(self.connection_manager.ui_manager.midi_matrix_tab_widget, "MIDI Matrix") # Index 2

        self.tab_ui_manager.setup_graph_tab(self.connection_manager, self.connection_manager.ui_manager.graph_tab_widget)
        self.tab_widget.insertTab(self.tab_widget.count(), self.connection_manager.ui_manager.graph_tab_widget, "Graph")

        self.tab_widget.addTab(self.connection_manager.ui_manager.pwtop_tab_widget, "pw-top")

        # Alsa Mixer tab
        alsa_mixer_layout = QVBoxLayout(self.connection_manager.ui_manager.alsa_mixer_tab_widget)
        self.connection_manager.alsa_mixer_app = AlsMixerApp(config_manager=self.connection_manager.config_manager) # Pass ConfigManager
        alsa_mixer_layout.addWidget(self.connection_manager.alsa_mixer_app)
        self.tab_widget.insertTab(self.tab_widget.count(), self.connection_manager.ui_manager.alsa_mixer_tab_widget, "ALSA Mixer")

        self.tab_widget.addTab(self.connection_manager.ui_manager.latency_tab_widget, "Latency Test")

        # Setup fullscreen functionality
        if hasattr(self.connection_manager, 'graph_main_window') and self.connection_manager.graph_main_window and \
           hasattr(self.connection_manager.graph_main_window, 'view') and self.connection_manager.graph_main_window.view and \
           hasattr(self.connection_manager.graph_main_window.view, 'fullscreen_request_signal'):
            self.connection_manager.graph_main_window.view.fullscreen_request_signal.connect(self.connection_manager.toggle_graph_fullscreen)

        # Load last active tab from config
        self.last_active_tab = self.connection_manager.config_manager.get_int('last_active_tab', 0)
        if 0 <= self.last_active_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(self.last_active_tab)

        # Connect tab switching signal
        self.tab_widget.currentChanged.connect(self.switch_tab)

        # Set initial state for global zoom actions and tooltips
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        self._update_zoom_button_tooltips(current_tab)
        self._update_global_zoom_action_state(current_tab)

        self._setup_midi_matrix_v_splitter()

    def _add_cable_tab(self):
        """Add Cable (PipeWireSettingsApp) as the first tab when integrated mode is enabled."""
        # Use local import to avoid circular imports
        from Cable import PipeWireSettingsApp
        
        # Create Cable widget in embedded mode
        self.cable_widget = PipeWireSettingsApp(embedded=True, parent=self.tab_widget)
        self.connection_manager.cable_widget = self.cable_widget  # Store reference on connection manager
        
        # Insert as the first tab
        self.tab_widget.insertTab(0, self.cable_widget, "Cable")
        print("Added Cable tab in integrated mode")

    def _setup_midi_matrix_v_splitter(self):
        """Setup MIDI Matrix vertical splitter position loading and saving."""
        if hasattr(self.connection_manager, 'midi_matrix_v_splitter') and self.connection_manager.midi_matrix_v_splitter:
            # Load splitter sizes from config
            splitter_sizes_str = self.connection_manager.config_manager.get_str('midi_matrix_v_splitter_sizes', '0,400')
            try:
                sizes = [int(x.strip()) for x in splitter_sizes_str.split(',')]
                if len(sizes) == 2:
                    self.connection_manager.midi_matrix_v_splitter.setSizes(sizes)
            except (ValueError, IndexError):
                # Use default sizes if config is invalid
                self.connection_manager.midi_matrix_v_splitter.setSizes([0, 400])

            # Connect splitterMoved signal to save position
            self.connection_manager.midi_matrix_v_splitter.splitterMoved.connect(self._save_midi_matrix_v_splitter_sizes)

    def _save_midi_matrix_v_splitter_sizes(self, pos, index):
        """Save MIDI Matrix vertical splitter sizes to config when splitter is moved."""
        if hasattr(self.connection_manager, 'midi_matrix_v_splitter') and self.connection_manager.midi_matrix_v_splitter:
            sizes = self.connection_manager.midi_matrix_v_splitter.sizes()
            if len(sizes) == 2:
                sizes_str = f"{sizes[0]},{sizes[1]}"
                self.connection_manager.config_manager.set_str('midi_matrix_v_splitter_sizes', sizes_str)


    def _setup_bottom_layout(self, main_layout):
        """Setup bottom UI controls layout."""
        bottom_layout = self.connection_manager._setup_bottom_layout(main_layout)
        return bottom_layout

    def switch_tab(self, index: int):
        """
        Handle tab switching.

        Args:
            index: The index of the tab to switch to
        """
        # New Tab Order:
        # Audio (0), MIDI (1), MIDI Matrix (2), Graph (3), pw-top (4), Alsa Mixer (5), Latency Test (6)

        # Stop pw-top monitor if switching away from it
        if self.tab_widget.tabText(self.last_active_tab) == "pw-top" and hasattr(self.connection_manager, 'pwtop_monitor') and self.connection_manager.pwtop_monitor is not None:
            self.connection_manager.pwtop_monitor.stop()

        # Configure based on the new tab index
        current_tab_text = self.tab_widget.tabText(index)

        if current_tab_text in ["Audio", "MIDI"]:
            self.connection_manager.port_type = 'audio' if current_tab_text == "Audio" else 'midi'
            if hasattr(self.connection_manager, 'ui_state_manager'):
                 self.connection_manager.ui_state_manager.apply_collapse_state_to_current_trees()
            self.connection_manager.refresh_visualizations()
            self.show_bottom_controls(True)
        elif current_tab_text == "MIDI Matrix":
            self.show_bottom_controls(False)
        elif current_tab_text == "Graph":
            self.show_bottom_controls(False)
            if hasattr(self.connection_manager, 'graph_main_window') and self.connection_manager.graph_main_window:
                if hasattr(self.connection_manager.graph_main_window, 'scene') and self.connection_manager.graph_main_window.scene:
                    self.connection_manager.graph_main_window.scene.full_graph_refresh()
        elif current_tab_text == "pw-top":
            if hasattr(self.connection_manager, 'pwtop_monitor') and self.connection_manager.pwtop_monitor is not None:
                self.connection_manager.pwtop_monitor.start()
            self.show_bottom_controls(False)
        elif current_tab_text == "ALSA Mixer":
            self.show_bottom_controls(False)
            if hasattr(self.connection_manager, 'alsa_mixer_app') and self.connection_manager.alsa_mixer_app:
                # Start ALSA mixer updates only if the window is focused
                if self.connection_manager.isActiveWindow():
                    self.connection_manager.alsa_mixer_app.start_updates()
        elif current_tab_text == "Latency Test":
            self.show_bottom_controls(False)
        elif current_tab_text == "Cable":
            self.show_bottom_controls(False)
            # Refresh Cable's pipewire settings when switching to Cable tab
            if hasattr(self, 'cable_widget') and self.cable_widget:
                self.cable_widget.pipewire_manager.load_current_settings()
                self.cable_widget.pipewire_manager.load_devices()
                self.cable_widget.pipewire_manager.load_nodes()
                self.cable_widget.update_latency_display()

        # Stop ALSA mixer updates when switching away from the tab
        if self.tab_widget.tabText(self.last_active_tab) == "ALSA Mixer" and hasattr(self.connection_manager, 'alsa_mixer_app') and self.connection_manager.alsa_mixer_app:
            self.connection_manager.alsa_mixer_app.stop_updates()

        self.last_active_tab = index
        self.connection_manager.config_manager.set_int('last_active_tab', index)

        # Update zoom button tooltips based on tab
        self._update_zoom_button_tooltips(index)

        # Update global zoom action enabled state
        self._update_global_zoom_action_state(index)

    def show_bottom_controls(self, visible: bool):
        """
        Show or hide bottom UI controls.

        Args:
            visible: Whether to show the controls
        """
        # Access controls from ui_manager since they were moved there
        if hasattr(self.connection_manager.ui_manager, 'auto_refresh_checkbox') and self.connection_manager.ui_manager.auto_refresh_checkbox:
            self.connection_manager.ui_manager.auto_refresh_checkbox.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'untangle_button') and self.connection_manager.ui_manager.untangle_button:
            self.connection_manager.ui_manager.untangle_button.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'collapse_all_checkbox') and self.connection_manager.ui_manager.collapse_all_checkbox:
            self.connection_manager.ui_manager.collapse_all_checkbox.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'bottom_refresh_button') and self.connection_manager.ui_manager.bottom_refresh_button:
            self.connection_manager.ui_manager.bottom_refresh_button.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'undo_button') and self.connection_manager.ui_manager.undo_button:
            self.connection_manager.ui_manager.undo_button.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'redo_button') and self.connection_manager.ui_manager.redo_button:
            self.connection_manager.ui_manager.redo_button.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'output_filter_edit') and self.connection_manager.ui_manager.output_filter_edit:
            self.connection_manager.ui_manager.output_filter_edit.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'input_filter_edit') and self.connection_manager.ui_manager.input_filter_edit:
            self.connection_manager.ui_manager.input_filter_edit.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'zoom_in_button') and self.connection_manager.ui_manager.zoom_in_button:
            self.connection_manager.ui_manager.zoom_in_button.setVisible(visible)
        if hasattr(self.connection_manager.ui_manager, 'zoom_out_button') and self.connection_manager.ui_manager.zoom_out_button:
            self.connection_manager.ui_manager.zoom_out_button.setVisible(visible)


    def _update_global_zoom_action_state(self, current_tab_index: int):
        """
        Enable/disable global zoom actions based on the active tab.

        Args:
            current_tab_index: Current tab index
        """
        if not hasattr(self, 'tab_widget') or not hasattr(self.connection_manager, 'action_manager') or \
           not self.connection_manager.action_manager:
            return

        current_widget = self.tab_widget.widget(current_tab_index)
        is_alsa_mixer_tab_active = (current_widget == self.connection_manager.ui_manager.alsa_mixer_tab_widget)

        if hasattr(self.connection_manager.action_manager, 'zoom_in_action') and self.connection_manager.action_manager.zoom_in_action:
            self.connection_manager.action_manager.zoom_in_action.setEnabled(not is_alsa_mixer_tab_active)
        if hasattr(self.connection_manager.action_manager, 'zoom_out_action') and self.connection_manager.action_manager.zoom_out_action:
            self.connection_manager.action_manager.zoom_out_action.setEnabled(not is_alsa_mixer_tab_active)

    def _update_zoom_button_tooltips(self, current_tab_index: int):
        """
        Update zoom button tooltips based on the active tab.

        Args:
            current_tab_index: Current tab index
        """
        if not hasattr(self.connection_manager, 'ui_manager'):
            return

        ui_manager = self.connection_manager.ui_manager

        current_tab_text = self.tab_widget.tabText(current_tab_index)

        if current_tab_text in ["Audio", "MIDI"]:
            if hasattr(ui_manager, 'zoom_in_button') and ui_manager.zoom_in_button:
                ui_manager.zoom_in_button.setToolTip("Increase port list font size <span style='color:grey'>Ctrl++</span>")
            if hasattr(ui_manager, 'zoom_out_button') and ui_manager.zoom_out_button:
                ui_manager.zoom_out_button.setToolTip("Decrease port list font size <span style='color:grey'>Ctrl+-</span>")
        elif current_tab_text == "MIDI Matrix":
            # The zoom buttons are in the tab, not in the bottom bar
            pass
