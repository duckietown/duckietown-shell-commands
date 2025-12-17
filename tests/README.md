# Duckietown Shell Commands Test Suite

This directory contains a simple testing suite to ensure that the commands run correctly in the latest duckietown shell release.

## Overview

The test suite validates:
- Command modules exist and can be imported
- Command modules have the required structure (DTCommand class with command method)
- Repository structure is correct (configuration files, requirements, etc.)

## Running Tests

### Run all tests

```bash
python3 tests/run_tests.py
```

### Run specific test file

```bash
python3 -m unittest tests.test_commands
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
├── test_utils.py         # Utility functions for testing
├── test_commands.py      # Main test cases
├── run_tests.py          # Test runner script
└── README.md             # This file
```

## Test Categories

### TestCommandExistence
Tests that all specified commands exist in the repository.

### TestCommandImport
Tests that all specified commands can be imported successfully.

### TestCommandStructure
Tests that all commands have the required structure (DTCommand class with command method).

### TestRepositoryStructure
Tests that the repository has the required configuration files.

## Adding New Tests

To add new commands to test, edit `tests/test_config.py` and add the command path to the `IMPORTABLE_COMMANDS` list.

Example:
```python
IMPORTABLE_COMMANDS = [
    "challenges",
    "devel/info",
    "your/new/command",  # Add your command here
]
```

## CI Integration

The test suite can be integrated into CI/CD pipelines. See `.github/workflows/test.yml` for the GitHub Actions configuration.

## Requirements

The test suite uses only Python standard library modules (unittest, importlib, os, sys) and does not require additional dependencies beyond those already specified in `__command_set__/requirements.txt`.
