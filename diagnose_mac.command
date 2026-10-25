#!/bin/bash
# Read-only local diagnostics. No document content is uploaded or printed.
set -euo pipefail
cd "$(dirname "$0")"
echo "ProofNotes local diagnostics"
echo "Project: $PWD"
echo
if [ -f .env ]; then
  grep -E '^(ANSWER_MODEL|EMBEDDING_MODEL|VERIFY_ANSWERS)=' .env || true
fi
if command -v ollama >/dev/null 2>&1; then
  echo; echo 'Installed local Ollama models:'; ollama list
else
  echo 'Ollama executable not found.'
fi
if [ ! -x .venv/bin/python3 ]; then
  echo 'Python virtual environment is missing. Run ./run_mac.command first.'
  exit 0
fi
"$PWD/.venv/bin/python3" - <<'PY'
from app import db
from app.local_models import EMBEDDING_MODEL
print('\nLocal library:')
documents=db.docs()
print(f'Documents: {len(documents)}')
print(f'Indexed chunks: {len(db.rows_all())}')
print(f'Saved conversations: {len(db.chats())}')
for d in documents:
    print(f'  - {d["name"]} | {d["kind"]} | {d["page_count"]} pages | {d["chunk_count"]} passages | {d["ocr_count"]} OCR pages')
if not documents:
    print('No documents have been indexed. Upload a PDF or note before asking source questions.')
print(f'Embedding configuration: {EMBEDDING_MODEL}')
PY
echo
echo 'If notes are present but a question is refused, open its cited passages or try a more specific question.'
