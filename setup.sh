#!/bin/bash
# One-time setup: creates the .venv folder and installs the Python packages.
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10 or newer is needed. You have: $("$PY" --version 2>&1)"
  exit 1
fi
echo "Creating .venv with $("$PY" --version)..."
"$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
echo "Installing packages (this takes a minute)..."
.venv/bin/python -m pip install --quiet -r requirements.txt
echo ""
echo "Setup done. Next:"
echo "  Terminal 1:  ./start_model.sh"
echo "  Terminal 2:  ./start_app.sh"
