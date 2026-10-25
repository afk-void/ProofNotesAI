#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Missing local virtual environment. Run ./run_mac.command once.'
  exit 1
fi
.venv/bin/python - <<'PY'
from app import db
from app.ai import recall_cards

docs=[d for d in db.docs() if d['name'].lower() == 'lecture3.1stackspart1.pdf']
if not docs:
    raise SystemExit('Stacks lecture not indexed here. Upload Lecture3.1StacksPart1.pdf in ProofNotes first.')
for doc in docs:
    cards=recall_cards('qwen3.6:27b',[doc['id']])
    pages=sorted({card['source']['page'] for card in cards})
    print(f'{doc["name"]}: {len(cards)} verified-page recall cards, spanning {len(pages)} distinct pages')
    print('Covered pages:', ', '.join(map(str,pages)))
    assert len(cards)>=30, 'Fewer than 30 cards — verify the PDF indexing and extraction.'
    for card in cards:
        src=card['source']
        assert src['quotes'][0] in db.pages_for(src['doc_id'],src['page'])['text']
    print('PASS: every card links to a verbatim excerpt on the cited PDF page.')
PY
