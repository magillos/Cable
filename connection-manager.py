import sys
import argparse
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.append(script_dir)
    from cables.connection_manager import JackConnectionManager
    from cables.config.preset_manager import PresetManager
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Cables - JACK/PipeWire connection manager')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode to apply startup preset')
    parser.add_argument('--stop-daemon', action='store_true', help='Stop the aj-snapshot daemon')
    args = parser.parse_args()

    if args.stop_daemon:
        print("Stopping aj-snapshot daemon...")
        preset_manager = PresetManager()
        preset_manager.stop_daemon_mode()
        sys.exit(0)

    app = QApplication(sys.argv)
    QGuiApplication.setDesktopFileName("com.github.magillos.cable")

    window = None
    if args.headless:
        print("Connection Manager starting in headless mode...")
        headless_manager = JackConnectionManager()
        startup_preset = headless_manager.preset_handler.startup_preset_name
        if startup_preset and startup_preset != 'None':
            print(f"Headless mode: Attempting to load startup preset '{startup_preset}'...")
            success = headless_manager.preset_handler._load_selected_preset(startup_preset, is_startup=True)
            if success:
                print(f"Startup preset '{startup_preset}' loaded successfully.")
            else:
                print(f"Failed to load startup preset '{startup_preset}'.")
        else:
            print("Headless mode: No startup preset configured.")
            headless_manager.config_manager.set_str('active_preset', None)
            print("Headless: Cleared active_preset in config (no startup preset).")
        QTimer.singleShot(1000, QApplication.quit)
    else:
        window = JackConnectionManager()
        window.start_startup_refresh()
        window.show()

    exit_code = app.exec()
    if args.headless:
        print("Headless preset load finished.")
    return exit_code

if __name__ == '__main__':
    sys.exit(main())
