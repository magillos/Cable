#!/usr/bin/env python3

import sys
import jack
import threading
import time
from collections import defaultdict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsTextItem, QGraphicsPathItem, QMenu, QStyleOptionGraphicsItem,
    QWidget, QStyle # Import QStyle
)
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QAction, QPolygonF
)
from PyQt6.QtCore import (
    Qt, QPointF, QRectF, QLineF, pyqtSignal, pyqtSlot, QObject, QTimer
)

from . import constants # Import the new constants module
from .jack_handler import JackHandler # Import the extracted class
from .port_item import PortItem
from .node_item import NodeItem
from .connection_item import ConnectionItem
from .gui_scene import JackGraphScene # Import the extracted scene class
from .gui_view import JackGraphView # Import the extracted view class
from .main_window import MainWindow # Import the extracted MainWindow class

# --- Entry Point ---

def main():
    # This main function is no longer used to run the graph as a standalone application.
    # The graph UI is now integrated as a tab within the main Cables application.
    # The following code is commented out.
    pass
    """
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Or another style like "Windows", "macOS"

    # Apply a dark theme stylesheet (basic example)
    app.setStyleSheet(\"\"\"
        QWidget {
            background-color: #2E2E2E;
            color: #E0E0E0;
            font-size: 9pt;
        }
        QMainWindow {
            background-color: #1E1E1E;
        }
        QGraphicsView {
            border: none; /* Remove border around the view */
        }
        QMenuBar, QMenu {
            background-color: #3C3C3C;
            color: #E0E0E0;
        }
        QMenuBar::item:selected, QMenu::item:selected {
            background-color: #5A5A5A;
        }
        QStatusBar {
            background-color: #1E1E1E;
        }
    \"\"\")

    print("Initializing JACK Handler...")
    # This would need to be the shared JackConnectionManager's client now
    # jack_handler = JackHandler() # Old way
    # jack_thread = threading.Thread(target=jack_handler.start, daemon=True)
    # jack_thread.start()
    # time.sleep(0.5)

    # if not jack_handler.is_active(): # Old check
    #      print("Failed to activate JACK client. Exiting.", file=sys.stderr)
    #      sys.exit(1)

    print("Creating Main Window...")
    # MainWindow now expects jack_client, connection_manager, preset_handler_ref, connection_history_ref
    # main_window = MainWindow(jack_handler) # Old way
    # main_window.show()

    exit_code = app.exec()
    print("Application exiting.")
    # Jack handler stop is called in MainWindow.closeEvent (if it were run standalone)
    sys.exit(exit_code)
    """


if __name__ == "__main__":
    main()
