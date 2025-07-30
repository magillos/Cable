"""
PresetManager - Manages connection presets
"""

import os
import subprocess
import signal
import sys
from subprocess import DEVNULL
from PyQt6.QtWidgets import QMessageBox

class PresetManager:
    """
    Manages connection presets for the Cables application.
    """
    
    def __init__(self):
        """Initialize the PresetManager."""
        self.config_dir = os.path.expanduser('~/.config/cable')
        self.presets_dir = os.path.join(self.config_dir, 'presets')
        self.pid_file = os.path.join(self.config_dir, 'aj-snapshot.pid')
        
        if not os.path.exists(self.presets_dir):
            try:
                if not os.path.exists(self.config_dir):
                    os.makedirs(self.config_dir)
                os.makedirs(self.presets_dir)
            except OSError as e:
                print(f"Error creating presets directory {self.presets_dir}: {e}")
    
    def load_presets(self):
        presets = {}
        if not os.path.exists(self.presets_dir):
            return presets
        
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".snap"):
                preset_name = filename[:-5]
                presets[preset_name] = {}
        return presets
    
    def get_preset_names(self):
        names = []
        if not os.path.exists(self.presets_dir):
            return names
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".snap"):
                names.append(filename[:-5])
        return sorted(names)
    
    def load_and_apply_preset(self, name, strict_mode=False, daemon_mode=False):
        preset_file = os.path.join(self.presets_dir, f"{name}.snap")
        if not os.path.exists(preset_file):
            print(f"Preset file not found: {preset_file}")
            return False
        
        if daemon_mode:
            return self.start_daemon_mode(name, strict_mode)

        try:
            command = ["aj-snapshot", "-r"]
            if strict_mode:
                command.append("-x")
            command.append(preset_file)
            
            print(f"Executing: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            print(f"aj-snapshot stdout:\n{result.stdout}")
            if result.stderr:
                print(f"aj-snapshot stderr:\n{result.stderr}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error applying preset '{name}' with aj-snapshot: {e}")
            print(f"aj-snapshot stdout:\n{e.stdout}")
            print(f"aj-snapshot stderr:\n{e.stderr}")
            return False
        except Exception as e:
            print(f"Unexpected error applying preset '{name}': {e}")
            return False
    
    def save_preset(self, name, parent_widget=None, confirm_overwrite=True):
        if not name:
            QMessageBox.warning(parent_widget, "Save Error", "Preset name cannot be empty.")
            return False
        
        preset_file = os.path.join(self.presets_dir, f"{name}.snap")
        
        if confirm_overwrite and os.path.exists(preset_file):
            reply = QMessageBox.question(parent_widget, 'Confirm Overwrite',
                                        f"A preset named '{name}' already exists.\nDo you want to overwrite it?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                print(f"Overwrite cancelled for preset '{name}'.")
                return False
        
        try:
            command = ["aj-snapshot"]
            if not confirm_overwrite:
                command.append("-f")
            command.append(preset_file)
            
            print(f"Executing: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            print(f"aj-snapshot stdout:\n{result.stdout}")
            if result.stderr:
                print(f"aj-snapshot stderr:\n{result.stderr}")
            print(f"Preset '{name}' saved to {preset_file}")
            return True
        except subprocess.CalledProcessError as e:
            error_message = f"Error saving preset '{name}' with aj-snapshot: {e}\n" \
                            f"Stdout: {e.stdout}\nStderr: {e.stderr}"
            print(error_message)
            QMessageBox.critical(parent_widget, "Save Error", error_message)
            return False
        except Exception as e:
            error_message = f"Unexpected error saving preset '{name}': {e}"
            print(error_message)
            QMessageBox.critical(parent_widget, "Save Error", error_message)
            return False
    
    def delete_preset(self, name):
        preset_file = os.path.join(self.presets_dir, f"{name}.snap")
        if os.path.exists(preset_file):
            try:
                os.remove(preset_file)
                print(f"Preset '{name}' deleted from {preset_file}")
                return True
            except OSError as e:
                print(f"Error deleting preset file {preset_file}: {e}")
                return False
        else:
            print(f"Preset file not found for deletion: {preset_file}")
            return False

    def start_daemon_mode(self, preset_name, strict_mode=False):
        self.stop_daemon_mode()

        preset_file = os.path.join(self.presets_dir, f"{preset_name}.snap")
        if not os.path.exists(preset_file):
            print(f"Cannot start daemon: Preset file not found: {preset_file}")
            return False

        command = ["aj-snapshot", "-d"]
        if strict_mode:
            command.append("-x")
        command.append(preset_file)
        
        try:
            process = subprocess.Popen(command, preexec_fn=os.setsid, stdout=DEVNULL, stderr=DEVNULL)
            with open(self.pid_file, 'w') as f:
                f.write(str(process.pid))
            print(f"aj-snapshot daemon started for '{preset_name}' with PID: {process.pid}")
            return True
        except Exception as e:
            print(f"Error starting aj-snapshot daemon: {e}")
            return False

    def stop_daemon_mode(self):
        if not os.path.exists(self.pid_file):
            print("No aj-snapshot daemon PID file found.")
            return True

        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
        except (IOError, ValueError) as e:
            print(f"Error reading PID file: {e}")
            os.remove(self.pid_file)
            return False

        print(f"Attempting to stop aj-snapshot daemon with PID: {pid}")
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            print(f"Sent SIGTERM to process group of PID {pid}.")
        except ProcessLookupError:
            print(f"Process with PID {pid} not found. It may have already been terminated.")
        except Exception as e:
            print(f"Error sending SIGTERM to process group {pid}: {e}")
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"Sent SIGKILL to PID {pid} as a fallback.")
            except Exception as e2:
                print(f"Failed to kill process with PID {pid}: {e2}")
                
        finally:
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
        
        return True