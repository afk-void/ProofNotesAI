"""Literal syllabus answers. Scan full indexed pages, not top-k chunks or model JSON."""
import re

from . import db
from .evidence_extraction import _source

_EXAM = re.compile(r'\b(?:mid[ -]?term|final\s+exam|examination|exam\s*\d*|test\s*\d*)\b', re.I)
_DATE = re.compile(
    r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
    r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?\b'
    r'|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b'
    r'|\b(?:TBA|TBD|to\s+be\s+(?:announced|determined))\b', re.I)
_WEIGHT = re.compile(r'\b(?:midterm|final|quiz|homework|programming|assignments?|recitation|participation|projects?|labs?)\b', re.I)
_PERCENT = re.compile(r'\d+(?:\.\d+)?\s*%')
_SOURCE_QUERY = re.compile(r'\b(?:syllabus|syllabi|exam|midterm|final|grading|grade\s+breakdown|test\s+dates?)\b', re.I)


def _clean(value):
    return ' '.join(value.split())


def _page_rows(rows, doc_id):
    pages = sorted({r['page_number'] for r in rows if r['doc_id'] == doc_id})
    for n in pages:
        p = db.pages_for(doc_id, n)
        if p and p['text'].strip():
            base = next(r for r in rows if r['doc_id'] == doc_id and r['page_number'] == n)
            yield {**base, 'text': p['text']}


def _relevant_lines(page, mode):
    lines = page['text'].splitlines()
    found = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if mode == 'date':
            if not _EXAM.search(line):
                continue
            if _PERCENT.search(line) and not _DATE.search(line):
                continue  # grading percentages are not exam dates
            # Keep original whitespace so the citation is an exact PDF substring.
            start = i - 1 if i and _DATE.search(lines[i-1]) else i
            end = i + 2 if i+1 < len(lines) and _DATE.search(lines[i+1]) else i + 1
            excerpt = '\n'.join(lines[start:end])
            if _DATE.search(excerpt):
                found.append((line, excerpt))
        else:
            # Some PDFs wrap the percentage onto the next line.
            end = i+2 if i+1 < len(lines) and _PERCENT.search(lines[i+1]) else i+1
            candidate = '\n'.join(lines[i:end])
            if _WEIGHT.search(line) and _PERCENT.search(candidate):
                found.append((_clean(candidate), candidate))
    return found


def syllabus_answer(question, rows):
    if not _SOURCE_QUERY.search(question):
        return None
    by_doc = {}
    for row in rows:
        if 'syllabus' in row['name'].lower() or 'syllabi' in row['name'].lower():
            by_doc[row['doc_id']] = row['name']
    if not by_doc:
        return None
    # A course-specific question must not silently select another syllabus.
    course = re.search(r'\b([A-Za-z]{2,4})\s*[- ]?(\d{3})\b', question)
    if course:
        key = f'{course.group(1)}{course.group(2)}'.lower()
        matching = {d:n for d,n in by_doc.items() if key in re.sub(r'[^a-z0-9]','',n.lower())}
        if not matching:
            return None
        by_doc = matching
    if len(by_doc) != 1:
        names = ', '.join(sorted(by_doc.values())[:8])
        return {'status':'conversation', 'answer_mode':'conversation',
                'direct':[{'text':f'I found several syllabi: {names}. Choose the course or select one PDF to get the correct exam dates.', 'source_ids':[]}],
                'detail':[], 'sources':[], 'next_question':''}

    doc_id, filename = next(iter(by_doc.items()))
    pages = list(_page_rows(rows,doc_id))
    if not pages:
        return None
    sources, direct, detail = [], [], []

    def add(row, quote, text, dest):
        # Every cited quote must exist in the uploaded indexed PDF page.
        if quote not in row['text']:
            return
        sid = f'S{len(sources)+1}'
        sources.append(_source(row,sid,quote[:550]))
        dest.append({'text':text,'source_ids':[sid]})

    asks_summary = bool(re.search(r'\b(?:syllabus|syllabi|summary|summari[sz]e|overview|understand)\b', question, re.I))
    asks_dates = asks_summary or bool(re.search(r'\b(?:when|dates?|schedule|calendar|upcoming)\b', question, re.I) and _EXAM.search(question))
    asks_grades = asks_summary or bool(re.search(r'\b(?:grading|grades?|worth|weigh(?:t|ts)|percent(?:age)?)\b', question, re.I))
    # "What exams are there?" is an exam-calendar question too.
    asks_dates = asks_dates or bool(re.search(r'\bwhat\s+(?:are\s+)?(?:the\s+)?(?:midterms?|exams?)\b', question, re.I))
    if asks_summary:
        first = pages[0]
        title = _clean('\n'.join(first['text'].splitlines()[:3]))[:180]
        if title:
            add(first,first['text'][:min(250,len(first['text']))],f'**{filename}**\n{title}',direct)

    if asks_dates:
        candidates = []
        for page in pages:
            for line,quote in _relevant_lines(page, 'date'):
                # Only report dates/unscheduled statuses in the immediate exam context.
                key = _clean(line + quote)
                if key not in {x[0] for x in candidates}:
                    candidates.append((key,page,line,quote))
        if candidates:
            for _,page,line,quote in candidates[:10]:
                # Include adjacent date line when needed; show source transcription verbatim.
                context = _clean(quote)
                add(page, quote, '- ' + context[:340], direct)
        else:
            direct.append({'text':'**Exam dates:** No explicit midterm/final exam dates were found in the searchable syllabus text. Check course announcements or the official exam schedule. Do not assume a date.', 'source_ids':[]})

    if asks_grades:
        grades = []
        for page in pages:
            for line,quote in _relevant_lines(page,'grade'):
                key = _clean(line)
                if key.lower() not in {x[0].lower() for x in grades}:
                    grades.append((key,page,quote))
        if grades:
            for index, (line, page, quote) in enumerate(grades[:12]):
                prefix = '**Grading breakdown**\n' if index == 0 else ''
                add(page, quote, prefix + '- ' + line, detail)
        elif asks_summary:
            detail.append({'text':'**Grading:** I could not identify a percentage breakdown in the searchable text.', 'source_ids':[]})
    if asks_summary:
        # A few literal course-logistics excerpts, not a generic AI syllabus summary.
        labels = ('piazza','blackboard','brightspace','attendance','textbook','course materials')
        covered = set()
        for page in pages:
            for line in page['text'].splitlines():
                low = line.lower()
                term = next((t for t in labels if t in low and t not in covered), None)
                if term and len(line.strip()) >= 22:
                    covered.add(term)
                    if len(covered) == 1:
                        detail.append({'text':'**Course logistics (as written)**','source_ids':[]})
                    add(page,line.strip(),'- '+_clean(line)[:280],detail)
                if len(covered) >= 4:
                    break
            if len(covered) >= 4:
                break
    if not direct and not detail:
        return None
    return {'status':'answered','answer_mode':'syllabus','direct':direct, 'detail':detail,
            'sources':sources,'next_question':''}
