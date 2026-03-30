"""
Additional test cases for duckietown-shell-commands.

These tests provide deeper validation of command quality:
1. Help text quality
2. Parser configuration (for commands using argparse)
3. Autocomplete support
4. Method signatures
5. Documentation quality
"""
import sys
import os
import unittest
import inspect
import re

# Add the repository root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_config import IMPORTABLE_COMMANDS
from tests.test_utils import import_command


def _get_valid_command_modules():
    """
    Helper generator to yield valid imported command modules.
    
    Yields:
        Tuple of (command_name, module, DTCommand class)
    """
    for command_name in IMPORTABLE_COMMANDS:
        module, import_error = import_command(command_name)
        if module is None:
            continue
        
        if not hasattr(module, "DTCommand"):
            continue
        
        yield command_name, module, module.DTCommand


class TestCommandHelpText(unittest.TestCase):
    """Test that commands have meaningful help text."""
    
    def test_commands_have_help_attribute(self):
        """Test that all commands have a 'help' attribute."""
        missing_help = {}
        
        for command_name, module, dt_command in _get_valid_command_modules():
            if not hasattr(dt_command, "help"):
                missing_help[command_name] = "No 'help' attribute"
        
        self.assertEqual(
            missing_help,
            {},
            f"The following commands are missing help text:\n" +
            "\n".join([f"  {cmd}: {err}" for cmd, err in missing_help.items()])
        )
    
    def test_help_text_is_meaningful(self):
        """Test that help text is not just the default template text."""
        default_help = "Brief description of the command"
        stats = {
            'with_help': [],
            'without_help': [],
            'default_help': []
        }
        
        for command_name, module, dt_command in _get_valid_command_modules():
            if hasattr(dt_command, "help"):
                help_text = dt_command.help
                if help_text == default_help:
                    stats['default_help'].append(command_name)
                elif not help_text or len(str(help_text).strip()) < 10:
                    stats['without_help'].append(command_name)
                else:
                    stats['with_help'].append(command_name)
            else:
                stats['without_help'].append(command_name)
        
        # This is informational - we report coverage but don't fail
        total = len(stats['with_help']) + len(stats['without_help']) + len(stats['default_help'])
        if total > 0:
            coverage = len(stats['with_help']) / total * 100
            print(f"\nMeaningful help text coverage: {coverage:.1f}% ({len(stats['with_help'])}/{total} commands)")
            if stats['without_help']:
                print(f"  Commands without help: {', '.join(stats['without_help'])}")
            if stats['default_help']:
                print(f"  Commands with default help: {', '.join(stats['default_help'])}")


class TestCommandMethodSignatures(unittest.TestCase):
    """Test that command methods have correct signatures."""
    
    def test_command_method_signature(self):
        """Test that command methods accept (shell, args) or (shell, args, **kwargs)."""
        invalid_signatures = {}
        
        for command_name, module, dt_command in _get_valid_command_modules():
            if not hasattr(dt_command, "command"):
                continue
            
            try:
                sig = inspect.signature(dt_command.command)
                params = list(sig.parameters.keys())
                
                # Valid signatures:
                # (shell, args)
                # (shell, args, **kwargs)
                if len(params) < 2:
                    invalid_signatures[command_name] = f"Too few parameters: {params}"
                elif params[0] != 'shell':
                    invalid_signatures[command_name] = f"First parameter should be 'shell', got '{params[0]}'"
                elif params[1] != 'args':
                    invalid_signatures[command_name] = f"Second parameter should be 'args', got '{params[1]}'"
                    
            except Exception as e:
                invalid_signatures[command_name] = f"Error inspecting signature: {e}"
        
        self.assertEqual(
            invalid_signatures,
            {},
            f"The following commands have invalid method signatures:\n" +
            "\n".join([f"  {cmd}: {err}" for cmd, err in invalid_signatures.items()])
        )


class TestCommandAutocomplete(unittest.TestCase):
    """Test that commands implement autocomplete functionality."""
    
    def test_commands_have_complete_method(self):
        """Test that commands have a 'complete' method for autocomplete."""
        # Note: complete method is optional, so we just check if it exists and is callable
        stats = {
            'with_complete': [],
            'without_complete': []
        }
        
        for command_name, module, dt_command in _get_valid_command_modules():
            if hasattr(dt_command, "complete") and callable(getattr(dt_command, "complete", None)):
                stats['with_complete'].append(command_name)
            else:
                stats['without_complete'].append(command_name)
        
        # This is informational - we don't fail if complete is missing
        total = len(stats['with_complete']) + len(stats['without_complete'])
        if total > 0:
            coverage = len(stats['with_complete']) / total * 100
            print(f"\nAutocomplete coverage: {coverage:.1f}% ({len(stats['with_complete'])}/{total} commands)")


class TestCommandDocumentation(unittest.TestCase):
    """Test that commands have proper documentation."""
    
    def test_command_method_has_docstring(self):
        """Test that command methods have docstrings."""
        missing_docs = []
        
        for command_name, module, dt_command in _get_valid_command_modules():
            if hasattr(dt_command, "command"):
                command_method = getattr(dt_command, "command")
                if not command_method.__doc__ or len(command_method.__doc__.strip()) < 10:
                    missing_docs.append(command_name)
        
        # This is a soft check - many commands might not have docstrings
        # We just report the coverage
        total = len(IMPORTABLE_COMMANDS)
        with_docs = total - len(missing_docs)
        if total > 0:
            coverage = with_docs / total * 100
            print(f"\nDocstring coverage: {coverage:.1f}% ({with_docs}/{total} commands)")


class TestCommandNameConventions(unittest.TestCase):
    """Test that command names and structures follow conventions."""
    
    def test_command_directories_have_init(self):
        """Test that command directories have __init__.py files."""
        from tests.test_config import REPO_ROOT
        
        missing_init = []
        
        for command_name in IMPORTABLE_COMMANDS:
            parts = command_name.split("/")
            command_dir = os.path.join(REPO_ROOT, *parts)
            init_file = os.path.join(command_dir, "__init__.py")
            
            if not os.path.exists(init_file):
                missing_init.append(command_name)
        
        self.assertEqual(
            missing_init,
            [],
            f"The following command directories are missing __init__.py:\n" +
            "\n".join([f"  {cmd}" for cmd in missing_init])
        )


class TestCommandErrorHandling(unittest.TestCase):
    """Test that commands handle errors appropriately."""
    
    def test_commands_import_dtslogger(self):
        """Test that commands import dtslogger for proper logging."""
        missing_logger = []
        
        for command_name in IMPORTABLE_COMMANDS:
            module, import_error = import_command(command_name)
            if module is None:
                continue
            
            # Check if the module imports dtslogger
            if not hasattr(module, "dtslogger"):
                # Check the source code
                from tests.test_utils import get_command_path
                command_path = get_command_path(command_name)
                try:
                    with open(command_path, 'r') as f:
                        content = f.read()
                    
                    # Check if dtslogger is imported
                    if 'dtslogger' not in content:
                        missing_logger.append(command_name)
                except Exception:
                    # Ignore errors reading files
                    pass
        
        # This is informational - not all commands need logging
        total = len(IMPORTABLE_COMMANDS)
        with_logger = total - len(missing_logger)
        if total > 0:
            coverage = with_logger / total * 100
            print(f"\ndtslogger usage: {coverage:.1f}% ({with_logger}/{total} commands)")


if __name__ == "__main__":
    unittest.main()
