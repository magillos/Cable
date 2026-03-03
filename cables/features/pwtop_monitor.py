"""
PwTopMonitor - Monitors and displays PipeWire statistics using pw-top
"""

import shutil
from typing import Optional
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QTextEdit

import logging
logger = logging.getLogger(__name__)

class PwTopMonitor:
    """
    Monitors and displays PipeWire statistics using pw-top.
    
    This class runs the pw-top command in batch mode and displays its output
    in a text widget, providing real-time statistics about PipeWire.
    """
    
    def __init__(self, manager: object, pwtop_text_widget: QTextEdit) -> None:
        """
        Initialize the PwTopMonitor.
        
        Args:
            manager: The JackConnectionManager instance
            pwtop_text_widget: The QTextEdit widget to display the output
        """
        self.manager = manager
        self.pwtop_text = pwtop_text_widget
        self.pw_process: Optional[QProcess] = None
        self.pwtop_buffer: str = ""
        self.last_complete_cycle: Optional[str] = None
        self.flatpak_env = manager.flatpak_env
    
    def start(self) -> None:
        """Start the pw-top process in batch mode."""
        if self.pw_process is None or self.pw_process.state() == QProcess.ProcessState.NotRunning:
            self.pw_process = QProcess()
            
            if self.flatpak_env:
                self.pw_process.setProgram("flatpak-spawn")
                self.pw_process.setArguments(["--host", "pw-top", "-b"])
            else:
                # Check if pw-top exists
                pw_top_path = shutil.which("pw-top")
                if not pw_top_path:
                    self.pwtop_text.setText("Error: 'pw-top' command not found.\nPlease install pipewire-utils or equivalent.")
                    self.pw_process = None  # Ensure process is None if command not found
                    return
                self.pw_process.setProgram(pw_top_path)
                self.pw_process.setArguments(["-b"])
            
            self.pw_process.readyReadStandardOutput.connect(self.handle_pwtop_output)
            self.pw_process.errorOccurred.connect(self.handle_pwtop_error)
            self.pw_process.finished.connect(self.handle_pwtop_finished)
# Note: The refresh rate of the pw-top display is determined by the
            # internal timing of the 'pw-top -b' command itself and how quickly
            # it outputs data. It is not directly configurable via app_config.py.
            # The application processes the data as it arrives from the subprocess.
            self.pw_process.start()
            logger.info("PwTopMonitor: Started pw-top process.")
        else:
            logger.debug("PwTopMonitor: pw-top process already running.")
    
    def stop(self) -> None:
        """Stop the pw-top process."""
        if self.pw_process is not None and self.pw_process.state() != QProcess.ProcessState.NotRunning:
            logger.info("PwTopMonitor: Stopping pw-top process...")
            # Close process standard I/O channels first
            try:
                self.pw_process.closeReadChannel(QProcess.ProcessChannel.StandardOutput)
                self.pw_process.closeReadChannel(QProcess.ProcessChannel.StandardError)
                self.pw_process.closeWriteChannel()
            except Exception as e:
                logger.debug(f"PwTopMonitor: Error closing process channels: {e}")
            
            # Terminate gracefully first
            self.pw_process.terminate()
            
            # Give it some time to terminate gracefully
            if not self.pw_process.waitForFinished(500):  # Reduced wait time
                logger.debug("PwTopMonitor: pw-top did not terminate gracefully, killing...")
                # Force kill if it doesn't terminate
                self.pw_process.kill()
                self.pw_process.waitForFinished(500)  # Wait for kill confirmation
            logger.debug("PwTopMonitor: pw-top process stopped.")
        else:
            logger.debug("PwTopMonitor: stop() called but process was not running or None.")
        self.pw_process = None  # Ensure process reference is cleared
    
    def handle_pwtop_output(self) -> None:
        """Handle new output from pw-top."""
        if self.pw_process is not None:
            try:
                data = self.pw_process.readAllStandardOutput().data().decode()
                if data:
                    # Append new data to buffer
                    self.pwtop_buffer += data
                    
                    # Extract complete cycle
                    complete_cycle = self.extract_latest_complete_cycle()
                    
                    # Update our stored complete cycle if we found a new one
                    if complete_cycle:
                        self.last_complete_cycle = complete_cycle
                    
                    # Always display the latest known complete cycle
                    if self.last_complete_cycle:
                        self.pwtop_text.setText(self.last_complete_cycle)
                        # Keep cursor at the top to maintain stable view
                        self.pwtop_text.verticalScrollBar().setValue(0)
                    
                    # Limit buffer size to prevent memory issues
                    if len(self.pwtop_buffer) > 10000:
                        self.pwtop_buffer = self.pwtop_buffer[-5000:]
            except Exception as e:
                logger.debug(f"PwTopMonitor: Error handling pw-top output: {e}")
    
    def handle_pwtop_error(self, error: QProcess.ProcessError) -> None:
        """Handle pw-top process errors."""
        error_string = "Unknown error"
        if self.pw_process:
            try:
                error_string = self.pw_process.errorString()
            except Exception as e:
                logger.debug(f"PwTopMonitor: Could not get error string: {e}")
        logger.debug(f"PwTopMonitor: pw-top process error: {error} - {error_string}")
        # Optionally display error in the text widget
        self.pwtop_text.append(f"\nError running pw-top: {error_string}")
    
    def handle_pwtop_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """Handle pw-top process completion."""
        status_str = "NormalExit" if exit_status == QProcess.ExitStatus.NormalExit else "CrashExit"
        logger.debug(f"PwTopMonitor: pw-top process finished - Exit code: {exit_code}, Status: {status_str}")
    
    def extract_latest_complete_cycle(self) -> Optional[str]:
        """
        Extract the latest complete cycle from the pw-top output buffer.
        
        Returns:
            str: The latest complete cycle, or None if no complete cycle is found
        """
        lines = self.pwtop_buffer.split('\n')
        
        # Find all lines that start with 'S' and contain 'ID' and 'NAME'
        header_indices = [
            i for i, line in enumerate(lines)
            if line.startswith('S') and 'ID' in line and 'NAME' in line
        ]
        
        # Keep buffer size manageable by removing old data
        if len(header_indices) > 2:
            keep_from_line = header_indices[-2]  # Keep last 2 cycles
            self.pwtop_buffer = '\n'.join(lines[keep_from_line:])
            # Re-calculate header indices for the trimmed buffer
            lines = self.pwtop_buffer.split('\n')
            header_indices = [
                i for i, line in enumerate(lines)
                if line.startswith('S') and 'ID' in line and 'NAME' in line
            ]
        
        # Need at least 2 headers to identify a complete cycle
        if len(header_indices) < 2:
            return None
        
        # Extract section between last two headers
        start_idx = header_indices[-2]
        end_idx = header_indices[-1]
        section = lines[start_idx:end_idx]
        
        # Basic validation - should have some minimum content
        if len(section) < 3:
            return None
        
        return '\n'.join(section)
