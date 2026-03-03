from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QLineEdit, QPushButton, QCheckBox, 
                             QProgressBar, QSizePolicy, QWidget)
from PyQt6.QtCore import Qt, QMargins
from cable_core.app_config import EDIT_LIST_TEXT
from typing import List, Callable, Any, Optional
from cable_core.config import ConfigManager

def create_section_group(title: str, layout: QVBoxLayout) -> QGroupBox:
    group = QGroupBox()
    group.setLayout(layout)
    group.setContentsMargins(QMargins(5, 10, 5, 10))

    from PyQt6.QtGui import QFont
    title_font = QFont()
    title_font.setBold(True)
    title_font.setPointSize(title_font.pointSize() + 1)

    title_label = QLabel(title)
    title_label.setFont(title_font)
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    layout.insertWidget(0, title_label)
    return group

class BaseAudioSettingGroup(QGroupBox):
    def __init__(self, title: str, config_manager: ConfigManager, default_values_key: str, 
                 default_values_list: List[int], vertical_buttons: bool, 
                 apply_slot: Callable, reset_slot: Callable, refresh_slot: Callable, 
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.combo_box = QComboBox()
        self.apply_button = QPushButton()
        self.reset_button = QPushButton()
        self.refresh_button = QPushButton()
        
        layout = QVBoxLayout()
        select_layout = QHBoxLayout()
        label = QLabel(f"{title}:")
        self.combo_box.setEditable(True)
        
        values = config_manager.get_list_from_config(default_values_key, default_values_list)
        for value in values:
            self.combo_box.addItem(str(value))
        self.combo_box.addItem(EDIT_LIST_TEXT)
        edit_item_index = self.combo_box.count() - 1
        self.combo_box.setItemData(edit_item_index, "Select, then press Enter to edit list", Qt.ItemDataRole.ToolTipRole)
        select_layout.addWidget(label)
        select_layout.addWidget(self.combo_box)
        layout.addLayout(select_layout)

        if vertical_buttons:
            buttons_layout = QVBoxLayout()
        else:
            buttons_layout = QHBoxLayout()
            
        self.apply_button.setText(f"Apply {title}")
        self.apply_button.clicked.connect(apply_slot)
        buttons_layout.addWidget(self.apply_button)
        self.combo_box.lineEdit().returnPressed.connect(apply_slot)

        self.reset_button.setText(f"Reset {title}")
        self.reset_button.clicked.connect(reset_slot)
        buttons_layout.addWidget(self.reset_button)

        self.refresh_button.setText("Refresh")
        self.refresh_button.clicked.connect(refresh_slot)
        self.refresh_button.setToolTip(f"Refreshes {title.lower()}, as well as the other audio setting, audio devices, nodes, and dropdown lists")
        buttons_layout.addWidget(self.refresh_button)

        layout.addLayout(buttons_layout)
        
        self.main_layout = layout
        
        # Apply style from create_section_group
        self.setLayout(layout)
        self.setContentsMargins(QMargins(5, 10, 5, 10))
        from PyQt6.QtGui import QFont
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label = QLabel(title)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.insertWidget(0, title_label)

class QuantumGroup(BaseAudioSettingGroup):
    def __init__(self, config_manager: ConfigManager, default_values_list: List[int], vertical_buttons: bool,
                 apply_slot: Callable, reset_slot: Callable, refresh_slot: Callable, 
                 reset_xrun_slot: Callable, parent: Optional[QWidget] = None) -> None:
        super().__init__("Quantum", config_manager, "quantum_values", default_values_list, 
                         vertical_buttons, apply_slot, reset_slot, refresh_slot, parent)
        
        self.reset_button.setToolTip("Restores default quantum/buffer")
        
        # Additional UI for Quantum
        latency_display_layout = QHBoxLayout()
        self.latency_display_label = QLabel("Latency:")
        self.latency_display_value = QLabel("0.00 ms")
        
        self.xrun_display_label = QLabel("Xruns:")
        self.xrun_display_label.setToolTip("Click to reset xrun count")
        self.xrun_display_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.xrun_display_label.mousePressEvent = reset_xrun_slot
        self.xrun_display_value = QLabel("0")
        self.xrun_display_value.setToolTip("Click to reset xrun count")
        self.xrun_display_value.setCursor(Qt.CursorShape.PointingHandCursor)
        self.xrun_display_value.mousePressEvent = reset_xrun_slot
        
        self.dsp_load_label = QLabel("DSP load:")
        self.dsp_load_value = QLabel("0%")
        self.dsp_load_value.setMinimumWidth(35)
        self.dsp_load_bar = QProgressBar()
        self.dsp_load_bar.setRange(0, 100)
        self.dsp_load_bar.setValue(0)
        self.dsp_load_bar.setTextVisible(False)
        self.dsp_load_bar.setFixedSize(60, 12)
        
        latency_display_layout.addStretch()
        latency_display_layout.addWidget(self.latency_display_label)
        latency_display_layout.addWidget(self.latency_display_value)
        latency_display_layout.addSpacing(15)
        latency_display_layout.addWidget(self.xrun_display_label)
        latency_display_layout.addWidget(self.xrun_display_value)
        latency_display_layout.addSpacing(15)
        latency_display_layout.addWidget(self.dsp_load_label)
        latency_display_layout.addWidget(self.dsp_load_value)
        latency_display_layout.addWidget(self.dsp_load_bar)
        
        self.main_layout.addLayout(latency_display_layout)

class SampleRateGroup(BaseAudioSettingGroup):
    def __init__(self, config_manager: ConfigManager, default_values_list: List[int], vertical_buttons: bool,
                 apply_slot: Callable, reset_slot: Callable, refresh_slot: Callable,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("Sample Rate", config_manager, "sample_rate_values", default_values_list, 
                         vertical_buttons, apply_slot, reset_slot, refresh_slot, parent)
        self.reset_button.setToolTip("Restores default sample rate")

class AudioProfileGroup(QGroupBox):
    def __init__(self, apply_slot: Callable, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        layout = QVBoxLayout()
        device_layout = QHBoxLayout()
        device_label = QLabel("Audio Device:")
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        layout.addLayout(device_layout)
        
        profile_select_layout = QHBoxLayout()
        profile_label = QLabel("Device Profile:")
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        profile_select_layout.addWidget(profile_label)
        profile_select_layout.addWidget(self.profile_combo)
        layout.addLayout(profile_select_layout)
        
        device_label.setFixedWidth(device_label.sizeHint().width())
        profile_label.setFixedWidth(device_label.width())
        
        self.apply_button = QPushButton("Apply Profile")
        self.apply_button.clicked.connect(apply_slot)
        layout.addWidget(self.apply_button)
        
        # Apply group style
        self.setLayout(layout)
        self.setContentsMargins(QMargins(5, 10, 5, 10))
        from PyQt6.QtGui import QFont
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label = QLabel("Audio Profile")
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.insertWidget(0, title_label)

class LatencyGroup(QGroupBox):
    def __init__(self, vertical_buttons: bool, apply_slot: Callable, reset_all_slot: Callable,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout()
        
        node_select_layout = QHBoxLayout()
        node_label = QLabel("Audio Node:")
        self.node_combo = QComboBox()
        self.node_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.node_combo.addItem("Choose Node")
        node_select_layout.addWidget(node_label)
        node_select_layout.addWidget(self.node_combo)
        layout.addLayout(node_select_layout)
        
        latency_input_layout = QHBoxLayout()
        latency_label = QLabel("Latency Offset (default in samples):")
        self.latency_input = QLineEdit()
        self.nanoseconds_checkbox = QCheckBox("nanoseconds")
        latency_input_layout.addWidget(latency_label)
        latency_input_layout.addWidget(self.latency_input)
        latency_input_layout.addWidget(self.nanoseconds_checkbox)
        layout.addLayout(latency_input_layout)
        
        self.apply_button = QPushButton("Apply Latency")
        self.apply_button.clicked.connect(apply_slot)
        
        if vertical_buttons:
            buttons_layout = QVBoxLayout()
        else:
            buttons_layout = QHBoxLayout()
            
        buttons_layout.addWidget(self.apply_button)
        self.reset_all_button = QPushButton("Reset All Latency")
        self.reset_all_button.clicked.connect(reset_all_slot)
        self.reset_all_button.setToolTip("Sets latency to '0' for all nodes")
        buttons_layout.addWidget(self.reset_all_button)
        
        layout.addLayout(buttons_layout)
        self.latency_input.returnPressed.connect(apply_slot)
        
        # Apply group style
        self.setLayout(layout)
        self.setContentsMargins(QMargins(5, 10, 5, 10))
        from PyQt6.QtGui import QFont
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label = QLabel("Latency Offset")
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.insertWidget(0, title_label)

class RestartGroup(QGroupBox):
    def __init__(self, vertical_buttons: bool, restart_wp_slot: Callable, restart_pw_slot: Callable,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout()
        
        if vertical_buttons:
            buttons_layout = QVBoxLayout()
        else:
            buttons_layout = QHBoxLayout()

        def set_style(btn: QPushButton) -> None:
            btn.setStyleSheet("QPushButton { color: red; font-weight: bold; }")
            
        self.restart_wp_button = QPushButton("Restart Wireplumber")
        self.restart_wp_button.clicked.connect(restart_wp_slot)
        set_style(self.restart_wp_button)
        buttons_layout.addWidget(self.restart_wp_button)
        
        self.restart_pw_button = QPushButton("Restart Pipewire")
        self.restart_pw_button.clicked.connect(restart_pw_slot)
        set_style(self.restart_pw_button)
        buttons_layout.addWidget(self.restart_pw_button)
        
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
        self.setContentsMargins(QMargins(5, 10, 5, 10))
        from PyQt6.QtGui import QFont
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label = QLabel("Restart Services")
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.insertWidget(0, title_label)
