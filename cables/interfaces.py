"""
Interfaces/Protocols for decoupling managers from JackConnectionManager.

This module defines abstract interfaces that specify the capabilities
each manager needs from the main JackConnectionManager, enabling:
1. Better testability (managers can be tested in isolation with mock implementations)
2. Clearer contracts between components
3. Reduced coupling (managers only depend on what they actually need)
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from PyQt6.QtWidgets import (
        QTreeWidget,
        QWidget,
        QPushButton,
        QTextEdit,
        QComboBox,
        QCheckBox,
    )
    from cable_core.config import ConfigManager
    from cables.config.enhanced_preset_manager import EnhancedPresetManager
    from cables.features.node_visibility_manager import NodeVisibilityManager
    from cables.jack_connection_handler import JackConnectionHandler
    import jack


@runtime_checkable
class ConfigProvider(Protocol):
    """Protocol for objects that provide configuration management."""

    config_manager: "ConfigManager"


@runtime_checkable
class JACKClientProvider(Protocol):
    """Protocol for objects that provide JACK client access."""

    client: "jack.Client"


@runtime_checkable
class GraphAccessor(Protocol):
    """Protocol for objects that provide graph component access."""

    def _get_graph_main_window(self) -> Optional[Any]:
        """Get the graph main window if available."""
        ...

    def _get_graph_scene(self) -> Optional[Any]:
        """Get the graph scene if available."""
        ...

    def _get_graph_view(self) -> Optional[Any]:
        """Get the graph view if available."""
        ...


@runtime_checkable
class ConnectionOperations(Protocol):
    """Protocol for objects that provide JACK connection operations."""

    def make_connection(self, output_name: str, input_name: str) -> None:
        """Make an audio connection."""
        ...

    def break_connection(self, output_name: str, input_name: str) -> None:
        """Break an audio connection."""
        ...

    def make_midi_connection(self, output_name: str, input_name: str) -> None:
        """Make a MIDI connection."""
        ...

    def break_midi_connection(self, output_name: str, input_name: str) -> None:
        """Break a MIDI connection."""
        ...


@runtime_checkable
class UIRefreshProvider(Protocol):
    """Protocol for objects that provide UI refresh capabilities."""

    def refresh_ports(
        self, refresh_all: bool = False, from_shortcut: bool = False
    ) -> None:
        """Refresh the port trees."""
        ...

    def refresh_visualizations(self) -> None:
        """Refresh connection visualizations."""
        ...


@runtime_checkable
class ColorProvider(Protocol):
    """Protocol for objects that provide color/theme information."""

    @property
    def text_color(self) -> Any:
        """Get the text color."""
        ...

    @property
    def background_color(self) -> Any:
        """Get the background color."""
        ...

    @property
    def highlight_color(self) -> Any:
        """Get the highlight color."""
        ...


@runtime_checkable
class PresetOperations(Protocol):
    """Protocol for objects that provide preset management access."""

    preset_manager: "EnhancedPresetManager"

    def disconnect_all_unified(self) -> None:
        """Disconnect all unified sink ports."""
        ...

    def reconnect_all_unified(self) -> None:
        """Reconnect all unified sink ports."""
        ...

    def _get_current_connections(self) -> List[Dict[str, str]]:
        """Get current JACK connections."""
        ...


@runtime_checkable
class PortTreeProvider(Protocol):
    """Protocol for objects that provide port tree widgets."""

    input_tree: "QTreeWidget"
    output_tree: "QTreeWidget"
    midi_input_tree: "QTreeWidget"
    midi_output_tree: "QTreeWidget"

    def _get_selected_item_info(self, tree_widget: "QTreeWidget") -> tuple:
        """Get selected item info from a tree."""
        ...

    def _restore_selection(
        self, tree_widget: "QTreeWidget", selection_info: tuple
    ) -> None:
        """Restore selection in a tree."""
        ...

    def _refresh_single_port_type(self, port_type: str) -> None:
        """Refresh a single port type (audio or midi)."""
        ...


@runtime_checkable
class LatencyUIProvider(Protocol):
    """Protocol for objects that provide latency test UI widgets."""

    latency_results_text: "QTextEdit"
    latency_run_button: "QPushButton"
    latency_stop_button: "QPushButton"
    latency_apply_offset_button: "QPushButton"
    latency_raw_output_checkbox: "QCheckBox"
    latency_input_combo: "QComboBox"
    latency_output_combo: "QComboBox"
    flatpak_env: bool
    port_type: str


@runtime_checkable
class ConnectionHistoryProvider(Protocol):
    """Protocol for objects that provide connection history access."""

    connection_history: Any

    def notify_connection_history_changed(self) -> None:
        """Notify that connection history has changed."""
        ...


# Composite interfaces for specific manager needs


@runtime_checkable
class PresetHandlerInterface(
    ConfigProvider,
    GraphAccessor,
    PresetOperations,
    ConnectionOperations,
    UIRefreshProvider,
    ColorProvider,
    JACKClientProvider,
    Protocol,
):
    """
    Complete interface needed by PresetHandler.

    This combines all the capabilities that PresetHandler needs from
    JackConnectionManager, making it clear what dependencies exist.
    """

    node_visibility_manager: Optional["NodeVisibilityManager"]
    action_manager: Optional[Any]
    save_preset_action: Optional[Any]


@runtime_checkable
class LatencyTesterInterface(
    ConfigProvider, LatencyUIProvider, ConnectionOperations, UIRefreshProvider, Protocol
):
    """
    Complete interface needed by LatencyTester.

    This combines all the capabilities that LatencyTester needs from
    JackConnectionManager.
    """

    pass


@runtime_checkable
class NodeVisibilityManagerInterface(
    ConfigProvider,
    GraphAccessor,
    PortTreeProvider,
    UIRefreshProvider,
    JACKClientProvider,
    Protocol,
):
    """
    Complete interface needed by NodeVisibilityManager.

    This combines all the capabilities that NodeVisibilityManager needs from
    JackConnectionManager.
    """

    midi_matrix_widget: Optional[Any]
    audio_matrix_widget: Optional[Any]


@runtime_checkable
class MatrixInterface(ConfigProvider, ConnectionOperations, Protocol):
    """
    Complete interface needed by MatrixWidget (both MIDI and Audio).

    This combines all the capabilities that MatrixWidget needs from
    JackConnectionManager.
    """

    pass


# Backward compatibility aliases
MidiMatrixInterface = MatrixInterface
AudioMatrixInterface = MatrixInterface


@runtime_checkable
class ActionManagerInterface(
    ConfigProvider,
    ColorProvider,
    ConnectionHistoryProvider,
    ConnectionOperations,
    UIRefreshProvider,
    Protocol,
):
    """
    Complete interface needed by ActionManager.

    This combines all the capabilities that ActionManager needs from
    JackConnectionManager.
    """

    ui_manager: Any

    def _get_ports_from_selected_items(self, tree_widget: "QTreeWidget") -> List[str]:
        """Get port names from selected items in a tree."""
        ...

    def update_connection_buttons(self) -> None:
        """Update audio connection button states."""
        ...

    def update_midi_connection_buttons(self) -> None:
        """Update MIDI connection button states."""
        ...

    def make_connection_selected(self) -> None:
        """Make connection from selected ports."""
        ...

    def break_connection_selected(self) -> None:
        """Break connection from selected ports."""
        ...

    def make_midi_connection_selected(self) -> None:
        """Make MIDI connection from selected ports."""
        ...

    def break_midi_connection_selected(self) -> None:
        """Break MIDI connection from selected ports."""
        ...


@runtime_checkable
class TabStateProvider(Protocol):
    """Protocol for objects that provide tab state information via signals."""

    def get_current_tab_type(self) -> str:
        """Get the current tab type: 'audio', 'midi', 'midi_matrix', 'graph', 'pwtop', 'alsa_mixer', 'latency', 'cable', or 'unknown'."""
        ...


@runtime_checkable
class ActionManagerCallbacks(Protocol):
    """Protocol for callbacks needed by ActionManager instead of main_window reference."""

    def on_connect_requested(self, is_midi: bool) -> None:
        """Handle connect request for audio or MIDI."""
        ...

    def on_disconnect_requested(self, is_midi: bool) -> None:
        """Handle disconnect request for audio or MIDI."""
        ...

    def on_undo_requested(self, is_midi: bool) -> None:
        """Handle undo request."""
        ...

    def on_redo_requested(self, is_midi: bool) -> None:
        """Handle redo request."""
        ...

    def on_refresh_requested(self) -> None:
        """Handle refresh ports request."""
        ...

    def on_untangle_requested(self, is_graph: bool) -> None:
        """Handle untangle request."""
        ...

    def on_zoom_requested(self, direction: int) -> None:
        """Handle zoom request. direction: 1=increase, -1=decrease."""
        ...

    def on_tab_switch_requested(self, forwards: bool) -> None:
        """Handle tab switch request between output/input trees."""
        ...

    def get_graph_main_window(self) -> Optional[Any]:
        """Get the graph main window if available."""
        ...

    def get_connection_history(self) -> Any:
        """Get the connection history object."""
        ...

    def notify_history_changed(self) -> None:
        """Notify that connection history has changed."""
        ...