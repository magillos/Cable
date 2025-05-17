import jack
from typing import List, Optional, Tuple

def get_all_jack_ports(client: jack.Client, name_pattern: str = '', is_audio: bool = False, is_midi: bool = False, is_input: bool = False, is_output: bool = False, is_physical: bool = False, can_monitor: bool = False, is_terminal: bool = False) -> List[jack.Port]:
    """
    Gets all JACK ports, with optional filtering.
    """
    try:
        ports = client.get_ports(
            name_pattern=name_pattern,
            is_audio=is_audio,
            is_midi=is_midi,
            is_input=is_input,
            is_output=is_output,
            is_physical=is_physical,
            can_monitor=can_monitor,
            is_terminal=is_terminal
        )
        return ports
    except jack.JackError:
        # Log error or handle as appropriate for the application
        # For a simple utility, returning an empty list might be sufficient.
        return []

def get_jack_port_by_name(client: jack.Client, port_name: str) -> Optional[jack.Port]:
    """
    Gets a JACK port by its full name.
    Returns None if the port is not found or if a JackError occurs.
    """
    try:
        port = client.get_port_by_name(port_name)
        return port
    except jack.JackError:
        # Log error or handle
        return None

def get_all_jack_connections(client: jack.Client, port_or_name: Optional[str | jack.Port] = None) -> List[Tuple[str, str]]:
    """
    Gets all JACK connections.
    If port_or_name is provided, gets connections for that specific port.
    Otherwise, iterates through all output ports and gets their connections.
    Returns a list of (source_port_name, dest_port_name) tuples.
    """
    connections: List[Tuple[str, str]] = []
    try:
        if port_or_name:
            if isinstance(port_or_name, jack.Port):
                port_name_to_query = port_or_name.name
            else:
                port_name_to_query = port_or_name
            
            # jack.Client.get_all_connections() takes a port name (str)
            # and returns a list of connected port names (str).
            # We need to determine if the given port is an input or output
            # to correctly form the (source, destination) tuples.
            port_obj = client.get_port_by_name(port_name_to_query)
            if port_obj:
                if port_obj.is_output:
                    # For an output port, port_name_to_query is the source
                    connected_items = client.get_all_connections(port_name_to_query)
                    for item in connected_items:
                        dest_name = item.name if isinstance(item, jack.Port) else item
                        connections.append((port_name_to_query, dest_name))
                elif port_obj.is_input:
                    # For an input port, port_name_to_query is the destination
                    # We need to find which output ports are connected to it.
                    # jack.Client.get_all_connections() called on an input port
                    # returns the output ports connected to it.
                    source_items = client.get_all_connections(port_name_to_query)
                    for item in source_items:
                        src_name = item.name if isinstance(item, jack.Port) else item
                        connections.append((src_name, port_name_to_query))
        else:
            # Get all connections by iterating through all output ports
            # Use the utility function get_all_jack_ports to fetch output ports
            output_ports = get_all_jack_ports(client, is_output=True) # Use our own utility
            for port_obj in output_ports: # port_obj is a jack.Port object
                # client.get_all_connections(port_obj.name) can return List[str] or List[jack.Port]
                # These are the destination ports for the current output port.
                connected_dest_items = client.get_all_connections(port_obj.name)
                for item in connected_dest_items:
                    dest_name = item.name if isinstance(item, jack.Port) else item
                    connections.append((port_obj.name, dest_name))
        return connections
    except jack.JackError:
        # Log error or handle
        return []

def get_jack_clients(client: jack.Client) -> List[str]:
    """
    Gets a list of all JACK client names.
    """
    try:
        # The jack.Client object itself doesn't have a direct method to list all *other* clients.
        # This typically involves iterating ports and extracting client names,
        # or using lower-level JACK API calls if available through the `jack` library.
        # A common way is to get all ports and derive client names from port names.
        all_ports = get_all_jack_ports(client)
        client_names = set()
        for port in all_ports:
            client_name = port.name.split(':')[0]
            client_names.add(client_name)
        return sorted(list(client_names))
    except jack.JackError:
        return []

# Example of a more specific utility if needed:
def get_jack_connections_for_port(client: jack.Client, port: jack.Port) -> List[str]:
    """
    Gets all connections for a specific jack.Port object.
    Returns a list of names of connected ports.
    """
    try:
        connected_items = client.get_all_connections(port.name)
        return [item.name if isinstance(item, jack.Port) else item for item in connected_items]
    except jack.JackError:
        return []