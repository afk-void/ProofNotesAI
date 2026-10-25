"""Safe source-derived lecture overviews when rigid model JSON fails or isn't necessary."""
import re
from collections import defaultdict

from .evidence_extraction import _source, _result

CATS = (
    ('fundamentals', r'fundamental|introduct|overview|definition|basic concept|principle'),
    ('applications', r'application|real.world|use[sd]?'),
    ('operations', r'operations?|methods?|push|pop|peek'),
    ('implementation', r'implement|array|linked\s+list|structure|representation'),
    ('practice', r'parenthes|algorithms?|exercise|problems?|practice'),
)


def _words(topic):
    return [w for w in re.findall(r'[a-z0-9]+', (topic or '').lower()) if len(w) > 2 and w not in {'this', 'that', 'more', 'about', 'lecture', 'chapter', 'notes'}][:5]


def _score_document(name, pages, terms):
    filename = re.sub(r'[^a-z0-9]', ' ', name.lower())
    title_hits = sum(15 for t in terms if t in filename or (t.endswith('s') and t[:-1] in filename))
    page_hits = sum(1 for row in pages for t in terms if re.search(r'\b'+re.escape(t.rstrip('s'))+r's?\b', row['text'].lower()))
    return title_hits + min(page_hits, 20)


def _heading(row):
    lines = [re.sub(r'\s+', ' ', x).strip() for x in row['text'].splitlines() if x.strip()]
    if not lines:
        return ''
    h = lines[0]
    if h.startswith(('•', '-', '*')) or len(h) > 90 or re.search(r'cont[’\']?d|continued', h, re.I):
        return ''
    return h


def _points(row, maximum=4):
    text = row['text']
    bullets = re.split(r'(?m)\s*[•*]\s+', text)
    if len(bullets) <= 1:
        return ''
    items = []
    for raw in bullets[1:]:
        raw = re.split(r'\n\s*(?:if not |How would |temp |return\(|push\(|\s{4,}if\b)', raw, maxsplit=1)[0]
        item = re.sub(r'\s+', ' ', raw).strip(' -•')
        if len(item) < 16 or re.match(r'^(?:ARRAYS|LINKED LISTS)\b', item, re.I):
            continue
        if len(item) > 250:
            # Cut at a sentence/phrase boundary where possible, not mid-word.
            cut = item[:248].rsplit(' ', 1)[0]
            item = cut.rstrip(' ,;') + '…'
        items.append(item)
        if len(items) >= maximum:
            break
    return '; '.join(items).strip()


def _category(head):
    for cat, expr in CATS:
        if re.search(expr, head, re.I):
            return cat
    return ''


def _priority(cat, head, row):
    lower = head.lower()
    if cat == 'operations':
        return 7 if 'basic' in lower else 6 if 'extended' in lower else 1
    if cat == 'implementation':
        if lower.startswith('implementation') and re.search(r'\b(arrays|linked lists)\b', row['text'], re.I):
            return 7
        return 2
    if cat == 'practice':
        return 6 if 'parenthes' in lower else 3
    return 6 if cat in ('fundamentals', 'applications') else 2


def source_overview(topic, rows, doc_ids=None, *, document_only=False):
    allowed = set(doc_ids or [])
    grouped = defaultdict(list)
    for row in rows:
        if not doc_ids or row['doc_id'] in allowed:
            grouped[row['doc_id']].append(row)
    if not grouped:
        return None
    terms = _words(topic)
    if document_only and len(grouped) != 1:
        return None
    ranked = sorted(grouped.items(), key=lambda x: _score_document(x[1][0]['name'], x[1], terms), reverse=True)
    doc_id, document = ranked[0]
    if not document_only and (not terms or _score_document(document[0]['name'], document, terms) == 0):
        return None
    by_page = {}
    for row in sorted(document, key=lambda r: (r['page_number'], r['id'])):
        by_page.setdefault(row['page_number'], row)
    pages = list(by_page.values())
    if not pages:
        return None
    candidates = []
    for row in pages:
        head = _heading(row)
        if not head or len(row['text']) < 33:
            continue
        cat = _category(head)
        if cat:
            candidates.append((cat, head, row, _priority(cat, head, row)))
    chosen = {}
    for cat, head, row, priority in candidates:
        if cat == 'implementation':
            impl = chosen.setdefault(cat, [])
            if priority >= 6:
                marker = 'linked' if 'linked lists' in row['text'].lower() else 'array' if 'arrays' in row['text'].lower() else 'other'
                if not any(t[3] == marker for t in impl):
                    impl.append((head, row, priority, marker))
        elif cat == 'operations':
            ops = chosen.setdefault(cat, [])
            if priority >= 6:
                marker = 'basic' if 'basic' in head.lower() else 'extended' if 'extended' in head.lower() else 'other'
                if not any(t[3] == marker for t in ops):
                    ops.append((head, row, priority, marker))
        else:
            old = chosen.get(cat)
            if old is None or priority > old[2]:
                chosen[cat] = (head, row, priority)
    selected = []
    for cat in ('fundamentals', 'applications', 'operations', 'implementation', 'practice'):
        found = chosen.get(cat)
        if not found:
            continue
        if cat in ('operations', 'implementation'):
            for head, row, priority, marker in found[:2]:
                selected.append((cat, head, row, marker))
        else:
            head, row, _ = found
            selected.append((cat, head, row, ''))
    if not selected:
        return None
    first = pages[0]
    title = _heading(first) or document[0]['name']
    intro = (f"**{title}** — here are the main topics in this document:" if document_only
             else f"More about **{title}** from your slides:")
    sources = [_source(first, 'S1', first['text'][:550].strip())]
    direct = [{'text': intro, 'source_ids': ['S1']}]
    detail = []
    for cat, head, row, marker in selected[:7]:
        sid = f'S{len(sources)+1}'
        if cat == 'implementation' and marker in ('array', 'linked'):
            text = '**Implementation with ' + ('arrays' if marker == 'array' else 'linked lists') + '**'
        elif cat == 'practice' and 'parenthes' in head.lower():
            text = f'**{head}** — the slides explain what makes parentheses balanced.'
        else:
            points = _points(row)
            text = f'**{head}**' + (f': {points}' if points else '')
        detail.append({'text': text, 'source_ids': [sid]})
        sources.append(_source(row, sid, row['text'][:550].strip()))
    return {**_result(direct, sources, detail), 'answer_mode': 'outline'}
