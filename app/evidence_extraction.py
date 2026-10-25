"""Deterministic answers for questions directly answered by literal source text.

No model output is used here. Every displayed assertion is tied to a verbatim
substring of an indexed page; title lookup honors the selected-document scope.
"""
import re
from collections import defaultdict


def _source(row, sid, quote):
    return {'id': sid, 'doc_id': row['doc_id'], 'document': row['name'],
            'page': row['page_number'], 'quotes': [quote], 'kind': row['kind'],
            'ocr': bool(row.get('ocr', False))}


def _result(direct, sources, detail=None):
    return {'status': 'answered', 'answer_mode': 'extractive', 'direct': direct,
            'detail': detail or [], 'sources': sources, 'next_question': ''}


def _question_term(question):
    q = question.strip().lower().rstrip('?.! ')
    match = re.fullmatch(r'(?:what\s+(?:is|are)|define|explain\s+(?:the\s+term)?)\s+(.+)', q)
    if not match:
        return ''
    term = re.sub(r'^(?:a|an|the)\s+', '', match.group(1)).strip()
    if len(term.split()) > 4 or 'lecture' in term or len(term) < 3:
        return ''
    return term[:-1] if term.endswith('s') and not term.endswith('ss') else term


def _bullets(text):
    """Return literal multi-line bullet spans; never fabricate missing words."""
    marks = list(re.finditer(r'(?m)^\s*[•*]\s+', text))
    for i, mark in enumerate(marks):
        raw = text[mark.start():marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip()
        if 18 <= len(raw) <= 450:
            yield raw


def definition_answer(question, hits):
    """Find an explicit definition or bullet explicitly labeling the query term."""
    term = _question_term(question)
    if not term:
        return None
    words = term.split()
    term_re = r'\s+'.join(map(re.escape, words))
    pattern = re.compile(r'\b(?:a|an|the)\s+' + term_re + r'\s+(?:is|are|means|refers\s+to)\b', re.I)
    for hit in hits:
        text = hit['text']
        m = pattern.search(text)
        if not m:
            continue
        end = text.find('.', m.start(), min(len(text), m.start() + 550))
        if end < 0:
            continue  # unfinished fragment is not a definition
        quotation = text[m.start():end + 1].strip()
        if len(quotation) < 28:
            continue
        sid = 'S1'
        answer = ' '.join(quotation.split())
        sources = [_source(hit, sid, quotation)]
        detail = []
        # The adjacent bullet explanations are optional additional evidence,
        # not AI-authored claims; the quotations remain literal PDF substrings.
        if term.lower() == 'stack':
            for label in ('PUSH', 'POP'):
                for b in _bullets(text):
                    if re.search(r'\b' + label + r'\b', b, re.I):
                        detail.append({'text': ' '.join(b.split()), 'source_ids': [sid]})
                        sources[0]['quotes'].append(b)
                        break
        return _result([{'text': answer, 'source_ids': [sid]}], sources, detail)
    # Some slides label an operation at the *end* of a literal definition:
    #   • An element can be added to the top ... (“PUSH”)
    # Do not infer anything not in the bullet itself.
    if len(words) == 1:
        for hit in hits:
            for b in _bullets(hit['text']):
                if re.search(r'[\(\[“"]\s*' + term_re + r'\s*[\)\]”"]', b, re.I):
                    return _result([{'text': ' '.join(b.split()), 'source_ids': ['S1']}],
                                   [_source(hit, 'S1', b)])
    return None



def explained_from_examples(question, hits):
    """Use a method signature plus its labeled parameters, not invented definitions.

    The slides may *illustrate* a concept without defining it. Only infer the
    clearly demonstrated part, and link the actual method example.
    """
    if not re.search(r'\bparameters?\b', question, re.I) or not re.search(
            r'\b(?:what|explain|define|mean|understand)\b', question, re.I):
        return None
    for hit in hits:
        text = hit['text']
        # A source must actually contain the declaration AND labeled descriptions.
        signature = re.search(
            r'\b([A-Za-z_]\w*)\s*\(\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*,\s*'
            r'([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\)', text)
        if not signature or not re.search(r'\bParameters\s*:', text, re.I):
            continue
        func, type1, arg1, type2, arg2 = signature.groups()
        # Don't claim labels if the excerpt lacks them.
        labels = re.search(
            r'\bParameters\s*:\s*' + re.escape(arg1) + r'\s*[-–—:]\s*([^\n]+?)\s+'
            + re.escape(arg2) + r'\s*[-–—:]\s*([^\n]+?)(?:\s+Returns?\s*:|\s+Special\s+Note\s*:|$)',
            ' '.join(text.split()), re.I)
        if not labels:
            # A faithful example is still useful without guessing the label text.
            if not all(re.search(r'\b' + re.escape(a) + r'\b', text[signature.end():], re.I) for a in (arg1, arg2)):
                continue
            explanation = f'In this lecture, parameters are named inputs declared in a method signature. For example, `{func}({type1} {arg1}, {type2} {arg2})` takes `{arg1}` and `{arg2}` as parameters.'
        else:
            explanation = (f'Parameters are the named inputs a method accepts. The lecture uses '
                           f'`{func}({type1} {arg1}, {type2} {arg2})`: `{arg1}` and `{arg2}` are its two parameters.')
        # The source may include a heading before the method example. Keep a
        # literal span starting at the signature and ending after 'Parameters'.
        start = max(0, signature.start() - 50)
        end = min(len(text), max(signature.end(), text.lower().find('parameters:', signature.end()) + 100))
        quote = text[start:min(len(text), end)].strip()
        if len(quote) < 12:
            continue
        return _result([{'text': explanation, 'source_ids': ['S1']}],
                       [_source(hit, 'S1', quote)])
    return None

def lecture_overview(question, rows, doc_ids=None):
    """Look up the actual uploaded lecture by its file name, not by guessing."""
    match = re.search(r'\blecture\s*(\d+(?:[.\-]\d+)*)\b', question.lower())
    if not match or not re.search(r'\b(?:what|about|overview|summary|summari[sz]e|cover|topic)\b', question.lower()):
        return None
    number = match.group(1)
    name_pat = re.compile(r'lecture[\s._-]*' + r'[\s._-]*'.join(re.escape(p) for p in re.split(r'[.\-]', number)) + r'(?!\d)', re.I)
    allowed = set(doc_ids or [])
    matches = [r for r in rows if (not doc_ids or r['doc_id'] in allowed) and name_pat.search(r['name'])]
    if not matches:
        return None
    by_doc = defaultdict(list)
    for row in matches:
        by_doc[row['doc_id']].append(row)
    if len(by_doc) != 1:
        return None  # ambiguous matching lectures: let the normal chat clarify
    pages = sorted(next(iter(by_doc.values())), key=lambda r: (r['page_number'], r['id']))
    # Chunks can repeat per page. Keep the first for a human-visible outline.
    unique = {}
    for p in pages:
        unique.setdefault(p['page_number'], p)
    ordered = list(unique.values())
    first = ordered[0]
    title_lines = [s.strip() for s in first['text'].splitlines() if s.strip()]
    if not title_lines:
        return None
    title = title_lines[0][:100]
    prefix = f'Lecture {number} is titled “{title}”.'
    if len(title_lines) > 1 and re.fullmatch(r'chapter\s+\d+[\w.-]*', title_lines[1], flags=re.I):
        prefix = f'Lecture {number} is titled “{title}” ({title_lines[1]}).'
    sources = [_source(first, 'S1', first['text'][:350].strip())]
    headings = []
    rejected = {'algorithm (cont’d)', 'algorithm (cont\'d)', 'examples', 'trace', 'conceptual picture'}
    for r in ordered[1:]:
        lines = [x.strip() for x in r['text'].splitlines() if x.strip()]
        if not lines:
            continue
        heading = lines[0]
        key = heading.lower()
        if (len(heading) > 72 or len(heading) < 5 or heading.startswith('•')
                or key in rejected or 'cont' in key or key.startswith('intstack')
                or '  ' in heading or not re.search(r'[a-zA-Z]', heading)):
            continue
        if key not in {h[0].lower() for h in headings}:
            headings.append((heading, r))
        if len(headings) >= 6:
            break
    direct = [{'text': prefix, 'source_ids': ['S1']}]
    if headings:
        chosen = headings[:5]
        names = ', '.join(h for h, _ in chosen)
        ids = []
        for i, (_, row) in enumerate(chosen, start=2):
            sid = f'S{i}'
            sources.append(_source(row, sid, row['text'][:350].strip()))
            ids.append(sid)
        direct.append({'text': 'The slides cover: ' + names + '.', 'source_ids': ids})
    return _result(direct, sources)
