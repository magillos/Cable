"""
GitHub-based update checking and notification.
"""

import requests
import webbrowser
from typing import Any, List, Optional
from packaging import version
from PyQt6.QtWidgets import QMessageBox, QWidget
from cables.utils.helpers import show_timed_messagebox
from cable_core.app_config import APP_VERSION

import logging
logger = logging.getLogger(__name__)


class UpdateManager:
    def __init__(self, app: QWidget, app_version: str) -> None:
        self.app = app
        self.app_version = app_version
        self.latest_version: Optional[version.Version] = None
        self.update_available: bool = False

    def _initial_update_check(self) -> None:
        """Performs the update check only if the setting is enabled."""
        if self.app.check_updates_at_start:
            logger.info("Performing initial update check as configured...")
            self.check_for_updates()
        else:
            logger.debug("Skipping initial update check as configured.")

    def _fetch_tags(self) -> List[dict]:
        """Fetch tags from GitHub. Runs in a background thread via AsyncRunner."""
        response = requests.get("https://api.github.com/repos/magillos/Cable/tags", timeout=10)
        response.raise_for_status()
        return response.json()

    def _on_tags_fetched(self, tags: List[dict], manual_check: bool) -> None:
        """Process fetched tags on the main thread."""
        if not tags:
            logger.debug("No tags found on GitHub.")
            self.update_available = False
            self.latest_version = None
            if getattr(self.app, 'update_version_display', None) is not None:
                self.app.update_version_display()
            if manual_check:
                show_timed_messagebox(self.app, QMessageBox.Icon.Information, "Update Check", "No new version found (no tags).", duration=1000)
            return

        latest_version = None
        for tag in tags:
            tag_name = tag.get('name', '').lstrip('v')
            try:
                current_tag_version = version.parse(tag_name)
                if latest_version is None or current_tag_version > latest_version:
                    latest_version = current_tag_version
            except version.InvalidVersion:
                logger.debug(f"Skipping invalid tag name: {tag.get('name')}")
                continue

        if latest_version:
            current_app_version = version.parse(self.app_version)
            logger.debug(f"Current version: {current_app_version}, Latest GitHub version: {latest_version}")
            if latest_version > current_app_version:
                logger.info("Newer version found!")
                self.update_available = True
                self.latest_version = latest_version
                if manual_check:
                    show_timed_messagebox(self.app, QMessageBox.Icon.Information, "Update Check", f"Update available: v{latest_version}", duration=1000)
            else:
                logger.info("Application is up to date.")
                self.update_available = False
                self.latest_version = latest_version
                if manual_check:
                    show_timed_messagebox(self.app, QMessageBox.Icon.Information, "Update Check", "Application is up to date.", duration=1000)
        else:
            logger.debug("Could not determine the latest version from tags.")
            self.update_available = False
            self.latest_version = None
            if manual_check:
                show_timed_messagebox(self.app, QMessageBox.Icon.Warning, "Update Check", "Could not determine the latest version.", duration=1000)

        if getattr(self.app, 'update_version_display', None) is not None:
            self.app.update_version_display()

    def _on_fetch_error(self, err: Any, manual_check: bool) -> None:
        """Handle errors from the background fetch on the main thread."""
        logger.error(f"Error checking for updates: {err}")
        if manual_check:
            show_timed_messagebox(self.app, QMessageBox.Icon.Warning, "Update Check", "Could not reach update server.", duration=1000)

    def check_for_updates(self, manual_check: bool = False) -> None:
        """Checks GitHub for newer versions in a background thread."""
        logger.info(f"Checking for updates... (Manual Check: {manual_check})")
        self.app.async_runner.run(
            self._fetch_tags,
            on_finished=lambda tags: self._on_tags_fetched(tags, manual_check),
            on_error=lambda err: self._on_fetch_error(err, manual_check),
        )

    def open_download_page(self) -> None:
        """Opens the GitHub releases page in the default web browser."""
        url = "https://github.com/magillos/Cable/releases"
        logger.info(f"Opening download page: {url}")
        webbrowser.open(url)
