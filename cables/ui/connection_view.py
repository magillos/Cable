"""
ConnectionView - Visualizes connections between ports
"""

from PyQt6.QtWidgets import QGraphicsView
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPainter

class ConnectionView(QGraphicsView):
    """
    A custom QGraphicsView for visualizing connections between ports.
    
    This class provides a view for displaying connection lines between
    audio or MIDI ports, with support for automatic refreshing.
    """
    
    def __init__(self, scene, parent=None):
        """
        Initialize the ConnectionView.
        
        Args:
            scene: The QGraphicsScene to display
            parent: The parent widget
        """
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.refresh_timer = QTimer()
    
    def start_refresh_timer(self, refresh_callback, interval=1000):
        """
        Start the refresh timer to periodically update the view.
        
        Args:
            refresh_callback: The function to call when refreshing
            interval: The refresh interval in milliseconds
        """
        self.refresh_timer.timeout.connect(refresh_callback)
        self.refresh_timer.start(interval)
    
    def resizeEvent(self, event):
        """
        Handle resize events to maintain the view of the scene.
        
        Args:
            event: The resize event
        """
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def connect_to_jack(self, jack_client):
        """
        Connect to JACK client and initialize port monitoring.
        
        Args:
            jack_client: The JACK client instance to connect to
        """
        self.jack_client = jack_client
        self._port_cache = {}  # Clear cache when connecting to new client
        self._poll_timer = QTimer()
    
    def connect_to_jack_signals(self, client):
        """
        Connect JACK client signals to view update handlers.
        
        Args:
            client: The JACK client instance to connect signals for
        """
        # Connect signals to update the view when ports or connections change
        client.port_registered = self._on_port_registered
        client.connection_changed = self._on_connection_changed
    def _poll_jack_ports(self):
        """Poll JACK server for port changes and update visualization."""
        if not self.jack_client:
            return
            
        try:
            # Get all ports
            all_ports = self.jack_client.get_ports()
            current_ports = {port.name: port for port in all_ports}
            
            # Check for removed ports
            removed_ports = set(self._port_cache.keys()) - set(current_ports.keys())
            for port_name in removed_ports:
                self._on_port_removed(port_name)
            
            # Check for new or changed ports
            for port_name, port in current_ports.items():
                if port_name not in self._port_cache or self._port_cache[port_name].is_input != port.is_input:
                    self._on_port_added(port)
            
            # Update cache
            self._port_cache = current_ports
            
            # Update visualization after port changes
            self.scene().update()
            
        except jack.JackError as e:
            print(f"Error polling JACK ports: {e}")
            return
    
    def _on_port_registered(self, port):
        """Handle port registration events."""
        self.viewport().update()
    
    def _on_connection_changed(self, port1, port2, is_connected):
        """Handle connection change events."""
        self.viewport().update()
