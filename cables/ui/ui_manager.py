#!/usr/bin/env python3
"""
UI Manager for Cables JACK/PipeWire connection manager.
Handles all UI setup, styling, and widget management.
"""

from PyQt6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QCheckBox,
    QPushButton,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QMainWindow,
    QToolButton,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QAction

from cables.ui.tab_ui_manager import TabUIManager
from cables.ui.shared_widgets import create_action_button, TOOLBAR_BUTTON_MIN_WIDTH
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    from cable_core.config import ConfigManager
    from cables.connection_manager import JackConnectionManager
    from cables.ui.port_tree_widget import PortTreeWidget
    from cables.ui.connection_view import ConnectionView
    from graph.main_window import MainWindow as GraphMainWindow


class UIManager:
    """
    Manages all UI-related functionality for the Cables application.

    This class handles:
    - Color scheme setup and management
    - Widget creation and layout setup
    - Styling of UI components
    - Main window UI initialization
    """

    def __init__(
        self, main_window: QMainWindow, config_manager: "ConfigManager"
    ) -> None:
        """
        Initialize the UI Manager.

        Args:
            main_window: The main application window
            config_manager: Configuration manager for settings
        """
        self.main_window = main_window
        self.config_manager = config_manager

        # Color state
        self.background_color: QColor = QColor()
        self.text_color: QColor = QColor()
        self.highlight_color: QColor = QColor()
        self.button_color: QColor = QColor()
        self.connection_color: QColor = QColor()
        self.auto_highlight_color: QColor = QColor()
        self.drag_highlight_color: QColor = QColor()

        # Initialize color scheme
        self.dark_mode: bool = self.is_dark_mode()
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
        self.collapse_all_checkbox: Optional[QCheckBox] = None
        self.collapse_all_button: Optional[QToolButton] = None
        self.collapse_all_action: Optional[QAction] = None
        self.untangle_button: Optional[QPushButton] = None
        self.bottom_presets_button: Optional[QPushButton] = None
        self.bottom_visibility_button: Optional[QPushButton] = None
        self.zoom_in_button: Optional[QPushButton] = None
        self.zoom_out_button: Optional[QPushButton] = None

        # Tree and view references (set by connection manager)
        self.input_tree: Optional["PortTreeWidget"] = None
        self.output_tree: Optional["PortTreeWidget"] = None
        self.midi_input_tree: Optional["PortTreeWidget"] = None
        self.midi_output_tree: Optional["PortTreeWidget"] = None
        self.connection_view: Optional["ConnectionView"] = None
        self.midi_connection_view: Optional["ConnectionView"] = None
        self.graph_main_window: Optional["GraphMainWindow"] = None

    def is_dark_mode(self) -> bool:
        """Determine if the system is in dark mode."""
        from cable_core.theme import get_theme_manager
        return get_theme_manager().is_dark_mode()

    def setup_colors(self) -> None:
        """Set up the color scheme based on dark/light mode."""
        from cable_core.theme import get_theme_manager
        theme_mgr = get_theme_manager()
        self.background_color = theme_mgr.get_color("background")
        self.text_color = theme_mgr.get_color("text")
        self.highlight_color = theme_mgr.get_color("highlight")
        self.button_color = theme_mgr.get_color("button")
        self.connection_color = theme_mgr.get_color("connection")
        self.auto_highlight_color = theme_mgr.get_color("auto_highlight")
        self.drag_highlight_color = theme_mgr.get_color("drag_highlight")

    def list_stylesheet(self) -> str:
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

    def button_stylesheet(self) -> str:
        """Get stylesheet for buttons."""
        return f"""
            QPushButton {{ background-color: {self.button_color.name()}; color: {self.text_color.name()}; }}
            QPushButton:hover {{ background-color: {self.highlight_color.name()}; }}
        """

    def get_filter_stylesheet(self) -> str:
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

    def get_no_hover_button_stylesheet(self) -> str:
        """Get stylesheet for buttons that shouldn't have hover effects."""
        return """
            QPushButton { background-color: palette(button); color: palette(buttonText); }
            QPushButton:hover { background-color: palette(button); color: palette(buttonText); }
        """

    def _setup_ui(self) -> None:
        """Set up the main UI layout and widgets."""
        self.main_window.setMinimumSize(400, 300)
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
        self.audio_matrix_tab_widget = QWidget()
        self.alsa_mixer_tab_widget = QWidget()
        self.pwtop_tab_widget = QWidget()
        self.latency_tab_widget = QWidget()

        self._setup_bottom_layout(main_layout)

    def _setup_bottom_layout(self, main_layout: QVBoxLayout) -> None:
        """Set up the bottom control bar with buttons and filters."""
        bottom_layout = QHBoxLayout()

        # Create control widgets - Collapse All as checkable QToolButton (like Persistent layout)
        self.collapse_all_action = QAction("Collapse All", self.main_window)
        self.collapse_all_action.setCheckable(True)
        self.collapse_all_action.setToolTip(
            "Toggle collapse state for all groups <span style='color:grey'>Alt+C</span>"
        )

        self.collapse_all_button = create_action_button(
            parent_widget=self.main_window,
            action=self.collapse_all_action,
            tooltip="Toggle collapse state for all groups <span style='color:grey'>Alt+C</span>",
        )

        no_hover_style = self.get_no_hover_button_stylesheet()

        # Style filter edits
        filter_style = self.get_filter_stylesheet()
        self.output_filter_edit.setStyleSheet(filter_style)
        self.output_filter_edit.setClearButtonEnabled(True)
        self.output_filter_edit.setFixedWidth(150)

        bottom_layout.addWidget(self.output_filter_edit)

        bottom_layout.addStretch(1)

        self.untangle_button = QPushButton()
        self.untangle_button.setStyleSheet(no_hover_style)
        self.untangle_button.setMinimumWidth(TOOLBAR_BUTTON_MIN_WIDTH)

        # Create presets button for bottom bar (QToolButton like Graph tab)
        self.bottom_presets_button = QToolButton(self.main_window)
        self.bottom_presets_button.setText("Presets")
        self.bottom_presets_button.setMinimumWidth(TOOLBAR_BUTTON_MIN_WIDTH)

        # Create visibility button for bottom bar
        self.bottom_visibility_button = QPushButton("Clients Visibility")
        self.bottom_visibility_button.setStyleSheet(no_hover_style)
        self.bottom_visibility_button.setMinimumWidth(TOOLBAR_BUTTON_MIN_WIDTH)

        bottom_layout.addWidget(self.collapse_all_button)
        bottom_layout.addWidget(self.untangle_button)
        bottom_layout.addWidget(self.bottom_presets_button)
        bottom_layout.addWidget(self.bottom_visibility_button)
        bottom_layout.addStretch(1)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip(
            "Increase port list font size <span style='color:grey'>Ctrl++</span>"
        )
        self.zoom_in_button.setStyleSheet(no_hover_style)
        zoom_button_size = QSize(25, 25)
        self.zoom_in_button.setFixedSize(zoom_button_size)

        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.setToolTip(
            "Decrease port list font size <span style='color:grey'>Ctrl+-</span>"
        )
        self.zoom_out_button.setStyleSheet(no_hover_style)
        self.zoom_out_button.setFixedSize(zoom_button_size)

        bottom_layout.addWidget(self.zoom_out_button)
        bottom_layout.addWidget(self.zoom_in_button)

        self.input_filter_edit.setStyleSheet(filter_style)
        self.input_filter_edit.setClearButtonEnabled(True)
        self.input_filter_edit.setFixedWidth(150)
        bottom_layout.addWidget(self.input_filter_edit)

        main_layout.addLayout(bottom_layout)

    def get_color_scheme(self) -> Dict[str, QColor]:
        """Get the current color scheme as a dictionary."""
        return {
            "background": self.background_color,
            "text": self.text_color,
            "highlight": self.highlight_color,
            "auto_highlight": self.auto_highlight_color,
            "drag_highlight": self.drag_highlight_color,
        }

    def _on_theme_changed(self) -> None:
        """Regenerate colors and re-apply all stylesheets."""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("UIManager._on_theme_changed: START")
        self.dark_mode = self.is_dark_mode()
        logger.info(f"UIManager._on_theme_changed: dark_mode = {self.dark_mode}")
        self.setup_colors()

        # Regenerate stylesheets now that colors are fresh
        # Filter edits
        flt = self.get_filter_stylesheet()
        self.output_filter_edit.setStyleSheet(flt)
        self.input_filter_edit.setStyleSheet(flt)

        # No-hover toolbar buttons
        nh = self.get_no_hover_button_stylesheet()
        for btn in (
            self.collapse_all_button,
            self.untangle_button,
            self.bottom_visibility_button,
            self.zoom_in_button,
            self.zoom_out_button,
        ):
            if btn is not None:
                btn.setStyleSheet(nh)
