"""
Utility functions for testing duckietown-shell-commands.
"""
import importlib.util
import os
import sys
from typing import Optional, Tuple


def get_command_path(command_name: str) -> str:
    """
    Get the full path to a command module.
    
    Args:
        command_name: The command name (e.g., "devel/info")
    
    Returns:
        Full path to the command.py file
    """
    from tests.test_config import REPO_ROOT
    
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


def import_command(command_name: str) -> Tuple[Optional[object], Optional[str]]:
    """
    Import a command module dynamically using dt_shell.
    
    Args:
        command_name: The command name (e.g., "devel/info")
    
    Returns:
        Tuple of (imported module or None, error message or None)
    """
    from tests.test_config import REPO_ROOT
    
    try:
        command_path = get_command_path(command_name)
        if not os.path.exists(command_path):
            return None, f"Command file not found: {command_path}"
        
        # Add repo root to path if not already there
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        
        # Create a module name from the command path
        module_name = command_name.replace("/", ".")
        
        # Load the module using importlib
        spec = importlib.util.spec_from_file_location(module_name, command_path)
        if spec is None or spec.loader is None:
            return None, f"Failed to create module spec for {command_name}"
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        return module, None
        
    except Exception as e:
        return None, f"Failed to import {command_name}: {type(e).__name__}: {e}"


def validate_command_structure(module) -> Tuple[bool, Optional[str]]:
    """
    Validate that a command module has the required structure using dt_shell.
    
    Args:
        module: The imported command module
    
    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str])
    """
    if module is None:
        return False, "Module is None"
    
    # Check for DTCommand class
    if not hasattr(module, "DTCommand"):
        return False, "Module does not have DTCommand class"
    
    dt_command = module.DTCommand
    
    # Verify it's a class
    if not isinstance(dt_command, type):
        return False, "DTCommand is not a class"
    
    # Check that it inherits from DTCommandAbs
    try:
        from dt_shell import DTCommandAbs
        if not issubclass(dt_command, DTCommandAbs):
            return False, "DTCommand does not inherit from DTCommandAbs"
    except ImportError as e:
        return False, f"Cannot import DTCommandAbs: {e}"
    except TypeError:
        return False, "DTCommand cannot be checked with issubclass"
    
    # Check for required methods
    if not hasattr(dt_command, "command"):
        return False, "DTCommand does not have 'command' method"
    
    # The command method should be callable
    if not callable(getattr(dt_command, "command", None)):
        return False, "'command' attribute is not callable"
    
    return True, None
