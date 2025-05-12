# --- PyQt Graphical Items ---
#
# This file has been refactored. Its contents have been moved to:
# - port_item.py (for PortItem class)
# - bulk_area_item.py (for BulkAreaItem class)
# - node_item.py (for NodeItem class and natural_sort_key function)
# - connection_item.py (for ConnectionItem class)
#
# This file is kept to avoid breaking existing imports immediately,
# but it should no longer be directly used for new development.
# Consider updating imports to point to the new specific files.

# Common imports that might have been used by multiple items (if any)
# can be left here, or preferably, each new file should manage its own imports.
# For this refactoring, all specific imports were moved with their respective classes.

# Example of how you might re-export for backward compatibility (optional, not done here):
# from .port_item import PortItem
# from .node_item import NodeItem, natural_sort_key
# from .connection_item import ConnectionItem
# from .bulk_area_item import BulkAreaItem

# For now, this file is intentionally left almost empty.
