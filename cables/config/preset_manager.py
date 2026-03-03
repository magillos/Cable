"""
PresetManager - Manages connection presets
"""

import os
import subprocess
import signal
import sys
import logging
from typing import Any, Dict, List, Optional
from subprocess import DEVNULL
from PyQt6.QtWidgets import QMessageBox, QWidget

logger = logging.getLogger(__name__)

class PresetManager:
    """
    Manages connection presets for the Cables application.
    """
    
    def __init__(self) -> None:
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
                logger.error(f"Error creating presets directory {self.presets_dir}: {e}")
    
    def load_presets(self) -> Dict[str, Dict[str, Any]]:
        presets = {}
        if not os.path.exists(self.presets_dir):
            return presets
        
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".snap"):
                preset_name = filename[:-5]
                presets[preset_name] = {}
        return presets
    
    def get_preset_names(self) -> List[str]:
        names = []
        if not os.path.exists(self.presets_dir):
            return names
        for filename in os.listdir(self.presets_dir):
            if filename.endswith(".snap"):
                names.append(filename[:-5])
        return sorted(names)
    
    def load_and_apply_preset(self, name: str, strict_mode: bool = False, daemon_mode: bool = False) -> bool:
        preset_file = os.path.join(self.presets_dir, f"{name}.snap")
        if not os.path.exists(preset_file):
            logger.warning(f"Preset file not found: {preset_file}")
            return False
        
        if daemon_mode:
            return self.start_daemon_mode(name, strict_mode)

        try:
            command = ["aj-snapshot", "-r"]
            if strict_mode:
                command.append("-x")
            command.append(preset_file)
            
            logger.info(f"Executing: {' '.join(command)}")
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            logger.debug(f"aj-snapshot stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"aj-snapshot stderr:\n{result.stderr}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error applying preset '{name}' with aj-snapshot: {e}")
            logger.debug(f"aj-snapshot stdout:\n{e.stdout}")
            logger.debug(f"aj-snapshot stderr:\n{e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error applying preset '{name}': {e}")
            return False
    
    def save_preset(self, name: str, parent_widget: Optional[QWidget] = None, confirm_overwrite: bool = True) -> bool:
        logger.debug(f"PresetManager.save_preset called with name='{name}', confirm_overwrite={confirm_overwrite}")
        
        if not name:
            QMessageBox.warning(parent_widget, "Save Error", "Preset name cannot be empty.")
            return False
        
        preset_file = os.path.join(self.presets_dir, f"{name}.snap")
        logger.debug(f"Preset file path: {preset_file}")
        
        if confirm_overwrite and os.path.exists(preset_file):
            logger.debug(f"Preset file exists, showing overwrite confirmation dialog")
            try:
                # Create the message box explicitly to have more control
                msgBox = QMessageBox(parent_widget)
                msgBox.setIcon(QMessageBox.Icon.Question)
                msgBox.setWindowTitle('Confirm Overwrite')
                msgBox.setText(f"A preset named '{name}' already exists.\nDo you want to overwrite it?")
                msgBox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msgBox.setDefaultButton(QMessageBox.StandardButton.No)
                
                # Ensure the dialog is modal and properly handled
                msgBox.setModal(True)
                logger.debug("About to show overwrite confirmation dialog")
                reply = msgBox.exec()
                logger.debug(f"Dialog reply: {reply}")
                
                if reply == QMessageBox.StandardButton.No:
                    logger.info(f"Overwrite cancelled for preset '{name}'.")
                    return False
            except Exception as e:
                logger.error(f"Error showing overwrite confirmation dialog: {e}")
                import traceback
                traceback.print_exc()
                # If dialog fails, assume user wants to cancel
                return False
        
        try:
            command = ["aj-snapshot"]
            if not confirm_overwrite:
                command.append("-f")
            command.append(preset_file)
            
            logger.info(f"Executing: {' '.join(command)}")
            # Add timeout to prevent hanging
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            logger.debug(f"aj-snapshot stdout:\n{result.stdout}")
            if result.stderr:
                logger.debug(f"aj-snapshot stderr:\n{result.stderr}")
            logger.info(f"Preset '{name}' saved to {preset_file}")
            return True
        except subprocess.TimeoutExpired as e:
            error_message = f"Timeout saving preset '{name}' with aj-snapshot (30s limit exceeded)"
            logger.error(error_message)
            QMessageBox.critical(parent_widget, "Save Error", error_message)
            return False
        except subprocess.CalledProcessError as e:
            error_message = f"Error saving preset '{name}' with aj-snapshot: {e}\n" \
                            f"Stdout: {e.stdout}\nStderr: {e.stderr}"
            logger.error(error_message)
            QMessageBox.critical(parent_widget, "Save Error", error_message)
            return False
        except Exception as e:
            error_message = f"Unexpected error saving preset '{name}': {e}"
            logger.error(error_message)
            QMessageBox.critical(parent_widget, "Save Error", error_message)
            return False
    
    def delete_preset(self, name: str) -> bool:
        preset_file = os.path.join(self.presets_dir, f"{name}.snap")
        if os.path.exists(preset_file):
            try:
                os.remove(preset_file)
                logger.info(f"Preset '{name}' deleted from {preset_file}")
                return True
            except OSError as e:
                logger.error(f"Error deleting preset file {preset_file}: {e}")
                return False
        else:
            logger.warning(f"Preset file not found for deletion: {preset_file}")
            return False

    def start_daemon_mode(self, preset_name: str, strict_mode: bool = False) -> bool:
        self.stop_daemon_mode()

        preset_file = os.path.join(self.presets_dir, f"{preset_name}.snap")
        if not os.path.exists(preset_file):
            logger.warning(f"Cannot start daemon: Preset file not found: {preset_file}")
            return False

        command = ["aj-snapshot", "-d"]
        if strict_mode:
            command.append("-x")
        command.append(preset_file)
        
        try:
            process = subprocess.Popen(command, preexec_fn=os.setsid, stdout=DEVNULL, stderr=DEVNULL)
            with open(self.pid_file, 'w') as f:
                f.write(str(process.pid))
            logger.info(f"aj-snapshot daemon started for '{preset_name}' with PID: {process.pid}")
            return True
        except Exception as e:
            logger.error(f"Error starting aj-snapshot daemon: {e}")
            return False

    def stop_daemon_mode(self) -> bool:
        stopped = False
        
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, 'r') as f:
                    pid = int(f.read().strip())
                logger.info(f"Attempting to stop aj-snapshot daemon with PID: {pid}")
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    logger.info(f"Sent SIGTERM to process group of PID {pid}.")
                    stopped = True
                except ProcessLookupError:
                    logger.info(f"Process with PID {pid} not found. It may have already been terminated.")
                except Exception as e:
                    logger.warning(f"Error sending SIGTERM to process group {pid}: {e}")
                    try:
                        os.kill(pid, signal.SIGTERM)
                        logger.info(f"Sent SIGTERM to PID {pid} directly.")
                        stopped = True
                    except ProcessLookupError:
                        logger.info(f"Process {pid} not found.")
                    except Exception as e2:
                        logger.error(f"Failed to kill process with PID {pid}: {e2}")
            except (IOError, ValueError) as e:
                logger.error(f"Error reading PID file: {e}")
            finally:
                if os.path.exists(self.pid_file):
                    os.remove(self.pid_file)
        else:
            logger.info("No aj-snapshot daemon PID file found.")
        
        # Fallback: kill any remaining aj-snapshot daemon processes
        try:
            result = subprocess.run(
                ["pkill", "-f", "aj-snapshot.*-d"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                logger.info("Killed remaining aj-snapshot daemon processes via pkill.")
                stopped = True
        except Exception as e:
            logger.warning(f"pkill fallback failed: {e}")
        
        return stopped or True