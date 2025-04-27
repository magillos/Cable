"""
LatencyTester - Runs latency tests using jack_delay
"""

import re
import shutil
import subprocess
from PyQt6.QtCore import QTimer, QProcess
from PyQt6.QtGui import QTextCursor # Added import
from PyQt6.QtWidgets import QMessageBox, QSizePolicy

class LatencyTester:
    """
    Runs latency tests using jack_delay.
    
    This class provides functionality to measure the round-trip latency
    of an audio interface using jack_delay or jack_iodelay.
    """
    
    def __init__(self, manager):
        """
        Initialize the LatencyTester.
        
        Args:
            manager: The JackConnectionManager instance
        """
        self.manager = manager
        self.latency_process = None
        self.latency_values = []
        self.latency_timer = QTimer()
        self.latency_waiting_for_connection = False  # Flag to wait for connection
        # Store selected physical port aliases for latency test
        self.latency_selected_input_alias = None
        self.latency_selected_output_alias = None
        
        # Connect timer timeout signal internally
        self.latency_timer.timeout.connect(self.stop_latency_test)
    
    def run_latency_test(self):
        """Starts the jack_delay process and timer."""
        if self.latency_process is not None and self.latency_process.state() != QProcess.ProcessState.NotRunning:
            self.manager.latency_results_text.append("Test already in progress.")
            return
        
        # Refresh combo boxes with latest ports
        self._populate_latency_combos()
        
        self.manager.latency_run_button.setEnabled(False)
        self.manager.latency_stop_button.setEnabled(True)  # Enable Stop button
        self.manager.latency_results_text.clear()  # Clear previous results/messages
        
        if self.manager.latency_raw_output_checkbox.isChecked():
            self.manager.latency_results_text.setText("Starting latency test (Raw Output)...\n"
                                              "Select ports if not already selected.\n"
                                              "Attempting auto-connection...\n")
        else:
            self.manager.latency_results_text.setText("Starting latency test (Average)...\n"
                                              "Select ports if not already selected.\n"
                                              "Attempting auto-connection...\n"
                                              "Waiting for measurement signal...\n")
        
        self.latency_values = []
        # Only wait for connection signal if NOT showing raw output
        self.latency_waiting_for_connection = not self.manager.latency_raw_output_checkbox.isChecked()
        
        self.latency_process = QProcess()
        self.latency_process.readyReadStandardOutput.connect(self.handle_latency_output)
        self.latency_process.finished.connect(self.handle_latency_finished)
        self.latency_process.errorOccurred.connect(self.handle_latency_error)
        
        # Determine command based on environment
        if self.manager.flatpak_env:
            program = "flatpak-spawn"
            arguments = ["--host", "jack_delay"]
        else:
            # Try jack_delay first, then jack_iodelay as fallback
            program = shutil.which("jack_delay")
            if program is None:
                program = shutil.which("jack_iodelay")
            
            # If neither is found, show error and exit
            if program is None:
                self.manager.latency_results_text.setText("Error: Neither 'jack_delay' nor 'jack_iodelay' found.\n"
                                                  "Depending on your distribution, install jack-delay, jack_delay or jack-example-tools (jack_iodelay).")
                self.manager.latency_run_button.setEnabled(True)  # Re-enable run button
                self.manager.latency_stop_button.setEnabled(False)  # Ensure stop is disabled
                self.latency_process = None  # Clear the process object
                return  # Stop execution
            
            arguments = []
        
        self.latency_process.setProgram(program)  # Use the found program path
        self.latency_process.setArguments(arguments)
        self.latency_process.start()  # Start the process
        # Connection attempt is now triggered by _on_port_registered when jack_delay ports appear.
    
    def handle_latency_output(self):
        """Handles output from the jack_delay process."""
        if self.latency_process is None:
            return
        
        data = self.latency_process.readAllStandardOutput().data().decode()
        
        if self.manager.latency_raw_output_checkbox.isChecked():
            # Raw output mode: Append data directly
            self.manager.latency_results_text.moveCursor(QTextCursor.MoveOperation.End)
            self.manager.latency_results_text.insertPlainText(data)
            self.manager.latency_results_text.moveCursor(QTextCursor.MoveOperation.End)
        else:
            # Average calculation mode (original logic)
            # Check if we are waiting for the connection signal
            if self.latency_waiting_for_connection:
                # Check if any line contains a latency measurement
                if re.search(r'\d+\.\d+\s+ms', data):
                    self.latency_waiting_for_connection = False
                    self.manager.latency_results_text.setText("Connection detected. Running test...")
                    # Start the timer now
                    self.latency_timer.setSingleShot(True)
                    self.latency_timer.start(10000)  # 10 seconds
            
            # If not waiting (or connection just detected), parse for values
            if not self.latency_waiting_for_connection:
                for line in data.splitlines():
                    # Updated regex to capture both frames and ms
                    match = re.search(r'(\d+\.\d+)\s+frames\s+(\d+\.\d+)\s+ms', line)
                    if match:
                        try:
                            latency_frames = float(match.group(1))
                            latency_ms = float(match.group(2))
                            # Store both values as a tuple
                            self.latency_values.append((latency_frames, latency_ms))
                        except ValueError:
                            pass  # Ignore lines that don't parse correctly
    
    def stop_latency_test(self):
        """Stops the jack_delay process."""
        if self.latency_timer.isActive():
            self.latency_timer.stop()  # Stop timer if called manually before timeout
        
        if self.latency_process is not None and self.latency_process.state() != QProcess.ProcessState.NotRunning:
            self.manager.latency_results_text.append("\nStopping test...")
            self.latency_process.terminate()
            # Give it a moment to terminate gracefully before potentially killing
            if not self.latency_process.waitForFinished(500):
                self.latency_process.kill()
                self.latency_process.waitForFinished()  # Wait for kill confirmation
            
            self.latency_waiting_for_connection = False  # Reset flag
    
    def handle_latency_finished(self, exit_code, exit_status):
        """Handles the jack_delay process finishing."""
        # Clear previous text before showing final result
        self.manager.latency_results_text.clear()
        
        if self.manager.latency_raw_output_checkbox.isChecked():
            # If raw output was shown, just indicate stop
            self.manager.latency_results_text.setText("Measurement stopped.")
        elif self.latency_values:
            # Calculate average for frames and ms separately (only if not raw output)
            total_frames = sum(val[0] for val in self.latency_values)
            total_ms = sum(val[1] for val in self.latency_values)
            count = len(self.latency_values)
            average_frames = total_frames / count
            average_ms = total_ms / count
            # Display both average latencies
            self.manager.latency_results_text.setText(f"Round-trip latency (average): {average_frames:.3f} frames / {average_ms:.3f} ms")
        else:
            # Check if the process exited normally but produced no values
            if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
                # Display a clear error message
                self.manager.latency_results_text.setText("No valid latency readings obtained. Check connections.")
            elif exit_status == QProcess.ExitStatus.CrashExit:
                self.manager.latency_results_text.setText("Measurement stopped.")
            # Error message handled by handle_latency_error if exit code != 0 and no values were found
            elif exit_code != 0:
                # If an error occurred (handled by handle_latency_error),
                # ensure some message is shown if handle_latency_error didn't set one.
                if not self.manager.latency_results_text.toPlainText():
                    self.manager.latency_results_text.setText(f"Test failed (Exit code: {exit_code}). Check connections.")
            else:  # Should not happen often, but catch other cases
                self.manager.latency_results_text.setText("Test finished without valid readings.")
        
        self.latency_waiting_for_connection = False  # Reset flag
        self.manager.latency_run_button.setEnabled(True)
        self.manager.latency_stop_button.setEnabled(False)  # Disable Stop button
        self.latency_process = None  # Clear the process reference
    
    def handle_latency_error(self, error):
        """Handles errors occurring during the jack_delay process execution."""
        error_string = self.latency_process.errorString() if self.latency_process else "Unknown error"
        self.manager.latency_results_text.append(f"\nError running jack_delay: {error} - {error_string}")
        
        # Ensure timer and process are stopped/cleaned up
        if self.latency_timer.isActive():
            self.latency_timer.stop()
        if self.latency_process is not None:
            # Ensure process is terminated if it hasn't finished yet
            if self.latency_process.state() != QProcess.ProcessState.NotRunning:
                self.latency_process.kill()
                self.latency_process.waitForFinished()
            self.latency_process = None
        
        self.latency_waiting_for_connection = False  # Reset flag
        self.manager.latency_run_button.setEnabled(True)
        self.manager.latency_stop_button.setEnabled(False)  # Disable Stop button on error
    
    def _populate_latency_combos(self):
        """Populates the latency test combo boxes using python-jack."""
        capture_ports = []  # Physical capture devices (JACK outputs)
        playback_ports = []  # Physical playback devices (JACK inputs)
        try:
            # Get physical capture ports (System Output -> JACK Input)
            jack_capture_ports = self.manager.client.get_ports(is_physical=True, is_audio=True, is_output=True)
            capture_ports = sorted([port.name for port in jack_capture_ports])
            
            # Get physical playback ports (System Input <- JACK Output)
            jack_playback_ports = self.manager.client.get_ports(is_physical=True, is_audio=True, is_input=True)
            playback_ports = sorted([port.name for port in jack_playback_ports])
            
        except Exception as e:
            print(f"Error getting physical JACK ports: {e}")
            # Optionally display an error in the UI
        
        # Block signals while populating to avoid triggering handlers prematurely
        self.manager.latency_input_combo.blockSignals(True)
        self.manager.latency_output_combo.blockSignals(True)
        
        # Clear existing items first, keeping placeholder
        self.manager.latency_input_combo.clear()
        self.manager.latency_output_combo.clear()
        self.manager.latency_input_combo.addItem("Select Physical Input (Capture)...", None)  # Add placeholder back
        self.manager.latency_output_combo.addItem("Select Physical Output (Playback)...", None)  # Add placeholder back
        
        # Populate Input Combo (Capture Ports - JACK Outputs)
        for port_name in capture_ports:
            self.manager.latency_input_combo.addItem(port_name, port_name)  # Use name for display and data
        
        # Populate Output Combo (Playback Ports - JACK Inputs)
        for port_name in playback_ports:
            self.manager.latency_output_combo.addItem(port_name, port_name)  # Use name for display and data
        
        # Restore previous selection if port names still exist
        if self.latency_selected_input_alias:
            index = self.manager.latency_input_combo.findData(self.latency_selected_input_alias)
            if index != -1:
                self.manager.latency_input_combo.setCurrentIndex(index)
        if self.latency_selected_output_alias:
            index = self.manager.latency_output_combo.findData(self.latency_selected_output_alias)
            if index != -1:
                self.manager.latency_output_combo.setCurrentIndex(index)
        
        # Set Output Combo Width to Match Input Combo Width
        input_width = self.manager.latency_input_combo.sizeHint().width()
        if input_width > 0:  # Ensure valid width before setting
            self.manager.latency_output_combo.setMinimumWidth(input_width)
            # Ensure the output combo can expand horizontally if needed
            output_policy = self.manager.latency_output_combo.sizePolicy()
            # Using Expanding ensures it takes *at least* the input width, and can grow if layout dictates
            output_policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            self.manager.latency_output_combo.setSizePolicy(output_policy)
        
        # Unblock signals
        self.manager.latency_input_combo.blockSignals(False)
        self.manager.latency_output_combo.blockSignals(False)
    
    def _on_latency_input_selected(self, index):
        """Stores the selected physical input port alias."""
        self.latency_selected_input_alias = self.manager.latency_input_combo.itemData(index)
        # Attempt connection if output is also selected and test is running
        self._attempt_latency_auto_connection()
    
    def _on_latency_output_selected(self, index):
        """Stores the selected physical output port alias."""
        self.latency_selected_output_alias = self.manager.latency_output_combo.itemData(index)
        # Attempt connection if input is also selected and test is running
        self._attempt_latency_auto_connection()
    
    def _attempt_latency_auto_connection(self):
        """Connects selected physical ports to jack_delay if ports are selected."""
        # Only connect if both an input and output alias have been selected from the dropdowns.
        if (self.latency_selected_input_alias and
            self.latency_selected_output_alias):
            
            # Pipewire 'in' direction (our output_ports list) connects to jack_delay:out
            # Pipewire 'out' direction (our input_ports list) connects to jack_delay:in
            output_to_connect = self.latency_selected_output_alias  # This is the physical playback port alias
            input_to_connect = self.latency_selected_input_alias    # This is the physical capture port alias
            
            print(f"Attempting auto-connection: jack_delay:out -> {output_to_connect}")
            print(f"Attempting auto-connection: {input_to_connect} -> jack_delay:in")
            
            try:
                # Connect jack_delay output to the selected physical playback port
                # Ensure the target port exists before connecting
                if any(p.name == output_to_connect for p in self.manager.client.get_ports(is_input=True, is_audio=True)):
                    self.manager.make_connection("jack_delay:out", output_to_connect)
                else:
                    print(f"Warning: Target output port '{output_to_connect}' not found.")
                
                # Connect the selected physical capture port to jack_delay input
                # Ensure the target port exists before connecting
                if any(p.name == input_to_connect for p in self.manager.client.get_ports(is_output=True, is_audio=True)):
                    self.manager.make_connection(input_to_connect, "jack_delay:in")
                else:
                    print(f"Warning: Target input port '{input_to_connect}' not found.")
                
                self.manager.latency_results_text.append("\nTry different ports if you're seeing this message after clicking 'Start measurement' button")
                # Refresh the audio tab view to show the new connections
                if self.manager.port_type == 'audio':
                    self.manager.refresh_ports()
                
            except Exception as e:
                print(f"Error during latency auto-connection: {e}")
                self.manager.latency_results_text.append(f"\nError auto-connecting: {e}")
