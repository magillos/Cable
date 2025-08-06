"""
Preset Migration Utilities - Helps migrate existing presets to enhanced format
"""

import os
import json
from pathlib import Path


def migrate_presets_to_enhanced():
    """
    Migrate existing presets to the enhanced preset system.
    
    This creates empty layout files for existing connection presets,
    allowing them to work with the enhanced system while preserving
    backward compatibility.
    
    Returns:
        tuple: (migrated_count, error_count) - number of presets migrated and errors encountered
    """
    config_dir = Path.home() / ".config" / "cable"
    presets_dir = config_dir / "presets"
    layout_presets_dir = config_dir / "layout_presets"
    
    if not presets_dir.exists():
        print("No presets directory found - nothing to migrate")
        return 0, 0
    
    # Ensure layout presets directory exists
    layout_presets_dir.mkdir(parents=True, exist_ok=True)
    
    migrated_count = 0
    error_count = 0
    
    # Find all .snap files
    for snap_file in presets_dir.glob("*.snap"):
        preset_name = snap_file.stem
        layout_file = layout_presets_dir / f"{preset_name}.json"
        
        # Skip if layout file already exists
        if layout_file.exists():
            print(f"Layout file already exists for preset '{preset_name}' - skipping")
            continue
        
        try:
            # Create empty layout data
            empty_layout = {
                "node_states": {},
                "graph_zoom_level": 1.0
            }
            
            with open(layout_file, 'w') as f:
                json.dump(empty_layout, f, indent=4)
            
            print(f"Created empty layout file for preset '{preset_name}'")
            migrated_count += 1
            
        except Exception as e:
            print(f"Error creating layout file for preset '{preset_name}': {e}")
            error_count += 1
    
    return migrated_count, error_count


def check_migration_needed():
    """
    Check if migration is needed by looking for presets without layout data.
    
    Returns:
        bool: True if migration is needed, False otherwise
    """
    config_dir = Path.home() / ".config" / "cable"
    presets_dir = config_dir / "presets"
    layout_presets_dir = config_dir / "layout_presets"
    
    if not presets_dir.exists():
        return False
    
    # Check if any .snap files don't have corresponding .json files
    for snap_file in presets_dir.glob("*.snap"):
        preset_name = snap_file.stem
        layout_file = layout_presets_dir / f"{preset_name}.json"
        
        if not layout_file.exists():
            return True
    
    return False


def auto_migrate_if_needed():
    """
    Automatically migrate presets if needed.
    
    This is called when the application starts to ensure
    existing presets work with the enhanced system.
    
    Returns:
        bool: True if migration was performed, False otherwise
    """
    if check_migration_needed():
        print("Migrating existing presets to enhanced format...")
        migrated_count, error_count = migrate_presets_to_enhanced()
        
        if migrated_count > 0:
            print(f"Successfully migrated {migrated_count} presets to enhanced format")
        
        if error_count > 0:
            print(f"Encountered {error_count} errors during migration")
        
        return migrated_count > 0
    
    return False


if __name__ == "__main__":
    """Allow running as standalone script for manual migration."""
    print("Cable Preset Migration Utility")
    print("=" * 40)
    
    if check_migration_needed():
        print("Migration needed - starting migration...")
        migrated_count, error_count = migrate_presets_to_enhanced()
        
        print(f"\nMigration complete:")
        print(f"  Presets migrated: {migrated_count}")
        print(f"  Errors encountered: {error_count}")
        
        if error_count == 0:
            print("\nAll presets successfully migrated!")
        else:
            print(f"\nMigration completed with {error_count} errors - check output above")
    else:
        print("No migration needed - all presets are already compatible")