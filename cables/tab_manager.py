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

        # Setup individual tabs
        self.tab_ui_manager.setup_port_tab(
            self.connection_manager, self.connection_manager.ui_manager.audio_tab_widget, "Audio", 'audio'
        )
        self.tab_ui_manager.setup_port_tab(
            self.connection_manager, self.connection_manager.ui_manager.midi_tab_widget, "MIDI", 'midi'
        )

        # Setup pw-top tab
        self.tab_ui_manager.setup_pwtop_tab(self.connection_manager, self.connection_manager.ui_manager.pwtop_tab_widget)
        self.connection_manager.pwtop_monitor = getattr(self.connection_manager, 'pwtop_monitor', None)

        # Setup latency tab
        self.tab_ui_manager.setup_latency_tab(self.connection_manager, self.connection_manager.ui_manager.latency_tab_widget)
        self.connection_manager.latency_tester = getattr(self.connection_manager, 'latency_tester', None)

        # New Tab Order:
        # Audio (0), MIDI (1), Graph (2), pw-top (3), Alsa Mixer (4), Latency Test (5)
        self.tab_widget.addTab(self.connection_manager.ui_manager.audio_tab_widget, "Audio") # Index 0
        self.tab_widget.addTab(self.connection_manager.ui_manager.midi_tab_widget, "MIDI")   # Index 1

        self.tab_ui_manager.setup_graph_tab(self.connection_manager, self.connection_manager.ui_manager.graph_tab_widget)
        self.tab_widget.insertTab(2, self.connection_manager.ui_manager.graph_tab_widget, "Graph") # Index 2

        self.tab_widget.addTab(self.connection_manager.ui_manager.pwtop_tab_widget, "pw-top") # Index 3

        # Alsa Mixer tab (index 4)
        alsa_mixer_layout = QVBoxLayout(self.connection_manager.ui_manager.alsa_mixer_tab_widget)
        self.connection_manager.alsa_mixer_app = AlsMixerApp(config_manager=self.connection_manager.config_manager) # Pass ConfigManager
        alsa_mixer_layout.addWidget(self.connection_manager.alsa_mixer_app)
        self.tab_widget.insertTab(4, self.connection_manager.ui_manager.alsa_mixer_tab_widget, "ALSA Mixer") # Index 4

        self.tab_widget.addTab(self.connection_manager.ui_manager.latency_tab_widget, "Latency Test") # Index 5

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

        # Set initial state for global zoom actions
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        self._update_global_zoom_action_state(current_tab)

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
        # Audio (0), MIDI (1), Graph (2), pw-top (3), Alsa Mixer (4), Latency Test (5)

        # Stop pw-top monitor if switching away from it (pw-top is now index 3)
        if index != 3 and hasattr(self.connection_manager, 'pwtop_monitor') and self.connection_manager.pwtop_monitor is not None:
            self.connection_manager.pwtop_monitor.stop()

        # Configure based on the new tab index
        if index < 2:  # Audio (0) or MIDI (1) tabs
            self.connection_manager.port_type = 'audio' if index == 0 else 'midi'
            if hasattr(self.connection_manager, 'ui_state_manager'):
                 self.connection_manager.ui_state_manager.apply_collapse_state_to_current_trees()
            self.connection_manager.refresh_visualizations()
            self.show_bottom_controls(True)
        elif index == 2: # Graph tab (index 2)
            self.show_bottom_controls(False)
            # Disable global Alt+U shortcut when Graph tab is active to allow Graph-specific Alt+U handling
            if hasattr(self.connection_manager, 'action_manager') and hasattr(self.connection_manager.action_manager, 'untangle_shortcut_action'):
                self.connection_manager.action_manager.untangle_shortcut_action.setEnabled(False)
            if hasattr(self.connection_manager, 'graph_main_window') and self.connection_manager.graph_main_window:
                if hasattr(self.connection_manager.graph_main_window, 'scene') and self.connection_manager.graph_main_window.scene:
                    self.connection_manager.graph_main_window.scene.full_graph_refresh()
        elif index == 3:  # pw-top tab (index 3)
            if hasattr(self.connection_manager, 'pwtop_monitor') and self.connection_manager.pwtop_monitor is not None:
                self.connection_manager.pwtop_monitor.start()
            self.show_bottom_controls(False)
        elif index == 4: # Alsa Mixer tab (index 4)
            self.show_bottom_controls(False)
            if hasattr(self.connection_manager, 'alsa_mixer_app') and self.connection_manager.alsa_mixer_app:
                # Start ALSA mixer updates only if the window is focused
                if self.connection_manager.isActiveWindow():
                    self.connection_manager.alsa_mixer_app.start_updates()
        elif index == 5:  # Latency Test tab (index 5)
            self.show_bottom_controls(False)

        # Stop ALSA mixer updates when switching away from the tab
        if self.last_active_tab == 4 and hasattr(self.connection_manager, 'alsa_mixer_app') and self.connection_manager.alsa_mixer_app:
            self.connection_manager.alsa_mixer_app.stop_updates()

        # Re-enable global Alt+U shortcut when switching away from Graph tab
        if self.last_active_tab == 2:  # Was previously on Graph tab
            if hasattr(self.connection_manager, 'action_manager') and hasattr(self.connection_manager.action_manager, 'untangle_shortcut_action'):
                self.connection_manager.action_manager.untangle_shortcut_action.setEnabled(True)

        self.last_active_tab = index
        self.connection_manager.config_manager.set_int('last_active_tab', index)

        # Update global zoom action enabled state
        self._update_global_zoom_action_state(index)

        if hasattr(self.connection_manager, 'ui_state_manager') and self.connection_manager.ui_state_manager:
             self.connection_manager.ui_state_manager._update_refresh_timer_interval()

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
