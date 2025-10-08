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
from cables import jack_utils # Import the new jack_utils module
from cables.config.config_manager import ConfigManager
from cables.config.enhanced_preset_manager import EnhancedPresetManager
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
from cables.features.mixer import AlsMixerApp # Added import for Alsa Mixer
from cables.features.node_visibility_manager import NodeVisibilityManager

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
        self.preset_manager = EnhancedPresetManager()
        
        # Auto-migrate existing presets to enhanced format if needed
        from cables.utils.preset_migration import auto_migrate_if_needed
        auto_migrate_if_needed()
        
        self.preset_handler = PresetHandler(self)
        
        # Read last active tab from config
        self.last_active_tab = self.config_manager.get_int('last_active_tab', 0)
        
        # Set up the main window
        self.setWindowTitle('Cables')
        # Load window dimensions from config or use app_config defaults
        conn_manager_initial_width = self.config_manager.get_int_setting("CONN_MANAGER_INITIAL_WIDTH", app_config.CONN_MANAGER_INITIAL_WIDTH)
        conn_manager_initial_height = self.config_manager.get_int_setting("CONN_MANAGER_INITIAL_HEIGHT", app_config.CONN_MANAGER_INITIAL_HEIGHT)
        self.setGeometry(app_config.CONN_MANAGER_INITIAL_X, app_config.CONN_MANAGER_INITIAL_Y, conn_manager_initial_width, conn_manager_initial_height)
        self.initial_middle_width = 250
        self.port_type = 'audio'
        
        # Initialize JACK client
        self.client = jack.Client('ConnectionManager')
        self.jack_handler = JackConnectionHandler(self.client, self) # Instantiate handler

        # Initialize connection history
        self.connection_history = ConnectionHistory()
        
        self.flatpak_env = os.path.exists('/.flatpak-info')
        
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()
        
        self.output_filter_edit = QLineEdit()
        self.output_filter_edit.setPlaceholderText("Filter outputs...")
        self.output_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        self.input_filter_edit = QLineEdit()
        self.input_filter_edit.setPlaceholderText("Filter inputs...")
        self.input_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        
        self.client.set_port_registration_callback(self._handle_port_registration)
        self.client.set_client_registration_callback(self._handle_client_registration)
        self.client.set_port_connect_callback(self._handle_port_connect_callback)
        self.client.set_shutdown_callback(self._handle_shutdown_callback)
        
        self.port_registered.connect(self._on_port_registered)
        self.port_unregistered.connect(self._on_port_unregistered)
        
        self.port_manager = PortManager(
            connection_manager=self,
            jack_client=self.client,
            input_filter_edit=self.input_filter_edit,
            output_filter_edit=self.output_filter_edit
        )

        self.ui_elements = {}

        self.action_manager = ActionManager(
            main_window=self,
            connection_handler=self.jack_handler,
            preset_handler=self.preset_handler,
            ui=self.ui_elements
        )
        self._setup_ui()

        self.port_manager.set_trees(
            input_tree=getattr(self, 'input_tree', None),
            output_tree=getattr(self, 'output_tree', None),
            midi_input_tree=getattr(self, 'midi_input_tree', None),
            midi_output_tree=getattr(self, 'midi_output_tree', None)
        )

        self.ui_state_manager = UIStateManager(
            parent=self,
            config_manager=self.config_manager,
            main_window=self,
            auto_refresh_checkbox=self.auto_refresh_checkbox,
            collapse_checkbox=self.collapse_all_checkbox,
            untangle_button=self.untangle_button,
            increase_font_button=self.zoom_in_button,
            decrease_font_button=self.zoom_out_button,
            input_tree=self.input_tree,
            output_tree=self.output_tree,
            midi_input_tree=self.midi_input_tree,
            midi_output_tree=self.midi_output_tree,
            connection_view=self.connection_view,
            midi_connection_view=self.midi_connection_view
        )
        
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

        if hasattr(self, 'tab_widget'):
             self.switch_tab(self.tab_widget.currentIndex())

        self.ui_elements.update({
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
            'graph_main_window': getattr(self, 'graph_main_window', None),
        })
        
        if hasattr(self, 'action_manager') and self.action_manager and hasattr(self, 'ui_state_manager'):
            self.action_manager.complete_setup(state_manager=self.ui_state_manager)

        if hasattr(self, 'undo_button') and self.undo_button and hasattr(self.action_manager, 'global_undo_action') and self.action_manager.global_undo_action:
            self.undo_button.clicked.connect(self.action_manager.global_undo_action.trigger)
        if hasattr(self, 'redo_button') and self.redo_button and hasattr(self.action_manager, 'global_redo_action') and self.action_manager.global_redo_action:
            self.redo_button.clicked.connect(self.action_manager.global_redo_action.trigger)

        if hasattr(self, 'presets_button') and self.presets_button:
            self.presets_button.clicked.connect(self.preset_handler._show_preset_menu)
        if hasattr(self, 'midi_presets_button') and self.midi_presets_button:
            self.midi_presets_button.clicked.connect(self.preset_handler._show_preset_menu)
        
        self.client.activate()
        
        if hasattr(self.action_manager, 'save_preset_action') and self.action_manager.save_preset_action:
            self.action_manager.save_preset_action.setEnabled(bool(self.preset_handler.current_preset_name))

        # Load startup preset if configured
        if self.preset_handler.startup_preset_name and self.preset_handler.startup_preset_name != 'None':
            startup_preset = self.preset_handler.startup_preset_name
            print(f"Loading startup preset '{startup_preset}'...")
            # Load the preset without showing a success message (is_startup=True)
            self.preset_handler._load_selected_preset(startup_preset, is_startup=True)
        
        

        self.interaction_manager = InteractionManager(
            highlight_manager=self.highlight_manager,
            update_connection_buttons_func=self.update_connection_buttons,
            update_midi_connection_buttons_func=self.update_midi_connection_buttons
        )

        if hasattr(self, 'input_tree') and self.input_tree:
            self.input_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.input_tree, False
                )
            )
        if hasattr(self, 'output_tree') and self.output_tree:
            self.output_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.output_tree, False
                )
            )
        if hasattr(self, 'midi_input_tree') and self.midi_input_tree:
            self.midi_input_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.midi_input_tree, True
                )
            )
        if hasattr(self, 'midi_output_tree') and self.midi_output_tree:
            self.midi_output_tree.itemClicked.connect(
                lambda item, col: self.interaction_manager.handle_port_click(
                    item, self.midi_output_tree, True
                )
            )

        # Initialize NodeVisibilityManager
        self.node_visibility_manager = NodeVisibilityManager(self, self.config_manager)
        
        # Pass node visibility manager to port_manager
        if hasattr(self, 'port_manager') and self.port_manager:
            self.port_manager.set_node_visibility_manager(self.node_visibility_manager)

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        self.audio_tab_widget = QWidget()
        self.midi_tab_widget = QWidget()
        self.graph_tab_widget = QWidget()
        self.alsa_mixer_tab_widget = QWidget()
        self.pwtop_tab_widget = QWidget()
        self.latency_tab_widget = QWidget()
        
        self.tab_ui_manager = TabUIManager()
        self.highlight_manager = HighlightManager(
            input_tree=None,
            output_tree=None,
            midi_input_tree=None,
            midi_output_tree=None,
            client=self.client,
            colors={
                'text': self.text_color,
                'background': self.background_color,
                'highlight': self.highlight_color,
                'auto_highlight': self.auto_highlight_color,
                'drag_highlight': self.drag_highlight_color
            }
        )

        self.tab_ui_manager.setup_port_tab(self, self.audio_tab_widget, "Audio", 'audio')
        self.tab_ui_manager.setup_port_tab(self, self.midi_tab_widget, "MIDI", 'midi')
        self.tab_ui_manager.setup_pwtop_tab(self, self.pwtop_tab_widget)
        self.tab_ui_manager.setup_latency_tab(self, self.latency_tab_widget)

        self.highlight_manager.input_tree = self.input_tree
        self.highlight_manager.output_tree = self.output_tree
        self.highlight_manager.midi_input_tree = self.midi_input_tree
        self.highlight_manager.midi_output_tree = self.midi_output_tree

        # New Tab Order:
        # Audio (0), MIDI (1), Graph (2), pw-top (3), Alsa Mixer (4), Latency Test (5)
        self.tab_widget.addTab(self.audio_tab_widget, "Audio") # Index 0
        self.tab_widget.addTab(self.midi_tab_widget, "MIDI")   # Index 1

        self.tab_ui_manager.setup_graph_tab(self, self.graph_tab_widget)
        self.tab_widget.insertTab(2, self.graph_tab_widget, "Graph") # Index 2
        
        self.tab_widget.addTab(self.pwtop_tab_widget, "pw-top") # Index 3
        
        self.alsa_mixer_layout = QVBoxLayout(self.alsa_mixer_tab_widget)
        self.alsa_mixer_app = AlsMixerApp(config_manager=self.config_manager) # Pass ConfigManager
        self.alsa_mixer_layout.addWidget(self.alsa_mixer_app)
        self.tab_widget.insertTab(4, self.alsa_mixer_tab_widget, "ALSA Mixer") # Index 4
        
        self.tab_widget.addTab(self.latency_tab_widget, "Latency Test") # Index 5
 
        if hasattr(self, 'graph_main_window') and self.graph_main_window and \
           hasattr(self.graph_main_window, 'view') and self.graph_main_window.view and \
           hasattr(self.graph_main_window.view, 'fullscreen_request_signal'):
            self.graph_main_window.view.fullscreen_request_signal.connect(self.toggle_graph_fullscreen)
        
        if 0 <= self.last_active_tab < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(self.last_active_tab)
        
        self._setup_bottom_layout(main_layout)
        
        self.tab_widget.currentChanged.connect(self.switch_tab)
        # Set initial state for global zoom actions based on the initially loaded tab
        if hasattr(self, 'tab_widget'):
             self._update_global_zoom_action_state(self.tab_widget.currentIndex())
    
    def _update_global_zoom_action_state(self, current_tab_index):
        """Enable/disable global zoom actions based on the active tab."""
        if not hasattr(self, 'tab_widget') or not hasattr(self, 'action_manager') or \
           not self.action_manager or not hasattr(self, 'alsa_mixer_tab_widget'):
            return

        current_widget = self.tab_widget.widget(current_tab_index)
        is_alsa_mixer_tab_active = (current_widget == self.alsa_mixer_tab_widget)

        if hasattr(self.action_manager, 'zoom_in_action') and self.action_manager.zoom_in_action:
            self.action_manager.zoom_in_action.setEnabled(not is_alsa_mixer_tab_active)
        if hasattr(self.action_manager, 'zoom_out_action') and self.action_manager.zoom_out_action:
            self.action_manager.zoom_out_action.setEnabled(not is_alsa_mixer_tab_active)

    def _setup_bottom_layout(self, main_layout):
        bottom_layout = QHBoxLayout()
        
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        self.auto_refresh_checkbox.setToolTip("Toggle automatic refreshing of ports and connections <span style='color:grey'>Alt+R</span>")
 
        self.collapse_all_checkbox = QCheckBox('Collapse All')
        self.collapse_all_checkbox.setToolTip("Toggle collapse state for all groups <span style='color:grey'>Alt+C</span>")

        self.undo_button = QPushButton('       Undo       ')
        self.undo_button.setToolTip("Undo last connection <span style='color:grey'>Ctrl+Z</span>")
        self.redo_button = QPushButton('       Redo       ')
        self.redo_button.setToolTip("Redo last connection <span style='color:grey'>Shift+Ctrl+Z/Ctrl+Y</span>")
        
        no_hover_style = """
            QPushButton { background-color: palette(button); color: palette(buttonText); }
            QPushButton:hover { background-color: palette(button); color: palette(buttonText); }
        """
        self.undo_button.setStyleSheet(no_hover_style)
        self.redo_button.setStyleSheet(no_hover_style)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        
        filter_style = f"""
            QLineEdit {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                border: 1px solid {self.text_color.name()};
                padding: 2px;
                border-radius: 3px;
            }}
        """
        
        if hasattr(self, 'output_filter_edit'):
            self.output_filter_edit.setStyleSheet(filter_style)
            self.output_filter_edit.setClearButtonEnabled(True)
            self.output_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.output_filter_edit)
        
        bottom_layout.addStretch(1)
        
        self.bottom_refresh_button = QPushButton('     Refresh     ')
        self.bottom_refresh_button.setToolTip("Refresh port list <span style='color:grey'>R</span>")
        self.bottom_refresh_button.setStyleSheet(no_hover_style)
        self.bottom_refresh_button.clicked.connect(self.refresh_ports)
        
        self.untangle_button = QPushButton()
        self.untangle_button.setStyleSheet(no_hover_style)

        bottom_layout.addWidget(self.collapse_all_checkbox)
        bottom_layout.addWidget(self.auto_refresh_checkbox)
        bottom_layout.addWidget(self.bottom_refresh_button)
        bottom_layout.addWidget(self.untangle_button)
        bottom_layout.addWidget(self.undo_button)
        bottom_layout.addWidget(self.redo_button)
        bottom_layout.addStretch(1)
        
        self.zoom_in_button = QPushButton('+')
        self.zoom_in_button.setToolTip("Increase port list font size <span style='color:grey'>Ctrl++</span>")
        self.zoom_in_button.setStyleSheet(no_hover_style)
        zoom_button_size = QSize(25, 25)
        self.zoom_in_button.setFixedSize(zoom_button_size)

        self.zoom_out_button = QPushButton('-')
        self.zoom_out_button.setToolTip("Decrease port list font size <span style='color:grey'>Ctrl+-</span>")
        self.zoom_out_button.setStyleSheet(no_hover_style)
        self.zoom_out_button.setFixedSize(zoom_button_size)

        bottom_layout.addWidget(self.zoom_out_button)
        bottom_layout.addWidget(self.zoom_in_button)
        
        if hasattr(self, 'input_filter_edit'):
            self.input_filter_edit.setStyleSheet(filter_style)
            self.input_filter_edit.setClearButtonEnabled(True)
            self.input_filter_edit.setFixedWidth(150)
            bottom_layout.addWidget(self.input_filter_edit)
        
        main_layout.addLayout(bottom_layout)
        
        current_tab = self.tab_widget.currentIndex() if hasattr(self, 'tab_widget') else 0
        self.show_bottom_controls(current_tab < 2)

    def is_dark_mode(self):
        palette = QApplication.palette()
        return palette.window().color().lightness() < 128
    
    def setup_colors(self):
        if self.dark_mode:
            self.background_color = QColor(24, 26, 33)
            self.text_color = QColor(255, 255, 255)
            self.highlight_color = QColor(20, 62, 104)
            self.button_color = QColor(68, 68, 68)
            self.connection_color = QColor(0, 150, 255)
            self.auto_highlight_color = QColor(255, 200, 0)
            self.drag_highlight_color = QColor(41, 61, 90)
        else:
            self.background_color = QColor(255, 255, 255)
            self.text_color = QColor(0, 0, 0)
            self.highlight_color = QColor(173, 216, 230)
            self.button_color = QColor(240, 240, 240)
            self.connection_color = QColor(0, 100, 200)
            self.auto_highlight_color = QColor(255, 140, 0)
            self.drag_highlight_color = QColor(200, 200, 200)
    
    def list_stylesheet(self):
        highlight_bg = self.highlight_color.name()
        selected_text_color = "#ffffff" if self.dark_mode else "#000000"
        
        return f"""
            QListWidget {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
            }}
            QListWidget::item:selected {{
                background-color: {highlight_bg};
                color: {selected_text_color};
            }}
            QTreeView {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
            }}
            QTreeView::item:selected {{
                background-color: {highlight_bg};
                color: {selected_text_color};
            }}
        """
    
    def button_stylesheet(self):
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
        # New Tab Order:
        # Audio (0), MIDI (1), Graph (2), pw-top (3), Alsa Mixer (4), Latency Test (5)

        # Stop pw-top monitor if switching away from it (pw-top is now index 3)
        if index != 3 and hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
            self.pwtop_monitor.stop()
 
        # Configure based on the new tab index
        if index < 2:  # Audio (0) or MIDI (1) tabs
            self.port_type = 'audio' if index == 0 else 'midi'
            if hasattr(self, 'ui_state_manager'):
                 self.ui_state_manager.apply_collapse_state_to_current_trees()
            self.refresh_visualizations()
            self.show_bottom_controls(True)
        elif index == 2: # Graph tab (index 2)
            self.show_bottom_controls(False)
            # Disable global Alt+U shortcut when Graph tab is active to allow Graph-specific Alt+U handling
            if hasattr(self, 'action_manager') and hasattr(self.action_manager, 'untangle_shortcut_action'):
                self.action_manager.untangle_shortcut_action.setEnabled(False)
            if hasattr(self, 'graph_main_window') and self.graph_main_window:
                if hasattr(self.graph_main_window, 'scene') and self.graph_main_window.scene:
                    self.graph_main_window.scene.full_graph_refresh()
        elif index == 3:  # pw-top tab (index 3)
            if hasattr(self, 'pwtop_monitor') and self.pwtop_monitor is not None:
                self.pwtop_monitor.start()
            self.show_bottom_controls(False)
        elif index == 4: # Alsa Mixer tab (index 4)
            self.show_bottom_controls(False)
            if hasattr(self, 'alsa_mixer_app') and self.alsa_mixer_app:
                # Start ALSA mixer updates only if the window is focused
                if self.isActiveWindow():
                    self.alsa_mixer_app.start_updates()
        elif index == 5:  # Latency Test tab (index 5)
            self.show_bottom_controls(False)
        
        # Stop ALSA mixer updates when switching away from the tab
        if self.last_active_tab == 4 and hasattr(self, 'alsa_mixer_app') and self.alsa_mixer_app:
            self.alsa_mixer_app.stop_updates()

        # Re-enable global Alt+U shortcut when switching away from Graph tab
        if self.last_active_tab == 2:  # Was previously on Graph tab
            if hasattr(self, 'action_manager') and hasattr(self.action_manager, 'untangle_shortcut_action'):
                self.action_manager.untangle_shortcut_action.setEnabled(True)

        self.last_active_tab = index
        self.config_manager.set_int('last_active_tab', index)

        # Update global zoom action enabled state
        self._update_global_zoom_action_state(index)
 
        if hasattr(self, 'ui_state_manager') and self.ui_state_manager:
             self.ui_state_manager._update_refresh_timer_interval()
    
    def show_bottom_controls(self, visible):
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
    
    def refresh_visualizations(self):
        if self.port_type == 'audio':
            self.update_connections()
        else:
            self.update_midi_connections()
    
    def _refresh_single_port_type(self, port_type_to_refresh):
        if port_type_to_refresh == 'audio':
            input_tree = self.input_tree
            output_tree = self.output_tree
            update_visuals = self.update_connections
            update_buttons = self.update_connection_buttons
            is_midi = False
        elif port_type_to_refresh == 'midi':
            input_tree = self.midi_input_tree
            output_tree = self.midi_output_tree
            update_visuals = self.update_midi_connections
            update_buttons = self.update_midi_connection_buttons
            is_midi = True
        else:
            print(f"Warning: Invalid port_type '{port_type_to_refresh}' passed to _refresh_single_port_type")
            return
        
        current_input_filter = self.input_filter_edit.text() if hasattr(self, 'input_filter_edit') else ""
        current_output_filter = self.output_filter_edit.text() if hasattr(self, 'output_filter_edit') else ""
        
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
            self.highlight_manager.apply_highlights_for_selection(restored_input_item, input_tree, is_midi)

        if restored_output_item:
            if restored_output_item != restored_input_item:
                 self.highlight_manager.apply_highlights_for_selection(restored_output_item, output_tree, is_midi)

        if self.port_type == port_type_to_refresh:
            self.ui_state_manager.apply_collapse_state_to_current_trees()
    
    def refresh_ports(self, refresh_all=False, from_shortcut=False):
        if from_shortcut:
            self._animate_button_press(self.bottom_refresh_button)
        
        if refresh_all:
            self._refresh_single_port_type('audio')
            self._refresh_single_port_type('midi')
        else:
            self._refresh_single_port_type(self.port_type)
        
        # Apply node visibility settings after refreshing ports
        if hasattr(self, 'node_visibility_manager') and self.node_visibility_manager:
            self.node_visibility_manager.apply_visibility_settings()
    
    def _get_selected_item_info(self, tree_widget):
        if not hasattr(tree_widget, 'currentItem'):
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
    
    def _restore_selection(self, tree_widget, selection_info):
        if not selection_info or not hasattr(tree_widget, 'port_items'):
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
    
    def start_startup_refresh(self):
        self.startup_refresh_count = 0
        self.startup_refresh_timer = QTimer()
        self.startup_refresh_timer.timeout.connect(self.startup_refresh)
        self.startup_refresh_timer.start(1)
    
    def startup_refresh(self):
        original_port_type = self.port_type
        
        self.port_type = 'audio'
        self.refresh_ports()
        
        self.port_type = 'midi'
        self.refresh_ports()
        
        self.port_type = original_port_type
        
        self.refresh_visualizations()
        
        self.startup_refresh_count += 1
        if self.startup_refresh_count >= 3:
            self.startup_refresh_timer.stop()
            
            self.ui_state_manager.apply_collapse_state_to_all_trees(
                collapse=self.ui_state_manager.collapse_checkbox.isChecked()
            )

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.ActivationChange:
            is_focused = self.isActiveWindow()
            if hasattr(self, 'ui_state_manager'):
                 self.ui_state_manager.handle_focus_change(is_focused)

            # Manage ALSA mixer updates based on focus and active tab
            if hasattr(self, 'tab_widget') and hasattr(self, 'alsa_mixer_tab_widget') and hasattr(self, 'alsa_mixer_app'):
                current_tab_index = self.tab_widget.currentIndex()
                current_widget = self.tab_widget.widget(current_tab_index)
                is_alsa_mixer_tab_active = (current_widget == self.alsa_mixer_tab_widget)

                if is_alsa_mixer_tab_active:
                    if is_focused:
                        self.alsa_mixer_app.start_updates()
                    else:
                        self.alsa_mixer_app.stop_updates()

    def _animate_button_press(self, button):
        if not button:
            return
        
        original_style = button.styleSheet()
        
        if "inset" in original_style:
            return
        
        pressed_style = f"""
            QPushButton {{
                background-color: {self.highlight_color.name()};
                color: {self.text_color.name()};
                border: 2px inset {self.highlight_color.darker(120).name()};
            }}
        """
        button.setStyleSheet(pressed_style)
        
        QTimer.singleShot(150, lambda: button.setStyleSheet(original_style))
    
    def _handle_port_registration(self, port, register: bool):
        try:
            if port is None:
                return
            
            port_name_str = None
            client_name_str = "UnknownClient"
            port_flags_val = 0
            port_type_str = "UnknownType"
            is_input_val = False

            if not hasattr(port, 'name') or not hasattr(port, '_client') or \
               (hasattr(port, '_client') and not hasattr(port._client, 'name')) or \
               not hasattr(port, 'is_input'):
                print(f"Port registration callback: Port object missing critical attributes (name, _client, _client.name, or is_input). Port: {port}")
                self.graph_updated.emit()
                return

            try:
                port_name_str = port.name
                if not isinstance(port_name_str, str) or not port_name_str:
                    print(f"Port registration callback: Invalid port name. Port: {port}")
                    self.graph_updated.emit()
                    return

                if ':' in port.name:
                    client_name_str = port.name.split(':', 1)[0]
                else:
                    client_name_str = port.name
                
                try:
                    port_flags_val = port.flags
                except AttributeError:
                    port_flags_val = 0

                try:
                    port_type_str = port.type
                except AttributeError:
                    if port.is_midi:
                        port_type_str = "midi"
                    elif port.is_audio:
                        port_type_str = "audio"
                    else:
                        port_type_str = "unknown"
                
                is_input_val = port.is_input

            except Exception as ex_attrs:
                print(f"Port registration callback: Error accessing critical port attributes for '{getattr(port, 'name', 'N/A')}': {ex_attrs}")
                self.graph_updated.emit()
                return

            if register:
                self.port_added.emit(port_name_str, client_name_str, port_flags_val, port_type_str, is_input_val)
                self.port_registered.emit(port_name_str, is_input_val)
            else:
                self.port_removed.emit(port_name_str, client_name_str)
                self.port_unregistered.emit(port_name_str, is_input_val)
            
            self.graph_updated.emit()
        except Exception as e:
            print(f"Port registration callback error: {type(e).__name__}: {e}")
            self.graph_updated.emit()

    def _handle_client_registration(self, client_name: str, register: bool):
        try:
            if not isinstance(client_name, str) or not client_name:
                print(f"Client registration callback: Invalid client_name '{client_name}'.")
                self.graph_updated.emit()
                return

            print(f"Client {'added' if register else 'removed'}: {client_name}")
            if register:
                self.client_added.emit(client_name)
            else:
                self.client_removed.emit(client_name)
            
            self.client_registered.emit(client_name, register)
            self.graph_updated.emit()
        except Exception as e:
            print(f"Client registration callback error: {type(e).__name__}: {e}")
            self.graph_updated.emit()

    def _handle_port_connect_callback(self, port_a: jack.Port, port_b: jack.Port, are_connected: bool):
        try:
            if not port_a or not hasattr(port_a, 'name') or \
               not port_b or not hasattr(port_b, 'name') or \
               not hasattr(port_a, 'is_output') or not hasattr(port_b, 'is_input'):
                print(f"Port connect callback: Invalid port objects or missing attributes. Port A: {port_a}, Port B: {port_b}")
                self.graph_updated.emit()
                return

            port_a_name = port_a.name
            port_b_name = port_b.name

            out_port_name, in_port_name = "", ""
            if port_a.is_output and port_b.is_input:
                out_port_name, in_port_name = port_a_name, port_b_name
            elif port_b.is_output and port_a.is_input:
                out_port_name, in_port_name = port_b_name, port_a_name
            else:
                print(f"Port connect callback: Ambiguous port types for {port_a_name} (is_output={port_a.is_output}) and {port_b_name} (is_input={port_b.is_input}). Refreshing graph.")
                self.graph_updated.emit()
                return

            if are_connected:
                print(f"Connection made: {out_port_name} -> {in_port_name}")
                self.connection_made.emit(out_port_name, in_port_name)
            else:
                print(f"Connection broken: {out_port_name} -> {in_port_name}")
                self.connection_broken.emit(out_port_name, in_port_name)
            
            self.ports_connected.emit(out_port_name, in_port_name, are_connected)
            self.graph_updated.emit()

        except jack.JackError as e:
            print(f"JACK error in port_connect_callback: {e}")
            self.graph_updated.emit()
        except AttributeError as e:
            print(f"AttributeError in port_connect_callback. Port A: '{getattr(port_a, 'name', 'N/A')}', Port B: '{getattr(port_b, 'name', 'N/A')}'. Error: {e}")
            self.graph_updated.emit()
        except Exception as e:
            print(f"Unexpected error in port_connect_callback: {type(e).__name__}: {e}. Ports: A='{getattr(port_a, 'name', 'N/A')}', B='{getattr(port_b, 'name', 'N/A')}'")
            self.graph_updated.emit()

    def _handle_shutdown_callback(self, status, reason):
        try:
            print(f"JACK server shutdown: status={status}, reason='{reason}'")
            self.jack_shutdown_signal.emit()
            self.graph_updated.emit()
        except Exception as e:
            print(f"Error in shutdown_callback: {type(e).__name__}: {e}")
    
    def _on_port_registered(self, port_name: str, is_input: bool):
        if not self.ui_state_manager.are_callbacks_enabled():
            return

        if (hasattr(self, 'latency_tester') and self.latency_tester is not None and
            (port_name == "jack_delay:in" or port_name == "jack_delay:out")):
            print(f"Detected registration of {port_name}, attempting latency auto-connection via LatencyTester...")
            QTimer.singleShot(50, self.latency_tester._attempt_latency_auto_connection)
        
        self.refresh_ports(refresh_all=True)
    
    def _on_port_unregistered(self, port_name: str, is_input: bool):
        if not self.ui_state_manager.are_callbacks_enabled():
            return
        self.refresh_ports(refresh_all=True)
    
    def make_connection(self, output_name, input_name):
        self.jack_handler.make_connection(output_name, input_name)

    def make_midi_connection(self, output_name, input_name):
        self.jack_handler.make_midi_connection(output_name, input_name)

    def break_connection(self, output_name, input_name):
        self.jack_handler.break_connection(output_name, input_name)

    def break_midi_connection(self, output_name, input_name):
        self.jack_handler.break_midi_connection(output_name, input_name)
        
    def make_connection_selected(self):
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            print("Make Connection: Select at least one input and one output item (port or group).")
            return

        print(f"Making connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        self.jack_handler.make_multiple_connections(selected_outputs, selected_inputs)

    def make_midi_connection_selected(self):
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            print("Make MIDI Connection: Select at least one input and one output item (port or group).")
            return

        print(f"Making MIDI connections (button): Outputs={selected_outputs}, Inputs={selected_inputs}")
        self.jack_handler.make_multiple_connections(selected_outputs, selected_inputs)

    def break_connection_selected(self):
        selected_inputs = self._get_ports_from_selected_items(self.input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.output_tree)

        if not selected_inputs or not selected_outputs:
            print("Break Connection: Select at least one input and one output port.")
            return

        print(f"Breaking connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                self.jack_handler.break_connection(out_port, in_port)

    def break_midi_connection_selected(self):
        selected_inputs = self._get_ports_from_selected_items(self.midi_input_tree)
        selected_outputs = self._get_ports_from_selected_items(self.midi_output_tree)

        if not selected_inputs or not selected_outputs:
            print("Break MIDI Connection: Select at least one input and one output MIDI port.")
            return

        print(f"Breaking MIDI connections for: Outputs={selected_outputs}, Inputs={selected_inputs}")
        for out_port in selected_outputs:
            for in_port in selected_inputs:
                self.jack_handler.break_midi_connection(out_port, in_port)

    def _get_ports_from_selected_items(self, tree_widget):
        port_names = set()
        for item in tree_widget.selectedItems():
            if not item:
                continue
            
            if item.childCount() == 0:
                port_name = item.data(0, Qt.ItemDataRole.UserRole)
                if port_name:
                    port_names.add(port_name)
            else:
                for i in range(item.childCount()):
                    child = item.child(i)
                    port_name = child.data(0, Qt.ItemDataRole.UserRole)
                    if port_name:
                        port_names.add(port_name)
        return list(port_names)

    def make_multiple_connections(self, outputs, inputs):
        self.jack_handler.make_multiple_connections(outputs, inputs)

    def update_connection_buttons(self):
        self._update_port_connection_buttons(self.input_tree, self.output_tree,
                                           self.connect_button, self.disconnect_button)
    
    def update_midi_connection_buttons(self):
        self._update_port_connection_buttons(self.midi_input_tree, self.midi_output_tree,
                                           self.midi_connect_button, self.midi_disconnect_button)
    
    def _update_port_connection_buttons(self, input_tree, output_tree, connect_button, disconnect_button):
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
            
            existing_connections = self.jack_handler._get_existing_connections_between(selected_output_ports, selected_input_ports)

            if len(possible_connections) > 0 and possible_connections != existing_connections:
                can_connect = True
            
            if len(existing_connections) > 0:
                can_disconnect = True
        
        connect_button.setEnabled(can_connect)
        disconnect_button.setEnabled(can_disconnect)

    def update_undo_redo_buttons(self):
        if hasattr(self, 'undo_button') and self.undo_button:
            self.undo_button.setEnabled(self.connection_history.can_undo())
        if hasattr(self, 'redo_button') and self.redo_button:
            self.redo_button.setEnabled(self.connection_history.can_redo())

    def disconnect_node(self, node_name):
        self.jack_handler.disconnect_node(node_name)

    def increase_font_size(self):
        max_size = 24
        if self.port_list_font_size < max_size:
            self.port_list_font_size += 1
            self.config_manager.set_str('port_list_font_size', str(self.port_list_font_size))
            self._apply_port_list_font_size()
            print(f"Port list font size increased to: {self.port_list_font_size}")
    
    def decrease_font_size(self):
        min_size = 6
        if self.port_list_font_size > min_size:
            self.port_list_font_size -= 1
            self.config_manager.set_str('port_list_font_size', str(self.port_list_font_size))
            self._apply_port_list_font_size()
            print(f"Port list font size decreased to: {self.port_list_font_size}")
    
    def _apply_port_list_font_size(self):
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
        
        self.refresh_visualizations()
    
    def update_connections(self):
        self._update_connection_graphics(self.connection_scene, self.connection_view,
                                        self.output_tree, self.input_tree, is_midi=False)
    
    def update_midi_connections(self):
        self._update_connection_graphics(self.midi_connection_scene, self.midi_connection_view,
                                        self.midi_output_tree, self.midi_input_tree, is_midi=True)
    
    def _update_connection_graphics(self, scene, view, output_tree, input_tree, is_midi):
        scene.clear()
        view_rect = view.rect()
        scene_rect = QRectF(0, 0, view_rect.width(), view_rect.height())
        scene.setSceneRect(scene_rect)
        
        connections = []
        try:
            relevant_output_ports: list[jack.Port] = []
            if is_midi:
                relevant_output_ports = jack_utils.get_all_jack_ports(self.client, is_output=True, is_midi=True)
            else:
                relevant_output_ports = jack_utils.get_all_jack_ports(self.client, is_output=True, is_audio=True)

            for output_port_obj in relevant_output_ports:
                port_connections = jack_utils.get_all_jack_connections(self.client, output_port_obj)
                connections.extend(port_connections)

        except jack.JackError as e:
            print(f"Error getting connections via jack_utils: {e}")
            return
        
        for output_name, input_name in connections:
            start_pos = self.get_port_position(output_tree, output_name, view)
            end_pos = self.get_port_position(input_tree, input_name, view)
            
            if start_pos and end_pos:
                path = QPainterPath()
                path.moveTo(start_pos)
                
                ctrl1_x = start_pos.x() + (end_pos.x() - start_pos.x()) / 3
                ctrl2_x = start_pos.x() + 2 * (end_pos.x() - start_pos.x()) / 3
                
                path.cubicTo(
                    QPointF(ctrl1_x, start_pos.y()),
                    QPointF(ctrl2_x, end_pos.y()),
                    end_pos
                )
                
                base_name = output_name.rsplit(':', 1)[0]
                
                random.seed(base_name)
                base_color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                
                if self.dark_mode:
                    h, s, v, a = base_color.getHsvF()
                    s = min(1.0, s * 1.4)
                    v = min(1.0, v * 1.3)
                    base_color.setHsvF(h, s, v, a)
                
                pen = QPen(base_color, 2)
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                scene.addItem(path_item)
        
        view.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def get_port_position(self, tree_widget, port_name, connection_view):
        port_item = tree_widget.port_items.get(port_name)
        if not port_item:
            return None
        
        parent_group = port_item.parent()
        if not parent_group:
            return None
        
        is_expanded = parent_group.isExpanded()
        
        target_item = port_item if is_expanded else parent_group
        
        rect = tree_widget.visualItemRect(target_item)
        
        if rect.height() <= 0:
            return None
        
        is_output = tree_widget in (self.output_tree, self.midi_output_tree)
        
        point = QPointF(tree_widget.viewport().width() if is_output else 0,
                       rect.top() + rect.height() / 2)
        
        viewport_point = tree_widget.viewport().mapToParent(point.toPoint())
        global_point = tree_widget.mapToGlobal(viewport_point)
        scene_point = connection_view.mapFromGlobal(global_point)
        return connection_view.mapToScene(scene_point)
    
    def disconnect_selected_groups(self, group_items):
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

    

    

    def _get_current_connections(self):
        return self.jack_handler._get_current_connections()

    def notify_connection_history_changed(self):
        self.update_undo_redo_buttons()

        if hasattr(self, 'graph_main_window') and self.graph_main_window:
            if hasattr(self.graph_main_window, '_update_graph_undo_redo_buttons_state'):
                self.graph_main_window._update_graph_undo_redo_buttons_state()

    @pyqtSlot()
    def toggle_graph_fullscreen(self):
        if not hasattr(self, 'tab_widget') or not hasattr(self, 'graph_tab_widget'):
            print("Error: Tab widget or graph_tab_widget not found.")
            return
 
        # Ensure this action is only for the graph tab, which should be at index 2 (new index)
        if self.tab_widget.widget(2) != self.graph_tab_widget or self.tab_widget.currentWidget() != self.graph_tab_widget: # Graph is now index 2
            print("Graph fullscreen toggle requested, but graph tab is not active or not found at index 2.")
            return
 
        self._graph_is_fullscreen = not self._graph_is_fullscreen

        components_to_manage = []
        if self.menuBar():
            components_to_manage.append(self.menuBar())
        if self.statusBar():
            components_to_manage.append(self.statusBar())
        
        for toolbar in self.findChildren(QToolBar):
            if toolbar.parent() == self:
                components_to_manage.append(toolbar)

        if hasattr(self.tab_widget, 'tabBar'):
            components_to_manage.append(self.tab_widget.tabBar())

        if self._graph_is_fullscreen:
            self._widgets_original_visibility.clear()

            for widget in components_to_manage:
                if widget:
                    self._widgets_original_visibility[widget] = widget.isVisible()
                    widget.hide()
            
            self.show_bottom_controls(False)
            
            for i in range(self.tab_widget.count()):
                tab_page_widget = self.tab_widget.widget(i)
                if tab_page_widget != self.graph_tab_widget:
                    if tab_page_widget not in self._widgets_original_visibility:
                         self._widgets_original_visibility[tab_page_widget] = self.tab_widget.isTabEnabled(i)
                    self.tab_widget.setTabEnabled(i, False)
            
            if hasattr(self, 'graph_main_window') and self.graph_main_window and hasattr(self.graph_main_window, 'toggle_internal_controls'):
                self.graph_main_window.toggle_internal_controls(False)

            self.showFullScreen()

        else: 
            self.showNormal()

            if hasattr(self, 'graph_main_window') and self.graph_main_window and hasattr(self.graph_main_window, 'toggle_internal_controls'):
                self.graph_main_window.toggle_internal_controls(True)

            chrome_widgets_managed_on_exit = []
            if self.menuBar(): chrome_widgets_managed_on_exit.append(self.menuBar())
            if self.statusBar(): chrome_widgets_managed_on_exit.append(self.statusBar())
            for toolbar in self.findChildren(QToolBar):
                if toolbar.parent() == self:
                    chrome_widgets_managed_on_exit.append(toolbar)
            if hasattr(self.tab_widget, 'tabBar') and self.tab_widget.tabBar():
                chrome_widgets_managed_on_exit.append(self.tab_widget.tabBar())

            for item_widget, original_state in self._widgets_original_visibility.items():
                if item_widget in chrome_widgets_managed_on_exit:
                    if item_widget and original_state:
                        item_widget.show()
                else:
                    tab_index_to_restore = -1
                    for i in range(self.tab_widget.count()):
                        if self.tab_widget.widget(i) == item_widget:
                            tab_index_to_restore = i
                            break
                    
                    if tab_index_to_restore != -1 and self.tab_widget.widget(tab_index_to_restore) != self.graph_tab_widget:
                        if original_state:
                            self.tab_widget.setTabEnabled(tab_index_to_restore, True)
            
            self._widgets_original_visibility.clear()
            
        if self.centralWidget() and self.centralWidget().layout():
            self.centralWidget().layout().activate()
        if self.graph_tab_widget and self.graph_tab_widget.layout():
            self.graph_tab_widget.layout().activate()

    def show_node_visibility_dialog(self):
        """Show the node visibility configuration dialog."""
        if hasattr(self, 'node_visibility_manager') and self.node_visibility_manager:
            self.node_visibility_manager.show_configuration_dialog(self)
            
            # After dialog closes, pass node visibility manager to graph_main_window.scene if needed
            if hasattr(self, 'graph_main_window') and self.graph_main_window:
                if hasattr(self.graph_main_window, 'scene') and self.graph_main_window.scene:
                    self.graph_main_window.scene.set_node_visibility_manager(self.node_visibility_manager)
                    # Refresh the graph view
                    self.graph_main_window.scene.full_graph_refresh()
