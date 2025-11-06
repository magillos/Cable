# cables/jack_connection_handler.py
import jack
import random # Needed for _get_current_connections potentially, though seems unused there. Keep for now.
import re # Needed for _sort_ports if we move it, but it's not on the list.

# Forward declaration for type hinting
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager

class JackConnectionHandler:
    """Handles direct JACK connection operations."""

    def __init__(self, client: jack.Client, manager: 'JackConnectionManager'):
        """
        Initialize the JackConnectionHandler.

        Args:
            client: The jack.Client instance.
            manager: The main JackConnectionManager instance.
        """
        self._client = client
        self._manager = manager # To access history and UI update methods
        self._batch_count = 0

    def start_batch(self):
        """Start a batch of connection operations."""
        self._batch_count += 1

    def end_batch(self):
        """End a batch of connection operations and perform a single refresh."""
        self._batch_count -= 1
        if self._batch_count == 0:
            self._perform_refresh()

    def _perform_refresh(self):
        """Perform all UI and state updates after an operation."""
        self._manager.update_undo_redo_buttons()
        self._manager.update_connections()  # Update audio viz
        self._manager.update_midi_connections()  # Update midi viz
        self._manager.refresh_ports(refresh_all=True)  # Refresh both audio and midi ports
        self._manager.update_connection_buttons()  # Update audio buttons
        self._manager.update_midi_connection_buttons()  # Update midi buttons

        # Update preset save button state if presets are being used
        if hasattr(self._manager, 'preset_handler') and self._manager.preset_handler:
            self._manager.preset_handler._update_save_button_enabled_state()

    def _port_operation(self, operation_type, output_name, input_name, is_midi, is_undo_redo=False):
        """
        Perform a port operation (connect or disconnect).

        Args:
            operation_type: The operation type ('connect' or 'disconnect')
            output_name: The name of the output port
            input_name: The name of the input port
            is_midi: Whether the ports are MIDI ports
            is_undo_redo: If True, skip adding to connection history.
        """
        try:
            if operation_type == 'connect':
                self._client.connect(output_name, input_name)
                if not is_undo_redo:
                    self._manager.connection_history.add_action('connect', output_name, input_name, is_midi)
            else: # disconnect
                self._client.disconnect(output_name, input_name)
                if not is_undo_redo:
                    self._manager.connection_history.add_action('disconnect', output_name, input_name, is_midi)

            if self._batch_count == 0:
                self._perform_refresh()

        except jack.JackError:
            # Silently ignore connection/disconnection errors.
            # This is expected during drag operations in the matrix view when
            # trying to connect/disconnect a port that is already in that state.
            pass

    def make_connection(self, output_name, input_name, is_undo_redo=False):
        """
        Make a connection between an output port and an input port.

        Args:
            output_name: The name of the output port
            input_name: The name of the input port
            is_undo_redo: If True, skip adding to connection history.
        """
        self._port_operation('connect', output_name, input_name, is_midi=False, is_undo_redo=is_undo_redo)

    def make_midi_connection(self, output_name, input_name, is_undo_redo=False):
        """
        Make a MIDI connection between an output port and an input port.

        Args:
            output_name: The name of the output port
            input_name: The name of the input port
            is_undo_redo: If True, skip adding to connection history.
        """
        self._port_operation('connect', output_name, input_name, is_midi=True, is_undo_redo=is_undo_redo)

    def break_connection(self, output_name, input_name, is_undo_redo=False):
        """
        Break a connection between an output port and an input port.

        Args:
            output_name: The name of the output port
            input_name: The name of the input port
            is_undo_redo: If True, skip adding to connection history.
        """
        self._port_operation('disconnect', output_name, input_name, is_midi=False, is_undo_redo=is_undo_redo)

    def break_midi_connection(self, output_name, input_name, is_undo_redo=False):
        """
        Break a MIDI connection between an output port and an input port.

        Args:
            output_name: The name of the output port
            input_name: The name of the input port
            is_undo_redo: If True, skip adding to connection history.
        """
        self._port_operation('disconnect', output_name, input_name, is_midi=True, is_undo_redo=is_undo_redo)

    def make_multiple_connections(self, outputs, inputs, is_undo_redo=False):
        """
        Connects multiple output ports to multiple input ports.

        Args:
            outputs: The output ports
            inputs: The input ports
            is_undo_redo: If True, skip adding to connection history.
        """
        if not outputs or not inputs:
            print("Warning: make_multiple_connections called with empty outputs or inputs.")
            return

        # Ensure inputs are lists for consistent handling
        output_list = outputs if isinstance(outputs, list) else [outputs]
        input_list = inputs if isinstance(inputs, list) else [inputs]

        if not output_list or not input_list:
            print(f"Warning: make_multiple_connections called with empty lists after ensuring list type: outputs={output_list}, inputs={input_list}")
            return

        # Determine if MIDI or Audio based on the manager's current tab
        is_midi = self._manager.ui_manager.tab_widget.currentIndex() == 1 # Assuming MIDI is tab index 1
        # Use _port_operation directly as it handles history and updates
        operation_type = 'connect'

        num_outputs = len(output_list)
        num_inputs = len(input_list)
        made_connection_attempt = False # Track if any operation was attempted

        print(f"make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs. MIDI: {is_midi}")

        if num_outputs > 1 and num_inputs == 1:
            # Group/List to Port: Connect all outputs to the single input
            single_input = input_list[0]
            print(f"  Scenario: Group/List ({num_outputs}) -> Port ({single_input})")
            for output_name in output_list:
                try:
                    self._port_operation(operation_type, output_name, single_input, is_midi, is_undo_redo=is_undo_redo)
                    made_connection_attempt = True
                except jack.JackError as e:
                    print(f"  Failed to connect {output_name} -> {single_input}: {e}")

        elif num_outputs == 1 and num_inputs > 1:
            # Port to Group/List: Connect the single output to all inputs
            single_output = output_list[0]
            print(f"  Scenario: Port ({single_output}) -> Group/List ({num_inputs})")
            for input_name in input_list:
                try:
                    self._port_operation(operation_type, single_output, input_name, is_midi, is_undo_redo=is_undo_redo)
                    made_connection_attempt = True
                except jack.JackError as e:
                    print(f"  Failed to connect {single_output} -> {input_name}: {e}")

        elif num_outputs > 1 and num_inputs > 1:
            # Group/List to Group/List: Use suffix matching then sequential matching
            print(f"  Scenario: Group/List ({num_outputs}) -> Group/List ({num_inputs}) - Applying suffix/sequential matching")

            # Define common suffixes for matching
            common_suffixes = [
                '_FL', '_FR', '_SL', '_SR', '_FC', '_LFE', '_RL', '_RR',
                '_L', '_R', '_1', '_2', '_3', '_4', '_5', '_6', '_7', '_8',
                'left', 'right', 'Left', 'Right'
            ]

            # Create copies to modify while iterating
            unmatched_outputs = list(output_list)
            unmatched_inputs = list(input_list)
            connections_made_in_group = [] # Track connections made in this block

            # First pass: match by exact suffixes
            for suffix in common_suffixes:
                outputs_with_suffix = [p for p in unmatched_outputs if p.endswith(suffix)]
                inputs_with_suffix = [p for p in unmatched_inputs if p.endswith(suffix)]

                # Pair up matching ports based on suffix
                pairs_to_connect = min(len(outputs_with_suffix), len(inputs_with_suffix))
                for i in range(pairs_to_connect):
                    out_p = outputs_with_suffix[i]
                    in_p = inputs_with_suffix[i]
                    try:
                        print(f"    Suffix Match ({suffix}): {out_p} -> {in_p}")
                        # Use _port_operation directly, passing the flag
                        self._port_operation(operation_type, out_p, in_p, is_midi, is_undo_redo=is_undo_redo)
                        connections_made_in_group.append((out_p, in_p))
                        unmatched_outputs.remove(out_p)
                        unmatched_inputs.remove(in_p)
                        made_connection_attempt = True # Set the outer flag
                    except Exception as e:
                        print(f"      Connection failed: {e}")

            # Second pass: try to match remaining ports sequentially
            while unmatched_outputs and unmatched_inputs:
                out_p = unmatched_outputs[0]
                in_p = unmatched_inputs[0]
                try:
                    print(f"    Sequential Match: {out_p} -> {in_p}")
                    # Use _port_operation directly, passing the flag
                    self._port_operation(operation_type, out_p, in_p, is_midi, is_undo_redo=is_undo_redo)
                    connections_made_in_group.append((out_p, in_p))
                    made_connection_attempt = True # Set the outer flag
                except Exception as e:
                    print(f"      Connection failed: {e}")
                # Remove the matched ports regardless of success to avoid infinite loops on error
                unmatched_outputs.pop(0)
                unmatched_inputs.pop(0)

            print(f"  Group-to-group connection finished. Attempted {len(connections_made_in_group)} connections.")

        elif num_outputs == 1 and num_inputs == 1:
            # Single Port to Single Port
            single_output = output_list[0]
            single_input = input_list[0]
            print(f"  Scenario: Port ({single_output}) -> Port ({single_input})")
            try:
                self._port_operation(operation_type, single_output, single_input, is_midi, is_undo_redo=is_undo_redo)
                made_connection_attempt = True
            except jack.JackError as e:
                print(f"  Failed to connect {single_output} -> {single_input}: {e}")
        else:
            # Should not happen if lists are not empty at the start
            print(f"Warning: Unexpected case in make_multiple_connections: {num_outputs} outputs, {num_inputs} inputs")

        # No need for a final refresh here, as _port_operation handles refreshes internally now.
        if made_connection_attempt:
             print("Multiple connection process finished.")


    def _get_existing_connections_between(self, output_ports, input_ports):
        """
        Returns a set of existing (output, input) connection tuples between the given port lists.

        Args:
            output_ports: The output ports
            input_ports: The input ports

        Returns:
            set: The existing connections
        """
        existing_connections = set()
        if not output_ports or not input_ports:
            return existing_connections
        try:
            # Convert input_ports to a set for faster lookups
            input_ports_set = set(input_ports)
            # Determine if MIDI based on manager's current tab context
            is_midi = self._manager.ui_manager.tab_widget.currentIndex() == 1

            for out_port in output_ports:
                # Check connections for this output port
                try:
                    # Ensure port exists before querying
                    if not any(p.name == out_port for p in self._client.get_ports(is_output=True, is_midi=is_midi)):
                        continue

                    connections = self._client.get_all_connections(out_port)
                    for conn in connections:
                        # If the connected input port is in our target input set, add the tuple
                        if conn.name in input_ports_set:
                            existing_connections.add((out_port, conn.name))
                except jack.JackError:
                    continue # Ignore error for this specific output port
            return existing_connections
        except jack.JackError as e:
            # Broader error during the process
            print(f"Error getting existing connections: {e}")
            return existing_connections # Return what we have found so far or empty set

    def disconnect_node(self, node_name, is_undo_redo=False):
        """
        Disconnect all connections from/to a specific port.

        Args:
            node_name: The name of the port to disconnect
            is_undo_redo: If True, skip adding to connection history.
        """
        try:
            port_obj = self._client.get_port_by_name(node_name)
            is_midi = port_obj.is_midi
            is_input = port_obj.is_input
            is_output = port_obj.is_output

            if is_input:
                # Node is an input port, find all outputs connected to it
                all_output_ports = self._client.get_ports(is_output=True, is_midi=is_midi)
                for output_port in all_output_ports:
                    try:
                        connections = self._client.get_all_connections(output_port)
                        if node_name in [conn.name for conn in connections]:
                            print(f"Disconnecting (input node): {output_port.name} -> {node_name}")
                            self._port_operation('disconnect', output_port.name, node_name, is_midi, is_undo_redo=is_undo_redo)
                    except jack.JackError:
                        continue # Ignore error for one output port
            elif is_output:
                # Node is an output port, find all inputs it's connected to
                try:
                    connections = self._client.get_all_connections(node_name)
                    for input_port in connections:
                         # Ensure we only disconnect ports of the same type (audio/midi)
                        if input_port.is_midi == is_midi:
                            print(f"Disconnecting (output node): {node_name} -> {input_port.name}")
                            self._port_operation('disconnect', node_name, input_port.name, is_midi, is_undo_redo=is_undo_redo)
                except jack.JackError as e:
                     print(f"Error getting connections for output node {node_name}: {e}")

        except jack.JackError as e:
            print(f"Error disconnecting node {node_name}: {e}")


    def _get_current_connections(self):
        """Gets the current state of all JACK audio and MIDI connections."""
        all_connections = []
        try:
            # Get all output ports (both audio and MIDI)
            output_ports = self._client.get_ports(is_output=True)
            for output_port in output_ports:
                try:
                    # Check if port still exists before getting connections
                    if not any(p.name == output_port.name for p in self._client.get_ports(is_output=True)):
                        continue
                    connected_inputs = self._client.get_all_connections(output_port)
                    port_type = "midi" if output_port.is_midi else "audio"
                    for input_port in connected_inputs:
                        # Ensure the connected port is also of the same type (should always be true)
                        if input_port.is_midi == output_port.is_midi:
                             all_connections.append({
                                 "output": output_port.name,
                                 "input": input_port.name,
                                 "type": port_type
                             })
                except jack.JackError as conn_err:
                    # Ignore errors getting connections for a single port (it might have disappeared)
                    print(f"Warning: Could not get connections for {output_port.name}: {conn_err}")
                    continue
        except jack.JackError as e:
            print(f"Error getting current connections: {e}")
        return all_connections

    def disconnect_all_ports_of_client(self, client_name: str, is_undo_redo=False):
        """
        Disconnects all ports belonging to a given client.

        Args:
            client_name: The name of the client whose ports to disconnect.
            is_undo_redo: If True, skip adding to connection history.
        """
        print(f"Attempting to disconnect all ports of client: {client_name}")
        disconnected_something = False
        try:
            # Get all ports (audio and MIDI)
            all_ports = self._client.get_ports()
            if not all_ports:
                print(f"  No ports found on the JACK server.")
                return

            # Filter for ports belonging to the specified client
            client_ports = [p for p in all_ports if p.name.startswith(client_name + ':')]

            if not client_ports:
                print(f"  No ports found for client {client_name}.")
                return

            for port_obj in client_ports:
                port_name = port_obj.name
                is_midi = port_obj.is_midi
                
                if port_obj.is_input:
                    # Port is an input, find all outputs connected to it
                    all_output_ports = self._client.get_ports(is_output=True, is_midi=is_midi)
                    for output_port_obj in all_output_ports:
                        try:
                            # Check if output_port_obj still exists
                            if not any(p.name == output_port_obj.name for p in self._client.get_ports(is_output=True, is_midi=is_midi)):
                                continue
                            connections = self._client.get_all_connections(output_port_obj.name)
                            if port_name in [conn.name for conn in connections]:
                                print(f"  Disconnecting (client input port): {output_port_obj.name} -> {port_name}")
                                self._port_operation('disconnect', output_port_obj.name, port_name, is_midi, is_undo_redo=is_undo_redo)
                                disconnected_something = True
                        except jack.JackError:
                            continue # Ignore error for one output port connection check
                elif port_obj.is_output:
                    # Port is an output, find all inputs it's connected to
                    try:
                        # Check if port_obj still exists
                        if not any(p.name == port_name for p in self._client.get_ports(is_output=True, is_midi=is_midi)):
                            continue
                        connections = self._client.get_all_connections(port_name)
                        for input_port_obj in connections:
                            if input_port_obj.is_midi == is_midi: # Ensure type match
                                print(f"  Disconnecting (client output port): {port_name} -> {input_port_obj.name}")
                                self._port_operation('disconnect', port_name, input_port_obj.name, is_midi, is_undo_redo=is_undo_redo)
                                disconnected_something = True
                    except jack.JackError as e:
                        print(f"  Error getting connections for output port {port_name} of client {client_name}: {e}")
            
            if disconnected_something:
                print(f"Finished disconnecting ports for client {client_name}.")
            else:
                print(f"No active connections found to disconnect for client {client_name}.")

        except jack.JackError as e:
            print(f"Error disconnecting ports for client {client_name}: {e}")
        except Exception as e:
            print(f"Unexpected error disconnecting ports for client {client_name}: {type(e).__name__} - {e}")
