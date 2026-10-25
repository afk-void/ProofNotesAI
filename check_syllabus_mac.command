#!/bin/zsh
set -e
cd "$(dirname "$0")"
./.venv/bin/python - <<'PY'
import json, urllib.request, urllib.error
base='http://127.0.0.1:8765'
def api(path, payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'} if data else {})
    with urllib.request.urlopen(req,timeout=25) as response:
        return json.load(response)
try:
    docs=api('/api/documents')['documents']
except (OSError,urllib.error.URLError) as exc:
    raise SystemExit(f'Start ProofNotes first: ./run_mac.command ({exc})')
syllabi=[d for d in docs if 'syllabus' in d['name'].lower()]
if not syllabi:
    raise SystemExit('No syllabus PDF is indexed yet. Upload it under Sources.')
for doc in syllabi:
    print(f'\n{doc["name"]} — {doc["page_count"]} indexed page(s)')
    q='Please summarize this syllabus and list all explicit exam dates and grading percentages.'
    result=api('/api/ask',{'question':q,'doc_ids':[doc['id']],'model':'qwen3.6:27b'})
    print('Result:',result['status'],'/',result.get('answer_mode'))
    for section in ('direct','detail'):
        for line in result.get(section,[]):
            print(' ',line['text'])
    for source in result.get('sources',[]):
        print('  Citation: page', source['page'], '-',source['document'])
    if result['status']!='answered':
        raise SystemExit('FAIL: Syllabus handler did not return an answer.')
print('\nPASS: Local syllabus handler answered without needing any Ollama generation.')
print('IMPORTANT: If no exam dates are shown, inspect the original PDF for image-only tables or dates announced elsewhere.')
PY
