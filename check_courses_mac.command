#!/bin/zsh
set -e
cd "$(dirname "$0")"
./.venv/bin/python - <<'PY'
import json
import urllib.request
base='http://127.0.0.1:8765'
def get(path):
    return json.load(urllib.request.urlopen(base+path, timeout=8))
try:
    docs=get('/api/documents')['documents']
    courses=get('/api/courses')['courses']
except Exception as exc:
    raise SystemExit(f'Start ProofNotes with ./run_mac.command first. ({exc})')
print(f'Indexed files: {len(docs)}; courses: {len(courses)}')
for c in courses:
    files=[d['name'] for d in docs if d['course_id']==c['id']]
    print(f'  {c["name"]}: {len(files)} file(s)')
    for name in files:print('    -',name)
payload=json.dumps({'model':'qwen3.6:27b','doc_ids':[]}).encode()
req=urllib.request.Request(base+'/api/recall',data=payload,headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req,timeout=30) as response:
        cards=json.load(response)['cards']
except Exception as exc:
    raise SystemExit(f'Recall request failed: {exc}')
print(f'Recall cards from entire library: {len(cards)}')
if len(docs)>1 and len(cards)<2:
    raise SystemExit('FAIL: Multiple documents indexed, but too few recall cards.')
for c in cards[:5]:print('  -',c['question'])
print('PASS: Library metadata and recall endpoint responded.')
PY
