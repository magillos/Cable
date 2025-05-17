import sys
import jack
# import threading # No longer managing its own thread or needing a lock for client access
from PyQt6.QtCore import QObject # pyqtSignal, pyqtSlot, QTimer removed

from . import constants # Import the constants module
from cables import jack_utils # Import the new jack_utils module

# --- JACK Interaction (Simplified for Graph Specifics) ---

class GraphJackHandler(QObject):
    """Handles JACK client interactions using a shared client instance.
    This class is responsible for graph-specific JACK operations like
    querying port information, but does not manage the JACK client
    lifecycle or callbacks itself. Connection/disconnection logic is
    handled by JackConnectionHandler.
    """

    def __init__(self, jack_client: jack.Client, connection_history_ref=None, main_window_ref=None, jack_connection_handler_ref=None):
        super().__init__()
        self.jack_client = jack_client # The shared jack.Client instance
        self.connection_history = connection_history_ref
        self.main_window_ref = main_window_ref # For updating undo/redo buttons
        self.jack_connection_handler = jack_connection_handler_ref # Store the new handler

    # --- Safe Accessors ---
    def get_ports(self, **kwargs):
        if not self.jack_client: return []
        # Pass all keyword arguments directly to the utility function
        return jack_utils.get_all_jack_ports(self.jack_client, **kwargs)

    def get_all_connections(self, port_name: str):
        """
        Gets all connections for a given port name.
        Returns a list of (source_port_name, dest_port_name) tuples.
        """
        if not self.jack_client: return []
        # The utility function handles if port_name is a source or destination
        # and returns the connections in (source, dest) format.
        return jack_utils.get_all_jack_connections(self.jack_client, port_or_name=port_name)

    def get_port_by_name(self, name: str):
        if not self.jack_client: return None
        return jack_utils.get_jack_port_by_name(self.jack_client, name)


    # Connection methods (connect, disconnect, connect_all_between, disconnect_all_between)
    # are removed as their functionality is now centralized in JackConnectionHandler.
    # GraphJackHandler will primarily be used for querying port/client information for the graph.

    # Callbacks and related signals/slots are removed as they are now handled by JackConnectionManager
    # The GraphJackHandler no longer manages its own client lifecycle or JACK event callbacks.
