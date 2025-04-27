# Cables

A JACK/PipeWire connection manager for audio and MIDI connections.

## Project Structure

The refactored project is organized as follows:

```
connection-manager.py            # Main entry point
cables/
├── __init__.py                  # Package initialization
├── config/                      # Configuration management
│   ├── __init__.py
│   ├── config_manager.py        # Application configuration
│   └── preset_manager.py        # Connection presets
├── features/                    # Core functionality
│   ├── __init__.py
│   ├── connection_history.py    # Undo/redo functionality
│   ├── latency_tester.py        # Latency testing
│   └── pwtop_monitor.py         # PipeWire monitoring
├── ui/                          # User interface components
│   ├── __init__.py
│   ├── connection_view.py       # Connection visualization
│   ├── port_tree_widget.py      # Port tree widgets
│   └── tab_ui_manager.py        # Tab setup and management
└── utils/                       # Utility functions
    ├── __init__.py
    └── helpers.py               # Helper functions
```

## Features

- Audio and MIDI connection management
- Connection presets
- Latency testing
- PipeWire monitoring
- Drag and drop connection creation
- Undo/redo functionality

## Usage

Run the application with:

```bash
python connection-manager.py
```

For headless mode (to load a preset without GUI):

```bash
python connection-manager.py --headless
```
