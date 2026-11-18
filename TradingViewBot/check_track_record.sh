#!/bin/bash
# Shows how the logged picks (the Track record) have done, without opening the app. Read-only.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "Python was not found. Run setup_mac.sh first."
  exit 1
fi
"$PY" check_track_record.py
