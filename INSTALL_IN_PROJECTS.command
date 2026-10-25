#!/bin/bash
# Optional convenience installer; use explicit Terminal commands in README if preferred.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/Projects/ProofNotesAI"
mkdir -p "$HOME/Projects"
if [ "$SRC" = "$DEST" ]; then
  echo "Already installed in $DEST"
  exit 0
fi
if [ ! -e "$DEST" ] && [ -d "$HOME/Downloads/ProofNotesAI" ] && [ "$SRC" != "$HOME/Downloads/ProofNotesAI" ]; then
  mv "$HOME/Downloads/ProofNotesAI" "$DEST"
fi
mkdir -p "$DEST"
# The source archive intentionally has no .env, live database or uploads.
# Keep all existing user data, configuration and Python environment.
rsync -a \
  --exclude=.env --exclude=.venv/ --exclude=app/data/ --exclude=__pycache__/ \
  "$SRC/" "$DEST/"
chmod +x "$DEST/"*.command
printf '\nProofNotes installed at: %s\n' "$DEST"
printf 'Next: cd "%s" && ./setup_models_mac.command && ./run_mac.command\n' "$DEST"
