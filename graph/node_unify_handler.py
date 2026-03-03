"""
Handler for unifying multiple sink/source nodes into combined virtual devices via PipeWire.
"""
from __future__ import annotations
import logging
import traceback
from typing import TYPE_CHECKING, Optional, List, Dict, Any

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QRadioButton, QDialogButtonBox
from PyQt6.QtCore import QTimer, Qt

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .node_item import NodeItem
    from .port_item import PortItem
    from PyQt6.QtWidgets import QMenu
    from cables.unified_sink_manager import UnifiedSinkManager


class NodeUnifyHandler:
    """Handles unified virtual sink logic for a NodeItem."""

    def __init__(self, node_item: NodeItem) -> None:
        self.node_item = node_item

    def _get_unified_sink_manager(self) -> Optional['UnifiedSinkManager']:
        """Get the UnifiedSinkManager from the scene's connection_manager."""
        ni = self.node_item
        scene = ni.scene()
        if not scene:
            return None
        cm = getattr(scene, 'connection_manager', None)
        return getattr(cm, 'unified_sink_manager', None) if cm else None

    def ensure_sink_exists(self) -> None:
        """Check if the unified sinks exist and recreate them if not or if broken."""
        ni = self.node_item
        if getattr(ni, 'is_virtual_sink', False):
            return

        # Skip MIDI-only nodes (no audio ports to unify)
        if ni.is_midi and not any(
            getattr(pi.port_obj, 'is_audio', False)
            for pl in (ni.input_ports, ni.output_ports)
            for pi in pl.values()
        ):
            return

        # Check input unified sink
        if ni.is_input_unified and ni.unified_input_sink_name:
            self._ensure_specific_sink_exists(is_input=True)

        # Check output unified sink
        if ni.is_output_unified and ni.unified_output_sink_name:
            self._ensure_specific_sink_exists(is_input=False)

    def _ensure_specific_sink_exists(self, is_input: bool) -> None:
        """Helper to ensure a specific unified sink exists."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return

        # Check if we have ports to unify
        has_ports = bool(ni.input_ports) if is_input else bool(ni.output_ports)

        jack_handler = ni.jack_handler if ni.jack_handler else getattr(ni.scene(), 'jack_connection_handler', None)
        if not jack_handler:
            return

        all_ports = jack_handler.get_ports()
        sink_client_name = f"{sink_name} Audio/Sink sink"
        sink_ports = [p for p in all_ports if p.name.startswith(sink_client_name)]

        if not has_ports:
            if sink_ports:
                logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} exists but node has no ports. Unloading...")
                self._unload_unified_sink(is_input=is_input)
            return

        if not sink_ports:
            # Sink doesn't exist, recreate it
            logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} not found, recreating...")
            self._create_unified_sink(is_input=is_input)
            self._wait_for_sink_and_connect(is_input=is_input)
        else:
            logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} found, testing connections...")
            # Test if the sink is functional by trying to make a test connection
            if self._test_sink_functionality(is_input=is_input):
                logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} is functional, ensuring connections...")
                # Disconnect any existing connections to prevent self-connections
                self._disconnect_sink_self_connections(sink_client_name, all_ports)
                self._connect_to_unified_sink(is_input=is_input)
            else:
                logger.debug(f"Unified {'input' if is_input else 'output'} sink {sink_name} is broken, recreating...")
                usm = self._get_unified_sink_manager()
                if usm:
                    new_module_id = usm.force_recreate_unified_sink(sink_name)
                    if new_module_id:
                        if is_input:
                            ni.unified_input_module_id = new_module_id
                        else:
                            ni.unified_output_module_id = new_module_id
                    else:
                        if is_input:
                            ni.unified_input_module_id = None
                        else:
                            ni.unified_output_module_id = None
                self._wait_for_sink_and_connect(is_input=is_input)

    def _test_sink_functionality(self, is_input: bool) -> bool:
        """Test if the unified sink is functional via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return False

        usm = self._get_unified_sink_manager()
        if not usm:
            return False

        jack_handler = ni.jack_handler
        if not jack_handler:
            return False

        all_ports = jack_handler.get_ports()
        ports_type = 'input' if is_input else 'output'
        return usm.test_sink_functionality(sink_name, ports_type, all_ports)

    def _disconnect_sink_self_connections(self, sink_client_name: str, all_ports: List[Any]) -> None:
        """Disconnect any connections between the sink's own ports (monitor -> playback)."""
        ni = self.node_item
        if not ni.scene() or not hasattr(ni.scene(), 'jack_connection_handler'):
            return
        
        connection_handler = ni.scene().jack_connection_handler
        
        # Find all sink ports
        sink_outputs = [p for p in all_ports if p.is_output and p.name.startswith(sink_client_name + ':')]
        sink_inputs = [p for p in all_ports if p.is_input and p.name.startswith(sink_client_name + ':')]
        
        # Check for and break any connections between sink's own ports
        for sink_output in sink_outputs:
            try:
                # Get connections for this output port
                connections = connection_handler.get_all_connections(sink_output.name)
                for out_port, in_port in connections:
                    # Check if the input port belongs to the same sink
                    if in_port.startswith(sink_client_name + ':'):
                        logger.debug(f"Breaking self-connection: {out_port} -> {in_port}")
                        try:
                            connection_handler.break_connection(out_port, in_port)
                        except Exception as e:
                            logger.error(f"Error breaking self-connection: {e}")
            except Exception as e:
                logger.error(f"Error checking connections for {sink_output.name}: {e}")

    def apply_preset(self, unify_data: Dict[str, Any]) -> None:
        """Applies the unified state to the node from a preset."""
        ni = self.node_item
        if getattr(ni, 'is_virtual_sink', False):
            return

        # Skip MIDI-only nodes (no audio ports to unify)
        if ni.is_midi and not any(
            getattr(pi.port_obj, 'is_audio', False)
            for pl in (ni.input_ports, ni.output_ports)
            for pi in pl.values()
        ):
            return

        # Handle split states
        if unify_data.get('is_input_unified'):
            ni.is_input_unified = True
            ni.unified_input_sink_name = unify_data.get('unified_input_sink_name')
            if not ni.unified_input_sink_name:
                base_name = (ni.original_client_name or ni.client_name).replace(' ', '_')
                ni.unified_input_sink_name = f"unified-input-{base_name}"
        
        if unify_data.get('is_output_unified'):
            ni.is_output_unified = True
            ni.unified_output_sink_name = unify_data.get('unified_output_sink_name')
            if not ni.unified_output_sink_name:
                base_name = (ni.original_client_name or ni.client_name).replace(' ', '_')
                ni.unified_output_sink_name = f"unified-output-{base_name}"

        # Skip sink creation here, ensure_sink_exists will handle it
        ni.update()

    def _create_unified_sink(self, is_input: bool) -> None:
        """Create the unified virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            logger.warning("Cannot create unified sink: UnifiedSinkManager not available")
            return

        module_id = usm.create_unified_sink(sink_name)
        if module_id:
            if is_input:
                ni.unified_input_module_id = module_id
            else:
                ni.unified_output_module_id = module_id
            logger.info(f"Created unified {'input' if is_input else 'output'} virtual sink: {sink_name}")

    def _save_unified_module_id(self, sink_name: str, module_id: str) -> None:
        """Save the unified module ID to config via UnifiedSinkManager."""
        usm = self._get_unified_sink_manager()
        if usm:
            usm._save_unified_module_id(sink_name, module_id)

    def _unload_unified_sink(self, is_input: bool) -> None:
        """Unload the unified virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name:
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            logger.warning("Cannot unload unified sink: UnifiedSinkManager not available")
            return

        if usm.remove_unified_sink(sink_name):
            logger.info(f"Unloaded unified {'input' if is_input else 'output'} virtual sink: {sink_name}")

        # Clear local state
        if is_input:
            ni.unified_input_module_id = None
        else:
            ni.unified_output_module_id = None

    def _remove_unified_module_id(self, sink_name: str) -> None:
        """Remove the unified module ID from config via UnifiedSinkManager."""
        usm = self._get_unified_sink_manager()
        if usm:
            usm._remove_unified_module_id(sink_name)

    def _connect_to_unified_sink(self, is_input: bool) -> None:
        """Connect this node's ports to the unified sink via UnifiedSinkManager."""
        ni = self.node_item
        sink_name = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        
        if not sink_name or not ni.scene() or not hasattr(ni.scene(), 'jack_connection_handler'):
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            return

        jack_handler = ni.jack_handler
        all_ports = jack_handler.get_ports()
        connection_handler = ni.scene().jack_connection_handler

        # Connect only the specified direction
        if not is_input:
            sink_client_name = f"{sink_name} Audio/Sink sink"
            usm._connect_output_ports(ni, all_ports, sink_client_name, connection_handler)
        else:
            sink_client_name = f"{sink_name} Audio/Sink sink"
            usm._connect_input_ports(ni, all_ports, sink_client_name, connection_handler)

    def connect_new_port(self, port_item: 'PortItem', is_input: bool) -> None:
        """Connect a newly added port to the unified sink via UnifiedSinkManager."""
        ni = self.node_item
        usm = self._get_unified_sink_manager()
        if not usm:
            return

        if not ni.scene() or not hasattr(ni.scene(), 'jack_connection_handler'):
            return

        jack_handler = ni.jack_handler
        if not jack_handler:
            return

        all_ports = jack_handler.get_ports()
        usm.connect_new_port_to_unified_sink(port_item, all_ports, ni.scene().jack_connection_handler)

    def _wait_for_sink_and_connect(self, is_input: bool) -> None:
        """Waits for the unified sink to appear and then connects to it."""
        ni = self.node_item
        MAX_RETRIES = 50 # 50 * 100ms = 5 seconds
        if ni.wait_for_sink_retries >= MAX_RETRIES:
            logger.debug("Unified sink did not appear in time.")
            ni.wait_for_sink_retries = 0
            return

        sink_name_base = ni.unified_input_sink_name if is_input else ni.unified_output_sink_name
        if not sink_name_base:
            logger.debug("No unified sink name available for connection attempt.")
            ni.wait_for_sink_retries = 0
            return

        jack_handler = ni.jack_handler
        all_ports = jack_handler.get_ports()

        # Look specifically for ports that belong to the sink we created for this node
        # The full JACK client name will be: "sink_name_base Audio/Sink sink"
        sink_client_name = f"{sink_name_base} Audio/Sink sink"
        
        # We check for ANY ports from this sink to confirm its existence
        sink_ports = sorted([p for p in all_ports if (
            p.name.startswith(sink_client_name + ':')
        )], key=lambda p: p.name)

        logger.debug(f"Waiting for sink - name_base: '{sink_name_base}', found {len(sink_ports)} sink ports")
        if sink_ports:
            for port in sink_ports[:5]:  # Show first 5
                logger.debug(f"  Found sink port: {port.name}")

        if sink_ports:
            ni.wait_for_sink_retries = 0
            self._connect_to_unified_sink(is_input=is_input)
        else:
            ni.wait_for_sink_retries += 1
            ni.wait_for_sink_timer = QTimer()
            ni.wait_for_sink_timer.setSingleShot(True)
            ni.wait_for_sink_timer.timeout.connect(lambda: self._wait_for_sink_and_connect(is_input))
            ni.wait_for_sink_timer.start(100)

    def toggle_input(self, checked: bool) -> None:
        """Toggle unification for input ports."""
        ni = self.node_item
        try:
            if getattr(ni, 'is_virtual_sink', False):
                if ni.unify_input_action:
                    ni.unify_input_action.setChecked(False)
                return
            if checked:
                if not ni.input_ports:
                    logger.debug("Node has no input ports, cannot unify inputs")
                    if ni.unify_input_action: ni.unify_input_action.setChecked(False)
                    return

                ni.is_input_unified = True
                base_name = (ni.original_client_name or ni.client_name).replace(' ', '_')
                ni.unified_input_sink_name = f"unified-input-{base_name}"
                self._create_unified_sink(is_input=True)
                self._wait_for_sink_and_connect(is_input=True)
            else:
                ni.is_input_unified = False
                sink_name_to_remove = ni.unified_input_sink_name
                module_id_to_remove = ni.unified_input_module_id
                
                self._unload_unified_sink(is_input=True)
                ni.unified_input_sink_name = None
                ni.unified_input_module_id = None

            ni.update()
            self.update_config_state()

        except Exception as e:
            logger.error(f"Error toggling input unification: {e}")
            traceback.print_exc()

    def toggle_output(self, checked: bool) -> None:
        """Toggle unification for output ports."""
        ni = self.node_item
        try:
            if getattr(ni, 'is_virtual_sink', False):
                if ni.unify_output_action:
                    ni.unify_output_action.setChecked(False)
                return
            if checked:
                if not ni.output_ports:
                    logger.debug("Node has no output ports, cannot unify outputs")
                    if ni.unify_output_action: ni.unify_output_action.setChecked(False)
                    return

                ni.is_output_unified = True
                base_name = (ni.original_client_name or ni.client_name).replace(' ', '_')
                ni.unified_output_sink_name = f"unified-output-{base_name}"
                self._create_unified_sink(is_input=False)
                self._wait_for_sink_and_connect(is_input=False)
            else:
                ni.is_output_unified = False
                sink_name_to_remove = ni.unified_output_sink_name
                module_id_to_remove = ni.unified_output_module_id
                
                self._unload_unified_sink(is_input=False)
                ni.unified_output_sink_name = None
                ni.unified_output_module_id = None

            ni.update()
            self.update_config_state()

        except Exception as e:
            logger.error(f"Error toggling output unification: {e}")
            traceback.print_exc()

    def update_config_state(self) -> None:
        """Updates the unified state in the saved configuration.
        
        Uses GraphConfigManager's cache to avoid overwriting data on flush.
        """
        ni = self.node_item
        if hasattr(ni, 'config_manager') and ni.config_manager:
            if getattr(ni, 'is_virtual_sink', False):
                return
            try:
                # Use the config manager's cache instead of direct file access
                cached_data = ni.config_manager._cached_data
                if cached_data is None:
                    cached_data = {}
                    ni.config_manager._cached_data = cached_data

                client_config = cached_data.get(ni.client_name, {})

                # Update input unified state
                if ni.is_input_unified:
                    client_config[ni.config_manager.IS_INPUT_UNIFIED_KEY] = True
                    client_config[ni.config_manager.UNIFIED_INPUT_SINK_NAME_KEY] = ni.unified_input_sink_name
                    client_config[ni.config_manager.UNIFIED_INPUT_MODULE_ID_KEY] = ni.unified_input_module_id
                else:
                    client_config.pop(ni.config_manager.IS_INPUT_UNIFIED_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_INPUT_SINK_NAME_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_INPUT_MODULE_ID_KEY, None)

                # Update output unified state
                if ni.is_output_unified:
                    client_config[ni.config_manager.IS_OUTPUT_UNIFIED_KEY] = True
                    client_config[ni.config_manager.UNIFIED_OUTPUT_SINK_NAME_KEY] = ni.unified_output_sink_name
                    client_config[ni.config_manager.UNIFIED_OUTPUT_MODULE_ID_KEY] = ni.unified_output_module_id
                else:
                    client_config.pop(ni.config_manager.IS_OUTPUT_UNIFIED_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_OUTPUT_SINK_NAME_KEY, None)
                    client_config.pop(ni.config_manager.UNIFIED_OUTPUT_MODULE_ID_KEY, None)

                # Update cache and mark dirty for deferred write
                cached_data[ni.client_name] = client_config
                ni.config_manager._dirty = True

            except Exception as e:
                logger.error(f"Error updating unified state in config: {e}")

    def show_choice_dialog(self) -> Optional[str]:
        """
        Show a dialog to choose whether to unify input ports or output ports.

        Returns:
            str or None: 'input', 'output', or None if canceled
        """
        ni = self.node_item
        # Get the main window as parent for proper centering
        parent = None
        if ni.scene() and ni.scene().views():
            parent = ni.scene().views()[0]

        dialog = QDialog(parent)
        dialog.setWindowTitle("Choose Ports to Unify")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)

        # Add instruction text
        instruction = QLabel("Unify:")
        instruction.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(instruction)

        # Create radio buttons
        output_radio = QRadioButton("Output ports")
        output_radio.setChecked(True)  # Default selection
        layout.addWidget(output_radio)

        input_radio = QRadioButton("Input ports")
        layout.addWidget(input_radio)

        # Add buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # Center the dialog in the main window
        if parent:
            dialog.adjustSize()  # Ensure the dialog size is calculated
            parent_center = parent.rect().center()
            dialog_center = dialog.rect().center()
            dialog.move(parent.mapToGlobal(parent_center - dialog_center))

        # Execute dialog
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            if input_radio.isChecked():
                return 'input'
            elif output_radio.isChecked():
                return 'output'
            else:
                return None
        else:
            return None

    def classify_node(self, client_name: str) -> None:
        """Check if this node represents a virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        try:
            usm = self._get_unified_sink_manager()
            if not usm:
                ni.is_virtual_sink = False
                ni.module_id = None
                return

            info = usm.classify_virtual_sink(client_name)
            ni.is_virtual_sink = info.get('is_virtual_sink', False)
            ni.module_id = info.get('module_id')
            ni.external_sink = info.get('external_sink', False)
            ni.is_unified_sink = info.get('is_unified_sink', False)

            if ni.is_unified_sink:
                ni.update()

        except Exception as e:
            logger.error(f"Error checking if node is virtual sink for {client_name}: {e}")
            ni.is_virtual_sink = False
            ni.module_id = None

    def _find_module_id_for_external_sink(self, sink_name: str) -> Optional[str]:
        """Find module ID for an external virtual sink via UnifiedSinkManager."""
        usm = self._get_unified_sink_manager()
        if usm:
            return usm.find_module_id_for_external_sink(sink_name)
        return None

    def unload_sink(self) -> None:
        """Unload this virtual sink via UnifiedSinkManager."""
        ni = self.node_item
        if not ni.is_virtual_sink:
            logger.debug(f"Cannot unload sink: {ni.client_name} is not identified as a virtual sink")
            return

        usm = self._get_unified_sink_manager()
        if not usm:
            logger.warning("Cannot unload sink: UnifiedSinkManager not available")
            return

        if usm.unload_virtual_sink(ni.client_name):
            sink_type = "external" if getattr(ni, 'external_sink', False) else "tracked"
            logger.info(f"Successfully unloaded {sink_type} virtual sink: {ni.client_name}")

    def build_context_menu(self, menu: 'QMenu') -> None:
        """Add unify-related items to a context menu for a normal node."""
        ni = self.node_item
        
        # Check if this is a MIDI node - Unify toggle should not be available for MIDI nodes
        is_midi_node = ni.is_midi
        
        # Check if this is a virtual sink (any virtual sink)
        is_virtual_sink = getattr(ni, 'is_virtual_sink', False)
        
        # Add separate toggles for Input and Output unification only for audio nodes that aren't virtual sinks
        if not is_midi_node and not is_virtual_sink:
            from PyQt6.QtGui import QAction
            # Add separator before Unify section
            menu.addSeparator()
            
            # Unify Input Ports
            if bool(ni.input_ports):
                ni.unify_input_action = QAction("Unify input ports", menu)
                ni.unify_input_action.setCheckable(True)
                ni.unify_input_action.setChecked(ni.is_input_unified)
                ni.unify_input_action.toggled.connect(self.toggle_input)
                menu.addAction(ni.unify_input_action)
            
            # Unify Output Ports
            if bool(ni.output_ports):
                ni.unify_output_action = QAction("Unify output ports", menu)
                ni.unify_output_action.setCheckable(True)
                ni.unify_output_action.setChecked(ni.is_output_unified)
                ni.unify_output_action.toggled.connect(self.toggle_output)
                menu.addAction(ni.unify_output_action)
            
            # Add help text
            help_text = QAction("Route client ports through\ndedicated stereo virtual sinks", menu)
            help_text.setEnabled(False)
            menu.addAction(help_text)

    def handle_new_port(self, port_item: 'PortItem', is_input: bool) -> None:
        """Handle auto-connecting a newly added port to unified sink."""
        ni = self.node_item
        if is_input and ni.is_input_unified and ni.unified_input_sink_name:
            if not ni.unified_input_module_id:
                self._create_unified_sink(is_input=True)
                self._wait_for_sink_and_connect(is_input=True)
            elif ni.scene() and hasattr(ni.scene(), 'jack_connection_handler'):
                self.connect_new_port(port_item, is_input=True)
        elif not is_input and ni.is_output_unified and ni.unified_output_sink_name:
            if not ni.unified_output_module_id:
                self._create_unified_sink(is_input=False)
                self._wait_for_sink_and_connect(is_input=False)
            elif ni.scene() and hasattr(ni.scene(), 'jack_connection_handler'):
                self.connect_new_port(port_item, is_input=False)
