import requests
import json
import webbrowser
from packaging import version
from PyQt6.QtWidgets import QMessageBox, QApplication # Added QApplication for potential parent reference if needed
from cables.utils.helpers import show_timed_messagebox # Import the helper function
# Removed relative import: from ..Cable import APP_VERSION
from cable_core.app_config import APP_VERSION # Import from new location

class UpdateManager:
    def __init__(self, app, app_version): # Add app_version parameter
        self.app = app
        self.app_version = app_version # Store app_version
        self.latest_version = None
        self.update_available = False

    def _initial_update_check(self):
        """Performs the update check only if the setting is enabled."""
        if self.app.check_updates_at_start: # Changed self. to self.app.
            print("Performing initial update check as configured...")
            self.check_for_updates() # Internal call, remains self.
        else:
            print("Skipping initial update check as configured.")

    def check_for_updates(self, manual_check=False): # Add manual_check parameter
        """Checks GitHub for newer versions and updates the version label color."""
        print(f"Checking for updates... (Manual Check: {manual_check})")
        try:
            # Use a timeout to prevent hanging indefinitely
            response = requests.get("https://api.github.com/repos/magillos/Cable/tags", timeout=10)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            tags = response.json()

            if not tags:
                print("No tags found on GitHub.")
                # Indicate check completed, no update found
                self.update_available = False
                self.latest_version = None
                if hasattr(self.app, 'update_version_display'):
                    self.app.update_version_display()
                if manual_check:
                    show_timed_messagebox(self.app, QMessageBox.Icon.Information, "Update Check", "No new version found (no tags).", duration=1000)
                return

            # Extract version numbers from tag names (assuming tags are like 'vX.Y.Z' or 'X.Y.Z')
            latest_version = None
            for tag in tags:
                tag_name = tag.get('name', '').lstrip('v') # Remove leading 'v' if present
                try:
                    current_tag_version = version.parse(tag_name)
                    if latest_version is None or current_tag_version > latest_version:
                        latest_version = current_tag_version
                except version.InvalidVersion:
                    print(f"Skipping invalid tag name: {tag.get('name')}")
                    continue # Skip tags that don't parse as versions

            if latest_version:
                current_app_version = version.parse(self.app_version) # Use self.app_version
                print(f"Current version: {current_app_version}, Latest GitHub version: {latest_version}")
                if latest_version > current_app_version:
                    print("Newer version found!")
                    self.update_available = True
                    self.latest_version = latest_version
                else:
                    print("Application is up to date.")
                    self.update_available = False
                    self.latest_version = latest_version
                    if manual_check:
                        show_timed_messagebox(self.app, QMessageBox.Icon.Information, "Update Check", "Application is up to date.", duration=1000)
            else:
                print("Could not determine the latest version from tags.")
                self.update_available = False
                self.latest_version = None
                if manual_check:
                    show_timed_messagebox(self.app, QMessageBox.Icon.Warning, "Update Check", "Could not determine the latest version.", duration=1000)

            # Update the UI display if the method exists
            if hasattr(self.app, 'update_version_display'):
                self.app.update_version_display()


        except requests.exceptions.RequestException as e:
            # Handle network errors, timeouts, etc.
            print(f"Error checking for updates (network issue): {e}")

        except json.JSONDecodeError as e:
            print(f"Error checking for updates (invalid JSON response): {e}")
            # QMessageBox.warning(self.app, "Update Check Failed", f"Received an invalid response from GitHub:\n{e}") # Changed self to self.app
        except Exception as e:
            # Catch any other unexpected errors
            print(f"An unexpected error occurred during update check: {e}")
            # QMessageBox.critical(self.app, "Update Check Error", f"An unexpected error occurred:\n{e}") # Changed self to self.app


    def open_download_page(self):
        """Opens the GitHub releases page in the default web browser."""
        url = "https://github.com/magillos/Cable/releases"
        print(f"Opening download page: {url}")
        webbrowser.open(url)