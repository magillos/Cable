import sys
import argparse
import os
import signal

# Initialize verbose mode before any other imports that might print
# Add the script directory to path first so we can import cable_core
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
from cable_core.verbose import init_verbose_mode
init_verbose_mode()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication, QIcon


class JackErrorFilter:
    """Filter to suppress python-jack cffi callback assertion errors."""
    
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
        self._buffer = []
        self._in_traceback = False
        self._is_jack_error = False
    
    def write(self, text):
        lines = text.split("\n")
        
        for i, line in enumerate(lines):
            # Add newline back except for last segment (may be incomplete)
            if i < len(lines) - 1:
                self._process_line(line + "\n")
            elif line:  # Last segment, no newline yet
                self._buffer.append(line)
    
    def _process_line(self, line):
        # Flush any buffered incomplete line first
        if self._buffer:
            line = "".join(self._buffer) + line
            self._buffer = []
        
        # Detect start of traceback
        if line.startswith("Traceback (most recent call last):"):
            self._in_traceback = True
            self._is_jack_error = False
            self._traceback_lines = [line]
            return
        
        if line.startswith("Exception ignored from cffi callback"):
            self._in_traceback = True
            self._is_jack_error = True  # Definitely a jack cffi error
            self._traceback_lines = [line]
            return
        
        if self._in_traceback:
            self._traceback_lines.append(line)
            
            # Check if this is a jack-related error
            if "jack.py" in line or "_wrap_port_ptr" in line or "callback_wrapper" in line:
                self._is_jack_error = True
            
            # End of traceback detection
            if line.startswith("AssertionError") or (line.strip() and not line.startswith(" ") and not line.startswith("File ")):
                self._in_traceback = False
                # Only output if NOT a jack error
                if not self._is_jack_error:
                    for tline in self._traceback_lines:
                        self.original_stderr.write(tline)
                self._traceback_lines = []
                self._is_jack_error = False
            return
        
        # Normal line - output directly
        self.original_stderr.write(line)
    
    def flush(self):
        if self._buffer:
            text = "".join(self._buffer)
            if not self._in_traceback:
                self.original_stderr.write(text)
            self._buffer = []
        self.original_stderr.flush()
    
    def fileno(self):
        return self.original_stderr.fileno()
    
    def isatty(self):
        return self.original_stderr.isatty()


# Install the stderr filter
sys.stderr = JackErrorFilter(sys.stderr)

try:
    from cables.connection_manager import JackConnectionManager
    from cables.config.preset_manager import PresetManager
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Cables - JACK/PipeWire connection manager')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode to apply startup preset')
    parser.add_argument('--stop-daemon', action='store_true', help='Stop the aj-snapshot daemon')
    parser.add_argument('--minimized', action='store_true', help='Start application minimized to tray')
    args = parser.parse_args()

    if args.stop_daemon:
        print("Stopping aj-snapshot daemon...")
        preset_manager = PresetManager()
        preset_manager.stop_daemon_mode()
        sys.exit(0)

    app = QApplication(sys.argv)
    QGuiApplication.setDesktopFileName("com.github.magillos.cable")
    
    # Set window icon explicitly for title bar
    icon_name = "jack-plug.svg"
    icon_theme_name = "jack-plug"
    app_icon = None
    
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
        bundle_icon_path = os.path.join(base_path, icon_name)
        if os.path.exists(bundle_icon_path):
            app_icon = QIcon(bundle_icon_path)
            if app_icon.isNull():
                app_icon = None
    else:
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
        local_icon_path = os.path.join(base_path, icon_name)
        if os.path.exists(local_icon_path):
            app_icon = QIcon(local_icon_path)
            if app_icon.isNull():
                app_icon = None
    
    if app_icon is None:
        theme_icon = QIcon.fromTheme(icon_theme_name)
        if not theme_icon.isNull():
            app_icon = theme_icon
    
    if app_icon:
        app.setWindowIcon(app_icon)

    window = None
    if args.headless:
        print("Connection Manager starting in headless mode...")
        headless_manager = JackConnectionManager(load_startup_preset=True)
        startup_preset = headless_manager.preset_handler.startup_preset_name
        if startup_preset and startup_preset != 'None':
            print(f"Headless mode: Startup preset '{startup_preset}' loaded.")
        else:
            print("Headless mode: No startup preset configured.")
        QTimer.singleShot(1000, QApplication.quit)
    elif args.minimized:
        print("Connection Manager starting minimized to tray...")
        window = JackConnectionManager(load_startup_preset=True)
        window.start_startup_refresh()
        # Start minimized - enable tray if Cable tab exists and has tray functionality
        if hasattr(window, 'cable_widget') and window.cable_widget:
            cable = window.cable_widget
            # Enable tray if not already enabled
            if not cable.tray_enabled:
                cable.tray_toggle_checkbox.setChecked(True)
                cable.tray_manager.toggle_tray_icon(2)  # Qt.CheckState.Checked = 2
            # Hide the window
            window.hide()
        else:
            # No Cable tab, just hide the window (no tray functionality without Cable)
            window.hide()
    else:
        window = JackConnectionManager(load_startup_preset=False)
        window.start_startup_refresh()
        window.show()

    # Set up SIGINT handler for Ctrl+C
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())
    # Timer to allow Python to process signals
    sig_timer = QTimer()
    sig_timer.start(100)
    sig_timer.timeout.connect(lambda: None)

    # Ensure cleanup happens on quit (handles Ctrl+C, app.quit(), etc.)
    if window:
        app.aboutToQuit.connect(window._cleanup_on_quit)

    exit_code = app.exec()
    if args.headless:
        print("Headless preset load finished.")
    return exit_code

if __name__ == '__main__':
    sys.exit(main())
