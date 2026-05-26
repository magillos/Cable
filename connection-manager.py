"""
Cables — JACK/PipeWire connection manager.

Entry point that launches JackConnectionManager with tabs for Audio, MIDI,
MIDI Matrix, Graph, Alsa Mixer, pw-top, and Latency Test.
"""
import sys
import argparse
import os
import signal
import logging
from typing import Optional

# Suppress D-Bus portal registration warnings on GNOME/Ubuntu
# This prevents "Could not register app ID: Connection already associated" errors
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.services=false")

# Add the script directory to path first so we can import cable_core
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Pre-parse arguments to check for verbose flag before setting up logging
# This allows verbose output during import phase
_pre_parser = argparse.ArgumentParser(add_help=False)
_pre_parser.add_argument('-v', '--verbose', action='count', default=0)
_pre_args, _remaining = _pre_parser.parse_known_args()

from cable_core.logging_config import setup_logging
setup_logging(verbose_override=_pre_args.verbose)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from cable_core.app_config import load_app_icon, load_and_apply_theme


try:
    from cables.connection_manager import JackConnectionManager
    from cables.config.preset_manager import PresetManager
except ImportError as e:
    logging.getLogger(__name__).error(f"Error importing modules: {e}")
    sys.exit(1)

logger = logging.getLogger(__name__)

def main() -> int:
    parser = argparse.ArgumentParser(description='Cables - JACK/PipeWire connection manager')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode to apply startup preset')
    parser.add_argument('--stop-daemon', action='store_true', help='Stop the aj-snapshot daemon')
    parser.add_argument('--minimized', action='store_true', help='Start application minimized to tray')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Enable verbose output (-v) or extra verbose with JACK errors (-vv)')
    parser.add_argument('--integrated', action='store_true', default=False,
                        help='Force integrated mode: show Cable tab regardless of config (set by Cable.py -i)')
    parser.add_argument('--non-integrated', action='store_true', default=False,
                        help='Force non-integrated mode: hide Cable tab regardless of config (set by Cable.py -n)')
    args = parser.parse_args()

    # None = read from config; True = force integrated (-i); False = force non-integrated (-n)
    if args.integrated:
        integrated_override: Optional[bool] = True
    elif args.non_integrated:
        integrated_override = False
    else:
        integrated_override = None

    if args.stop_daemon:
        logger.info("Stopping aj-snapshot daemon...")
        preset_manager = PresetManager()
        preset_manager.stop_daemon_mode()
        sys.exit(0)

    logger.info("Launcher: Creating QApplication...")
    app = QApplication(sys.argv)
    logger.info("Launcher: QApplication created.")
    QGuiApplication.setDesktopFileName("com.github.magillos.cable")

    # Apply forced colour theme from config before building any widgets
    logger.info("Launcher: Applying theme from config...")
    load_and_apply_theme(os.path.expanduser("~/.config/cable/config.ini"))
    logger.info("Launcher: Theme load completed.")
    
    app_icon = load_app_icon()
    if app_icon:
        app.setWindowIcon(app_icon)

    window = None
    if args.headless:
        logger.info("Connection Manager starting in headless mode...")
        headless_manager = JackConnectionManager(load_startup_preset=True, integrated_override=integrated_override)
        startup_preset = headless_manager.preset_handler.startup_preset_name
        if startup_preset and startup_preset != 'None':
            logger.info(f"Headless mode: Startup preset '{startup_preset}' loaded.")
        else:
            logger.info("Headless mode: No startup preset configured.")
        QTimer.singleShot(1000, QApplication.quit)
    elif args.minimized:
        logger.info("Connection Manager starting minimized to tray...")
        window = JackConnectionManager(load_startup_preset=True, integrated_override=integrated_override)
        window.start_startup_refresh()
        # Start minimized - enable tray if Cable tab exists and has tray functionality
        if getattr(window, 'cable_widget', None) is not None:
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
        logger.info("Launcher: Creating JackConnectionManager...")
        window = JackConnectionManager(load_startup_preset=False, integrated_override=integrated_override)
        logger.info("Launcher: JackConnectionManager created. Starting startup refresh...")
        window.start_startup_refresh()
        logger.info("Launcher: Showing window...")
        window.show()
        logger.info("Launcher: Window shown.")

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
        logger.info("Headless preset load finished.")
    return exit_code

if __name__ == '__main__':
    sys.exit(main())
