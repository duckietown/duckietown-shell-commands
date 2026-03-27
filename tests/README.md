# Duckietown Shell Commands Test Suite

This directory contains a testing suite that uses `dt_shell` to actually import and validate commands in the duckietown-shell-commands repository.

## Overview

The test suite validates:
- Command modules exist and can be imported using dt_shell
- Command modules have the required structure (DTCommand class inheriting from DTCommandAbs)
- Commands have the required methods (command method is callable)
- Repository structure is correct (configuration files, requirements, etc.)

## Requirements

The test suite requires `duckietown-shell` to be installed:

```bash
pip install -r tests/requirements.txt
```

## Running Tests

### Run all tests

```bash
python3 tests/run_tests.py
```

### Run specific test file

```bash
python3 -m unittest tests.test_commands
```

### Run specific test class

```bash
python3 -m unittest tests.test_commands.TestCommandImport
```

### Run with different verbosity

```bash
# Quiet mode
python3 tests/run_tests.py -q

# Verbose mode
python3 tests/run_tests.py -v
```

## Test Structure

```
tests/
├── __init__.py           # Test package initialization
├── test_config.py        # Test configuration and command lists
├── test_utils.py         # Utility functions for importing and validating commands
├── test_commands.py      # Main test cases
├── run_tests.py          # Test runner script
├── requirements.txt      # Test dependencies (duckietown-shell)
└── README.md             # This file
```

## Test Categories

### TestCommandExistence
Tests that all specified commands exist in the repository.

### TestCommandImport
Tests that all specified commands can be imported successfully using dt_shell.

### TestCommandStructure
Tests that all commands:
- Have a DTCommand class that inherits from DTCommandAbs
- Have a callable 'command' method

### TestRepositoryStructure
Tests that the repository has the required configuration files and they can be imported.

### TestCommandCount
Tests that the repository has a reasonable number of commands (>10).

## Adding New Tests

To add new commands to test, edit `tests/test_config.py` and add the command path to the `IMPORTABLE_COMMANDS` list.

**Note:** Only add commands that can be imported without additional dependencies beyond what's in `__command_set__/requirements.txt`.

Example:
```python
IMPORTABLE_COMMANDS = [
    "challenges",
    "devel/info",
    "your/new/command",  # Add your command here
]
```

## CI Integration

The test suite is integrated into GitHub Actions via `.github/workflows/test.yml`. It runs on:
- Python 3.8, 3.9, and 3.10
- Push to main branches (main, master, daffy, ente)
- Pull requests to main branches

## How It Works

Unlike static analysis, this test suite actually imports commands using Python's `importlib`:

```python
# Import a command dynamically
module, error = import_command("devel/info")

# Validate it has the correct structure
is_valid, error = validate_command_structure(module)

# Check it inherits from DTCommandAbs
from dt_shell import DTCommandAbs
assert issubclass(module.DTCommand, DTCommandAbs)
```

This ensures that commands are compatible with the latest duckietown shell release.
