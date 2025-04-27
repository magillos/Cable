#!/usr/bin/env python3
"""
Cables - A JACK/PipeWire connection manager
"""

import sys
import argparse
import os
import jack
import random
import re
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
                            QHBoxLayout, QCheckBox, QPushButton, QLineEdit, QSizePolicy,
                            QSpacerItem, QMessageBox, QGraphicsPathItem, QTreeWidget) # Removed QSize
from PyQt6.QtCore import Qt, QMimeData, QPointF, QRectF, QTimer, QSize, QRect, QProcess, pyqtSignal, QPoint
from PyQt6.QtGui import QGuiApplication, QColor, QPalette, QFont, QKeySequence, QAction, QTextCursor, QPainterPath, QPen, QBrush

# Import our modules
from cables.config.config_manager import ConfigManager
from cables.config.preset_manager import PresetManager
from cables.features.connection_history import ConnectionHistory
from cables.features.preset_handler import PresetHandler
from cables.ui.tab_ui_manager import TabUIManager
from cable_core import app_config

class JackConnectionManager(QMainWindow):
    """
    Main application window for the JACK/PipeWire connection manager.
    
    This class manages the UI and functionality for connecting and
    disconnecting JACK/PipeWire ports, as well as managing presets.
    """
    
    # PyQt signals for port registration events
    port_registered = pyqtSignal(str, bool)  # port name, is_input
    port_unregistered = pyqtSignal(str, bool)  # port name, is_input
    untangle_mode_changed = pyqtSignal(int)  # Signal for mode change
    
    def __init__(self):
        """Initialize the JackConnectionManager."""
        super().__init__()
        
        # Initialize configuration and preset managers
        self.config_manager = ConfigManager()
        self.preset_manager = PresetManager()
        self.preset_handler = PresetHandler(self)
        
        # Read last active tab from config
        self.last_active_tab = self.config_manager.get_int('last_active_tab', 0)
        
        # Set up the main window
        self.setWindowTitle('Cables')
        self.setGeometry(app_config.CONN_MANAGER_INITIAL_X, app_config.CONN_MANAGER_INITIAL_Y, app_config.CONN_MANAGER_INITIAL_WIDTH, app_config.CONN_MANAGER_INITIAL_HEIGHT)
        self.initial_middle_width = 250
        self.port_type = 'audio'
        
        # Initialize JACK client
        self.client = jack.Client('ConnectionManager')
        
        # Initialize connection history
        self.connection_history = ConnectionHistory()
        
        # Initialize untangle mode
        self.untangle_mode = self.config_manager.get_int('untangle_mode', 0)
        
        # Detect Flatpak environment
        self.flatpak_env = os.path.exists('/.flatpak-info')
        
        # Set up colors
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()
        
        # Initialize auto-refresh state
        self.callbacks_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        self.is_focused = self.isActiveWindow()
        
        # Load and store initial port list font size
        try:
            self.port_list_font_size = int(self.config_manager.get_str('port_list_font_size', '10'))
        except ValueError:
            self.port_list_font_size = 10  # Default if config value is invalid
        
        # Create filter edit widgets
        self.output_filter_edit = QLineEdit()
        self.output_filter_edit.setPlaceholderText("Filter outputs...")
        self.output_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        self.input_filter_edit = QLineEdit()
        self.input_filter_edit.setPlaceholderText("Filter inputs...")
        self.input_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        
        # Set up JACK port registration callbacks
        self.client.set_port_registration_callback(self._handle_port_registration)
        
        # Connect signals to refresh methods
        self.port_registered.connect(self._on_port_registered)
        self.port_unregistered.connect(self._on_port_unregistered)
        
        # Set up the UI
        self._setup_ui()
        
        
        # Set up shortcuts and actions
        self._setup_actions()
        self.setup_shortcuts()
        
        # Connect preset button signals after UI is set up
        if hasattr(self, 'presets_button') and self.presets_button:
            self.presets_button.clicked.connect(self.preset_handler._show_preset_menu)
        if hasattr(self, 'midi_presets_button') and self.midi_presets_button:
            self.midi_presets_button.clicked.connect(self.preset_handler._show_preset_menu)
        
        # Activate JACK client
        self.client.activate()
        
        # Set initial state for the global save shortcut based on loaded preset
        if hasattr(self, 'save_preset_action'):
            self.save_preset_action.setEnabled(bool(self.preset_handler.current_preset_name))
    
    def _setup_ui(self):
        """Set up the main UI components."""
        # Create central widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Create tab widgets
        self.audio_tab_widget = QWidget()
        self.midi_tab_widget = QWidget()
        self.pwtop_tab_widget = QWidget()
        self.latency_tab_widget = QWidget()
        
        # Set up tabs using TabUIManager
        self.tab_ui_manager = TabUIManager()
        self.tab_ui_manager.setup_port_tab(self, self.audio_tab_widget, "Audio", 'audio')
        self.tab_ui_manager.setup_port_tab(self, self.midi_tab_widget, "MIDI", 'midi')
        self.tab_ui_manager.setup_pwtop_tab(self, self.pwtop_tab_widget)
        self.tab_ui_manager.setup_latency_tab(self, self.latency_tab_widget)
        
        # Add tabs to tab widget
        self.tab_widget.addTab(self.audio_tab_widget, "Audio")
        self.tab_widget.addTab(self.midi_tab_widget, "MIDI")
        self.tab_widget.addTab(self.pwtop_tab_widget, "pw-top")
        self.tab_widget.addTab(self.latency_tab_widget, "Latency Test")
        
        # Set the active tab based on the saved value
        if 0 <= self.last_active_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(self.last_active_tab)
        
        # Set up bottom layout
        self._setup_bottom_layout(main_layout)
        
        # Connect tab change signal
        self.tab_widget.currentChanged.connect(self.switch_tab)
        
        # Explicitly call switch_tab for the initial index to ensure setup runs
        self.switch_tab(self.tab_widget.currentIndex())
    
    def _setup_bottom_layout(self, main_layout):
        """Set up the bottom layout with controls."""
        bottom_layout = QHBoxLayout()
        
        # Auto Refresh checkbox
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        auto_refresh_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        self.auto_refresh_checkbox.setChecked(auto_refresh_enabled)
        self.auto_refresh_checkbox.setToolTip("Toggle automatic refreshing of ports and connections (Alt+R)")
        
        # Collapse All toggle
        self.collapse_all_checkbox = QCheckBox('Collapse All')
        collapse_all_enabled = self.config_manager.get_bool('collapse_all_enabled', False)
        self.collapse_all_checkbox.setChecked(collapse_all_enabled)
        self.collapse_all_checkbox.setToolTip("Toggle collapse state for all groups (Alt+C)")
        self.collapse_all_checkbox.stateChanged.connect(self.toggle_collapse_all)
        
        # Undo/Redo buttons
        self.undo_button = QPushButton('       Undo       ')
        self.undo_button.setToolTip("Undo last action (Ctrl+Z)")
        self.redo_button = QPushButton('       Redo       ')
        self.redo_button.setToolTip("Redo last action (Ctrl+Y/Ctrl+Shift+Z)")
        
        for button in [self.undo_button, self.redo_button]:
            button.setStyleSheet(self.button_stylesheet())
            button.setEnabled(False)
        
        # Apply style to filter edits
        filter_style = f"""
            QLineEdit {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                border: 1px solid {self.text_color.name()};
                padding: 2px;
                border-radius: 3px;
            }}
        """
        
        # Apply style and fixed width to filter edits
        if hasattr(self, 'output_filter_edit'):
            self.output_filter_edit.setStyleSheet(filter_style)
            self.output_filter_edit.setClearButtonEnabled(True)
            self.output_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.output_filter_edit)  # Add output filter to the far left
        
        bottom_layout.addStretch(1)  # Push central controls away from left filter
        
        # Refresh button
        self.bottom_refresh_button = QPushButton('     Refresh     ')
        self.bottom_refresh_button.setToolTip("Refresh port list (R)")
        self.bottom_refresh_button.setStyleSheet(self.button_stylesheet())
        self.bottom_refresh_button.clicked.connect(self.refresh_ports)
        
        # Untangle button
        self.untangle_button = QPushButton()  # Text set by _update_untangle_button_text
        self.untangle_button.setStyleSheet(self.button_stylesheet())
        self.untangle_button.setToolTip("Untangle cables: Default -> A -> B (Alt+U)")
        self.untangle_button.clicked.connect(self.toggle_untangle_sort)
        self._update_untangle_button_text()  # Set initial text based on loaded mode
        
        # Add widgets to bottom layout
        bottom_layout.addWidget(self.collapse_all_checkbox)
        bottom_layout.addWidget(self.auto_refresh_checkbox)
        bottom_layout.addWidget(self.bottom_refresh_button)
        bottom_layout.addWidget(self.untangle_button)
        bottom_layout.addWidget(self.undo_button)
        bottom_layout.addWidget(self.redo_button)
        bottom_layout.addStretch(1)  # Push zoom and input filter away from central controls
        
        # Add Zoom Buttons
        self.zoom_in_button = QPushButton('+')
        self.zoom_in_button.setToolTip("Increase port list font size (Ctrl++)")
        self.zoom_in_button.setStyleSheet(self.button_stylesheet())
        zoom_button_size = QSize(25, 25)  # Define smaller, square size
        self.zoom_in_button.setFixedSize(zoom_button_size)
        self.zoom_in_button.clicked.connect(self.increase_font_size)
        
        self.zoom_out_button = QPushButton('-')
        self.zoom_out_button.setToolTip("Decrease port list font size (Ctrl+-)")
        self.zoom_out_button.setStyleSheet(self.button_stylesheet())
        self.zoom_out_button.setFixedSize(zoom_button_size)
        self.zoom_out_button.clicked.connect(self.decrease_font_size)
        
        bottom_layout.addWidget(self.zoom_out_button)
        bottom_layout.addWidget(self.zoom_in_button)
        
        if hasattr(self, 'input_filter_edit'):
            self.input_filter_edit.setStyleSheet(filter_style)
            self.input_filter_edit.setClearButtonEnabled(True)
            self.input_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.input_filter_edit)  # Add input filter to the far right
        
        main_layout.addLayout(bottom_layout)
        
        # Connect signals
        self.auto_refresh_checkbox.stateChanged.connect(self.toggle_auto_refresh)
        self.undo_button.clicked.connect(self.undo_action)
        self.redo_button.clicked.connect(self.redo_action)
        
        # Initialize callback state from config
        self.callbacks_enabled = auto_refresh_enabled
        
        # Initialize visibility based on current tab
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        self.show_bottom_controls(current_tab < 2)
        
        # Start visualization timers if auto-refresh is enabled in config
        if auto_refresh_enabled:
            self.connection_view.start_refresh_timer(self.refresh_visualizations)
            self.midi_connection_view.start_refresh_timer(self.refresh_visualizations)
    
    def is_dark_mode(self):
        """
        Determine if the application is in dark mode.
        
        Returns:
            bool: True if in dark mode, False otherwise
        """
        palette = QApplication.palette()
        return palette.window().color().lightness() < 128
    
    def setup_colors(self):
        """Set up colors based on dark mode."""
        if self.dark_mode:
            self.background_color = QColor(24, 26, 33)  # Made background darker
            self.text_color = QColor(255, 255, 255)
            self.highlight_color = QColor(20, 62, 104)
            self.button_color = QColor(68, 68, 68)
            self.connection_color = QColor(0, 150, 255)  # Brighter blue for dark mode
            self.auto_highlight_color = QColor(255, 200, 0)  # Brighter orange
            self.drag_highlight_color = QColor(41, 61, 90)  # New color for drag highlight
        else:
            self.background_color = QColor(255, 255, 255)
            self.text_color = QColor(0, 0, 0)
            self.highlight_color = QColor(173, 216, 230)
            self.button_color = QColor(240, 240, 240)
            self.connection_color = QColor(0, 100, 200)
            self.auto_highlight_color = QColor(255, 140, 0)
            self.drag_highlight_color = QColor(200, 200, 200)  # New color for drag highlight
    
    def list_stylesheet(self):
        """
        Get the stylesheet for list widgets.
        
        Returns:
            str: The stylesheet
        """
        highlight_bg = self.highlight_color.name()
        # Use white text for dark mode highlight, black for light mode highlight
        selected_text_color = "#ffffff" if self.dark_mode else "#000000"
        
        return f"""
            QListWidget {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
            }}
            QListWidget::item:selected {{
                background-color: {highlight_bg};
                color: {selected_text_color}; /* Ensure text is visible */
            }}
            QTreeView {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                /* Add other base styles like border if needed */
            }}
            QTreeView::item:selected {{
                background-color: {highlight_bg};
                color: {selected_text_color}; /* Ensure text is visible */
            }}
            /* Optional: Define hover style if needed */
            /* QTreeView::item:hover {{ ... }} */
        """
    
    def button_stylesheet(self):
        """
        Get the stylesheet for buttons.
        
        Returns:
            str: The stylesheet
        """
        return f"""
            QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
            QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
        """
    
    def switch_tab(self, index):
        """
        Handle tab switching.
        
        Args:
            index: The index of the tab to switch to
        """
        # Stop pw-top monitor if switching away from it
        if index != 2 and hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
            self.pwtop_monitor.stop()
        
        # Configure based on the new tab index
        if index < 2:  # Audio or MIDI tabs
            self.port_type = 'audio' if index == 0 else 'midi'
            self.apply_collapse_state_to_all_trees()
            self.refresh_visualizations()
            self.show_bottom_controls(True)  # Show controls
        elif index == 2:  # pw-top tab
            # Start pw-top monitor only when switching to this tab
            if hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
                self.pwtop_monitor.start()
            self.show_bottom_controls(False)  # Hide controls
        elif index == 3:  # jack_delay tab
            # No specific process to start here, just hide controls
            self.show_bottom_controls(False)  # Hide controls
        
        # Update the refresh interval based on the new tab and current focus state
        self._update_refresh_timer_interval()
        
        # Save the current tab index to config
        self.last_active_tab = index
        self.config_manager.set_int('last_active_tab', index)
    
    def show_bottom_controls(self, visible):
        """
        Show or hide bottom controls based on active tab.
        
        Args:
            visible: Whether to show the controls
        """
        if hasattr(self, 'auto_refresh_checkbox'):
            self.auto_refresh_checkbox.setVisible(visible)
            if hasattr(self, 'untangle_button'):
                self.untangle_button.setVisible(visible)
        if hasattr(self, 'collapse_all_checkbox'):
            self.collapse_all_checkbox.setVisible(visible)
        if hasattr(self, 'bottom_refresh_button'):
            self.bottom_refresh_button.setVisible(visible)
        if hasattr(self, 'undo_button'):
            self.undo_button.setVisible(visible)
        if hasattr(self, 'redo_button'):
            self.redo_button.setVisible(visible)
        if hasattr(self, 'output_filter_edit'):
            self.output_filter_edit.setVisible(visible)
        if hasattr(self, 'input_filter_edit'):
            self.input_filter_edit.setVisible(visible)
        if hasattr(self, 'zoom_in_button'):
            self.zoom_in_button.setVisible(visible)
        if hasattr(self, 'zoom_out_button'):
            self.zoom_out_button.setVisible(visible)
    
    def filter_ports(self, tree_widget, filter_text):
        """
        Filters the items in the specified tree widget based on the filter text.
        
        Args:
            tree_widget: The tree widget to filter
            filter_text: The filter text
        """
        filter_text_lower = filter_text.lower()
        terms = filter_text_lower.split()
        include_terms = [term for term in terms if not term.startswith('-')]
        exclude_terms = [term[1:] for term in terms if term.startswith('-') and len(term) > 1]  # Remove '-'
        
        # Iterate through all top-level items (groups)
        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            group_visible = False  # Assume group is hidden unless a child matches
            
            # Iterate through children (ports) of the group
            for j in range(group_item.childCount()):
                port_item = group_item.child(j)
                port_name = port_item.data(0, Qt.ItemDataRole.UserRole)  # Get full port name
                if not port_name:  # Skip if port name is invalid
                    port_item.setHidden(True)
                    continue
                
                port_name_lower = port_name.lower()
                
                # 1. Check exclusion terms
                excluded = False
                for term in exclude_terms:
                    if term in port_name_lower:
                        excluded = True
                        break
                if excluded:
                    port_item.setHidden(True)
                    continue  # Skip to next port if excluded
                
                # 2. Check inclusion terms (all must match)
                included = True
                if include_terms:  # Only check if there are inclusion terms
                    for term in include_terms:
                        if term not in port_name_lower:
                            included = False
                            break
                
                if included:
                    port_item.setHidden(False)
                    group_visible = True  # Make group visible if this port is visible
                else:
                    port_item.setHidden(True)
            
            # Set the visibility of the group item
            group_item.setHidden(not group_visible)
        
        # After filtering, we need to refresh the connection visualization
        # because hidden items might affect line drawing positions.
        self.refresh_visualizations()
    
    def refresh_visualizations(self):
        """Refresh only the connection visualizations without refreshing ports."""
        if self.port_type == 'audio':
            self.update_connections()
        else:
            self.update_midi_connections()
    
    def _refresh_single_port_type(self, port_type_to_refresh):
        """
        Helper method to refresh ports for a specific type (audio or midi).
        
        Args:
            port_type_to_refresh: The port type to refresh ('audio' or 'midi')
        """
        # 1. Determine context based on port_type_to_refresh
        if port_type_to_refresh == 'audio':
            input_tree = self.input_tree
            output_tree = self.output_tree
            update_visuals = self.update_connections
            clear_highlights = self.clear_highlights
            update_buttons = self.update_connection_buttons
            is_midi = False
        elif port_type_to_refresh == 'midi':
            input_tree = self.midi_input_tree
            output_tree = self.midi_output_tree
            update_visuals = self.update_midi_connections
            clear_highlights = self.clear_midi_highlights
            update_buttons = self.update_midi_connection_buttons
            is_midi = True
        else:
            print(f"Warning: Invalid port_type '{port_type_to_refresh}' passed to _refresh_single_port_type")
            return  # Should not happen
        
        # Use shared filter edits
        current_input_filter = self.input_filter_edit.text() if hasattr(self, 'input_filter_edit') else ""
        current_output_filter = self.output_filter_edit.text() if hasattr(self, 'output_filter_edit') else ""
        
        # 2. Save current selection for this type
        selected_input_info = self._get_selected_item_info(input_tree)
        selected_output_info = self._get_selected_item_info(output_tree)
        # previous_input_group_order and previous_output_group_order are no longer needed here
        # as PortTreeWidget now manages its manual order internally.
        
        # 3. Clear visual tree for this type
        input_tree.clear()
        output_tree.clear()
        
        # 4. Get new port lists for this type
        input_ports, output_ports = self._get_ports(is_midi=is_midi)
        
        # 5. Repopulate trees for this type (without previous_group_order)
        input_tree.populate_tree(input_ports)
        output_tree.populate_tree(output_ports)
        
        # 6. Re-apply filter for this type
        self.filter_ports(input_tree, current_input_filter)
        self.filter_ports(output_tree, current_output_filter)
        
        # 7. Restore selection for this type
        self._restore_selection(input_tree, selected_input_info)
        self._restore_selection(output_tree, selected_output_info)
        
        # 8. Update visuals and button states for this type
        update_visuals()
        clear_highlights()  # Clear old highlights before applying new ones
        update_buttons()
        
        # 9. Re-apply highlights based on the *restored* selection for this type
        restored_input_item = input_tree.currentItem()
        restored_output_item = output_tree.currentItem()
        
        # Highlight selected item itself (port or group)
        if restored_input_item:
            if restored_input_item.childCount() == 0:  # Port
                port_name = restored_input_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:  # Check if port_name is valid
                    self._highlight_tree_item(input_tree, port_name)  # Highlight selected port
        
        if restored_output_item:
            if restored_output_item.childCount() == 0:  # Port
                port_name = restored_output_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:  # Check if port_name is valid
                    self._highlight_tree_item(output_tree, port_name)  # Highlight selected port
        
        # Highlight connected items/groups
        if restored_input_item:
            if restored_input_item.childCount() > 0:  # Group selected
                self._highlight_connected_output_groups_for_input_group(restored_input_item, is_midi)
            else:  # Port selected
                port_name = restored_input_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:  # Ensure port_name is valid
                    self._highlight_connected_outputs_for_input(port_name, is_midi)
        
        if restored_output_item:
            if restored_output_item.childCount() > 0:  # Group selected
                self._highlight_connected_input_groups_for_output_group(restored_output_item, is_midi)
            else:  # Port selected
                port_name = restored_output_item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:  # Ensure port_name is valid
                    self._highlight_connected_inputs_for_output(port_name, is_midi)
        
        # 10. Maintain collapse state if needed for this type
        if self.port_type == port_type_to_refresh:
            if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox.isChecked():
                self.apply_collapse_state_to_current_trees()
    
    def refresh_ports(self, refresh_all=False, from_shortcut=False):
        """
        Refreshes the port lists displayed in the trees.
        
        Args:
            refresh_all: If True, refresh both audio and MIDI ports.
                         If False, refresh only the currently active port type.
            from_shortcut: If True, animate the refresh button press.
        """
        # Animate the refresh button if triggered by shortcut
        if from_shortcut:
            self._animate_button_press(self.bottom_refresh_button)
        
        if refresh_all:
            self._refresh_single_port_type('audio')
            self._refresh_single_port_type('midi')
        else:
            self._refresh_single_port_type(self.port_type)
    
    def _get_selected_item_info(self, tree_widget):
        """
        Gets information about the currently selected item (port or group).
        
        Args:
            tree_widget: The tree widget to get the selected item from
            
        Returns:
            tuple: A tuple containing the item name and whether it's a group
        """
        if not hasattr(tree_widget, 'currentItem'):
            return None, None  # Not a valid tree
        item = tree_widget.currentItem()
        if not item:
            return None, None  # Nothing selected
        
        is_group = item.childCount() > 0
        if is_group:
            return item.text(0), True  # Return group name and True
        else:
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            return port_name, False  # Return port name and False
    
    def _restore_selection(self, tree_widget, selection_info):
        """
        Restores selection based on saved info (group name or port name).
        
        Args:
            tree_widget: The tree widget to restore selection in
            selection_info: The selection info to restore
        """
        if not selection_info or not hasattr(tree_widget, 'port_items'):
            return
        
        name_or_text, is_group = selection_info
        if name_or_text is None:
            return
        
        item_to_select = None
        if is_group:
            # Find group item by text
            for i in range(tree_widget.topLevelItemCount()):
                group_item = tree_widget.topLevelItem(i)
                if group_item.text(0) == name_or_text:
                    item_to_select = group_item
                    break
        else:
            # Find port item by port name (UserRole data)
            item_to_select = tree_widget.port_items.get(name_or_text)
        
        if item_to_select and not item_to_select.isHidden():
            tree_widget.setCurrentItem(item_to_select)
    
    def _get_ports(self, is_midi):
        """
        Get the input and output ports.
        
        Args:
            is_midi: Whether to get MIDI ports
            
        Returns:
            tuple: A tuple containing the input and output ports
        """
        input_ports = []
        output_ports = []
        try:
            # Get input port objects
            input_port_objects = self.client.get_ports(is_input=True, is_midi=is_midi)
            
            # Get output port objects
            output_port_objects = self.client.get_ports(is_output=True, is_midi=is_midi)
            
            # Explicitly filter for the Audio tab (is_midi=False)
            # Ensure only ports reported as non-MIDI by the port object itself are included.
            if not is_midi:
                input_port_objects = [p for p in input_port_objects if p is not None and not p.is_midi]
                output_port_objects = [p for p in output_port_objects if p is not None and not p.is_midi]
            else:
                # For MIDI tab, just ensure ports are not None
                input_port_objects = [p for p in input_port_objects if p is not None]
                output_port_objects = [p for p in output_port_objects if p is not None]
            
            # Extract names from the filtered objects
            input_ports = [p.name for p in input_port_objects]
            output_ports = [p.name for p in output_port_objects]
            
            # Sort the names
            input_ports = self._sort_ports(input_ports)
            output_ports = self._sort_ports(output_ports)
        except jack.JackError as e:
            print(f"Error getting ports: {e}")
            # Return current lists even if incomplete
            pass
        
        return input_ports, output_ports
    
    def _sort_ports(self, port_names):
        """
        Sort port names in a natural order.
        
        Args:
            port_names: The port names to sort
            
        Returns:
            list: The sorted port names
        """
        def get_sort_key(port_name):
            parts = re.split(r'(\d+)', port_name)
            key = []
            for part in parts:
                if part.isdigit():
                    key.append(int(part))
                else:
                    key.append(part.lower())
            return key
        
        return sorted(port_names, key=get_sort_key)
    
    def start_startup_refresh(self):
        """Start the rapid refresh sequence on startup."""
        self.startup_refresh_count = 0
        self.startup_refresh_timer = QTimer()
        self.startup_refresh_timer.timeout.connect(self.startup_refresh)
        self.startup_refresh_timer.start(1)  # 1ms interval
    
    def startup_refresh(self):
        """Handle the rapid refresh sequence."""
        # Remember original port type
        original_port_type = self.port_type
        
        # First refresh audio ports
        self.port_type = 'audio'
        self.refresh_ports()
        
        # Then refresh MIDI ports
        self.port_type = 'midi'
        self.refresh_ports()
        
        # Restore original port type
        self.port_type = original_port_type
        
        # Update current tab's view
        self.refresh_visualizations()
        
        # Increment counter and stop timer if done
        self.startup_refresh_count += 1
        if self.startup_refresh_count >= 3:
            self.startup_refresh_timer.stop()
            
            # Apply collapse state after startup refresh is complete
            if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox.isChecked():
                self.apply_collapse_state_to_all_trees()
    
    def toggle_auto_refresh(self, state):
        """
        Handle auto refresh toggle state change.
        
        Args:
            state: The new state of the checkbox
        """
        is_checked = int(state) == 2  # Qt.CheckState.Checked equals 2
        self.callbacks_enabled = is_checked
        
        # Start/stop and adjust visualization timers based on state and focus
        if is_checked:
            # Ensure timers are started (start_refresh_timer handles multiple calls safely)
            self.connection_view.start_refresh_timer(self.refresh_visualizations, interval=1)
            self.midi_connection_view.start_refresh_timer(self.refresh_visualizations, interval=1)
            # Set the correct interval based on current focus
            self._update_refresh_timer_interval()
        else:
            self.connection_view.stop_refresh_timer()
            self.midi_connection_view.stop_refresh_timer()
        
        # Save state to config
        self.config_manager.set_bool('auto_refresh_enabled', is_checked)
    
    def _update_refresh_timer_interval(self):
        """Adjusts the visualization refresh timer interval based on focus and active tab."""
        if self.callbacks_enabled:
            if not self.is_focused:
                interval = app_config.REFRESH_RATE_UNFOCUSED_MS  # Not focused
            else:
                # Window is focused, check the active tab
                current_index = self.tab_widget.currentIndex()
                if current_index == 0 or current_index == 1:  # Audio or MIDI tab
                    interval = app_config.REFRESH_RATE_FOCUSED_MS
                elif current_index == 2 or current_index == 3:  # pw-top or Latency Test tab
                    interval = app_config.REFRESH_RATE_SPECIAL_TABS_MS
                else:
                    # Fallback for any other potential tabs
                    interval = app_config.REFRESH_RATE_UNFOCUSED_MS
            
            try:
                # Check if timers exist and are active before setting interval
                if hasattr(self.connection_view, 'refresh_timer') and self.connection_view.refresh_timer.isActive():
                    self.connection_view.refresh_timer.setInterval(interval)
                if hasattr(self.midi_connection_view, 'refresh_timer') and self.midi_connection_view.refresh_timer.isActive():
                    self.midi_connection_view.refresh_timer.setInterval(interval)
            except AttributeError as e:
                print(f"Warning: Could not access refresh_timer: {e}")
    
    def changeEvent(self, event):
        """
        Handle window state changes, specifically activation.
        
        Args:
            event: The change event
        """
        super().changeEvent(event)  # Call base implementation first
        if event.type() == event.Type.ActivationChange:
            self.is_focused = self.isActiveWindow()
            self._update_refresh_timer_interval()
    
    def toggle_collapse_all(self, state):
        """
        Handle collapse all toggle state change.
        
        Args:
            state: The new state of the checkbox
        """
        is_checked = int(state) == 2  # Qt.CheckState.Checked equals 2
        
        # Apply to all trees
        self.apply_collapse_state_to_all_trees()
        
        # Save state to config
        self.config_manager.set_bool('collapse_all_enabled', is_checked)
    
    def apply_collapse_state_to_all_trees(self):
        """Apply the current collapse state to all port trees."""
        if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox.isChecked():
            # Collapse all trees regardless of current tab
            if hasattr(self, 'input_tree'):
                self.input_tree.collapseAllGroups()
            if hasattr(self, 'output_tree'):
                self.output_tree.collapseAllGroups()
            if hasattr(self, 'midi_input_tree'):
                self.midi_input_tree.collapseAllGroups()
            if hasattr(self, 'midi_output_tree'):
                self.midi_output_tree.collapseAllGroups()
        else:
            # Expand all trees
            if hasattr(self, 'input_tree'):
                self.input_tree.expandAllGroups()
            if hasattr(self, 'output_tree'):
                self.output_tree.expandAllGroups()
            if hasattr(self, 'midi_input_tree'):
                self.midi_input_tree.expandAllGroups()
            if hasattr(self, 'midi_output_tree'):
                self.midi_output_tree.expandAllGroups()
        
        # Update visualizations
        self.refresh_visualizations()
    
    def apply_collapse_state_to_current_trees(self):
        """Apply the collapse state to the currently visible trees only."""
        if self.port_type == 'audio':
            if hasattr(self, 'input_tree') and self.collapse_all_checkbox.isChecked():
                self.input_tree.collapseAllGroups()
            elif hasattr(self, 'input_tree'):
                self.input_tree.expandAllGroups()
            
            if hasattr(self, 'output_tree') and self.collapse_all_checkbox.isChecked():
                self.output_tree.collapseAllGroups()
            elif hasattr(self, 'output_tree'):
                self.output_tree.expandAllGroups()
        elif self.port_type == 'midi':
            if hasattr(self, 'midi_input_tree') and self.collapse_all_checkbox.isChecked():
                self.midi_input_tree.collapseAllGroups()
            elif hasattr(self, 'midi_input_tree'):
                self.midi_input_tree.expandAllGroups()
            
            if hasattr(self, 'midi_output_tree') and self.collapse_all_checkbox.isChecked():
                self.midi_output_tree.collapseAllGroups()
            elif hasattr(self, 'midi_output_tree'):
                self.midi_output_tree.expandAllGroups()
    
    def _update_untangle_button_text(self):
        """Updates the text of the untangle button based on the current mode."""
        modes = {
            0: "Untangle: Off",
            1: "Untangle: >>",
            2: "Untangle: <<"
        }
        if self.untangle_button:  # Check if button exists before setting text
            self.untangle_button.setText(modes.get(self.untangle_mode, "Untangle: Unknown"))
    
    def toggle_untangle_sort(self):
        """Cycles the untangle sort mode and refreshes the port lists."""
        self.untangle_mode = (self.untangle_mode + 1) % 3  # Cycle 0 -> 1 -> 2 -> 0
        self.config_manager.set_int('untangle_mode', self.untangle_mode)
        self._update_untangle_button_text()
        print(f"Untangle sort mode set to: {self.untangle_mode}")
        self.untangle_mode_changed.emit(self.untangle_mode)  # Emit signal
        self.refresh_ports(refresh_all=True)  # Refresh both lists
    
    def _handle_untangle_shortcut(self):
        """Handles the Alt+U shortcut for cycling untangle sort."""
        # Animate the untangle button press
        self._animate_button_press(self.untangle_button)
        self.toggle_untangle_sort()  # Directly call the cycle method
    
    def _animate_button_press(self, button):
        """
        Animates a button press by briefly changing its style and then restoring it.
        
        Args:
            button: The button to animate
        """
        if not button:
            return
        
        # Store original style
        original_style = button.styleSheet()
        
        # Skip if already in pressed state
        if "inset" in original_style:
            return
        
        # Apply pressed style
        pressed_style = f"""
            QPushButton {{
                background-color: {self.highlight_color.name()};
                color: {self.text_color.name()};
                border: 2px inset {self.highlight_color.darker(120).name()};
            }}
        """
        button.setStyleSheet(pressed_style)
        
        # Restore original style after a short delay
        QTimer.singleShot(150, lambda: button.setStyleSheet(original_style))
    
    def _handle_filter_change(self):
        """Handles text changes in the shared filter boxes."""
        current_index = self.tab_widget.currentIndex()
        input_text = self.input_filter_edit.text()
        output_text = self.output_filter_edit.text()
        
        if current_index == 0:  # Audio tab
            if hasattr(self, 'input_tree'):
                self.filter_ports(self.input_tree, input_text)
            if hasattr(self, 'output_tree'):
                self.filter_ports(self.output_tree, output_text)
        elif current_index == 1:  # MIDI tab
            if hasattr(self, 'midi_input_tree'):
                self.filter_ports(self.midi_input_tree, input_text)
            if hasattr(self, 'midi_output_tree'):
                self.filter_ports(self.midi_output_tree, output_text)
    
    def _handle_port_registration(self, port, register: bool):
        """
        JACK callback for port registration events. This runs in JACK's thread.
        
        Args:
            port: The port that was registered or unregistered
            register: True if the port was registered, False if it was unregistered
        """
        try:
            # If port is None or not fully initialized, skip processing
            if port is None:
                return
            
            # Check if the port object has the required attributes before accessing them
            port_name = None
            is_input = False
            
            # Use hasattr checks first to avoid triggering AttributeErrors
            if hasattr(port, 'name'):
                try:
                    port_name = port.name
                    # Only proceed if we got a valid port name
                    if not isinstance(port_name, str) or not port_name:
                        return
                except Exception:
                    return
            
            if hasattr(port, 'is_input'):
                try:
                    is_input = port.is_input
                except Exception:
                    # Default to False if we can't determine input status
                    is_input = False
            
            # Only emit signals if we successfully obtained port information
            if port_name:
                if register:
                    self.port_registered.emit(port_name, is_input)
                else:
                    self.port_unregistered.emit(port_name, is_input)
        except Exception as e:
            # Log any errors since this runs in a callback
            print(f"Port registration callback error: {type(e).__name__}: {e}")
    
    def _on_port_registered(self, port_name: str, is_input: bool):
        """
        Handle port registration events in the Qt main thread.
        
        Args:
            port_name: The name of the port that was registered
            is_input: Whether the port is an input port
        """
        if not self.callbacks_enabled:
            return
        
        # Check if this is a jack_delay port registration, and if so, attempt auto-connection via LatencyTester
        if (hasattr(self, 'latency_tester') and self.latency_tester is not None and
            (port_name == "jack_delay:in" or port_name == "jack_delay:out")):
            print(f"Detected registration of {port_name}, attempting latency auto-connection via LatencyTester...")
            # Use QTimer.singleShot to slightly delay the connection attempt,
            # ensuring both jack_delay ports might be ready.
            QTimer.singleShot(50, self.latency_tester._attempt_latency_auto_connection)  # 50ms delay
        
        self.refresh_ports(refresh_all=True)
    
    def _on_port_unregistered(self, port_name: str, is_input: bool):
        """
        Handle port unregistration events in the Qt main thread.
        
        Args:
            port_name: The name of the port that was unregistered
            is_input: Whether the port is an input port
        """
        if not self.callbacks_enabled:
            return
        
        self.refresh_ports(refresh_all=True)
    
    def _highlight_connected_outputs_for_input(self, input_name, is_midi):
        """
        Highlight output ports connected to the given input port.
        
        Args:
            input_name: The name of the input port
            is_midi: Whether the port is a MIDI port
        """
        try:
            # Get only relevant output ports
            output_ports = self.client.get_ports(is_output=True, is_midi=is_midi)
            for output_port in output_ports:
                try:
                    connections = self.client.get_all_connections(output_port)
                    if input_name in [conn.name for conn in connections]:
                        if is_midi:
                            self.highlight_midi_output(output_port.name, auto_highlight=True)
                        else:
                            self.highlight_output(output_port.name, auto_highlight=True)
                except jack.JackError:
                    continue
        except jack.JackError as e:
            print(f"Error highlighting connected outputs: {e}")
    
    def _highlight_connected_inputs_for_output(self, output_name, is_midi):
        """
        Highlight input ports connected to the given output port.
        
        Args:
            output_name: The name of the output port
            is_midi: Whether the port is a MIDI port
        """
        try:
            # Get only relevant input ports
            input_ports = self.client.get_ports(is_input=True, is_midi=is_midi)
            for input_port in input_ports:
                try:
                    connections = self.client.get_all_connections(input_port)
                    if output_name in [c.name for c in connections]:
                        if is_midi:
                            self.highlight_midi_input(input_port.name, auto_highlight=True)
                        else:
                            self.highlight_input(input_port.name, auto_highlight=True)
                except jack.JackError:
                    continue
        except jack.JackError as e:
            print(f"Error highlighting connected inputs: {e}")
    
    def _highlight_connected_output_groups_for_input_group(self, input_group_item, is_midi):
        """
        Finds and highlights output groups connected to the selected input group.
        
        Args:
            input_group_item: The input group item
            is_midi: Whether the port is a MIDI port
        """
        input_ports = self._get_ports_in_group(input_group_item)
        if not input_ports:
            return
        
        output_tree = self.midi_output_tree if is_midi else self.output_tree
        highlight_func = self._highlight_group_item  # Use the new group highlight function
        
        try:
            # Iterate through all output ports to find connections to any port in the input group
            output_port_objects = self.client.get_ports(is_output=True, is_midi=is_midi)
            connected_output_groups = set()  # Store names of groups to highlight
            
            for output_port in output_port_objects:
                try:
                    # Check if output port exists before querying
                    if not any(p.name == output_port.name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    connections = self.client.get_all_connections(output_port)
                    # Check if this output port connects to *any* port in the selected input group
                    if any(conn.name in input_ports for conn in connections):
                        # Find the group this output port belongs to
                        output_item = output_tree.port_items.get(output_port.name)
                        if output_item and output_item.parent():
                            connected_output_groups.add(output_item.parent().text(0))
                except jack.JackError:
                    continue  # Ignore errors for individual ports
            
            # Highlight the identified groups
            for group_name in connected_output_groups:
                highlight_func(output_tree, group_name)
        
        except jack.JackError as e:
            print(f"Error highlighting connected output groups: {e}")
    
    def _highlight_connected_input_groups_for_output_group(self, output_group_item, is_midi):
        """
        Finds and highlights input groups connected to the selected output group.
        
        Args:
            output_group_item: The output group item
            is_midi: Whether the port is a MIDI port
        """
        output_ports = self._get_ports_in_group(output_group_item)
        if not output_ports:
            return
        
        input_tree = self.midi_input_tree if is_midi else self.input_tree
        highlight_func = self._highlight_group_item  # Use the new group highlight function
        
        try:
            connected_input_groups = set()  # Store names of groups to highlight
            
            # Iterate through all ports in the selected output group
            for output_name in output_ports:
                try:
                    # Check if output port exists before querying
                    if not any(p.name == output_name for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    # Get all connections *from* this specific output port
                    connections = self.client.get_all_connections(output_name)
                    for input_port in connections:
                        # Find the group this connected input port belongs to
                        input_item = input_tree.port_items.get(input_port.name)
                        if input_item and input_item.parent():
                            connected_input_groups.add(input_item.parent().text(0))
                except jack.JackError:
                    continue  # Ignore errors for individual ports
            
            # Highlight the identified groups
            for group_name in connected_input_groups:
                highlight_func(input_tree, group_name)
        
        except jack.JackError as e:
            print(f"Error highlighting connected input groups: {e}")
    
    def _get_ports_in_group(self, item):
        """
        Get all ports in a group or just the single port if it's a port item.
        
        Args:
            item: The tree item
            
        Returns:
            list: The ports in the group
        """
        if not item:
            return []
        if item.childCount() == 0:  # It's a port item
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            return [port_name] if port_name else []
        else:  # It's a group item
            ports = []
            for i in range(item.childCount()):
                child = item.child(i)
                port_name = child.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    ports.append(port_name)
            return ports
    
    def highlight_input(self, input_name, auto_highlight=False):
        """
        Highlight an input port.
        
        Args:
            input_name: The name of the input port
            auto_highlight: Whether to use the auto highlight color
        """
        self._highlight_tree_item(self.input_tree, input_name, auto_highlight)
    
    def highlight_output(self, output_name, auto_highlight=False):
        """
        Highlight an output port.
        
        Args:
            output_name: The name of the output port
            auto_highlight: Whether to use the auto highlight color
        """
        self._highlight_tree_item(self.output_tree, output_name, auto_highlight)
    
    def highlight_midi_input(self, input_name, auto_highlight=False):
        """
        Highlight a MIDI input port.
        
        Args:
            input_name: The name of the MIDI input port
            auto_highlight: Whether to use the auto highlight color
        """
        self._highlight_tree_item(self.midi_input_tree, input_name, auto_highlight)
    
    def highlight_midi_output(self, output_name, auto_highlight=False):
        """
        Highlight a MIDI output port.
        
        Args:
            output_name: The name of the MIDI output port
            auto_highlight: Whether to use the auto highlight color
        """
        self._highlight_tree_item(self.midi_output_tree, output_name, auto_highlight)
    
    def _highlight_tree_item(self, tree_widget, port_name, auto_highlight=False):
        """
        Highlight a specific port item in a tree widget.
        
        Args:
            tree_widget: The tree widget
            port_name: The name of the port
            auto_highlight: Whether to use the auto highlight color
        """
        port_item = tree_widget.port_items.get(port_name)
        if port_item:
            port_item.setForeground(0, QBrush(
                self.highlight_color if not auto_highlight else self.auto_highlight_color))
    
    def _highlight_group_item(self, tree_widget, group_name):
        """
        Highlight a specific group item in a tree widget.
        
        Args:
            tree_widget: The tree widget
            group_name: The name of the group
        """
        group_item = tree_widget.port_groups.get(group_name)
        if group_item:
            # Use the auto_highlight_color for connected groups
            group_item.setForeground(0, QBrush(self.auto_highlight_color))
    
    def clear_highlights(self):
        """Clear highlights from audio port trees."""
        self._clear_tree_highlights(self.input_tree)
        self._clear_tree_highlights(self.output_tree)
    
    def clear_midi_highlights(self):
        """Clear highlights from MIDI port trees."""
        self._clear_tree_highlights(self.midi_input_tree)
        self._clear_tree_highlights(self.midi_output_tree)
    
    def _clear_tree_highlights(self, tree_widget):
        """
        Clear highlights from all group and port items in a tree widget.
        
        Args:
            tree_widget: The tree widget
        """
        if not hasattr(tree_widget, 'topLevelItemCount'):
            return  # Safety check
        
        for i in range(tree_widget.topLevelItemCount()):
            group_item = tree_widget.topLevelItem(i)
            # Reset group item highlight
            group_item.setForeground(0, QBrush(self.text_color))
            # Reset child item highlights
            for j in range(group_item.childCount()):
                child_item = group_item.child(j)
                child_item.setForeground(0, QBrush(self.text_color))
    
    def highlight_drop_target_item(self, tree_widget, item):
        """
        Highlight an item when being dragged over.
        
        Args:
            tree_widget: The tree widget
            item: The item to highlight
        """
        item.setBackground(0, QBrush(self.drag_highlight_color))
    
    def clear_drop_target_highlight(self, tree_widget):
        """
        Clear drop target highlighting.
        
        Args:
            tree_widget: The tree widget
        """
        if isinstance(tree_widget, QTreeWidget):
            for i in range(tree_widget.topLevelItemCount()):
                group_item = tree_widget.topLevelItem(i)
                group_item.setBackground(0, QBrush(self.background_color))
                for j in range(group_item.childCount()):
                    child_item = group_item.child(j)
                    child_item.setBackground(0, QBrush(self.background_color))
    
    def on_input_clicked(self, item, column):
        """
        Handle input port click.
        
        Args:
            item: The clicked item
            column: The clicked column
        """
        self._on_port_clicked(item, self.input_tree, self.output_tree, False)
    
    def on_midi_input_clicked(self, item, column):
        """
        Handle MIDI input port click.
        
        Args:
            item: The clicked item
            column: The clicked column
        """
        self._on_port_clicked(item, self.midi_input_tree, self.midi_output_tree, True)
    
    def on_output_clicked(self, item, column):
        """
        Handle output port click.
        
        Args:
            item: The clicked item
            column: The clicked column
        """
        self._on_port_clicked(item, self.output_tree, self.input_tree, False)
    
    def on_midi_output_clicked(self, item, column):
        """
        Handle MIDI output port click.
        
        Args:
            item: The clicked item
            column: The clicked column
        """
        self._on_port_clicked(item, self.midi_output_tree, self.midi_input_tree, True)
    
    def _on_port_clicked(self, item, clicked_tree, other_tree, is_midi):
        """
        Handle selection in tree widgets for ports and groups, respecting Ctrl modifier.
        
        Args:
            item: The clicked item
            clicked_tree: The tree that was clicked
            other_tree: The other tree
            is_midi: Whether the port is a MIDI port
        """
        # Check if Ctrl key is pressed during the click that triggered this handler
        ctrl_pressed = QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        
        if not ctrl_pressed:
            # --- Standard Click Behavior (No Ctrl) ---
            # 1. Clear previous highlights
            if is_midi:
                self.clear_midi_highlights()
            else:
                self.clear_highlights()
            
            # Highlight the clicked item itself
            port_name_or_group = item.data(0, Qt.ItemDataRole.UserRole) or item.text(0)
            if is_midi:
                if clicked_tree == self.midi_input_tree:
                    self.highlight_midi_input(port_name_or_group)
                else:
                    self.highlight_midi_output(port_name_or_group)
            else:
                if clicked_tree == self.input_tree:
                    self.highlight_input(port_name_or_group)
                else:
                    self.highlight_output(port_name_or_group)
        
        # --- Behavior for Both Ctrl+Click and Standard Click ---
        # 3. Handle highlighting of connected items based on the *currently clicked* item
        is_group_item = item.childCount() > 0
        
        if is_group_item:
            # Group item clicked - highlight connected groups and update buttons
            if is_midi:
                if clicked_tree == self.midi_input_tree:
                    self._highlight_connected_output_groups_for_input_group(item, is_midi)
                else:  # Clicked on midi_output_tree
                    self._highlight_connected_input_groups_for_output_group(item, is_midi)
                self.update_midi_connection_buttons()
            else:  # Audio
                if clicked_tree == self.input_tree:
                    self._highlight_connected_output_groups_for_input_group(item, is_midi)
                else:  # Clicked on output_tree
                    self._highlight_connected_input_groups_for_output_group(item, is_midi)
                self.update_connection_buttons()
        else:
            # Port item clicked - perform highlighting and update buttons
            port_name = item.data(0, Qt.ItemDataRole.UserRole)
            if not port_name:
                return  # Should not happen, but safety check
            
            if is_midi:
                if clicked_tree == self.midi_input_tree:
                    self.highlight_midi_input(port_name)
                    self._highlight_connected_outputs_for_input(port_name, is_midi)
                    self.update_midi_connection_buttons()
                else:  # Clicked on midi_output_tree
                    self.highlight_midi_output(port_name)
                    self._highlight_connected_inputs_for_output(port_name, is_midi)
                    self.update_midi_connection_buttons()
            else:  # Audio
                if clicked_tree == self.input_tree:
                    self.highlight_input(port_name)
                    self._highlight_connected_outputs_for_input(port_name, is_midi)
                    self.update_connection_buttons()
                else:  # Clicked on output_tree
                    self.highlight_output(port_name)
                    self._highlight_connected_inputs_for_output(port_name, is_midi)
                    self.update_connection_buttons()
    
    def make_connection(self, output_name, input_name):
        """
        Make a connection between an output port and an input port.
        
        Args:
            output_name: The name of the output port
            input_name: The name of the input port
        """
        self._port_operation('connect', output_name, input_name, is_midi=False)
    
    def make_midi_connection(self, output_name, input_name):
        """
        Make a MIDI connection between an output port and an input port.
        
        Args:
            output_name: The name of the output port
            input_name: The name of the input port
        """
        self._port_operation('connect', output_name, input_name, is_midi=True)
    
    def break_connection(self, output_name, input_name):
        """
        Break a connection between an output port and an input port.
        
        Args:
            output_name: The name of the output port
            input_name: The name of the input port
        """
        self._port_operation('disconnect', output_name, input_name, is_midi=False)
    
    def break_midi_connection(self, output_name, input_name):
        """
        Break a MIDI connection between an output port and an input port.
        
        Args:
            output_name: The name of the output port
            input_name: The name of the input port
        """
        self._port_operation('disconnect', output_name, input_name, is_midi=True)
    
    def _port_operation(self, operation_type, output_name, input_name, is_midi):
        """
        Perform a port operation (connect or disconnect).
        
        Args:
            operation_type: The operation type ('connect' or 'disconnect')
            output_name: The name of the output port
            input_name: The name of the input port
            is_midi: Whether the ports are MIDI ports
        """
        try:
            if operation_type == 'connect':
                # Check if connection already exists before attempting to connect
                try:
                    connections = self.client.get_all_connections(output_name)
                    if any(conn.name == input_name for conn in connections):
                        print(f"Connection {output_name} -> {input_name} already exists, skipping")
                        return
                except jack.JackError:
                    # If we can't check connections, try the connect anyway
                    pass
                
                self.client.connect(output_name, input_name)
                self.connection_history.add_action('connect', output_name, input_name)
            else:
                self.client.disconnect(output_name, input_name)
                self.connection_history.add_action('disconnect', output_name, input_name)
            
            self.update_undo_redo_buttons()
            self.update_connections()
            self.refresh_ports()
            self.update_connection_buttons()
            self.update_midi_connection_buttons()
        
        except jack.JackError as e:
            print(f"{operation_type.capitalize()} error: {e}")
            # Don't crash on connection errors, just log them
    
    def make_connection_selected(self):
        """Connects selected items."""
        selected_input_items = self.input_tree.selectedItems()
        selected_output_items = self.output_tree.selectedItems()
        
        # Get all ports from selected items (handles both ports and groups)
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)
        
        if not selected_inputs or not selected_outputs:
            print("Make Connection: Select at least one input and one output item (port or group).")
            return
        
        print(f"Making connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        # Use make_multiple_connections which handles the cross-product internally
        self.make_multiple_connections(selected_outputs, selected_inputs)
    
    def make_midi_connection_selected(self):
        """Connects selected MIDI items."""
        selected_input_items = self.midi_input_tree.selectedItems()
        selected_output_items = self.midi_output_tree.selectedItems()
        
        # Get all ports from selected items (handles both ports and groups)
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)
        
        if not selected_inputs or not selected_outputs:
            print("Make MIDI Connection: Select at least one input and one output item (port or group).")
            return
        
        print(f"Making MIDI connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        # Use make_multiple_connections which handles the cross-product internally
        self.make_multiple_connections(selected_outputs, selected_inputs)
    
    def break_connection_selected(self):
        """Disconnects all selected output ports from all selected input ports."""
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)
        
        if not selected_inputs or not selected_outputs:
            print("Break Connection: Select at least one input and one output port.")
            return
        
        print(f"Breaking connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                # We only need to attempt disconnection, Jack handles non-existent ones gracefully
                self.break_connection(out_port, in_port)  # Use existing single disconnection method
    
    def break_midi_connection_selected(self):
        """Disconnects all selected MIDI output ports from all selected MIDI input ports."""
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)
        
        if not selected_inputs or not selected_outputs:
            print("Break MIDI Connection: Select at least one input and one output MIDI port.")
            return
        
        print(f"Breaking MIDI connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                # We only need to attempt disconnection, Jack handles non-existent ones gracefully
                self.break_midi_connection(out_port, in_port)  # Use existing single MIDI disconnection method
    
    def _get_ports_from_selected_items(self, tree_widget):
        """
        Returns a list of unique port names from selected items (ports and groups) in a tree.
        If a group is selected, all its child ports are included.
        
        Args:
            tree_widget: The tree widget to get selected items from
            
        Returns:
            list: The port names from selected items
        """
        port_names = set()  # Use a set to automatically handle duplicates
        for item in tree_widget.selectedItems():
            if not item:
                continue
            
            if item.childCount() == 0:  # Is a port item (leaf)
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    port_names.add(port_name)
            else:  # Is a group item
                for i in range(item.childCount()):
                    child = item.child(i)
                    port_name = child.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        port_names.add(port_name)
        return list(port_names)  # Return as a list
    
    def make_multiple_connections(self, outputs, inputs):
        """
        Connects multiple output ports to multiple input ports.
        
        Args:
            outputs: The output ports
            inputs: The input ports
        """
        if not outputs or not inputs:
            print("Warning: make_multiple_connections called with empty outputs or inputs.")
            return
        
        # Ensure inputs are lists for consistent handling
        output_list = outputs if isinstance(outputs, list) else [outputs]
        input_list = inputs if isinstance(inputs, list) else [inputs]
        
        if not output_list or not input_list:
            print(f"Warning: make_multiple_connections called with empty lists after ensuring list type: outputs={output_list}, inputs={input_list}")
            return
        
        # Determine if MIDI or Audio based on the current tab
        is_midi = self.tab_widget.currentIndex() == 1  # Assuming MIDI is tab index 1
        # Use _port_operation directly as it handles history and updates
        operation_type = 'connect'
        
        num_outputs = len(output_list)
        num_inputs = len(input_list)
        made_connection_attempt = False
        
        print(f"make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs. MIDI: {is_midi}")
        
        if num_outputs > 1 and num_inputs == 1:
            # Group/List to Port: Connect all outputs to the single input
            single_input = input_list[0]
            print(f"  Scenario: Group/List ({num_outputs}) -> Port ({single_input})")
            for output_name in output_list:
                try:
                    self._port_operation(operation_type, output_name, single_input, is_midi)
                    made_connection_attempt = True
                except jack.JackError as e:
                    print(f"  Failed to connect {output_name} -> {single_input}: {e}")
        
        elif num_outputs == 1 and num_inputs > 1:
            # Port to Group/List: Connect the single output to all inputs
            single_output = output_list[0]
            print(f"  Scenario: Port ({single_output}) -> Group/List ({num_inputs})")
            for input_name in input_list:
                try:
                    self._port_operation(operation_type, single_output, input_name, is_midi)
                    made_connection_attempt = True
                except jack.JackError as e:
                    print(f"  Failed to connect {single_output} -> {input_name}: {e}")
        
        elif num_outputs > 1 and num_inputs > 1:
            # Group/List to Group/List: Use suffix matching then sequential matching
            print(f"  Scenario: Group/List ({num_outputs}) -> Group/List ({num_inputs}) - Applying suffix/sequential matching")
            
            # Define common suffixes for matching
            common_suffixes = [
                '_FL', '_FR', '_SL', '_SR', '_FC', '_LFE', '_RL', '_RR',
                '_L', '_R', '_1', '_2', '_3', '_4', '_5', '_6', '_7', '_8',
                'left', 'right', 'Left', 'Right'
            ]
            
            # Create copies to modify while iterating
            unmatched_outputs = list(output_list)
            unmatched_inputs = list(input_list)
            connections_made_in_group = []  # Track connections made in this block
            
            # First pass: match by exact suffixes
            for suffix in common_suffixes:
                outputs_with_suffix = [p for p in unmatched_outputs if p.endswith(suffix)]
                inputs_with_suffix = [p for p in unmatched_inputs if p.endswith(suffix)]
                
                # Pair up matching ports based on suffix
                pairs_to_connect = min(len(outputs_with_suffix), len(inputs_with_suffix))
                for i in range(pairs_to_connect):
                    out_p = outputs_with_suffix[i]
                    in_p = inputs_with_suffix[i]
                    try:
                        print(f"    Suffix Match ({suffix}): {out_p} -> {in_p}")
                        # Use _port_operation directly to handle history correctly for each pair
                        self._port_operation(operation_type, out_p, in_p, is_midi)
                        connections_made_in_group.append((out_p, in_p))
                        unmatched_outputs.remove(out_p)
                        unmatched_inputs.remove(in_p)
                        made_connection_attempt = True  # Set the outer flag
                    except Exception as e:
                        print(f"      Connection failed: {e}")
            
            # Second pass: try to match remaining ports sequentially
            while unmatched_outputs and unmatched_inputs:
                out_p = unmatched_outputs[0]
                in_p = unmatched_inputs[0]
                try:
                    print(f"    Sequential Match: {out_p} -> {in_p}")
                    # Use _port_operation directly
                    self._port_operation(operation_type, out_p, in_p, is_midi)
                    connections_made_in_group.append((out_p, in_p))
                    made_connection_attempt = True  # Set the outer flag
                except Exception as e:
                    print(f"      Connection failed: {e}")
                # Remove the matched ports regardless of success to avoid infinite loops on error
                unmatched_outputs.pop(0)
                unmatched_inputs.pop(0)
            
            print(f"  Group-to-group connection finished. Attempted {len(connections_made_in_group)} connections.")
        
        elif num_outputs == 1 and num_inputs == 1:
            # Single Port to Single Port
            single_output = output_list[0]
            single_input = input_list[0]
            print(f"  Scenario: Port ({single_output}) -> Port ({single_input})")
            try:
                self._port_operation(operation_type, single_output, single_input, is_midi)
                made_connection_attempt = True
            except jack.JackError as e:
                print(f"  Failed to connect {single_output} -> {single_input}: {e}")
        else:
            # Should not happen if lists are not empty at the start
            print(f"Warning: Unexpected case in make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs")
        
        if made_connection_attempt:
            print("Multiple connection process finished.")
    
    def update_connection_buttons(self):
        """Update the state of the audio connection buttons."""
        self._update_port_connection_buttons(self.input_tree, self.output_tree,
                                           self.connect_button, self.disconnect_button)
    
    def update_midi_connection_buttons(self):
        """Update the state of the MIDI connection buttons."""
        self._update_port_connection_buttons(self.midi_input_tree, self.midi_output_tree,
                                           self.midi_connect_button, self.midi_disconnect_button)
    
    def _update_port_connection_buttons(self, input_tree, output_tree, connect_button, disconnect_button):
        """
        Update connection button states based on selected ports.
        
        Args:
            input_tree: The input tree widget
            output_tree: The output tree widget
            connect_button: The connect button
            disconnect_button: The disconnect button
        """
        # Get lists of selected port names (only leaf items)
        selected_input_ports = self._get_ports_from_selected_items(input_tree)
        selected_output_ports = self._get_ports_from_selected_items(output_tree)
        
        ports_selected = bool(selected_input_ports and selected_output_ports)
        
        can_connect = False
        can_disconnect = False
        
        if ports_selected:
            # 1. Determine all possible connections (cross-product)
            possible_connections = set()
            for out_p in selected_output_ports:
                for in_p in selected_input_ports:
                    possible_connections.add((out_p, in_p))
            
            # 2. Determine existing connections between the selected ports
            existing_connections = self._get_existing_connections_between(selected_output_ports, selected_input_ports)
            
            # 3. Enable Connect if there are possible connections that don't already exist.
            if len(possible_connections) > 0 and possible_connections != existing_connections:
                can_connect = True
            
            # 4. Enable Disconnect if there are any existing connections
            if len(existing_connections) > 0:
                can_disconnect = True
        
        connect_button.setEnabled(can_connect)
        disconnect_button.setEnabled(can_disconnect)
    
    def _get_existing_connections_between(self, output_ports, input_ports):
        """
        Returns a set of existing (output, input) connection tuples between the given port lists.
        
        Args:
            output_ports: The output ports
            input_ports: The input ports
            
        Returns:
            set: The existing connections
        """
        existing_connections = set()
        if not output_ports or not input_ports:
            return existing_connections
        try:
            # Convert input_ports to a set for faster lookups
            input_ports_set = set(input_ports)
            for out_port in output_ports:
                # Check connections for this output port
                try:
                    # Determine if MIDI based on current tab context
                    is_midi = self.tab_widget.currentIndex() == 1
                    # Ensure port exists before querying
                    if not any(p.name == out_port for p in self.client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    
                    connections = self.client.get_all_connections(out_port)
                    for conn in connections:
                        # If the connected input port is in our target input set, add the tuple
                        if conn.name in input_ports_set:
                            existing_connections.add((out_port, conn.name))
                except jack.JackError:
                    continue  # Ignore error for this specific output port
            return existing_connections
        except jack.JackError as e:
            # Broader error during the process
            print(f"Error getting existing connections: {e}")
            return existing_connections  # Return what we have found so far or empty set
    
    def update_undo_redo_buttons(self):
        """Update the state of the undo and redo buttons."""
        self.undo_button.setEnabled(self.connection_history.can_undo())
        self.redo_button.setEnabled(self.connection_history.can_redo())
    
    def undo_action(self):
        """Undo the last connection action."""
        # Animate the undo button press
        self._animate_button_press(self.undo_button)
        
        action = self.connection_history.undo()
        if action:
            action_type, output_name, input_name = action
            is_midi = 'midi' in output_name or 'midi' in input_name  # heuristic to determine midi or audio
            try:
                if action_type == 'connect':
                    self.client.connect(output_name, input_name)
                else:
                    self.client.disconnect(output_name, input_name)
                self.update_undo_redo_buttons()
                self.update_connections()
                self.refresh_ports()
                self.update_connection_buttons()
                self.update_midi_connection_buttons()
            
            except jack.JackError as e:
                print(f"Undo error: {e}")
    
    def redo_action(self):
        """Redo the last undone connection action."""
        # Animate the redo button press
        self._animate_button_press(self.redo_button)
        
        action = self.connection_history.redo()
        if action:
            action_type, output_name, input_name = action
            is_midi = 'midi' in output_name or 'midi' in input_name  # heuristic to determine midi or audio
            try:
                if action_type == 'connect':
                    self.client.connect(output_name, input_name)
                else:
                    self.client.disconnect(output_name, input_name)
                self.update_undo_redo_buttons()
                self.update_connections()
                self.refresh_ports()
                self.update_connection_buttons()
                self.update_midi_connection_buttons()
            except jack.JackError as e:
                print(f"Redo error: {e}")
    
    def disconnect_node(self, node_name):
        """
        Disconnect all connections from/to a specific port.
        
        Args:
            node_name: The name of the port to disconnect
        """
        is_midi = 'midi' in node_name  # heuristic to determine midi or audio
        
        if node_name in [port.name for port in self.client.get_ports(is_input=True)]:
            # Node is an input port, disconnect all outputs connected to it
            for output_port in self.client.get_ports(is_output=True):
                if node_name in [conn.name for conn in self.client.get_all_connections(output_port)]:
                    if not is_midi:
                        self.break_connection(output_port.name, node_name)
                    else:
                        self.break_midi_connection(output_port.name, node_name)
        elif node_name in [port.name for port in self.client.get_ports(is_output=True)]:
            # Node is an output port, disconnect all inputs it's connected to
            for input_port in self.client.get_all_connections(node_name):
                if not is_midi:
                    self.break_connection(node_name, input_port.name)
                else:
                    self.break_midi_connection(node_name, input_port.name)
    
    def _setup_actions(self):
        """Define all QAction objects for shortcuts and context menus."""
        # Connect Shortcut (c)
        self.connect_action = QAction("Connect Shortcut", self)
        self.connect_action.setShortcut(QKeySequence(Qt.Key.Key_C))
        self.connect_action.triggered.connect(self._handle_connect_shortcut)
        
        # Disconnect Shortcut (d/Delete)
        self.disconnect_action = QAction("Disconnect Shortcut", self)
        self.disconnect_action.setShortcuts([QKeySequence(Qt.Key.Key_D), QKeySequence(Qt.Key.Key_Delete)])
        self.disconnect_action.triggered.connect(self._handle_disconnect_shortcut)
        
        # Undo Shortcut (Ctrl+Z)
        self.undo_shortcut_action = QAction("Undo Shortcut", self)
        self.undo_shortcut_action.setShortcut(QKeySequence.StandardKey.Undo)  # Standard Ctrl+Z
        self.undo_shortcut_action.triggered.connect(self.undo_action)
        
        # Redo Shortcut (Ctrl+Y / Ctrl+Shift+Z)
        self.redo_shortcut_action = QAction("Redo Shortcut", self)
        self.redo_shortcut_action.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Y")])
        self.redo_shortcut_action.triggered.connect(self.redo_action)
        
        # Refresh Shortcut (r)
        self.refresh_shortcut_action = QAction("Refresh Shortcut", self)
        self.refresh_shortcut_action.setShortcut(QKeySequence(Qt.Key.Key_R))
        self.refresh_shortcut_action.triggered.connect(lambda: self.refresh_ports(from_shortcut=True))
        
        # Collapse All Shortcut (Alt+C)
        self.collapse_all_shortcut_action = QAction("Collapse All Shortcut", self)
        self.collapse_all_shortcut_action.setShortcut(QKeySequence("Alt+C"))
        self.collapse_all_shortcut_action.triggered.connect(self._handle_collapse_all_shortcut)
        
        # Auto Refresh Shortcut (Alt+R)
        self.auto_refresh_shortcut_action = QAction("Auto Refresh Shortcut", self)
        self.auto_refresh_shortcut_action.setShortcut(QKeySequence("Alt+R"))
        self.auto_refresh_shortcut_action.triggered.connect(self._handle_auto_refresh_shortcut)
        
        # Untangle Shortcut (Alt+U)
        self.untangle_shortcut_action = QAction("Untangle Shortcut", self)
        self.untangle_shortcut_action.setShortcut(QKeySequence("Alt+U"))
        self.untangle_shortcut_action.triggered.connect(self._handle_untangle_shortcut)
        
        # Font Size Increase Shortcut (Ctrl++/Ctrl+=)
        self.increase_font_action = QAction("Increase Font Size", self)
        self.increase_font_action.setShortcuts([
            QKeySequence.StandardKey.ZoomIn,  # Standard Ctrl++
            QKeySequence("Ctrl++"),
            QKeySequence("Ctrl+=")
        ])
        self.increase_font_action.triggered.connect(self.increase_font_size)
        
        # Font Size Decrease Shortcut (Ctrl+-)
        self.decrease_font_action = QAction("Decrease Font Size", self)
        self.decrease_font_action.setShortcut(QKeySequence.StandardKey.ZoomOut)  # Standard Ctrl+-
        self.decrease_font_action.triggered.connect(self.decrease_font_size)
        
        # Tab key for switching focus between trees
        self.tab_switch_action = QAction("Switch Focus Forwards", self)
        self.tab_switch_action.setShortcut(QKeySequence(Qt.Key.Key_Tab))
        self.tab_switch_action.triggered.connect(lambda: self._switch_focus_between_trees(forwards=True))
        
        # Shift+Tab for switching focus in reverse
        self.tab_switch_back_action = QAction("Switch Focus Backwards", self)
        self.tab_switch_back_action.setShortcut(QKeySequence(Qt.Key.Key_Backtab))  # Backtab is Shift+Tab
        self.tab_switch_back_action.triggered.connect(lambda: self._switch_focus_between_trees(forwards=False))
        
        # --- Preset Shortcuts (Global) ---
        # Save Preset Shortcut (Ctrl+S)
        self.save_preset_action = QAction("Save Preset Shortcut", self)
        self.save_preset_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_preset_action.triggered.connect(self.preset_handler._save_current_loaded_preset)
        self.save_preset_action.setEnabled(False)  # Initially disabled
        
        # Default Preset Shortcut (Ctrl+Shift+R)
        self.default_preset_action = QAction("Default Preset Shortcut", self)
        self.default_preset_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.default_preset_action.triggered.connect(self.preset_handler._handle_default_preset_action)
        
        # --- PortTreeWidget Actions (Move Up/Down) ---
        self.move_group_up_action = QAction("Move Up", self)
        self.move_group_up_action.setShortcut(QKeySequence("Alt+Up"))
        self.move_group_up_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # Context needed
        self.move_group_up_action.triggered.connect(self._handle_move_group_up)
        
        self.move_group_down_action = QAction("Move Down", self)
        self.move_group_down_action.setShortcut(QKeySequence("Alt+Down"))
        self.move_group_down_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)  # Context needed
        self.move_group_down_action.triggered.connect(self._handle_move_group_down)
    
    def setup_shortcuts(self):
        """Add the pre-defined QAction objects (with shortcuts) to the main window."""
        # Actions are defined in _setup_actions
        self.addAction(self.connect_action)
        self.addAction(self.disconnect_action)
        self.addAction(self.undo_shortcut_action)
        self.addAction(self.redo_shortcut_action)
        self.addAction(self.refresh_shortcut_action)
        self.addAction(self.collapse_all_shortcut_action)
        self.addAction(self.auto_refresh_shortcut_action)
        self.addAction(self.untangle_shortcut_action)
        self.addAction(self.increase_font_action)
        self.addAction(self.decrease_font_action)
        self.addAction(self.tab_switch_action)
        self.addAction(self.tab_switch_back_action)
        self.addAction(self.save_preset_action)
        self.addAction(self.default_preset_action)
        self.addAction(self.move_group_up_action)
        self.addAction(self.move_group_down_action)
    
    def _handle_connect_shortcut(self):
        """Calls the appropriate connect method based on the current tab."""
        current_index = self.tab_widget.currentIndex()
        if current_index == 0:  # Audio Tab
            self._animate_button_press(self.connect_button)
            self.make_connection_selected()
        elif current_index == 1:  # MIDI Tab
            self._animate_button_press(self.midi_connect_button)
            self.make_midi_connection_selected()
        # Ignore if on other tabs
    
    def _handle_disconnect_shortcut(self):
        """Calls the appropriate disconnect method based on the current tab."""
        current_index = self.tab_widget.currentIndex()
        if current_index == 0:  # Audio Tab
            self._animate_button_press(self.disconnect_button)
            self.break_connection_selected()
        elif current_index == 1:  # MIDI Tab
            self._animate_button_press(self.midi_disconnect_button)
            self.break_midi_connection_selected()
        # Ignore if on other tabs
    
    def _handle_collapse_all_shortcut(self):
        """Toggles the 'Collapse All' checkbox."""
        if hasattr(self, 'collapse_all_checkbox'):
            self.collapse_all_checkbox.toggle()
    
    def _handle_auto_refresh_shortcut(self):
        """Handles the Alt+R shortcut to toggle the auto-refresh checkbox."""
        if hasattr(self, 'auto_refresh_checkbox'):
            self.auto_refresh_checkbox.toggle()
    
    def _get_focused_tree_widget(self):
        """Finds which PortTreeWidget currently has focus."""
        focused_widget = QApplication.focusWidget()
        if hasattr(focused_widget, 'port_items'):
            return focused_widget
        # Check parents if focus is on a child widget within the tree
        while focused_widget is not None:
            if hasattr(focused_widget, 'port_items'):
                return focused_widget
            focused_widget = focused_widget.parent()
        return None
    
    def _handle_move_group_up(self):
        """Handles the global 'Move Up' action trigger."""
        focused_tree = self._get_focused_tree_widget()
        if focused_tree:
            item = focused_tree.currentItem()
            if item and item.parent() is None:  # Only move top-level items (groups)
                focused_tree.move_group_up(item)
    
    def _handle_move_group_down(self):
        """Handles the global 'Move Down' action trigger."""
        focused_tree = self._get_focused_tree_widget()
        if focused_tree:
            item = focused_tree.currentItem()
            if item and item.parent() is None:  # Only move top-level items (groups)
                focused_tree.move_group_down(item)
    
    def _switch_focus_between_trees(self, forwards=True):
        """Switch focus between output and input trees in the current tab."""
        current_tab = self.tab_widget.currentIndex()
        is_midi = current_tab == 1
        
        if current_tab == 0:  # Audio tab
            trees = [self.output_tree, self.input_tree] if forwards else [self.input_tree, self.output_tree]
        elif current_tab == 1:  # MIDI tab
            trees = [self.midi_output_tree, self.midi_input_tree] if forwards else [self.midi_input_tree, self.midi_output_tree]
        else:
            return  # Do nothing on other tabs
        
        # Find which tree currently has focus
        current_tree = None
        for tree in trees:
            if tree.hasFocus():
                current_tree = tree
                break
        
        # Switch focus to the other tree
        if current_tree:
            other_tree = trees[1] if current_tree == trees[0] else trees[0]
            
            # Get selected ports from current tree
            selected_ports = self._get_ports_from_selected_items(current_tree)
            
            # Find connected ports in the other tree
            if selected_ports:
                # Determine direction based on which tree we're moving from
                is_input_to_output = current_tree in (self.input_tree, self.midi_input_tree)
                connected_ports = self._get_connected_ports(selected_ports, is_input_to_output, is_midi)
                
                # Clear current selection in destination tree
                other_tree.clearSelection()
                
                # Select connected ports in destination tree
                for port_name in connected_ports:
                    port_item = other_tree.port_items.get(port_name)
                    if port_item:
                        port_item.setSelected(True)
            
            # Set focus to destination tree
            other_tree.setFocus()
            
            # Update button states after selection and focus change
            if is_midi:
                self.update_midi_connection_buttons()
            else:
                self.update_connection_buttons()
        else:
            # If no tree has focus, focus the first one
            trees[0].setFocus()
    
    def _get_connected_ports(self, port_names, is_input_to_output=True, is_midi=False):
        """
        Get connected ports for the given port names.
        
        Args:
            port_names: The port names to get connected ports for
            is_input_to_output: Whether to get output ports connected to input ports
            is_midi: Whether the ports are MIDI ports
            
        Returns:
            list: The connected ports
        """
        connected_ports = set()
        try:
            if is_input_to_output:
                # From input to output - look at all output ports
                output_ports = self.client.get_ports(is_output=True, is_midi=is_midi)
                for output_port in output_ports:
                    try:
                        connections = self.client.get_all_connections(output_port)
                        # If this output connects to any of our input ports
                        if any(conn.name in port_names for conn in connections):
                            connected_ports.add(output_port.name)
                    except jack.JackError:
                        continue
            else:
                # From output to input - just get direct connections
                for port_name in port_names:
                    try:
                        connections = self.client.get_all_connections(port_name)
                        connected_ports.update(conn.name for conn in connections)
                    except jack.JackError:
                        continue
        except jack.JackError as e:
            print(f"Error getting connected ports: {e}")
        return list(connected_ports)
    
    def increase_font_size(self):
        """Increases the font size for port lists."""
        max_size = 24
        if self.port_list_font_size < max_size:
            self.port_list_font_size += 1
            self.config_manager.set_str('port_list_font_size', str(self.port_list_font_size))
            self._apply_port_list_font_size()
            print(f"Port list font size increased to: {self.port_list_font_size}")
    
    def decrease_font_size(self):
        """Decreases the font size for port lists."""
        min_size = 6
        if self.port_list_font_size > min_size:
            self.port_list_font_size -= 1
            self.config_manager.set_str('port_list_font_size', str(self.port_list_font_size))
            self._apply_port_list_font_size()
            print(f"Port list font size decreased to: {self.port_list_font_size}")
    
    def _apply_port_list_font_size(self):
        """Applies the current font size to all port list tree widgets."""
        font = QFont()
        font.setPointSize(self.port_list_font_size)
        
        trees_to_update = []
        if hasattr(self, 'input_tree'):
            trees_to_update.append(self.input_tree)
        if hasattr(self, 'output_tree'):
            trees_to_update.append(self.output_tree)
        if hasattr(self, 'midi_input_tree'):
            trees_to_update.append(self.midi_input_tree)
        if hasattr(self, 'midi_output_tree'):
            trees_to_update.append(self.midi_output_tree)
        
        for tree in trees_to_update:
            tree.setFont(font)
        
        # Refresh visualizations as item sizes might change
        self.refresh_visualizations()
    
    def update_connections(self):
        """Update the audio connection visualization."""
        self._update_connection_graphics(self.connection_scene, self.connection_view,
                                        self.output_tree, self.input_tree, is_midi=False)
    
    def update_midi_connections(self):
        """Update the MIDI connection visualization."""
        self._update_connection_graphics(self.midi_connection_scene, self.midi_connection_view,
                                        self.midi_output_tree, self.midi_input_tree, is_midi=True)
    
    def _update_connection_graphics(self, scene, view, output_tree, input_tree, is_midi):
        """
        Update the connection graphics in the scene.
        
        Args:
            scene: The scene to update
            view: The view to update
            output_tree: The output tree widget
            input_tree: The input tree widget
            is_midi: Whether the connections are MIDI connections
        """
        # Clear the scene first
        scene.clear()
        view_rect = view.rect()
        scene_rect = QRectF(0, 0, view_rect.width(), view_rect.height())
        scene.setSceneRect(scene_rect)
        
        # Get all connections
        connections = []
        try:
            ports = self.client.get_ports()
            for output_port in ports:
                if output_port.is_output and output_port.is_midi == is_midi:
                    for input_port in self.client.get_all_connections(output_port):
                        if input_port.is_input and input_port.is_midi == is_midi:
                            connections.append((output_port.name, input_port.name))
        except jack.JackError as e:
            print(f"Error getting connections: {e}")
            return
        
        # Draw each connection
        for output_name, input_name in connections:
            start_pos = self.get_port_position(output_tree, output_name, view)
            end_pos = self.get_port_position(input_tree, input_name, view)
            
            # Only draw connections where both ends are visible
            if start_pos and end_pos:
                path = QPainterPath()
                path.moveTo(start_pos)
                
                # Calculate control points for a smooth curve
                ctrl1_x = start_pos.x() + (end_pos.x() - start_pos.x()) / 3
                ctrl2_x = start_pos.x() + 2 * (end_pos.x() - start_pos.x()) / 3
                
                path.cubicTo(
                    QPointF(ctrl1_x, start_pos.y()),
                    QPointF(ctrl2_x, end_pos.y()),
                    end_pos
                )
                
                # Use a consistent color for connections from the same source
                base_name = output_name.rsplit(':', 1)[0]
                
                # Get a base random color
                random.seed(base_name)
                base_color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                
                # Brighten the color in dark mode for better visibility
                if self.dark_mode:
                    # Make colors more vibrant and brighter in dark mode
                    h, s, v, a = base_color.getHsvF()
                    # Increase saturation and value for more vibrant appearance
                    s = min(1.0, s * 1.4)  # Increase saturation by 40%
                    v = min(1.0, v * 1.3)  # Increase brightness by 30%
                    base_color.setHsvF(h, s, v, a)
                
                pen = QPen(base_color, 2)
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                scene.addItem(path_item)
        
        # Fit the view to show all connections
        view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def get_port_position(self, tree_widget, port_name, connection_view):
        """
        Get the position of a port in the tree widget for drawing connections.
        
        Args:
            tree_widget: The tree widget containing the port
            port_name: The name of the port
            connection_view: The connection view
            
        Returns:
            QPointF: The position of the port in scene coordinates
        """
        port_item = tree_widget.port_items.get(port_name)
        if not port_item:
            return None
        
        # Get the parent group item
        parent_group = port_item.parent()
        if not parent_group:
            return None
        
        # Check if the parent group is expanded
        is_expanded = parent_group.isExpanded()
        
        # If the group is collapsed, use the group's position instead
        target_item = port_item if is_expanded else parent_group
        
        # Get the rectangle for the item
        rect = tree_widget.visualItemRect(target_item)
        
        # If the rect has zero height (item not visible), return None
        if rect.height() <= 0:
            return None
        
        is_output = tree_widget in (self.output_tree, self.midi_output_tree)
        
        # Calculate the point at the middle-right or middle-left of the item
        point = QPointF(tree_widget.viewport().width() if is_output else 0,
                       rect.top() + rect.height() / 2)
        
        viewport_point = tree_widget.viewport().mapToParent(point.toPoint())
        global_point = tree_widget.mapToGlobal(viewport_point)
        scene_point = connection_view.mapFromGlobal(global_point)
        return connection_view.mapToScene(scene_point)
    
    def disconnect_selected_groups(self, group_items):
        """
        Disconnects all connections for all ports within the selected group items.
        
        Args:
            group_items: The group items to disconnect
        """
        ports_to_disconnect = set()
        
        for group_item in group_items:
            # Ensure it's actually a group item (has children)
            if group_item and group_item.childCount() > 0:
                for i in range(group_item.childCount()):
                    port_item = group_item.child(i)
                    port_name = port_item.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        ports_to_disconnect.add(port_name)
        
        if not ports_to_disconnect:
            return
        
        for port_name in ports_to_disconnect:
            # Use the existing disconnect_node logic which handles connections
            # and updates history/UI via break_connection/_port_operation
            self.disconnect_node(port_name)
    
    def closeEvent(self, event):
        """
        Handle window closing behavior.
        
        Args:
            event: The close event
        """
        # Always quit the application when the window is closed
        event.accept()
        QApplication.quit()
        
        # Clean up JACK client and deactivate callbacks
        if hasattr(self, 'client'):
            self.callbacks_enabled = False
            self.client.deactivate()
            self.client.close()
        
        # Stop the visualization refresh timers
        self.connection_view.stop_refresh_timer()
        self.midi_connection_view.stop_refresh_timer()
        
        # Stop pw-top monitor before closing
        if hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
            self.pwtop_monitor.stop()
        
        # Stop latency test process before closing
        if hasattr(self, 'latency_tester') and self.latency_tester is not None:
            self.latency_tester.stop_latency_test()

    def _get_current_connections(self):
        """Gets the current state of all JACK audio and MIDI connections."""
        all_connections = []
        try:
            # Get all output ports (both audio and MIDI)
            output_ports = self.client.get_ports(is_output=True)
            for output_port in output_ports:
                try:
                    # Check if port still exists before getting connections
                    if not any(p.name == output_port.name for p in self.client.get_ports(is_output=True)):
                        continue
                    connected_inputs = self.client.get_all_connections(output_port)
                    port_type = "midi" if output_port.is_midi else "audio"
                    for input_port in connected_inputs:
                        # Ensure the connected port is also of the same type (should always be true)
                        if input_port.is_midi == output_port.is_midi:
                             all_connections.append({
                                 "output": output_port.name,
                                 "input": input_port.name,
                                 "type": port_type
                             })
                except jack.JackError as conn_err:
                    # Ignore errors getting connections for a single port (it might have disappeared)
                    print(f"Warning: Could not get connections for {output_port.name}: {conn_err}")
                    continue
        except jack.JackError as e:
            print(f"Error getting current connections: {e}")
        return all_connections
