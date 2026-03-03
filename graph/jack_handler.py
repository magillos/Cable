"""
Graph-specific JACK handler for querying port and client information.
"""

import sys
import jack
# import threading # No longer managing its own thread or needing a lock for client access
from PyQt6.QtCore import QObject # pyqtSignal, pyqtSlot, QTimer removed

from . import constants # Import the constants module
from cables.jack_service import get_jack_service

from typing import TYPE_CHECKING, List, Tuple, Optional, Any
from PyQt6.QtWidgets import QWidget
if TYPE_CHECKING:
    from cables.features.connection_history import ConnectionHistory
    from cables.jack_connection_handler import JackConnectionHandler

# --- JACK Interaction (Simplified for Graph Specifics) ---

class GraphJackHandler(QObject):
    """Handles JACK client interactions using a shared client instance.
    This class is responsible for graph-specific JACK operations like
    querying port information, but does not manage the JACK client
    lifecycle or callbacks itself. Connection/disconnection logic is
    handled by JackConnectionHandler.
    """

    def __init__(self, jack_client: jack.Client, connection_history_ref: Optional['ConnectionHistory'] = None, main_window_ref: Optional[QWidget] = None, jack_connection_handler_ref: Optional['JackConnectionHandler'] = None) -> None:
        super().__init__()
        self.jack_client = jack_client # The shared jack.Client instance
        self._jack_service = get_jack_service()
        self.connection_history = connection_history_ref
        self.main_window_ref = main_window_ref # For updating undo/redo buttons
        self.jack_connection_handler = jack_connection_handler_ref # Store the new handler

    # --- Safe Accessors ---
    def get_ports(self, **kwargs: Any) -> List[jack.Port]:
        if not self.jack_client: return []
        return self._jack_service.get_ports(**kwargs)

    def get_all_connections(self, port_name: str) -> List[Tuple[str, str]]:
        """
        Gets all connections for a given port name.
        Returns a list of (source_port_name, dest_port_name) tuples.
        """
        if not self.jack_client: return []
        return self._jack_service.get_all_connections_as_tuples(port_name)

    def get_port_by_name(self, name: str) -> Optional[jack.Port]:
        if not self.jack_client: return None
        return self._jack_service.get_port_by_name(name)


    # Connection methods (connect, disconnect, connect_all_between, disconnect_all_between)
    # are removed as their functionality is now centralized in JackConnectionHandler.
    # GraphJackHandler will primarily be used for querying port/client information for the graph.

    # Callbacks and related signals/slots are removed as they are now handled by JackConnectionManager
    # The GraphJackHandler no longer manages its own client lifecycle or JACK event callbacks.
