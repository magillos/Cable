"""
TabUIManager - Manages the setup of UI tabs
"""

from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QSpacerItem,
                             QSizePolicy, QWidget, QTextEdit, QComboBox, QPushButton,
                             QToolButton, QMenu) # Added QToolButton, QMenu
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon, QAction
import threading # Added for graph tab

from cables.ui.port_tree_widget import DragPortTreeWidget, DropPortTreeWidget
from cables.ui.shared_widgets import create_action_button

# Imports for Graph Tab
import graph
import graph.jack_handler
import graph.main_window
# import graph.gui_view # If needed directly

GraphJackHandler = graph.jack_handler.GraphJackHandler # Updated to GraphJackHandler
GraphMainWindow = graph.main_window.MainWindow
# GraphGuiView = graph.gui_view.JackGraphView # If JackGraphView is obtained from MainWindow instance, this isn't needed here

from cable_core import app_config

class TabUIManager:
    """
    Manages the setup of UI tabs in the Cables application.
    
    This class provides methods to set up the UI for the different tabs
    in the application, including the port tabs, pw-top tab, and latency test tab.
    """
    
    def setup_port_tab(self, manager, tab_widget, tab_name, port_type):
        """
        Set up a port tab (Audio or MIDI).
        
        Args:
            manager: The JackConnectionManager instance
            tab_widget: The widget to set up as a port tab
            tab_name: The name of the tab ('Audio' or 'MIDI')
            port_type: The type of ports to display ('audio' or 'midi')
        """
        # Create main layout for the tab
        layout = QVBoxLayout(tab_widget)

        # Create button widget and layout at the top
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create buttons using shared_widgets factory
        if port_type == 'audio':
            actual_connect_action = manager.action_manager.audio_connect_action
            actual_disconnect_action = manager.action_manager.audio_disconnect_action
        elif port_type == 'midi':
            actual_connect_action = manager.action_manager.midi_connect_action
            actual_disconnect_action = manager.action_manager.midi_disconnect_action
        else: # Fallback, should not be reached for valid port_types
            actual_connect_action = None
            actual_disconnect_action = None

        connect_button = create_action_button(
            parent_widget=button_widget,
            action=actual_connect_action,
            tooltip="Connect selected items <span style='color:grey'>C</span>"
        )
        
        disconnect_button = create_action_button(
            parent_widget=button_widget,
            action=actual_disconnect_action,
            tooltip="Disconnect selected items <span style='color:grey'>D/Del</span>"
        )

        presets_action = manager.action_manager.presets_action
        presets_button = create_action_button(
            parent_widget=button_widget,
            action=presets_action,
            tooltip="Manage Presets"
        )
        presets_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        
        # Add Node Visibility button
        node_visibility_action = QAction("Clients Visibility", button_widget)
        node_visibility_action.triggered.connect(manager.show_node_visibility_dialog)
        node_visibility_button = create_action_button(
            parent_widget=button_widget,
            action=node_visibility_action,
            tooltip="Configure which nodes should be visible"
        )

        # Add buttons to layout with stretches for centering
        button_layout.addStretch()  # Push buttons to center
        button_layout.addWidget(connect_button)
        button_layout.addWidget(disconnect_button)
        button_layout.addWidget(presets_button)
        button_layout.addWidget(node_visibility_button)  # Add in line with other buttons
        button_layout.addStretch()  # Push buttons to center

        # Add button widget to main layout
        layout.addWidget(button_widget)

        # Create port list layouts
        input_layout = QVBoxLayout()
        output_layout = QVBoxLayout()
        input_label = QLabel(f' {tab_name} Input Ports')
        output_label = QLabel(f' {tab_name} Output Ports')
        
        font = QFont()
        font.setBold(True)
        input_label.setFont(font)
        output_label.setFont(font)
        input_label.setStyleSheet(f"color: {manager.text_color.name()};")
        output_label.setStyleSheet(f"color: {manager.text_color.name()};")
        
        # Create tree widgets with appropriate roles, passing the highlight manager
        input_tree = DropPortTreeWidget(highlight_manager=manager.highlight_manager, parent=tab_widget)
        output_tree = DragPortTreeWidget(highlight_manager=manager.highlight_manager, parent=tab_widget)
        
        # Create connection visualization
        from PyQt6.QtWidgets import QGraphicsScene
        from cables.ui.connection_view import ConnectionView
        connection_scene = QGraphicsScene()
        connection_view = ConnectionView(connection_scene)
        # Connect to JACK client signals for real-time updates
        connection_view.connect_to_jack_signals(manager.client)
        
        # Apply styles
        input_tree.setStyleSheet(manager.list_stylesheet())
        output_tree.setStyleSheet(manager.list_stylesheet())
        connection_view.setStyleSheet(f"background: {manager.background_color.name()}; border: none;")
        
        # Add spacers and labels to layouts
        input_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))
        output_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))
        
        input_layout.addWidget(input_label)
        input_layout.addWidget(input_tree)
        
        output_layout.addWidget(output_label)
        output_layout.addWidget(output_tree)
        
        # Create middle layout with connection view
        middle_layout = QVBoxLayout()
        # Add spacer to align with port areas
        middle_layout.addSpacerItem(QSpacerItem(20, 30, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))
        middle_layout.addWidget(connection_view)
        
        # Create middle layout widget
        middle_layout_widget = QWidget()
        middle_layout_widget.setLayout(middle_layout)
        middle_layout_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        # Load connection view width from config or use app_config default
        connection_view_initial_width = manager.config_manager.get_int_setting("CONNECTION_VIEW_INITIAL_WIDTH", app_config.CONNECTION_VIEW_INITIAL_WIDTH)
        middle_layout_widget.setFixedWidth(connection_view_initial_width)
        
        # Combine layouts
        content_layout = QHBoxLayout()
        content_layout.addLayout(output_layout)
        content_layout.addWidget(middle_layout_widget)
        content_layout.addLayout(input_layout)
        layout.addLayout(content_layout)
        
        # Store references in manager
        if port_type == 'audio':
            manager.input_tree = input_tree
            manager.output_tree = output_tree
            manager.connection_scene = connection_scene
            manager.connection_view = connection_view
            manager.connect_button = connect_button
            manager.disconnect_button = disconnect_button
            # Refresh button reference removed
            manager.presets_button = presets_button
            manager.audio_node_visibility_button = node_visibility_button
            
            # Signal connections are now handled by QAction via button.setDefaultAction()
            # in create_action_button.
            # The QActions (e.g., audio_connect_action, presets_action) must be connected
            # to their respective handlers within the ActionManager or JackConnectionManager.
            # The enabled state of presets_button is also handled by presets_action.
            
            # Filter signals are now connected in PortManager.set_trees() after trees are created.
            # No need to connect them here anymore.

        elif port_type == 'midi':
            manager.midi_input_tree = input_tree
            manager.midi_output_tree = output_tree
            manager.midi_connection_scene = connection_scene
            manager.midi_connection_view = connection_view
            manager.midi_connect_button = connect_button
            manager.midi_disconnect_button = disconnect_button
            # Refresh button reference removed
            manager.midi_presets_button = presets_button
            manager.midi_node_visibility_button = node_visibility_button
            
            # Signal connections are now handled by QAction via button.setDefaultAction()
            # in create_action_button.
            # The QActions (e.g., midi_connect_action, presets_action) must be connected
            # to their respective handlers within the ActionManager or JackConnectionManager.
            # The enabled state of presets_button is also handled by presets_action.
        
        # Initial font size is now applied by UIStateManager after it's initialized
        # manager._apply_port_list_font_size() # Removed call

    def setup_pwtop_tab(self, manager, tab_widget):
        """
        Set up the pw-top statistics tab.
        
        Args:
            manager: The JackConnectionManager instance
            tab_widget: The widget to set up as the pw-top tab
        """
        layout = QVBoxLayout(tab_widget)
        
        # Create text display widget
        pwtop_text_widget = QTextEdit()
        pwtop_text_widget.setReadOnly(True)
        pwtop_text_widget.setStyleSheet(f"""
            QTextEdit {{
                background-color: {manager.background_color.name()};
                color: {manager.text_color.name()};
                font-family: monospace;
                font-size: {manager.config_manager.get_int_setting("PWTOP_FONT_SIZE_PT", app_config.PWTOP_FONT_SIZE_PT)}pt;
            }}
        """)
        layout.addWidget(pwtop_text_widget)
        
        # Assign the widget to the manager
        manager.pwtop_text = pwtop_text_widget
        
        # Instantiate PwTopMonitor and store it on the manager
        from cables.features.pwtop_monitor import PwTopMonitor
        manager.pwtop_monitor = PwTopMonitor(manager, pwtop_text_widget)
    
    def setup_latency_tab(self, manager, tab_widget):
        """
        Set up the Latency Test tab.
        
        Args:
            manager: The JackConnectionManager instance
            tab_widget: The widget to set up as the latency test tab
        """
        layout = QVBoxLayout(tab_widget)
        
        # Instantiate LatencyTester
        from cables.features.latency_tester import LatencyTester
        manager.latency_tester = LatencyTester(manager)
        
        # Instructions Label
        instructions_text = (
            "<b>Instructions:</b><br><br>"
            "1. Ensure 'jack_delay', 'jack-delay' or 'jack_iodelay' (via 'jack-example-tools') is installed.<br>"
            "2. Physically connect an output and input of your audio interface using a cable (loopback).<br>"
            "3. Select the corresponding Input (Capture) and Output (Playback) ports using the dropdowns below.<br>"
            "4. Click 'Start Measurement'. The selected ports will be automatically connected to jack_delay.<br>"
            "(you can click 'Start Measurement' first and then try different ports)<br>"
            "5. <b><font color='orange'>Warning:</font></b> Start with low volume/gain levels on your interface "
            "to avoid potential damage from the test signal.<br><br>"
            "After the signal is detected, the average measured round-trip latency will be shown after 10 seconds.<br><br><br><br><br>"
        )
        instructions_label = QLabel(instructions_text)
        instructions_label.setWordWrap(True)
        instructions_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        instructions_label.setStyleSheet(f"color: {manager.text_color.name()}; font-size: 11pt;")
        layout.addWidget(instructions_label)
        
        # Combo Boxes for Port Selection
        manager.latency_input_combo = QComboBox()
        manager.latency_input_combo.setPlaceholderText("Select Input (Capture)...")
        manager.latency_input_combo.setStyleSheet(manager.list_stylesheet())
        
        manager.latency_output_combo = QComboBox()
        manager.latency_output_combo.setPlaceholderText("Select Output (Playback)...")
        manager.latency_output_combo.setStyleSheet(manager.list_stylesheet())
        
        # Refresh Button
        manager.latency_refresh_button = QPushButton("Refresh Ports")
        manager.latency_refresh_button.setStyleSheet(manager.button_stylesheet())
        manager.latency_refresh_button.clicked.connect(manager.latency_tester._populate_latency_combos)
        
        # Combo Boxes Layout
        combo_box_container = QWidget()
        combo_box_layout = QVBoxLayout(combo_box_container)
        combo_box_layout.setContentsMargins(0, 0, 0, 0)
        
        input_combo_layout = QHBoxLayout()
        input_combo_layout.addWidget(manager.latency_input_combo)
        input_combo_layout.addStretch(1)
        combo_box_layout.addLayout(input_combo_layout)
        
        output_combo_layout = QHBoxLayout()
        output_combo_layout.addWidget(manager.latency_output_combo)
        output_combo_layout.addStretch(1)
        combo_box_layout.addLayout(output_combo_layout)
        
        layout.addWidget(combo_box_container)
        
        # Refresh Button Layout
        refresh_button_layout = QHBoxLayout()
        refresh_button_layout.addWidget(manager.latency_refresh_button)
        refresh_button_layout.addStretch(1)
        layout.addLayout(refresh_button_layout)
        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))
        
        # Start/Stop Buttons Layout
        start_stop_button_layout = QHBoxLayout()
        manager.latency_run_button = QPushButton('Start measurement')
        manager.latency_run_button.setStyleSheet(manager.button_stylesheet())
        manager.latency_run_button.clicked.connect(manager.latency_tester.run_latency_test)
        
        manager.latency_stop_button = QPushButton('Stop')
        manager.latency_stop_button.setStyleSheet(manager.button_stylesheet())
        manager.latency_stop_button.clicked.connect(manager.latency_tester.stop_latency_test)
        manager.latency_stop_button.setEnabled(False)
        
        start_stop_button_layout.addWidget(manager.latency_run_button)
        start_stop_button_layout.addWidget(manager.latency_stop_button)
        start_stop_button_layout.addStretch(2)
        layout.addLayout(start_stop_button_layout)
        
        # Raw Output Toggle Checkbox
        from PyQt6.QtWidgets import QCheckBox
        manager.latency_raw_output_checkbox = QCheckBox("Show Raw Output (Continuous)")
        manager.latency_raw_output_checkbox.setToolTip("If 'ON', measurement has to be stopped manually with 'Stop' button")
        manager.latency_raw_output_checkbox.setStyleSheet(f"color: {manager.text_color.name()};")
        
        # Results Text Edit
        manager.latency_results_text = QTextEdit()
        manager.latency_results_text.setReadOnly(True)
        manager.latency_results_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {manager.background_color.name()};
                color: {manager.text_color.name()};
                font-family: monospace;
                font-size: 14pt;
            }}
        """)
        manager.latency_results_text.setText("Ready to test.")
        layout.addWidget(manager.latency_results_text, 1)
        layout.addWidget(manager.latency_raw_output_checkbox)  # Add checkbox below results
        
        # Populate combo boxes and connect signals
        manager.latency_tester._populate_latency_combos()
        manager.latency_input_combo.currentIndexChanged.connect(manager.latency_tester._on_latency_input_selected)
        manager.latency_output_combo.currentIndexChanged.connect(manager.latency_tester._on_latency_output_selected)

    def setup_graph_tab(self, manager, tab_widget):
        """
        Set up the Graph tab.

        Args:
            manager: The JackConnectionManager instance
            tab_widget: The widget to set up as the graph tab
        """
        layout = QVBoxLayout(tab_widget)
        tab_widget.setLayout(layout) # Ensure layout is set for the tab_widget
        
        # The Graph tab will now use the main jack.Client from JackConnectionManager (manager.client)
        # No separate GraphJackHandler instance is created here anymore.

        # Instantiate MainWindow for the graph, passing the main jack.Client,
        # the JackConnectionManager (for signals), and connection_history.
        # The preset_handler_ref is still needed for preset functionality within the graph.
        manager.graph_main_window = GraphMainWindow(
            jack_client=manager.client, # Pass the main jack.Client instance
            connection_manager=manager, # Pass the JackConnectionManager for signals
            preset_handler_ref=manager.preset_handler,
            connection_history_ref=manager.connection_history
            # The graph's MainWindow will internally create its GraphJackHandler
            # and JackGraphScene, passing the jack_client and connection_manager down.
        )
        
        # Get the central widget (JackGraphView) from the graph's MainWindow
        graph_view_widget = manager.graph_main_window.centralWidget()

        if graph_view_widget:
            # Make sure the view can accept keyboard input - critical for shortcuts
            from PyQt6.QtCore import Qt
            graph_view_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            
            # Set tab order to ensure the view gets focus when tab is clicked
            tab_widget.setTabOrder(tab_widget, graph_view_widget)
            
            # Add the widget to the layout
            layout.addWidget(graph_view_widget)
            
            # Add zoom actions directly to the view widget - this is crucial for shortcuts
            if hasattr(manager.graph_main_window, 'zoom_in_action') and manager.graph_main_window.zoom_in_action:
                graph_view_widget.addAction(manager.graph_main_window.zoom_in_action)
            if hasattr(manager.graph_main_window, 'zoom_out_action') and manager.graph_main_window.zoom_out_action:
                graph_view_widget.addAction(manager.graph_main_window.zoom_out_action)
                
            # Create Node Visibility button and add it to the main window's top toolbar layout
            if hasattr(manager.graph_main_window, 'preset_button') and manager.graph_main_window.preset_button:
                # Create the Node Visibility button
                graph_node_visibility_action = QAction("Clients Visibility", manager.graph_main_window)
                graph_node_visibility_action.triggered.connect(manager.show_node_visibility_dialog)
                graph_node_visibility_button = create_action_button(
                    parent_widget=manager.graph_main_window,
                    action=graph_node_visibility_action,
                    tooltip="Configure which nodes should be visible"
                )
                
                # Try to get the top toolbar layout
                top_toolbar_layout = None
                if hasattr(manager.graph_main_window, 'get_top_toolbar_layout'):
                    top_toolbar_layout = manager.graph_main_window.get_top_toolbar_layout()
                
                if top_toolbar_layout:
                    # Get the index of the last stretch to insert before it
                    for i in range(top_toolbar_layout.count()):
                        item = top_toolbar_layout.itemAt(i)
                        # We want to insert before the ending stretch
                        if item.spacerItem() and i > 0:  # Skip the first stretch
                            top_toolbar_layout.insertWidget(i, graph_node_visibility_button)
                            break
                    else:
                        # Fallback if no ending stretch found - add after preset button
                        preset_index = -1
                        for i in range(top_toolbar_layout.count()):
                            item = top_toolbar_layout.itemAt(i)
                            if item.widget() == manager.graph_main_window.preset_button:
                                preset_index = i
                                break
                        
                        if preset_index != -1:
                            top_toolbar_layout.insertWidget(preset_index + 1, graph_node_visibility_button)
                        else:
                            # Just add it at the end
                            top_toolbar_layout.addWidget(graph_node_visibility_button)
                else:
                    # Create a separate button container if we can't access the top toolbar
                    button_container = QWidget()
                    button_layout = QHBoxLayout(button_container)
                    button_layout.setContentsMargins(0, 0, 0, 0)
                    button_layout.addStretch(1)
                    button_layout.addWidget(graph_node_visibility_button)
                    button_layout.addStretch(1)
                    layout.insertWidget(0, button_container)
                
                # Store a reference to the graph tab's node visibility button
                manager.graph_node_visibility_button = graph_node_visibility_button
                
                # Add to the internal controls to handle fullscreen mode
                if hasattr(manager.graph_main_window, '_internal_controls'):
                    manager.graph_main_window._internal_controls.append(graph_node_visibility_button)
        else:
            # Fallback if central widget is None
            error_label = QLabel("Could not load Graph View.")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(error_label)
            
        # Add zoom actions to the tab_widget as well for shortcuts to work when tab is active
        if hasattr(manager.graph_main_window, 'zoom_in_action') and manager.graph_main_window.zoom_in_action:
            tab_widget.addAction(manager.graph_main_window.zoom_in_action)
        if hasattr(manager.graph_main_window, 'zoom_out_action') and manager.graph_main_window.zoom_out_action:
            tab_widget.addAction(manager.graph_main_window.zoom_out_action)

        # Store a reference to the graph tab's preset button on the connection manager
        # so PresetHandler can find it.
        if hasattr(manager.graph_main_window, 'preset_button'):
            manager.graph_tab_presets_button = manager.graph_main_window.preset_button
        else:
            manager.graph_tab_presets_button = None
            
        # The graph's Jack client (the main client) is managed by JackConnectionManager,
        # so no separate thread or start call is needed here for a graph-specific handler.
            
        # Add an explicit refresh call after a short delay to populate the graph initially.
        # This is still useful as the JACK client might take a moment to be fully ready
        # or for initial events to propagate.
        if hasattr(manager, 'graph_main_window') and manager.graph_main_window and \
           hasattr(manager.graph_main_window, 'scene') and manager.graph_main_window.scene:
            
            # Define a slot for the refresh
            def delayed_refresh():
                print("TabUIManager: Explicit delayed full_graph_refresh for graph tab.")
                if manager.graph_main_window and manager.graph_main_window.scene: # Re-check existence
                    manager.graph_main_window.scene.full_graph_refresh()

            from PyQt6.QtCore import QTimer # Ensure QTimer is imported if not already at top
            QTimer.singleShot(250, delayed_refresh) # Increased delay to 250ms
            
            # Pass node visibility manager to the graph scene
            if (hasattr(manager, 'node_visibility_manager') and manager.node_visibility_manager and
                hasattr(manager.graph_main_window, 'scene') and manager.graph_main_window.scene):
                manager.graph_main_window.scene.set_node_visibility_manager(manager.node_visibility_manager)

        # Styling: For now, assume main app styling is sufficient.
        # If graph-specific styles are needed, they could be applied here:
        # e.g., graph_view_widget.setStyleSheet(...)
        # or manager.graph_main_window.setStyleSheet(...)
        # The original graph.py applies stylesheet to the QApplication.
        # We might need to apply it to graph_view_widget or its parent tab.
        # For simplicity, this is omitted for now.
