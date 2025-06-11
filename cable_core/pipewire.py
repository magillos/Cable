import os
import subprocess
import json
import re
import configparser
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer

# Define the constant directly in this module
EDIT_LIST_TEXT = "Edit List..."

class PipewireManager:
    def __init__(self, app):
        self.app = app

    def get_metadata_value(self, key):
        """Get pipewire metadata values without shell pipelines"""
        output = self.run_command(['pw-metadata', '-n', 'settings'])
        if not output:
            return None

        for line in output.split('\n'):
            if key in line:
                try:
                    return line.split("'")[3]  # Extract value from metadata line
                except IndexError:
                    continue
        return None

    def _load_pw_cli_items(self, item_type, combo_box, initial_text):
        """Helper to load items (Devices or Nodes) from 'pw-cli ls' output."""
        combo_box.clear()
        combo_box.addItem(initial_text)
        try:
            output = self.run_command(['pw-cli', 'ls', item_type])
            if not output:
                print(f"Error: Empty response from pw-cli ls {item_type}")
                return

            items = output.split('\n')
            current_item_id = None
            current_item_description = None
            current_item_name = None
            desc_key = f"{item_type.lower()}.description"
            name_key = f"{item_type.lower()}.name"

            for line in items:
                line = line.strip()
                if line.startswith("id "):
                    # Extract ID, handling potential extra info after comma
                    try:
                        current_item_id = line.split(',')[0].split()[-1].strip()
                    except IndexError:
                        print(f"Warning: Could not parse ID from line: {line}")
                        current_item_id = None # Reset ID if parsing fails
                        continue # Skip to next line
                elif desc_key in line:
                    try:
                        current_item_description = line.split('=', 1)[1].strip().strip('"')
                    except IndexError:
                         print(f"Warning: Could not parse description from line: {line}")
                         current_item_description = None
                elif name_key in line:
                    try:
                        current_item_name = line.split('=', 1)[1].strip().strip('"')
                    except IndexError:
                         print(f"Warning: Could not parse name from line: {line}")
                         current_item_name = None

                    # Once we have name, check if we have enough info and if it's an ALSA item
                    if current_item_id and current_item_description and current_item_name and current_item_name.startswith("alsa_"):
                        label = f"{current_item_description} (ID: {current_item_id})"
                        # Add I/O type for Nodes
                        if item_type == 'Node':
                            io_type = "Unknown"
                            if "input" in current_item_name.lower():
                                io_type = "Input"
                            elif "output" in current_item_name.lower():
                                io_type = "Output"
                            label = f"{current_item_description} ({io_type}) (ID: {current_item_id})"

                        combo_box.addItem(label)

                    # Reset for next item after processing name line
                    current_item_id = None
                    current_item_description = None
                    current_item_name = None

        except Exception as e:
            print(f"Error loading {item_type}s: {e}")
            QMessageBox.critical(self.app, "Error", # Changed self to self.app for QMessageBox parent
                f"Could not retrieve {item_type}s:\n{str(e)}")

    def load_devices(self):
        self._load_pw_cli_items('Device', self.app.device_combo, "Choose device")

    def load_nodes(self):
        self._load_pw_cli_items('Node', self.app.node_combo, "Choose Node")

    def load_latency_offset(self, node_id):
        try:
            # Note: subprocess calls don't need self.app prefix
            output = subprocess.check_output(["pw-cli", "e", node_id, "ProcessLatency"], universal_newlines=True)

            # First, check for Long (nanoseconds) value
            ns_match = re.search(r'Long\s+(\d+)', output)
            if ns_match and int(ns_match.group(1)) > 0:
                latency_rate = ns_match.group(1)
                self.app.nanoseconds_checkbox.setChecked(True)
                self.app.latency_input.setText(latency_rate)
            else:
                # If Long is not present or zero, check for Int (samples) value
                rate_match = re.search(r'Int\s+(\d+)', output)
                if rate_match:
                    latency_rate = rate_match.group(1)
                    self.app.nanoseconds_checkbox.setChecked(False)
                    self.app.latency_input.setText(latency_rate)
                else:
                    self.app.latency_input.setText("")
                    self.app.nanoseconds_checkbox.setChecked(False)
                    print(f"Error: Unable to parse latency offset for node {node_id}")
        except subprocess.CalledProcessError:
            self.app.latency_input.setText("")
            self.app.nanoseconds_checkbox.setChecked(False)
            print(f"Error: Unable to retrieve latency offset for node {node_id}")

    def load_profiles(self):
        self.app.profile_combo.clear()
        self.app.profile_index_map.clear() # This map should probably live in the app now? Or passed in? Assuming app for now.
        selected_device = self.app.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        try:
            # Note: subprocess calls don't need self.app prefix
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
                    self.app.profile_combo.addItem(description)
                    self.app.profile_index_map[description] = index # Storing on app

                    # Set the active profile
                    if active_profile_index is not None and index == active_profile_index:
                        self.app.profile_combo.setCurrentText(description)
        except subprocess.CalledProcessError:
            print(f"Error: Unable to retrieve profiles for device {selected_device}")

    def apply_latency_settings(self):
        selected_node = self.app.node_combo.currentText()
        node_id = selected_node.split('(ID: ')[-1].strip(')')
        latency_offset = self.app.latency_input.text()
        try:
            # Build base command
            command = [
                'pw-cli',
                's',
                node_id,
                'ProcessLatency'
            ]
            # Add latency parameter
            if self.app.nanoseconds_checkbox.isChecked():
                command.append(f'{{ ns = {latency_offset} }}')
            else:
                command.append(f'{{ rate = {latency_offset} }}')
            # Add Flatpak prefix if needed (using self.app.flatpak_env)
            if self.app.flatpak_env:
                command = ['flatpak-spawn', '--host'] + command
            # Run command (subprocess doesn't need self.app)
            result = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            print(f"Applied latency offset {latency_offset} to node {selected_node}")
            print(f"Command output: {result.stdout}")

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to apply latency settings:\n{e.stderr}"
            print(error_msg)
            QMessageBox.critical(
                self.app, # Parent is self.app
                "Latency Error",
                f"{error_msg}\n\n"
                "Possible solutions:\n"
                "1. Ensure PipeWire is running\n"
                "2. Check Flatpak permissions\n"
                "3. Verify node ID is correct"
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            print(error_msg)
            QMessageBox.critical(
                self.app, # Parent is self.app
                "Error",
                error_msg
            )

    def apply_profile_settings(self):
        selected_device = self.app.device_combo.currentText()
        device_id = selected_device.split('(ID: ')[-1].strip(')')
        selected_profile = self.app.profile_combo.currentText()
        profile_index = self.app.profile_index_map.get(selected_profile) # Assuming map is on app
        try:
            # Use internal run_command
            self.run_command(['wpctl', 'set-profile', device_id, str(profile_index)], check_output=False)
            print(f"Applied profile {selected_profile} to device {selected_device}")
        except Exception as e:
            print(f"Error applying profile: {e}")

    def _apply_metadata_setting(self, setting_name, metadata_key, combo_box, last_valid_index_attr, was_reset_attr, save_setting_func, skip_save=False):
        """Helper to apply PipeWire metadata settings for quantum or sample rate."""
        value_str = combo_box.currentText()
        # last_valid_index is an attribute of the app, accessed via getattr
        last_valid_index = getattr(self.app, last_valid_index_attr)

        # Prevent applying if value is empty or the special edit text
        if not value_str or value_str == EDIT_LIST_TEXT: # Use imported constant
             print(f"Skipping apply for invalid/special text: '{value_str}'")
             # Reset to last valid value if user typed it and pressed Enter/Apply
             QTimer.singleShot(0, lambda: combo_box.setCurrentIndex(last_valid_index))
             return False # Indicate failure

        try:
            # Check if it's a valid integer before proceeding
            int(value_str)

            # Use internal run_command
            success = self.run_command([
                'pw-metadata',
                '-n', 'settings',
                '0', metadata_key,
                value_str
            ], check_output=False)

            if success:
                print(f"Applied {setting_name} setting: {value_str}")
                # Clear the reset flag since we're explicitly applying a setting
                # But only if we're not in initial load (accessing app's attribute)
                if not self.app.initial_load:
                    setattr(self.app, was_reset_attr, False) # Set attribute on app

                # Save setting if remember settings is enabled, we're not skipping save,
                # and we're not in initial load (accessing app's attributes)
                if self.app.remember_settings_checkbox.isChecked() and not skip_save and not self.app.initial_load:
                    # save_setting_func is already a method of app.config_manager, so call it directly
                    save_setting_func()

                # Update the last valid index to the newly applied value's index
                # Do this *after* successful application
                new_index = combo_box.findText(value_str)
                if new_index >= 0: # Ensure the applied value exists in the combo (it should)
                    setattr(self.app, last_valid_index_attr, new_index) # Set attribute on app
                    print(f"Updated last valid index for {setting_name} to {new_index} after applying '{value_str}'")

                return True # Indicate success
            else:
                print(f"Failed to apply {setting_name} setting: {value_str} (run_command failed)")
                # Optionally show error message here?
                return False # Indicate failure

        except ValueError:
             print(f"Invalid {setting_name} value entered: {value_str}. Cannot apply.")
             QMessageBox.warning(self.app, "Invalid Input", f"{setting_name} value must be an integer: '{value_str}'") # Parent is self.app
             # Reset to last valid index
             QTimer.singleShot(0, lambda: combo_box.setCurrentIndex(last_valid_index))
             return False # Indicate failure
        except Exception as e:
            print(f"Error applying {setting_name}: {e}")
            # Optionally show error message here?
            return False # Indicate failure

    def apply_quantum_settings(self, skip_save=False):
        # Check if "Edit List..." is selected and open the dialog if so
        if self.app.quantum_combo.currentText() == EDIT_LIST_TEXT: # Use imported constant
            self.app.edit_quantum_list() # Call app's method
            # Reset to last valid selection after dialog
            QTimer.singleShot(0, lambda: self.app.quantum_combo.setCurrentIndex(self.app.last_valid_quantum_index))
            return

        self._apply_metadata_setting(
            setting_name="quantum/buffer",
            metadata_key='clock.force-quantum',
            combo_box=self.app.quantum_combo, # Use app's combo box
            last_valid_index_attr='last_valid_quantum_index', # Attribute name on app
            was_reset_attr='quantum_was_reset', # Attribute name on app
            save_setting_func=self.app.config_manager.save_quantum_setting, # Pass app's config manager method
            skip_save=skip_save
        )

    def _reset_metadata_setting(self, setting_name, metadata_key, config_key, was_reset_attr, force_reset_kwarg):
        """Helper to reset PipeWire metadata settings and update config."""
        try:
            # Reset PipeWire setting using internal run_command
            command = ["pw-metadata", "-n", "settings", "0", metadata_key, "0"]
            success = self.run_command(command, check_output=False)

            if not success:
                 print(f"Reset {setting_name} failed (run_command).")
                 QMessageBox.critical(
                     self.app, # Parent is self.app
                     "Error",
                     f"Failed to reset {setting_name} settings.\n"
                     "Check PipeWire status and permissions."
                 )
                 return

            print(f"Reset {setting_name} setting to default")

            # Set the reset flag on the app to prevent saving default values
            setattr(self.app, was_reset_attr, True)
            print(f"Loading default {setting_name} value from system, marked as reset")

            # Remove saved setting from config if it exists
            config = configparser.ConfigParser()
            # Construct the config path directly
            config_path = os.path.expanduser("~/.config/cable/config.ini")
            config_modified = False
            if os.path.exists(config_path):
                config.read(config_path)
                if 'DEFAULT' in config and config_key in config['DEFAULT']:
                    del config['DEFAULT'][config_key]
                    config_modified = True

            if config_modified:
                # Use the app's config_manager's helper method to write the config
                self.app.config_manager._write_config(config)
                print(f"Removed {config_key} setting from config")

            # Reload current settings but don't save them
            # Call the internal load_current_settings method
            # Pass the force_reset flag dynamically
            load_kwargs = {force_reset_kwarg: True}
            self.load_current_settings(**load_kwargs) # Call internal method

        except subprocess.CalledProcessError as e: # Keep specific check for CalledProcessError if run_command raises it
            print(f"Reset {setting_name} failed: {e.stderr.decode() if e.stderr else str(e)}")
            QMessageBox.critical(
                self.app, # Parent is self.app
                "Permission Error",
                f"Failed to reset {setting_name} settings:\n"
                "Ensure Flatpak permissions are properly configured\n"
                f"Details: {e.stderr.decode() if e.stderr else str(e)}"
            )
        except Exception as e:
            print(f"Error during reset {setting_name}: {e}")
            QMessageBox.critical(self.app, "Error", f"An unexpected error occurred while resetting {setting_name}: {e}") # Parent is self.app


    def reset_quantum_settings(self):
        self._reset_metadata_setting(
            setting_name="quantum/buffer",
            metadata_key='clock.force-quantum',
            config_key='saved_quantum', # Config key name
            was_reset_attr='quantum_was_reset', # Attribute name on app
            force_reset_kwarg='force_reset_quantum' # Kwarg for load_current_settings
        )

    def apply_sample_rate_settings(self, skip_save=False):
        # Check if "Edit List..." is selected and open the dialog if so
        if self.app.sample_rate_combo.currentText() == EDIT_LIST_TEXT: # Use imported constant
            self.app.edit_sample_rate_list() # Call app's method
            # Reset to last valid selection after dialog
            QTimer.singleShot(0, lambda: self.app.sample_rate_combo.setCurrentIndex(self.app.last_valid_sample_rate_index))
            return

        self._apply_metadata_setting(
            setting_name="sample rate",
            metadata_key='clock.force-rate',
            combo_box=self.app.sample_rate_combo, # Use app's combo box
            last_valid_index_attr='last_valid_sample_rate_index', # Attribute name on app
            was_reset_attr='sample_rate_was_reset', # Attribute name on app
            save_setting_func=self.app.config_manager.save_sample_rate_setting, # Pass app's config manager method
            skip_save=skip_save
        )

    def reset_sample_rate_settings(self):
        self._reset_metadata_setting(
            setting_name="sample rate",
            metadata_key='clock.force-rate',
            config_key='saved_sample_rate', # Config key name
            was_reset_attr='sample_rate_was_reset', # Attribute name on app
            force_reset_kwarg='force_reset_sample_rate' # Kwarg for load_current_settings
        )

    def load_current_settings(self, force_reset_quantum=False, force_reset_sample_rate=False):
        # Block signals during programmatic changes
        self.app.quantum_combo.blockSignals(True)
        self.app.sample_rate_combo.blockSignals(True)
        try:

            sample_rate = None
            quantum = None
            try:
                # Use internal get_metadata_value
                forced_rate = self.get_metadata_value('clock.force-rate')
                if forced_rate in (None, "0"):
                    sample_rate = self.get_metadata_value('clock.rate')
                else:
                    sample_rate = forced_rate

                forced_quantum = self.get_metadata_value('clock.force-quantum')
                if forced_quantum in (None, "0"):
                    quantum = self.get_metadata_value('clock.quantum')
                else:
                    quantum = forced_quantum
            except Exception as meta_e:
                print(f"Error getting metadata values: {meta_e}")
                # Continue, UI might show defaults or be empty


            if force_reset_quantum and forced_quantum in (None, "0"):
                self.app.quantum_was_reset = True # Set attribute on app

            if force_reset_sample_rate and forced_rate in (None, "0"):
                self.app.sample_rate_was_reset = True # Set attribute on app

            # --- Update UI elements with the new logic ---
            if sample_rate:
                index = self.app.sample_rate_combo.findText(sample_rate)
                # Ensure the found index is for a valid numerical item
                if index >= 0:
                    self.app.sample_rate_combo.setCurrentIndex(index)
                    self.app.last_valid_sample_rate_index = index # Store initial valid index on app
                else:
                    # System value not in list, insert it before "Edit List..."
                    edit_item_index = self.app.sample_rate_combo.count() - 1
                    if edit_item_index >= 0:
                        self.app.sample_rate_combo.insertItem(edit_item_index, sample_rate)
                        self.app.sample_rate_combo.setCurrentIndex(edit_item_index)
                        self.app.last_valid_sample_rate_index = edit_item_index # Store on app
                        print(f"Inserted system sample rate '{sample_rate}' into dropdown.")
                    else: # Fallback if edit item not found
                         print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert system sample rate '{sample_rate}' before.") # Use imported constant


            if quantum:
                index = self.app.quantum_combo.findText(quantum)
                 # Ensure the found index is for a valid numerical item
                if index >= 0:
                    self.app.quantum_combo.setCurrentIndex(index)
                    self.app.last_valid_quantum_index = index # Store initial valid index on app
                else:
                    # System value not in list, insert it before "Edit List..."
                    edit_item_index = self.app.quantum_combo.count() - 1
                    if edit_item_index >= 0:
                        self.app.quantum_combo.insertItem(edit_item_index, quantum)
                        self.app.quantum_combo.setCurrentIndex(edit_item_index)
                        self.app.last_valid_quantum_index = edit_item_index # Store on app
                        print(f"Inserted system quantum '{quantum}' into dropdown.")
                    else: # Fallback if edit item not found
                         print(f"Warning: Could not find '{EDIT_LIST_TEXT}' to insert system quantum '{quantum}' before.") # Use imported constant

        except Exception as e:
            # Catch exceptions during the process
            print(f"Error loading current settings: {e}")
        finally:
            # Unblock signals
            self.app.quantum_combo.blockSignals(False)
            self.app.sample_rate_combo.blockSignals(False)

            # Call app's update_latency_display method
            self.app.update_latency_display()

    def reset_all_latency(self):
        """Resets the ProcessLatency for all nodes listed in the node combo box."""
        print("Attempting to reset latency for all nodes...")
        if not hasattr(self.app, 'node_combo'):
            print("Error: self.app.node_combo not found.")
            return

        node_count = self.app.node_combo.count()
        if node_count <= 1: # Only contains "Choose Node" or is empty
             print("No nodes found in the combo box to reset latency for.")
             return

        for i in range(node_count):
            node_text = self.app.node_combo.itemText(i)

            if node_text == "Choose Node":
                continue

            node_id = None # Initialize node_id
            try:
                # Extract node ID robustly
                if '(ID: ' in node_text:
                    node_id = node_text.split('(ID: ')[-1].strip(')')
                else:
                     print(f"Warning: Skipping item '{node_text}' - Could not find '(ID: ' marker.")
                     continue # Skip if format is unexpected

                if not node_id: # Check if node_id extraction resulted in an empty string
                    print(f"Warning: Skipping item '{node_text}' - Extracted empty node ID.")
                    continue

                # Command to reset latency (setting rate to 0)
                command_args = ['pw-cli', 's', node_id, 'ProcessLatency', '{ rate = 0 }']

                try:
                    # Use the existing run_command helper
                    success = self.run_command(command_args, check_output=False)
                    if success:
                        print(f"Successfully reset latency for node {node_id} ('{node_text}')")
                    else:
                        # run_command already prints failure details
                        print(f"Failed to reset latency for node {node_id} ('{node_text}') (run_command returned False/None)")

                except Exception as e:
                    # Catch errors during command execution specifically
                    print(f"Failed to execute latency reset command for node {node_id} ('{node_text}'): {e}")

            except Exception as e:
                # Catch errors during text processing/splitting
                print(f"Warning: Error processing item '{node_text}': {e}. Skipping.")
                continue # Skip to the next node if processing fails

        print("Finished attempting to reset latency for all nodes.")
        # Optionally, refresh the latency input field if a node is selected
        # self.app.on_node_changed(self.app.node_combo.currentIndex())

    def run_command(self, command_args, check_output=True):
        """Generic command runner with Flatpak support"""
        # Use app's flatpak_env attribute
        if self.app.flatpak_env:
            command_args = ['flatpak-spawn', '--host'] + command_args

        try:
            if check_output:
                # subprocess calls don't need self.app prefix
                result = subprocess.check_output(
                    command_args,
                    universal_newlines=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()
            else:
                # subprocess calls don't need self.app prefix
                subprocess.run(
                    command_args,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
        except subprocess.CalledProcessError as e:
            print(f"Command failed: {e}")
            return None
    # Methods moved from PipeWireSettingsApp are now above
