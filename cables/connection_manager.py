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
                            QSpacerItem, QMessageBox, QGraphicsPathItem, QTreeWidget, QToolBar) # Removed QSize, Added QToolBar
from PyQt6.QtCore import Qt, QMimeData, QPointF, QRectF, QTimer, QSize, QRect, QProcess, pyqtSignal, QPoint, pyqtSlot
from PyQt6.QtGui import QGuiApplication, QColor, QPalette, QFont, QKeySequence, QAction, QTextCursor, QPainterPath, QPen, QBrush

# Import our modules
from cables.config.config_manager import ConfigManager
from cables.config.preset_manager import PresetManager
from cables.features.connection_history import ConnectionHistory
from cables.features.preset_handler import PresetHandler
from cables.ui.tab_ui_manager import TabUIManager
from cables.jack_connection_handler import JackConnectionHandler # Added import
from cables.highlight_manager import HighlightManager # Added import
from cables.ui_state_manager import UIStateManager # Added import
from cables.action_manager import ActionManager # Added import
from cables.port_manager import PortManager # Added import
from cables.interaction_manager import InteractionManager # Added import
from cable_core import app_config

class JackConnectionManager(QMainWindow):
    """
    Main application window for the JACK/PipeWire connection manager.
    
    This class manages the UI and functionality for connecting and
    disconnecting JACK/PipeWire ports, as well as managing presets.
    """
    
    # PyQt signals for JACK events, designed for detailed graph updates
    port_added = pyqtSignal(str, str, int, str, bool)  # port_name, client_name, flags, type, is_input
    port_removed = pyqtSignal(str, str)  # port_name, client_name
    client_added = pyqtSignal(str)  # client_name
    client_removed = pyqtSignal(str)  # client_name
    connection_made = pyqtSignal(str, str)  # out_port_name, in_port_name
    connection_broken = pyqtSignal(str, str)  # out_port_name, in_port_name
    jack_shutdown_signal = pyqtSignal()  # For JACK server shutdown
    graph_updated = pyqtSignal()  # For general graph updates / fallback
    untangle_mode_changed = pyqtSignal(int)  # Signal for mode change
    
    # Old signals (kept for now if other parts of the app use them, but graph should use new ones)
    port_registered = pyqtSignal(str, bool)  # port name, is_input
    port_unregistered = pyqtSignal(str, bool)  # port name, is_input
    client_registered = pyqtSignal(str, bool) # client_name, is_registered
    ports_connected = pyqtSignal(str, str, bool) # out_port_name, in_port_name, is_connected
    
    def __init__(self):
        """Initialize the JackConnectionManager."""
        super().__init__()

        self._graph_is_fullscreen = False
        self._widgets_original_visibility = {} # For storing visibility of main UI chrome
        
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
        self.jack_handler = JackConnectionHandler(self.client, self) # Instantiate handler

        # Initialize connection history
        self.connection_history = ConnectionHistory()
        
        # Untangle mode state is now managed by UIStateManager
        # self.untangle_mode = self.config_manager.get_int('untangle_mode', 0)

        # Detect Flatpak environment
        self.flatpak_env = os.path.exists('/.flatpak-info')
        
        # Set up colors
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()

        # HighlightManager will be instantiated in _setup_ui after trees are created
        
        # Auto-refresh state (callbacks_enabled, is_focused) managed by UIStateManager
        # self.callbacks_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        # self.is_focused = self.isActiveWindow()

        # Port list font size managed by UIStateManager
        # try:
        #     self.port_list_font_size = int(self.config_manager.get_str('port_list_font_size', '10'))
        # except ValueError:
        #     self.port_list_font_size = 10  # Default if config value is invalid

        # Create filter edit widgets
        self.output_filter_edit = QLineEdit()
        self.output_filter_edit.setPlaceholderText("Filter outputs...")
        self.output_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        self.input_filter_edit = QLineEdit()
        self.input_filter_edit.setPlaceholderText("Filter inputs...")
        self.input_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        
        # Set up JACK port registration callbacks
        self.client.set_port_registration_callback(self._handle_port_registration)
        self.client.set_client_registration_callback(self._handle_client_registration) # ADDED
        self.client.set_port_connect_callback(self._handle_port_connect_callback) # ADDED
        self.client.set_shutdown_callback(self._handle_shutdown_callback) # ADDED
        # self.client.set_graph_order_callback(self._handle_graph_order_callback) # TODO: Add if needed for JackGraphScene
        
        # Connect signals to refresh methods
        self.port_registered.connect(self._on_port_registered)
        self.port_unregistered.connect(self._on_port_unregistered)
        
        # Instantiate PortManager *before* _setup_ui, passing filters but not trees yet
        self.port_manager = PortManager(
            connection_manager=self,
            jack_client=self.client,
            input_filter_edit=self.input_filter_edit,
            output_filter_edit=self.output_filter_edit
        )

        # Set up the UI (this creates the widgets needed by UIStateManager and the trees)
        self._setup_ui()

        # Now that trees exist, set them in PortManager and connect signals
        self.port_manager.set_trees(
            input_tree=getattr(self, 'input_tree', None),
            output_tree=getattr(self, 'output_tree', None),
            midi_input_tree=getattr(self, 'midi_input_tree', None),
            midi_output_tree=getattr(self, 'midi_output_tree', None)
        )

        # Instantiate UIStateManager *after* _setup_ui() has created the necessary widgets
        # and *after* _setup_bottom_layout() has connected signals to its methods.
        self.ui_state_manager = UIStateManager(
            parent=self,
            config_manager=self.config_manager,
            main_window=self,
            auto_refresh_checkbox=self.auto_refresh_checkbox, # Exists now
            collapse_checkbox=self.collapse_all_checkbox, # Exists now
            untangle_button=self.untangle_button, # Exists now
            increase_font_button=self.zoom_in_button, # Exists now
            decrease_font_button=self.zoom_out_button, # Exists now
            input_tree=self.input_tree, # Exists now
            output_tree=self.output_tree, # Exists now
            midi_input_tree=self.midi_input_tree, # Exists now
            midi_output_tree=self.midi_output_tree, # Exists now
            connection_view=self.connection_view, # Exists now
            midi_connection_view=self.midi_connection_view # Exists now
        )

        # Connect signals from widgets created in _setup_bottom_layout to UIStateManager
        if hasattr(self, 'auto_refresh_checkbox') and self.auto_refresh_checkbox:
            self.auto_refresh_checkbox.stateChanged.connect(self.ui_state_manager.toggle_auto_refresh)
        if hasattr(self, 'collapse_all_checkbox') and self.collapse_all_checkbox:
            self.collapse_all_checkbox.stateChanged.connect(self.ui_state_manager.toggle_collapse_all)
        if hasattr(self, 'untangle_button') and self.untangle_button:
            self.untangle_button.clicked.connect(self.ui_state_manager.toggle_untangle_sort)
        if hasattr(self, 'zoom_in_button') and self.zoom_in_button:
            self.zoom_in_button.clicked.connect(self.ui_state_manager.increase_font_size)
        if hasattr(self, 'zoom_out_button') and self.zoom_out_button:
            self.zoom_out_button.clicked.connect(self.ui_state_manager.decrease_font_size)

        # Explicitly call switch_tab for the initial index *after* UIStateManager is set up
        # This ensures the necessary state (like collapse) is applied correctly.
        if hasattr(self, 'tab_widget'):
             self.switch_tab(self.tab_widget.currentIndex())

        # Gather UI elements for ActionManager
        self.ui_elements = {
            'tab_widget': self.tab_widget,
            'connect_button': getattr(self, 'connect_button', None),
            'disconnect_button': getattr(self, 'disconnect_button', None),
            'midi_connect_button': getattr(self, 'midi_connect_button', None),
            'midi_disconnect_button': getattr(self, 'midi_disconnect_button', None),
            'undo_button': getattr(self, 'undo_button', None),
            'redo_button': getattr(self, 'redo_button', None),
            'collapse_all_checkbox': getattr(self, 'collapse_all_checkbox', None),
            'auto_refresh_checkbox': getattr(self, 'auto_refresh_checkbox', None),
            'output_tree': getattr(self, 'output_tree', None),
            'input_tree': getattr(self, 'input_tree', None),
            'midi_output_tree': getattr(self, 'midi_output_tree', None),
            'midi_input_tree': getattr(self, 'midi_input_tree', None),
            'graph_main_window': getattr(self, 'graph_main_window', None), # Added for Graph tab actions
            # Add other UI elements needed by ActionManager handlers if any
        }

        # Instantiate ActionManager
        self.action_manager = ActionManager(
            main_window=self,
            state_manager=self.ui_state_manager,
            connection_handler=self.jack_handler,
            preset_handler=self.preset_handler,
            ui=self.ui_elements
        )
        # Set up actions and shortcuts via the manager
        self.action_manager.setup_actions_and_shortcuts()

        # Connect Undo/Redo button signals *after* action_manager is created
        if hasattr(self, 'undo_button') and self.undo_button:
            self.undo_button.clicked.connect(self.action_manager._handle_undo)
        if hasattr(self, 'redo_button') and self.redo_button:
            self.redo_button.clicked.connect(self.action_manager._handle_redo)

        # Connect preset button signals after UI is set up
        if hasattr(self, 'presets_button') and self.presets_button:
            self.presets_button.clicked.connect(self.preset_handler._show_preset_menu)
        if hasattr(self, 'midi_presets_button') and self.midi_presets_button:
            self.midi_presets_button.clicked.connect(self.preset_handler._show_preset_menu)
        
        # Activate JACK client
        self.client.activate()
        
        # Set initial state for the global save shortcut (now managed by ActionManager)
        if hasattr(self.action_manager, 'save_preset_action') and self.action_manager.save_preset_action:
            self.action_manager.save_preset_action.setEnabled(bool(self.preset_handler.current_preset_name))

        # Instantiate InteractionManager *after* highlight_manager and button update methods exist
        self.interaction_manager = InteractionManager(
            highlight_manager=self.highlight_manager,
            update_connection_buttons_func=self.update_connection_buttons,
            update_midi_connection_buttons_func=self.update_midi_connection_buttons
        )

        # Connect tree click signals to InteractionManager using lambdas
        if hasattr(self, 'input_tree') and self.input_tree:
            self.input_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.input_tree, False # Pass clicked_tree and is_midi
                )
            )
        if hasattr(self, 'output_tree') and self.output_tree:
            self.output_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.output_tree, False # Pass clicked_tree and is_midi
                )
            )
        if hasattr(self, 'midi_input_tree') and self.midi_input_tree:
            self.midi_input_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.midi_input_tree, True # Pass clicked_tree and is_midi
                )
            )
        if hasattr(self, 'midi_output_tree') and self.midi_output_tree:
            self.midi_output_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.midi_output_tree, True # Pass clicked_tree and is_midi
                )
            )

        # PortManager instantiation moved earlier

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
        self.graph_tab_widget = QWidget() # Added for Graph tab
        self.pwtop_tab_widget = QWidget()
        self.latency_tab_widget = QWidget()
        
        # Set up tabs using TabUIManager
        self.tab_ui_manager = TabUIManager()
        # Setup tabs *before* HighlightManager instantiation needs the trees
        # Instantiate HighlightManager *before* setting up port tabs, passing None for trees initially
        self.highlight_manager = HighlightManager(
            input_tree=None,
            output_tree=None,
            midi_input_tree=None,
            midi_output_tree=None,
            client=self.client,
            colors={ # Pass color definitions
                'text': self.text_color,
                'background': self.background_color,
                'highlight': self.highlight_color,
                'auto_highlight': self.auto_highlight_color,
                'drag_highlight': self.drag_highlight_color
            }
        )

        # Setup tabs - this will create the trees and pass the highlight_manager instance
        self.tab_ui_manager.setup_port_tab(self, self.audio_tab_widget, "Audio", 'audio')
        self.tab_ui_manager.setup_port_tab(self, self.midi_tab_widget, "MIDI", 'midi')
        # setup_graph_tab will be called after port tabs, before pwtop
        self.tab_ui_manager.setup_pwtop_tab(self, self.pwtop_tab_widget)
        self.tab_ui_manager.setup_latency_tab(self, self.latency_tab_widget)

        # Now that trees exist, update the HighlightManager instance with references
        self.highlight_manager.input_tree = self.input_tree
        self.highlight_manager.output_tree = self.output_tree
        self.highlight_manager.midi_input_tree = self.midi_input_tree
        self.highlight_manager.midi_output_tree = self.midi_output_tree

        # Add tabs to tab widget
        self.tab_widget.addTab(self.audio_tab_widget, "Audio") # Index 0
        self.tab_widget.addTab(self.midi_tab_widget, "MIDI")   # Index 1
        
        # Setup and insert the Graph tab as the third tab (index 2)
        self.tab_ui_manager.setup_graph_tab(self, self.graph_tab_widget)
        self.tab_widget.insertTab(2, self.graph_tab_widget, "Graph") # Index 2

        # Connect the fullscreen toggle signal from the graph view
        if hasattr(self, 'graph_main_window') and self.graph_main_window and \
           hasattr(self.graph_main_window, 'view') and self.graph_main_window.view and \
           hasattr(self.graph_main_window.view, 'fullscreen_request_signal'):
            self.graph_main_window.view.fullscreen_request_signal.connect(self.toggle_graph_fullscreen)
        
        self.tab_widget.addTab(self.pwtop_tab_widget, "pw-top") # Becomes Index 3
        self.tab_widget.addTab(self.latency_tab_widget, "Latency Test") # Becomes Index 4
        
        # Set the active tab based on the saved value
        if 0 <= self.last_active_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(self.last_active_tab)
        
        # Set up bottom layout
        self._setup_bottom_layout(main_layout)
        
        # Connect tab change signal
        self.tab_widget.currentChanged.connect(self.switch_tab)
        
        # Initial switch_tab call moved to __init__ after UIStateManager is ready.
    
    def _setup_bottom_layout(self, main_layout):
        """Set up the bottom layout with controls."""
        bottom_layout = QHBoxLayout()
        
        # Auto Refresh checkbox
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        # Auto Refresh checkbox state is loaded/set by UIStateManager
        # auto_refresh_enabled = self.config_manager.get_bool('auto_refresh_enabled', True)
        # self.auto_refresh_checkbox.setChecked(auto_refresh_enabled)
        self.auto_refresh_checkbox.setToolTip("Toggle automatic refreshing of ports and connections <span style='color:grey'>Alt+R</span>")
        # Signal connected later
 
        # Collapse All toggle
        self.collapse_all_checkbox = QCheckBox('Collapse All')
        # Collapse state is loaded/set by UIStateManager
        # collapse_all_enabled = self.config_manager.get_bool('collapse_all_enabled', False)
        # self.collapse_all_checkbox.setChecked(collapse_all_enabled)
        self.collapse_all_checkbox.setToolTip("Toggle collapse state for all groups <span style='color:grey'>Alt+C</span>")
        # Signal connected later

        # Undo/Redo buttons
        self.undo_button = QPushButton('       Undo       ')
        self.undo_button.setToolTip("Undo last connection <span style='color:grey'>Ctrl+Z</span>")
        self.redo_button = QPushButton('       Redo       ')
        self.redo_button.setToolTip("Redo last connection <span style='color:grey'>Shift+Ctrl+Z/Ctrl+Y</span>")
        
        # Apply a specific stylesheet to disable hover effect for Undo/Redo buttons to match Graph tab
        no_hover_style = """
            QPushButton { background-color: palette(button); color: palette(buttonText); }
            QPushButton:hover { background-color: palette(button); color: palette(buttonText); }
        """
        self.undo_button.setStyleSheet(no_hover_style)
        self.redo_button.setStyleSheet(no_hover_style)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        
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
        
        # Apply a specific stylesheet to disable hover effect
        no_hover_style = """
            QPushButton { background-color: palette(button); color: palette(buttonText); }
            QPushButton:hover { background-color: palette(button); color: palette(buttonText); }
        """
        
        # Refresh button
        self.bottom_refresh_button = QPushButton('     Refresh     ')
        self.bottom_refresh_button.setToolTip("Refresh port list <span style='color:grey'>R</span>")
        self.bottom_refresh_button.setStyleSheet(no_hover_style)
        self.bottom_refresh_button.clicked.connect(self.refresh_ports)
        
        # Untangle button
        self.untangle_button = QPushButton()  # Text set by _update_untangle_button_text
        self.untangle_button.setStyleSheet(no_hover_style)
        # Tooltip and text are set by UIStateManager._update_untangle_button_text()
        # self.untangle_button.setToolTip("Untangle cables: Default -> A -> B (Alt+U)")
        # Signal connected later
        # self._update_untangle_button_text() is called by UIStateManager init

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
        self.zoom_in_button.setToolTip("Increase port list font size <span style='color:grey'>Ctrl++</span>")
        self.zoom_in_button.setStyleSheet(no_hover_style)
        zoom_button_size = QSize(25, 25)  # Define smaller, square size
        self.zoom_in_button.setFixedSize(zoom_button_size)
        # Signal connected later

        self.zoom_out_button = QPushButton('-')
        self.zoom_out_button.setToolTip("Decrease port list font size <span style='color:grey'>Ctrl+-</span>")
        self.zoom_out_button.setStyleSheet(no_hover_style)
        self.zoom_out_button.setFixedSize(zoom_button_size)
        # Signal connected later

        bottom_layout.addWidget(self.zoom_out_button)
        bottom_layout.addWidget(self.zoom_in_button)
        
        if hasattr(self, 'input_filter_edit'):
            self.input_filter_edit.setStyleSheet(filter_style)
            self.input_filter_edit.setClearButtonEnabled(True)
            self.input_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.input_filter_edit)  # Add input filter to the far right
        
        main_layout.addLayout(bottom_layout)
        
        # Signal connections to UIStateManager moved to __init__ after instantiation

        # Signal connections for Undo/Redo moved to __init__ after action_manager creation

        # Callback state is managed internally by UIStateManager
        # self.callbacks_enabled = auto_refresh_enabled

        # Initialize visibility based on current tab
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        self.show_bottom_controls(current_tab < 2)
        
        # Start visualization timers handled by UIStateManager init/load
        # if auto_refresh_enabled:
        #     self.connection_view.start_refresh_timer(self.refresh_visualizations)
        #     self.midi_connection_view.start_refresh_timer(self.refresh_visualizations)

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
        # Adjusted index for pw-top due to new Graph tab
        if index != 3 and hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
            self.pwtop_monitor.stop()

        # Stop graph_jack_handler if switching away from Graph tab (index 2)
        # The handler is started in setup_graph_tab. Here we manage stopping/restarting if needed.
        # For now, we assume it's started once and stopped on close.
        # If we need to stop/start it on tab visibility, this is where it would go.
        # if index != 2 and hasattr(self, 'graph_jack_handler') and self.graph_jack_handler and self.graph_jack_handler.is_active():
        #     print("Switching away from Graph tab, stopping its JackHandler (if implemented)")
        #     # self.graph_jack_handler.stop() # Potentially stop
        
        # Configure based on the new tab index
        if index < 2:  # Audio (0) or MIDI (1) tabs
            self.port_type = 'audio' if index == 0 else 'midi'
            # Apply collapse state based on checkbox state for the *current* tab's trees
            if hasattr(self, 'ui_state_manager'): # Ensure ui_state_manager exists
                 self.ui_state_manager.apply_collapse_state_to_current_trees()
            self.refresh_visualizations()
            self.show_bottom_controls(True)  # Show controls
        elif index == 2: # Graph tab
            self.show_bottom_controls(False) # Hide standard controls for graph tab
            # Start graph_jack_handler if it's not running (e.g., if we implement stop on tab switch away)
            # if hasattr(self, 'graph_jack_handler') and self.graph_jack_handler and not self.graph_jack_handler.is_active():
            #     print("Switching to Graph tab, ensuring its JackHandler is running (if implemented)")
            #     # graph_jack_thread = threading.Thread(target=self.graph_jack_handler.start, daemon=True)
            #     # graph_jack_thread.start() # Potentially (re)start
            # For now, graph_jack_handler is started once in setup_graph_tab.
            # Refresh the graph view if necessary
            if hasattr(self, 'graph_main_window') and self.graph_main_window:
                if hasattr(self.graph_main_window, 'scene') and self.graph_main_window.scene:
                    # Corrected method call:
                    self.graph_main_window.scene.full_graph_refresh()
        elif index == 3:  # pw-top tab (new index)
            # Start pw-top monitor only when switching to this tab
            if hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
                self.pwtop_monitor.start()
            self.show_bottom_controls(False)  # Hide controls
        elif index == 4:  # Latency Test tab (new index)
            # No specific process to start here, just hide controls
            self.show_bottom_controls(False)  # Hide controls
        
        # Update the refresh interval (handled by UIStateManager based on focus/tab change)
        # We still need to inform UIStateManager about focus changes if they happen during tab switch
        # but the interval update itself is internal to UIStateManager.
        # The focus change event (changeEvent) will trigger the update.
        # self._update_refresh_timer_interval() # Removed

        # Save the current tab index to config
        self.last_active_tab = index
        self.config_manager.set_int('last_active_tab', index)

        # Ensure the refresh interval is updated based on the new tab and current focus state
        if hasattr(self, 'ui_state_manager') and self.ui_state_manager:
            self.ui_state_manager._update_refresh_timer_interval()
    
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
    
    # filter_ports moved to PortManager

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
            # clear_highlights = self.clear_highlights # Replaced by highlight_manager call
            update_buttons = self.update_connection_buttons
            is_midi = False
        elif port_type_to_refresh == 'midi':
            input_tree = self.midi_input_tree
            output_tree = self.midi_output_tree
            update_visuals = self.update_midi_connections
            # clear_highlights = self.clear_midi_highlights # Replaced by highlight_manager call
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
        
        # 4. Get new port lists for this type using PortManager
        input_ports, output_ports = self.port_manager._get_ports(is_midi=is_midi)

        # 5. Repopulate trees for this type (without previous_group_order)
        input_tree.populate_tree(input_ports)
        output_tree.populate_tree(output_ports)
        
        # 6. Re-apply filter for this type using PortManager
        self.port_manager.filter_ports(input_tree, current_input_filter)
        self.port_manager.filter_ports(output_tree, current_output_filter)

        # 7. Restore selection for this type
        self._restore_selection(input_tree, selected_input_info)
        self._restore_selection(output_tree, selected_output_info)
        
        # 8. Update visuals and button states for this type
        update_visuals()
        # Clear highlights using the manager
        if is_midi:
            self.highlight_manager.clear_midi_highlights()
        else:
            self.highlight_manager.clear_highlights()
        update_buttons()

        # 9. Re-apply highlights based on the *restored* selection using HighlightManager
        restored_input_item = input_tree.currentItem()
        restored_output_item = output_tree.currentItem()

        if restored_input_item:
            self.highlight_manager.apply_highlights_for_selection(restored_input_item, input_tree, is_midi)

        if restored_output_item:
            # Avoid double-highlighting if the same item is selected in both trees (unlikely but possible)
            if restored_output_item != restored_input_item:
                 self.highlight_manager.apply_highlights_for_selection(restored_output_item, output_tree, is_midi)

        # 10. Maintain collapse state if needed for this type
        if self.port_type == port_type_to_refresh:
            # Apply collapse state based on checkbox state for the *current* tab's trees
            self.ui_state_manager.apply_collapse_state_to_current_trees()
    
    # Dedent the following method definition by one level
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
    
    # _get_ports moved to PortManager
    # _sort_ports moved to PortManager

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
            
            # Apply collapse state after startup refresh is complete using UIStateManager
            self.ui_state_manager.apply_collapse_state_to_all_trees(
                collapse=self.ui_state_manager.collapse_checkbox.isChecked()
            )

    # --- UI State Methods Moved to UIStateManager ---
    # (Commented out methods below are placeholders and their bodies were removed)

    # def toggle_auto_refresh(self, state):
    #     """Handled by UIStateManager.toggle_auto_refresh"""
    #     pass

    # def _update_refresh_timer_interval(self):
    #     """Handled by UIStateManager._update_refresh_timer_interval"""
    #     pass

    def changeEvent(self, event):
        """
        Handle window state changes, specifically activation.

        Args:
            event: The change event
        """
        super().changeEvent(event)  # Call base implementation first
        if event.type() == event.Type.ActivationChange:
            # Inform UIStateManager about focus change
            if hasattr(self, 'ui_state_manager'): # Check if manager exists yet
                 self.ui_state_manager.handle_focus_change(self.isActiveWindow())
            # Timer interval update is handled within UIStateManager

    # def toggle_collapse_all(self, state):
    #     """Handled by UIStateManager.toggle_collapse_all"""
    #     pass

    # def apply_collapse_state_to_all_trees(self):
    #     """Handled by UIStateManager.apply_collapse_state_to_all_trees"""
    #     pass

    # def apply_collapse_state_to_current_trees(self):
    #     """Handled by UIStateManager.apply_collapse_state_to_current_trees"""
    #     pass

    # def _update_untangle_button_text(self):
    #     """Handled by UIStateManager._update_untangle_button_text"""
    #     pass

    # def toggle_untangle_sort(self):
    #     """Handled by UIStateManager.toggle_untangle_sort"""
    #     pass

    # def _handle_untangle_shortcut(self):
    #     """Handled by UIStateManager._handle_untangle_shortcut"""
    #     pass

    # def increase_font_size(self):
    #     """Handled by UIStateManager.increase_font_size"""
    #     pass

    # def decrease_font_size(self):
    #     """Handled by UIStateManager.decrease_font_size"""
    #     pass

    # def _apply_port_list_font_size(self):
    #     """Handled by UIStateManager._apply_port_list_font_size"""
    #     pass

    # --- End of Moved UI State Methods ---

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
    
    # _handle_filter_change moved to PortManager

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
            port_name_str = None
            client_name_str = "UnknownClient"
            port_flags_val = 0
            port_type_str = "UnknownType"
            is_input_val = False

            if not hasattr(port, 'name') or not hasattr(port, '_client') or \
               (hasattr(port, '_client') and not hasattr(port._client, 'name')) or \
               not hasattr(port, 'is_input'): # Temporarily removed flags and type checks from this initial guard
                print(f"Port registration callback: Port object missing critical attributes (name, _client, _client.name, or is_input). Port: {port}")
                self.graph_updated.emit() # Fallback to general refresh
                return

            try:
                port_name_str = port.name
                if not isinstance(port_name_str, str) or not port_name_str:
                    print(f"Port registration callback: Invalid port name. Port: {port}")
                    self.graph_updated.emit()
                    return

                # Derive client_name_str from port.name
                if ':' in port.name:
                    client_name_str = port.name.split(':', 1)[0]
                else:
                    # This case should ideally not happen for client ports with a specific port part
                    # but handle defensively. If port.name is just "client_name", use that.
                    client_name_str = port.name
                
                # Attempt to get flags and type, with fallbacks
                try:
                    port_flags_val = port.flags # This is expected to fail
                except AttributeError:
                    port_flags_val = 0 # Fallback value

                try:
                    port_type_str = port.type # This is expected to fail
                except AttributeError:
                    if port.is_midi:
                        port_type_str = "midi"
                    elif port.is_audio:
                        port_type_str = "audio"
                    else:
                        port_type_str = "unknown" # Fallback type string
                
                is_input_val = port.is_input

            except Exception as ex_attrs:
                print(f"Port registration callback: Error accessing critical port attributes for '{getattr(port, 'name', 'N/A')}': {ex_attrs}")
                self.graph_updated.emit() # Fallback
                return

            if register:
                self.port_added.emit(port_name_str, client_name_str, port_flags_val, port_type_str, is_input_val)
                # Emit old signal for compatibility if needed by other parts
                self.port_registered.emit(port_name_str, is_input_val)
            else:
                self.port_removed.emit(port_name_str, client_name_str)
                # Emit old signal for compatibility
                self.port_unregistered.emit(port_name_str, is_input_val)
            
            self.graph_updated.emit() # Emit graph_updated for port changes as a general notification
        except Exception as e:
            # Log any errors since this runs in a callback
            print(f"Port registration callback error: {type(e).__name__}: {e}")
            self.graph_updated.emit() # Fallback

    def _handle_client_registration(self, client_name: str, register: bool):
        """
        JACK callback for client registration events. This runs in JACK's thread.
        Emits client_added or client_removed signals.
        """
        try:
            if not isinstance(client_name, str) or not client_name:
                print(f"Client registration callback: Invalid client_name '{client_name}'.")
                self.graph_updated.emit() # Fallback
                return

            print(f"Client {'added' if register else 'removed'}: {client_name}")
            if register:
                self.client_added.emit(client_name)
            else:
                self.client_removed.emit(client_name)
            
            # Emit old signal for compatibility
            self.client_registered.emit(client_name, register)
            self.graph_updated.emit() # Emit graph_updated for client changes as a general notification
        except Exception as e:
            print(f"Client registration callback error: {type(e).__name__}: {e}")
            self.graph_updated.emit() # Fallback

    def _handle_port_connect_callback(self, port_a: jack.Port, port_b: jack.Port, are_connected: bool):
        """
        JACK callback for port connection events. Runs in JACK's thread.
        Emits connection_made or connection_broken signals.
        The arguments port_a and port_b are jack.Port objects.
        """
        try:
            if not port_a or not hasattr(port_a, 'name') or \
               not port_b or not hasattr(port_b, 'name') or \
               not hasattr(port_a, 'is_output') or not hasattr(port_b, 'is_input'):
                print(f"Port connect callback: Invalid port objects or missing attributes. Port A: {port_a}, Port B: {port_b}")
                self.graph_updated.emit() # Fallback
                return

            port_a_name = port_a.name
            port_b_name = port_b.name

            out_port_name, in_port_name = "", ""
            if port_a.is_output and port_b.is_input:
                out_port_name, in_port_name = port_a_name, port_b_name
            elif port_b.is_output and port_a.is_input: # JACK might call with (input, output)
                out_port_name, in_port_name = port_b_name, port_a_name
            else:
                # This case should ideally not happen if JACK provides one output and one input.
                print(f"Port connect callback: Ambiguous port types for {port_a_name} (is_output={port_a.is_output}) and {port_b_name} (is_input={port_b.is_input}). Refreshing graph.")
                self.graph_updated.emit()
                return

            if are_connected:
                print(f"Connection made: {out_port_name} -> {in_port_name}")
                self.connection_made.emit(out_port_name, in_port_name)
            else:
                print(f"Connection broken: {out_port_name} -> {in_port_name}")
                self.connection_broken.emit(out_port_name, in_port_name)
            
            # Emit old signal for compatibility
            self.ports_connected.emit(out_port_name, in_port_name, are_connected)
            self.graph_updated.emit() # Also signal general graph update

        except jack.JackError as e:
            print(f"JACK error in port_connect_callback: {e}")
            self.graph_updated.emit() # Fallback
        except AttributeError as e:
            print(f"AttributeError in port_connect_callback. Port A: '{getattr(port_a, 'name', 'N/A')}', Port B: '{getattr(port_b, 'name', 'N/A')}'. Error: {e}")
            self.graph_updated.emit() # Fallback
        except Exception as e:
            print(f"Unexpected error in port_connect_callback: {type(e).__name__}: {e}. Ports: A='{getattr(port_a, 'name', 'N/A')}', B='{getattr(port_b, 'name', 'N/A')}'")
            self.graph_updated.emit() # Fallback

    def _handle_shutdown_callback(self, status, reason):
        """
        JACK callback for server shutdown. Runs in JACK's thread.
        Emits jack_shutdown_signal and graph_updated.
        """
        try:
            print(f"JACK server shutdown: status={status}, reason='{reason}'")
            # Potentially set an internal flag to prevent further JACK operations
            # self.client = None # Or some other way to indicate client is gone
            self.jack_shutdown_signal.emit()
            self.graph_updated.emit() # Signal that graph needs to react
        except Exception as e:
            print(f"Error in shutdown_callback: {type(e).__name__}: {e}")
    
    def _on_port_registered(self, port_name: str, is_input: bool):
        """
        Handle port registration events in the Qt main thread.
        
        Args:
            port_name: The name of the port that was registered
            is_input: Whether the port is an input port
        """
        # Check callbacks via UIStateManager
        if not self.ui_state_manager.are_callbacks_enabled():
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
        # Check callbacks via UIStateManager
        if not self.ui_state_manager.are_callbacks_enabled():
            return

        self.refresh_ports(refresh_all=True)
    
    # --- Highlighting methods removed, now handled by HighlightManager ---

    # _highlight_connected_outputs_for_input -> highlight_manager._highlight_connected_outputs_for_input
    # _highlight_connected_inputs_for_output -> highlight_manager._highlight_connected_inputs_for_output
    # _highlight_connected_output_groups_for_input_group -> highlight_manager._highlight_connected_output_groups_for_input_group
    # _highlight_connected_input_groups_for_output_group -> highlight_manager._highlight_connected_input_groups_for_output_group
    # highlight_input -> highlight_manager.highlight_input
    # highlight_output -> highlight_manager.highlight_output
    # highlight_midi_input -> highlight_manager.highlight_midi_input
    # highlight_midi_output -> highlight_manager.highlight_midi_output
    # _highlight_tree_item -> highlight_manager._highlight_tree_item_by_name (internal)
    # _highlight_group_item -> highlight_manager._highlight_group_item (internal)
    # clear_highlights -> highlight_manager.clear_highlights
    # clear_midi_highlights -> highlight_manager.clear_midi_highlights
    # _clear_tree_highlights -> highlight_manager._clear_tree_highlights (internal)
    # highlight_drop_target_item -> highlight_manager.highlight_drop_target_item
    # clear_drop_target_highlight -> highlight_manager.clear_drop_target_highlight
    # _get_ports_in_group -> highlight_manager._get_ports_in_group (internal)

    # --- Port Click Handling Moved to InteractionManager ---
    # on_input_clicked, on_midi_input_clicked, on_output_clicked,
    # on_midi_output_clicked, _on_port_clicked methods removed.
    # Signals are now connected directly to interaction_manager.handle_port_click
    # in __init__.

    # --- Methods now delegated to JackConnectionHandler ---

    def make_connection(self, output_name, input_name):
        """Make an audio connection (delegated)."""
        self.jack_handler.make_connection(output_name, input_name)

    def make_midi_connection(self, output_name, input_name):
        """Make a MIDI connection (delegated)."""
        self.jack_handler.make_midi_connection(output_name, input_name)

    def break_connection(self, output_name, input_name):
        """Break an audio connection (delegated)."""
        self.jack_handler.break_connection(output_name, input_name)

    def break_midi_connection(self, output_name, input_name):
        """Break a MIDI connection (delegated)."""
        self.jack_handler.break_midi_connection(output_name, input_name)

    # _port_operation is now internal to JackConnectionHandler

            # --- Methods using the handler ---
        
    def make_connection_selected(self):
        """Connects selected items using the handler."""
        selected_input_items = self.input_tree.selectedItems()
        selected_output_items = self.output_tree.selectedItems()

        # Get all ports from selected items (handles both ports and groups)
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            print("Make Connection: Select at least one input and one output item (port or group).")
            return

        print(f"Making connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        # Use handler's make_multiple_connections
        self.jack_handler.make_multiple_connections(selected_outputs, selected_inputs)

    def make_midi_connection_selected(self):
        """Connects selected MIDI items using the handler."""
        selected_input_items = self.midi_input_tree.selectedItems()
        selected_output_items = self.midi_output_tree.selectedItems()

        # Get all ports from selected items (handles both ports and groups)
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            print("Make MIDI Connection: Select at least one input and one output item (port or group).")
            return

        print(f"Making MIDI connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        # Use handler's make_multiple_connections
        self.jack_handler.make_multiple_connections(selected_outputs, selected_inputs)

    def break_connection_selected(self):
        """Disconnects selected audio items using the handler."""
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            print("Break Connection: Select at least one input and one output port.")
            return

        print(f"Breaking connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                # Use handler's break_connection
                self.jack_handler.break_connection(out_port, in_port)

    def break_midi_connection_selected(self):
        """Disconnects selected MIDI items using the handler."""
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            print("Break MIDI Connection: Select at least one input and one output MIDI port.")
            return

        print(f"Breaking MIDI connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                # Use handler's break_midi_connection
                self.jack_handler.break_midi_connection(out_port, in_port)

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
        """Connects multiple ports (delegated)."""
        self.jack_handler.make_multiple_connections(outputs, inputs)

    def update_connection_buttons(self):
        """Update the state of the audio connection buttons using the handler."""
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
            
            # 2. Determine existing connections using the handler
            existing_connections = self.jack_handler._get_existing_connections_between(selected_output_ports, selected_input_ports)

            # 3. Enable Connect if there are possible connections that don't already exist.
            if len(possible_connections) > 0 and possible_connections != existing_connections:
                can_connect = True
            
            # 4. Enable Disconnect if there are any existing connections
            if len(existing_connections) > 0:
                can_disconnect = True
        
        connect_button.setEnabled(can_connect)
        disconnect_button.setEnabled(can_disconnect)

    # _get_existing_connections_between is now internal to JackConnectionHandler

    def update_undo_redo_buttons(self):
        """Update the state of the undo and redo buttons."""
        # Check if buttons exist before enabling/disabling
        if hasattr(self, 'undo_button') and self.undo_button:
            self.undo_button.setEnabled(self.connection_history.can_undo())
        if hasattr(self, 'redo_button') and self.redo_button:
            self.redo_button.setEnabled(self.connection_history.can_redo())

    # --- Action/Shortcut Setup and Handlers Moved to ActionManager ---
    # def _setup_actions(self): ...
    # def setup_shortcuts(self): ...
    # def _handle_connect_shortcut(self): ...
    # def _handle_disconnect_shortcut(self): ...
    # def undo_action(self): ... (Now handled by ActionManager._handle_undo)
    # def redo_action(self): ... (Now handled by ActionManager._handle_redo)
    # def _handle_collapse_all_shortcut(self): ... (Handled via checkbox toggle -> UIStateManager)
    # def _handle_auto_refresh_shortcut(self): ... (Handled via checkbox toggle -> UIStateManager)
    # def _get_focused_tree_widget(self): ... (Moved to ActionManager)
    # def _handle_move_group_up(self): ... (Moved to ActionManager)
    # def _handle_move_group_down(self): ... (Moved to ActionManager)
    # def _switch_focus_between_trees(self, forwards=True): ... (Moved to ActionManager)
    # def _get_connected_ports(self, port_names, is_input_to_output=True, is_midi=False): ... (Moved to ActionManager)
    # --- End of Moved Methods ---

    def disconnect_node(self, node_name):
        """Disconnect all connections for a port (delegated)."""
        self.jack_handler.disconnect_node(node_name)

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
            # Use the handler's disconnect_node method
            self.jack_handler.disconnect_node(port_name)

    def closeEvent(self, event):
        """
        Handle window closing behavior.
        
        Args:
            event: The close event
        """
        # Always quit the application when the window is closed
        event.accept()
        QApplication.quit()
        
        # Clean up UIStateManager (stops its timers etc.)
        if hasattr(self, 'ui_state_manager'):
            self.ui_state_manager.cleanup()

        # Clean up JACK client and deactivate callbacks
        if hasattr(self, 'client'):
            # self.callbacks_enabled = False # State managed by UIStateManager
            self.client.deactivate()
            self.client.close()
        
        # Stop the visualization refresh timers
        self.connection_view.stop_refresh_timer()
        self.midi_connection_view.stop_refresh_timer()
        
        # Stop pw-top monitor before closing
        if hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
            self.pwtop_monitor.stop()

        # Ensure graph node positions are saved before stopping its handler
        # REMOVED: Saving on exit is no longer desired. States are saved immediately on change.
        # if hasattr(self, 'graph_main_window') and self.graph_main_window and \
        #    hasattr(self.graph_main_window, 'scene') and self.graph_main_window.scene and \
        #    hasattr(self.graph_main_window, 'view') and self.graph_main_window.view:
        #     print("JackConnectionManager.closeEvent: Saving graph node states and zoom...")
        #     current_graph_zoom = self.graph_main_window.view.get_zoom_level()
        #     print(f"JackConnectionManager.closeEvent: Retrieved graph_zoom_level = {current_graph_zoom}") # DEBUG
        #     self.graph_main_window.scene.save_node_states(graph_zoom_level=current_graph_zoom)
        # elif hasattr(self, 'graph_main_window') and self.graph_main_window and \
        #      hasattr(self.graph_main_window, 'scene') and self.graph_main_window.scene:
        #     # Fallback if view is not available for some reason, save without zoom
        #     print("JackConnectionManager.closeEvent: Saving graph node states (view not found, zoom not saved)...")
        #     self.graph_main_window.scene.save_node_states()


        # Stop graph_jack_handler before closing
        if hasattr(self, 'graph_jack_handler') and self.graph_jack_handler:
            print("Stopping Graph JackHandler on close...")
            self.graph_jack_handler.stop()
            # MainWindow.closeEvent for graph also calls stop, but good to be explicit.
        
        # Stop latency test process before closing
        if hasattr(self, 'latency_tester') and self.latency_tester is not None:
            self.latency_tester.stop_latency_test()

    def _get_current_connections(self):
        """Gets current connections (delegated)."""
        # This method is primarily used by PresetHandler, which will need updating
        # For now, just delegate the call.
        return self.jack_handler._get_current_connections()

    def notify_connection_history_changed(self):
        """
        Notifies that the connection history has changed, so UI elements
        like the Graph tab's undo/redo buttons can be updated.
        """
        # Update the main undo/redo buttons
        self.update_undo_redo_buttons()

        # Update the graph tab's undo/redo buttons if the graph_main_window exists
        if hasattr(self, 'graph_main_window') and self.graph_main_window:
            if hasattr(self.graph_main_window, '_update_graph_undo_redo_buttons_state'):
                self.graph_main_window._update_graph_undo_redo_buttons_state()

    @pyqtSlot()
    def toggle_graph_fullscreen(self):
        """Toggles native fullscreen mode and hides UI chrome for the graph tab."""
        if not hasattr(self, 'tab_widget') or not hasattr(self, 'graph_tab_widget'):
            print("Error: Tab widget or graph_tab_widget not found.")
            return

        # Ensure this action is only for the graph tab, which should be at index 2
        # The signal comes from the graph view, implying it has focus, so its tab should be active.
        if self.tab_widget.widget(2) != self.graph_tab_widget or self.tab_widget.currentWidget() != self.graph_tab_widget:
            print("Graph fullscreen toggle requested, but graph tab is not active or not found at index 2.")
            return

        self._graph_is_fullscreen = not self._graph_is_fullscreen

        components_to_manage = []
        if self.menuBar():
            components_to_manage.append(self.menuBar())
        if self.statusBar():
            components_to_manage.append(self.statusBar())
        
        # Add QMainWindow's direct toolbars
        for toolbar in self.findChildren(QToolBar):
            if toolbar.parent() == self:
                components_to_manage.append(toolbar)

        if hasattr(self.tab_widget, 'tabBar'):
            components_to_manage.append(self.tab_widget.tabBar())

        if self._graph_is_fullscreen:
            self._widgets_original_visibility.clear() # Clear before populating

            # Store visibility of chrome widgets and hide them
            for widget in components_to_manage:
                if widget: # Ensure widget exists
                    self._widgets_original_visibility[widget] = widget.isVisible()
                    widget.hide()
            
            # Hide the standard bottom controls panel
            self.show_bottom_controls(False)
            
            # Store enabled state of other tabs and disable them
            for i in range(self.tab_widget.count()):
                tab_page_widget = self.tab_widget.widget(i)
                if tab_page_widget != self.graph_tab_widget:
                    # Ensure we don't overwrite chrome widget states if a tab page somehow is one (highly unlikely)
                    if tab_page_widget not in self._widgets_original_visibility:
                         self._widgets_original_visibility[tab_page_widget] = self.tab_widget.isTabEnabled(i)
                    self.tab_widget.setTabEnabled(i, False)
            
            # Hide internal controls within the graph tab itself
            if hasattr(self, 'graph_main_window') and self.graph_main_window and hasattr(self.graph_main_window, 'toggle_internal_controls'):
                self.graph_main_window.toggle_internal_controls(False)

            # Enter native fullscreen
            self.showFullScreen()

        else: # Exiting fullscreen
            # Exit native fullscreen first
            self.showNormal() # Or self.showMaximized() if you want to restore maximization

            # Show internal controls within the graph tab itself first
            if hasattr(self, 'graph_main_window') and self.graph_main_window and hasattr(self.graph_main_window, 'toggle_internal_controls'):
                self.graph_main_window.toggle_internal_controls(True)

            # Re-evaluate which components were considered chrome widgets for visibility
            chrome_widgets_managed_on_exit = []
            if self.menuBar(): chrome_widgets_managed_on_exit.append(self.menuBar())
            if self.statusBar(): chrome_widgets_managed_on_exit.append(self.statusBar())
            for toolbar in self.findChildren(QToolBar):
                if toolbar.parent() == self: # Only direct toolbars of QMainWindow
                    chrome_widgets_managed_on_exit.append(toolbar)
            if hasattr(self.tab_widget, 'tabBar') and self.tab_widget.tabBar(): # Check tabBar exists
                chrome_widgets_managed_on_exit.append(self.tab_widget.tabBar())

            for item_widget, original_state in self._widgets_original_visibility.items():
                if item_widget in chrome_widgets_managed_on_exit:
                    # This item was a chrome widget; original_state is its visibility
                    if item_widget and original_state: # original_state is True (was visible)
                        item_widget.show()
                else:
                    # This item should be a tab page widget (other than the graph tab)
                    # original_state is its original enabled status
                    tab_index_to_restore = -1
                    for i in range(self.tab_widget.count()):
                        if self.tab_widget.widget(i) == item_widget:
                            tab_index_to_restore = i
                            break
                    
                    # Ensure it's indeed a tab page we stored and not the graph tab itself
                    if tab_index_to_restore != -1 and self.tab_widget.widget(tab_index_to_restore) != self.graph_tab_widget:
                        if original_state: # original_state is True (was enabled)
                            self.tab_widget.setTabEnabled(tab_index_to_restore, True)
            
            self._widgets_original_visibility.clear()
            
            # The visibility of bottom controls is handled by switch_tab when on graph tab.
            # Since we are on the graph tab (index 2), switch_tab ensures show_bottom_controls(False).
            # So, no explicit call to show_bottom_controls is needed here when exiting.

        # Force the main window and graph tab to re-layout to reflect changes.
        if self.centralWidget() and self.centralWidget().layout():
            self.centralWidget().layout().activate()
        if self.graph_tab_widget and self.graph_tab_widget.layout():
            self.graph_tab_widget.layout().activate()
        # self.adjustSize() # May or may not be needed
