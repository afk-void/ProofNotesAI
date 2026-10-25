"""Literal syllabus answers. Scan full indexed pages, not top-k chunks or model JSON."""
import re
import hashlib

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
    # SQL page rows are already full-page text. Legacy chunk callers still
    # resolve the original page so excerpts/citations remain literal.
    pages = {r['page_number']: r for r in rows if r['doc_id'] == doc_id}
    for number, row in sorted(pages.items()):
        page = row if row.get('_full_page') else db.pages_for(doc_id, number)
        if page and page['text'].strip():
            yield {**row, 'text': page['text']}


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
            # Never include the previous/next exam's date when this line
            # already contains its own date (e.g. "Midterm Exam 2: April 16").
            start = i - 1 if i and not _DATE.search(line) and _DATE.search(lines[i-1]) and not _EXAM.search(lines[i-1]) else i
            end = i + 2 if i+1 < len(lines) and not _DATE.search(line) and _DATE.search(lines[i+1]) and not _EXAM.search(lines[i+1]) else i + 1
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


def syllabus_answer(question, rows, history=None):
    # A user replying with a filename to a date clarification means "use
    # that file to answer my previous question", not "summarize its syllabus".
    filename_reply = question.strip().lower().endswith(('.pdf', '.docx', '.txt'))
    if filename_reply and history:
        previous = next((m.get('content', '') for m in reversed(history)
                         if m.get('role') == 'user' and _SOURCE_QUERY.search(m.get('content', ''))), '')
        if previous:
            question = question + ' — ' + previous
    if not _SOURCE_QUERY.search(question):
        return None
    by_doc = {}
    for row in rows:
        if 'syllabus' in row['name'].lower() or 'syllabi' in row['name'].lower():
            by_doc[row['doc_id']] = {'name': row['name'], 'sha': row.get('sha256')}
    if not by_doc:
        return None
    # Explicit filename is an actual selection; use the exact name even when
    # similarly named copies or syllabi from other courses exist.
    named = {doc_id: item for doc_id, item in by_doc.items()
             if item['name'].lower() in question.lower()}
    if named:
        max_length = max(len(item['name']) for item in named.values())
        by_doc = {doc_id: item for doc_id, item in named.items()
                  if len(item['name']) == max_length}
    else:
        course = re.search(r'\b([A-Za-z]{2,4})\s*[- ]?(\d{3})\b', question)
        if course:
            key = f'{course.group(1)}{course.group(2)}'.lower()
            matching = {d:item for d,item in by_doc.items()
                        if key in re.sub(r'[^a-z0-9]','', item['name'].lower())}
            if not matching:
                return None
            by_doc = matching
    # Two entries with identical file bytes are one logical evidence source.
    # This also repairs already-uploaded duplicates without deleting any file.
    unique = {}
    for doc_id, item in by_doc.items():
        # PDF metadata can change the binary SHA without changing any lecture
        # text. Exact page content is the evidence identity, not the file wrapper.
        pages_for_doc = list(_page_rows(rows, doc_id))
        content = '\f'.join(page['text'] for page in pages_for_doc)
        key = hashlib.sha256(content.encode()).hexdigest() if content else item['sha'] or doc_id
        unique.setdefault(key, (doc_id, item['name']))
    if len(unique) != 1:
        names = ', '.join(sorted({item['name'] for item in by_doc.values()})[:8])
        return {'status':'conversation', 'answer_mode':'conversation',
                'direct':[{'text':f'I found syllabi for different sources: {names}. Select a course or specify an exact filename.', 'source_ids':[]}],
                'detail':[], 'sources':[], 'next_question':''}

    doc_id, filename = next(iter(unique.values()))
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

    # A filename containing 'Syllabus' is a selection, not a summary request.
    intent = re.sub(r'\S*syllab(?:us|i)\S*\.(?:pdf|docx|txt)', '', question, flags=re.I)
    asks_summary = bool(re.search(r'\b(?:syllabus|syllabi|summary|summari[sz]e|overview|understand)\b', intent, re.I))
    asks_dates = asks_summary or bool(re.search(r'\b(?:when|dates?|schedule|calendar|upcoming)\b', question, re.I) and _EXAM.search(question))
    asks_grades = asks_summary or bool(re.search(r'\b(?:grading|grades?|worth|weigh(?:t|ts)|percent(?:age)?)\b', question, re.I))
    # "What exams are there?" is an exam-calendar question too.
    asks_dates = asks_dates or bool(re.search(r'\bwhat\s+(?:are\s+)?(?:the\s+)?(?:midterms?|exams?)\b', question, re.I))
    # A specific midterm question must not return Midterm 1/Final dates.
    target = re.search(r'\bmid[ -]?term\s*(?:exam\s*)?(?:#|no\.?\s*)?([1-9])\b', question, re.I)
    target_re = (re.compile(r'\b(?:mid[ -]?term\s*(?:exam\s*)?|exam\s*)(?:#|no\.?\s*)?'+target.group(1)+r'\b', re.I)
                 if target else None)
    if asks_summary:
        first = pages[0]
        title = _clean('\n'.join(first['text'].splitlines()[:3]))[:180]
        if title:
            add(first,first['text'][:min(250,len(first['text']))],f'**{filename}**\n{title}',direct)

    if asks_dates:
        candidates = []
        for page in pages:
            for line,quote in _relevant_lines(page, 'date'):
                if target_re and not target_re.search(line):
                    continue
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
            missing = (f'Midterm {target.group(1)}' if target else 'midterm/final exam')
            direct.append({'text':f'No explicit date for {missing} was found in the searchable syllabus text. Check official course announcements; do not assume a date.', 'source_ids':[]})

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
