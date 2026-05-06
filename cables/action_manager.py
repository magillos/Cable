# cables/action_manager.py
"""
ActionManager - Manages QActions and QShortcuts for the application

This class handles all keyboard shortcuts and action management.
It uses a signal-based approach to decouple from the main window,
listening for tab state changes and emitting signals for actions.
"""

import random
import jack
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtGui import QKeySequence, QColor, QPainterPath, QPen, QAction
from PyQt6.QtCore import Qt, QTimer, QPointF, QObject, pyqtSignal

import logging
logger = logging.getLogger(__name__)

from cable_core import config_keys as keys
from typing import TYPE_CHECKING, Dict, Optional, List, Any, Callable
if TYPE_CHECKING:
    from cables.interfaces import ActionManagerInterface
    from cables.jack_connection_handler import JackConnectionHandler
    from cables.features.preset_handler import PresetHandler
    from cables.ui_state_manager import UIStateManager
    from PyQt6.QtWidgets import QPushButton, QWidget


class ActionManager(QObject):
    """
    Manages QActions and QShortcuts for the application.
    
    This class uses signals to communicate with the main application,
    reducing tight coupling. It maintains its own internal state for
    which tab is active, updated via the tab_changed signal.
    
    Signals emitted:
        connect_requested(bool): Request connection (is_midi)
        disconnect_requested(bool): Request disconnection (is_midi)
        undo_requested(bool): Request undo (is_graph)
        redo_requested(bool): Request redo (is_graph)
        refresh_requested(): Request port refresh
        untangle_requested(bool): Request untangle (is_graph)
        zoom_requested(int): Request zoom (direction: 1=in, -1=out)
        tab_switch_requested(bool): Request tree focus switch (forwards)
    """
    
    # Signals for decoupled communication
    connect_requested = pyqtSignal(bool)  # is_midi
    disconnect_requested = pyqtSignal(bool)  # is_midi
    undo_requested = pyqtSignal(bool)  # is_graph
    redo_requested = pyqtSignal(bool)  # is_graph
    refresh_requested = pyqtSignal()
    untangle_requested = pyqtSignal(bool)  # is_graph
    zoom_requested = pyqtSignal(int)  # direction: 1=increase, -1=decrease
    tab_switch_requested = pyqtSignal(bool)  # forwards

    def __init__(self,
                 connection_handler: 'JackConnectionHandler', 
                 preset_handler: 'PresetHandler',
                 get_current_tab_type: Callable[[], str],
                 get_graph_main_window: Callable[[], Optional[Any]],
                 get_colors: Callable[[], Dict[str, QColor]],
                 get_connection_history: Callable[[], Any],
                 notify_history_changed: Callable[[], None],
                 parent: Optional[QObject] = None) -> None:
        """
        Initialize ActionManager with callback functions instead of main_window reference.
        
        Args:
            connection_handler: Handler for JACK connection operations
            preset_handler: Handler for preset operations
            get_current_tab_type: Callback that returns current tab type string
            get_graph_main_window: Callback that returns graph main window or None
            get_colors: Callback that returns dict with 'text' and 'highlight' QColor values
            get_connection_history: Callback that returns the connection history object
            notify_history_changed: Callback to notify history state changed
            parent: Parent QObject
        """
        super().__init__(parent)
        self.connection_handler = connection_handler
        self.preset_handler = preset_handler
        
        # Callbacks for state access (instead of main_window reference)
        self._get_current_tab_type = get_current_tab_type
        self._get_graph_main_window = get_graph_main_window
        self._get_colors = get_colors
        self._get_connection_history = get_connection_history
        self._notify_history_changed = notify_history_changed
        
        self.state_manager: Optional['UIStateManager'] = None  # Will be set in complete_setup
        
        # Internal state for tab type (updated via callback)
        self._current_tab_type: str = keys.TAB_AUDIO

        # --- Action Attributes ---
        # Define all action attributes first
        # Generic global shortcuts
        self.global_connect_action: Optional[QAction] = None
        self.global_disconnect_action: Optional[QAction] = None
        self.global_undo_action: Optional[QAction] = None
        self.global_redo_action: Optional[QAction] = None
        
        # Port Tab Actions (Audio/MIDI)
        self.audio_connect_action: Optional[QAction] = None
        self.audio_disconnect_action: Optional[QAction] = None
        self.midi_connect_action: Optional[QAction] = None
        self.midi_disconnect_action: Optional[QAction] = None
        self.refresh_ports_action: Optional[QAction] = None
        self.presets_action: Optional[QAction] = None
        self.presets_menu: Optional[QMenu] = None

        # Graph Tab Actions
        self.graph_connect_action: Optional[QAction] = None
        self.graph_disconnect_action: Optional[QAction] = None
        self.graph_undo_action: Optional[QAction] = None
        self.graph_redo_action: Optional[QAction] = None
        self.presets_graph_action: Optional[QAction] = None
        self.presets_graph_menu: Optional[QMenu] = None
        
        # Zoom Actions
        self.zoom_in_action: Optional[QAction] = None
        self.zoom_out_action: Optional[QAction] = None

        # Other actions
        self.collapse_all_shortcut_action: Optional[QAction] = None
        self.untangle_shortcut_action: Optional[QAction] = None
        self.tab_switch_action: Optional[QAction] = None
        self.tab_switch_back_action: Optional[QAction] = None
        self.save_preset_action: Optional[QAction] = None
        self.default_preset_action: Optional[QAction] = None
        self.move_group_up_action: Optional[QAction] = None
        self.move_group_down_action: Optional[QAction] = None

        self._define_all_actions()

    def update_tab_state(self, tab_type: str) -> None:
        """
        Update internal tab state. Called by the main window when tabs change.
        
        Args:
            tab_type: The current tab type ('audio', 'midi', 'graph', etc.)
        """
        self._current_tab_type = tab_type

    def _is_graph_tab_active(self) -> bool:
        """Check if the Graph tab is currently active."""
        return self._current_tab_type == keys.TAB_GRAPH

    def _is_audio_tab_active(self) -> bool:
        """Check if the Audio tab is currently active."""
        return self._current_tab_type == keys.TAB_AUDIO

    def _is_midi_tab_active(self) -> bool:
        """Check if the MIDI tab is currently active."""
        return self._current_tab_type == keys.TAB_MIDI

    def _define_all_actions(self) -> None:
        """Define all QAction objects and their basic properties (text, shortcuts)."""
        # Get a parent widget for actions (use self as QObject parent)
        
        # --- Global Shortcut Actions ---
        self.global_connect_action = QAction("Connect Shortcut", self)
        self.global_connect_action.setShortcut(QKeySequence(Qt.Key.Key_C))

        self.global_disconnect_action = QAction("Disconnect Shortcut", self)
        self.global_disconnect_action.setShortcuts([QKeySequence(Qt.Key.Key_D), QKeySequence(Qt.Key.Key_Delete)])

        self.global_undo_action = QAction("Undo", self)
        self.global_undo_action.setShortcut(QKeySequence.StandardKey.Undo)

        self.global_redo_action = QAction("Redo", self)
        self.global_redo_action.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Y")])

        # --- Port Tab Specific Actions (Audio/MIDI) ---
        self.audio_connect_action = QAction("Connect", self)
        self.audio_disconnect_action = QAction("Disconnect", self)
        self.midi_connect_action = QAction("Connect", self)
        self.midi_disconnect_action = QAction("Disconnect", self)

        self.refresh_ports_action = QAction("Refresh", self)
        self.refresh_ports_action.setShortcut(QKeySequence(Qt.Key.Key_R))

        self.presets_action = QAction("Presets", self)
        self.presets_menu = QMenu()
        self.presets_action.setMenu(self.presets_menu)
        if not self.preset_handler:
            self.presets_action.setEnabled(False)
        else:
            self.presets_action.setEnabled(True)

        # --- Graph Tab Specific Actions ---
        self.graph_connect_action = QAction("Connect", self)
        self.graph_disconnect_action = QAction("Disconnect", self)
        self.graph_undo_action = QAction("       Undo       ", self)
        self.graph_redo_action = QAction("       Redo       ", self)
        
        self.presets_graph_action = QAction("Presets", self)
        self.presets_graph_menu = QMenu()
        self.presets_graph_action.setMenu(self.presets_graph_menu)
        if not self.preset_handler:
            self.presets_graph_action.setEnabled(False)
        else:
            self.presets_graph_action.setEnabled(True)

        # --- Zoom Actions ---
        self.zoom_in_action = QAction("+", self)
        self.zoom_in_action.setShortcuts([
            QKeySequence.StandardKey.ZoomIn, QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")
        ])

        self.zoom_out_action = QAction("-", self)
        self.zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)

        # --- Other Existing Actions ---
        self.collapse_all_shortcut_action = QAction("Collapse All Shortcut", self)
        self.collapse_all_shortcut_action.setShortcut(QKeySequence("Alt+C"))

        self.untangle_shortcut_action = QAction("Untangle Shortcut", self)
        self.untangle_shortcut_action.setShortcut(QKeySequence("Alt+U"))

        self.tab_switch_action = QAction("Switch Focus Forwards", self)
        self.tab_switch_action.setShortcut(QKeySequence(Qt.Key.Key_Tab))

        self.tab_switch_back_action = QAction("Switch Focus Backwards", self)
        self.tab_switch_back_action.setShortcut(QKeySequence(Qt.Key.Key_Backtab))

        self.save_preset_action = QAction("Save Preset Shortcut", self)
        self.save_preset_action.setShortcut(QKeySequence("Ctrl+S"))
        self.save_preset_action.setEnabled(False)

        self.default_preset_action = QAction("Default", self)
        self.default_preset_action.setShortcut(QKeySequence("Ctrl+Shift+R"))

        self.move_group_up_action = QAction("Move Up", self)
        self.move_group_up_action.setShortcut(QKeySequence("Alt+Up"))
        self.move_group_up_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.move_group_down_action = QAction("Move Down", self)
        self.move_group_down_action.setShortcut(QKeySequence("Alt+Down"))
        self.move_group_down_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def complete_setup(self, state_manager: 'UIStateManager', add_action_callback: Callable[[QAction], None]) -> None:
        """
        Connects action signals and adds shortcuts to the window.
        
        Args:
            state_manager: UIStateManager for font size and untangle operations
            add_action_callback: Callback to add actions to the main window
        """
        self.state_manager = state_manager
        self._connect_all_signals()
        self._add_actions_to_window(add_action_callback)

    def _connect_all_signals(self) -> None:
        """Connect all QAction signals to their handlers."""
        # --- Global Shortcut Actions ---
        self.global_connect_action.triggered.connect(self._handle_global_connect_shortcut)
        self.global_disconnect_action.triggered.connect(self._handle_global_disconnect_shortcut)
        self.global_undo_action.triggered.connect(self._handle_global_undo_shortcut)
        self.global_redo_action.triggered.connect(self._handle_global_redo_shortcut)

        # --- Port Tab Specific Actions (Audio/MIDI) ---
        # These connect to signals that the main window will handle
        self.audio_connect_action.triggered.connect(lambda: self.connect_requested.emit(False))
        self.audio_disconnect_action.triggered.connect(lambda: self.disconnect_requested.emit(False))
        self.midi_connect_action.triggered.connect(lambda: self.connect_requested.emit(True))
        self.midi_disconnect_action.triggered.connect(lambda: self.disconnect_requested.emit(True))
        self.refresh_ports_action.triggered.connect(self.refresh_requested.emit)
        
        if self.preset_handler:
            self.presets_menu.aboutToShow.connect(self.preset_handler.show_preset_menu)

        # --- Graph Tab Specific Actions ---
        self.graph_connect_action.triggered.connect(self._handle_graph_connect)
        self.graph_disconnect_action.triggered.connect(self._handle_graph_disconnect)
        self.graph_undo_action.triggered.connect(self._handle_graph_undo)
        self.graph_redo_action.triggered.connect(self._handle_graph_redo)
        
        if self.preset_handler:
            self.presets_graph_menu.aboutToShow.connect(self.preset_handler.show_preset_menu)

        # --- Zoom Actions ---
        self.zoom_in_action.triggered.connect(lambda: self.zoom_requested.emit(1))
        self.zoom_out_action.triggered.connect(lambda: self.zoom_requested.emit(-1))

        # --- Other Existing Actions ---
        # Collapse all is handled via signal to allow main window to manage UI
        self.collapse_all_shortcut_action.triggered.connect(self._handle_collapse_all)
        
        if self.state_manager:
            self.untangle_shortcut_action.triggered.connect(self._handle_global_untangle_shortcut)

        self.tab_switch_action.triggered.connect(lambda: self.tab_switch_requested.emit(True))
        self.tab_switch_back_action.triggered.connect(lambda: self.tab_switch_requested.emit(False))
        
        if self.preset_handler:
            self.save_preset_action.triggered.connect(self.preset_handler.save_current_loaded_preset)
            self.default_preset_action.triggered.connect(self.preset_handler.handle_default_preset_action)
        
        self.move_group_up_action.triggered.connect(lambda: self._handle_move_group(1))
        self.move_group_down_action.triggered.connect(lambda: self._handle_move_group(-1))

    def _add_actions_to_window(self, add_action_callback: Callable[[QAction], None]) -> None:
        """Add QAction objects with shortcuts to the main window via callback."""
        actions_with_shortcuts = [
            self.global_connect_action, self.global_disconnect_action,
            self.global_undo_action, self.global_redo_action,
            self.refresh_ports_action, self.collapse_all_shortcut_action,
            self.untangle_shortcut_action,
            self.zoom_in_action, self.zoom_out_action,
            self.tab_switch_action, self.tab_switch_back_action,
            self.save_preset_action, self.default_preset_action,
            self.move_group_up_action, self.move_group_down_action
        ]
        for action in actions_with_shortcuts:
            if action and add_action_callback:
                add_action_callback(action)

    # --- Handler Methods ---

    def _animate_button_press(self, button: Optional['QPushButton']) -> None:
        if not button:
            return

        # Store original style
        original_style = button.styleSheet()

        # Skip if already in pressed state
        if "inset" in original_style:
            return

        # Get colors via callback
        colors = self._get_colors()
        highlight = colors.get('highlight', QColor(100, 100, 200))
        text = colors.get('text', QColor(255, 255, 255))

        # Apply pressed style
        pressed_style = f"""
            QPushButton {{
                background-color: {highlight.name()};
                color: {text.name()};
                border: 2px inset {highlight.darker(120).name()};
            }}
        """
        button.setStyleSheet(pressed_style)

        # Restore original style after a short delay
        QTimer.singleShot(150, lambda: button.setStyleSheet(original_style))

    def _handle_collapse_all(self) -> None:
        """Handle collapse all shortcut - emit signal for main window to handle."""
        # This would need to be connected to a checkbox toggle in the main window
        pass

    def _handle_global_connect_shortcut(self) -> None:
        """Handles the global 'C' key shortcut for connect."""
        if self._is_audio_tab_active():
            self.audio_connect_action.trigger()
        elif self._is_midi_tab_active():
            self.midi_connect_action.trigger()
        elif self._is_graph_tab_active():
            self.graph_connect_action.trigger()

    def _handle_global_disconnect_shortcut(self) -> None:
        """Handles the global 'D'/Delete key shortcut for disconnect."""
        if self._is_audio_tab_active():
            self.audio_disconnect_action.trigger()
        elif self._is_midi_tab_active():
            self.midi_disconnect_action.trigger()
        elif self._is_graph_tab_active():
            self.graph_disconnect_action.trigger()

    def _handle_global_undo_shortcut(self) -> None:
        """Handles the global Ctrl+Z shortcut for undo."""
        if self._is_graph_tab_active():
            self.graph_undo_action.trigger()
            return
        
        # Audio/MIDI undo logic
        connection_history = self._get_connection_history()
        if not connection_history:
            return
            
        action = connection_history.undo()
        if action:
            action_type, output_name, input_name, is_midi = action

            try:
                if action_type == 'disconnect':
                    if is_midi:
                        self.connection_handler.break_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.break_connection(output_name, input_name, is_undo_redo=True)
                elif action_type == 'connect':
                    if is_midi:
                        self.connection_handler.make_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.make_connection(output_name, input_name, is_undo_redo=True)
                
                self._notify_history_changed()

            except jack.JackError as e:
                logger.debug(f"Undo error during handler call: {e}")
            
            self._notify_history_changed()

    def _handle_global_redo_shortcut(self) -> None:
        """Handles the global Ctrl+Y/Ctrl+Shift+Z shortcut for redo."""
        if self._is_graph_tab_active():
            self.graph_redo_action.trigger()
            return

        # Audio/MIDI redo logic
        connection_history = self._get_connection_history()
        if not connection_history:
            return
            
        action = connection_history.redo()
        if action:
            action_type, output_name, input_name, is_midi = action

            try:
                if action_type == 'connect':
                    if is_midi:
                        self.connection_handler.make_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.make_connection(output_name, input_name, is_undo_redo=True)
                else:
                    if is_midi:
                        self.connection_handler.break_midi_connection(output_name, input_name, is_undo_redo=True)
                    else:
                        self.connection_handler.break_connection(output_name, input_name, is_undo_redo=True)
                
                self._notify_history_changed()

            except jack.JackError as e:
                logger.debug(f"Redo error during handler call: {e}")
            
            self._notify_history_changed()

    def _handle_graph_connect(self) -> None:
        graph_mw = self._get_graph_main_window()
        if graph_mw and getattr(graph_mw, 'handle_connect_action', None) is not None:
            graph_mw.handle_connect_action()

    def _handle_graph_disconnect(self) -> None:
        graph_mw = self._get_graph_main_window()
        if graph_mw and getattr(graph_mw, 'handle_disconnect_action', None) is not None:
            graph_mw.handle_disconnect_action()

    def _handle_graph_undo(self) -> None:
        graph_mw = self._get_graph_main_window()
        if graph_mw and getattr(graph_mw, '_handle_graph_undo', None) is not None:
            graph_mw._handle_graph_undo()

    def _handle_graph_redo(self) -> None:
        graph_mw = self._get_graph_main_window()
        if graph_mw and getattr(graph_mw, '_handle_graph_redo', None) is not None:
            graph_mw._handle_graph_redo()

    def _handle_global_untangle_shortcut(self) -> None:
        """Handles the global 'Alt+U' key shortcut for untangle."""
        if self._is_audio_tab_active() or self._is_midi_tab_active():
            if self.state_manager:
                self.state_manager._handle_untangle_shortcut()
        elif self._is_graph_tab_active():
            graph_mw = self._get_graph_main_window()
            if graph_mw and getattr(graph_mw, '_handle_untangle', None) is not None:
                if getattr(graph_mw, 'untangle_button', None) is not None:
                    self._animate_button_press(graph_mw.untangle_button)
                graph_mw._handle_untangle()

    def _handle_move_group(self, direction: int) -> None:
        """
        Handle move group request (Alt+Up/Alt+Down shortcuts).
        
        Finds the focused tree widget and moves the selected group up or down.
        
        Args:
            direction: 1 for up, -1 for down
        """
        from PyQt6.QtWidgets import QApplication
        
        focused_widget = QApplication.focusWidget()
        focused_tree = None
        
        # Find the focused tree widget by walking up the parent chain
        while focused_widget is not None:
            if getattr(focused_widget, 'port_items', None) is not None:  # PortTreeWidget has this attribute
                focused_tree = focused_widget
                break
            focused_widget = focused_widget.parent()
        
        if focused_tree:
            item = focused_tree.currentItem()
            if item and item.parent() is None:  # Top-level item (group)
                if direction > 0:
                    focused_tree.move_group_up(item)
                else:
                    focused_tree.move_group_down(item)

    # --- Methods for external control ---
    
    def set_zoom_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable zoom actions."""
        if self.zoom_in_action:
            self.zoom_in_action.setEnabled(enabled)
        if self.zoom_out_action:
            self.zoom_out_action.setEnabled(enabled)

    def set_save_preset_enabled(self, enabled: bool) -> None:
        """Enable or disable save preset action."""
        if self.save_preset_action:
            self.save_preset_action.setEnabled(enabled)