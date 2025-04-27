#!/usr/bin/env python3
"""
Cables - A JACK/PipeWire connection manager (Entry Point)
"""

import sys
import argparse
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication

# Import the main application class from the cables module
try:
    # Get the directory containing the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Add this directory to the end of sys.path if not already present
    if script_dir not in sys.path:
        sys.path.append(script_dir)
    from cables.connection_manager import JackConnectionManager
except ImportError as e:
    print(f"Error importing JackConnectionManager: {e}")
    print("Please ensure the 'cables' directory is in the same directory as this script or in the Python path.")
    sys.exit(1)

def main():
    """Main entry point for the application."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='JACK Connection Manager (Cables)')
    parser.add_argument('--headless', action='store_true',
                        help='Load startup preset and exit without showing GUI.')
    args = parser.parse_args()

    # Create QApplication
    app = QApplication(sys.argv)
    # Set the desktop filename for correct icon display
    QGuiApplication.setDesktopFileName("com.github.magillos.cable")

    window = None
    headless_manager = None

    try:
        # Handle headless mode
        if args.headless:
            print("Connection Manager starting in headless mode...")
            # Create a manager instance to load the preset
            headless_manager = JackConnectionManager() # Instantiate from cables module

            # Explicitly load startup preset if defined
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
                # Ensure active preset is cleared if none is configured for startup
                headless_manager.config_manager.set_str('active_preset', None)
                print("Headless: Cleared active_preset in config (no startup preset).")

            # Exit after a short delay to allow JACK connections to establish
            QTimer.singleShot(1000, QApplication.quit) # Exit after 1 second

        else:
            # Normal GUI mode
            window = JackConnectionManager() # Instantiate from cables module
            window.start_startup_refresh() # Start the refresh sequence for GUI mode
            window.show()

        # Run the application event loop
        exit_code = app.exec()
        if args.headless:
            print("Headless preset load finished.")
        return exit_code

    except KeyboardInterrupt:
        print("Received keyboard interrupt")
        if window:
            window.close() # Trigger closeEvent for cleanup
        elif headless_manager:
             # Ensure client is closed in headless mode on interrupt
             if hasattr(headless_manager, 'client'):
                 try:
                     headless_manager.client.deactivate()
                     headless_manager.client.close()
                     print("JACK client closed (headless interrupt).")
                 except Exception as e:
                     print(f"Error closing JACK client (headless interrupt): {e}")
        app.quit()
        return 1
    finally:
        # Ensure cleanup happens if window/manager exists and wasn't closed by closeEvent/interrupt
        manager_to_clean = window if window else headless_manager
        if manager_to_clean and hasattr(manager_to_clean, 'client'):
             try:
                 print("Performing final JACK client cleanup...")
                 # Attempt to deactivate and close the client regardless of its reported state
                 manager_to_clean.client.deactivate()
                 manager_to_clean.client.close()
                 print("JACK client closed (finally block).")
             except Exception as e:
                 print(f"Error during final JACK client cleanup: {e}")

if __name__ == '__main__':
    sys.exit(main())
