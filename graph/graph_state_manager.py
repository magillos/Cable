# graph/graph_state_manager.py
"""
Headless manager for JACK graph state synchronization.

Listens to JackService signals, processes JACK state changes (port/client
filtering, audio/MIDI splitting, visibility), and emits signals for the
scene to apply visual updates. The scene only responds to signals from
this manager rather than interacting with JACK directly.
"""
import jack
import logging
from typing import TYPE_CHECKING, List, Dict, Optional, Any, Set

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from cable_core import config_keys as keys
from cables.jack_service import get_jack_service
from cables.unified_sink_manager import _has_sink_suffix, _strip_sink_suffix

if TYPE_CHECKING:
    from cables.connection_manager import JackConnectionManager
    from cables.features.node_visibility_manager import NodeVisibilityManager
    from cable_core.config import ConfigManager

logger = logging.getLogger(__name__)


class GraphStateManager(QObject):
    """Manages JACK state synchronization for the graph scene.

    Queries JACK for current clients/ports, applies visibility filtering
    and audio/MIDI splitting, then emits signals with the processed data
    for the scene to apply visually.

    Signals:
        full_sync_ready(clients_to_process, present_client_names, all_ports):
            Emitted when a full sync computation is complete.
            - clients_to_process: dict mapping client_name -> {ports: dict, original_client_name: str}
            - present_client_names: set of all client names present in JACK (before visibility filter)
            - all_ports: list of jack.Port objects (audio + MIDI)

        jack_shutdown_detected():
            Emitted when the JACK server shuts down.
    """

    full_sync_ready = pyqtSignal(object, object, object)
    jack_shutdown_detected = pyqtSignal()

    def __init__(
        self,
        jack_client: jack.Client,
        connection_manager: 'JackConnectionManager',
        main_config_manager: 'ConfigManager',
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)

        self.jack_client = jack_client
        self.connection_manager = connection_manager
        self.main_config_manager = main_config_manager
        self._node_visibility_manager: Optional['NodeVisibilityManager'] = None

        # Debounce timer for batching rapid JACK events (e.g. desktop clients)
        self._refresh_debounce_timer = QTimer(self)
        self._refresh_debounce_timer.setSingleShot(True)
        self._refresh_debounce_timer.timeout.connect(self._perform_sync)

        # Connect to JackService signals directly
        jack_service = get_jack_service()
        jack_service.port_added.connect(self._on_port_added)
        jack_service.port_removed.connect(self._on_port_removed)
        jack_service.client_added.connect(self._on_client_added)
        jack_service.client_removed.connect(self._on_client_removed)
        jack_service.connection_made.connect(lambda out, inp: self.schedule_refresh())
        jack_service.connection_broken.connect(lambda out, inp: self.schedule_refresh())
        jack_service.shutdown.connect(self._on_jack_shutdown)

    # --- Public API ---

    def set_node_visibility_manager(self, nvm: 'NodeVisibilityManager') -> None:
        """Set the NodeVisibilityManager used for visibility filtering during sync."""
        self._node_visibility_manager = nvm

    def schedule_refresh(self) -> None:
        """Schedule a debounced full graph refresh (100 ms)."""
        self._refresh_debounce_timer.start(100)

    def perform_sync(self) -> None:
        """Perform an immediate (non-debounced) full sync.

        Computes the desired graph state and emits ``full_sync_ready``.
        Any pending debounced refresh is cancelled.
        """
        self._refresh_debounce_timer.stop()
        self._perform_sync()

    # --- Internal sync logic ---

    @pyqtSlot()
    def _perform_sync(self) -> None:
        """Compute sync data and emit ``full_sync_ready``."""
        logger.info("GraphStateManager: Performing sync...")
        try:
            all_ports = self._get_all_audio_midi_ports()
            clients_to_process, present_client_names = self._compute_clients_to_process(all_ports)
            self.full_sync_ready.emit(clients_to_process, present_client_names, all_ports)
        except Exception as e:
            logger.error(f"GraphStateManager: Error during sync: {e}")
            import traceback
            traceback.print_exc()

    def _get_all_audio_midi_ports(self) -> List[jack.Port]:
        """Query JACK for all audio and MIDI ports."""
        all_ports: List[jack.Port] = []
        jack_service = get_jack_service()
        midi_ports = jack_service.get_ports(is_midi=True)
        audio_ports = jack_service.get_ports(is_audio=True)
        if midi_ports:
            all_ports.extend(midi_ports)
        if audio_ports:
            all_ports.extend(audio_ports)
        return all_ports

    def _compute_clients_to_process(
        self, all_ports: List[jack.Port]
    ) -> tuple[Dict[str, Dict[str, Any]], Set[str]]:
        """Compute the set of clients that should exist in the graph.

        Returns:
            Tuple of (clients_to_process, present_client_names).
            ``clients_to_process`` is the dict *after* visibility filtering.
            ``present_client_names`` is the set of all client names in JACK
            *before* visibility filtering (used for unified-sink unload decisions).
        """
        # Group ports by client
        clients_ports: Dict[str, Dict[str, jack.Port]] = {}
        for port in all_ports:
            client_name, _ = port.name.split(':', 1)
            if client_name not in clients_ports:
                clients_ports[client_name] = {}
            clients_ports[client_name][port.name] = port

        # Handle audio/MIDI splitting
        split_audio_midi = self.main_config_manager.get_bool(
            keys.GRAPH_SPLIT_AUDIO_MIDI_CLIENTS, False
        )
        clients_to_process = self._apply_audio_midi_splitting(clients_ports, split_audio_midi)

        # Track present clients (before visibility filtering)
        present_client_names = set(clients_to_process.keys())

        # Apply visibility filtering
        clients_to_process = self._apply_visibility_filtering(clients_to_process)

        return clients_to_process, present_client_names

    def _apply_audio_midi_splitting(
        self,
        clients_ports: Dict[str, Dict[str, jack.Port]],
        split_audio_midi: bool,
    ) -> Dict[str, Dict[str, Any]]:
        """Split mixed audio/MIDI clients into separate virtual clients if configured."""
        clients_to_process: Dict[str, Dict[str, Any]] = {}

        if split_audio_midi:
            for client_name, ports in clients_ports.items():
                has_audio = any(p.is_audio for p in ports.values())
                has_midi = any(p.is_midi for p in ports.values())

                if has_audio and has_midi:
                    audio_ports = {n: p for n, p in ports.items() if p.is_audio}
                    midi_ports = {n: p for n, p in ports.items() if p.is_midi}

                    clients_to_process[f"{client_name} (Audio)"] = {
                        'ports': audio_ports,
                        'original_client_name': client_name,
                    }
                    clients_to_process[f"{client_name} (MIDI)"] = {
                        'ports': midi_ports,
                        'original_client_name': client_name,
                    }
                else:
                    clients_to_process[client_name] = {
                        'ports': ports,
                        'original_client_name': client_name,
                    }
        else:
            for client_name, ports in clients_ports.items():
                clients_to_process[client_name] = {
                    'ports': ports,
                    'original_client_name': client_name,
                }

        return clients_to_process

    def _apply_visibility_filtering(
        self,
        clients_to_process: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Filter clients based on NodeVisibilityManager settings."""
        if not self._node_visibility_manager:
            return clients_to_process

        visible_clients: Dict[str, Dict[str, Any]] = {}
        visible_owner_bases: Set[str] = set()

        _UNIFIED_PREFIXES = (
            'unified-input-', 'unified-output-',
            'unified_input-', 'unified_output-',
        )

        # Pass 1: decide visibility for non-sink clients and collect bases
        for client_name, client_info in clients_to_process.items():
            is_midi = False
            ports = client_info['ports']
            if ports:
                for port_obj in ports.values():
                    if hasattr(port_obj, 'is_midi') and port_obj.is_midi:
                        is_midi = True
                        break

            is_unified_sink = _has_sink_suffix(client_name) and any(
                client_name.startswith(p) for p in _UNIFIED_PREFIXES
            )

            if is_unified_sink:
                continue

            if self._node_visibility_manager.is_node_visible(client_name, is_midi=is_midi, tab_type="graph"):
                visible_clients[client_name] = client_info
                owner_base = (client_info.get('original_client_name') or client_name).replace(' ', '_')
                visible_owner_bases.add(owner_base)

        # Pass 2: include unified sink clients only if their owner is visible
        for client_name, client_info in clients_to_process.items():
            is_unified_sink = _has_sink_suffix(client_name) and any(
                client_name.startswith(p) for p in _UNIFIED_PREFIXES
            )
            if not is_unified_sink:
                continue

            sink_base_name = _strip_sink_suffix(client_name)
            for prefix in _UNIFIED_PREFIXES:
                if sink_base_name.startswith(prefix):
                    owner_base = sink_base_name[len(prefix):]
                    if owner_base in visible_owner_bases:
                        visible_clients[client_name] = client_info
                    break

        return visible_clients

    # --- JackService signal handlers ---

    @pyqtSlot(str, str, int, str, bool)
    def _on_port_added(self, port_name: str, client_name: str, flags: int, type_str: str, is_input: bool) -> None:
        logger.debug(f"GraphStateManager: Port added - {port_name}")
        self.schedule_refresh()

    @pyqtSlot(str, str)
    def _on_port_removed(self, port_name: str, client_name: str) -> None:
        logger.debug(f"GraphStateManager: Port removed - {port_name}")
        self.schedule_refresh()

    @pyqtSlot(str)
    def _on_client_added(self, client_name: str) -> None:
        logger.debug(f"GraphStateManager: Client added - {client_name}")
        self.schedule_refresh()

    @pyqtSlot(str)
    def _on_client_removed(self, client_name: str) -> None:
        logger.debug(f"GraphStateManager: Client removed - {client_name}")
        self.schedule_refresh()

    @pyqtSlot()
    def _on_jack_shutdown(self) -> None:
        logger.debug("GraphStateManager: JACK server shutdown detected.")
        self.jack_shutdown_detected.emit()
