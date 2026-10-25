#!/bin/bash
# Relocation-safe macOS launcher for ProofNotes Studio.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
if ! command -v python3 >/dev/null 2>&1; then echo 'Python 3.10+ is required. Install Python 3 and retry.'; exit 1; fi
if ! command -v ollama >/dev/null 2>&1; then echo 'Ollama is required. Install it from https://ollama.com/download/mac'; exit 1; fi
if ! python3 -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then echo 'Python 3.10+ is required.'; exit 1; fi

# Python venv activation scripts embed the original absolute folder path.
# If the project was moved from Downloads to Projects, rebuild only the venv.
if [ -d .venv ]; then
  if [ ! -x .venv/bin/python3 ] || [ ! -f .venv/bin/activate ] || ! grep -Fq "$ROOT/.venv" .venv/bin/activate; then
    echo 'Detected missing or relocated Python environment. Repairing .venv (notes and settings stay untouched)...'
    python3 -m venv --clear .venv
  fi
else
  echo 'Creating local Python environment...'
  python3 -m venv .venv
fi
PY="$ROOT/.venv/bin/python3"
"$PY" -m pip install -q -r requirements.txt

if [ ! -f .env ]; then cp .env.example .env; fi
if ! curl -sf --max-time 3 'http://127.0.0.1:11434/api/tags' >/dev/null 2>&1; then
  open -a Ollama >/dev/null 2>&1 || (ollama serve >/dev/null 2>&1 &)
fi
if ! (lsof -n -iTCP:8765 -sTCP:LISTEN 2>/dev/null | grep -q LISTEN) ; then
  (sleep 2; open 'http://127.0.0.1:8765' >/dev/null 2>&1) &
fi
echo 'ProofNotes — http://127.0.0.1:8765'
echo "Project: $ROOT"
echo 'Press Ctrl+C to stop this server.'
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8765
