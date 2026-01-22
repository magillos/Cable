import os
import sys
from PyQt6.QtCore import QProcess, QTimer

class ProcessManager:
    def __init__(self, app):
        self.app = app
        self.connection_manager_process = None

    def launch_connection_manager(self, headless=False, stop_daemon=False):
        """Launch connection-manager.py as an independent process."""
        try:
            possible_paths = [
                os.path.join(sys._MEIPASS, 'connection-manager.py') if getattr(sys, 'frozen', False) else None,
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'connection-manager.py'),
                '/usr/share/cable/connection-manager.py'
            ]

            module_path = next((path for path in possible_paths if path and os.path.exists(path)), None)
            if not module_path:
                script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                dev_path = os.path.join(script_dir, 'connection-manager.py')
                if os.path.exists(dev_path):
                    module_path = dev_path
                else:
                    raise FileNotFoundError("Could not find connection-manager.py in any expected locations")

            if self.connection_manager_process is None:
                self.connection_manager_process = QProcess()
                self.connection_manager_process.finished.connect(self.on_connection_manager_closed)

            arguments = [module_path]
            if headless:
                arguments.append('--headless')
            if stop_daemon:
                arguments.append('--stop-daemon')

            self.connection_manager_process.setProgram('python3')
            self.connection_manager_process.setArguments(arguments)

            self.connection_manager_process.start()
            print(f"Started connection manager with args: {arguments}")
        except Exception as e:
            print(f"Error launching connection manager: {e}")


    def on_connection_manager_closed(self, exitCode, exitStatus):
        """Handle the connection manager process closing"""
        print(f"Connection manager process exited with code {exitCode}, status {exitStatus}")
        # Reset the process object so we can create a new one next time
        self.connection_manager_process = None

    def terminate_connection_manager(self):
        """Terminates the connection manager process if it is running."""
        if self.connection_manager_process and self.connection_manager_process.state() == QProcess.ProcessState.Running:
            print("Terminating connection manager process...")
            self.connection_manager_process.terminate()
            self.connection_manager_process.waitForFinished(5000) # Wait up to 5 seconds
            if self.connection_manager_process.state() == QProcess.ProcessState.Running:
                print("Connection manager process did not terminate gracefully, killing.")
                self.connection_manager_process.kill()
            else:
                print("Connection manager process terminated.")
        else:
            print("Connection manager process is not running.")

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
