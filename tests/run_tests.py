#!/usr/bin/env python3
"""
Test runner for duckietown-shell-commands.

This script runs the test suite and reports results.
"""
import sys
import unittest
import os

# Add the repository root to the Python path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def run_tests(verbosity=2):
    """
    Run all tests in the tests directory.
    
    Args:
        verbosity: Level of verbosity (0-2)
    
    Returns:
        True if all tests passed, False otherwise
    """
    # Discover and run tests
    loader = unittest.TestLoader()
    start_dir = os.path.join(REPO_ROOT, 'tests')
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    # Parse command line arguments
    verbosity = 2
    if len(sys.argv) > 1:
        if sys.argv[1] == "-v":
            verbosity = 2
        elif sys.argv[1] == "-q":
            verbosity = 0
    
    print("=" * 70)
    print("Duckietown Shell Commands Test Suite")
    print("=" * 70)
    print()
    
    success = run_tests(verbosity=verbosity)
    
    print()
    print("=" * 70)
    if success:
        print("✓ All tests passed!")
        sys.exit(0)
    else:
        print("✗ Some tests failed!")
        sys.exit(1)
