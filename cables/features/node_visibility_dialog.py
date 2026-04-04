import logging

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QPushButton,
    QScrollArea,
    QDialog,
    QLineEdit,
)
from PyQt6.QtCore import Qt

from cables.jack_service import get_jack_service
from cable_core import config_keys as keys

from typing import TYPE_CHECKING, Optional, Any

logger = logging.getLogger(__name__)


class NodeVisibilityDialog(QDialog):
    """Dialog for configuring node visibility settings."""

    def __init__(
        self,
        connection_manager,
        audio_input_visibility,
        audio_output_visibility,
        midi_input_visibility,
        midi_output_visibility,
        parent=None,
        tab_type="graph",
    ):
        """
        Initialize the dialog.

        Args:
            connection_manager: The main JackConnectionManager instance
            audio_input_visibility: Dictionary of audio input visibility settings
            audio_output_visibility: Dictionary of audio output visibility settings
            midi_input_visibility: Dictionary of MIDI input visibility settings
            midi_output_visibility: Dictionary of MIDI output visibility settings
            parent: The parent widget
            tab_type: The type of tab ('audio', 'midi', or 'graph')
        """
        super().__init__(parent)
        self.connection_manager = connection_manager
        # For MIDI Matrix, work with references to allow direct modification
        if tab_type in ("midi_matrix", "audio_matrix"):
            self.audio_input_visibility = audio_input_visibility
            self.audio_output_visibility = audio_output_visibility
            self.midi_input_visibility = midi_input_visibility
            self.midi_output_visibility = midi_output_visibility
        else:
            # For other tabs, work with copies for cancel functionality
            self.audio_input_visibility = dict(audio_input_visibility)
            self.audio_output_visibility = dict(audio_output_visibility)
            self.midi_input_visibility = dict(midi_input_visibility)
            self.midi_output_visibility = dict(midi_output_visibility)
        self.tab_type = tab_type

        # Show input/output checkboxes for all tabs
        self.show_ports = True

        if self.tab_type == "midi_matrix":
            self.setWindowTitle("MIDI Matrix Clients Visibility Configuration")
        elif self.tab_type == "audio_matrix":
            self.setWindowTitle("Audio Matrix Clients Visibility Configuration")
        else:
            self.setWindowTitle("Clients Visibility Configuration")
        self.resize(600, 600)

        # Track node checkboxes and their children
        self.audio_nodes = {}  # Maps node name to: {'node': node_checkbox, 'input': input_checkbox, 'output': output_checkbox}
        self.midi_nodes = {}  # Same structure for MIDI nodes

        self._setup_ui()
        self._populate_nodes()

    def _setup_ui(self) -> None:
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)

        # Add filter input
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter clients...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_edit)
        layout.addLayout(filter_layout)

        # Tabs label
        if self.tab_type == "midi_matrix":
            self.tabs_label = QLabel("Note: Changes will apply to the MIDI Matrix tab")
        elif self.tab_type == "audio_matrix":
            self.tabs_label = QLabel("Note: Changes will apply to the Audio Matrix tab")
        else:
            self.tabs_label = QLabel(
                "Note: Changes will apply to Audio, MIDI, and Graph tabs"
            )
        layout.addWidget(self.tabs_label)

        # Create scroll area for node checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.node_container = QWidget()
        self.node_layout = QVBoxLayout(self.node_container)

        # Audio nodes section
        self.audio_label = QLabel("Audio Clients")
        font = self.audio_label.font()
        font.setBold(True)
        self.audio_label.setFont(font)
        self.node_layout.addWidget(self.audio_label)

        # MIDI nodes section
        self.midi_label = QLabel("MIDI Clients")
        font = self.midi_label.font()
        font.setBold(True)
        self.midi_label.setFont(font)
        self.node_layout.addWidget(self.midi_label)

        scroll.setWidget(self.node_container)
        layout.addWidget(scroll)

        # Buttons
        button_layout = QHBoxLayout()

        # Select/deselect all buttons
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._populate_nodes)

        # OK/Cancel buttons
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(deselect_all_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _populate_nodes(self) -> None:
        """Populate the dialog with node checkboxes."""
        self._clear_node_layout()

        self.audio_nodes = {}
        self.midi_nodes = {}

        # Get clients based on tab type
        if self.tab_type in [keys.TAB_AUDIO, keys.TAB_AUDIO_MATRIX, keys.TAB_GRAPH]:
            # Get all audio nodes (clients)
            audio_nodes = self._get_unique_client_names(is_midi=False)
            for node in sorted(audio_nodes):
                self._add_node_hierarchy(node, is_midi=False)

        if self.tab_type in [keys.TAB_MIDI, keys.TAB_MIDI_MATRIX, keys.TAB_GRAPH]:
            # Get all MIDI nodes (clients)
            midi_nodes = self._get_unique_client_names(is_midi=True)
            for node in sorted(midi_nodes):
                self._add_node_hierarchy(node, is_midi=True)

        # Apply any active filter
        self._apply_filter(self.filter_edit.text())

        # Add stretch to prevent spacing issues when there are few clients
        self.node_layout.addStretch()

    def _clear_node_layout(self) -> None:
        """Clear all widgets and items from node layout except section labels."""
        if not self.node_layout:
            return

        # Iterate backwards to safely remove items
        for i in reversed(range(self.node_layout.count())):
            item = self.node_layout.itemAt(i)
            widget = item.widget()

            # Skip the section labels
            if widget and (widget == self.audio_label or widget == self.midi_label):
                continue

            # Remove the item from layout
            self.node_layout.takeAt(i)

            # If it's a widget, delete it
            if widget:
                widget.deleteLater()

    def _add_node_hierarchy(self, node_name: str, is_midi: bool = False) -> None:
        """
        Create a hierarchical layout for a node with indented input/output checkboxes.

        Args:
            node_name: The name of the node
            is_midi: Whether this is a MIDI node
        """
        # Handle split node names for querying ports
        query_name = node_name
        is_audio_split = False
        is_midi_split = False

        if node_name.endswith(" (Audio)"):
            query_name = node_name[:-8]
            is_audio_split = True
        elif node_name.endswith(" (MIDI)"):
            query_name = node_name[:-7]
            is_midi_split = True

        # For client-only mode (non-graph tabs), we don't need to check port directions
        # since we're only showing client-level visibility
        has_input = False
        has_output = False

        if self.show_ports:
            # Graph tab: determine which directions this client actually exposes
            try:
                # If it's a split node, we must enforce the type matching the suffix
                # regardless of the is_midi argument passed to this function (though they should match)
                check_midi = is_midi
                check_audio = not is_midi

                if is_audio_split:
                    check_midi = False
                    check_audio = True
                elif is_midi_split:
                    check_midi = True
                    check_audio = False

                # Get ports from JackService
                jack_service = get_jack_service()

                # Get both input and output ports to determine what directions exist
                input_ports = jack_service.get_ports(
                    name_pattern=f"{query_name}:",
                    is_input=True,
                    is_midi=check_midi,
                    is_audio=check_audio,
                )
                output_ports = jack_service.get_ports(
                    name_pattern=f"{query_name}:",
                    is_output=True,
                    is_midi=check_midi,
                    is_audio=check_audio,
                )

                # Check if there are any input ports
                if input_ports:
                    has_input = True
                # Check if there are any output ports
                if output_ports:
                    has_output = True
            except Exception as e:
                logger.error(f"Error checking port directions for {node_name}: {e}")

            # If no ports are found, assume the node has both input and output
            # This can happen for nodes that exist in the graph but don't have active JACK ports
            # at the moment of querying (e.g., Easy Effects internal filters)
            if not has_input and not has_output:
                # Default to having both directions so the node appears in the dialog
                has_input = True
                has_output = True

        # Create node container and checkbox
        node_widget = QWidget()
        node_layout = QVBoxLayout(node_widget)
        node_layout.setContentsMargins(0, 5, 0, 5)

        # Main node checkbox with name
        node_checkbox = QCheckBox(node_name)
        font = node_checkbox.font()
        font.setBold(True)
        node_checkbox.setFont(font)
        node_layout.addWidget(node_checkbox)

        input_checkbox = None
        output_checkbox = None

        # Only create input/output checkboxes for Graph tab
        if self.show_ports:
            # Add indented container for input/output checkboxes
            io_widget = QWidget()
            io_layout = QHBoxLayout(io_widget)
            io_layout.setContentsMargins(20, 0, 0, 0)

            # Create input checkbox if the client has input ports
            if has_input:
                input_checkbox = QCheckBox("Input")
                # Use query_name (base client name) for visibility lookup
                if is_midi:
                    input_checkbox.setChecked(
                        self.midi_input_visibility.get(query_name, True)
                    )
                    input_checkbox.stateChanged.connect(
                        lambda state, n=query_name: (
                            self._on_midi_input_checkbox_changed(n, state)
                        )
                    )
                else:
                    input_checkbox.setChecked(
                        self.audio_input_visibility.get(query_name, True)
                    )
                    input_checkbox.stateChanged.connect(
                        lambda state, n=query_name: (
                            self._on_audio_input_checkbox_changed(n, state)
                        )
                    )
                io_layout.addWidget(input_checkbox)

            # Create output checkbox if the client has output ports
            if has_output:
                output_checkbox = QCheckBox("Output")
                # Use query_name (base client name) for visibility lookup
                if is_midi:
                    output_checkbox.setChecked(
                        self.midi_output_visibility.get(query_name, True)
                    )
                    output_checkbox.stateChanged.connect(
                        lambda state, n=query_name: (
                            self._on_midi_output_checkbox_changed(n, state)
                        )
                    )
                else:
                    output_checkbox.setChecked(
                        self.audio_output_visibility.get(query_name, True)
                    )
                    output_checkbox.stateChanged.connect(
                        lambda state, n=query_name: (
                            self._on_audio_output_checkbox_changed(n, state)
                        )
                    )
                io_layout.addWidget(output_checkbox)

            io_layout.addStretch()
            node_layout.addWidget(io_widget)

            # Connect node checkbox to control existing child checkboxes
            node_checkbox.stateChanged.connect(
                lambda state, i=input_checkbox, o=output_checkbox: (
                    self._on_node_checkbox_changed(state, i, o)
                )
            )

            # Update node checkbox initial state
            self._update_node_checkbox_state(
                node_checkbox, input_checkbox, output_checkbox
            )

            # Connect child checkbox state changes to update the parent node checkbox
            if input_checkbox:
                input_checkbox.stateChanged.connect(
                    lambda _state, n=node_checkbox, i=input_checkbox, o=output_checkbox: (
                        self._update_node_checkbox_state(n, i, o)
                    )
                )
            if output_checkbox:
                output_checkbox.stateChanged.connect(
                    lambda _state, n=node_checkbox, i=input_checkbox, o=output_checkbox: (
                        self._update_node_checkbox_state(n, i, o)
                    )
                )
        else:
            # For non-graph tabs (client-only mode), the node checkbox directly controls visibility
            # Set initial state based on whether both input and output are visible
            if is_midi:
                input_visible = self.midi_input_visibility.get(query_name, True)
                output_visible = self.midi_output_visibility.get(query_name, True)
            else:
                input_visible = self.audio_input_visibility.get(query_name, True)
                output_visible = self.audio_output_visibility.get(query_name, True)

            # Client is visible if either input or output is visible
            node_checkbox.setChecked(input_visible or output_visible)

            # Connect node checkbox to update both input and output visibility
            node_checkbox.stateChanged.connect(
                lambda state, n=query_name, midi=is_midi: (
                    self._on_client_checkbox_changed(n, state, midi)
                )
            )

        # Add to appropriate section and tracking dictionaries
        if is_midi:
            self.node_layout.insertWidget(self.node_layout.count(), node_widget)
            self.midi_nodes[node_name] = {
                "node": node_checkbox,
                "input": input_checkbox,
                "output": output_checkbox,
                "widget": node_widget,
            }
        else:
            self.node_layout.insertWidget(
                self.node_layout.indexOf(self.midi_label), node_widget
            )
            self.audio_nodes[node_name] = {
                "node": node_checkbox,
                "input": input_checkbox,
                "output": output_checkbox,
                "widget": node_widget,
            }

    def _on_node_checkbox_changed(
        self,
        state: int,
        input_checkbox: Optional["QCheckBox"],
        output_checkbox: Optional["QCheckBox"],
    ) -> None:
        """Handle changes to the node checkbox by updating child checkboxes."""
        checked = state == Qt.CheckState.Checked.value

        if input_checkbox:
            input_checkbox.blockSignals(True)
            input_checkbox.setChecked(checked)
            input_checkbox.blockSignals(False)
            if not input_checkbox.signalsBlocked():
                input_checkbox.stateChanged.emit(
                    Qt.CheckState.Checked.value
                    if checked
                    else Qt.CheckState.Unchecked.value
                )

        if output_checkbox:
            output_checkbox.blockSignals(True)
            output_checkbox.setChecked(checked)
            output_checkbox.blockSignals(False)
            if not output_checkbox.signalsBlocked():
                output_checkbox.stateChanged.emit(
                    Qt.CheckState.Checked.value
                    if checked
                    else Qt.CheckState.Unchecked.value
                )

    def _update_node_checkbox_state(
        self,
        node_checkbox: "QCheckBox",
        input_checkbox: Optional["QCheckBox"],
        output_checkbox: Optional["QCheckBox"],
    ) -> None:
        """Synchronize node checkbox state with its existing child checkboxes."""
        node_checkbox.blockSignals(True)

        # Gather child states that actually exist
        child_states = []
        if input_checkbox:
            child_states.append(input_checkbox.isChecked())
        if output_checkbox:
            child_states.append(output_checkbox.isChecked())

        if not child_states:
            node_checkbox.setCheckState(Qt.CheckState.Unchecked)
        elif all(child_states):
            node_checkbox.setCheckState(Qt.CheckState.Checked)
        elif any(child_states):
            node_checkbox.setCheckState(
                Qt.CheckState.Checked
            )  # Set to checked if any child is checked
        else:
            node_checkbox.setCheckState(Qt.CheckState.Unchecked)

        node_checkbox.blockSignals(False)

    def _get_unique_client_names(self, is_midi: bool = False) -> set:
        """
        Get a list of unique client names.

        Args:
            is_midi: Whether to get MIDI clients

        Returns:
            set: A set of unique client names
        """
        unique_clients = set()

        try:
            # Check if we should split audio/midi clients
            # We need to access the main config manager, which is passed to NodeVisibilityManager
            # but not directly to NodeVisibilityDialog. However, NodeVisibilityDialog has connection_manager
            # which has config_manager.
            split_audio_midi = False
            if self.connection_manager.config_manager is not None:
                split_audio_midi = self.connection_manager.config_manager.get_bool(
                    keys.GRAPH_SPLIT_AUDIO_MIDI_CLIENTS, False
                )

            # If we are in the graph tab and splitting is enabled, we need special handling
            if self.tab_type == "graph" and split_audio_midi:
                # Get all ports to determine which clients have what
                jack_service = get_jack_service()
                all_audio_ports = jack_service.get_ports(is_audio=True)
                all_midi_ports = jack_service.get_ports(is_midi=True)

                client_capabilities = {}  # client_name -> {'audio': bool, 'midi': bool}

                for port in all_audio_ports:
                    parts = port.name.split(":")
                    if parts:
                        client = parts[0]
                        if client not in client_capabilities:
                            client_capabilities[client] = {
                                "audio": False,
                                "midi": False,
                            }
                        client_capabilities[client]["audio"] = True

                for port in all_midi_ports:
                    parts = port.name.split(":")
                    if parts:
                        client = parts[0]
                        if client not in client_capabilities:
                            client_capabilities[client] = {
                                "audio": False,
                                "midi": False,
                            }
                        client_capabilities[client]["midi"] = True

                # Now generate the list based on requested type
                for client, caps in client_capabilities.items():
                    if caps["audio"] and caps["midi"]:
                        # Mixed client - split it
                        if is_midi:
                            unique_clients.add(f"{client} (MIDI)")
                        else:
                            unique_clients.add(f"{client} (Audio)")
                    else:
                        # Not mixed, add as is if it matches the requested type
                        if is_midi and caps["midi"]:
                            unique_clients.add(client)
                        elif not is_midi and caps["audio"]:
                            unique_clients.add(client)

            else:
                # Standard behavior for other tabs or when split is disabled
                jack_service = get_jack_service()
                if is_midi:
                    ports = jack_service.get_ports(is_midi=True)
                else:
                    ports = jack_service.get_ports(is_audio=True)

                # Extract client names (part before the colon)
                for port in ports:
                    parts = port.name.split(":")
                    if parts:
                        unique_clients.add(parts[0])

        except Exception as e:
            logger.error(f"Error getting client names: {e}")

        return unique_clients

    def _on_audio_input_checkbox_changed(self, node_name: str, state: int) -> None:
        """
        Handle checkbox state change for audio inputs.

        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.audio_input_visibility[node_name] = state == Qt.CheckState.Checked.value

    def _on_audio_output_checkbox_changed(self, node_name: str, state: int) -> None:
        """
        Handle checkbox state change for audio outputs.

        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.audio_output_visibility[node_name] = state == Qt.CheckState.Checked.value

    def _on_midi_input_checkbox_changed(self, node_name: str, state: int) -> None:
        """
        Handle checkbox state change for MIDI inputs.

        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.midi_input_visibility[node_name] = state == Qt.CheckState.Checked.value

    def _on_midi_output_checkbox_changed(self, node_name: str, state: int) -> None:
        """
        Handle checkbox state change for MIDI outputs.

        Args:
            node_name: The name of the node
            state: The new state (Qt.CheckState)
        """
        self.midi_output_visibility[node_name] = state == Qt.CheckState.Checked.value

    def _on_client_checkbox_changed(
        self, node_name: str, state: int, is_midi: bool
    ) -> None:
        """
        Handle checkbox state change for client-level visibility (non-graph tabs).
        When a client checkbox is toggled, both input and output visibility are set to the same value.

        Args:
            node_name: The name of the node/client
            state: The new state (Qt.CheckState)
            is_midi: Whether this is a MIDI client
        """
        checked = state == Qt.CheckState.Checked.value

        if is_midi:
            self.midi_input_visibility[node_name] = checked
            self.midi_output_visibility[node_name] = checked
        else:
            self.audio_input_visibility[node_name] = checked
            self.audio_output_visibility[node_name] = checked

    def _select_all(self) -> None:
        """Select all visible checkboxes."""
        for node_dict in [self.audio_nodes, self.midi_nodes]:
            for checkboxes in node_dict.values():
                if not checkboxes["widget"].isHidden():
                    node_cb = checkboxes["node"]
                    input_cb = checkboxes.get("input")
                    output_cb = checkboxes.get("output")

                    if self.show_ports:
                        # Graph mode: set input/output checkboxes
                        if input_cb:
                            input_cb.setChecked(True)
                        if output_cb:
                            output_cb.setChecked(True)

                        # Update node checkbox state to reflect children
                        self._update_node_checkbox_state(node_cb, input_cb, output_cb)
                    else:
                        # Client-only mode: just set the node checkbox
                        node_cb.setChecked(True)

    def _deselect_all(self) -> None:
        """Deselect all visible checkboxes and hide all nodes."""
        # First, uncheck all visible checkboxes in the dialog
        for node_dict in [self.audio_nodes, self.midi_nodes]:
            for checkboxes in node_dict.values():
                if not checkboxes["widget"].isHidden():
                    node_cb = checkboxes["node"]
                    input_cb = checkboxes.get("input")
                    output_cb = checkboxes.get("output")

                    if self.show_ports:
                        # Graph mode: uncheck input/output checkboxes
                        if input_cb:
                            input_cb.setChecked(False)
                        if output_cb:
                            output_cb.setChecked(False)

                        # Update node checkbox state to reflect children
                        self._update_node_checkbox_state(node_cb, input_cb, output_cb)
                    else:
                        # Client-only mode: just uncheck the node checkbox
                        node_cb.setChecked(False)

        # Also explicitly set all nodes in visibility dictionaries to False
        # This ensures nodes that don't appear in the current dialog (due to tab type)
        # are also hidden
        for client_name in list(self.audio_input_visibility.keys()):
            self.audio_input_visibility[client_name] = False
        for client_name in list(self.audio_output_visibility.keys()):
            self.audio_output_visibility[client_name] = False
        for client_name in list(self.midi_input_visibility.keys()):
            self.midi_input_visibility[client_name] = False
        for client_name in list(self.midi_output_visibility.keys()):
            self.midi_output_visibility[client_name] = False

    def _apply_filter(self, filter_text: str) -> None:
        """
        Apply filter to checkboxes.

        Args:
            filter_text: The filter text
        """
        filter_text = filter_text.lower()

        audio_visible = False
        midi_visible = False

        # Apply filter to audio nodes
        for node_name, checkboxes in self.audio_nodes.items():
            should_hide = bool(filter_text and filter_text not in node_name.lower())
            checkboxes["widget"].setHidden(should_hide)
            if not should_hide:
                audio_visible = True

        # Apply filter to MIDI nodes
        for node_name, checkboxes in self.midi_nodes.items():
            should_hide = bool(filter_text and filter_text not in node_name.lower())
            checkboxes["widget"].setHidden(should_hide)
            if not should_hide:
                midi_visible = True

        # Show/hide section labels based on if any items are visible
        self.audio_label.setHidden(not audio_visible)
        self.midi_label.setHidden(not midi_visible)
