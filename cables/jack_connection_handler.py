# cables/jack_connection_handler.py
"""
Centralized JACK connection/disconnection operations with error handling and history tracking.
"""
import jack

import logging
logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING, List, Tuple, Set, Optional, Dict, Any, Union
if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager

from cables.jack_service import get_jack_service


class JackConnectionHandler:
    """Handles direct JACK connection operations."""

    def __init__(self, client: jack.Client, manager: 'JackConnectionManager') -> None:
        """
        Initialize the JackConnectionHandler.

        Args:
            client: The jack.Client instance (kept for backward compatibility).
            manager: The main JackConnectionManager instance.
        """
        self._client = client
        self._manager = manager
        self._batch_count = 0
        self._jack_service = get_jack_service()

    def start_batch(self) -> None:
        """Start a batch of connection operations."""
        self._batch_count += 1

    def end_batch(self) -> None:
        """End a batch of connection operations and perform a single refresh."""
        self._batch_count -= 1
        if self._batch_count == 0:
            self._perform_refresh()

    def _perform_refresh(self) -> None:
        """Perform all UI and state updates after an operation."""
        self._manager.update_undo_redo_buttons()
        self._manager.update_connections()
        self._manager.update_midi_connections()
        self._manager.refresh_ports(refresh_all=True)
        self._manager.update_connection_buttons()
        self._manager.update_midi_connection_buttons()

        if self._manager.preset_handler is not None:
            self._manager.preset_handler.update_save_button_enabled_state()

    def _port_operation(self, operation_type: str, output_name: str, input_name: str, is_midi: bool, is_undo_redo: bool = False) -> None:
        """
        Perform a port operation (connect or disconnect).

        Args:
            operation_type: The operation type ('connect' or 'disconnect')
            output_name: The name of the output port
            input_name: The name of the input port
            is_midi: Whether the ports are MIDI ports
            is_undo_redo: If True, skip adding to connection history.
        """
        service = get_jack_service()
        try:
            if operation_type == 'connect':
                service.connect(output_name, input_name)
                if not is_undo_redo:
                    self._manager.connection_history.add_action('connect', output_name, input_name, is_midi)
            else:
                service.disconnect(output_name, input_name)
                if not is_undo_redo:
                    self._manager.connection_history.add_action('disconnect', output_name, input_name, is_midi)

            if self._batch_count == 0:
                self._perform_refresh()

        except jack.JackError:
            logger.debug("jack.JackError suppressed")

    def make_connection(self, output_name: str, input_name: str, is_undo_redo: bool = False) -> None:
        """Make a connection between an output port and an input port."""
        self._port_operation('connect', output_name, input_name, is_midi=False, is_undo_redo=is_undo_redo)

    def make_midi_connection(self, output_name: str, input_name: str, is_undo_redo: bool = False) -> None:
        """Make a MIDI connection between an output port and an input port."""
        self._port_operation('connect', output_name, input_name, is_midi=True, is_undo_redo=is_undo_redo)

    def break_connection(self, output_name: str, input_name: str, is_undo_redo: bool = False) -> None:
        """Break a connection between an output port and an input port."""
        self._port_operation('disconnect', output_name, input_name, is_midi=False, is_undo_redo=is_undo_redo)

    def break_midi_connection(self, output_name: str, input_name: str, is_undo_redo: bool = False) -> None:
        """Break a MIDI connection between an output port and an input port."""
        self._port_operation('disconnect', output_name, input_name, is_midi=True, is_undo_redo=is_undo_redo)

    def make_multiple_connections(self, outputs: Union[str, List[str]], inputs: Union[str, List[str]], is_undo_redo: bool = False) -> None:
        """Connects multiple output ports to multiple input ports."""
        if not outputs or not inputs:
            logger.warning("Warning: make_multiple_connections called with empty outputs or inputs.")
            return

        output_list = outputs if isinstance(outputs, list) else [outputs]
        input_list = inputs if isinstance(inputs, list) else [inputs]

        if not output_list or not input_list:
            logger.warning(f"Warning: make_multiple_connections called with empty lists: outputs={output_list}, inputs={input_list}")
            return

        is_midi = self._manager.ui_manager.tab_widget.currentIndex() == 1
        operation_type = 'connect'

        num_outputs = len(output_list)
        num_inputs = len(input_list)
        made_connection_attempt = False

        logger.debug(f"make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs. MIDI: {is_midi}")

        if num_outputs > 1 and num_inputs == 1:
            single_input = input_list[0]
            logger.debug(f"  Scenario: Group/List ({num_outputs}) -> Port ({single_input})")
            for output_name in output_list:
                try:
                    self._port_operation(operation_type, output_name, single_input, is_midi, is_undo_redo=is_undo_redo)
                    made_connection_attempt = True
                except jack.JackError as e:
                    logger.debug(f"  Failed to connect {output_name} -> {single_input}: {e}")

        elif num_outputs == 1 and num_inputs > 1:
            single_output = output_list[0]
            logger.debug(f"  Scenario: Port ({single_output}) -> Group/List ({num_inputs})")
            for input_name in input_list:
                try:
                    self._port_operation(operation_type, single_output, input_name, is_midi, is_undo_redo=is_undo_redo)
                    made_connection_attempt = True
                except jack.JackError as e:
                    logger.debug(f"  Failed to connect {single_output} -> {input_name}: {e}")

        elif num_outputs > 1 and num_inputs > 1:
            logger.debug(f"  Scenario: Group/List ({num_outputs}) -> Group/List ({num_inputs}) - Applying suffix/sequential matching")

            common_suffixes = [
                '_FL', '_FR', '_SL', '_SR', '_FC', '_LFE', '_RL', '_RR',
                '_L', '_R', '_1', '_2', '_3', '_4', '_5', '_6', '_7', '_8',
                'left', 'right', 'Left', 'Right'
            ]

            unmatched_outputs = list(output_list)
            unmatched_inputs = list(input_list)
            connections_made_in_group = []

            for suffix in common_suffixes:
                outputs_with_suffix = [p for p in unmatched_outputs if p.endswith(suffix)]
                inputs_with_suffix = [p for p in unmatched_inputs if p.endswith(suffix)]

                pairs_to_connect = min(len(outputs_with_suffix), len(inputs_with_suffix))
                for i in range(pairs_to_connect):
                    out_p = outputs_with_suffix[i]
                    in_p = inputs_with_suffix[i]
                    try:
                        logger.debug(f"    Suffix Match ({suffix}): {out_p} -> {in_p}")
                        self._port_operation(operation_type, out_p, in_p, is_midi, is_undo_redo=is_undo_redo)
                        connections_made_in_group.append((out_p, in_p))
                        unmatched_outputs.remove(out_p)
                        unmatched_inputs.remove(in_p)
                        made_connection_attempt = True
                    except Exception as e:
                        logger.debug(f"      Connection failed: {e}")

            while unmatched_outputs and unmatched_inputs:
                out_p = unmatched_outputs[0]
                in_p = unmatched_inputs[0]
                try:
                    logger.debug(f"    Sequential Match: {out_p} -> {in_p}")
                    self._port_operation(operation_type, out_p, in_p, is_midi, is_undo_redo=is_undo_redo)
                    connections_made_in_group.append((out_p, in_p))
                    made_connection_attempt = True
                except Exception as e:
                    logger.debug(f"      Connection failed: {e}")
                unmatched_outputs.pop(0)
                unmatched_inputs.pop(0)

            logger.debug(f"  Group-to-group connection finished. Attempted {len(connections_made_in_group)} connections.")

        elif num_outputs == 1 and num_inputs == 1:
            single_output = output_list[0]
            single_input = input_list[0]
            logger.debug(f"  Scenario: Port ({single_output}) -> Port ({single_input})")
            try:
                self._port_operation(operation_type, single_output, single_input, is_midi, is_undo_redo=is_undo_redo)
                made_connection_attempt = True
            except jack.JackError as e:
                logger.debug(f"  Failed to connect {single_output} -> {single_input}: {e}")
        else:
            logger.warning(f"Warning: Unexpected case in make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs")

        if made_connection_attempt:
             logger.debug("Multiple connection process finished.")

    def get_all_connections(self, port_name: str) -> List[Tuple[str, str]]:
        """
        Gets all connections for a given port name.
        Returns a list of (source_port_name, dest_port_name) tuples.
        """
        return self._jack_service.get_all_connections_as_tuples(port_name)

    def _get_existing_connections_between(
        self,
        output_ports: List[str],
        input_ports: List[str],
        is_midi: Optional[bool] = None,
    ) -> Set[Tuple[str, str]]:
        """Returns a set of existing (output, input) connection tuples between the given port lists."""
        existing_connections = set()
        if not output_ports or not input_ports:
            return existing_connections
        try:
            input_ports_set = set(input_ports)
            if is_midi is None:
                is_midi = self._manager.ui_manager.tab_widget.currentIndex() == 1

            # Build a fast lookup of valid output port names for the correct port type.
            # Without this, MIDI outputs may be incorrectly filtered out by an audio-only check,
            # which breaks detection of existing connections and keeps the Connect button enabled.
            valid_output_names = {
                p.name for p in self._jack_service.get_ports(is_output=True, is_midi=is_midi)
            }

            for out_port in output_ports:
                try:
                    if out_port not in valid_output_names:
                        continue

                    connections = self._jack_service.get_all_connections(out_port)
                    for conn in connections:
                        if conn.name in input_ports_set:
                            existing_connections.add((out_port, conn.name))
                except jack.JackError:
                    continue
            return existing_connections
        except jack.JackError as e:
            logger.error(f"Error getting existing connections: {e}")
            return existing_connections

    def disconnect_node(self, node_name: str, is_undo_redo: bool = False) -> None:
        """Disconnect all connections from/to a specific port."""
        try:
            port_obj = self._jack_service.get_port_by_name(node_name)
            is_midi = port_obj.is_midi
            is_input = port_obj.is_input
            is_output = port_obj.is_output

            if is_input:
                all_output_ports = self._jack_service.get_ports(is_output=True, is_midi=is_midi)
                for output_port in all_output_ports:
                    try:
                        connections = self._jack_service.get_all_connections(output_port)
                        if node_name in [conn.name for conn in connections]:
                            logger.debug(f"Disconnecting (input node): {output_port.name} -> {node_name}")
                            self._port_operation('disconnect', output_port.name, node_name, is_midi, is_undo_redo=is_undo_redo)
                    except jack.JackError:
                        continue
            elif is_output:
                try:
                    connections = self._jack_service.get_all_connections(node_name)
                    for input_port in connections:
                        if input_port.is_midi == is_midi:
                            logger.debug(f"Disconnecting (output node): {node_name} -> {input_port.name}")
                            self._port_operation('disconnect', node_name, input_port.name, is_midi, is_undo_redo=is_undo_redo)
                except jack.JackError as e:
                     logger.error(f"Error getting connections for output node {node_name}: {e}")

        except jack.JackError as e:
            logger.error(f"Error disconnecting node {node_name}: {e}")

    def _get_current_connections(self) -> List[Dict[str, str]]:
        """Gets the current state of all JACK audio and MIDI connections."""
        all_connections = []
        try:
            output_ports = self._jack_service.get_ports(is_output=True)
            for output_port in output_ports:
                try:
                    if not any(p.name == output_port.name for p in self._jack_service.get_ports(is_output=True)):
                        continue
                    connected_inputs = self._jack_service.get_all_connections(output_port)
                    port_type = "midi" if output_port.is_midi else "audio"
                    for input_port in connected_inputs:
                        if input_port.is_midi == output_port.is_midi:
                             all_connections.append({
                                 "output": output_port.name,
                                 "input": input_port.name,
                                 "type": port_type
                             })
                except jack.JackError as conn_err:
                    logger.warning(f"Warning: Could not get connections for {output_port.name}: {conn_err}")
                    continue
        except jack.JackError as e:
            logger.error(f"Error getting current connections: {e}")
        return all_connections

    def disconnect_all_ports_of_client(self, client_name: str, is_undo_redo: bool = False) -> None:
        """Disconnects all ports belonging to a given client."""
        logger.debug(f"Attempting to disconnect all ports of client: {client_name}")
        disconnected_something = False
        try:
            all_ports = self._jack_service.get_ports()
            if not all_ports:
                logger.debug(f"  No ports found on the JACK server.")
                return

            client_ports = [p for p in all_ports if p.name.startswith(client_name + ':')]

            if not client_ports:
                logger.debug(f"  No ports found for client {client_name}.")
                return

            for port_obj in client_ports:
                port_name = port_obj.name
                is_midi = port_obj.is_midi
                
                if port_obj.is_input:
                    all_output_ports = self._jack_service.get_ports(is_output=True, is_midi=is_midi)
                    for output_port_obj in all_output_ports:
                        try:
                            if not any(p.name == output_port_obj.name for p in self._jack_service.get_ports(is_output=True, is_midi=is_midi)):
                                continue
                            connections = self._jack_service.get_all_connections(output_port_obj.name)
                            if port_name in [conn.name for conn in connections]:
                                logger.debug(f"  Disconnecting (client input port): {output_port_obj.name} -> {port_name}")
                                self._port_operation('disconnect', output_port_obj.name, port_name, is_midi, is_undo_redo=is_undo_redo)
                                disconnected_something = True
                        except jack.JackError:
                            continue
                elif port_obj.is_output:
                    try:
                        if not any(p.name == port_name for p in self._jack_service.get_ports(is_output=True, is_midi=is_midi)):
                            continue
                        connections = self._jack_service.get_all_connections(port_name)
                        for input_port_obj in connections:
                            if input_port_obj.is_midi == is_midi:
                                logger.debug(f"  Disconnecting (client output port): {port_name} -> {input_port_obj.name}")
                                self._port_operation('disconnect', port_name, input_port_obj.name, is_midi, is_undo_redo=is_undo_redo)
                                disconnected_something = True
                    except jack.JackError as e:
                        logger.debug(f"  Error getting connections for output port {port_name} of client {client_name}: {e}")
            
            if disconnected_something:
                logger.debug(f"Finished disconnecting ports for client {client_name}.")
            else:
                logger.debug(f"No active connections found to disconnect for client {client_name}.")

        except jack.JackError as e:
            logger.error(f"Error disconnecting ports for client {client_name}: {e}")
        except Exception as e:
            logger.debug(f"Unexpected error disconnecting ports for client {client_name}: {type(e).__name__} - {e}")
