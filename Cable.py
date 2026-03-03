"""
Cable — PipeWire settings GUI.

Main entry point for the Cable application. Provides quantum (buffer size),
sample rate, device, and latency controls via a PyQt6 widget that can run
standalone or embedded in the Cables connection manager.
"""
import sys
import signal
import os
import logging
import configparser
import argparse
import shutil

from cable_core.logging_config import setup_logging
setup_logging()

from cable_core.autostart import AutostartManager
from cable_core.config import ConfigManager
from cable_core.system import SystemManager
from cable_core.tray import TrayManager
from cable_core.pipewire import PipewireManager
from cable_core.async_worker import AsyncRunner
from cable_core.process import ProcessManager
from cable_core.updates import UpdateManager
from cable_core.app_config import APP_VERSION, EDIT_LIST_TEXT, load_app_icon
from cable_core.embedded_settings_panel import EmbeddedSettingsPanel
from cable_core import app_config
from cable_core import config_keys as keys
# New managers for decomposed functionality
from cable_core.dsp_monitor import DSPMonitor
from cable_core.latency_manager import LatencyManager
from cable_core.device_manager import DeviceManager
from cable_core.quantum_manager import QuantumManager
from cables.config.preset_manager import PresetManager
from cables.jack_service import get_jack_service
from PyQt6.QtCore import Qt, QTimer, QMargins, QEvent
from PyQt6.QtGui import QFont, QIcon, QGuiApplication, QActionGroup, QAction
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QComboBox, QLineEdit, QPushButton, QLabel,
                             QSpacerItem, QSizePolicy, QMessageBox, QGroupBox,
                             QCheckBox, QSystemTrayIcon, QMenu, QDialog, QDialogButtonBox,
                             QScrollArea, QWidgetAction, QSplitter, QProgressBar)

from typing import TYPE_CHECKING, List, Optional, Any, Dict, Union
if TYPE_CHECKING:
    from cable_core.config import ConfigManager
    from cable_core.system import SystemManager
    from cable_core.tray import TrayManager
    from cable_core.process import ProcessManager
    from cable_core.updates import UpdateManager
    from cable_core.pipewire import PipewireManager
    from cable_core.async_worker import AsyncRunner
    from cable_core.autostart import AutostartManager
    from cables.jack_service import JackService

logger = logging.getLogger(__name__)

class CableApp(QApplication):
    def __init__(self, argv: List[str]) -> None:
        super().__init__(argv)


        # This needs to match your .desktop file name exactly
        QGuiApplication.setDesktopFileName("com.github.magillos.cable")


        # Set the application name to match the .desktop file
        self.setApplicationName("Cable")
        
        # Set window icon explicitly for title bar
        self._set_application_icon()
    
    def _set_application_icon(self) -> None:
        """Set the application window icon."""
        app_icon = load_app_icon()
        if app_icon:
            self.setWindowIcon(app_icon)

