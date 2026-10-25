#!/bin/bash
# Read-only local smoke test using the user's OWN already indexed lecture.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python3 ]; then
  echo 'First launch ProofNotes with ./run_mac.command to create .venv.'
  exit 1
fi
"$PWD/.venv/bin/python3" - <<'PY'
import json
import sys
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:8765'
def request(route, payload=None):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = Request(BASE + route, data=data, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=90) as r:
        return json.loads(r.read())
try:
    docs = request('/api/documents')['documents']
except (URLError, HTTPError) as e:
    sys.exit('ProofNotes is not running. Open another Terminal and run ./run_mac.command first. ' + str(e))
found = [d for d in docs if 'lecture3.1stackspart1' in d['name'].lower().replace(' ', '')]
if not found:
    sys.exit('Lecture3.1StacksPart1.pdf is not indexed. Upload it in the website, then rerun this check.')
uid = found[0]['id']
for q in ('what is lecture 3.1', 'what are stacks', 'what is PUSH', 'what is POP'):
    res = request('/api/ask', {'question': q, 'model': 'qwen3.6:27b', 'doc_ids': [uid]})
    src = [(s['document'], s['page']) for s in res.get('sources', [])]
    print('\nQuestion:', q)
    print('Result:', res['status'], '-', ' '.join(x['text'] for x in res.get('direct', [])))
    print('Sources:', src)
    if res['status'] != 'answered':
        sys.exit('FAILED: relevant uploaded evidence was not answered.')
    if q.lower() in ('what are stacks', 'what is push', 'what is pop') and not any(p == 2 for _, p in src):
        sys.exit('FAILED: expected page 2 of Lecture3.1StacksPart1.pdf.')
print('\nPASS: all four source-grounded questions answered using local indexed notes.')
PY
