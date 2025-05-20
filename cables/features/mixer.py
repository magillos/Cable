import sys
try:
    import alsaaudio
except ImportError:
    alsaaudio = None
import os 
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QComboBox, QLabel, QSlider, QCheckBox, QMessageBox, QScrollArea,
    QFrame, QPushButton
)
from PyQt6.QtCore import Qt, QTimer, QSize, QSocketNotifier
from PyQt6.QtGui import QFont, QAction, QKeySequence
from functools import partial

# --- Constants ---
_MIXER_CAP_PVOLUME_INT = 2
_MIXER_SWCAP_PLAYBACK_INT = 1
_MIXER_CAP_CVOLUME_INT = 1

_CAP_STRING_PLAYBACK_VOLUME = "Playback Volume"
_SWCAP_STRING_PLAYBACK_MUTE = "Playback Mute"
_CAP_STRING_GENERIC_VOLUME = "Volume"
_CAP_STRING_CAPTURE_VOLUME = "Capture Volume"

try: _MIXER_CAP_PVOLUME_INT = alsaaudio.MIXER_CAP_PVOLUME
except AttributeError: print(f"Warning: alsaaudio.MIXER_CAP_PVOLUME not found. Using default int value {_MIXER_CAP_PVOLUME_INT}.", file=sys.stderr)
try: _MIXER_SWCAP_PLAYBACK_INT = alsaaudio.MIXER_SWCAP_PLAYBACK
except AttributeError: print(f"Warning: alsaaudio.MIXER_SWCAP_PLAYBACK not found. Using default int value {_MIXER_SWCAP_PLAYBACK_INT}.", file=sys.stderr)
try: _MIXER_CAP_CVOLUME_INT = alsaaudio.MIXER_CAP_CVOLUME
except AttributeError: print(f"Warning: alsaaudio.MIXER_CAP_CVOLUME not found. Using default int value {_MIXER_CAP_CVOLUME_INT}.", file=sys.stderr)
# --- End Constants ---

