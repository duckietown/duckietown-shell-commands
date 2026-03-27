"""
Configuration for duckietown-shell-commands tests.
"""
import os

# Test configuration
TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TEST_ROOT)

# Commands to test - organized by priority and safety
# Safe commands that don't require special permissions or external resources
SAFE_COMMANDS = [
    "devel/info",
    "devel/bump",
    "cli",
]

# Commands that can be imported and checked for structure
# These commands can be successfully imported with dt_shell installed
IMPORTABLE_COMMANDS = [
    "challenges",
    "devel/info",
    "devel/clean",
    "devel/bump",
    "duckiebot/dashboard",
    "duckiebot/clean",
    "cli",
]

# Timeout for command tests (in seconds)
COMMAND_TIMEOUT = 10
