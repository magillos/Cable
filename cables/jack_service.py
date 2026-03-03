# cables/jack_service.py
"""
Centralized JACK service singleton for all JACK operations.

This module provides a single jack.Client instance shared across the entire app,
with signals for thread-safe UI updates from JACK callbacks.
"""

import jack
import threading
from typing import List, Optional, Tuple
from PyQt6.QtCore import QObject, pyqtSignal

import logging
logger = logging.getLogger(__name__)

__all__ = ['JackService']


class JackService(QObject):
    """Singleton service for all JACK operations."""
    
    _instance: Optional['JackService'] = None
    
    # === Signals (for thread-safe UI updates from JACK callbacks) ===
    port_added = pyqtSignal(str, str, int, str, bool)  # port_name, client_name, flags, type, is_input
    port_removed = pyqtSignal(str, str)                # port_name, client_name
    client_added = pyqtSignal(str)                     # client_name
    client_removed = pyqtSignal(str)                   # client_name
    connection_made = pyqtSignal(str, str)             # out_port, in_port
    connection_broken = pyqtSignal(str, str)           # out_port, in_port
    xrun_occurred = pyqtSignal(int)                    # xrun count
    shutdown = pyqtSignal()                            # JACK server shutdown
    
    # Legacy signals for backward compatibility
    port_registered = pyqtSignal(str, bool)            # port name, is_input
    port_unregistered = pyqtSignal(str, bool)          # port name, is_input
    client_registered = pyqtSignal(str, bool)          # client_name, is_registered
    ports_connected = pyqtSignal(str, str, bool)       # out_port, in_port, is_connected
    
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._client: Optional[jack.Client] = None
        self._active = False
        self._xrun_count = 0
        self._closing = False  # Flag to prevent callbacks during shutdown
        self._close_lock = threading.Lock()  # Thread-safe close flag access
    
    @classmethod
    def instance(cls) -> 'JackService':
        """Get the singleton instance, creating it if necessary."""
        if cls._instance is None:
            cls._instance = JackService()
        return cls._instance
    
    def initialize(self, client_name: str = 'Cable') -> bool:
        """
        Initialize the JACK client.
        
        Args:
            client_name: Name to register with JACK server.
            
        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._client is not None:
            return True
        
        try:
            self._client = jack.Client(client_name)
            self._setup_callbacks()
            return True
        except jack.JackError as e:
            logger.debug(f"Failed to create JACK client '{client_name}': {e}")
            self._client = None
            return False
    
    def set_client(self, client: jack.Client, setup_callbacks: bool = False) -> None:
        """
        Use an existing JACK client instead of creating a new one.
        
        This allows JackService to share a client with existing code
        during migration.
        
        Args:
            client: An existing jack.Client instance.
            setup_callbacks: If True, set up JACK callbacks on this client.
                             If False (default), caller is responsible for callbacks.
        """
        self._client = client
        if setup_callbacks:
            self._setup_callbacks()
    
    def _setup_callbacks(self) -> None:
        """Set up JACK callbacks that emit Qt signals."""
        if self._client is None:
            return
        
        self._client.set_port_registration_callback(self._on_port_registration)
        self._client.set_client_registration_callback(self._on_client_registration)
        self._client.set_port_connect_callback(self._on_port_connect)
        self._client.set_shutdown_callback(self._on_shutdown)
        self._client.set_xrun_callback(self._on_xrun)
    
    def _is_closing(self) -> bool:
        """Thread-safe check if we're shutting down.
        
        Returns True if we're closing OR if the QObject has been deleted,
        to prevent any callback activity on a deleted object.
        """
        try:
            # Check if the C++ object still exists by accessing a property
            # This will raise RuntimeError if the object has been deleted
            _ = self.parent()
            with self._close_lock:
                return self._closing
        except (RuntimeError, AttributeError):
            # QObject has been deleted - treat as closing
            return True
    
    def _on_port_registration(self, port: jack.Port, registered: bool) -> None:
        """JACK callback for port registration/unregistration."""
        # Early exit if we're shutting down to prevent signal emission on deleted QObject
        if self._is_closing():
            return
        try:
            if port is None:
                return
            
            if not hasattr(port, 'name') or not hasattr(port, 'is_input'):
                return
            
            port_name = port.name
            if not isinstance(port_name, str) or not port_name:
                return
            
            client_name = port_name.split(':', 1)[0] if ':' in port_name else port_name
            
            try:
                port_flags = port.flags
            except AttributeError:
                port_flags = 0
            
            try:
                port_type = port.type
            except AttributeError:
                if hasattr(port, 'is_midi') and port.is_midi:
                    port_type = "midi"
                elif hasattr(port, 'is_audio') and port.is_audio:
                    port_type = "audio"
                else:
                    port_type = "unknown"
            
            is_input = port.is_input
            
            if registered:
                self.port_added.emit(port_name, client_name, port_flags, port_type, is_input)
                self.port_registered.emit(port_name, is_input)
            else:
                self.port_removed.emit(port_name, client_name)
                self.port_unregistered.emit(port_name, is_input)
                
        except Exception as e:
            logger.debug(f"JackService port registration callback error: {e}")
    
    def _on_client_registration(self, client_name: str, registered: bool) -> None:
        """JACK callback for client registration/unregistration."""
        # Early exit if we're shutting down to prevent signal emission on deleted QObject
        if self._is_closing():
            return
        try:
            if not isinstance(client_name, str) or not client_name:
                return
            
            if registered:
                self.client_added.emit(client_name)
            else:
                self.client_removed.emit(client_name)
            
            self.client_registered.emit(client_name, registered)
                
        except Exception as e:
            logger.debug(f"JackService client registration callback error: {e}")
    
    def _on_port_connect(self, port_a: jack.Port, port_b: jack.Port, connected: bool) -> None:
        """JACK callback for port connection/disconnection."""
        # Early exit if we're shutting down to prevent signal emission on deleted QObject
        if self._is_closing():
            return
        try:
            if not port_a or not port_b:
                return
            if not hasattr(port_a, 'name') or not hasattr(port_b, 'name'):
                return
            if not hasattr(port_a, 'is_output') or not hasattr(port_b, 'is_input'):
                return
            
            port_a_name = port_a.name
            port_b_name = port_b.name
            
            if port_a.is_output and port_b.is_input:
                out_port_name, in_port_name = port_a_name, port_b_name
            elif port_b.is_output and port_a.is_input:
                out_port_name, in_port_name = port_b_name, port_a_name
            else:
                return
            
            if connected:
                self.connection_made.emit(out_port_name, in_port_name)
            else:
                self.connection_broken.emit(out_port_name, in_port_name)
            
            self.ports_connected.emit(out_port_name, in_port_name, connected)
                
        except Exception as e:
            logger.debug(f"JackService port connect callback error: {e}")
    
    def _on_shutdown(self, status: int, reason: str) -> None:
        """JACK callback for server shutdown."""
        # Early exit if we're shutting down to prevent signal emission on deleted QObject
        if self._is_closing():
            return
        try:
            logger.debug(f"JACK server shutdown: status={status}, reason='{reason}'")
            self.shutdown.emit()
        except Exception as e:
            logger.debug(f"JackService shutdown callback error: {e}")
    
    def _on_xrun(self, delay_usecs: float) -> None:
        """JACK callback for xrun occurrence."""
        # Early exit if we're shutting down to prevent signal emission on deleted QObject
        if self._is_closing():
            return
        self._xrun_count += 1
        self.xrun_occurred.emit(self._xrun_count)
    
    # === Port Enumeration ===
    
    def get_ports(self, name_pattern: str = '', is_audio: bool = False, 
                  is_midi: bool = False, is_input: bool = False, 
                  is_output: bool = False, is_physical: bool = False,
                  can_monitor: bool = False, is_terminal: bool = False) -> List[jack.Port]:
        """
        Get JACK ports matching the given filters.
        
        Args:
            name_pattern: Regular expression to match port names.
            is_audio: If True, only return audio ports.
            is_midi: If True, only return MIDI ports.
            is_input: If True, only return input ports.
            is_output: If True, only return output ports.
            is_physical: If True, only return physical ports.
            can_monitor: If True, only return ports that can monitor.
            is_terminal: If True, only return terminal ports.
            
        Returns:
            List of matching jack.Port objects.
        """
        if self._client is None:
            return []
        try:
            return self._client.get_ports(
                name_pattern=name_pattern,
                is_audio=is_audio,
                is_midi=is_midi,
                is_input=is_input,
                is_output=is_output,
                is_physical=is_physical,
                can_monitor=can_monitor,
                is_terminal=is_terminal
            )
        except jack.JackError:
            return []
    
    def get_port_by_name(self, name: str) -> Optional[jack.Port]:
        """
        Get a JACK port by its full name.
        
        Args:
            name: Full port name (e.g., "client:port").
            
        Returns:
            The jack.Port object, or None if not found.
        """
        if self._client is None:
            return None
        try:
            return self._client.get_port_by_name(name)
        except jack.JackError:
            return None
    
    def get_all_connections(self, port_or_name: str | jack.Port) -> List[jack.Port]:
        """
        Get all connections for a specific port.
        
        This mirrors the behavior of jack.Client.get_all_connections(),
        returning a list of jack.Port objects connected to the given port.
        
        Args:
            port_or_name: The port name or jack.Port object to query.
                          
        Returns:
            List of jack.Port objects connected to the given port.
        """
        if self._client is None:
            return []
        
        try:
            if isinstance(port_or_name, jack.Port):
                port_name_to_query = port_or_name.name
            else:
                port_name_to_query = port_or_name
            return self._client.get_all_connections(port_name_to_query)
        except jack.JackError:
            return []
    
    def get_all_connections_as_tuples(self, port_or_name: Optional[str | jack.Port] = None) -> List[Tuple[str, str]]:
        """
        Get JACK connections as (source, dest) tuples.
        
        Args:
            port_or_name: If provided, get connections for that specific port.
                          Otherwise, get all connections in the system.
                          
        Returns:
            List of (source_port_name, dest_port_name) tuples.
        """
        if self._client is None:
            return []
        
        connections: List[Tuple[str, str]] = []
        try:
            if port_or_name:
                if isinstance(port_or_name, jack.Port):
                    port_name_to_query = port_or_name.name
                else:
                    port_name_to_query = port_or_name
                
                port_obj = self._client.get_port_by_name(port_name_to_query)
                if port_obj:
                    if port_obj.is_output:
                        connected_items = self._client.get_all_connections(port_name_to_query)
                        for item in connected_items:
                            dest_name = item.name if isinstance(item, jack.Port) else item
                            connections.append((port_name_to_query, dest_name))
                    elif port_obj.is_input:
                        source_items = self._client.get_all_connections(port_name_to_query)
                        for item in source_items:
                            src_name = item.name if isinstance(item, jack.Port) else item
                            connections.append((src_name, port_name_to_query))
            else:
                output_ports = self.get_ports(is_output=True)
                for port_obj in output_ports:
                    connected_dest_items = self._client.get_all_connections(port_obj.name)
                    for item in connected_dest_items:
                        dest_name = item.name if isinstance(item, jack.Port) else item
                        connections.append((port_obj.name, dest_name))
            return connections
        except jack.JackError:
            return []
    
    def get_client_names(self) -> List[str]:
        """
        Get a list of all JACK client names.
        
        Returns:
            Sorted list of unique client names.
        """
        if self._client is None:
            return []
        try:
            all_ports = self.get_ports()
            client_names = set()
            for port in all_ports:
                client_name = port.name.split(':')[0]
                client_names.add(client_name)
            return sorted(list(client_names))
        except jack.JackError:
            return []
    
    def get_connections_for_port(self, port: jack.Port) -> List[str]:
        """
        Get all connections for a specific jack.Port object.
        
        Args:
            port: The jack.Port to query.
            
        Returns:
            List of names of connected ports.
        """
        if self._client is None:
            return []
        try:
            connected_items = self._client.get_all_connections(port.name)
            return [item.name if isinstance(item, jack.Port) else item for item in connected_items]
        except jack.JackError:
            return []
    
    # === Connection Operations ===
    
    def connect(self, output: str, input: str) -> None:
        """
        Connect an output port to an input port.
        
        Args:
            output: Name of the output port.
            input: Name of the input port.
            
        Raises:
            jack.JackError: If connection fails or client not initialized.
        """
        if self._client is None:
            raise jack.JackError("JackService not initialized")
        self._client.connect(output, input)
    
    def disconnect(self, output: str, input: str) -> None:
        """
        Disconnect an output port from an input port.
        
        Args:
            output: Name of the output port.
            input: Name of the input port.
            
        Raises:
            jack.JackError: If disconnection fails or client not initialized.
        """
        if self._client is None:
            raise jack.JackError("JackService not initialized")
        self._client.disconnect(output, input)
    
    def disconnect_port(self, port_name: str) -> List[Tuple[str, str]]:
        """
        Disconnect all connections from/to a specific port.
        
        Args:
            port_name: Name of the port to disconnect.
            
        Returns:
            List of (output, input) tuples that were disconnected.
        """
        if self._client is None:
            return []
        
        disconnected = []
        try:
            port_obj = self._client.get_port_by_name(port_name)
            if port_obj is None:
                return []
            
            is_midi = port_obj.is_midi
            
            if port_obj.is_input:
                all_output_ports = self._client.get_ports(is_output=True, is_midi=is_midi)
                for output_port in all_output_ports:
                    try:
                        connections = self._client.get_all_connections(output_port)
                        if port_name in [conn.name for conn in connections]:
                            if self.disconnect(output_port.name, port_name):
                                disconnected.append((output_port.name, port_name))
                    except jack.JackError:
                        continue
            elif port_obj.is_output:
                try:
                    connections = self._client.get_all_connections(port_name)
                    for input_port in connections:
                        if input_port.is_midi == is_midi:
                            if self.disconnect(port_name, input_port.name):
                                disconnected.append((port_name, input_port.name))
                except jack.JackError:
                    logger.debug("jack.JackError suppressed")
        except jack.JackError:
            logger.debug("jack.JackError suppressed")
        
        return disconnected
    
    def disconnect_client_ports(self, client_name: str) -> List[Tuple[str, str]]:
        """
        Disconnect all ports belonging to a client.
        
        Args:
            client_name: Name of the client whose ports to disconnect.
            
        Returns:
            List of (output, input) tuples that were disconnected.
        """
        if self._client is None:
            return []
        
        disconnected = []
        try:
            all_ports = self._client.get_ports()
            client_ports = [p for p in all_ports if p.name.startswith(client_name + ':')]
            
            for port_obj in client_ports:
                port_name = port_obj.name
                is_midi = port_obj.is_midi
                
                if port_obj.is_input:
                    all_output_ports = self._client.get_ports(is_output=True, is_midi=is_midi)
                    for output_port_obj in all_output_ports:
                        try:
                            connections = self._client.get_all_connections(output_port_obj.name)
                            if port_name in [conn.name for conn in connections]:
                                if self.disconnect(output_port_obj.name, port_name):
                                    disconnected.append((output_port_obj.name, port_name))
                        except jack.JackError:
                            continue
                elif port_obj.is_output:
                    try:
                        connections = self._client.get_all_connections(port_name)
                        for input_port_obj in connections:
                            if input_port_obj.is_midi == is_midi:
                                if self.disconnect(port_name, input_port_obj.name):
                                    disconnected.append((port_name, input_port_obj.name))
                    except jack.JackError:
                        logger.debug("jack.JackError suppressed")
        except jack.JackError:
            logger.debug("jack.JackError suppressed")
        
        return disconnected
    
    def get_current_connections(self) -> List[dict]:
        """
        Get the current state of all JACK audio and MIDI connections.
        
        Returns:
            List of dicts with 'output', 'input', and 'type' keys.
        """
        if self._client is None:
            return []
        
        all_connections = []
        try:
            output_ports = self._client.get_ports(is_output=True)
            for output_port in output_ports:
                try:
                    connected_inputs = self._client.get_all_connections(output_port)
                    port_type = "midi" if output_port.is_midi else "audio"
                    for input_port in connected_inputs:
                        if input_port.is_midi == output_port.is_midi:
                            all_connections.append({
                                "output": output_port.name,
                                "input": input_port.name,
                                "type": port_type
                            })
                except jack.JackError:
                    continue
        except jack.JackError:
            logger.debug("jack.JackError suppressed")
        return all_connections
    
    def get_existing_connections_between(self, output_ports: List[str],
                                          input_ports: List[str],
                                          is_midi: bool = False) -> set[Tuple[str, str]]:
        """
        Get existing connections between two sets of ports.
        
        Args:
            output_ports: List of output port names.
            input_ports: List of input port names.
            is_midi: Whether to check MIDI ports.
            
        Returns:
            Set of (output, input) tuples.
        """
        if self._client is None:
            return set()
        
        existing_connections = set()
        if not output_ports or not input_ports:
            return existing_connections
        
        try:
            input_ports_set = set(input_ports)
            
            for out_port in output_ports:
                try:
                    if not any(p.name == out_port for p in self._client.get_ports(is_output=True, is_midi=is_midi)):
                        continue
                    
                    connections = self._client.get_all_connections(out_port)
                    for conn in connections:
                        if conn.name in input_ports_set:
                            existing_connections.add((out_port, conn.name))
                except jack.JackError:
                    continue
        except jack.JackError:
            logger.debug("jack.JackError suppressed")
        
        return existing_connections
    
    # === Monitoring (to be implemented in Phase 4.5) ===
    
    @property
    def cpu_load(self) -> float:
        """Get current JACK DSP CPU load percentage."""
        if self._client is None:
            return 0.0
        try:
            return self._client.cpu_load()
        except jack.JackError:
            return 0.0
    
    @property
    def xrun_count(self) -> int:
        """Get the current xrun count."""
        return self._xrun_count
    
    def reset_xrun_count(self) -> None:
        """Reset the xrun counter to zero."""
        self._xrun_count = 0
    
    # === Lifecycle ===
    
    def activate(self) -> None:
        """Activate the JACK client."""
        if self._client is not None and not self._active:
            try:
                self._client.activate()
                self._active = True
            except jack.JackError as e:
                logger.debug(f"Failed to activate JACK client: {e}")
    
    def deactivate(self) -> None:
        """Deactivate the JACK client."""
        if self._client is not None and self._active:
            try:
                self._client.deactivate()
                self._active = False
            except jack.JackError as e:
                logger.debug(f"Failed to deactivate JACK client: {e}")

    def close(self) -> None:
        """Deactivate and close the JACK client, preventing further callbacks.

        Must be called during application shutdown *before* Qt tears down
        QObjects, otherwise JACK's C-level callbacks fire on a deleted
        JackService and cause 'wrapped C/C++ object has been deleted' crashes.
        """
        # Set closing flag FIRST to prevent any new callback emissions
        with self._close_lock:
            if self._closing:
                return  # Already closing, avoid double-close
            self._closing = True
        
        logger.debug("JackService.close() - setting _closing=True and shutting down...")
        
        self.deactivate()
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.debug(f"Error closing JACK client: {e}")
            self._client = None
        
        logger.debug("JackService.close() - JACK client closed successfully")

    def is_active(self) -> bool:
        """Check if the JACK client is active."""
        return self._active
    
    @property
    def client(self) -> Optional[jack.Client]:
        """
        Direct access to the underlying jack.Client.
        
        Use this sparingly - prefer using JackService methods instead.
        Provided for backward compatibility during migration.
        """
        return self._client


def get_jack_service() -> JackService:
    """
    Get the global JackService singleton.
    
    Usage:
        from cables.jack_service import get_jack_service
        service = get_jack_service()
        ports = service.get_ports(is_audio=True, is_output=True)
    """
    return JackService.instance()
