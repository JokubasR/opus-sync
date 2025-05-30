#!/usr/bin/env python3
"""
Test runner for opus_sync tests.
Run this script to execute all tests.
"""
import sys
import pytest

if __name__ == "__main__":
    print("Running opus_sync tests...")
    # -v for verbose output, -x to exit immediately on first failure
    sys.exit(pytest.main(["-v", "-x", "tests/"]))
