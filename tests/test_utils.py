"""
Utility functions for testing duckietown-shell-commands.
"""
import importlib.util
import os
import sys
from typing import Optional


def get_command_path(command_name: str) -> str:
    """
    Get the full path to a command module.
    
    Args:
        command_name: The command name (e.g., "devel/info")
    
    Returns:
        Full path to the command.py file
    """
    from test_config import REPO_ROOT
    
    parts = command_name.split("/")
    command_path = os.path.join(REPO_ROOT, *parts, "command.py")
    return command_path


def command_exists(command_name: str) -> bool:
    """
    Check if a command exists.
    
    Args:
        command_name: The command name (e.g., "devel/info")
    
    Returns:
        True if the command exists, False otherwise
    """
    command_path = get_command_path(command_name)
    return os.path.exists(command_path)


def import_command(command_name: str) -> Optional[object]:
    """
    Import a command module dynamically.
    
    Args:
        command_name: The command name (e.g., "devel/info")
    
    Returns:
        The imported module or None if import fails
    """
    try:
        command_path = get_command_path(command_name)
        if not os.path.exists(command_path):
            return None
        
        # Create a unique module name
        module_name = f"test_command_{command_name.replace('/', '_')}"
        
        # Load the module
        spec = importlib.util.spec_from_file_location(module_name, command_path)
        if spec is None or spec.loader is None:
            return None
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        return module
    except Exception as e:
        print(f"Failed to import {command_name}: {e}")
        return None


def validate_command_structure(module) -> bool:
    """
    Validate that a command module has the required structure.
    
    Args:
        module: The imported command module
    
    Returns:
        True if the module has the required structure, False otherwise
    """
    if module is None:
        return False
    
    # Check for DTCommand class
    if not hasattr(module, "DTCommand"):
        return False
    
    dt_command = module.DTCommand
    
    # Check for required methods
    if not hasattr(dt_command, "command"):
        return False
    
    # The command method should be a static method or callable
    if not callable(getattr(dt_command, "command", None)):
        return False
    
    return True
