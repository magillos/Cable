#!/usr/bin/env python3
"""
DeviceManager - Handles audio device and profile management for Cable.

This module provides a manager class that handles:
- Loading and displaying audio devices
- Loading and applying device profiles
- Coordinating with PipewireManager for device operations
"""

import logging
from typing import TYPE_CHECKING, Optional, Any, Dict

from PyQt6.QtWidgets import QComboBox, QMessageBox

if TYPE_CHECKING:
    from cable_core.pipewire import PipewireManager
    from cable_core.async_worker import AsyncRunner

logger = logging.getLogger(__name__)

__all__ = ['DeviceManager']


class DeviceManager:
    """
    Manages audio device and profile settings.
    
    This class handles the loading, display, and application of audio
    device profiles in PipeWire.
    
    Usage:
        manager = DeviceManager(parent, pipewire_manager, async_runner)
        manager.load_devices()
        # User selects device, profiles are loaded automatically
        manager.apply_profile()  # Apply selected profile
    """
    
    def __init__(
        self,
        parent: Any,
        pipewire_manager: 'PipewireManager',
        async_runner: 'AsyncRunner',
        device_combo: QComboBox,
        profile_combo: QComboBox,
        apply_button: Optional[Any] = None
    ) -> None:
        """
        Initialize the DeviceManager.
        
        Args:
            parent: Parent widget for dialog parenting
            pipewire_manager: PipewireManager instance for backend operations
            async_runner: AsyncRunner for async operations
            device_combo: Combo box for device selection
            profile_combo: Combo box for profile selection
            apply_button: Optional apply button to enable/disable based on selection
        """
        self.parent = parent
        self.pipewire_manager = pipewire_manager
        self.async_runner = async_runner
        self.device_combo = device_combo
        self.profile_combo = profile_combo
        self.apply_button = apply_button
        
        # Map profile descriptions to their indices
        self.profile_index_map: Dict[str, int] = {}
        
        # Connect signals
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
    
    def load_devices(self, preserve_selection: bool = False) -> None:
        """Load available audio devices asynchronously.
        
        Args:
            preserve_selection: If True, attempt to restore the current selection after reload.
        """
        # Save current selection if requested
        if preserve_selection and self.device_combo.currentIndex() > 0:
            self._saved_device_selection = self.device_combo.currentText()
            self._saved_profile_selection = self.profile_combo.currentText() if self.profile_combo.count() > 0 else None
        else:
            self._saved_device_selection = None
            self._saved_profile_selection = None
        
        self.device_combo.setEnabled(False)
        self.async_runner.run(
            self.pipewire_manager.load_devices,
            self._on_devices_loaded
        )
    
    def _on_devices_loaded(self, result: Dict[str, Any]) -> None:
        """Handle async device loading completion."""
        self.device_combo.setEnabled(True)
        self.device_combo.clear()
        self.device_combo.addItem("Choose device")
        
        if result and result.get("ok") and result.get("data"):
            for dev in result["data"]:
                self.device_combo.addItem(f"{dev['description']} (ID: {dev['id']})")
        elif result and not result.get("ok") and result.get("error"):
            QMessageBox.critical(self.parent, result["error"]["title"], result["error"]["message"])
        
        # Restore previous selection if saved
        if hasattr(self, '_saved_device_selection') and self._saved_device_selection:
            index = self.device_combo.findText(self._saved_device_selection)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
                # Profile will be restored via the profiles loaded callback
            self._saved_device_selection = None
    
    def _on_device_changed(self, index: int) -> None:
        """Handle device selection change."""
        if index > 0:  # Ignore the "Choose device" option
            self._load_profiles()
        else:
            self.profile_combo.clear()
            # Disable apply button when no device selected
            if self.apply_button:
                self.apply_button.setEnabled(False)
    
    def _on_profile_changed(self, index: int) -> None:
        """Handle profile selection change."""
        # Enable apply button only if both device and profile are selected
        if self.apply_button:
            device_selected = self.device_combo.currentIndex() > 0
            profile_selected = index >= 0 and self.profile_combo.count() > 0
            self.apply_button.setEnabled(device_selected and profile_selected)
    
    def _load_profiles(self) -> None:
        """Load profiles for the selected device asynchronously."""
        selected_device = self.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        
        self.profile_combo.setEnabled(False)
        self.async_runner.run(
            self.pipewire_manager.load_profiles,
            self._on_profiles_loaded,
            None,
            device_id
        )
    
    def _on_profiles_loaded(self, result: Dict[str, Any]) -> None:
        """Handle async profile loading completion."""
        self.profile_combo.setEnabled(True)
        self.profile_combo.clear()
        self.profile_index_map.clear()
        
        if result and result.get("ok") and result.get("data"):
            profiles = result["data"].get("profiles", [])
            active_index = result["data"].get("active_index")
            
            for profile in profiles:
                description = profile.get("description", "Unknown Profile")
                index = profile.get("index", "Unknown")
                self.profile_combo.addItem(description)
                self.profile_index_map[description] = index
                
                if active_index is not None and index == active_index:
                    self.profile_combo.setCurrentText(description)
            
            # Restore saved profile selection if available
            if hasattr(self, '_saved_profile_selection') and self._saved_profile_selection:
                profile_index = self.profile_combo.findText(self._saved_profile_selection)
                if profile_index >= 0:
                    self.profile_combo.setCurrentIndex(profile_index)
                self._saved_profile_selection = None
    
    def apply_profile(self) -> bool:
        """Apply the selected profile to the selected device.
        
        Returns:
            True if profile was applied successfully, False otherwise.
        """
        selected_device = self.device_combo.currentText()
        if "(ID: " not in selected_device:
            logger.warning("No valid device selected for profile application")
            return False
        
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        selected_profile = self.profile_combo.currentText()
        profile_index = self.profile_index_map.get(selected_profile)
        
        result = self.pipewire_manager.apply_profile_settings(device_id, profile_index)
        if not result.get("ok") and result.get("error"):
            QMessageBox.critical(self.parent, result["error"]["title"], result["error"]["message"])
            return False
        return True
    
    def reset_selection(self) -> None:
        """Reset device and profile selections."""
        self.device_combo.setCurrentIndex(0)
        self.profile_combo.clear()
    
    def get_selected_device_id(self) -> Optional[str]:
        """
        Get the ID of the currently selected device.
        
        Returns:
            Device ID string or None if no device selected
        """
        selected_device = self.device_combo.currentText()
        if "(ID: " in selected_device:
            return selected_device.split('(ID: ')[-1].strip(')')
        return None
