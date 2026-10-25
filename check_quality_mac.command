#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python3 ]; then
  echo 'Python virtual environment not found. Launch ./run_mac.command once first.' >&2
  exit 1
fi
exec .venv/bin/python3 quality_check.py --model qwen3.6:27b
