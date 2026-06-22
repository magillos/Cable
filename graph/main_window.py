"""
Graph tab main window with toolbar, search, and layout controls.
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLineEdit, QSpacerItem, QSizePolicy, QMessageBox, QToolButton, QMenu, QApplication, QCheckBox)
from PyQt6.QtCore import pyqtSlot, QSize, Qt, QTimer, QEvent # Added QTimer for debounce
from PyQt6.QtGui import QAction, QKeySequence, QIcon # Added for shortcuts and icons
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import logging
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PyQt6.QtGui import QCloseEvent
    from cables.connection_manager import JackConnectionManager
    from cables.features.preset_handler import PresetHandler
    from cables.features.connection_history import ConnectionHistory

from cables.jack_service import get_jack_service
from cables.ui.shared_widgets import create_action_button
from cable_core import config_keys as keys
import jack # For jack.Client type hint
# from cables.connection_manager import JackConnectionManager # For type hint - REMOVED to break cycle
from .jack_handler import GraphJackHandler # Updated import
from .gui_scene import JackGraphScene
from .gui_view import JackGraphView
from .port_item import PortItem
from .connection_item import ConnectionItem
from .constants import GRAPH_TOOLBAR_UNDO_REDO_OFFSET
from . import graph_drag_helpers
from cable_core import app_config
import os
import configparser
import copy

# Special value to represent the original layout in the untangle cycle
ORIGINAL_LAYOUT = -1
# Special value for Graphviz-based auto layout
AUTO_LAYOUT = -2

def _check_graphviz_available() -> bool:
    """Check if python-graphviz and the graphviz dot binary are both available."""
    try:
        import graphviz
        # Verify the dot engine binary is actually installed
        graphviz.version()
        return True
    except Exception:
        return False

_graphviz_available = _check_graphviz_available()

class MainWindow(QMainWindow):
    def __init__(self, jack_client: jack.Client, connection_manager: 'JackConnectionManager', preset_handler_ref: 'PresetHandler', connection_history_ref: 'ConnectionHistory') -> None:
        super().__init__()
        self.jack_client = jack_client
        self.connection_manager = connection_manager
        self.preset_handler = preset_handler_ref
        self.connection_history = connection_history_ref
        
        # Load untangle values from config or use defaults
        self.untangle_values = self._load_untangle_values()
        
        # Debounce timer for layout reapplication (I/O mode)
        self._layout_debounce_timer = QTimer(self)
        self._layout_debounce_timer.setSingleShot(True)
        self._layout_debounce_timer.timeout.connect(self._deferred_reapply_layout)
        
        # Add the special value for original layout to the untangle values
        if ORIGINAL_LAYOUT not in self.untangle_values:
            self.untangle_values.append(ORIGINAL_LAYOUT)
        
        # Add auto layout option at the top of the menu
        if AUTO_LAYOUT not in self.untangle_values:
            self.untangle_values.insert(0, AUTO_LAYOUT)
        
        self.current_untangle_setting = self.untangle_values[0] if self.untangle_values else 6
        self.untangle_button_clicked = False
        self.first_untangle_click_done = False
        self.keep_untangled = False
        self.initial_node_positions = None

        # Widget/action references created later in _create_toolbar;
        # pre-declared to None so hasattr() guards are unnecessary.
        self.graph_connect_action: Any = None
        self.graph_disconnect_action: Any = None
        self.graph_undo_action: Any = None
        self.graph_redo_action: Any = None
        self.presets_graph_action: Any = None
        self.preset_button: Any = None
        self._top_toolbar_layout: Any = None
        self._bottom_toolbar_layout: Any = None

        self.setWindowTitle("PyQt JACK Graph")
        self.setGeometry(100, 100, 1000, 700)

        self._create_scene_and_view()
        self._create_toolbar()
        self._connect_signals()
        self._restore_state()

    def _create_scene_and_view(self) -> None:
        """Create the graph scene and view, and load saved untangle/keep settings."""
        self.scene = JackGraphScene(
            jack_client=self.jack_client,
            connection_manager=self.connection_manager,
            connection_history=self.connection_history,
            parent=self
        )
        self.view = JackGraphView(self.scene)
        
        # Load the saved untangle setting from the scene if available
        if getattr(self.scene, 'initial_untangle_setting', None) is not None:
            if self.scene.initial_untangle_setting in self.untangle_values:
                self.current_untangle_setting = self.scene.initial_untangle_setting
                self.untangle_button_clicked = True
                logger.info(f"Loaded untangle setting: {self.current_untangle_setting}")
            else:
                logger.info("No valid stored untangle setting, will apply Auto layout when scene is ready")
                self.scene.scene_fully_loaded.connect(self._deferred_apply_auto_layout)
        else:
            logger.info("No stored untangle setting found, will apply Auto layout when scene is ready")
            self.scene.scene_fully_loaded.connect(self._deferred_apply_auto_layout)
        
        # Load the keep_untangled setting from the scene's config manager
        if getattr(self.scene, 'node_config_manager', None) is not None:
            self.keep_untangled = self.scene.node_config_manager.load_keep_untangled()

    def _create_toolbar(self) -> None:
        """Create all toolbar buttons and assemble the main layout."""
        action_manager = self.connection_manager.action_manager

        # Action buttons
        self.graph_connect_action = action_manager.graph_connect_action
        self.connect_button = create_action_button(self, self.graph_connect_action, tooltip="Connect selected items <span style='color:grey'>C</span>")

        self.graph_disconnect_action = action_manager.graph_disconnect_action
        self.disconnect_button = create_action_button(self, self.graph_disconnect_action, tooltip="Disconnect selected items <span style='color:grey'>D/Del</span>")

        self.presets_graph_action = action_manager.presets_graph_action
        self.preset_button = create_action_button(self, self.presets_graph_action, tooltip="Manage Presets")
        self.preset_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.graph_undo_action = action_manager.graph_undo_action
        self.undo_button = create_action_button(
            self,
            self.graph_undo_action,
            tooltip="Undo last connection <span style='color:grey'>Ctrl+Z</span>"
        )

        self.graph_redo_action = action_manager.graph_redo_action
        self.redo_button = create_action_button(
            self,
            self.graph_redo_action,
            tooltip="Redo last connection <span style='color:grey'>Shift+Ctrl+Z/Ctrl+Y</span>"
        )
        
        # Layouts button with menu (formerly called Untangle and refernced in the code as such)
        self.untangle_action = QAction("Layouts", self)
        self.untangle_action.setToolTip("Reorganise graph layout <span style='color:grey'>Alt+U</span>")
        self.untangle_action.triggered.connect(self._handle_untangle)
        self.untangle_menu = QMenu(self)
        self.untangle_action.setMenu(self.untangle_menu)
        self.untangle_menu.aboutToShow.connect(self._populate_untangle_menu)
        
        self.untangle_button = create_action_button(
            self,
            self.untangle_action,
            tooltip="Reorganise graph layout <span style='color:grey'>Alt+U</span>"
        )
        self.untangle_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        # Persistent layout button (checkable)
        self.persistent_layout_action = QAction("Persistent layout", self)
        self.persistent_layout_action.setCheckable(True)
        self.persistent_layout_action.setChecked(self.keep_untangled)
        self.persistent_layout_action.setToolTip("Automatically reapply the current layout when nodes are added or removed\n"
                                                "When off, double click to refresh active layout")
        self.persistent_layout_action.toggled.connect(self._toggle_persistent_layout)
        
        self.persistent_layout_button = create_action_button(
            self,
            self.persistent_layout_action,
            tooltip="Automatically reapply the current layout when nodes are added or removed\n"
                    "When off, double click to refresh active layout"
        )

        # Zoom buttons
        self.zoom_in_action = action_manager.zoom_in_action
        self.zoom_in_button = create_action_button(
            self,
            self.zoom_in_action,
            tooltip="Zoom In <span style='color:grey'>Ctrl++/Ctrl+Scroll</span>",
            fixed_size=QSize(25, 25)
        )

        self.zoom_out_action = action_manager.zoom_out_action
        self.zoom_out_button = create_action_button(
            self,
            self.zoom_out_action,
            tooltip="Zoom Out <span style='color:grey'>Ctrl+-/Ctrl+Scroll</span>",
            fixed_size=QSize(25, 25)
        )

        # Filter box
        self.node_filter_box = QLineEdit()
        self.node_filter_box.setPlaceholderText("Filter Clients...")
        self.node_filter_box.setFixedWidth(150)
        self.node_filter_box.setToolTip("Use \"-\" prefix for exclusive filtering")
        self.node_filter_box.setClearButtonEnabled(True)
        self.node_filter_box.textChanged.connect(self._handle_node_filter_change)

        # Top toolbar layout (Connect, Disconnect, Undo, Redo) - Centered
        top_toolbar_layout = QHBoxLayout()
        top_toolbar_layout.addStretch(1)
        top_toolbar_layout.addWidget(self.connect_button)
        top_toolbar_layout.addWidget(self.disconnect_button)
        top_toolbar_layout.addWidget(self.undo_button)
        top_toolbar_layout.addWidget(self.redo_button)
        top_toolbar_layout.addStretch(1)
        self._top_toolbar_layout = top_toolbar_layout

        # Bottom toolbar layout (Filters, Presets, Zoom)
        bottom_toolbar_layout = QHBoxLayout()
        bottom_toolbar_layout.addWidget(self.node_filter_box)
        bottom_toolbar_layout.addStretch(1)
        
        if GRAPH_TOOLBAR_UNDO_REDO_OFFSET > 0:
            bottom_toolbar_layout.addSpacerItem(QSpacerItem(GRAPH_TOOLBAR_UNDO_REDO_OFFSET, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        
        bottom_toolbar_layout.addWidget(self.persistent_layout_button)
        bottom_toolbar_layout.addWidget(self.untangle_button)
        bottom_toolbar_layout.addWidget(self.preset_button)

        if GRAPH_TOOLBAR_UNDO_REDO_OFFSET < 0:
            bottom_toolbar_layout.addSpacerItem(QSpacerItem(abs(GRAPH_TOOLBAR_UNDO_REDO_OFFSET), 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        
        bottom_toolbar_layout.addStretch(1)
        bottom_toolbar_layout.addWidget(self.zoom_out_button)
        bottom_toolbar_layout.addWidget(self.zoom_in_button)
        bottom_toolbar_layout.addSpacerItem(QSpacerItem(10, 10, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
        self._bottom_toolbar_layout = bottom_toolbar_layout
        
        # Assemble main layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        main_layout.addLayout(top_toolbar_layout)
        main_layout.addWidget(self.view)
        main_layout.addLayout(bottom_toolbar_layout)
        self.setCentralWidget(main_widget)

    def _connect_signals(self) -> None:
        """Connect scene, view, and JACK service signals."""
        # Scene signals for layout tracking
        self.scene.scene_fully_loaded.connect(self._store_initial_node_positions)
        self.scene.node_states_changed.connect(self._update_original_layout_baseline)
        self.scene.node_states_changed.connect(self._reapply_auto_layout_on_split_change)
        self.scene.node_states_changed.connect(lambda: self.preset_handler.update_save_button_enabled_state() if self.preset_handler else None)
        self.scene.scene_connections_changed.connect(self._schedule_layout_reapply)

        # JACK shutdown and reconnection
        jack_service = get_jack_service()
        jack_service.shutdown.connect(self.handle_jack_shutdown)
        jack_service.reconnected.connect(self.handle_jack_reconnected)

        # Button state updates
        self.scene.selectionChanged.connect(self.update_graph_connection_buttons_state)
        self.scene.scene_connections_changed.connect(self.update_graph_connection_buttons_state)
        self.scene.scene_connections_changed.connect(self._update_graph_undo_redo_buttons_state)

        # Reset untangle first-click tracking on layout changes
        self.scene.node_states_changed.connect(self._reset_untangle_first_click)
        jack_service.client_added.connect(self._reset_untangle_first_click)
        jack_service.client_removed.connect(self._reset_untangle_first_click)
 
        # Zoom state persistence
        self.view.zoom_changed.connect(self.handle_zoom_changed)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            from cable_core.theme import get_theme_manager
            get_theme_manager().check_theme_changed()

    def _restore_state(self) -> None:
        """Set initial button states and apply saved zoom level."""
        self.update_graph_connection_buttons_state()
        self._update_graph_undo_redo_buttons_state()

        if self.scene.initial_zoom_level is not None:
            logger.info(f"Applying loaded zoom level: {self.scene.initial_zoom_level}")
            self.view.set_zoom_level(self.scene.initial_zoom_level)

        # Controls that can be hidden in fullscreen
        self._internal_controls = [
            self.connect_button, self.disconnect_button, self.preset_button,
            self.untangle_button, self.undo_button, self.redo_button, 
            self.zoom_in_button, self.zoom_out_button,
            self.persistent_layout_button,
            self.node_filter_box
        ]
        
        self._update_persistent_layout_button_state()

    def _load_untangle_values(self) -> List[int]:
        """Load untangle values from config or use defaults."""
        config_path = os.path.expanduser("~/.config/cable/config.ini")
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            try:
                config.read(config_path)
                if 'DEFAULT' in config and keys.GRAPH_UNTANGLE_VALUES in config['DEFAULT']:
                    values_str = config['DEFAULT'][keys.GRAPH_UNTANGLE_VALUES]
                    try:
                        # Parse comma-separated values
                        values = [int(v.strip()) for v in values_str.split(',') if v.strip().isdigit()]
                        if values:  # Only return if we have valid values
                            return values
                    except ValueError:
                        logger.error(f"Error parsing untangle values from config: {values_str}")
            except Exception as e:
                logger.error(f"Error reading untangle values from config: {e}")
        
        # Return default values if config doesn't exist or has invalid values
        return app_config.DEFAULT_UNTANGLE_VALUES

    def _store_initial_node_positions(self) -> None:
        """Store the initial node positions when the scene is first loaded."""
        if not self.initial_node_positions:
            # Get current node positions from the scene
            node_states = self.scene.get_node_states()
            if node_states:
                self.initial_node_positions = copy.deepcopy(node_states)
                logger.debug("Initial node positions stored")

    def _update_original_layout_baseline(self) -> None:
        """Refresh the 'original layout' snapshot to reflect current user adjustments."""
        node_states = self.scene.get_node_states()
        if node_states:
            self.initial_node_positions = copy.deepcopy(node_states)
    
    def _schedule_layout_reapply(self) -> None:
        """Schedule a debounced layout reapplication for I/O mode or persistent layout mode."""
        if not self.untangle_button_clicked:
            return
        if self.current_untangle_setting == 0:
            self._layout_debounce_timer.start(150)
        elif self.keep_untangled and self.current_untangle_setting != ORIGINAL_LAYOUT:
            self._layout_debounce_timer.start(150)
    
    @pyqtSlot()
    def _deferred_reapply_layout(self) -> None:
        """Deferred reapplication of layout after debounce."""
        self._reapply_layout_if_needed()
    
    def _reapply_layout_if_needed(self) -> None:
        """Reapply the current layout after graph refresh for I/O or persistent layout mode."""
        if getattr(self.scene, '_in_full_refresh', False):
            return
        if not self.untangle_button_clicked:
            return
        if self.current_untangle_setting == 0:
            logger.debug("Reapplying I/O layout after graph refresh")
            # Don't unsplit nodes before applying I/O layout - it will handle splitting
            self.scene.untangle_graph_by_io()
        elif self.keep_untangled and self.current_untangle_setting != ORIGINAL_LAYOUT:
            if self.current_untangle_setting == AUTO_LAYOUT:
                logger.debug("Reapplying Auto layout for 'Persistent layout'")
                self.scene.untangle_graph_auto(auto_split=self._get_auto_split_setting())
            else:
                logger.debug(f"Reapplying untangle layout ({self.current_untangle_setting} nodes per row) for 'Persistent layout'")
                self.scene.unsplit_all_nodes(save_state=False)
                self.scene.untangle_graph(max_nodes_per_row=self.current_untangle_setting)

    def _get_auto_split_setting(self) -> bool:
        """Read the 'Split nodes in Auto layout' setting from config."""
        if getattr(self.scene, 'main_config_manager', None) is not None:
            return self.scene.main_config_manager.get_bool(keys.GRAPH_AUTO_LAYOUT_SPLIT, False)
        return False

    def _reapply_auto_layout_on_split_change(self) -> None:
        """Reapply auto layout when user manually splits/unsplits a node.

        Only fires when auto layout is active, auto-split setting is OFF,
        and 'Persistent layout' is ON. When 'Persistent layout' is OFF, no automatic
        re-layout should occur.
        """
        if not self.untangle_button_clicked:
            return
        if self.current_untangle_setting != AUTO_LAYOUT:
            return
        if not self.keep_untangled:
            return  # Don't reapply layout when persistent_layout is OFF
        if self._get_auto_split_setting():
            return  # auto-split is ON — the algorithm manages splits itself
        if getattr(self.scene, '_in_full_refresh', False):
            return
        logger.debug("Reapplying Auto layout after user split/unsplit change (persistent layout is ON)")
        self.scene.untangle_graph_auto(auto_split=False)

    def toggle_internal_controls(self, visible: bool) -> None:
        """Shows or hides the internal toolbar/control widgets."""
        logger.debug(f"Graph MainWindow: Setting internal controls visibility to {visible}")
        for control in self._internal_controls:
            if control: # Check if widget exists
                control.setVisible(visible)
        # Force layout update within the graph tab's main widget
        if self.centralWidget() and self.centralWidget().layout():
             self.centralWidget().layout().activate()


    @pyqtSlot()
    def _update_graph_undo_redo_buttons_state(self) -> None:
        """Updates the enabled state of Undo and Redo buttons for the graph tab."""
        if self.connection_history and self.graph_undo_action is not None and self.graph_redo_action is not None:
            self.graph_undo_action.setEnabled(self.connection_history.can_undo())
            self.graph_redo_action.setEnabled(self.connection_history.can_redo())
        else:
            if self.graph_undo_action is not None: self.graph_undo_action.setEnabled(False)
            if self.graph_redo_action is not None: self.graph_redo_action.setEnabled(False)

    @pyqtSlot()
    def _handle_graph_undo(self) -> None:
        """Undo the last connection action via ConnectionHistory."""
        if self.connection_history:
            if self.connection_history.undo_and_execute(self.scene.jack_connection_handler):
                logger.debug("Graph Undo: executed inverse connection")
            self._update_graph_undo_redo_buttons_state()

    @pyqtSlot()
    def _handle_graph_redo(self) -> None:
        """Redo the next connection action via ConnectionHistory."""
        if self.connection_history:
            if self.connection_history.redo_and_execute(self.scene.jack_connection_handler):
                logger.debug("Graph Redo: executed connection")
            self._update_graph_undo_redo_buttons_state()

    @pyqtSlot()
    def _zoom_in_view(self) -> None:
        if self.view:
            self.view.zoom_in()

    @pyqtSlot()
    def _zoom_out_view(self) -> None:
        if self.view:
            self.view.zoom_out()

    @pyqtSlot(float)
    def handle_zoom_changed(self, zoom_level: float) -> None:
        """Handles the zoom_changed signal from the view and saves the state."""
        # print(f"Handling zoom change event in MainWindow: {zoom_level}") # Silenced
        # Save node positions, zoom level, and untangle setting
        self.scene.save_node_states(graph_zoom_level=zoom_level, current_untangle_setting=self.current_untangle_setting)

    @pyqtSlot()
    def _reset_untangle_first_click(self, *args: Any) -> None:
        """Resets the untangle button first-click tracking when graph layout changes."""
        # Only reset if we have actually clicked it once, to avoid unnecessary writes/logic if it's already False
        if self.first_untangle_click_done:
            self.first_untangle_click_done = False
            # print("Graph layout changed, resetting untangle first-click tracking")
        
    def _populate_untangle_menu(self) -> None:
        """Populates the untangle layout menu with available layouts."""
        self.untangle_menu.clear()
        
        for value in self.untangle_values:
            if value == ORIGINAL_LAYOUT:
                label = "Autosaved layout"
            elif value == AUTO_LAYOUT:
                label = "Auto layout"
            elif value == 0:
                label = "I/O layout"
            else:
                label = f"{value} nodes per row"
            
            action = QAction(label, self)
            
            # Grey out Auto layout when graphviz is not installed
            if value == AUTO_LAYOUT and not _graphviz_available:
                action.setEnabled(False)
                action.setToolTip("Requires python-graphviz and graphviz")
            
            # Highlight active layout with bold font (consistent with presets menu)
            if value == self.current_untangle_setting and self.untangle_button_clicked:
                font = action.font()
                font.setBold(True)
                action.setFont(font)
            
            # Store the value in the action for retrieval when triggered
            action.setData(value)
            action.triggered.connect(lambda checked, v=value: self._apply_untangle_layout(v))
            
            self.untangle_menu.addAction(action)
    
    def _update_persistent_layout_button_state(self) -> None:
        """Updates the enabled state of the 'Persistent layout' button based on current layout."""
        # The button should be enabled only when:
        # - Untangle has been used at least once (button clicked)
        # - Current setting is not I/O layout (0)
        # - Current setting is not Autosaved layout (ORIGINAL_LAYOUT)
        can_enable = (
            self.untangle_button_clicked and 
            self.current_untangle_setting != 0 and
            self.current_untangle_setting != ORIGINAL_LAYOUT
        )
        self.persistent_layout_button.setEnabled(can_enable)
    
    def _toggle_persistent_layout(self, checked: bool) -> None:
        """Toggles the 'Persistent layout' setting."""
        self.keep_untangled = checked
        
        # Save the setting to config
        if getattr(self.scene, 'node_config_manager', None) is not None:
            self.scene.node_config_manager.save_keep_untangled(checked)
        
        # Reapply the current layout when turning ON
        if checked and self.untangle_button_clicked and self.current_untangle_setting != ORIGINAL_LAYOUT:
            if self.current_untangle_setting == 0:
                # I/O layout
                logger.debug("Reapplying I/O layout on 'Persistent layout' enable")
                self.scene.unsplit_all_nodes(save_state=False)
                self.scene.untangle_graph_by_io()
                if self.statusBar() is not None:
                    self.statusBar().showMessage("Persistent layout enabled - I/O layout reapplied.", 3000)
            elif self.current_untangle_setting == AUTO_LAYOUT:
                # Auto layout
                logger.debug("Reapplying Auto layout on 'Persistent layout' enable")
                self.scene.untangle_graph_auto(auto_split=self._get_auto_split_setting())
                if self.statusBar() is not None:
                    self.statusBar().showMessage("Persistent layout enabled - Auto layout reapplied.", 3000)
            else:
                # Nodes per row layout
                logger.debug(f"Reapplying {self.current_untangle_setting} nodes per row layout on 'Persistent layout' enable")
                self.scene.unsplit_all_nodes(save_state=False)
                self.scene.untangle_graph(max_nodes_per_row=self.current_untangle_setting)
                if self.statusBar() is not None:
                    self.statusBar().showMessage(f"Persistent layout enabled - {self.current_untangle_setting} nodes per row layout reapplied.", 3000)
        elif self.statusBar() is not None:
            if checked:
                self.statusBar().showMessage("Persistent layout enabled - layout will be reapplied when nodes change.", 3000)
            else:
                self.statusBar().showMessage("Persistent layout disabled.", 3000)
    
    def _deferred_apply_auto_layout(self) -> None:
        """Apply Auto layout after deferred node push-away callbacks complete.

        Node creation schedules QTimer.singleShot(0) push-away callbacks.
        Those run in the next event-loop tick after scene_fully_loaded.
        We defer our layout one more tick so push-aways finish first and
        the auto layout can reposition everything cleanly.
        """
        QTimer.singleShot(0, lambda: self._apply_untangle_layout(AUTO_LAYOUT))

    def _apply_untangle_layout(self, layout_value: int) -> None:
        """Applies the selected untangle layout."""
        # Update the current setting
        self.current_untangle_setting = layout_value
        
        # Apply the layout
        if layout_value == ORIGINAL_LAYOUT:
            if self.initial_node_positions:
                self.scene.restore_node_states(self.initial_node_positions)
                if self.statusBar() is not None:
                    self.statusBar().showMessage("Restored original layout.", 3000)
            else:
                self.scene.untangle_graph(max_nodes_per_row=6)
                if self.statusBar() is not None:
                    self.statusBar().showMessage("Original layout not available, using default untangle.", 3000)
        elif layout_value == AUTO_LAYOUT:
            success = self.scene.untangle_graph_auto(auto_split=self._get_auto_split_setting())
            if success:
                if self.statusBar() is not None:
                    self.statusBar().showMessage("Auto layout applied.", 3000)
            else:
                if self.statusBar() is not None:
                    self.statusBar().showMessage("Auto layout failed. Is python-graphviz installed?", 5000)
        elif layout_value == 0:
            # I/O layout will handle splitting nodes itself
            self.scene.untangle_graph_by_io()
            if self.statusBar() is not None:
                self.statusBar().showMessage("Graph untangled by I/O.", 3000)
        else:
            self.scene.unsplit_all_nodes(save_state=False)
            self.scene.untangle_graph(max_nodes_per_row=layout_value)
            if self.statusBar() is not None:
                self.statusBar().showMessage(f"Graph untangled with {layout_value} nodes per row.", 3000)
        
        # Save the current untangle setting after applying the layout
        current_zoom_level = self.view.get_zoom_level() if getattr(self.view, 'get_zoom_level', None) is not None else None
        self.scene.save_node_states(graph_zoom_level=current_zoom_level, current_untangle_setting=self.current_untangle_setting)
        
        # Mark that untangle has been used
        self.untangle_button_clicked = True
        self.first_untangle_click_done = True
        
        # Update the persistent layout button enabled state
        self._update_persistent_layout_button_state()

    def _handle_untangle(self) -> None:
        """Handles the untangle keyboard shortcut (Alt+U). Cycles through layouts."""
        if not self.untangle_values:
            self.untangle_values = app_config.DEFAULT_UNTANGLE_VALUES
            if ORIGINAL_LAYOUT not in self.untangle_values:
                self.untangle_values.append(ORIGINAL_LAYOUT)
        
        # Cycle to next value
        try:
            current_index = self.untangle_values.index(self.current_untangle_setting)
            next_index = (current_index + 1) % len(self.untangle_values)
            next_value = self.untangle_values[next_index]
        except ValueError:
            next_value = self.untangle_values[0] if self.untangle_values else 6
        
        # Apply the next layout
        self._apply_untangle_layout(next_value)

    @pyqtSlot()
    def update_graph_connection_buttons_state(self) -> None:
        selected_items = self.scene.selectedItems()
        
        selected_input_ports = []
        selected_output_ports = []
        selected_connection_items = []
        selected_input_bulk_areas = []
        selected_output_bulk_areas = []

        for item in selected_items:
            if isinstance(item, PortItem):
                if item.is_input:
                    selected_input_ports.append(item)
                else:
                    selected_output_ports.append(item)
            elif isinstance(item, ConnectionItem):
                selected_connection_items.append(item)
            # Check for BulkAreaItem selections
            elif getattr(item, 'is_input', None) is not None and getattr(item, 'parent_node', None) is not None:
                # This is likely a BulkAreaItem
                if item.is_input:
                    selected_input_bulk_areas.append(item)
                else:
                    selected_output_bulk_areas.append(item)

        # Connect button state
        can_connect = False
        potential_connections_to_make = []
        all_potential_connections_exist = True # Assume true until a non-existing one is found

        # Check for port-to-port connections
        if len(selected_output_ports) == 1 and len(selected_input_ports) >= 1:
            single_out = selected_output_ports[0]
            if single_out in selected_input_ports: # Self-connection attempt with the same item selected as both
                 pass # can_connect remains false
            else:
                for in_port in selected_input_ports:
                    if single_out == in_port: continue # Should not happen if selection logic is strict
                    potential_connections_to_make.append((single_out.port_name, in_port.port_name))
                    # Check if this specific connection doesn't exist
                    if (single_out.port_name, in_port.port_name) not in self.scene.connections:
                        all_potential_connections_exist = False
                if not potential_connections_to_make: # e.g. output selected, and the same port (if it were also input capable) selected as input
                    pass
                else:
                    can_connect = not all_potential_connections_exist # Only enable if at least one connection doesn't exist

        elif len(selected_input_ports) == 1 and len(selected_output_ports) >= 1:
            single_in = selected_input_ports[0]
            if single_in in selected_output_ports: # Self-connection attempt
                pass # can_connect remains false
            else:
                for out_port in selected_output_ports:
                    if single_in == out_port: continue
                    potential_connections_to_make.append((out_port.port_name, single_in.port_name))
                    # Check if this specific connection doesn't exist
                    if (out_port.port_name, single_in.port_name) not in self.scene.connections:
                        all_potential_connections_exist = False
                if not potential_connections_to_make:
                    pass
                else:
                    can_connect = not all_potential_connections_exist # Only enable if at least one connection doesn't exist
        
        # Check for bulk-to-port connections (OUT bulk + IN port)
        elif len(selected_output_bulk_areas) == 1 and len(selected_input_ports) == 1:
            source_bulk = selected_output_bulk_areas[0]
            target_port = selected_input_ports[0]
    
            if source_bulk.parent_node == target_port.parent_node and \
               (source_bulk.parent_node.is_split_origin or source_bulk.parent_node.is_split_part):
                pass # Disallow self-connection on split nodes
            else:
                # Use the bulk area's paired ports as sources
                source_ports = source_bulk.paired_ports
    
                if source_ports:
                    # Check if any source port is not yet connected to the target port
                    num_pairs = 0
                    num_already_connected = 0
                    for s_port in source_ports:
                        num_pairs += 1
                        if (s_port.port_name, target_port.port_name) in self.scene.connections:
                            num_already_connected += 1
    
                    if num_pairs > 0 and num_already_connected < num_pairs:
                        can_connect = True

        # Check for port-to-bulk connections (OUT port + IN bulk)
        elif len(selected_output_ports) == 1 and len(selected_input_bulk_areas) == 1:
            source_port = selected_output_ports[0]
            target_bulk = selected_input_bulk_areas[0]
    
            if source_port.parent_node == target_bulk.parent_node and \
                (source_port.parent_node.is_split_origin or source_port.parent_node.is_split_part):
                pass # Disallow self-connection on split nodes
            else:
                # Use the bulk area's paired ports as targets
                target_ports = target_bulk.paired_ports
    
                if target_ports:
                    # Check if the source port is not yet connected to all target ports
                    num_pairs = 0
                    num_already_connected = 0
                    for t_port in target_ports:
                        num_pairs += 1
                        if (source_port.port_name, t_port.port_name) in self.scene.connections:
                            num_already_connected += 1
    
                    if num_pairs > 0 and num_already_connected < num_pairs:
                        can_connect = True
        
        # Check for bulk area connections (IN/OUT bulk areas selected)
        elif (len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1):
            # Check if any paired ports between the bulk areas are not connected
            all_connected = True
            for input_bulk in selected_input_bulk_areas:
                for output_bulk in selected_output_bulk_areas:
                    input_node = input_bulk.parent_node
                    output_node = output_bulk.parent_node
                    if input_node == output_node:
                        continue
                    # Use paired ports from each bulk area
                    in_ports = input_bulk.paired_ports
                    out_ports = output_bulk.paired_ports
                    for i in range(min(len(in_ports), len(out_ports))):
                        output_port = out_ports[i]
                        input_port = in_ports[i]
                        if (output_port.port_name, input_port.port_name) not in self.scene.connections:
                            all_connected = False
                            break
                    if not all_connected:
                        break
                if not all_connected:
                    break
            can_connect = not all_connected # Enable if any potential connections are missing

        if self.graph_connect_action is not None:
            self.graph_connect_action.setEnabled(can_connect)

        # Disconnect button state
        can_disconnect = False
        if selected_connection_items: # Can always disconnect selected connection items
            can_disconnect = True
        elif selected_input_ports and selected_output_ports: # Only check port-based disconnect if no direct connections selected
            # Check if any selected input port is connected to any selected output port
            for out_port in selected_output_ports:
                for in_port in selected_input_ports:
                    if (out_port.port_name, in_port.port_name) in self.scene.connections:
                        can_disconnect = True
                        break
                if can_disconnect:
                    break
        # Check for bulk-to-port disconnections (OUT bulk + IN port)
        elif len(selected_output_bulk_areas) == 1 and len(selected_input_ports) == 1:
            source_bulk = selected_output_bulk_areas[0]
            target_port = selected_input_ports[0]
    
            # Use the bulk area's paired ports as sources
            source_ports = source_bulk.paired_ports
    
            if source_ports:
                # Check if any source port is connected to the target port
                for s_port in source_ports:
                    if (s_port.port_name, target_port.port_name) in self.scene.connections:
                        can_disconnect = True
                        break
        # Check for port-to-bulk disconnections (OUT port + IN bulk)
        elif len(selected_output_ports) == 1 and len(selected_input_bulk_areas) == 1:
            source_port = selected_output_ports[0]
            target_bulk = selected_input_bulk_areas[0]
    
            # Use the bulk area's paired ports as targets
            target_ports = target_bulk.paired_ports
    
            if target_ports:
                # Check if the source port is connected to any target port
                for t_port in target_ports:
                    if (source_port.port_name, t_port.port_name) in self.scene.connections:
                        can_disconnect = True
                        break
        # Check for bulk area disconnections
        elif len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1:
            # For each pair of input and output bulk areas
            for input_bulk in selected_input_bulk_areas:
                for output_bulk in selected_output_bulk_areas:
                    # Get the parent nodes
                    input_node = input_bulk.parent_node
                    output_node = output_bulk.parent_node
    
                    # Skip if same node
                    if input_node == output_node:
                        continue
    
                    # Use paired ports from each bulk area
                    in_ports = input_bulk.paired_ports
                    out_ports = output_bulk.paired_ports
    
                    # Check for connections between paired ports
                    for i in range(min(len(in_ports), len(out_ports))):
                        output_port = out_ports[i]
                        input_port = in_ports[i]
                        if (output_port.port_name, input_port.port_name) in self.scene.connections:
                            can_disconnect = True
                            break
                    if can_disconnect:
                        break
                if can_disconnect:
                    break
        
        if self.graph_disconnect_action is not None:
            self.graph_disconnect_action.setEnabled(can_disconnect)


    @pyqtSlot()
    def handle_connect_action(self) -> None:
        selected_items = self.scene.selectedItems()
        
        selected_input_ports = []
        selected_output_ports = []
        selected_input_bulk_areas = []
        selected_output_bulk_areas = []

        for item in selected_items:
            if isinstance(item, PortItem):
                if item.is_input:
                    selected_input_ports.append(item)
                else:
                    selected_output_ports.append(item)
            # Check for BulkAreaItem selections
            elif getattr(item, 'is_input', None) is not None and getattr(item, 'parent_node', None) is not None:
                # This is likely a BulkAreaItem
                if item.is_input:
                    selected_input_bulk_areas.append(item)
                else:
                    selected_output_bulk_areas.append(item)
        
        # Button should be disabled if selection is invalid, so no need for QMessageBox here.

        connections_made = 0
        
        # First, check if we have a bulk-to-port or port-to-bulk selection
        is_bulk_to_port = len(selected_output_bulk_areas) == 1 and len(selected_input_ports) >= 1
        is_port_to_bulk = len(selected_output_ports) >= 1 and len(selected_input_bulk_areas) == 1
        
        if is_bulk_to_port:
            source_bulk = selected_output_bulk_areas[0]
            # Get the first selected input port as the target
            target_port = selected_input_ports[0]
            
            if source_bulk.parent_node == target_port.parent_node and \
               (source_bulk.parent_node.is_split_origin or source_bulk.parent_node.is_split_part):
                logger.debug("Skipping self-connection on split node")
            else:
                # Use the bulk area's paired ports as sources
                source_ports = source_bulk.paired_ports
        
                if source_ports:
                    # Connect all source ports to the single target port
                    for s_port in source_ports:
                        if (s_port.port_name, target_port.port_name) not in self.scene.connections:
                            logger.debug(f"Attempting bulk-to-port connection: {s_port.port_name} -> {target_port.port_name}")
                            if s_port.is_midi:
                                if self.scene.jack_connection_handler.make_midi_connection(s_port.port_name, target_port.port_name):
                                    connections_made += 1
                            else:
                                if self.scene.jack_connection_handler.make_connection(s_port.port_name, target_port.port_name):
                                    connections_made += 1
        
        elif is_port_to_bulk:
            # Get the first selected output port as the source
            source_port = selected_output_ports[0]
            target_bulk = selected_input_bulk_areas[0]
        
            if source_port.parent_node == target_bulk.parent_node and \
                (source_port.parent_node.is_split_origin or target_bulk.parent_node.is_split_part):
                logger.debug("Skipping self-connection on split node")
            else:
                # Use the bulk area's paired ports as targets
                target_ports = target_bulk.paired_ports
        
                if target_ports:
                    # Connect the single source port to all target ports
                    for t_port in target_ports:
                        if (source_port.port_name, t_port.port_name) not in self.scene.connections:
                            logger.debug(f"Attempting port-to-bulk connection: {source_port.port_name} -> {t_port.port_name}")
                            if source_port.is_midi:
                                if self.scene.jack_connection_handler.make_midi_connection(source_port.port_name, t_port.port_name):
                                    connections_made += 1
                            else:
                                if self.scene.jack_connection_handler.make_connection(source_port.port_name, t_port.port_name):
                                    connections_made += 1
        
        # Handle port-to-port connections (only if not bulk-to-port or port-to-bulk)
        elif len(selected_output_ports) == 1 and len(selected_input_ports) >= 1:
            output_port_item = selected_output_ports[0]
            for input_port_item in selected_input_ports:
                # Prevent connecting a port to itself
                if output_port_item == input_port_item:
                    logger.debug(f"Skipping self-connection for port: {output_port_item.port_name}")
                    continue
                logger.debug(f"Attempting to connect: {output_port_item.port_name} -> {input_port_item.port_name}")
                # Use JackConnectionHandler
                if output_port_item.is_midi: # Assuming PortItem has is_midi
                    if self.scene.jack_connection_handler.make_midi_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made +=1
                else:
                    if self.scene.jack_connection_handler.make_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made +=1
        elif len(selected_input_ports) == 1 and len(selected_output_ports) >= 1:
            input_port_item = selected_input_ports[0]
            for output_port_item in selected_output_ports:
                 # Prevent connecting a port to itself
                if output_port_item == input_port_item:
                    logger.debug(f"Skipping self-connection for port: {output_port_item.port_name}")
                    continue
                logger.debug(f"Attempting to connect: {output_port_item.port_name} -> {input_port_item.port_name}")
                # Use JackConnectionHandler
                if output_port_item.is_midi: # Assuming PortItem has is_midi
                    if self.scene.jack_connection_handler.make_midi_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made += 1
                else:
                    if self.scene.jack_connection_handler.make_connection(output_port_item.port_name, input_port_item.port_name):
                        connections_made += 1
        
        # Handle bulk area connections
        elif len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1:
            # For each pair of input and output bulk areas
            for input_bulk_area_item in selected_input_bulk_areas:
                for output_bulk_area_item in selected_output_bulk_areas:
                    # Get the parent nodes
                    input_node = input_bulk_area_item.parent_node
                    output_node = output_bulk_area_item.parent_node
    
                    # Skip if same node
                    if input_node == output_node:
                        continue
    
                    # Use paired ports from each bulk area
                    input_port_items = input_bulk_area_item.paired_ports
                    output_port_items = output_bulk_area_item.paired_ports
    
                    # Convert to lists of port names for JackConnectionHandler
                    input_port_names = [p.port_name for p in input_port_items]
                    output_port_names = [p.port_name for p in output_port_items]
    
                    if output_port_names and input_port_names:
                        logger.debug(f"Attempting bulk connection between {output_node.client_name} (OUT) and {input_node.client_name} (IN)")
                        self.scene.jack_connection_handler.make_multiple_connections(output_port_names, input_port_names)
                        connections_made += 1
                    else:
                        logger.debug(f"Skipping bulk connection between {output_node.client_name} and {input_node.client_name} due to empty port lists.")
        
        if connections_made > 0:
            if self.statusBar() is not None:
                self.statusBar().showMessage(f"{connections_made} connection(s) attempted.", 3000)
        else:
            # Only show this if an attempt was actually possible (action was enabled)
            if self.graph_connect_action is not None and self.graph_connect_action.isEnabled(): # Check if action was enabled
                 if self.statusBar() is not None:
                     self.statusBar().showMessage("No new connections were made (possibly already connected or error).", 3000)
        # self.update_graph_connection_buttons_state() # No longer needed here, scene signal will trigger it
        self._update_graph_undo_redo_buttons_state() # Update undo/redo buttons


    @pyqtSlot()
    def handle_disconnect_action(self) -> None:
        selected_items = self.scene.selectedItems()
        disconnections_made = 0

        selected_connection_items = [item for item in selected_items if isinstance(item, ConnectionItem)]
        selected_port_items = [item for item in selected_items if isinstance(item, PortItem)]
        selected_input_bulk_areas = []
        selected_output_bulk_areas = []

        # Check for BulkAreaItem selections
        for item in selected_items:
            if getattr(item, 'is_input', None) is not None and getattr(item, 'parent_node', None) is not None:
                # This is likely a BulkAreaItem
                if item.is_input:
                    selected_input_bulk_areas.append(item)
                else:
                    selected_output_bulk_areas.append(item)

        if selected_connection_items:
            for conn_item in selected_connection_items:
                if conn_item.source_port and conn_item.dest_port:
                    logger.debug(f"Attempting to disconnect via ConnectionItem: {conn_item.source_port.port_name} -> {conn_item.dest_port.port_name}")
                    # Use JackConnectionHandler
                    if conn_item.source_port.is_midi: # Assuming PortItem has is_midi
                        if self.scene.jack_connection_handler.break_midi_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name):
                            disconnections_made += 1
                    else:
                        if self.scene.jack_connection_handler.break_connection(conn_item.source_port.port_name, conn_item.dest_port.port_name):
                            disconnections_made += 1
                else:
                    logger.warning(f"Warning: A selected ConnectionItem has missing source or destination port. Skipping.")
        
        elif selected_port_items:
            selected_input_ports = []
            selected_output_ports = []
            for item in selected_port_items:
                if item.is_input:
                    selected_input_ports.append(item)
                else:
                    selected_output_ports.append(item)

            if selected_input_ports and selected_output_ports: # Ensure both lists have items
                for output_port_item in selected_output_ports:
                    for input_port_item in selected_input_ports:
                        connection_key = (output_port_item.port_name, input_port_item.port_name)
                        if connection_key in self.scene.connections:
                            logger.debug(f"Attempting to disconnect via PortItems: {output_port_item.port_name} -> {input_port_item.port_name}")
                            # Use JackConnectionHandler
                            if output_port_item.is_midi: # Assuming PortItem has is_midi
                                if self.scene.jack_connection_handler.break_midi_connection(output_port_item.port_name, input_port_item.port_name):
                                    disconnections_made += 1
                            else:
                                if self.scene.jack_connection_handler.break_connection(output_port_item.port_name, input_port_item.port_name):
                                    disconnections_made += 1
        
        # Handle bulk-to-port disconnections (OUT bulk + IN port)
        elif len(selected_output_bulk_areas) == 1 and len(selected_input_ports) == 1:
            source_bulk = selected_output_bulk_areas[0]
            target_port = selected_input_ports[0]
        
            # Use the bulk area's paired ports as sources
            source_ports = source_bulk.paired_ports
        
            if source_ports:
                # Disconnect all source ports from the single target port
                for s_port in source_ports:
                    if (s_port.port_name, target_port.port_name) in self.scene.connections:
                        logger.debug(f"Attempting bulk-to-port disconnection: {s_port.port_name} -> {target_port.port_name}")
                        if s_port.is_midi:
                            if self.scene.jack_connection_handler.break_midi_connection(s_port.port_name, target_port.port_name):
                                disconnections_made += 1
                        else:
                            if self.scene.jack_connection_handler.break_connection(s_port.port_name, target_port.port_name):
                                disconnections_made += 1
        
        # Handle port-to-bulk disconnections (OUT port + IN bulk)
        elif len(selected_output_ports) == 1 and len(selected_input_bulk_areas) == 1:
            source_port = selected_output_ports[0]
            target_bulk = selected_input_bulk_areas[0]
        
            # Use the bulk area's paired ports as targets
            target_ports = target_bulk.paired_ports
        
            if target_ports:
                # Disconnect the single source port from all target ports
                for t_port in target_ports:
                    if (source_port.port_name, t_port.port_name) in self.scene.connections:
                        logger.debug(f"Attempting port-to-bulk disconnection: {source_port.port_name} -> {t_port.port_name}")
                        if source_port.is_midi:
                            if self.scene.jack_connection_handler.break_midi_connection(source_port.port_name, t_port.port_name):
                                disconnections_made += 1
                        else:
                            if self.scene.jack_connection_handler.break_connection(source_port.port_name, t_port.port_name):
                                disconnections_made += 1
        
        # Handle bulk area disconnections
        elif len(selected_input_bulk_areas) >= 1 and len(selected_output_bulk_areas) >= 1:
            # For each pair of input and output bulk areas
            for input_bulk in selected_input_bulk_areas:
                for output_bulk in selected_output_bulk_areas:
                    # Get the parent nodes
                    input_node = input_bulk.parent_node
                    output_node = output_bulk.parent_node
        
                    # Skip if same node
                    if input_node == output_node:
                        continue
        
                    # Use paired ports from each bulk area
                    in_ports = input_bulk.paired_ports
                    out_ports = output_bulk.paired_ports
        
                    # Check for connections between paired ports
                    for i in range(min(len(in_ports), len(out_ports))):
                        output_port = out_ports[i]
                        input_port = in_ports[i]
                        connection_key = (output_port.port_name, input_port.port_name)
                        if connection_key in self.scene.connections:
                            logger.debug(f"Attempting bulk disconnection: {output_port.port_name} -> {input_port.port_name}")
                            if output_port.is_midi:
                                if self.scene.jack_connection_handler.break_midi_connection(output_port.port_name, input_port.port_name):
                                    disconnections_made += 1
                            else:
                                if self.scene.jack_connection_handler.break_connection(output_port.port_name, input_port.port_name):
                                    disconnections_made += 1

        if disconnections_made > 0:
            if self.statusBar() is not None:
                self.statusBar().showMessage(f"{disconnections_made} disconnection(s) attempted.", 3000)
        else:
            # Only show this if an attempt was actually possible (action was enabled)
            if self.graph_disconnect_action is not None and self.graph_disconnect_action.isEnabled(): # Check if action was enabled
                if self.statusBar() is not None:
                    self.statusBar().showMessage("No connections were broken (possibly not connected or error).", 3000)
        # self.update_graph_connection_buttons_state() # No longer needed here, scene signal will trigger it
        self._update_graph_undo_redo_buttons_state() # Update undo/redo buttons

    @pyqtSlot()
    @pyqtSlot()
    def _handle_node_filter_change(self) -> None:
        """Handles text changes in the node filter box."""
        filter_text = self.node_filter_box.text()
        self.scene.filter_nodes(filter_text)

    def handle_jack_shutdown(self) -> None:
        logger.debug("JACK has shut down. Disabling graph interaction.")
        # Disable further interaction, maybe show a message
        self.scene.clear_graph()
        self.view.setEnabled(False)
        # Check if statusBar exists before using it
        if self.statusBar() is not None:
              self.statusBar().showMessage("JACK connection lost. Waiting for reconnection...", 0)

    def handle_jack_reconnected(self) -> None:
        """Handle JACK client reconnection after server restart.

        Re-enables the graph view and updates client references so the
        graph can resume normal operation.
        """
        logger.info("GraphMainWindow: JACK reconnected, re-enabling graph.")

        # Update client references
        jack_service = get_jack_service()
        new_client = jack_service.client
        self.jack_client = new_client
        self.scene.jack_client = new_client
        self.scene.graph_jack_handler.jack_client = new_client

        # Re-enable the view
        self.view.setEnabled(True)

        # Show status message
        if self.statusBar() is not None:
            self.statusBar().showMessage("JACK connection restored.", 5000)

    def closeEvent(self, event: 'QCloseEvent') -> None:
        """Ensure JACK client is cleaned up when closing the window."""
        logger.debug("Closing application...")
        # Disconnect signals that might try to access the scene after it's deleted
        try:
            self.scene.selectionChanged.disconnect(self.scene.interaction_handler.handle_selection_changed)
        except TypeError: # Signal might already be disconnected or handler doesn't exist
            pass # Ignore if disconnection fails
        # Save node positions and zoom level before shutting down
        # REMOVED: Saving on exit is no longer desired. States are saved immediately on change.
        # current_zoom_level = self.view.get_zoom_level()
        # print(f"MainWindow closeEvent: current_zoom_level from view = {current_zoom_level}") # DEBUG
        # self.scene.save_node_states(graph_zoom_level=current_zoom_level) # Also ensure this uses save_node_states if kept
        # self.jack_handler.stop() # Removed, main client lifecycle managed by JackConnectionManager
        event.accept()

    def get_top_toolbar_layout(self) -> Optional[QHBoxLayout]:
        """Returns the top toolbar layout for external modification.
        
        Returns:
            QHBoxLayout: The top toolbar layout containing Connect, Disconnect, Undo, and Redo buttons
        """
        # Store a reference to the top_toolbar_layout as a class member
        if self._top_toolbar_layout is not None:
            return self._top_toolbar_layout
            
        if self.centralWidget() and isinstance(self.centralWidget().layout(), QVBoxLayout):
            main_layout = self.centralWidget().layout()
            if main_layout.count() > 0:
                # The first item should be the top_toolbar_layout
                item = main_layout.itemAt(0)
                if item and item.layout() and isinstance(item.layout(), QHBoxLayout):
                    # Cache the reference for future use
                    self._top_toolbar_layout = item.layout()
                    return self._top_toolbar_layout
        
        return None

    def get_bottom_toolbar_layout(self) -> Optional[QHBoxLayout]:
        """Returns the bottom toolbar layout for external modification.
        
        Returns:
            QHBoxLayout: The bottom toolbar layout containing Presets, Untangle, and other controls
        """
        if self._bottom_toolbar_layout is not None:
            return self._bottom_toolbar_layout
        return None

    def save_current_layout(self) -> None:
        """Save the current node layout to the node_positions.json file.
        This is called when the user selects "Save current layout" from the context menu.
        """
        # Get the current node states from the scene
        current_states = self.scene.get_node_states()
        
        # Save the node states to the config file
        self.scene.node_config_manager.save_node_states_as_default(current_states)
        
        # Update the in-memory initial_node_positions variable
        # This ensures that when cycling back to the original layout with the Untangle button,
        # the saved layout will be used
        self.initial_node_positions = copy.deepcopy(current_states)
        
        # Show a status message
        if self.statusBar() is not None:
            self.statusBar().showMessage("Current layout saved as default and will be used as 'Original layout' in Untangle menu", 5000)