class PipeWireSettingsApp(QWidget):

    # Comment block to ensure it stays in config.ini

    def __init__(self, is_minimized_startup: bool = False, embedded: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.is_minimized_startup = is_minimized_startup # Store the flag
        self.embedded = embedded # Store embedded mode flag
        self.flatpak_env = os.path.exists('/.flatpak-info')
        self.appimage_path = self._detect_appimage_path()  # Detect AppImage path
        self.tray_icon = None  # Initialize tray_icon here
        self.tray_enabled = False
        self.connection_manager_process = None
        self.tray_click_opens_cables = True
        self.cables_executable_path = None  # Will be set during init
        # Initialize autostart manager (will be updated after config is loaded)
        self.autostart_manager = AutostartManager(self.flatpak_env, self.appimage_path)
        # Instantiate ConfigManager
        self.config_manager = ConfigManager(self)
        
        # Check if migration happened and show dialog if needed
        self.config_manager.show_migration_dialog_if_needed(parent_widget=self)
        
        self.system_manager = SystemManager(self) # Instantiate SystemManager
        self.tray_manager = TrayManager(self) # Instantiate TrayManager
        self.process_manager = ProcessManager(self) # Instantiate ProcessManager
        self.update_manager = UpdateManager(self, APP_VERSION) # Instantiate UpdateManager, passing APP_VERSION
        self.pipewire_manager = PipewireManager(self.flatpak_env, self.config_manager)
        self.async_runner = AsyncRunner(self)
        
        self.remember_settings = False # Keep placeholder for type hinting/attribute existence if needed elsewhere initially
        self.restore_only_minimized = False # New setting
        self.saved_quantum = 0
        self.saved_sample_rate = 0
        self.autostart_enabled = False
        self.check_updates_at_start = False # Default: Do not check for updates on startup
        self.values_initialized = False  # Flag to track if values have been initialized
        self.autostart_version_action = None # Action for version menu autostart toggle

        # Placeholder for focused managers (initialized after UI)
        self.dsp_monitor: Optional[DSPMonitor] = None
        self.latency_manager: Optional[LatencyManager] = None
        self.device_manager: Optional[DeviceManager] = None
        self.quantum_manager: Optional[QuantumManager] = None
        
        # Initialize UI first (creates widgets needed by managers)
        self.initUI()
        
        # Flag to prevent saving during initial load
        self.initial_load = True
        
        # First load current system settings as fallback
        self._apply_current_settings()

        # Ensure config lists exist before loading settings
        self.config_manager.ensure_config_lists()

        # Then load settings from config using the manager
        settings = self.config_manager.load_settings()
        self._apply_loaded_settings(settings)

        # Now allow saving of user changes
        self.initial_load = False
        
        # Mark values as initialized
        self.values_initialized = True

        # Update autostart manager with configured AppImage path
        appimage_path_to_use = self.appimage_path if self.appimage_path else self._detect_appimage_path()
        if appimage_path_to_use:
            # Use configured path if available, otherwise use detected path
            self.autostart_manager = AutostartManager(self.flatpak_env, appimage_path_to_use)

        # Update latency display after everything is loaded
        self.update_latency_display()

        # Conditionally check for updates shortly after startup
        QTimer.singleShot(2000, self.update_manager._initial_update_check) # Check after 2 seconds if enabled (using UpdateManager)
        
        # Timer for debouncing splitter save (embedded mode)
        self._splitter_save_timer = QTimer(self)
        self._splitter_save_timer.setSingleShot(True)
        self._splitter_save_timer.setInterval(500)
        self._splitter_save_timer.timeout.connect(self._perform_save_embedded_splitter_position)
        self._pending_splitter_pos = None

    def _detect_appimage_path(self) -> Optional[str]:
        """Detect if the application is running from an AppImage and return the path."""
        # Check for APPIMAGE environment variable (set by AppImage runtime)
        appimage_path = os.environ.get('APPIMAGE')
        if appimage_path and os.path.exists(appimage_path):
            logger.info(f"Detected AppImage path: {appimage_path}")
            return appimage_path
        return None


    def _reset_xrun_count(self, event: Optional[Any] = None) -> None:
        """Reset the xrun counter to zero."""
        if self.dsp_monitor is not None:
            self.dsp_monitor.reset_xrun_count()



    def edit_quantum_list(self) -> None:
        """Opens the dialog to edit the quantum values list."""
        if self.quantum_manager is not None:
            self.quantum_manager.edit_quantum_list()
            self.refresh_all_settings()

    def edit_sample_rate_list(self) -> None:
        """Opens the dialog to edit the sample rate values list."""
        if self.quantum_manager is not None:
            self.quantum_manager.edit_sample_rate_list()
            self.refresh_all_settings()

    def initUI(self) -> None:
        from cable_core.ui_widgets import (QuantumGroup, SampleRateGroup, AudioProfileGroup, 
                                           LatencyGroup, RestartGroup)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(10) # Adjust main layout spacing

        # Use vertical buttons in embedded mode
        use_vertical_buttons = self.embedded

        # Quantum Section
        quantum_group = QuantumGroup(
            config_manager=self.config_manager,
            default_values_list=QuantumManager.DEFAULT_QUANTUM_VALUES,
            vertical_buttons=use_vertical_buttons,
            apply_slot=self.apply_quantum_settings,
            reset_slot=self._handle_reset_quantum,
            refresh_slot=self.refresh_all_settings,
            reset_xrun_slot=self._reset_xrun_count
        )
        self.quantum_combo = quantum_group.combo_box
        self.apply_quantum_button = quantum_group.apply_button
        self.reset_quantum_button = quantum_group.reset_button
        self.refresh_quantum_button = quantum_group.refresh_button
        self.latency_display_value = quantum_group.latency_display_value
        self.xrun_display_value = quantum_group.xrun_display_value
        self.dsp_load_value = quantum_group.dsp_load_value
        self.dsp_load_bar = quantum_group.dsp_load_bar

        # Sample Rate Section
        sample_rate_group = SampleRateGroup(
            config_manager=self.config_manager,
            default_values_list=QuantumManager.DEFAULT_SAMPLE_RATE_VALUES,
            vertical_buttons=use_vertical_buttons,
            apply_slot=self.apply_sample_rate_settings,
            reset_slot=self._handle_reset_sample_rate,
            refresh_slot=self.refresh_all_settings
        )
        self.sample_rate_combo = sample_rate_group.combo_box
        self.apply_sample_rate_button = sample_rate_group.apply_button
        self.reset_sample_rate_button = sample_rate_group.reset_button
        self.refresh_sample_rate_button = sample_rate_group.refresh_button

        # Audio Profile Section
        profile_group = AudioProfileGroup(apply_slot=self._handle_apply_profile)
        self.device_combo = profile_group.device_combo
        self.profile_combo = profile_group.profile_combo
        self.apply_profile_button = profile_group.apply_button

        # Latency Section
        latency_group = LatencyGroup(
            vertical_buttons=use_vertical_buttons,
            apply_slot=self._handle_apply_latency,
            reset_all_slot=self._handle_reset_all_latency_and_refresh
        )
        self.node_combo = latency_group.node_combo
        self.latency_input = latency_group.latency_input
        self.nanoseconds_checkbox = latency_group.nanoseconds_checkbox
        self.apply_latency_button = latency_group.apply_button
        self.reset_all_latency_button = latency_group.reset_all_button

        # Restart Buttons Section
        restart_group = RestartGroup(
            vertical_buttons=self.embedded,
            restart_wp_slot=self.system_manager.confirm_restart_wireplumber,
            restart_pw_slot=self.system_manager.confirm_restart_pipewire
        )
        self.restart_wireplumber_button = restart_group.restart_wp_button
        self.restart_pipewire_button = restart_group.restart_pw_button

        # Layout arrangement depends on embedded mode
        if self.embedded:
            # Splitter layout: cable content (left) + spacer/settings panel (right)
            self.embedded_splitter = QSplitter(Qt.Orientation.Horizontal)
            
            # Create cable content column
            cable_column = QWidget()
            cable_column.setMinimumWidth(50)
            cable_layout = QVBoxLayout(cable_column)
            cable_layout.setContentsMargins(0, 0, 0, 0)
            cable_layout.addWidget(quantum_group)
            cable_layout.addWidget(sample_rate_group)
            cable_layout.addWidget(profile_group)
            cable_layout.addWidget(latency_group)
            cable_layout.addWidget(restart_group)
            cable_layout.addStretch()
            
            self.embedded_splitter.addWidget(cable_column)
            
            # Add empty spacer widget (visible when settings hidden)
            self.embedded_spacer = QWidget()
            self.embedded_splitter.addWidget(self.embedded_spacer)
            
            # Create settings panel (hidden by default, will replace spacer when shown)
            self.embedded_settings_panel = EmbeddedSettingsPanel(self)
            self.embedded_settings_panel.setVisible(False)
            self.embedded_splitter.addWidget(self.embedded_settings_panel)
            
            # Configure splitter
            self.embedded_splitter.setCollapsible(0, False)
            self.embedded_splitter.setHandleWidth(6)
            self.embedded_splitter.setStyleSheet("QSplitter::handle { background: transparent; }")
            self.embedded_splitter.splitterMoved.connect(self._save_embedded_splitter_position)
            
            # Mark for restore after first show
            self._embedded_splitter_restored = False
            
            main_layout.addWidget(self.embedded_splitter)
        else:
            # Original vertical layout for standalone mode
            main_layout.addWidget(quantum_group)
            main_layout.addWidget(sample_rate_group)
            main_layout.addWidget(profile_group)
            main_layout.addWidget(latency_group)
            main_layout.addWidget(restart_group)



        #Connections button
        self.cables_button = QPushButton("Cables")
        self.cables_button.clicked.connect(self.process_manager.open_cables)
        main_layout.addWidget(self.cables_button)

        self.setLayout(main_layout)
        self.setWindowTitle('Cable')

        if not self.embedded:
            self._restore_window_geometry()

        self._apply_nodes()
        self._apply_devices()
        # Note: Signal connections for device/node/quantum/sample_rate are now handled by the managers
        # after they are initialized in _init_focused_managers()


        # Initialize the checkboxes (they will be added to version context menu)
        self.tray_toggle_checkbox = QCheckBox("Enable tray icon")
        self.tray_toggle_checkbox.setChecked(False)
        self.tray_toggle_checkbox.stateChanged.connect(self.tray_manager.toggle_tray_icon) # Use tray_manager

        self.remember_settings_checkbox = QCheckBox("Save buffer and sample rate")
        self.remember_settings_checkbox.setChecked(False)
        self.remember_settings_checkbox.stateChanged.connect(self._handle_toggle_remember_settings)

        # New checkbox for restoring only when auto-started
        self.restore_only_minimized_checkbox = QCheckBox("Restore above only when app is auto-started")
        self.restore_only_minimized_checkbox.setChecked(False)
        self.restore_only_minimized_checkbox.setEnabled(False) # Initially disabled
        self.restore_only_minimized_checkbox.stateChanged.connect(self._handle_toggle_restore_only_minimized)

        # Add Settings button at the bottom right
        version_layout = QHBoxLayout()
        version_layout.addStretch() # Push button to the right
        self.settings_button = QPushButton("Settings")
        self.settings_button.setToolTip("Click to access Settings")
        
        # In embedded mode, toggle inline settings panel; otherwise show popup menu
        if self.embedded:
            self.settings_button.clicked.connect(self._toggle_embedded_settings)
        else:
            self.settings_button.clicked.connect(lambda: self.tray_manager.show_version_context_menu(self.settings_button.rect().bottomLeft()))
        
        version_layout.addWidget(self.settings_button)
        main_layout.addLayout(version_layout) # Add to the main layout

        # Apply embedded mode UI modifications
        self._apply_embedded_mode_ui()
        
        # Initialize focused managers with created widgets
        self._init_focused_managers()
    
    def _init_focused_managers(self) -> None:
        """Initialize focused manager classes for decomposed functionality."""
        # Initialize DSPMonitor for DSP load and XRUN tracking
        self.dsp_monitor = DSPMonitor(
            parent=self,
            dsp_load_value=self.dsp_load_value,
            dsp_load_bar=self.dsp_load_bar,
            xrun_display_value=self.xrun_display_value
        )
        self.dsp_monitor.initialize_jack_connection()
        self.dsp_monitor.start_monitoring()
        
        # Initialize DeviceManager for device/profile management
        self.device_manager = DeviceManager(
            parent=self,
            pipewire_manager=self.pipewire_manager,
            async_runner=self.async_runner,
            device_combo=self.device_combo,
            profile_combo=self.profile_combo
        )
        
        # Initialize LatencyManager for latency offset management
        self.latency_manager = LatencyManager(
            parent=self,
            pipewire_manager=self.pipewire_manager,
            async_runner=self.async_runner,
            node_combo=self.node_combo,
            latency_input=self.latency_input,
            nanoseconds_checkbox=self.nanoseconds_checkbox
        )
        
        # Initialize QuantumManager for quantum/sample rate settings
        self.quantum_manager = QuantumManager(
            parent=self,
            config_manager=self.config_manager,
            pipewire_manager=self.pipewire_manager,
            quantum_combo=self.quantum_combo,
            sample_rate_combo=self.sample_rate_combo,
            latency_display_callback=self.update_latency_display
        )

    def _apply_embedded_mode_ui(self) -> None:
        """Hide UI elements that shouldn't appear when embedded in Cables window."""
        if not self.embedded:
            # When not embedded, check if integrated mode is enabled and hide Cables button
            integrated = self.config_manager.get_bool(keys.INTEGRATE_CABLE_AND_CABLES, False)
            if integrated:
                self.cables_button.hide()
            return
        
        # In embedded mode, hide elements that would be redundant or problematic
        self.cables_button.hide()
        self.tray_toggle_checkbox.hide()

    def _toggle_embedded_settings(self) -> None:
        """Toggle visibility of the embedded settings panel."""
        # embedded_settings_panel and embedded_splitter only exist in embedded mode
        if hasattr(self, 'embedded_settings_panel') and hasattr(self, 'embedded_splitter'):
            is_visible = self.embedded_settings_panel.isVisible()
            
            # Preserve the left column width
            sizes = self.embedded_splitter.sizes()
            left_width = sizes[0]
            total_width = self.embedded_splitter.width()
            remaining = max(0, total_width - left_width)
            
            if is_visible:
                # Hiding settings, show spacer
                self.embedded_settings_panel.setVisible(False)
                self.embedded_spacer.setVisible(True)
                self.embedded_splitter.setSizes([left_width, remaining, 0])
                self.config_manager.set_bool_setting(keys.EMBEDDED_SETTINGS_VISIBLE, False)
            else:
                # Showing settings, hide spacer
                self.embedded_spacer.setVisible(False)
                self.embedded_settings_panel.setVisible(True)
                self.embedded_settings_panel.refresh_settings()
                self.embedded_splitter.setSizes([left_width, 0, remaining])
                self.config_manager.set_bool_setting(keys.EMBEDDED_SETTINGS_VISIBLE, True)

    def _save_embedded_splitter_position(self, pos: int, index: int) -> None:
        """Save the embedded splitter position to config with debounce."""
        # embedded_splitter only exists in embedded mode
        if hasattr(self, 'embedded_splitter'):
            sizes = self.embedded_splitter.sizes()
            if sizes[0] > 0:
                self._pending_splitter_pos = sizes[0]
                self._splitter_save_timer.start()

    def _perform_save_embedded_splitter_position(self) -> None:
        """Actually save the splitter position to config."""
        if self._pending_splitter_pos is not None:
            self.config_manager.set_int_setting(keys.EMBEDDED_COLUMN_WIDTH, self._pending_splitter_pos)
            self.config_manager.flush()

    def showEvent(self, event: QEvent) -> None:
        """Handle show event to restore splitter size after widget is visible."""
        super().showEvent(event)
        if self.embedded and hasattr(self, '_embedded_splitter_restored') and not self._embedded_splitter_restored:
            self._embedded_splitter_restored = True
            QTimer.singleShot(0, self._restore_embedded_splitter_size)

    def _restore_embedded_splitter_size(self) -> None:
        """Restore the embedded splitter size and settings panel visibility from config."""
        if hasattr(self, 'embedded_splitter'):
            saved_width = self.config_manager.get_int_setting(keys.EMBEDDED_COLUMN_WIDTH, 350)
            total_width = self.embedded_splitter.width()
            remaining = max(0, total_width - saved_width)
            
            settings_was_visible = self.config_manager.get_bool_setting(keys.EMBEDDED_SETTINGS_VISIBLE, False)
            if settings_was_visible:
                self.embedded_spacer.setVisible(False)
                self.embedded_settings_panel.setVisible(True)
                self.embedded_settings_panel.refresh_settings()
                self.embedded_splitter.setSizes([saved_width, 0, remaining])
            else:
                self.embedded_splitter.setSizes([saved_width, remaining, 0])

    def _restore_window_geometry(self) -> None:
        """Restore saved window geometry, or apply first-launch defaults."""
        saved = self.config_manager.get_str_setting(keys.MAIN_WINDOW_GEOMETRY, "")
        if saved:
            from PyQt6.QtCore import QByteArray
            import base64
            self.restoreGeometry(QByteArray(base64.b64decode(saved)))
        else:
            self.resize(app_config.MAIN_WINDOW_INITIAL_WIDTH,
                        app_config.MAIN_WINDOW_INITIAL_HEIGHT)

    def _save_window_geometry(self) -> None:
        """Persist current window geometry to config."""
        import base64
        data = base64.b64encode(bytes(self.saveGeometry())).decode('ascii')
        self.config_manager.set_str_setting(keys.MAIN_WINDOW_GEOMETRY, data)

    def closeEvent(self, event: QEvent) -> None:
        if not self.embedded:
            self._save_window_geometry()
        # If tray is enabled, hide the window instead of closing
        if self.tray_enabled and self.tray_manager.tray_icon and self.tray_manager.tray_icon.isVisible():
            event.ignore()
            self.hide()
        else:
            # If not hiding to tray, quit the application properly via tray manager
            self.tray_manager.quit_app()
            event.accept()

    def update_version_display(self) -> None:
        """Updates the Settings button highlighting if a new version is available."""
        if self.update_manager.update_available:
            self.settings_button.setStyleSheet("color: orange; font-weight: bold;")
            self.settings_button.setToolTip(f"New version available: {self.update_manager.latest_version}")
        else:
            self.settings_button.setStyleSheet("")
            self.settings_button.setToolTip("Click to access Settings")
        if hasattr(self, 'embedded_settings_panel'):
            self.embedded_settings_panel._update_version_label()


    def update_latency_display(self) -> None:
        if self.quantum_manager is not None:
            latency_ms = self.quantum_manager.calculate_latency_ms()
            if latency_ms is not None:
                self.latency_display_value.setText(f"{latency_ms:.2f} ms")
            else:
                self.latency_display_value.setText("N/A")
        else:
            self.latency_display_value.setText("N/A")





    def _handle_reset_all_latency_and_refresh(self) -> None:
        """Reset latency for all nodes and refresh settings."""
        logger.debug("Resetting all latency and refreshing settings...")
        if self.latency_manager is not None:
            node_ids = self.latency_manager.get_all_node_ids()
            self.latency_manager.reset_all_latency(node_ids, self.refresh_all_settings)
        logger.debug("Finished resetting latency and refreshing.")

    def refresh_all_settings(self) -> None:
        """Refresh all settings from PipeWire and config."""
        logger.debug("Refreshing all settings...")

        self._apply_devices()
        self._apply_nodes()

        if self.quantum_manager is not None:
            self.quantum_manager.populate_dropdowns()

        self._apply_current_settings()
        self.update_latency_display()
        logger.debug("Finished refreshing all settings.")


    def _apply_current_settings(self, force_reset_quantum: bool = False, force_reset_sample_rate: bool = False) -> None:
        self._pending_force_reset_quantum = force_reset_quantum
        self._pending_force_reset_sample_rate = force_reset_sample_rate
        self.async_runner.run(
            self.pipewire_manager.get_current_settings,
            self._on_current_settings_loaded
        )

    def _on_current_settings_loaded(self, settings: Dict[str, Any]) -> None:
        """Handle async settings loading completion."""
        if self.quantum_manager is not None:
            self.quantum_manager.apply_loaded_settings(settings)

    def _apply_devices(self) -> None:
        """Load available audio devices."""
        if self.device_manager is not None:
            self.device_manager.load_devices()

    def _apply_nodes(self) -> None:
        """Load available audio nodes."""
        if self.latency_manager is not None:
            self.latency_manager.load_nodes()

    def _apply_profiles(self) -> None:
        """Load profiles for selected device."""
        if self.device_manager is not None:
            self.device_manager._load_profiles()

    def _apply_latency_offset(self, node_id: str) -> None:
        """Load latency offset for a node."""
        if self.latency_manager is not None:
            self.latency_manager._load_latency_offset(node_id)

    def _handle_apply_latency(self) -> None:
        """Apply latency settings."""
        if self.latency_manager is not None:
            self.latency_manager.apply_latency()

    def _handle_apply_profile(self) -> None:
        """Apply profile settings."""
        if self.device_manager is not None:
            self.device_manager.apply_profile()

    def apply_quantum_settings(self, skip_save: bool = False) -> None:
        """Apply quantum settings."""
        if self.quantum_manager is not None:
            self.quantum_manager.initial_load = self.initial_load
            self.quantum_manager.apply_quantum_settings(
                skip_save=skip_save,
                remember_settings=self.remember_settings_checkbox.isChecked()
            )

    def apply_sample_rate_settings(self, skip_save: bool = False) -> None:
        """Apply sample rate settings."""
        if self.quantum_manager is not None:
            self.quantum_manager.initial_load = self.initial_load
            self.quantum_manager.apply_sample_rate_settings(
                skip_save=skip_save,
                remember_settings=self.remember_settings_checkbox.isChecked()
            )

    def _handle_reset_quantum(self) -> None:
        """Reset quantum to default."""
        if self.quantum_manager is not None:
            if self.quantum_manager.reset_quantum():
                self._apply_current_settings(force_reset_quantum=True)

    def _handle_reset_sample_rate(self) -> None:
        """Reset sample rate to default."""
        if self.quantum_manager is not None:
            if self.quantum_manager.reset_sample_rate():
                self._apply_current_settings(force_reset_sample_rate=True)

    def _get_settings_dict(self) -> Dict[str, Any]:
        """Build a settings dict from current app state for save_settings."""
        return {
            'tray_enabled': self.tray_toggle_checkbox.isChecked(),
            'tray_click_opens_cables': self.tray_click_opens_cables,
            'remember_settings': self.remember_settings,
            'restore_only_minimized': self.restore_only_minimized,
            'autostart_enabled': self.autostart_enabled,
            'check_updates_at_start': self.check_updates_at_start,
            'appimage_path': self.appimage_path,
        }

    def _apply_loaded_settings(self, settings: Dict[str, Any]) -> None:
        """Apply loaded settings dict to app state and widgets."""
        self.remember_settings = settings["remember_settings"]
        self.restore_only_minimized = settings["restore_only_minimized"]
        self.saved_quantum = settings["saved_quantum"]
        self.saved_sample_rate = settings["saved_sample_rate"]
        self.autostart_enabled = settings["autostart_enabled"]
        self.check_updates_at_start = settings["check_updates_at_start"]
        self.appimage_path = settings["appimage_path"]
        self.tray_click_opens_cables = settings["tray_click_opens_cables"]

        # Sync quantum_manager reset state if available
        if self.quantum_manager is not None:
            if settings["has_saved_quantum"]:
                self.quantum_manager.quantum_was_reset = False
            if settings["has_saved_sample_rate"]:
                self.quantum_manager.sample_rate_was_reset = False

        # Sync autostart file with config
        if self.autostart_enabled != self.autostart_manager.is_autostart_enabled():
            if self.autostart_enabled:
                self.autostart_manager.enable_autostart()
            else:
                self.autostart_manager.disable_autostart()

        # Set checkbox states
        tray_enabled = settings["tray_enabled"]
        self.tray_toggle_checkbox.setChecked(tray_enabled)

        self.remember_settings_checkbox.blockSignals(True)
        self.remember_settings_checkbox.setChecked(self.remember_settings)
        self.remember_settings_checkbox.blockSignals(False)

        self.restore_only_minimized_checkbox.blockSignals(True)
        self.restore_only_minimized_checkbox.setChecked(self.restore_only_minimized)
        self.restore_only_minimized_checkbox.setEnabled(self.remember_settings)
        self.restore_only_minimized_checkbox.blockSignals(False)

        if tray_enabled:
            if self.tray_manager.tray_icon:
                self.tray_manager.tray_icon.hide()
                self.tray_manager.tray_icon = None
            self.tray_manager.toggle_tray_icon(Qt.CheckState.Checked)

        # Block signals while potentially setting combo indices during load
        self.quantum_combo.blockSignals(True)
        self.sample_rate_combo.blockSignals(True)

        # Apply saved audio settings if enabled AND the conditions for restoring are met
        should_restore = self.remember_settings and (
            not self.restore_only_minimized or
            (self.restore_only_minimized and self.is_minimized_startup)
        )

        if should_restore:
            try:
                if self.saved_quantum > 0:
                    quantum_str = str(self.saved_quantum)
                    logger.info(f"Applying saved quantum: {quantum_str}")
                    if self.quantum_manager is not None:
                        self.quantum_manager._set_combo_to_value(self.quantum_combo, quantum_str, 'last_valid_quantum_index')
                    self.apply_quantum_settings(skip_save=True)

                if self.saved_sample_rate > 0:
                    sample_rate_str = str(self.saved_sample_rate)
                    logger.info(f"Applying saved sample rate: {sample_rate_str}")
                    if self.quantum_manager is not None:
                        self.quantum_manager._set_combo_to_value(self.sample_rate_combo, sample_rate_str, 'last_valid_sample_rate_index')
                    self.apply_sample_rate_settings(skip_save=True)
            except Exception as e:
                logger.error(f"Error applying saved audio settings: {e}")
        else:
             # Sync indices from combo boxes to quantum_manager
             if self.quantum_manager is not None:
                 current_quantum_index = self.quantum_combo.currentIndex()
                 if current_quantum_index >= 0 and self.quantum_combo.itemText(current_quantum_index) != "Edit List...":
                     self.quantum_manager.last_valid_quantum_index = current_quantum_index
                 elif self.quantum_combo.count() > 1:
                     self.quantum_manager.last_valid_quantum_index = 0
                     self.quantum_combo.setCurrentIndex(0)

                 current_sample_rate_index = self.sample_rate_combo.currentIndex()
                 if current_sample_rate_index >= 0 and self.sample_rate_combo.itemText(current_sample_rate_index) != "Edit List...":
                     self.quantum_manager.last_valid_sample_rate_index = current_sample_rate_index
                 elif self.sample_rate_combo.count() > 1:
                     self.quantum_manager.last_valid_sample_rate_index = 0
                     self.sample_rate_combo.setCurrentIndex(0)

        # Unblock signals after potentially setting indices
        self.quantum_combo.blockSignals(False)
        self.sample_rate_combo.blockSignals(False)

        self.update_latency_display()

    def reload_after_service_restart(self) -> None:
        """Reload settings after a PipeWire/WirePlumber restart."""
        # Reset device and node selections
        if self.device_manager is not None:
            self.device_manager.reset_selection()
        
        if self.latency_manager is not None:
            self.latency_manager.clear()

        if self.remember_settings:
            try:
                cm = self.config_manager
                saved_quantum = cm.get_str_setting(keys.SAVED_QUANTUM, '')
                saved_sample_rate = cm.get_str_setting(keys.SAVED_SAMPLE_RATE, '')

                if saved_quantum or saved_sample_rate:
                    self.quantum_combo.blockSignals(True)
                    self.sample_rate_combo.blockSignals(True)
                    try:
                        if saved_quantum:
                            if self.quantum_manager is not None:
                                self.quantum_manager._set_combo_to_value(self.quantum_combo, saved_quantum, 'last_valid_quantum_index')
                            self.apply_quantum_settings(skip_save=True)

                        if saved_sample_rate:
                            if self.quantum_manager is not None:
                                self.quantum_manager._set_combo_to_value(self.sample_rate_combo, saved_sample_rate, 'last_valid_sample_rate_index')
                            self.apply_sample_rate_settings(skip_save=True)
                    finally:
                        self.quantum_combo.blockSignals(False)
                        self.sample_rate_combo.blockSignals(False)
                        self.update_latency_display()

            except Exception as e:
                logger.error(f"Error restoring saved settings during reload: {e}")

    def _handle_toggle_remember_settings(self, state: int) -> None:
        """Handle remember settings checkbox state changes."""
        remember = bool(state)
        self.remember_settings = remember

        self.restore_only_minimized_checkbox.setEnabled(remember)

        current_quantum = self.quantum_combo.currentText()
        current_sample_rate = self.sample_rate_combo.currentText()

        # Get reset states from quantum_manager
        quantum_was_reset = self.quantum_manager.quantum_was_reset if self.quantum_manager else False
        sample_rate_was_reset = self.quantum_manager.sample_rate_was_reset if self.quantum_manager else False

        result = self.config_manager.toggle_remember_settings(
            remember=remember,
            current_quantum=current_quantum,
            current_sample_rate=current_sample_rate,
            quantum_was_reset=quantum_was_reset,
            sample_rate_was_reset=sample_rate_was_reset,
            tray_enabled=self.tray_toggle_checkbox.isChecked(),
            tray_click_opens_cables=self.tray_click_opens_cables
        )

        if result.get("clear_restore_only_minimized"):
            self.restore_only_minimized_checkbox.setChecked(False)
            self.restore_only_minimized = False

    def _handle_toggle_restore_only_minimized(self, state: int) -> None:
        """Handle restore only when auto-started checkbox state changes."""
        self.restore_only_minimized = bool(state)
        self.config_manager.toggle_restore_only_minimized(self.restore_only_minimized)

    def changeEvent(self, event: QEvent) -> None:
        """Handle window state changes, refresh settings when gaining focus."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            # Refresh pipewire settings when window gains focus (non-embedded mode only)
            if not self.embedded and self.values_initialized:
                self._apply_current_settings()
                self._apply_devices()
                self._apply_nodes()
                self.update_latency_display()

    def set_tray_checkbox(self, checked: bool) -> None:
        self.tray_toggle_checkbox.setChecked(checked)

    def revert_tray_checkbox(self) -> None:
        self.tray_toggle_checkbox.blockSignals(True)
        self.tray_toggle_checkbox.setChecked(True)
        self.tray_toggle_checkbox.blockSignals(False)

    def set_tray_checkbox_enabled(self, enabled: bool) -> None:
        self.tray_toggle_checkbox.setEnabled(enabled)

    def is_tray_checked(self) -> bool:
        return self.tray_toggle_checkbox.isChecked()

    def is_remember_settings_checked(self) -> bool:
        return self.remember_settings_checkbox.isChecked()

    def set_remember_settings_checked(self, checked: bool) -> None:
        self.remember_settings_checkbox.setChecked(checked)

    def is_restore_only_minimized_checked(self) -> bool:
        return self.restore_only_minimized_checkbox.isChecked()

    def set_restore_only_minimized_checked(self, checked: bool) -> None:
        self.restore_only_minimized_checkbox.setChecked(checked)

    def get_settings_button_global_pos(self, local_pos: Any) -> Any:
        return self.settings_button.mapToGlobal(local_pos)

    def cleanup_before_quit(self) -> None:
        """Clean up resources before quitting."""
        logger.debug("Performing cleanup before quitting...")
        # First, shutdown async workers to prevent signals on deleted QObjects
        if hasattr(self, 'async_runner') and self.async_runner:
            self.async_runner.shutdown(wait_ms=500)
        # Clean up DSPMonitor
        if self.dsp_monitor is not None:
            self.dsp_monitor.cleanup()
        # Close JackService before Qt tears down QObjects to stop JACK callbacks
        try:
            get_jack_service().close()
        except Exception:
            pass
        # Stop the daemon directly
        preset_manager = PresetManager()
        preset_manager.stop_daemon_mode()
        # Flush config to disk
        if hasattr(self, 'config_manager') and self.config_manager:
            self.config_manager.flush()

def _check_integrated_mode() -> bool:
    """Check if integrated mode is enabled by reading config directly."""
    config_path = os.path.expanduser("~/.config/cable/config.ini")
    if os.path.exists(config_path):
        try:
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            return config.getboolean('DEFAULT', 'integrate_cable_and_cables', fallback=False)
        except (configparser.Error, ValueError):
            pass
    return False

def _find_connection_manager() -> Optional[str]:
    """Find connection-manager.py in various possible locations."""
    # Possible locations to search
    search_paths = [
        # Same directory as this script (development mode)
        os.path.dirname(os.path.abspath(__file__)),
        # System-wide installation locations
        '/usr/share/cable',
        '/usr/local/share/cable',
        # Flatpak locations
        '/app/bin',  # Flatpak installs to /app/bin
        '/app/share/cable',
        # User local installation
        os.path.expanduser('~/.local/share/cable'),
        os.path.expanduser('~/.local/bin'),
    ]
    
    # Also check directories in sys.path (for pip-installed packages)
    for sys_path in sys.path:
        if sys_path and os.path.isdir(sys_path):
            search_paths.append(sys_path)
    
    for path in search_paths:
        candidate = os.path.join(path, 'connection-manager.py')
        if os.path.exists(candidate):
            return candidate
    
    # Also try using shutil.which to find it in PATH
    result = shutil.which('connection-manager.py')
    if result:
        return result
    
    return None

def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Cable - PipeWire Settings Manager')
    parser.add_argument('--minimized', action='store_true',
                      help='Start application minimized to tray')
    args = parser.parse_args(sys.argv[1:])  # Skip the first argument (script name)
    
    # Check if integrated mode is enabled - if so, launch connection-manager.py instead
    if _check_integrated_mode():
        logger.info("Integrated mode enabled, launching Cables (connection-manager.py) instead...")
        # Find the connection-manager.py script
        connection_manager_path = _find_connection_manager()
        
        if connection_manager_path:
            logger.info(f"Found connection-manager.py at: {connection_manager_path}")
            # Replace current process with connection-manager.py
            os.execv(sys.executable, [sys.executable, connection_manager_path] + sys.argv[1:])
        else:
            logger.warning("connection-manager.py not found in any known location")
            logger.warning(f"Searched in: {os.path.dirname(os.path.abspath(__file__))}, /usr/share/cable, /app/bin, etc.")
            logger.warning("Falling back to standalone Cable mode.")
    
    # Create application instance
    app = CableApp(sys.argv)
    
    # Create main window, passing the minimized flag
    ex = PipeWireSettingsApp(is_minimized_startup=args.minimized)

    # Connect the cleanup function to the application's quit signal
    app.aboutToQuit.connect(ex.cleanup_before_quit)

    # Set up a signal handler for SIGINT (Ctrl+C) to gracefully quit
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # Use a timer to allow the Python interpreter to process signals
    timer = QTimer()
    timer.start(100)  # Check for signals every 100ms
    timer.timeout.connect(lambda: None)  # No-op to wake up the interpreter
    
    # Handle initial window state
    if args.minimized:
        # Ensure tray is enabled when starting minimized
        if not ex.tray_enabled:
            ex.tray_toggle_checkbox.setChecked(True)
            ex.tray_manager.toggle_tray_icon(Qt.CheckState.Checked) # Use tray_manager
        # Start hidden
        ex.hide()
        # Force a complete refresh of settings after a short delay
        # This simulates clicking the "Refresh" button when starting minimized
        # Also launch connection manager to load startup preset if configured
        logger.info("Cable started minimized, launching connection manager...")
        ex.process_manager.launch_connection_manager(headless=True) # Pass headless=True when Cable starts minimized
        # _apply_current_settings is already called in __init__
    else:
        # Show window normally
        ex.show()
    
    # Run the application and exit
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
