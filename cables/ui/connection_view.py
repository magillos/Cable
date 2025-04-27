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
    
    def resizeEvent(self, event):
        """
        Handle resize events to maintain the view of the scene.
        
        Args:
            event: The resize event
        """
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
    
    def start_refresh_timer(self, callback, interval=1):
        """
        Start the timer to refresh connections visualization.
        
        Args:
            callback: The function to call when the timer fires
            interval: The timer interval in milliseconds (default: 1ms)
        """
        self.refresh_timer.timeout.connect(callback)
        self.refresh_timer.start(interval)
    
    def stop_refresh_timer(self):
        """Stop the refresh timer."""
        self.refresh_timer.stop()
        if self.refresh_timer.receivers(self.refresh_timer.timeout) > 0:
            self.refresh_timer.timeout.disconnect()
