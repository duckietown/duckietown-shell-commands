"""
Test cases for duckietown-shell-commands.

This test suite verifies that:
1. Command modules exist and are accessible
2. Command modules can be imported using dt_shell
3. Command modules have the required structure (DTCommand class inheriting from DTCommandAbs)
4. Repository structure is correct
"""
import sys
import os
import unittest

# Add the repository root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_config import IMPORTABLE_COMMANDS, REPO_ROOT
from tests.test_utils import command_exists, import_command, validate_command_structure


class TestCommandExistence(unittest.TestCase):
    """Test that commands exist in the repository."""
    
    def test_commands_exist(self):
        """Test that all specified commands exist."""
        missing_commands = []
        
        for command_name in IMPORTABLE_COMMANDS:
            if not command_exists(command_name):
                missing_commands.append(command_name)
        
        self.assertEqual(
            missing_commands,
            [],
            f"The following commands are missing: {missing_commands}"
        )


class TestCommandImport(unittest.TestCase):
    """Test that commands can be imported successfully using dt_shell."""
    
    def test_commands_importable(self):
        """Test that all specified commands can be imported."""
        failed_imports = {}
        
        for command_name in IMPORTABLE_COMMANDS:
            module, error = import_command(command_name)
            if module is None:
                failed_imports[command_name] = error
        
        self.assertEqual(
            failed_imports,
            {},
            f"The following commands failed to import:\n" + 
            "\n".join([f"  {cmd}: {err}" for cmd, err in failed_imports.items()])
        )


class TestCommandStructure(unittest.TestCase):
    """Test that commands have the required structure using dt_shell."""
    
    def test_commands_have_dtcommand_class(self):
        """Test that all commands have a DTCommand class that inherits from DTCommandAbs."""
        invalid_commands = {}
        
        for command_name in IMPORTABLE_COMMANDS:
            module, import_error = import_command(command_name)
            if module is None:
                # Skip if import failed - that's tested in TestCommandImport
                continue
            
            is_valid, error = validate_command_structure(module)
            if not is_valid:
                invalid_commands[command_name] = error
        
        self.assertEqual(
            invalid_commands,
            {},
            f"The following commands have invalid structure:\n" +
            "\n".join([f"  {cmd}: {err}" for cmd, err in invalid_commands.items()])
        )
    
    def test_commands_have_command_method(self):
        """Test that all commands have a callable 'command' method."""
        missing_method = {}
        
        for command_name in IMPORTABLE_COMMANDS:
            module, import_error = import_command(command_name)
            if module is None:
                continue
            
            if not hasattr(module, "DTCommand"):
                continue
            
            dt_command = module.DTCommand
            if not hasattr(dt_command, "command"):
                missing_method[command_name] = "No 'command' method"
            elif not callable(getattr(dt_command, "command", None)):
                missing_method[command_name] = "'command' is not callable"
        
        self.assertEqual(
            missing_method,
            {},
            f"The following commands have issues with command method:\n" +
            "\n".join([f"  {cmd}: {err}" for cmd, err in missing_method.items()])
        )


class TestRepositoryStructure(unittest.TestCase):
    """Test repository structure and configuration."""
    
    def test_command_set_configuration_exists(self):
        """Test that __command_set__/configuration.py exists."""
        config_path = os.path.join(REPO_ROOT, "__command_set__", "configuration.py")
        self.assertTrue(
            os.path.exists(config_path),
            "__command_set__/configuration.py is missing"
        )
    
    def test_command_set_requirements_exists(self):
        """Test that __command_set__/requirements.txt exists."""
        requirements_path = os.path.join(REPO_ROOT, "__command_set__", "requirements.txt")
        self.assertTrue(
            os.path.exists(requirements_path),
            "__command_set__/requirements.txt is missing"
        )
    
    def test_readme_exists(self):
        """Test that README.md exists."""
        readme_path = os.path.join(REPO_ROOT, "README.md")
        self.assertTrue(
            os.path.exists(readme_path),
            "README.md is missing"
        )
    
    def test_command_set_configuration_imports(self):
        """Test that __command_set__/configuration.py can be imported."""
        try:
            sys.path.insert(0, REPO_ROOT)
            from __command_set__.configuration import DTCommandSetConfiguration
            self.assertTrue(True, "Configuration imported successfully")
        except ImportError as e:
            self.fail(f"Failed to import configuration: {e}")


class TestCommandCount(unittest.TestCase):
    """Test that we have a reasonable number of commands."""
    
    def test_multiple_commands_exist(self):
        """Test that we have multiple commands in the repository."""
        # Count all command.py files
        command_count = 0
        for root, dirs, files in os.walk(REPO_ROOT):
            # Skip .git directory
            if '.git' in root:
                continue
            if 'command.py' in files:
                command_count += 1
        
        self.assertGreater(
            command_count,
            10,
            f"Expected at least 10 commands, but found {command_count}"
        )


if __name__ == "__main__":
    unittest.main()