class AlsMixerApp(QWidget):
    def __init__(self, config_manager=None):
        super().__init__()
        
        if alsaaudio is None:
            self.init_error_ui("ALSA wrappers for Python not available")
            return

        self._init_mixer_components(config_manager)

    def _init_mixer_components(self, config_manager):
        self.config_manager = config_manager
        self.current_card_index = -1
        self._is_updating_ui = False
        self.mixer_controls_data = {}
        self.mixer_notifiers = {}  
        self.fd_to_mixer = {}      
        self.debug_mode = False 
        
        self.current_font_size_multiplier = 1.0
        self.base_slider_height = 300
        self.base_mixer_group_min_width = 180
        self.base_mixer_group_spacing = 6
        self.base_mixer_group_margins = (8, 8, 8, 8) 
        self.base_control_sub_frame_margins = (5, 5, 5, 5)
        self.base_mixer_hbox_spacing = 15
        self.base_mixer_hbox_margins = (10, 5, 10, 5)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus) # Allow widget to receive focus for shortcuts

        self._load_zoom_level() 
 
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_all_mixer_states)
        # self.update_timer.start(500) # Start timer only if event detection is not possible
 
        self.init_ui()
        # self.populate_cards() # Populate cards only when updates are started
 
    # Zoom methods defined before init_ui uses them via connections
    def _load_zoom_level(self):
        if self.config_manager:
            try:
                multiplier_str = self.config_manager.get_str('alsa_mixer_zoom_level', '1.0')
                self.current_font_size_multiplier = float(multiplier_str)
            except ValueError:
                self.current_font_size_multiplier = 1.0
        else:
            self.current_font_size_multiplier = 1.0

    def _save_zoom_level(self):
        if self.config_manager:
            self.config_manager.set_str('alsa_mixer_zoom_level', str(self.current_font_size_multiplier))

    def _zoom_in(self):
        self.current_font_size_multiplier = round(min(2.0, self.current_font_size_multiplier + 0.04), 2)
        self._apply_zoom()
        self._save_zoom_level()

    def _zoom_out(self):
        self.current_font_size_multiplier = round(max(0.5, self.current_font_size_multiplier - 0.04), 2)
        self._apply_zoom()
        self._save_zoom_level()

    def _apply_zoom(self):
        multiplier = self.current_font_size_multiplier
        base_app_font_size = QApplication.font().pointSizeF()
        if base_app_font_size <= 0: base_app_font_size = 10 

        if self.mixer_hbox_layout:
            self.mixer_hbox_layout.setSpacing(int(self.base_mixer_hbox_spacing * multiplier))
            self.mixer_hbox_layout.setContentsMargins(
                int(self.base_mixer_hbox_margins[0] * multiplier),
                int(self.base_mixer_hbox_margins[1] * multiplier),
                int(self.base_mixer_hbox_margins[2] * multiplier),
                int(self.base_mixer_hbox_margins[3] * multiplier)
            )

        for i in range(self.mixer_hbox_layout.count()):
            item = self.mixer_hbox_layout.itemAt(i)
            if not item: continue
            widget = item.widget()

            if widget and isinstance(widget, QFrame) and widget.objectName() == "MixerGroupFrame":
                widget.setMinimumWidth(int(self.base_mixer_group_min_width * multiplier))
                group_layout = widget.layout()
                if group_layout and isinstance(group_layout, QVBoxLayout):
                    group_layout.setSpacing(int(self.base_mixer_group_spacing * multiplier))
                    group_layout.setContentsMargins(
                        int(self.base_mixer_group_margins[0] * multiplier),
                        int(self.base_mixer_group_margins[1] * multiplier),
                        int(self.base_mixer_group_margins[2] * multiplier),
                        int(self.base_mixer_group_margins[3] * multiplier)
                    )

                labels = widget.findChildren(QLabel)
                for label in labels:
                    original_font = label.font()
                    new_label_font = QFont(original_font)
                    font_scale_factor = 0.9 if "Mute" in label.text() or label.text().isdigit() or label.text() == "N/A" else 1.0
                    if "<b>" in label.text(): 
                        font_scale_factor = 1.1
                        new_label_font.setBold(True)
                    
                    new_label_font.setPointSizeF(base_app_font_size * multiplier * font_scale_factor)
                    label.setFont(new_label_font)

                checkboxes = widget.findChildren(QCheckBox)
                for checkbox in checkboxes:
                    cb_font = checkbox.font()
                    cb_font.setPointSizeF(base_app_font_size * multiplier * 0.9)
                    checkbox.setFont(cb_font)

                sliders = widget.findChildren(QSlider)
                for slider in sliders:
                    slider.setMinimumHeight(int(self.base_slider_height * multiplier))
                    slider.setMaximumHeight(int(self.base_slider_height * multiplier))

                sub_frames = widget.findChildren(QFrame)
                for sub_frame in sub_frames:
                    if sub_frame.objectName() == "ControlSubFrame":
                        sub_frame_layout = sub_frame.layout()
                        if sub_frame_layout:
                             sub_frame_layout.setContentsMargins(
                                int(self.base_control_sub_frame_margins[0] * multiplier),
                                int(self.base_control_sub_frame_margins[1] * multiplier),
                                int(self.base_control_sub_frame_margins[2] * multiplier),
                                int(self.base_control_sub_frame_margins[3] * multiplier)
                             )
                widget.updateGeometry()

        if self.scroll_content_widget:
            self.scroll_content_widget.updateGeometry()
            self.scroll_area.updateGeometry()

    def init_ui(self):
        self.setWindowTitle("PyQt6 ALSA Mixer")
        self.setGeometry(200, 200, 800, 650)

        self.setStyleSheet("""
            QFrame#MixerGroupFrame {
                border: 1px solid #C0C0C0; /* lightgray */
                border-radius: 4px;
                padding: 4px;
            }
            QFrame#ControlSubFrame {
                border: 1px solid #A0A0A0; /* gray */
                border-radius: 2px;
                padding: 3px;
            }
        """)

        main_layout = QVBoxLayout(self)
        
        top_controls_layout = QHBoxLayout()

        card_layout = QHBoxLayout()
        card_layout.addWidget(QLabel("Sound Card:"))
        self.card_combo = QComboBox()
        card_layout.addWidget(self.card_combo)
        card_layout.addStretch(1)
        top_controls_layout.addLayout(card_layout)
        # Zoom buttons will be moved to a new bottom layout
        main_layout.addLayout(top_controls_layout)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(320)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll_content_widget = QWidget()
        self.mixer_hbox_layout = QHBoxLayout(self.scroll_content_widget)
        self.mixer_hbox_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.mixer_hbox_layout.setSpacing(self.base_mixer_hbox_spacing) 
        self.mixer_hbox_layout.setContentsMargins(
            self.base_mixer_hbox_margins[0], self.base_mixer_hbox_margins[1],
            self.base_mixer_hbox_margins[2], self.base_mixer_hbox_margins[3]
        )
        self.mixer_hbox_layout.addStretch(1)  
        self.scroll_area.setWidget(self.scroll_content_widget)
        main_layout.addWidget(self.scroll_area)

        # --- Bottom controls layout for zoom buttons ---
        bottom_controls_layout = QHBoxLayout()
        bottom_controls_layout.addStretch(1) # Pushes buttons to the right

        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.setToolTip("Zoom out <span style='color:grey'>Ctrl+-</span>")
        self.zoom_out_button.setFixedSize(QSize(25, 25))
        self.zoom_out_button.clicked.connect(self._zoom_out)
        bottom_controls_layout.addWidget(self.zoom_out_button)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("Zoom in <span style='color:grey'>Ctrl++</span>")
        self.zoom_in_button.setFixedSize(QSize(25, 25))
        self.zoom_in_button.clicked.connect(self._zoom_in)
        bottom_controls_layout.addWidget(self.zoom_in_button)
        
        main_layout.addLayout(bottom_controls_layout)
        # --- End bottom controls ---
        
        self._setup_zoom_shortcuts()
 
    def _get_long_card_name(self, card_index, fallback_name):
        try:
            longname_path = f"/proc/asound/card{card_index}/longname"
            if os.path.exists(longname_path):
                with open(longname_path, 'r') as f:
                    name = f.readline().strip()
                    if name:
                        return name
            
            id_path = f"/proc/asound/card{card_index}/id"
            if os.path.exists(id_path):
                with open(id_path, 'r') as f:
                    name = f.readline().strip()
                    if name:
                        if name == fallback_name.split(' (')[0]:
                             return f"{name} (hw:{card_index})"
                        return name 
        except Exception as e:
            if self.debug_mode:
                print(f"Error reading card name for index {card_index}: {e}", file=sys.stderr)
        return fallback_name

    def init_error_ui(self, message):
        layout = QVBoxLayout(self)
        error_label = QLabel(f"<b>Error:</b> {message}<br><br>"
                            "ALSA mixer functionality requires pyalsaaudio (install python-pyalsaaudio, python3-alsaaudio or equivalent package).</code>")                    
        error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_label.setWordWrap(True)
        layout.addWidget(error_label)
        self.setLayout(layout)

    def populate_cards(self):
        if alsaaudio is None:
            return
        self.card_combo.clear()
        initial_card_selected = False
        
        try:
            self.card_combo.currentIndexChanged.disconnect(self._on_card_selected)
        except TypeError: 
            pass

        try:
            alsa_cards_short_names = alsaaudio.cards() if alsaaudio else []
            if not alsa_cards_short_names:
                self.card_combo.addItem("No cards found")
                self.card_combo.setEnabled(False)
                QMessageBox.information(self, "Info", "No sound cards found.")
                self.clear_mixer_controls_ui()
                self.card_combo.currentIndexChanged.connect(self._on_card_selected)
                return

            self.card_name_to_index_map = {}

            for i, short_name in enumerate(alsa_cards_short_names):
                descriptive_name = self._get_long_card_name(i, f"{short_name} (hw:{i})")
                display_text = f"{descriptive_name}" 
                
                original_display_text = display_text
                counter = 1
                while display_text in self.card_name_to_index_map:
                    display_text = f"{original_display_text} ({counter})"
                    counter += 1
                
                self.card_combo.addItem(display_text, userData=i)
                self.card_name_to_index_map[display_text] = i

            self.card_combo.setEnabled(True)

            if self.card_combo.count() > 0:
                last_card_hw_index = -1 
                if self.config_manager:
                    last_card_hw_index_str = self.config_manager.get_str('last_alsa_mixer_card_index', '-1')
                    try:
                        last_card_hw_index = int(last_card_hw_index_str)
                    except ValueError:
                        last_card_hw_index = -1
                
                found_last_card = False
                if last_card_hw_index != -1: 
                    for combo_idx in range(self.card_combo.count()):
                        if self.card_combo.itemData(combo_idx) == last_card_hw_index:
                            self.card_combo.setCurrentIndex(combo_idx)
                            initial_card_selected = True
                            found_last_card = True
                            break
                
                if not found_last_card: 
                    self.card_combo.setCurrentIndex(0)
                    initial_card_selected = True
            
            if initial_card_selected:
                 self._on_card_selected(self.card_combo.currentIndex())

        except alsaaudio.ALSAAudioError as e:
            QMessageBox.critical(self, "ALSA Error", f"Could not list sound cards: {e}")
            self.card_combo.addItem("Error loading cards")
            self.card_combo.setEnabled(False)
            self.clear_mixer_controls_ui()
        finally:
            self.card_combo.currentIndexChanged.connect(self._on_card_selected)
        
        if not initial_card_selected: 
            self.clear_mixer_controls_ui()

    def clear_mixer_controls_ui(self):
        self._is_updating_ui = True; self.mixer_controls_data.clear()
        while self.mixer_hbox_layout.count():
            item = self.mixer_hbox_layout.takeAt(0)
            if item:
                widget = item.widget()
                if widget:
                    widget.deleteLater()
        self._is_updating_ui = False

    def _on_card_selected(self, index):
        if index < 0: self.clear_mixer_controls_ui(); self.current_card_index = -1; return
        selected_card_hw_index = self.card_combo.itemData(index) 
        if selected_card_hw_index is None:
            self.clear_mixer_controls_ui()
            self.current_card_index = -1
            return
        
        if self.config_manager:
            self.config_manager.set_str('last_alsa_mixer_card_index', str(selected_card_hw_index))

        if selected_card_hw_index == self.current_card_index and self.mixer_hbox_layout.count() > 1:
            return

        self.current_card_index = selected_card_hw_index 
        self.clear_mixer_controls_ui() 
        self._is_updating_ui = True
        try: mixers_list = alsaaudio.mixers(cardindex=self.current_card_index)
        except alsaaudio.ALSAAudioError as e: QMessageBox.warning(self, "ALSA Error", f"Could not list mixers: {e}"); self._is_updating_ui = False; return
        if not mixers_list: info_label = QLabel(f"No mixers for card 'hw:{self.current_card_index}'."); info_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.mixer_hbox_layout.addWidget(info_label); self._is_updating_ui = False; return

        notifiers_setup_successfully = False # Initialize flag before the loop
        for mixer_name_from_list in mixers_list:
            mixer_name_key = mixer_name_from_list
            try: mixer_obj = alsaaudio.Mixer(control=mixer_name_from_list, cardindex=self.current_card_index)
            except alsaaudio.ALSAAudioError as e:
                if self.debug_mode: print(f"Err init mixer '{mixer_name_from_list}': {e}", file=sys.stderr)
                continue

            if self._setup_mixer_notifiers(mixer_name_from_list, mixer_obj):
                notifiers_setup_successfully = True # Set flag if any notifier is set up

            mixer_group_widget = QFrame()
            mixer_group_widget.setObjectName("MixerGroupFrame")
            mixer_group_widget.setFrameShape(QFrame.Shape.StyledPanel)
            mixer_group_layout = QVBoxLayout(mixer_group_widget)
            mixer_group_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

            name_label = QLabel(f"<b>{mixer_name_from_list}</b>")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet("margin-bottom: 8px;")
            mixer_group_layout.addWidget(name_label)
            control_data = {'obj': mixer_obj, 'pb_slider': None, 'pb_vol_label': None, 'pb_mute_cb': None,
                            'cap_slider': None, 'cap_vol_label': None}

            has_pb_vol, has_pb_mute, has_cap_vol = False, False, False
            vol_cap_ret, sw_cap_ret = None, None
            if self.debug_mode: print(f"\nDEBUG: Mixer: {mixer_name_from_list}")
            try: vol_cap_ret = mixer_obj.volumecap();
            except Exception as e: print(f"  volumecap() ERROR for {mixer_name_from_list}: {e}", file=sys.stderr) if self.debug_mode else None
            try: sw_cap_ret = mixer_obj.switchcap();
            except Exception as e: print(f"  switchcap() ERROR for {mixer_name_from_list}: {e}", file=sys.stderr) if self.debug_mode else None
            if self.debug_mode: print(f"  volumecap: {vol_cap_ret}, switchcap: {sw_cap_ret}")

            if isinstance(vol_cap_ret, list):
                if _CAP_STRING_PLAYBACK_VOLUME in vol_cap_ret: has_pb_vol = True
                elif _CAP_STRING_GENERIC_VOLUME in vol_cap_ret and not any("Capture" in s.capitalize() for s in vol_cap_ret): has_pb_vol = True;
                elif _MIXER_CAP_PVOLUME_INT in vol_cap_ret: has_pb_vol = True
                if _CAP_STRING_CAPTURE_VOLUME in vol_cap_ret: has_cap_vol = True
                elif _MIXER_CAP_CVOLUME_INT in vol_cap_ret: has_cap_vol = True
            elif isinstance(vol_cap_ret, int):
                if bool(vol_cap_ret & _MIXER_CAP_PVOLUME_INT): has_pb_vol = True
                if bool(vol_cap_ret & _MIXER_CAP_CVOLUME_INT): has_cap_vol = True

            if isinstance(sw_cap_ret, list):
                if _SWCAP_STRING_PLAYBACK_MUTE in sw_cap_ret: has_pb_mute = True
                elif _MIXER_SWCAP_PLAYBACK_INT in sw_cap_ret: has_pb_mute = True
            elif isinstance(sw_cap_ret, int):
                if bool(sw_cap_ret & _MIXER_SWCAP_PLAYBACK_INT): has_pb_mute = True

            actually_controllable_elements = 0

            if has_pb_vol:
                volume_frame = QFrame()
                volume_frame.setObjectName("ControlSubFrame")
                frame_layout = QVBoxLayout(volume_frame)

                slider = QSlider(Qt.Orientation.Vertical)
                slider.setRange(0, 100)
                slider.setTickPosition(QSlider.TickPosition.TicksLeft)
                slider.setTickInterval(20)
                val_label = QLabel("N/A")
                val_label.setFixedWidth(30)
                val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

                try:
                    current_volumes = mixer_obj.getvolume()
                    if current_volumes:
                        vol_val = int(current_volumes[0])
                        slider.setValue(vol_val)
                        val_label.setText(str(vol_val))
                    else:
                        slider.setEnabled(False)
                        val_label.setText("Err")

                    slider.valueChanged.connect(partial(self._on_dynamic_volume_changed, mixer_name_key, val_label))
                    control_data['pb_slider'] = slider
                    control_data['pb_vol_label'] = val_label

                    frame_layout.addWidget(slider, 0, Qt.AlignmentFlag.AlignCenter)
                    frame_layout.addWidget(val_label, 0, Qt.AlignmentFlag.AlignCenter)

                    mixer_group_layout.addWidget(volume_frame)
                    actually_controllable_elements += 1
                except alsaaudio.ALSAAudioError as e:
                    if self.debug_mode: print(f"  UI INFO: PB Vol for '{mixer_name_from_list}' inaccessible: {e}", file=sys.stderr)

            if has_pb_mute:
                cb = QCheckBox("")
                try:
                    mutes = mixer_obj.getmute()
                    if mutes is not None: cb.setChecked(any(m == 1 for m in mutes))
                    else: cb.setEnabled(False); cb.setText("PB Mute (Err)")
                    cb.stateChanged.connect(partial(self._on_dynamic_mute_changed, mixer_name_key))

                    mute_layout = QVBoxLayout()
                    mute_layout.addWidget(cb, 0, Qt.AlignmentFlag.AlignCenter)
                    mute_label = QLabel("Mute")
                    mute_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    mute_layout.addWidget(mute_label)

                    control_data['pb_mute_cb'] = cb
                    mixer_group_layout.addLayout(mute_layout)
                    actually_controllable_elements += 1
                except alsaaudio.ALSAAudioError as e:
                    if self.debug_mode: print(f"  UI INFO: PB Mute for '{mixer_name_from_list}' inaccessible: {e}", file=sys.stderr)

            if actually_controllable_elements > 0 and has_cap_vol :
                sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setFrameShadow(QFrame.Shadow.Sunken); mixer_group_layout.addWidget(sep)

            if has_cap_vol:
                cap_volume_frame = QFrame()
                cap_volume_frame.setObjectName("ControlSubFrame")
                cap_frame_layout = QVBoxLayout(cap_volume_frame)

                slider = QSlider(Qt.Orientation.Vertical)
                slider.setRange(0, 100)
                slider.setTickPosition(QSlider.TickPosition.TicksLeft)
                slider.setTickInterval(20)

                val_label = QLabel("N/A")
                val_label.setFixedWidth(30)
                val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

                try:
                    current_volumes = mixer_obj.getvolume()
                    if current_volumes:
                        vol_val = int(current_volumes[0])
                        slider.setValue(vol_val)
                        val_label.setText(str(vol_val))
                    else:
                        slider.setEnabled(False)
                        val_label.setText("Err")

                    slider.valueChanged.connect(partial(self._on_dynamic_volume_changed, mixer_name_key, val_label))
                    control_data['cap_slider'] = slider
                    control_data['cap_vol_label'] = val_label

                    cap_frame_layout.addWidget(slider, 0, Qt.AlignmentFlag.AlignCenter)
                    cap_frame_layout.addWidget(val_label, 0, Qt.AlignmentFlag.AlignCenter)

                    mixer_group_layout.addWidget(cap_volume_frame)
                    actually_controllable_elements += 1
                except alsaaudio.ALSAAudioError as e:
                    if self.debug_mode: print(f"  UI INFO: CAP Vol for '{mixer_name_from_list}' inaccessible: {e}", file=sys.stderr)

            if actually_controllable_elements > 0:
                self.mixer_controls_data[mixer_name_key] = control_data
                self.mixer_hbox_layout.addWidget(mixer_group_widget)
            else:
                if self.debug_mode: print(f"  UI INFO: No controllable elements for '{mixer_name_from_list}', skipping UI frame.")
                mixer_group_widget.deleteLater()

        # Manage the timer based on notifier setup
        if notifiers_setup_successfully:
            self.update_timer.stop()
        else:
            self.update_timer.start(500)

        self._apply_zoom()
        self._is_updating_ui = False

    def _on_dynamic_volume_changed(self, mixer_name_key, volume_label_widget, value):
        if self._is_updating_ui: return
        control_data = self.mixer_controls_data.get(mixer_name_key)
        if not control_data or not control_data['obj']: return
        try:
            control_data['obj'].setvolume(value) 
            if volume_label_widget: volume_label_widget.setText(str(value))
        except alsaaudio.ALSAAudioError as e: QMessageBox.warning(self, "ALSA Error", f"Could not set volume for '{mixer_name_key}': {e}"); self.refresh_specific_mixer_state(mixer_name_key)

    def _on_dynamic_mute_changed(self, mixer_name_key, qt_state_value):
        if self._is_updating_ui: return
        control_data = self.mixer_controls_data.get(mixer_name_key)
        if not control_data or not control_data['obj']: return
        try:
            mute_val = 1 if qt_state_value == Qt.CheckState.Checked.value else 0
            control_data['obj'].setmute(mute_val)
        except alsaaudio.ALSAAudioError as e: QMessageBox.warning(self, "ALSA Error", f"Could not set mute for '{mixer_name_key}': {e}"); self.refresh_specific_mixer_state(mixer_name_key)

    def refresh_specific_mixer_state(self, mixer_name_key):
        if self._is_updating_ui: return
        control_data = self.mixer_controls_data.get(mixer_name_key)
        if not control_data or not control_data['obj']: return
        self._is_updating_ui = True; mixer_obj = control_data['obj']

        if control_data['pb_slider']:
            try:
                current_volumes = mixer_obj.getvolume()
                if current_volumes: v=int(current_volumes[0]); control_data['pb_slider'].setValue(v); control_data['pb_vol_label'].setText(str(v)); control_data['pb_slider'].setEnabled(True)
                else: control_data['pb_slider'].setEnabled(False); control_data['pb_vol_label'].setText("Err")
            except alsaaudio.ALSAAudioError: control_data['pb_slider'].setEnabled(False); control_data['pb_vol_label'].setText("Err")
        if control_data['pb_mute_cb']:
            try:
                mutes = mixer_obj.getmute()
                if mutes is not None: control_data['pb_mute_cb'].setChecked(any(m==1 for m in mutes)); control_data['pb_mute_cb'].setEnabled(True)
                else: control_data['pb_mute_cb'].setEnabled(False); control_data['pb_mute_cb'].setText("PB Mute (Err)")
            except alsaaudio.ALSAAudioError: control_data['pb_mute_cb'].setEnabled(False); control_data['pb_mute_cb'].setText("PB Mute (Err)")

        if control_data['cap_slider']:
            try:
                current_volumes = mixer_obj.getvolume() 
                if current_volumes: v=int(current_volumes[0]); control_data['cap_slider'].setValue(v); control_data['cap_vol_label'].setText(str(v)); control_data['cap_slider'].setEnabled(True)
                else: control_data['cap_slider'].setEnabled(False); control_data['cap_vol_label'].setText("Err")
            except alsaaudio.ALSAAudioError: control_data['cap_slider'].setEnabled(False); control_data['cap_vol_label'].setText("Err")

        self._is_updating_ui = False

    def refresh_all_mixer_states(self):
        if self._is_updating_ui: return; print("Refreshing all mixer states...") if self.debug_mode else None; self._is_updating_ui = True
        for key in list(self.mixer_controls_data.keys()): self.refresh_specific_mixer_state(key)
        self._is_updating_ui = False
 
    def start_updates(self):
        """Starts the ALSA mixer update mechanisms (timer or notifiers)."""
        print("ALSA Mixer: Starting updates...") if self.debug_mode else None
        # Re-populate cards to ensure correct state and setup notifiers/timer
        self.populate_cards()
 
    def stop_updates(self):
        """Stops the ALSA mixer update mechanisms (timer and notifiers)."""
        print("ALSA Mixer: Stopping updates...") if self.debug_mode else None
        self.update_timer.stop()
        self._cleanup_notifiers()
        self.clear_mixer_controls_ui() # Clear UI when stopping updates
 
    def closeEvent(self, event):
        self._cleanup_notifiers()
        self.clear_mixer_controls_ui()
        event.accept()

    def _setup_mixer_notifiers(self, mixer_name, mixer_obj):
        if not hasattr(mixer_obj, 'polldescriptors'):
            if self.debug_mode: print(f"polldescriptors not available for {mixer_name}")
            return False
 
        try:
            fds = mixer_obj.polldescriptors()
            if self.debug_mode: print(f"polldescriptors for {mixer_name}: {fds}")
            if not fds:
                return False
 
            self.mixer_notifiers[mixer_name] = []
            for fd, event_mask in fds:
                notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
                notifier.activated.connect(partial(self._handle_alsa_event, mixer_name, fd))
                self.mixer_notifiers[mixer_name].append(notifier)
                self.fd_to_mixer[fd] = mixer_name
 
            if self.debug_mode:
                print(f"Set up {len(fds)} notifiers for {mixer_name}")
            return True
 
        except Exception as e:
            if self.debug_mode:
                print(f"Error setting up notifiers for {mixer_name}: {e}")
            return False
    
    def _handle_alsa_event(self, mixer_name, fd):
        activated_notifier = None
        if mixer_name in self.mixer_notifiers:
            for notifier in self.mixer_notifiers[mixer_name]:
                if notifier.socket() == fd:
                    activated_notifier = notifier
                    break
        
        if activated_notifier:
            activated_notifier.setEnabled(False)
 
        if self.debug_mode:
            print(f"ALSA event detected for {mixer_name} (fd: {fd}). Notifier disabled temporarily.")
        
        control_data = self.mixer_controls_data.get(mixer_name)
        if control_data and control_data.get('obj'):
            mixer_obj = control_data['obj']
            try:
                mixer_obj.handleevents()
                if self.debug_mode:
                    print(f"Called handleevents() for {mixer_name}")
            except alsaaudio.ALSAAudioError as e:
                if self.debug_mode:
                    print(f"Error calling handleevents() for {mixer_name}: {e}", file=sys.stderr)
            except Exception as e:
                 if self.debug_mode:
                    print(f"Unexpected error during handleevents() for {mixer_name}: {e}", file=sys.stderr)
        
        # Debounce the UI refresh to avoid excessive updates from rapid ALSA events
        QTimer.singleShot(50, lambda: self.refresh_specific_mixer_state(mixer_name))
 
        if activated_notifier:
            activated_notifier.setEnabled(True)
            if self.debug_mode:
                print(f"Notifier for {mixer_name} (fd: {fd}) re-enabled.")
 
    def _cleanup_notifiers(self):
        for mixer_name, notifiers in self.mixer_notifiers.items():
            for notifier in notifiers:
                notifier.setEnabled(False)
                notifier.deleteLater()
        self.mixer_notifiers.clear()
        self.fd_to_mixer.clear()

    def _setup_zoom_shortcuts(self):
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut(QKeySequence("Ctrl+=")) # Using string for Ctrl+= (often same as Ctrl++)
        zoom_in_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        zoom_in_action.triggered.connect(self._zoom_in)
        self.addAction(zoom_in_action)

        # For Ctrl++, some systems might need "Ctrl+Shift+=" if "+" is on the same key as "="
        # but "Ctrl+=" is generally more standard for ZoomIn. We'll also add "Ctrl++" as an alternative.
        zoom_in_plus_action = QAction("Zoom In Alternative", self)
        zoom_in_plus_action.setShortcut(QKeySequence("Ctrl++"))
        zoom_in_plus_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        zoom_in_plus_action.triggered.connect(self._zoom_in)
        self.addAction(zoom_in_plus_action)


        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        zoom_out_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        zoom_out_action.triggered.connect(self._zoom_out)
        self.addAction(zoom_out_action)

    def keyPressEvent(self, event):
        """Handle key press events for zooming."""
        accepted = False
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
                self._zoom_in()
                accepted = True
            elif event.key() == Qt.Key.Key_Minus:
                self._zoom_out()
                accepted = True
        
        if accepted:
            event.accept()
        else:
            super().keyPressEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv); mixer_app = AlsMixerApp(); mixer_app.show(); sys.exit(app.exec())
