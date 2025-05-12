import sys
import jack
# import threading # No longer managing its own thread or needing a lock for client access
from PyQt6.QtCore import QObject # pyqtSignal, pyqtSlot, QTimer removed

from . import constants # Import the constants module

# --- JACK Interaction (Simplified for Graph Specifics) ---

class GraphJackHandler(QObject):
    """Handles JACK client interactions using a shared client instance.
    This class is responsible for graph-specific JACK operations like
    connecting/disconnecting ports and querying port information, but does
    not manage the JACK client lifecycle or callbacks itself.
    """

    def __init__(self, jack_client: jack.Client, connection_history_ref=None, main_window_ref=None, jack_connection_handler_ref=None):
        super().__init__()
        self.jack_client = jack_client # The shared jack.Client instance
        self.connection_history = connection_history_ref
        self.main_window_ref = main_window_ref # For updating undo/redo buttons
        self.jack_connection_handler = jack_connection_handler_ref # Store the new handler

    # --- Safe Accessors ---
    def get_ports(self, **kwargs):
        # with self._lock: # Lock removed
        if not self.jack_client: return [] # Check if client exists
        try:
            return self.jack_client.get_ports(**kwargs)
        except jack.JackError:
            return []

    def get_all_connections(self, port_name):
        """Gets all connections for a given port name using the library's method."""
        # with self._lock: # Lock removed
        if not self.jack_client: return []
        try:
            # Get the Port object for the given name
            port_obj = self.jack_client.get_port_by_name(port_name)
            if not port_obj:
                # print(f"Warning: Port '{port_name}' not found in get_all_connections.")
                return [] # Port doesn't exist

            # Use the library's built-in method, passing the Port object
            connected_ports = self.jack_client.get_all_connections(port_obj)

            # Convert the list of connected Port objects to the expected tuple format
            connections = []
            if port_obj.is_output:
                # If the input port_name refers to an output port
                for connected_in_port in connected_ports:
                    if connected_in_port.is_input: # Sanity check
                        connections.append((port_obj.name, connected_in_port.name))
            elif port_obj.is_input:
                 # If the input port_name refers to an input port
                 for connected_out_port in connected_ports:
                     if connected_out_port.is_output: # Sanity check
                         connections.append((connected_out_port.name, port_obj.name))
            # else: port is neither input nor output? Should not happen.

            return connections # Returns list of (out_port_name, in_port_name) tuples
        except jack.JackError as e:
             print(f"JACK Error in get_all_connections for {port_name}: {e}", file=sys.stderr)
             return []
        except AttributeError as e: # Handle potential issues if port_obj is None or client inactive
             print(f"AttributeError in get_all_connections for {port_name}: {e}", file=sys.stderr)
             return []


    def get_port_by_name(self, name):
        # with self._lock: # Lock removed
        if not self.jack_client: return None
        try:
            return self.jack_client.get_port_by_name(name)
        except jack.JackError:
            return None


    # Connection methods (connect, disconnect, connect_all_between, disconnect_all_between)
    # are removed as their functionality is now centralized in JackConnectionHandler.
    # GraphJackHandler will primarily be used for querying port/client information for the graph.

    # Callbacks and related signals/slots are removed as they are now handled by JackConnectionManager
    # The GraphJackHandler no longer manages its own client lifecycle or JACK event callbacks.
