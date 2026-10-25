# ProofNotes Studio V14 — Recall accuracy fix

Recall Lab quick cards no longer mistake notation examples (such as `INFIX: 3 * (5 + 7) - 9`) for definitions. Cards without supported answers are skipped instead of guessed. The optional AI Challenge cache is invalidated so previously accepted bad cards cannot reappear.

## Update existing Mac installation

Stop the app (`Ctrl+C`), download `ProofNotes_Studio_V14_Recall_Accuracy_Fix.zip`, and run:

```bash
mkdir -p "$HOME/Projects/ProofNotesAI_backups"
cd "$HOME/Projects/ProofNotesAI"
if [ -f app/data/proofnotes_local.sqlite3 ]; then
  cp -p app/data/proofnotes_local.sqlite3 "$HOME/Projects/ProofNotesAI_backups/notes_$(date +%Y%m%d_%H%M%S).sqlite3"
fi
ditto -x -k "$HOME/Downloads/ProofNotes_Studio_V14_Recall_Accuracy_Fix.zip" "$HOME/Projects"
cd "$HOME/Projects/ProofNotesAI"
chmod u+x ./*.command
bash ./run_mac.command
```

`bash ./run_mac.command` works even when ZIP extraction loses execute permissions. No model downloads/reindexing needed; the archive excludes databases, uploaded files and `.env`. Quick Recall never calls a model and may return fewer questions when source evidence is insufficient. Optional AI Challenge is model-generated and **not guaranteed correct**—always inspect evidence for important claims.
