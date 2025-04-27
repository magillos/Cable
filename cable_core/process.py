import os
import sys
from PyQt6.QtCore import QProcess, QTimer

class ProcessManager:
    def __init__(self, app):
        self.app = app
        self.connection_manager_process = None

    def launch_connection_manager(self, headless=False): # Add headless parameter
        """Launch connection-manager.py as an independent process."""
        try:
            # Define possible paths
            possible_paths = [
                os.path.join(sys._MEIPASS, 'connection-manager.py') if getattr(sys, 'frozen', False) else None,  # PyInstaller bundle path
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'connection-manager.py'), # Relative path from cable_core
                '/usr/share/cable/connection-manager.py'  # System installation path
            ]

            # Find first existing path
            module_path = next((path for path in possible_paths if path and os.path.exists(path)), None)
            if not module_path:
                # Try one level up from the script's dir as a fallback for development
                script_dir = os.path.dirname(os.path.abspath(sys.argv[0])) # Get dir of main Cable.py
                dev_path = os.path.join(script_dir, 'connection-manager.py')
                if os.path.exists(dev_path):
                    module_path = dev_path
                else:
                    raise FileNotFoundError("Could not find connection-manager.py in any expected locations")


            # Create a QProcess for running connection-manager.py if it's not already running
            if self.connection_manager_process is None:
                self.connection_manager_process = QProcess()

                # Connect signals to handle process state
                self.connection_manager_process.finished.connect(self.on_connection_manager_closed)

                # Prepare arguments
                arguments = [module_path]
                if headless:
                    arguments.append('--headless') # Add headless argument if requested

                # Set up the command
                if self.app.flatpak_env:
                    # In Flatpak, we need to use flatpak-spawn to run the Python interpreter
                    self.connection_manager_process.setProgram('flatpak-spawn')
                    self.connection_manager_process.setArguments(['--host', 'python3'] + arguments) # Pass arguments
                else:
                    # Normal execution
                    self.connection_manager_process.setProgram('python3')
                    self.connection_manager_process.setArguments(arguments) # Pass arguments

                # Start the process
                self.connection_manager_process.start()
                print(f"Started connection manager {'headless ' if headless else ''}using {module_path}") # Update log
            else:
                # Process exists but it might be terminated
                if self.connection_manager_process.state() == QProcess.ProcessState.NotRunning:
                    # Restart the process (re-use existing arguments/program)
                    self.connection_manager_process.start()
                    print("Restarting connection manager process")
                else:
                    print("Connection manager process already running")
        except Exception as e:
            print(f"Error launching connection manager: {e}")
            # Optionally show a message box to the user
            # from PyQt6.QtWidgets import QMessageBox
            # QMessageBox.critical(self.app, "Error", f"Failed to launch connection manager:\n{e}")


    def on_connection_manager_closed(self, exitCode, exitStatus):
        """Handle the connection manager process closing"""
        print(f"Connection manager process exited with code {exitCode}, status {exitStatus}")
        # Reset the process object so we can create a new one next time
        self.connection_manager_process = None

    def _ensure_connection_manager_visible(self):
        """Launches connection manager if not running, otherwise terminates and relaunches to bring to front."""
        if self.connection_manager_process is None or (
            hasattr(self.connection_manager_process, 'state') and
            self.connection_manager_process.state() == QProcess.ProcessState.NotRunning
        ):
            # If Cables app is not running, launch it
            self.launch_connection_manager()
        else:
            # As a workaround, kill and restart it to bring to front
            print("Connection manager process already running, bringing to front")
            self.connection_manager_process.terminate()
            # Wait a brief moment for termination before relaunching
            QTimer.singleShot(500, self.launch_connection_manager)

    def open_cables(self):
        """Open the Cables window (used by main app button and tray)"""
        self._ensure_connection_manager_visible()