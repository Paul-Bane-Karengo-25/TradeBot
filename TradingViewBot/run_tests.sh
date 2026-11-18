#!/bin/bash
# Runs the full automated test of the app (about 30 seconds, offline, doesn't touch your portfolio).
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "Python was not found. Run setup_mac.sh first."
  exit 1
fi
"$PY" tests/run_tests.py
