"""
ConnectionView - Visualizes connections between ports
"""

from PyQt6.QtWidgets import QGraphicsView
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPainter


class ConnectionView(QGraphicsView):
    """
    A custom QGraphicsView for visualizing connections between ports.
    
    This class provides a view for displaying connection lines between
    audio or MIDI ports, with support for event-driven refreshing.
    """
    
    # Signal to trigger refresh from any thread safely
    refresh_requested = pyqtSignal()
    
    def __init__(self, scene, parent=None):
        """
        Initialize the ConnectionView.
        
        Args:
            scene: The QGraphicsScene to display
            parent: The parent widget
        """
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Use BoundingRectViewportUpdate instead of FullViewportUpdate for better performance
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        
        # Optimization flags
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing, True)
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        
        # Debounced refresh timer - 16ms for ~60fps cap
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(16)
        
        self._refresh_callback = None
        
        # Connect internal signal for thread-safe refresh requests
        self.refresh_requested.connect(self._schedule_refresh)
        
        # Legacy timer for compatibility (will be removed/unused)
        self.refresh_timer = QTimer()
    
    def set_refresh_callback(self, callback):
        """
        Set the callback function for refreshing connections.
        
        Args:
            callback: Function to call when connections need to be redrawn
        """
        self._refresh_callback = callback
        # Disconnect any previous connection to avoid duplicates
        try:
            self._refresh_timer.timeout.disconnect()
        except TypeError:
            pass
        self._refresh_timer.timeout.connect(self._do_refresh)
    
    def _schedule_refresh(self):
        """Schedule a debounced refresh - restarts the timer if already running."""
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()
    
    def _do_refresh(self):
        """Execute the refresh callback."""
        if self._refresh_callback:
            self._refresh_callback()
    
    def request_refresh(self):
        """
        Request a connection refresh. This is debounced to ~60fps.
        Safe to call from any context.
        """
        self.refresh_requested.emit()
    
    def start_refresh_timer(self, refresh_callback, interval=1000):
        """
        Legacy method - now sets up event-driven refresh instead.
        The interval parameter is ignored; refresh is event-driven with debouncing.
        
        Args:
            refresh_callback: The function to call when refreshing
            interval: Ignored (kept for API compatibility)
        """
        self.set_refresh_callback(refresh_callback)
        # Do an initial refresh
        self._schedule_refresh()
    
    def resizeEvent(self, event):
        """
        Handle resize events to maintain the view of the scene.
        
        Args:
            event: The resize event
        """
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        # Schedule refresh after resize to update connection positions
        self._schedule_refresh()
    
    def connect_to_jack(self, jack_client):
        """
        Connect to JACK client and initialize port monitoring.
        
        Args:
            jack_client: The JACK client instance to connect to
        """
        self.jack_client = jack_client
        self._port_cache = {}
    
    def connect_to_jack_signals(self, client):
        """
        Connect JACK client signals to view update handlers.
        
        Args:
            client: The JACK client instance to connect signals for
        """
        pass
    
    def _on_port_registered(self, port):
        """Handle port registration events."""
        self.refresh_requested.emit()
    
    def _on_connection_changed(self, port1, port2, is_connected):
        """Handle connection change events."""
        self.refresh_requested.emit()
