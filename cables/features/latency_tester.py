"""
LatencyTester - Runs latency tests using jack_delay

This class manages latency testing operations using the jack_delay tool.
It uses the LatencyTesterInterface to access the capabilities it needs from
the main application, enabling better testability and reduced coupling.
"""

import json
import re
import shutil
import subprocess
from PyQt6.QtCore import QTimer, QProcess
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QMessageBox, QSizePolicy

import logging
logger = logging.getLogger(__name__)

from cables.jack_service import get_jack_service
from typing import TYPE_CHECKING, Any, List, Optional, Tuple, Dict
if TYPE_CHECKING:
    from cables.interfaces import LatencyTesterInterface


class LatencyTester:
    """
    Runs latency tests using jack_delay.
    
    This class provides functionality to measure the round-trip latency
    of an audio interface using jack_delay or jack_iodelay.
    
    The class uses the LatencyTesterInterface protocol to access capabilities
    from the main application. The manager parameter must implement:
    - LatencyUIProvider: for latency UI widgets
    - ConnectionOperations: for make_connection
    - UIRefreshProvider: for refresh_ports
    """
    
    def __init__(self, manager: 'LatencyTesterInterface') -> None:
        """
        Initialize the LatencyTester.

        Args:
            manager: Reference to an object implementing LatencyTesterInterface.
                     Typically the JackConnectionManager instance.
        """
        self.manager = manager
        self.latency_process: Optional[QProcess] = None
        self.latency_values: List[Tuple[float, float]] = []
        self.latency_timer = QTimer()
        self.latency_waiting_for_connection: bool = False  # Flag to wait for connection
        # Store selected physical port aliases for latency test
        self.latency_selected_input_alias: Optional[str] = None
        self.latency_selected_output_alias: Optional[str] = None
        # Store the last measured average frames for the "Apply measured offset" button
        self.last_measured_frames: Optional[float] = None
        # Number of initial samples to discard (jack_delay probes every ~0.5s,
        # so 10 samples ≈ 5s of startup transients)
        self.SAMPLES_TO_DISCARD: int = 10
        # Default measurement duration in seconds (user-facing; actual timer
        # is extended by ~5s internally to account for startup discard)
        self.measurement_duration_seconds: int = 10
        
        # Connect timer timeout signal internally
        self.latency_timer.timeout.connect(self.stop_latency_test)
    
    def run_latency_test(self) -> None:
        """Starts the jack_delay process and timer."""
        if self.latency_process is not None and self.latency_process.state() != QProcess.ProcessState.NotRunning:
            self.manager.latency_results_text.append("Test already in progress.")
            return
        
        # Refresh combo boxes with latest ports
        self._populate_latency_combos()
        
        self.manager.latency_run_button.setEnabled(False)
        self.manager.latency_stop_button.setEnabled(True)  # Enable Stop button
        self.manager.latency_apply_offset_button.setEnabled(False)  # Disable apply while testing
        self.manager.latency_results_text.clear()  # Clear previous results/messages
        self.last_measured_frames = None  # Clear previous measurement
        
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
        
        # Determine command: use bundled jack_delay in Flatpak, or search PATH otherwise.
        # NOTE: In Flatpak, /app/bin is on PATH inside the sandbox, so the bundled
        # jack_delay is found directly — no flatpak-spawn --host needed.
        arguments = []
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
        
        self.latency_process.setProgram(program)  # Use the found program path
        self.latency_process.setArguments(arguments)
        self.latency_process.start()  # Start the process
        # Connection attempt is now triggered by _on_port_registered when jack_delay ports appear.
    
    def handle_latency_output(self) -> None:
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
                    # Start the timer now, using the configured duration + 5s to allow
                    # for discarding startup transient samples (~5s at 0.5s intervals)
                    self.latency_timer.setSingleShot(True)
                    self.latency_timer.start((self.measurement_duration_seconds + 5) * 1000)  # Convert to milliseconds
            
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
    
    def set_measurement_duration(self, seconds: int) -> None:
        """
        Set the measurement duration in seconds.
        
        Args:
            seconds: Duration in seconds (must be positive)
        """
        if seconds > 0:
            self.measurement_duration_seconds = seconds
            logger.debug(f"Measurement duration set to {seconds} seconds")
    
    def stop_latency_test(self) -> None:
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
    
    def handle_latency_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        """Handles the jack_delay process finishing."""
        # Clear previous text before showing final result
        self.manager.latency_results_text.clear()
        
        if self.manager.latency_raw_output_checkbox.isChecked():
            # If raw output was shown, just indicate stop
            self.manager.latency_results_text.setText("Measurement stopped.")
        elif self.latency_values:
            # ── Compute median with startup-sample discarding ────────
            # 1. Sort by frame values
            sorted_values = sorted(self.latency_values, key=lambda v: v[0])
            
            # 2. Discard first N startup samples (avoid buffer-skew transients)
            #    but only if we have enough samples to spare.
            if len(sorted_values) > self.SAMPLES_TO_DISCARD:
                trimmed = sorted_values[self.SAMPLES_TO_DISCARD:]
                logger.debug(f"Discarded {self.SAMPLES_TO_DISCARD} startup samples, "
                             f"keeping {len(trimmed)} for median")
            else:
                # Not enough samples to discard — use all available
                trimmed = sorted_values
                logger.debug(f"Only {len(sorted_values)} samples collected, "
                             f"using all (no discard)")
            
            # 3. Compute median of the trimmed set
            n = len(trimmed)
            if n == 0:
                # Edge case: all samples were discarded (impossible given the
                # guard above, but keep for safety)
                median_frames = 0.0
                median_ms = 0.0
            elif n % 2 == 1:
                # Odd count: pick the middle element
                median_frames = trimmed[n // 2][0]
                median_ms = trimmed[n // 2][1]
            else:
                # Even count: average the two middle elements
                mid = n // 2
                median_frames = (trimmed[mid - 1][0] + trimmed[mid][0]) / 2.0
                median_ms = (trimmed[mid - 1][1] + trimmed[mid][1]) / 2.0
            
            # 4. Round to nearest frame for display and storage
            rounded_frames = round(median_frames)
            self.last_measured_frames = float(rounded_frames)
            # Enable the apply button now that we have a measurement
            self.manager.latency_apply_offset_button.setEnabled(True)
            
            # ── Display results ──────────────────────────────────────
            quantum = self._get_current_quantum()
            if quantum is not None and quantum > 0:
                offset_raw = (rounded_frames - quantum * 2) / 2.0
                offset = max(0, int(round(offset_raw)))
                sample_rate = self._get_current_sample_rate()
                if sample_rate is not None and sample_rate > 0:
                    ns_value = round(offset * 1_000_000_000 / sample_rate)
                    self.manager.latency_results_text.setText(
                        f"Round-trip latency (median): {rounded_frames} samples / {median_ms:.3f} ms\n"
                        f"Suggested latency offset: {offset} samples / {ns_value} ns (for each, input and output node)\n"
                        f"Apply suggested offset with the button below \u2193"
                    )
                else:
                    self.manager.latency_results_text.setText(
                        f"Round-trip latency (median): {rounded_frames} samples / {median_ms:.3f} ms\n"
                        f"Suggested latency offset: {offset} samples"
                    )
            else:
                self.manager.latency_results_text.setText(
                    f"Round-trip latency (median): {rounded_frames} samples / {median_ms:.3f} ms"
                )
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
    
    def handle_latency_error(self, error: QProcess.ProcessError) -> None:
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
        self.manager.latency_apply_offset_button.setEnabled(False)  # Disable apply on error
        self.manager.latency_stop_button.setEnabled(False)  # Disable Stop button on error
    
    def _populate_latency_combos(self) -> None:
        """Populates the latency test combo boxes using JackService."""
        capture_ports = []  # Physical capture devices (JACK outputs)
        playback_ports = []  # Physical playback devices (JACK inputs)
        try:
            jack_service = get_jack_service()
            # Get physical capture ports (System Output -> JACK Input)
            jack_capture_ports = jack_service.get_ports(is_physical=True, is_audio=True, is_output=True)
            capture_ports = sorted([port.name for port in jack_capture_ports])
            
            # Get physical playback ports (System Input <- JACK Output)
            jack_playback_ports = jack_service.get_ports(is_physical=True, is_audio=True, is_input=True)
            playback_ports = sorted([port.name for port in jack_playback_ports])
            
        except Exception as e:
            logger.error(f"Error getting physical JACK ports: {e}")
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
    
    def _on_latency_input_selected(self, index: int) -> None:
        """Stores the selected physical input port alias."""
        self.latency_selected_input_alias = self.manager.latency_input_combo.itemData(index)
        # Attempt connection if output is also selected and test is running
        self._attempt_latency_auto_connection()
    
    def _on_latency_output_selected(self, index: int) -> None:
        """Stores the selected physical output port alias."""
        self.latency_selected_output_alias = self.manager.latency_output_combo.itemData(index)
        # Attempt connection if input is also selected and test is running
        self._attempt_latency_auto_connection()
    
    def _attempt_latency_auto_connection(self) -> None:
        """Connects selected physical ports to jack_delay if ports are selected."""
        # Only connect if both an input and output alias have been selected from the dropdowns.
        if (self.latency_selected_input_alias and
            self.latency_selected_output_alias):
            
            # Pipewire 'in' direction (our output_ports list) connects to jack_delay:out
            # Pipewire 'out' direction (our input_ports list) connects to jack_delay:in
            output_to_connect = self.latency_selected_output_alias  # This is the physical playback port alias
            input_to_connect = self.latency_selected_input_alias    # This is the physical capture port alias
            
            logger.debug(f"Attempting auto-connection: jack_delay:out -> {output_to_connect}")
            logger.debug(f"Attempting auto-connection: {input_to_connect} -> jack_delay:in")
            
            try:
                jack_service = get_jack_service()
                # Connect jack_delay output to the selected physical playback port
                # Ensure the target port exists before connecting
                if any(p.name == output_to_connect for p in jack_service.get_ports(is_input=True, is_audio=True)):
                    self.manager.jack_handler.make_connection("jack_delay:out", output_to_connect)
                else:
                    logger.warning(f"Warning: Target output port '{output_to_connect}' not found.")
                
                # Connect the selected physical capture port to jack_delay input
                # Ensure the target port exists before connecting
                if any(p.name == input_to_connect for p in jack_service.get_ports(is_output=True, is_audio=True)):
                    self.manager.jack_handler.make_connection(input_to_connect, "jack_delay:in")
                else:
                    logger.warning(f"Warning: Target input port '{input_to_connect}' not found.")
                
                self.manager.latency_results_text.append("\nWait a few seconds, adjust I/O volume, or try different ports if you're seeing this message after clicking 'Start measurement' button")
                # Refresh the audio tab view to show the new connections
                if self.manager.port_type == 'audio':
                    self.manager.refresh_ports()
                
            except Exception as e:
                logger.error(f"Error during latency auto-connection: {e}")
                self.manager.latency_results_text.append(f"\nError auto-connecting: {e}")
    
    # ── "Reset All Latency" feature ─────────────────────────────────
    # Reuses the same approach as PipewireManager.reset_all_latency()
    # but uses the LatencyTester's own PipeWire command runner.

    def reset_all_latency(self) -> None:
        """
        Set Latency to '0' for all nodes.
        
        Mirrors the exact behavior of the "Reset All Latency" button in Cable:
        uses 'pw-cli ls Node' to discover only ALSA audio nodes (same filtering
        as PipewireManager._load_pw_cli_items), then runs
        'pw-cli s <node_id> ProcessLatency { rate = 0 }' for each one.
        """
        # Discover ALSA audio nodes using pw-cli ls Node (same as
        # PipewireManager.load_nodes() → _load_pw_cli_items('Node'))
        output = self._run_pw_command(['pw-cli', 'ls', 'Node'])
        if not output:
            self.manager.latency_results_text.setText(
                "Error: Could not query PipeWire node list (pw-cli ls Node failed)."
            )
            return

        node_ids = []
        current_id = None
        current_name = None
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('id '):
                try:
                    current_id = line.split(',')[0].split()[-1].strip()
                except IndexError:
                    current_id = None
                    continue
            elif 'node.name' in line:
                try:
                    current_name = line.split('=', 1)[1].strip().strip('"')
                except IndexError:
                    current_name = None

                # Only include ALSA nodes (same filter as PipewireManager)
                if current_id and current_name and current_name.startswith("alsa_"):
                    node_ids.append(current_id)

                current_id = None
                current_name = None

        if not node_ids:
            self.manager.latency_results_text.setText(
                "No ALSA PipeWire nodes found to reset."
            )
            return

        self.manager.latency_results_text.setText(
            f"Resetting latency for {len(node_ids)} ALSA node(s)...\n"
        )

        success_count = 0
        fail_count = 0
        for node_id in node_ids:
            ok = self._run_pw_command(
                ['pw-cli', 's', node_id, 'ProcessLatency', '{ rate = 0 }'],
                check_output=False
            )
            if ok:
                success_count += 1
            else:
                fail_count += 1

        self.manager.latency_results_text.append(
            f"Done. Reset {success_count} node(s) successfully"
            + (f", {fail_count} failed." if fail_count > 0 else ".")
        )

    # ── "Apply measured offset" feature ──────────────────────────────

    def apply_measured_offset(self) -> None:
        """
        Apply the measured round-trip latency offset to the selected audio nodes.
        
        Formula: offset = (measured_frames - quantum) / 2
        Applied to both the input (capture) and output (playback) PipeWire nodes.
        """
        if self.last_measured_frames is None:
            self.manager.latency_results_text.setText(
                "No measurement available. Run a latency test first."
            )
            return

        if not self.latency_selected_input_alias or not self.latency_selected_output_alias:
            self.manager.latency_results_text.setText(
                "Please select both Input (Capture) and Output (Playback) ports first."
            )
            return

        # Step 1: Read current quantum
        quantum = self._get_current_quantum()
        if quantum is None or quantum == 0:
            self.manager.latency_results_text.setText(
                "Error: Could not determine current PipeWire quantum."
            )
            return

        # Step 2: Calculate offset
        measured = self.last_measured_frames
        offset_raw = (measured - quantum * 2) / 2.0
        offset = max(0, int(round(offset_raw)))  # Clamp to non-negative, round to integer

        # Step 3: Map selected JACK ports to PipeWire node IDs via pw-dump
        pw_dump = self._get_pw_dump()
        if not pw_dump:
            self.manager.latency_results_text.append(
                "Error: Could not query PipeWire node list (pw-dump failed)."
            )
            return

        # Find PW nodes for both selected ports
        input_alias = self.latency_selected_input_alias
        output_alias = self.latency_selected_output_alias

        logger.info(f"Mapping JACK ports to PW nodes: input={input_alias}, output={output_alias}")

        input_node_ids = self._find_pw_nodes_for_jack_port(input_alias, pw_dump)
        output_node_ids = self._find_pw_nodes_for_jack_port(output_alias, pw_dump)

        all_node_ids = set(input_node_ids + output_node_ids)
        if not all_node_ids:
            self.manager.latency_results_text.append(
                "Error: Could not match selected ports to any PipeWire node. "
                "Try refreshing the port list."
            )
            return

        # Step 4: Apply offset to each found node
        success_count = 0
        fail_count = 0
        for node_id in sorted(all_node_ids):
            ok = self._apply_pw_latency_offset(node_id, offset)
            if ok:
                success_count += 1
            else:
                fail_count += 1

        # Step 5: Report results
        if success_count > 0:
            plural = "" if success_count == 1 else "s"
            self.manager.latency_results_text.setHtml(
                f"Applied offset of <b>{offset}</b> samples to {success_count} PipeWire node{plural}."
            )
        if fail_count > 0:
            plural = "" if fail_count == 1 else "s"
            fail_msg = f"✗ Failed to apply offset to {fail_count} node{plural}."
            if success_count > 0:
                self.manager.latency_results_text.append(f"\n{fail_msg}")
            else:
                self.manager.latency_results_text.setHtml(fail_msg)

    def _get_current_quantum(self) -> Optional[int]:
        """
        Get the current PipeWire quantum.
        
        Priority:
        1. If integrated mode (cable_widget available), read from QuantumManager
           (this is the most reliable — it's already parsed from pw-metadata)
        2. Otherwise, probe pw-metadata directly (standalone Cables mode)
        
        Returns:
            The quantum value as int, or None if cannot be determined.
        """
        # Priority 1: Reuse quantum from Cable's QuantumManager if available
        cable_widget = getattr(self.manager, 'cable_widget', None)
        if cable_widget is not None:
            quantum_manager = getattr(cable_widget, 'quantum_manager', None)
            if quantum_manager is not None:
                quantum = quantum_manager.get_quantum_value()
                if quantum is not None and quantum > 0:
                    logger.debug(f"Got quantum from QuantumManager: {quantum}")
                    return quantum

        # Priority 2: Probe pw-metadata directly
        # pw-metadata output format:
        #   update: id:0 key:'clock.force-quantum' value:'1024' type:''
        #   update: id:0 key:'clock.quantum' value:'1024' type:''
        try:
            # Try force-quantum first (non-zero means forced)
            output = self._run_pw_command(
                ['pw-metadata', '-n', 'settings']
            )
            if output:
                # Parse force-quantum
                match = re.search(r"clock\.force-quantum'.*?value:'(\d+)'", output)
                if match:
                    val = int(match.group(1))
                    if val > 0:
                        logger.debug(f"Got quantum from force-quantum: {val}")
                        return val

                # Fall back to effective quantum
                match = re.search(r"clock\.quantum'.*?value:'(\d+)'", output)
                if match:
                    val = int(match.group(1))
                    if val > 0:
                        logger.debug(f"Got quantum from clock.quantum: {val}")
                        return val

            logger.warning("Could not parse quantum from pw-metadata output")
            return None
        except Exception as e:
            logger.error(f"Error getting current quantum: {e}")
            return None

    def _get_current_sample_rate(self) -> Optional[int]:
        """
        Get the current PipeWire sample rate.
        
        Priority:
        1. If integrated mode (cable_widget available), read from QuantumManager
           (this is the most reliable — it's already parsed from pw-metadata)
        2. Otherwise, probe pw-metadata directly (standalone Cables mode)
        
        Returns:
            The sample rate as int (e.g. 48000), or None if cannot be determined.
        """
        # Priority 1: Reuse sample rate from Cable's QuantumManager if available
        cable_widget = getattr(self.manager, 'cable_widget', None)
        if cable_widget is not None:
            quantum_manager = getattr(cable_widget, 'quantum_manager', None)
            if quantum_manager is not None:
                rate = quantum_manager.get_sample_rate_value()
                if rate > 0:
                    logger.debug(f"Got sample rate from QuantumManager: {rate}")
                    return rate

        # Priority 2: Probe pw-metadata directly
        # pw-metadata output format:
        #   update: id:0 key:'clock.rate' value:'48000' type:''
        try:
            output = self._run_pw_command(
                ['pw-metadata', '-n', 'settings']
            )
            if output:
                match = re.search(r"clock\.rate'.*?value:'(\d+)'", output)
                if match:
                    val = int(match.group(1))
                    if val > 0:
                        logger.debug(f"Got sample rate from pw-metadata: {val}")
                        return val

            logger.warning("Could not parse sample rate from pw-metadata output")
            return None
        except Exception as e:
            logger.error(f"Error getting current sample rate: {e}")
            return None

    def _get_pw_dump(self) -> Optional[List[Dict[str, Any]]]:
        """
        Run pw-dump and return parsed JSON.
        
        Returns:
            List of pw-dump objects, or None on failure.
        """
        try:
            output = self._run_pw_command(['pw-dump'])
            if not output:
                return None
            return json.loads(output)
        except Exception as e:
            logger.error(f"Error running pw-dump: {e}")
            return None

    def _find_pw_nodes_for_jack_port(
        self, jack_port_name: str, pw_dump: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Given a JACK port name like 'Ryzen HD Audio Controller Speaker:playback_FL',
        find the PipeWire node ID that owns the corresponding physical port.
        
        Matching strategy:
        1. Extract the JACK client name (before ':') from the port name.
        2. Find the PipeWire Node object whose 'node.description' matches
           the JACK client name exactly.
        3. Return that node's ID.
        
        This ensures only the specific measured device node is targeted,
        not virtual sinks/sources that happen to share port names like
        'playback_FL'.
        
        Args:
            jack_port_name: The JACK port name
                (e.g. 'Ryzen HD Audio Controller Speaker:playback_FL')
            pw_dump: Parsed pw-dump JSON data
            
        Returns:
            List of PW node ID strings (may be empty, typically one element).
        """
        # Extract JACK client name (the part before ':')
        if ':' not in jack_port_name:
            logger.warning(f"JACK port name has no ':' separator: {jack_port_name}")
            return []
        
        jack_client_name = jack_port_name.split(':', 1)[0]
        logger.debug(f"Looking for PW node matching JACK client: '{jack_client_name}'")
        
        node_ids: set = set()
        
        # Search for PipeWire Node objects whose description matches the JACK client name.
        # PipeWire exposes JACK port names as '<node.description>:<port.name>',
        # so the JACK client name corresponds to node.description.
        for obj in pw_dump:
            if not isinstance(obj, dict):
                continue
            obj_type = obj.get('type', '')
            if 'PipeWire:Interface:Node' not in obj_type:
                continue
            
            info = obj.get('info', {})
            props = info.get('props', {}) if isinstance(info, dict) else {}
            
            node_desc = props.get('node.description', '')
            if node_desc == jack_client_name:
                node_id = obj.get('id')
                if node_id is not None:
                    node_ids.add(str(node_id))
                    logger.info(
                        f"Matched JACK client '{jack_client_name}' -> "
                        f"PW node {node_id} (name={props.get('node.name', '')})"
                    )
        
        if not node_ids:
            logger.warning(
                f"No PipeWire node found matching JACK client '{jack_client_name}'"
            )

        return list(node_ids)

    def _apply_pw_latency_offset(self, node_id: str, offset: int) -> bool:
        """
        Apply ProcessLatency '{ rate = <offset> }' to a PipeWire node.
        
        Args:
            node_id: PipeWire node ID string
            offset: Latency offset value (in frames)
            
        Returns:
            True if the command succeeded, False otherwise.
        """
        try:
            command = [
                'pw-cli', 's', node_id, 'ProcessLatency',
                f'{{ rate = {offset} }}'
            ]
            logger.info(f"Applying latency offset {offset} to PW node {node_id}")
            ok = self._run_pw_command(command, check_output=False)
            if ok:
                logger.info(f"Successfully applied offset {offset} to node {node_id}")
                return True
            else:
                logger.error(f"Failed to apply offset {offset} to node {node_id}")
                return False
        except Exception as e:
            logger.error(f"Error applying offset to node {node_id}: {e}")
            return False

    def _run_pw_command(
        self, command_args: List[str], check_output: bool = True
    ) -> Any:
        """
        Run a PipeWire-related command, respecting the flatpak_env flag.
        
        This mirrors the pattern used in PipewireManager.run_command().
        
        Args:
            command_args: Command and arguments as a list
            check_output: If True, return stdout string; if False, return bool success
            
        Returns:
            stdout string, bool, or None depending on mode and success.
        """
        try:
            if self.manager.flatpak_env:
                command_args = ['flatpak-spawn', '--host'] + command_args

            if check_output:
                result = subprocess.check_output(
                    command_args,
                    universal_newlines=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()
            else:
                subprocess.run(
                    command_args,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
        except subprocess.CalledProcessError as e:
            logger.debug(f"Command failed: {' '.join(command_args)}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error running command: {' '.join(command_args)}: {e}")
            return None