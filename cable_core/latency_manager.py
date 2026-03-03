#!/usr/bin/env python3
"""
LatencyManager - Handles latency offset management for Cable.

This module provides a manager class that handles:
- Loading and applying latency offsets to audio nodes
- Managing latency offset UI state
- Coordinating with PipewireManager for latency operations
"""

import logging
from typing import TYPE_CHECKING, Optional, Any, Dict, List

from PyQt6.QtWidgets import QComboBox, QLineEdit, QCheckBox, QMessageBox
from PyQt6.QtCore import Qt

if TYPE_CHECKING:
    from cable_core.pipewire import PipewireManager
    from cable_core.async_worker import AsyncRunner

logger = logging.getLogger(__name__)

__all__ = ['LatencyManager']


class LatencyManager:
    """
    Manages latency offset settings for audio nodes.
    
    This class handles the loading, display, and application of latency
    offsets to PipeWire audio nodes.
    
    Usage:
        manager = LatencyManager(parent, pipewire_manager, async_runner)
        manager.load_nodes()
        # User selects node, latency is loaded automatically
        manager.apply_latency()  # Apply current settings
    """
    
    def __init__(
        self,
        parent: Any,
        pipewire_manager: 'PipewireManager',
        async_runner: 'AsyncRunner',
        node_combo: QComboBox,
        latency_input: QLineEdit,
        nanoseconds_checkbox: QCheckBox
    ) -> None:
        """
        Initialize the LatencyManager.
        
        Args:
            parent: Parent widget for dialog parenting
            pipewire_manager: PipewireManager instance for backend operations
            async_runner: AsyncRunner for async operations
            node_combo: Combo box for node selection
            latency_input: Line edit for latency value input
            nanoseconds_checkbox: Checkbox for nanoseconds unit toggle
        """
        self.parent = parent
        self.pipewire_manager = pipewire_manager
        self.async_runner = async_runner
        self.node_combo = node_combo
        self.latency_input = latency_input
        self.nanoseconds_checkbox = nanoseconds_checkbox
        
        # Connect signals
        self.node_combo.currentIndexChanged.connect(self._on_node_changed)
    
    def load_nodes(self) -> None:
        """Load available audio nodes asynchronously."""
        self.node_combo.setEnabled(False)
        self.async_runner.run(
            self.pipewire_manager.load_nodes,
            self._on_nodes_loaded
        )
    
    def _on_nodes_loaded(self, result: Dict[str, Any]) -> None:
        """Handle async node loading completion."""
        self.node_combo.setEnabled(True)
        self.node_combo.clear()
        self.node_combo.addItem("Choose Node")
        
        if result and result.get("ok") and result.get("data"):
            for node in result["data"]:
                io_type = node.get("io_type", "")
                if io_type:
                    self.node_combo.addItem(f"{node['description']} ({io_type}) (ID: {node['id']})")
                else:
                    self.node_combo.addItem(f"{node['description']} (ID: {node['id']})")
        elif result and not result.get("ok") and result.get("error"):
            QMessageBox.critical(self.parent, result["error"]["title"], result["error"]["message"])
    
    def _on_node_changed(self, index: int) -> None:
        """Handle node selection change."""
        if index > 0:  # Ignore the "Choose Node" option
            selected_node = self.node_combo.currentText()
            node_id = selected_node.split('(ID: ')[-1].strip(')')
            self._load_latency_offset(node_id)
        else:
            self.latency_input.setText("")
    
    def _load_latency_offset(self, node_id: str) -> None:
        """Load latency offset for a specific node asynchronously."""
        self.latency_input.setEnabled(False)
        self.async_runner.run(
            self.pipewire_manager.load_latency_offset,
            self._on_latency_offset_loaded,
            None,
            node_id
        )
    
    def _on_latency_offset_loaded(self, result: Dict[str, Any]) -> None:
        """Handle async latency offset loading completion."""
        self.latency_input.setEnabled(True)
        if result and result.get("data"):
            self.latency_input.setText(result["data"].get("value", ""))
            self.nanoseconds_checkbox.setChecked(result["data"].get("is_nanoseconds", False))
        else:
            self.latency_input.setText("")
            self.nanoseconds_checkbox.setChecked(False)
    
    def apply_latency(self) -> None:
        """Apply the current latency settings to the selected node."""
        selected_node = self.node_combo.currentText()
        if "(ID: " not in selected_node:
            logger.warning("No valid node selected for latency application")
            return
        
        node_id = selected_node.split('(ID: ')[-1].strip(')')
        latency_offset = self.latency_input.text()
        use_nanoseconds = self.nanoseconds_checkbox.isChecked()
        
        result = self.pipewire_manager.apply_latency_settings(node_id, latency_offset, use_nanoseconds)
        if not result.get("ok") and result.get("error"):
            QMessageBox.critical(self.parent, result["error"]["title"], result["error"]["message"])
    
    def reset_all_latency(self, node_ids: List[str], on_complete: Optional[Any] = None) -> None:
        """
        Reset latency for all nodes.
        
        Args:
            node_ids: List of node IDs to reset
            on_complete: Optional callback to call after reset
        """
        logger.debug(f"Resetting latency for {len(node_ids)} nodes")
        self.pipewire_manager.reset_all_latency(node_ids)
        
        if on_complete:
            on_complete()
    
    def get_all_node_ids(self) -> List[str]:
        """
        Get all node IDs from the combo box.
        
        Returns:
            List of node ID strings
        """
        node_ids = []
        for i in range(self.node_combo.count()):
            node_text = self.node_combo.itemText(i)
            if node_text == "Choose Node":
                continue
            if '(ID: ' in node_text:
                node_id = node_text.split('(ID: ')[-1].strip(')')
                if node_id:
                    node_ids.append(node_id)
        return node_ids
    
    def clear(self) -> None:
        """Clear the latency input and reset node selection."""
        self.node_combo.setCurrentIndex(0)
        self.latency_input.setText("")
        self.nanoseconds_checkbox.setChecked(False)
