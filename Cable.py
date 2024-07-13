import sys
import subprocess
import json
import re
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QPushButton, QLabel, QSpacerItem, QSizePolicy
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

class PipeWireSettingsApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.profile_index_map = {}  # To store the mapping between profile names and indices
        self.load_current_settings()  # Load current settings when the app starts

    def create_section_title(self, title):
        label = QLabel(title)
        font = label.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignCenter)
        return label

    def initUI(self):
        layout = QVBoxLayout()
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        # Audio Profile Section
        layout.addWidget(self.create_section_title("Audio Profile"))

        device_layout = QHBoxLayout()
        device_label = QLabel("Audio Device:")
        self.device_combo = QComboBox()
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        layout.addLayout(device_layout)

        profile_layout = QHBoxLayout()
        profile_label = QLabel("Device Profile:")
        self.profile_combo = QComboBox()
        profile_layout.addWidget(profile_label)
        profile_layout.addWidget(self.profile_combo)
        layout.addLayout(profile_layout)

        self.apply_profile_button = QPushButton("Apply Profile")
        self.apply_profile_button.clicked.connect(self.apply_profile_settings)
        layout.addWidget(self.apply_profile_button)

        # Quantum Section
        layout.addWidget(self.create_section_title("Quantum"))

        quantum_layout = QHBoxLayout()
        quantum_label = QLabel("Quantum/Buffer:")
        self.quantum_combo = QComboBox()
        quantum_values = [16, 32, 48, 64, 96, 128, 144, 192, 240, 256, 512, 1024, 2048]
        for value in quantum_values:
            self.quantum_combo.addItem(str(value))
        quantum_layout.addWidget(quantum_label)
        quantum_layout.addWidget(self.quantum_combo)
        layout.addLayout(quantum_layout)

        self.apply_quantum_button = QPushButton("Apply Quantum")
        self.apply_quantum_button.clicked.connect(self.apply_quantum_settings)
        layout.addWidget(self.apply_quantum_button)

        self.reset_quantum_button = QPushButton("Reset Quantum")
        self.reset_quantum_button.clicked.connect(self.reset_quantum_settings)
        layout.addWidget(self.reset_quantum_button)

        # Sample Rate Section
        layout.addWidget(self.create_section_title("Sample Rate"))

        sample_rate_layout = QHBoxLayout()
        sample_rate_label = QLabel("Sample Rate:")
        self.sample_rate_combo = QComboBox()
        sample_rate_values = [44100, 48000, 88200, 96000, 176400, 192000]
        for value in sample_rate_values:
            self.sample_rate_combo.addItem(str(value))
        sample_rate_layout.addWidget(sample_rate_label)
        sample_rate_layout.addWidget(self.sample_rate_combo)
        layout.addLayout(sample_rate_layout)

        self.apply_sample_rate_button = QPushButton("Apply Sample Rate")
        self.apply_sample_rate_button.clicked.connect(self.apply_sample_rate_settings)
        layout.addWidget(self.apply_sample_rate_button)

        self.reset_sample_rate_button = QPushButton("Reset Sample Rate")
        self.reset_sample_rate_button.clicked.connect(self.reset_sample_rate_settings)
        layout.addWidget(self.reset_sample_rate_button)

        # Latency Section
        layout.addWidget(self.create_section_title("Latency"))

        node_layout = QHBoxLayout()
        node_label = QLabel("Audio Node:")
        self.node_combo = QComboBox()
        self.node_combo.addItem("Choose Node")  # Add "Choose Node" option
        node_layout.addWidget(node_label)
        node_layout.addWidget(self.node_combo)
        layout.addLayout(node_layout)

        latency_layout = QHBoxLayout()
        latency_label = QLabel("Latency Offset (samples):")
        self.latency_input = QLineEdit()
        latency_layout.addWidget(latency_label)
        latency_layout.addWidget(self.latency_input)
        layout.addLayout(latency_layout)

        self.apply_latency_button = QPushButton("Apply Latency")
        self.apply_latency_button.clicked.connect(self.apply_latency_settings)
        layout.addWidget(self.apply_latency_button)

           # Restart Buttons Section
        restart_layout = QHBoxLayout()

        self.restart_wireplumber_button = QPushButton("Restart Wireplumber")
        self.restart_wireplumber_button.clicked.connect(self.restart_wireplumber)
        self.set_button_style(self.restart_wireplumber_button)
        restart_layout.addWidget(self.restart_wireplumber_button)

        self.restart_pipewire_button = QPushButton("Restart Pipewire")
        self.restart_pipewire_button.clicked.connect(self.restart_pipewire)
        self.set_button_style(self.restart_pipewire_button)
        restart_layout.addWidget(self.restart_pipewire_button)

        layout.addLayout(restart_layout)

        self.setLayout(layout)
        self.setWindowTitle('Cable')
        self.setGeometry(300, 300, 400, 600)  # Increased height to accommodate new buttons

        self.load_nodes()
        self.load_devices()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.node_combo.currentIndexChanged.connect(self.on_node_changed)

    def set_button_style(self, button):
        button.setStyleSheet("""
            QPushButton {
                color: red;
                font-weight: bold;
            }
        """)

    def restart_wireplumber(self):
        try:
            subprocess.run(["systemctl", "restart", "--user", "wireplumber"], check=True)
            print("Wireplumber restarted successfully")
        except subprocess.CalledProcessError as e:
            print(f"Error restarting Wireplumber: {e}")

    def restart_pipewire(self):
        try:
            subprocess.run(["systemctl", "restart", "--user", "pipewire"], check=True)
            print("Pipewire restarted successfully")
        except subprocess.CalledProcessError as e:
            print(f"Error restarting Pipewire: {e}")

    def load_devices(self):
        self.device_combo.clear()
        self.device_combo.addItem("Choose device")  # Add dummy option
        try:
            output = subprocess.check_output(["pw-cli", "ls", "Device"], universal_newlines=True)
            devices = output.split('\n')
            current_device_id = None
            current_device_description = None
            current_device_name = None
            for line in devices:
                if line.strip().startswith("id "):
                    current_device_id = line.split(',')[0].split()[-1].strip()
                elif "device.description" in line:
                    current_device_description = line.split('=')[1].strip().strip('"')
                elif "device.name" in line:
                    current_device_name = line.split('=')[1].strip().strip('"')
                    if current_device_description and current_device_name and current_device_name.startswith("alsa_"):
                        device_label = f"{current_device_description} (ID: {current_device_id})"
                        self.device_combo.addItem(device_label)
                    current_device_id = None
                    current_device_description = None
                    current_device_name = None
        except subprocess.CalledProcessError:
            print("Error: Unable to retrieve device list.")

    def load_nodes(self):
        self.node_combo.clear()
        self.node_combo.addItem("Choose Node")  # Add "Choose Node" option
        try:
            output = subprocess.check_output(["pw-cli", "ls", "Node"], universal_newlines=True)
            nodes = output.split('\n')
            current_node_id = None
            current_node_description = None
            current_node_name = None
            for line in nodes:
                if line.strip().startswith("id "):
                    current_node_id = line.split(',')[0].split()[-1].strip()
                elif "node.description" in line:
                    current_node_description = line.split('=')[1].strip().strip('"')
                elif "node.name" in line:
                    current_node_name = line.split('=')[1].strip().strip('"')
                    if current_node_description and current_node_name and current_node_name.startswith("alsa_"):
                        io_type = "Input" if "input" in current_node_name.lower() else "Output" if "output" in current_node_name.lower() else "Unknown"
                        node_label = f"{current_node_description} ({io_type}) (ID: {current_node_id})"
                        self.node_combo.addItem(node_label)
                    current_node_id = None
                    current_node_description = None
                    current_node_name = None
        except subprocess.CalledProcessError:
            print("Error: Unable to retrieve node list.")

    def on_device_changed(self, index):
        if index > 0:  # Ignore the "Choose device" option
            self.load_profiles()
        else:
            self.profile_combo.clear()

    def on_node_changed(self, index):
        if index > 0:  # Ignore the "Choose Node" option
            selected_node = self.node_combo.currentText()
            node_id = selected_node.split('(ID: ')[-1].strip(')')
            self.load_latency_offset(node_id)
        else:
            self.latency_input.setText("")

    def load_latency_offset(self, node_id):
        try:
            output = subprocess.check_output(["pw-cli", "e", node_id, "ProcessLatency"], universal_newlines=True)
            rate_match = re.search(r'Int\s+(\d+)', output)
            if rate_match:
                latency_rate = rate_match.group(1)
                self.latency_input.setText(latency_rate)
            else:
                self.latency_input.setText("")
                print(f"Error: Unable to parse latency offset for node {node_id}")
        except subprocess.CalledProcessError:
            self.latency_input.setText("")
            print(f"Error: Unable to retrieve latency offset for node {node_id}")

    def load_profiles(self):
        self.profile_combo.clear()
        self.profile_index_map.clear()
        selected_device = self.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        try:
            output = subprocess.check_output(["pw-dump", device_id], universal_newlines=True)
            data = json.loads(output)
            active_profile_index = None
            profiles = None

            for item in data:
                if 'info' in item and 'params' in item['info']:
                    params = item['info']['params']
                    if 'Profile' in params:
                        active_profile_index = params['Profile'][0]['index']
                    if 'EnumProfile' in params:
                        profiles = params['EnumProfile']

            if profiles:
                for profile in profiles:
                    index = profile.get('index', 'Unknown')
                    description = profile.get('description', 'Unknown Profile')
                    self.profile_combo.addItem(description)
                    self.profile_index_map[description] = index

                    # Set the active profile
                    if active_profile_index is not None and index == active_profile_index:
                        self.profile_combo.setCurrentText(description)

        except subprocess.CalledProcessError:
            print(f"Error: Unable to retrieve profiles for device {selected_device}")

    def apply_latency_settings(self):
        selected_node = self.node_combo.currentText()
        node_id = selected_node.split('(ID: ')[-1].strip(')')
        latency_offset = self.latency_input.text()

        try:
            command = f"pw-cli s {node_id} ProcessLatency '{{ rate = {latency_offset} }}'"
            subprocess.run(command, shell=True, check=True)
            print(f"Applied latency offset {latency_offset} to node {selected_node}")
        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to apply settings to node {selected_node}")
            print(f"Command failed with error: {e}")

    def apply_profile_settings(self):
        selected_device = self.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        selected_profile = self.profile_combo.currentText()
        profile_index = self.profile_index_map.get(selected_profile, 'Unknown')

        try:
            command = f"wpctl set-profile {device_id} {profile_index}"
            subprocess.run(command, shell=True, check=True)
            print(f"Applied profile {selected_profile} to device {selected_device}")
        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to apply profile to device {selected_device}")
            print(f"Command failed with error: {e}")

    def apply_quantum_settings(self):
        quantum_value = self.quantum_combo.currentText()
        try:
            command = f"pw-metadata -n settings 0 clock.force-quantum {quantum_value}"
            subprocess.run(command, shell=True, check=True)
            print(f"Applied quantum/buffer setting: {quantum_value}")
        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to apply quantum/buffer setting")
            print(f"Command failed with error: {e}")

    def reset_quantum_settings(self):
        try:
            command = "pw-metadata -n settings 0 clock.force-quantum 0"
            subprocess.run(command, shell=True, check=True)
            print("Reset quantum/buffer setting to default")
            self.load_current_settings()  # Reload current settings to update the UI
        except subprocess.CalledProcessError as e:
            print("Error: Unable to reset quantum/buffer setting")
            print(f"Command failed with error: {e}")

    def apply_sample_rate_settings(self):
        sample_rate = self.sample_rate_combo.currentText()
        try:
            command = f"pw-metadata -n settings 0 clock.force-rate {sample_rate}"
            subprocess.run(command, shell=True, check=True)
            print(f"Applied sample rate setting: {sample_rate}")
        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to apply sample rate setting")
            print(f"Command failed with error: {e}")

    def reset_sample_rate_settings(self):
        try:
            command = "pw-metadata -n settings 0 clock.force-rate 0"
            subprocess.run(command, shell=True, check=True)
            print("Reset sample rate setting to default")
            self.load_current_settings()  # Reload current settings to update the UI
        except subprocess.CalledProcessError as e:
            print("Error: Unable to reset sample rate setting")
            print(f"Command failed with error: {e}")

    def load_current_settings(self):
        try:
            output = subprocess.check_output(["pw-metadata", "-n", "settings"], universal_newlines=True)
            rate_match = re.search(r"update: id:0 key:'clock.force.rate' value:'(\d+)'", output)
            quantum_match = re.search(r"update: id:0 key:'clock.force.quantum' value:'(\d+)'", output)

            if rate_match:
                current_rate = rate_match.group(1)
                index = self.sample_rate_combo.findText(current_rate)
                if index >= 0:
                    self.sample_rate_combo.setCurrentIndex(index)
                else:
                    print(f"Current sample rate {current_rate} not found in combo box options. Adding it.")
                    self.sample_rate_combo.addItem(current_rate)
                    self.sample_rate_combo.setCurrentText(current_rate)

            if quantum_match:
                current_quantum = quantum_match.group(1)
                index = self.quantum_combo.findText(current_quantum)
                if index >= 0:
                    self.quantum_combo.setCurrentIndex(index)
                else:
                    print(f"Current quantum {current_quantum} not found in combo box options. Adding it.")
                    self.quantum_combo.addItem(current_quantum)
                    self.quantum_combo.setCurrentText(current_quantum)

        except subprocess.CalledProcessError as e:
            print(f"Error: Unable to retrieve current settings")
            print(f"Command failed with error: {e}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = PipeWireSettingsApp()
    ex.show()
    sys.exit(app.exec_())
