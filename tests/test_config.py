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
IMPORTABLE_COMMANDS = [
    "challenges",
    "devel/build",
    "devel/clean",
    "devel/run",
    "init_sd_card",
    "duckiebot/update",
    "duckiebot/dashboard",
    "duckiebot/clean",
    "disk_image/create",
]

# Timeout for command tests (in seconds)
COMMAND_TIMEOUT = 10
