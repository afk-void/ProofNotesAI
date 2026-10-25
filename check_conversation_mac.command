#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
"$PWD/.venv/bin/python3" - <<'PY'
import json
from urllib.request import Request, urlopen
BASE = 'http://127.0.0.1:8765'
def api(path, payload=None, method=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(BASE+path, data=data, method=method, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=150) as resp:
        return json.loads(resp.read())
try:
    docs = api('/api/documents')['documents']
except Exception as exc:
    raise SystemExit('Please start ProofNotes with ./run_mac.command first. ' + str(exc))
matched = [d for d in docs if 'lecture3.1' in d['name'].lower() and 'stack' in d['name'].lower()]
if not matched:
    raise SystemExit('Lecture3.1StacksPart1.pdf is not indexed. Upload it before running this check.')
chat_id = api('/api/chats', {'doc_ids':[matched[0]['id']]})['chat']['id']
questions = ['Hi', 'What are stacks?', 'Can you let me know more stuff regarding stacks?', 'What is this?']
try:
    for question in questions:
        r = api('/api/chats/'+chat_id+'/ask', {'question':question,'model':'qwen3.6:27b','response_mode':'notes'})
        print('\nQUESTION:',question)
        print('STATUS:',r['status'], 'KIND:',r.get('answer_mode','conversation'))
        print('ANSWER:', ' '.join(s['text'] for s in r.get('direct',[]))[:320])
        print('PAGES:',sorted({x.get('page') for x in r.get('sources',[]) if x.get('page')}))
        if question!='Hi' and r['status']!='answered':
            raise SystemExit('FAIL: failed to answer the indexed lecture question.')
    print('\nPASS: source-grounded conversational checks passed.')
finally:
    api('/api/chats/'+chat_id, method='DELETE')
PY
