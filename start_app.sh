#!/bin/bash
# Starts the SLT AI Employee web app on http://localhost:8000
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run ./setup.sh first."
  exit 1
fi
exec .venv/bin/python app.py
