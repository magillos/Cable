#!/usr/bin/env python3
"""
Connection visualization service for drawing JACK/PipeWire connection lines.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainterPath, QColor, QPen
from PyQt6.QtWidgets import QGraphicsPathItem
import jack

import logging
logger = logging.getLogger(__name__)

from cables.jack_service import get_jack_service
from cable_core import config_keys as keys
from cables.utils.connection_colors import get_client_color, client_name_from_port

from typing import TYPE_CHECKING, Optional, List, Any
if TYPE_CHECKING:
    from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QTreeWidget
    from cable_core.config import ConfigManager


class ConnectionVisualizer:
    """
    Handles all drawing operations for connection visualization between ports.
    
    This class extracts the pure presentation logic for drawing connection lines,
    including path calculation, color generation, and scene management.
    """
    
    def __init__(self, jack_client: Any, ui_manager: Any, config_manager: Optional['ConfigManager'] = None) -> None:
        """
        Initialize the ConnectionVisualizer.
        
        Args:
            jack_client: JACK client (ignored, JackService is used)
            ui_manager: UI manager for accessing theme settings
            config_manager: Config manager for loading settings
        """
        self._jack_service = get_jack_service()
        self.ui_manager = ui_manager
        self.config_manager = config_manager
    
    def update_connection_graphics(self, scene: 'QGraphicsScene', view: 'QGraphicsView', output_tree: 'QTreeWidget', input_tree: 'QTreeWidget', is_midi: bool) -> None:
        """
        Update the connection graphics for the given scene and trees.
        
        Args:
            scene: QGraphicsScene to draw on
            view: QGraphicsView containing the scene
            output_tree: Tree widget for output ports
            input_tree: Tree widget for input ports
            is_midi: Whether to draw MIDI connections (vs audio)
        """
        scene.clear()
        view_rect = view.rect()
        scene_rect = QRectF(0, 0, view_rect.width(), view_rect.height())
        scene.setSceneRect(scene_rect)
        
        connections = []
        try:
            relevant_output_ports: list[jack.Port] = []
            if is_midi:
                relevant_output_ports = self._jack_service.get_ports(is_output=True, is_midi=True)
            else:
                relevant_output_ports = self._jack_service.get_ports(is_output=True, is_audio=True)

            for output_port_obj in relevant_output_ports:
                port_connections = self._jack_service.get_all_connections_as_tuples(output_port_obj)
                connections.extend(port_connections)

        except jack.JackError as e:
            logger.error(f"Error getting connections via JackService: {e}")
            return
        
        for output_name, input_name in connections:
            start_pos = self.get_port_position(output_tree, output_name, view, True)
            end_pos = self.get_port_position(input_tree, input_name, view, False)
            
            if start_pos and end_pos:
                path = QPainterPath()
                path.moveTo(start_pos)
                
                # Check if straight lines are enabled
                use_straight = False
                if self.config_manager:
                    use_straight = self.config_manager.get_bool(keys.USE_STRAIGHT_LINES, False)
                
                if use_straight:
                    path.lineTo(end_pos)
                else:
                    ctrl1_x = start_pos.x() + (end_pos.x() - start_pos.x()) / 3
                    ctrl2_x = start_pos.x() + 2 * (end_pos.x() - start_pos.x()) / 3
                    path.cubicTo(
                        QPointF(ctrl1_x, start_pos.y()),
                        QPointF(ctrl2_x, end_pos.y()),
                        end_pos
                    )
                
                use_colored = False
                if self.config_manager:
                    use_colored = self.config_manager.get_bool(keys.GRAPH_COLORED_CONNECTIONS, False)

                if use_colored:
                    base_name = client_name_from_port(output_name)
                    base_color = get_client_color(base_name, self.ui_manager.dark_mode)
                else:
                    base_color = self.ui_manager.connection_color
                
                # Get line thickness from config
                line_thickness = 2
                if self.config_manager:
                    line_thickness = self.config_manager.get_int_setting(keys.CONNECTION_LINE_THICKNESS, 2)
                pen = QPen(base_color, line_thickness)
                pen.setCosmetic(True)
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                scene.addItem(path_item)
    
    def get_port_position(self, tree_widget: 'QTreeWidget', port_name: str, connection_view: 'QGraphicsView', is_output: bool) -> Optional[QPointF]:
        """
        Get the scene position for a port in the tree widget.
        
        Args:
            tree_widget: Tree widget containing the port
            port_name: Name of the port
            connection_view: Connection view to map coordinates to
            is_output: Whether this is an output tree (affects x position)
            
        Returns:
            QPointF in scene coordinates, or None if not found
        """
        port_item = tree_widget.port_items.get(port_name)
        if not port_item:
            return None
        
        parent_group = port_item.parent()
        if not parent_group:
            return None
        
        is_expanded = parent_group.isExpanded()
        
        target_item = port_item if is_expanded else parent_group
        
        rect = tree_widget.visualItemRect(target_item)
        
        if rect.height() <= 0:
            return None
        
        point = QPointF(tree_widget.viewport().width() if is_output else 0,
                       rect.top() + rect.height() / 2)
        
        viewport_point = tree_widget.viewport().mapToParent(point.toPoint())
        global_point = tree_widget.mapToGlobal(viewport_point)
        scene_point = connection_view.mapFromGlobal(global_point)
        return connection_view.mapToScene(scene_point)
