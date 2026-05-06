"""
PipeWire interaction via subprocess calls to pw-cli, pw-metadata, pw-dump, and wpctl.
"""

import logging
import subprocess
import json
import re
from typing import Any, Callable, Dict, List, Optional, Union

from cable_core.app_config import EDIT_LIST_TEXT

logger = logging.getLogger(__name__)

class PipewireManager:
    def __init__(self, flatpak_env: bool, config_manager: Any) -> None:
        self.flatpak_env = flatpak_env
        self.config_manager = config_manager

    def get_metadata_value(self, key: str) -> Optional[str]:
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

    def _load_pw_cli_items(self, item_type: str) -> Dict[str, Any]:
        """Helper to load items (Devices or Nodes) from 'pw-cli ls' output."""
        try:
            output = self.run_command(['pw-cli', 'ls', item_type])
            if not output:
                logger.error(f"Error: Empty response from pw-cli ls {item_type}")
                return {"ok": True, "data": []}

            items_list = []
            items = output.split('\n')
            current_item_id = None
            current_item_description = None
            current_item_name = None
            desc_key = f"{item_type.lower()}.description"
            name_key = f"{item_type.lower()}.name"

            for line in items:
                line = line.strip()
                if line.startswith("id "):
                    try:
                        current_item_id = line.split(',')[0].split()[-1].strip()
                    except IndexError:
                        logger.warning(f"Warning: Could not parse ID from line: {line}")
                        current_item_id = None
                        continue
                elif desc_key in line:
                    try:
                        current_item_description = line.split('=', 1)[1].strip().strip('"')
                    except IndexError:
                         logger.warning(f"Warning: Could not parse description from line: {line}")
                         current_item_description = None
                elif name_key in line:
                    try:
                        current_item_name = line.split('=', 1)[1].strip().strip('"')
                    except IndexError:
                         logger.warning(f"Warning: Could not parse name from line: {line}")
                         current_item_name = None

                    # Include ALSA devices/nodes always; include bluez (Bluetooth) only for Devices (not Nodes)
                    # Bluetooth latency cannot be changed via ProcessLatency, so exclude from Node list
                    is_valid_device = current_item_name.startswith("alsa_") or (
                        item_type == 'Device' and current_item_name.startswith("bluez_")
                    )
                    if current_item_id and current_item_description and current_item_name and is_valid_device:
                        item_dict = {
                            "description": current_item_description,
                            "id": current_item_id,
                            "name": current_item_name,
                        }
                        if item_type == 'Node':
                            io_type = "Unknown"
                            if "input" in current_item_name.lower():
                                io_type = "Input"
                            elif "output" in current_item_name.lower():
                                io_type = "Output"
                            item_dict["io_type"] = io_type

                        items_list.append(item_dict)

                    current_item_id = None
                    current_item_description = None
                    current_item_name = None

            return {"ok": True, "data": items_list}

        except Exception as e:
            logger.error(f"Error loading {item_type}s: {e}")
            return {"ok": False, "error": {"title": "Error", "message": f"Could not retrieve {item_type}s:\n{str(e)}"}}

    def load_devices(self) -> Dict[str, Any]:
        return self._load_pw_cli_items('Device')

    def load_nodes(self) -> Dict[str, Any]:
        return self._load_pw_cli_items('Node')

    def load_latency_offset(self, node_id: str) -> Dict[str, Any]:
        try:
            output = self.run_command(["pw-cli", "e", node_id, "ProcessLatency"])
            if not output:
                logger.error(f"Error: Unable to retrieve latency offset for node {node_id}")
                return {"ok": False, "data": {"value": "", "is_nanoseconds": False}}

            ns_match = re.search(r'Long\s+(\d+)', output)
            if ns_match and int(ns_match.group(1)) > 0:
                latency_rate = ns_match.group(1)
                return {"ok": True, "data": {"value": latency_rate, "is_nanoseconds": True}}
            else:
                rate_match = re.search(r'Int\s+(\d+)', output)
                if rate_match:
                    latency_rate = rate_match.group(1)
                    return {"ok": True, "data": {"value": latency_rate, "is_nanoseconds": False}}
                else:
                    logger.error(f"Error: Unable to parse latency offset for node {node_id}")
                    return {"ok": True, "data": {"value": "", "is_nanoseconds": False}}
        except Exception as e:
            logger.error(f"Error: Unable to retrieve latency offset for node {node_id}: {e}")
            return {"ok": False, "data": {"value": "", "is_nanoseconds": False}}

    def load_profiles(self, device_id: str) -> Dict[str, Any]:
        try:
            output = self.run_command(["pw-dump", device_id])
            if not output:
                logger.error(f"Error: Unable to retrieve profiles for device {device_id}")
                return {"ok": False, "error": {"title": "Error", "message": f"Unable to retrieve profiles for device {device_id}"}}
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

            profiles_list = []
            if profiles:
                for profile in profiles:
                    index = profile.get('index', 'Unknown')
                    description = profile.get('description', 'Unknown Profile')
                    profiles_list.append({"index": index, "description": description})

            return {"ok": True, "data": {"profiles": profiles_list, "active_index": active_profile_index}}
        except Exception as e:
            logger.error(f"Error: Unable to retrieve profiles for device {device_id}: {e}")
            return {"ok": False, "error": {"title": "Error", "message": f"Unable to retrieve profiles for device {device_id}"}}

    def apply_latency_settings(self, node_id: str, latency_offset: str, use_nanoseconds: bool) -> Dict[str, Any]:
        return self._apply_latency_settings_impl(node_id, latency_offset, use_nanoseconds)

    def _apply_latency_settings_impl(self, node_id: str, latency_offset: str, use_nanoseconds: bool) -> Dict[str, Any]:
        try:
            command = [
                'pw-cli',
                's',
                node_id,
                'ProcessLatency'
            ]
            if use_nanoseconds:
                command.append(f'{{ ns = {latency_offset} }}')
            else:
                command.append(f'{{ rate = {latency_offset} }}')
            if self.flatpak_env:
                command = ['flatpak-spawn', '--host'] + command
            result = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logger.info(f"Applied latency offset {latency_offset} to node {node_id}")
            logger.debug(f"Command output: {result.stdout}")
            return {"ok": True}

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to apply latency settings:\n{e.stderr}"
            logger.error(error_msg)
            return {"ok": False, "error": {"title": "Latency Error", "message": f"{error_msg}\n\nPossible solutions:\n1. Ensure PipeWire is running\n2. Check Flatpak permissions\n3. Verify node ID is correct"}}
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            return {"ok": False, "error": {"title": "Error", "message": error_msg}}

    def apply_profile_settings(self, device_id: str, profile_index: int) -> Dict[str, Any]:
        return self._apply_profile_settings_impl(device_id, profile_index)

    def _apply_profile_settings_impl(self, device_id: str, profile_index: int) -> Dict[str, Any]:
        try:
            self.run_command(['wpctl', 'set-profile', device_id, str(profile_index)], check_output=False)
            logger.info(f"Applied profile index {profile_index} to device {device_id}")
            return {"ok": True}
        except Exception as e:
            logger.error(f"Error applying profile: {e}")
            return {"ok": False, "error": {"title": "Error", "message": f"Error applying profile: {e}"}}

    def _apply_metadata_setting(self, setting_name: str, metadata_key: str, value_str: str, save_setting_func: Optional[Callable[..., Any]] = None, skip_save: bool = False, remember_settings: bool = False, initial_load: bool = False, was_reset: bool = False) -> Dict[str, Any]:
        """Helper to apply PipeWire metadata settings for quantum or sample rate.
        No wait cursor - these are fast metadata operations that complete instantly."""
        return self._apply_metadata_setting_impl(
            setting_name, metadata_key, value_str, save_setting_func,
            skip_save, remember_settings, initial_load, was_reset
        )

    def _apply_metadata_setting_impl(self, setting_name: str, metadata_key: str, value_str: str, save_setting_func: Optional[Callable[..., Any]] = None, skip_save: bool = False, remember_settings: bool = False, initial_load: bool = False, was_reset: bool = False) -> Dict[str, Any]:
        if not value_str or value_str == EDIT_LIST_TEXT:
             logger.debug(f"Skipping apply for invalid/special text: '{value_str}'")
             return {"ok": False, "ui": {"revert": True}}

        try:
            int(value_str)

            success = self.run_command([
                'pw-metadata',
                '-n', 'settings',
                '0', metadata_key,
                value_str
            ], check_output=False)

            if success:
                logger.info(f"Applied {setting_name} setting: {value_str}")

                new_was_reset = was_reset
                if not initial_load:
                    new_was_reset = False

                saved = False
                if remember_settings and not skip_save and not initial_load:
                    if save_setting_func:
                        save_setting_func(current_value=value_str, was_reset=new_was_reset)
                        saved = True

                return {"ok": True, "data": {"was_reset": new_was_reset, "saved": saved}}
            else:
                logger.error(f"Failed to apply {setting_name} setting: {value_str} (run_command failed)")
                return {"ok": False}

        except ValueError:
             logger.warning(f"Invalid {setting_name} value entered: {value_str}. Cannot apply.")
             return {"ok": False, "error": {"title": "Invalid Input", "message": f"{setting_name} value must be an integer: '{value_str}'"}, "ui": {"revert": True}}
        except Exception as e:
            logger.error(f"Error applying {setting_name}: {e}")
            return {"ok": False}

    def apply_quantum_settings(self, value_str: str, skip_save: bool = False, remember_settings: bool = False, initial_load: bool = False, quantum_was_reset: bool = False) -> Dict[str, Any]:
        if value_str == EDIT_LIST_TEXT:
            return {"ok": False, "ui": {"edit_list": "quantum", "revert": True}}

        return self._apply_metadata_setting(
            setting_name="quantum/buffer",
            metadata_key='clock.force-quantum',
            value_str=value_str,
            save_setting_func=self.config_manager.save_quantum_setting,
            skip_save=skip_save,
            remember_settings=remember_settings,
            initial_load=initial_load,
            was_reset=quantum_was_reset
        )

    def apply_sample_rate_settings(self, value_str: str, skip_save: bool = False, remember_settings: bool = False, initial_load: bool = False, sample_rate_was_reset: bool = False) -> Dict[str, Any]:
        if value_str == EDIT_LIST_TEXT:
            return {"ok": False, "ui": {"edit_list": "sample_rate", "revert": True}}

        return self._apply_metadata_setting(
            setting_name="sample rate",
            metadata_key='clock.force-rate',
            value_str=value_str,
            save_setting_func=self.config_manager.save_sample_rate_setting,
            skip_save=skip_save,
            remember_settings=remember_settings,
            initial_load=initial_load,
            was_reset=sample_rate_was_reset
        )

    def _reset_metadata_setting(self, setting_name: str, metadata_key: str, config_key: str, force_reset_kwarg: str) -> Dict[str, Any]:
        """Helper to reset PipeWire metadata settings and update config.
        No wait cursor - these are fast metadata operations that complete instantly."""
        return self._reset_metadata_setting_impl(
            setting_name, metadata_key, config_key, force_reset_kwarg
        )

    def _reset_metadata_setting_impl(self, setting_name: str, metadata_key: str, config_key: str, force_reset_kwarg: str) -> Dict[str, Any]:
        try:
            command = ["pw-metadata", "-n", "settings", "0", metadata_key, "0"]
            success = self.run_command(command, check_output=False)

            if not success:
                 logger.error(f"Reset {setting_name} failed (run_command).")
                 return {"ok": False, "error": {"title": "Error", "message": f"Failed to reset {setting_name} settings.\nCheck PipeWire status and permissions."}}

            logger.debug(f"Reset {setting_name} setting to default")

            self.config_manager.clear_settings([config_key])
            self.config_manager.flush()
            logger.info(f"Removed {config_key} setting from config")

            return {"ok": True, "ui": {"refresh_settings": True}, "data": {"was_reset": True, "force_reset_kwarg": force_reset_kwarg}}

        except subprocess.CalledProcessError as e:
            logger.debug(f"Reset {setting_name} failed: {e.stderr.decode() if e.stderr else str(e)}")
            return {"ok": False, "error": {"title": "Permission Error", "message": f"Failed to reset {setting_name} settings:\nEnsure Flatpak permissions are properly configured\nDetails: {e.stderr.decode() if e.stderr else str(e)}"}}
        except Exception as e:
            logger.error(f"Error during reset {setting_name}: {e}")
            return {"ok": False, "error": {"title": "Error", "message": f"An unexpected error occurred while resetting {setting_name}: {e}"}}

    def reset_quantum_settings(self) -> Dict[str, Any]:
        return self._reset_metadata_setting(
            setting_name="quantum/buffer",
            metadata_key='clock.force-quantum',
            config_key='saved_quantum',
            force_reset_kwarg='force_reset_quantum'
        )

    def reset_sample_rate_settings(self) -> Dict[str, Any]:
        return self._reset_metadata_setting(
            setting_name="sample rate",
            metadata_key='clock.force-rate',
            config_key='saved_sample_rate',
            force_reset_kwarg='force_reset_sample_rate'
        )

    def get_current_settings(self) -> Dict[str, Optional[str]]:
        sample_rate = None
        quantum = None
        forced_rate = None
        forced_quantum = None
        try:
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
            logger.error(f"Error getting metadata values: {meta_e}")

        return {
            "quantum": quantum,
            "sample_rate": sample_rate,
            "forced_quantum": forced_quantum,
            "forced_rate": forced_rate
        }

    def reset_all_latency(self, node_ids: List[str]) -> Dict[str, Any]:
        """Resets the ProcessLatency for all given node IDs."""
        return self._reset_all_latency_impl(node_ids)

    def _reset_all_latency_impl(self, node_ids: List[str]) -> Dict[str, Any]:
        logger.debug("Attempting to reset latency for all nodes...")
        results = {}

        for node_id in node_ids:
            if not node_id:
                continue
            try:
                command_args = ['pw-cli', 's', node_id, 'ProcessLatency', '{ rate = 0 }']
                try:
                    success = self.run_command(command_args, check_output=False)
                    if success:
                        logger.debug(f"Successfully reset latency for node {node_id}")
                        results[node_id] = True
                    else:
                        logger.debug(f"Failed to reset latency for node {node_id} (run_command returned False/None)")
                        results[node_id] = False
                except Exception as e:
                    logger.debug(f"Failed to execute latency reset command for node {node_id}: {e}")
                    results[node_id] = False
            except Exception as e:
                logger.warning(f"Warning: Error processing node {node_id}: {e}. Skipping.")
                results[node_id] = False
                continue

        logger.debug("Finished attempting to reset latency for all nodes.")
        return {"ok": True, "data": {"results": results}}

    @property
    def is_flatpak(self) -> bool:
        """Whether this PipewireManager is running inside a Flatpak sandbox."""
        return self.flatpak_env

    # ── Sink/node operations (used by NodeSinkHandler) ──────────────

    def get_pw_dump(self) -> Optional[List[Dict[str, Any]]]:
        """Run ``pw-dump`` and return the parsed JSON output.

        Returns:
            List of dict nodes from pw-dump, or None on failure.
        """
        try:
            output = self.run_command(["pw-dump"])
            if not output:
                return None
            return json.loads(output)
        except Exception as e:
            logger.error(f"Error running pw-dump: {e}")
            return None

    def inspect_default_sink(self) -> Optional[str]:
        """Run ``wpctl inspect @DEFAULT_AUDIO_SINK@`` and return the output.

        Returns:
            Raw command output string, or None on failure.
        """
        try:
            output = self.run_command(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"])
            return output if output else None
        except Exception as e:
            logger.error(f"Error inspecting default sink: {e}")
            return None

    def set_default_node(self, node_id: int) -> bool:
        """Set the default PipeWire audio sink to the given node ID.

        Args:
            node_id: PipeWire node ID to set as default.

        Returns:
            True on success.
        """
        cmd = ["wpctl", "set-default", str(node_id)]
        return bool(self.run_command(cmd, check_output=False))

    def clear_default_node(self) -> bool:
        """Clear the default PipeWire audio sink.

        Returns:
            True on success.
        """
        cmd = ["wpctl", "clear-default", "0"]
        return bool(self.run_command(cmd, check_output=False))

    def list_sinks(self, short: bool = True) -> Optional[str]:
        """Run ``pactl list sinks`` (or ``pactl list short sinks``).

        Args:
            short: If True, run ``pactl list short sinks`` for a compact listing.

        Returns:
            Command output string, or None on failure.
        """
        try:
            cmd = ["pactl", "list", "short" if short else "", "sinks"]
            # Remove empty strings
            cmd = [c for c in cmd if c]
            output = self.run_command(cmd)
            return output if output else None
        except Exception as e:
            logger.error(f"Error listing sinks: {e}")
            return None

    def detect_channel_map(self, sink_name: str) -> str:
        """Detect the channel map of a running sink via ``pactl list sinks``.

        Args:
            sink_name: Name of the sink to inspect.

        Returns:
            Channel map string (e.g. ``"front-left,front-right"``) or default.
        """
        try:
            output = self.list_sinks(short=False)
            if not output:
                return "front-left,front-right"

            in_target_sink = False
            for line in output.splitlines():
                stripped = line.strip()
                if (
                    stripped.startswith("Name:")
                    and stripped.split(":", 1)[1].strip() == sink_name
                ):
                    in_target_sink = True
                elif stripped.startswith("Name:"):
                    in_target_sink = False
                elif in_target_sink and stripped.startswith("Channel Map:"):
                    return stripped.split(":", 1)[1].strip().replace(" ", "")
        except Exception as e:
            logger.warning(f"Could not detect channel map for {sink_name}: {e}")
        return "front-left,front-right"

    def run_command(self, command_args: List[str], check_output: bool = True) -> Union[str, bool, None]:
        """Generic command runner with Flatpak support"""
        if self.flatpak_env:
            command_args = ['flatpak-spawn', '--host'] + command_args

        try:
            if check_output:
                result = subprocess.check_output(
                    command_args,
                    universal_newlines=True,
                    stderr=subprocess.DEVNULL
                )
                return result.strip()
            else:
                subprocess.run(
                    command_args,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
        except subprocess.CalledProcessError as e:
            logger.debug(f"Command failed: {e}")
            return None
