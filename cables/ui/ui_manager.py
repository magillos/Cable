#!/usr/bin/env python3
"""
UI Manager for Cables JACK/PipeWire connection manager.
Handles all UI setup, styling, and widget management.
"""

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QCheckBox, QPushButton, QLineEdit, QSizePolicy, QSpacerItem, QMainWindow
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont

from cables.ui.tab_ui_manager import TabUIManager


class UIManager:
    """
    Manages all UI-related functionality for the Cables application.

    This class handles:
    - Color scheme setup and management
    - Widget creation and layout setup
    - Styling of UI components
    - Main window UI initialization
    """

    def __init__(self, main_window: QMainWindow, config_manager):
        """
        Initialize the UI Manager.

        Args:
            main_window: The main application window
            config_manager: Configuration manager for settings
        """
        self.main_window = main_window
        self.config_manager = config_manager

        # Initialize color scheme
        self.dark_mode = self.is_dark_mode()
        self.setup_colors()

        # Initialize filter widgets
        self.output_filter_edit = QLineEdit()
        self.output_filter_edit.setPlaceholderText("Filter outputs...")
        self.output_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        self.output_filter_edit.setClearButtonEnabled(True)
        self.input_filter_edit = QLineEdit()
        self.input_filter_edit.setPlaceholderText("Filter inputs...")
        self.input_filter_edit.setToolTip("Use '-' prefix for exclusive filtering")
        self.input_filter_edit.setClearButtonEnabled(True)

        # Tab widget and manager
        self.tab_widget = QTabWidget()
        self.tab_ui_manager = TabUIManager()

        # Widget references (to be set during setup)
        self.auto_refresh_checkbox = None
        self.collapse_all_checkbox = None
        self.undo_button = None
        self.redo_button = None
        self.bottom_refresh_button = None
        self.untangle_button = None
        self.zoom_in_button = None
        self.zoom_out_button = None

        # Tree and view references (set by connection manager)
        self.input_tree = None
        self.output_tree = None
        self.midi_input_tree = None
        self.midi_output_tree = None
        self.connection_view = None
        self.midi_connection_view = None
        self.graph_main_window = None

    def is_dark_mode(self):
        """Determine if the system is in dark mode."""
        palette = QApplication.palette()
        return palette.window().color().lightness() < 128

    def setup_colors(self):
        """Set up the color scheme based on dark/light mode."""
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
        """Get stylesheet for lists and trees."""
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
        """Get stylesheet for buttons."""
        return f"""
            QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
            QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
        """

    def get_filter_stylesheet(self):
        """Get stylesheet for filter input fields."""
        return f"""
            QLineEdit {{
                background-color: {self.background_color.name()};
                color: {self.text_color.name()};
                border: 1px solid {self.text_color.name()};
                padding: 2px;
                border-radius: 3px;
            }}
        """

    def get_no_hover_button_stylesheet(self):
        """Get stylesheet for buttons that shouldn't have hover effects."""
        return """
            QPushButton { background-color: palette(button); color: palette(buttonText); }
            QPushButton:hover { background-color: palette(button); color: palette(buttonText); }
        """

    def _setup_ui(self):
        """Set up the main UI layout and widgets."""
        main_widget = QWidget()
        self.main_window.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Create tab widgets
        self.audio_tab_widget = QWidget()
        self.midi_tab_widget = QWidget()
        self.graph_tab_widget = QWidget()
        self.midi_matrix_tab_widget = QWidget()
        self.alsa_mixer_tab_widget = QWidget()
        self.pwtop_tab_widget = QWidget()
        self.latency_tab_widget = QWidget()

        self._setup_bottom_layout(main_layout)

    def _setup_bottom_layout(self, main_layout):
        """Set up the bottom control bar with buttons and filters."""
        bottom_layout = QHBoxLayout()

        # Create control widgets
        self.auto_refresh_checkbox = QCheckBox('Auto Refresh')
        self.auto_refresh_checkbox.setToolTip("Toggle automatic refreshing of ports and connections <span style='color:grey'>Alt+R</span>")

        self.collapse_all_checkbox = QCheckBox('Collapse All')
        self.collapse_all_checkbox.setToolTip("Toggle collapse state for all groups <span style='color:grey'>Alt+C</span>")

        self.undo_button = QPushButton('       Undo       ')
        self.undo_button.setToolTip("Undo last connection <span style='color:grey'>Ctrl+Z</span>")
        self.redo_button = QPushButton('       Redo       ')
        self.redo_button.setToolTip("Redo last connection <span style='color:grey'>Shift+Ctrl+Z/Ctrl+Y</span>")

        no_hover_style = self.get_no_hover_button_stylesheet()
        self.undo_button.setStyleSheet(no_hover_style)
        self.redo_button.setStyleSheet(no_hover_style)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)

        # Style filter edits
        filter_style = self.get_filter_stylesheet()
        self.output_filter_edit.setStyleSheet(filter_style)
        self.output_filter_edit.setClearButtonEnabled(True)
        self.output_filter_edit.setFixedWidth(150)

        bottom_layout.addWidget(self.output_filter_edit)

        bottom_layout.addStretch(1)

        self.bottom_refresh_button = QPushButton('     Refresh     ')
        self.bottom_refresh_button.setToolTip("Refresh port list <span style='color:grey'>R</span>")
        self.bottom_refresh_button.setStyleSheet(no_hover_style)

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

        self.input_filter_edit.setStyleSheet(filter_style)
        self.input_filter_edit.setClearButtonEnabled(True)
        self.input_filter_edit.setFixedWidth(150)
        bottom_layout.addWidget(self.input_filter_edit)

        main_layout.addLayout(bottom_layout)



    def get_color_scheme(self):
        """Get the current color scheme as a dictionary."""
        return {
            'background': self.background_color,
            'text': self.text_color,
            'highlight': self.highlight_color,
            'auto_highlight': self.auto_highlight_color,
            'drag_highlight': self.drag_highlight_color
        }
