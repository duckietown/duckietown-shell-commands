"""
Test cases for duckietown-shell-commands.

This test suite verifies that:
1. Command modules exist and are accessible
2. Command modules have the required structure (DTCommand class with command method)
3. Repository structure is correct
"""
import sys
import os
import unittest
import re

# Add the repository root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_config import IMPORTABLE_COMMANDS, REPO_ROOT
from tests.test_utils import command_exists, get_command_path


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


class TestCommandStructure(unittest.TestCase):
    """Test that commands have the required structure by inspecting source code."""
    
    def test_commands_have_dtcommand_class(self):
        """Test that all commands have a DTCommand class."""
        invalid_commands = []
        
        for command_name in IMPORTABLE_COMMANDS:
            command_path = get_command_path(command_name)
            if not os.path.exists(command_path):
                invalid_commands.append(f"{command_name} (file not found)")
                continue
            
            try:
                with open(command_path, 'r') as f:
                    content = f.read()
                
                # Check for DTCommand class definition
                if not re.search(r'class\s+DTCommand\s*\(', content):
                    invalid_commands.append(f"{command_name} (no DTCommand class)")
                    continue
                
                # Check for command method
                if not re.search(r'def\s+command\s*\(', content):
                    invalid_commands.append(f"{command_name} (no command method)")
                    continue
                    
            except Exception as e:
                invalid_commands.append(f"{command_name} (error reading: {e})")
        
        self.assertEqual(
            invalid_commands,
            [],
            f"The following commands have invalid structure: {invalid_commands}"
        )
    
    def test_commands_import_dtshell(self):
        """Test that all commands import from dt_shell."""
        missing_import = []
        
        for command_name in IMPORTABLE_COMMANDS:
            command_path = get_command_path(command_name)
            if not os.path.exists(command_path):
                continue
            
            try:
                with open(command_path, 'r') as f:
                    content = f.read()
                
                # Check for dt_shell import
                if not re.search(r'from\s+dt_shell\s+import|import\s+dt_shell', content):
                    missing_import.append(command_name)
                    
            except Exception as e:
                missing_import.append(f"{command_name} (error: {e})")
        
        self.assertEqual(
            missing_import,
            [],
            f"The following commands don't import dt_shell: {missing_import}"
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
    
    def test_command_set_has_dtcommandabs(self):
        """Test that __command_set__/configuration.py imports DTCommandSetConfigurationAbs."""
        config_path = os.path.join(REPO_ROOT, "__command_set__", "configuration.py")
        with open(config_path, 'r') as f:
            content = f.read()
        
        self.assertIn(
            "DTCommandSetConfigurationAbs",
            content,
            "__command_set__/configuration.py should import DTCommandSetConfigurationAbs"
        )


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
