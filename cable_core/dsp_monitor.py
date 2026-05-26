#!/usr/bin/env python3
"""
DSPMonitor - Handles DSP load monitoring and XRUN tracking for Cable.

This module provides a manager class that handles:
- DSP load monitoring via JackService
- XRUN (buffer underrun) tracking
- Progress bar color updates based on load level
"""

import logging
from typing import TYPE_CHECKING, Optional, Any
from PyQt6.QtCore import QTimer, Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import QLabel, QProgressBar

if TYPE_CHECKING:
    from cables.jack_service import JackService

logger = logging.getLogger(__name__)

__all__ = ['DSPMonitor']


class DSPMonitor(QObject):
    """
    Manages DSP load monitoring and XRUN tracking.
    
    This class handles the monitoring of JACK DSP load and xrun events,
    updating UI elements accordingly.
    
    Usage:
        monitor = DSPMonitor(parent_widget)
        monitor.start_monitoring()
        # ... later ...
        monitor.stop_monitoring()
    """
    
    # Color thresholds for DSP load bar
    LOAD_GREEN_THRESHOLD = 50
    LOAD_YELLOW_THRESHOLD = 80
    
    # Colors
    COLOR_GREEN = "#4CAF50"
    COLOR_YELLOW = "#FFC107"
    COLOR_RED = "#F44336"
    
    def __init__(
        self,
        parent: Any,
        dsp_load_value: QLabel,
        dsp_load_bar: QProgressBar,
        xrun_display_value: QLabel,
        jack_service: Optional['JackService'] = None
    ) -> None:
        super().__init__(parent)
        self.parent_widget = parent  # QWidget reference for QTimer parenting
        self.dsp_load_value = dsp_load_value
        self.dsp_load_bar = dsp_load_bar
        self.xrun_display_value = xrun_display_value
        self._jack_service = jack_service
        
        # XRUN count (local tracking)
        self.xrun_count = 0
        
        # Timer for DSP load updates
        self._dsp_load_timer: Optional[QTimer] = None
        self._update_interval = 300  # ms
        
        # Set initial color
        self._update_dsp_load_bar_color(0)

        # Connect to theme manager for fast-path theme change refresh
        from cable_core.theme import get_theme_manager
        get_theme_manager().theme_changed.connect(self.on_theme_changed)
        
    def _get_jack_service(self) -> Optional['JackService']:
        """Get JackService instance, fetching if needed."""
        if self._jack_service is None:
            from cables.jack_service import get_jack_service
            self._jack_service = get_jack_service()
        return self._jack_service
    
    def initialize_jack_connection(self) -> bool:
        """
        Initialize connection to JackService for xrun tracking.
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        service = self._get_jack_service()
        if service is None:
            logger.warning("Could not get JackService instance")
            return False
        
        # Initialize JackService if no client exists yet (standalone mode)
        if service.client is None:
            if service.initialize('Cable'):
                service.activate()
        
        # Connect to xrun signal from JackService
        service.xrun_occurred.connect(self._on_xrun_signal)
        return True
    
    def start_monitoring(self) -> None:
        """Start the DSP load monitoring timer."""
        self._dsp_load_timer = QTimer(self.parent_widget)
        self._dsp_load_timer.timeout.connect(self._update_dsp_load)
        self._dsp_load_timer.start(self._update_interval)
        logger.debug("DSP monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop the DSP load monitoring timer."""
        if self._dsp_load_timer is not None:
            self._dsp_load_timer.stop()
            self._dsp_load_timer = None
            logger.debug("DSP monitoring stopped")
    
    def cleanup(self) -> None:
        """Clean up resources before quitting."""
        self.stop_monitoring()
        
        # Disconnect from JackService xrun signal
        service = self._get_jack_service()
        if service is not None:
            try:
                service.xrun_occurred.disconnect(self._on_xrun_signal)
            except (TypeError, RuntimeError):
                pass  # Signal was not connected or already disconnected
        logger.debug("DSP monitor cleanup complete")
    
    def _on_xrun_signal(self, xrun_count: int) -> None:
        """Slot invoked when JackService emits xrun_occurred signal."""
        self.xrun_count = xrun_count
        self._update_xrun_display()
    
    def _update_xrun_display(self) -> None:
        """Update the xrun display label."""
        self.xrun_display_value.setText(str(self.xrun_count))
    
    def reset_xrun_count(self) -> None:
        """Reset the xrun counter to zero."""
        self.xrun_count = 0
        service = self._get_jack_service()
        if service is not None:
            service.reset_xrun_count()
        self._update_xrun_display()
        logger.debug("XRUN count reset to zero")
    
    def _update_dsp_load(self) -> None:
        """Update the DSP load display."""
        service = self._get_jack_service()
        if service is None:
            return
        
        try:
            load = int(service.cpu_load)
            load = max(0, min(100, load))
            self.dsp_load_value.setText(f"{load}%")
            self.dsp_load_bar.setValue(load)
            self._update_dsp_load_bar_color(load)
        except Exception:
            pass
    
    def _update_dsp_load_bar_color(self, load: int) -> None:
        """Update the progress bar color based on load level."""
        if load < self.LOAD_GREEN_THRESHOLD:
            color = self.COLOR_GREEN
        elif load < self.LOAD_YELLOW_THRESHOLD:
            color = self.COLOR_YELLOW
        else:
            color = self.COLOR_RED
        
        # Determine if dark mode
        from PyQt6.QtWidgets import QApplication
        palette = QApplication.palette()
        dark_mode = palette.window().color().lightness() < 128
        
        # Set appropriate background color based on dark/light mode
        bg_color = "#333" if dark_mode else "#e0e0e0"
        border_color = "#555" if dark_mode else "#999"
        
        self.dsp_load_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {border_color};
                border-radius: 3px;
                background-color: {bg_color};
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 2px;
            }}
        """)

    def on_theme_changed(self) -> None:
        """Refresh load bar stylesheet immediately after a theme change."""
        self._update_dsp_load_bar_color(self.dsp_load_bar.value())
