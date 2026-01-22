#!/usr/bin/env python3
"""
Connection visualization service for drawing JACK/PipeWire connection lines.
"""

import random
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainterPath, QColor, QPen
from PyQt6.QtWidgets import QGraphicsPathItem
import jack

from cables import jack_utils


class ConnectionVisualizer:
    """
    Handles all drawing operations for connection visualization between ports.
    
    This class extracts the pure presentation logic for drawing connection lines,
    including path calculation, color generation, and scene management.
    """
    
    def __init__(self, jack_client, ui_manager, config_manager=None):
        """
        Initialize the ConnectionVisualizer.
        
        Args:
            jack_client: JACK client for accessing ports and connections
            ui_manager: UI manager for accessing theme settings
            config_manager: Config manager for loading settings
        """
        self.jack_client = jack_client
        self.ui_manager = ui_manager
        self.config_manager = config_manager
    
    def update_connection_graphics(self, scene, view, output_tree, input_tree, is_midi):
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
                relevant_output_ports = jack_utils.get_all_jack_ports(self.jack_client, is_output=True, is_midi=True)
            else:
                relevant_output_ports = jack_utils.get_all_jack_ports(self.jack_client, is_output=True, is_audio=True)

            for output_port_obj in relevant_output_ports:
                port_connections = jack_utils.get_all_jack_connections(self.jack_client, output_port_obj)
                connections.extend(port_connections)

        except jack.JackError as e:
            print(f"Error getting connections via jack_utils: {e}")
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
                    use_straight = self.config_manager.get_bool('use_straight_lines', False)
                
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
                
                base_name = output_name.rsplit(':', 1)[0]
                
                random.seed(base_name)
                base_color = QColor(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                
                if self.ui_manager.dark_mode:
                    h, s, v, a = base_color.getHsvF()
                    s = min(1.0, s * 1.4)
                    v = min(1.0, v * 1.3)
                    base_color.setHsvF(h, s, v, a)
                
                # Get line thickness from config
                line_thickness = 2
                if self.config_manager:
                    line_thickness = self.config_manager.get_int_setting('CONNECTION_LINE_THICKNESS', 2)
                pen = QPen(base_color, line_thickness)
                pen.setCosmetic(True)
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                scene.addItem(path_item)
    
    def get_port_position(self, tree_widget, port_name, connection_view, is_output):
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
