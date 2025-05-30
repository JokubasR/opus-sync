#!/usr/bin/env bash
set -euo pipefail

# Check if we should run tests
if [ "${1:-}" = "test" ]; then
    echo "Running tests..."
    # Run tests with -v for verbose output and fail immediately on first error
    exec python -m pytest -v -x tests/
else
    # Run the main application
    exec python opus_sync.py
fi
