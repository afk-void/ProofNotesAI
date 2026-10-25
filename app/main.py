"""ProofNotes: evidence-first, local-only FastAPI service."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
import zipfile

import fitz
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from . import db  # noqa: E402
from .ai import answer, embeddings, recall_cards, inspect_claim, _rows_checked  # noqa: E402
from .core import chunks_from_page, cosine  # noqa: E402
from .ingest import MAX_FILE_BYTES, SUPPORTED, extract_pages  # noqa: E402
from .local_models import MODEL_DEFAULT, ALLOWED_MODELS, EMBEDDING_MODEL, installed_models  # noqa: E402

BASE = Path(__file__).parent
app = FastAPI(title='ProofNotes Local', docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
db.setup()


@app.middleware('http')
async def restrict_cross_origin(request: Request, call_next):
    # Browsers cannot post data from a random website to the local API.
    origin = request.headers.get('origin') or ''
    if origin and origin not in (f'http://{request.headers.get("host", "")}',):
        return Response('Cross-origin request blocked', status_code=403)
    return await call_next(request)


class Message(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1800)
    history: list[Message] = Field(default_factory=list, max_length=10)
    model: str = MODEL_DEFAULT
    doc_ids: list[str] = Field(default_factory=list, max_length=100)
    response_mode: str = 'auto'


class ModelRequest(BaseModel):
    difficulty: str = 'mixed'
    advanced: bool = False
    model: str = MODEL_DEFAULT
    doc_ids: list[str] = Field(default_factory=list, max_length=100)
    course_id: str | None = None


class ClaimRequest(ModelRequest):
    claim: str = Field(min_length=5, max_length=700)


def _error(exc: Exception, action: str):
    if isinstance(exc, ValueError):
        raise HTTPException(422, str(exc)) from exc
    raise HTTPException(500, f'{action} failed ({type(exc).__name__}). See terminal for details.') from exc


@app.get('/api/health')
def health():
    try:
        models = installed_models()
        connected = True
    except (ValueError, TypeError):
        models = []
        connected = False
    return {'ok': True, 'offline_only': True, 'ollama_connected': connected,
            'installed_models': models, 'default_model': MODEL_DEFAULT,
            'embedding_model': EMBEDDING_MODEL, 'models': sorted(ALLOWED_MODELS),
            'ocr_installed': bool(shutil.which('tesseract')),
            'ocr_enabled': os.getenv('ENABLE_OCR', 'true').lower() == 'true'}


class CourseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class CourseAssign(BaseModel):
    course_id: str | None = None


@app.get('/api/courses')
def course_list():
    return {'courses': db.courses()}


@app.post('/api/courses')
def course_create(payload: CourseCreate):
    try:
        return {'course': db.create_course(payload.name)}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@app.patch('/api/documents/{doc_id}/course')
def document_assign(doc_id: str, payload: CourseAssign):
    try:
        if not db.assign_course(doc_id, payload.course_id):
            raise HTTPException(404,'Document not found')
        return {'ok':True}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@app.get('/api/documents')
def documents():
    return {'documents': db.docs()}


@app.get('/api/overview')
def overview():
    docs = db.docs()
    rows = db.rows_all()
    return {'documents': len(docs), 'pages': sum(x['page_count'] for x in docs),
            'evidence_passages': len(rows), 'notes': sum(x['kind'] == 'notes' for x in docs),
            'slides': sum(x['kind'] == 'slides' for x in docs)}


@app.post('/api/upload')
async def upload(file: UploadFile = File(...), kind: str = Form('notes'), course_id: str = Form('')):
    if kind not in ('notes', 'slides'):
        raise HTTPException(400, 'Choose My Notes or Lecture Slides.')
    try:
        db.validate_course(course_id or None)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    name = Path(file.filename or 'upload').name
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, 'Allowed: PDF, DOCX, PPTX, TXT, MD, PNG, JPG, WEBP.')
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, 'File exceeds 18 MB limit.')
    if not data:
        raise HTTPException(400, 'Empty file.')
    if ext in ('.docx', '.pptx'):
        try:
            with zipfile.ZipFile(__import__('io').BytesIO(data)) as arch:
                if len(arch.infolist()) > 5000 or sum(x.file_size for x in arch.infolist()) > 90_000_000:
                    raise HTTPException(413, 'Document exceeds safe extracted-size limits.')
        except zipfile.BadZipFile as exc:
            raise HTTPException(422, 'Invalid office document.') from exc
    digest = hashlib.sha256(data).hexdigest()
    with db.connect() as con:
        duplicate = con.execute('SELECT id FROM documents WHERE sha256=? AND kind=? AND embedding_model=?',
                                (digest, kind, EMBEDDING_MODEL)).fetchone()
    if duplicate:
        if course_id:
            db.assign_course(duplicate['id'],course_id)
        return {'ok': True, 'duplicate': True, 'id': duplicate['id']}
    uid = uuid.uuid4().hex
    path = db.UPLOADS / f'{uid}{ext}'
    path.write_bytes(data)
    try:
        pages = extract_pages(path)
        units = [(page, chunk) for page in pages for chunk in chunks_from_page(page.text)]
        if not units or len(units) > 850:
            raise ValueError('No searchable content or more than 850 passages. Split this file.')
        vecs = embeddings([chunk for page, chunk in units])
        with db.connect() as con:
            con.execute('INSERT INTO documents (id,name,kind,ext,path,sha256,page_count,chunk_count,ocr_count,embedding_model,course_id) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (uid, name, kind, ext, str(path), digest, len(pages), len(units),
                         sum(p.ocr for p in pages), EMBEDDING_MODEL,course_id or None))
            for p in pages:
                con.execute('INSERT INTO pages (doc_id,number,text,ocr) VALUES (?,?,?,?)',
                            (uid, p.number, p.text, int(p.ocr)))
            for (page, chunk), vec in zip(units, vecs):
                cur = con.execute('INSERT INTO chunks (doc_id,page_number,text,vector) VALUES (?,?,?,?)',
                                  (uid, page.number, chunk, json.dumps(vec)))
                con.execute('INSERT INTO chunk_search (rowid,text,chunk_id) VALUES (?,?,?)',
                            (cur.lastrowid, chunk, cur.lastrowid))
    except Exception as exc:
        path.unlink(missing_ok=True)
        _error(exc, 'Indexing')
    return {'ok': True, 'duplicate': False, 'id': uid, 'pages': len(pages),
            'chunks': len(units), 'ocr_pages': sum(p.ocr for p in pages)}


@app.delete('/api/documents/{doc_id}')
def delete(doc_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', doc_id) or not db.delete_document(doc_id):
        raise HTTPException(404, 'Document not found')
    return {'ok': True}


@app.get('/api/documents/{doc_id}/pages/{page}')
def source_page(doc_id: str, page: int):
    if not re.fullmatch(r'[0-9a-f]{32}', doc_id):
        raise HTTPException(404, 'Document not found')
    item = db.pages_for(doc_id, page)
    if item is None:
        raise HTTPException(404, 'Page not found')
    return item


@app.get('/api/documents/{doc_id}/file')
def original_file(doc_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', doc_id):
        raise HTTPException(404, 'Document not found')
    with db.connect() as con:
        item = con.execute('SELECT name,path FROM documents WHERE id=?', (doc_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Document not found')
    path = Path(item['path'])
    if path.parent.resolve() != db.UPLOADS.resolve() or not path.exists():
        raise HTTPException(404, 'File missing')
    return FileResponse(path, filename=item['name'], content_disposition_type='inline')


@app.get('/api/documents/{doc_id}/pages/{page}/pdf-preview')
def pdf_preview(doc_id: str, page: int, quote: str = ''):
    if not re.fullmatch(r'[0-9a-f]{32}', doc_id) or len(quote) > 600:
        raise HTTPException(400, 'Invalid preview request')
    with db.connect() as con:
        item = con.execute('SELECT ext,path FROM documents WHERE id=?', (doc_id,)).fetchone()
    if not item or item['ext'] != '.pdf':
        raise HTTPException(404, 'PDF unavailable')
    path = Path(item['path'])
    if path.parent.resolve() != db.UPLOADS.resolve() or not path.exists():
        raise HTTPException(404, 'PDF unavailable')
    try:
        with fitz.open(path) as pdf:
            if page < 1 or page > len(pdf):
                raise HTTPException(404, 'Page not found')
            p = pdf[page - 1]
            quads = p.search_for(' '.join(quote.split()), quads=True) if len(quote.strip()) >= 12 else []
            if quads:
                ann = p.add_highlight_annot(quads)
                if ann:
                    ann.update()
            png = p.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False, annots=True).tobytes('png')
            return Response(content=png, media_type='image/png', headers={'X-Exact-Highlight-Matches': str(len(quads))})
    except HTTPException:
        raise
    except Exception as exc:
        _error(exc, 'PDF preview')


def _inventory_answer(question, allowed_docs, label='your library'):
    # File metadata is a database query, not an LLM question.
    if not re.search(r'\b(?:what|which|list|show|how many|tell me)\b', question, re.I) or not re.search(
            r'\b(?:files?|slides?|documents?|pdfs?|notes?|uploads?)\b', question, re.I) or not re.search(
            r'\b(?:upload(?:ed)?|have|available|library|list|show|added)\b', question, re.I):
        return None
    kind = 'slides' if re.search(r'\bslides?\b', question, re.I) else 'notes' if re.search(r'\bnotes?\b', question, re.I) and not re.search(r'\bfiles?|documents?|pdfs?\b', question, re.I) else None
    allowed_docs = [d for d in allowed_docs if d['kind']==kind] if kind else allowed_docs
    if not allowed_docs:
        message = f'No {kind or "documents"} are assigned to {label} yet.'
    else:
        lines = [f'**{len(allowed_docs)} uploaded file(s) in {label}:**']
        lines.extend(f'- {d["name"]} — {"slides" if d["kind"] == "slides" else "notes"}, {d["page_count"]} pages'
                     for d in allowed_docs)
        message = '\n'.join(lines)
    return {'status':'conversation','answer_mode':'library',
            'direct':[{'text':message,'source_ids':[]}], 'detail':[], 'sources':[], 'next_question':''}


@app.post('/api/ask')
def ask(payload: AskRequest):
    if payload.model not in ALLOWED_MODELS:
        raise HTTPException(400, 'Unsupported local model')
    history = [{'role': msg.role, 'content': msg.content[:450]} for msg in payload.history[-6:]
               if msg.role in ('user', 'assistant')]
    try:
        db.validate_doc_ids(payload.doc_ids)
        selected = [d for d in db.docs() if not payload.doc_ids or d['id'] in payload.doc_ids]
        inventory = _inventory_answer(payload.question, selected)
        if inventory:
            return inventory
        return answer(payload.question.strip(), history, payload.model, doc_ids=payload.doc_ids or None, response_mode=payload.response_mode)
    except Exception as exc:
        _error(exc, 'Evidence answer')


@app.post('/api/gaps')
def gaps():
    # Deterministic candidate discovery; no unsupported assertion of topic absence.
    try:
        rows = _rows_checked()
        slides = [x for x in rows if x['kind'] == 'slides']
        notes = [x for x in rows if x['kind'] == 'notes']
        if not slides or not notes:
            raise HTTPException(400, 'Upload at least one slide file and one personal-notes file.')
        notes_vecs = [(x, json.loads(x['vector'])) for x in notes]
        ranked = []
        for s in slides:
            sims = sorted(((cosine(json.loads(s['vector']), v), note) for note, v in notes_vecs),
                          key=lambda x: x[0], reverse=True)
            ranked.append((sims[0][0], s, sims[0][1]))
        ranked.sort(key=lambda t: t[0])
        visited, matches = set(), []
        for similarity, slide, nearest in ranked:
            key = (slide['doc_id'], slide['page_number'])
            if key in visited:
                continue
            visited.add(key)
            quote = slide['text'][:260].strip()
            if len(quote) < 12:
                continue
            sid = f'G{len(matches)+1}'
            matches.append({'title': f'{slide["name"]} · p.{slide["page_number"]}',
                            'explanation': 'Review this passage against your notes. It has one of the weakest semantic matches; this does not establish that the topic is missing.',
                            'source': {'id': sid, 'doc_id': slide['doc_id'], 'document': slide['name'],
                                       'page': slide['page_number'], 'quotes': [quote]},
                            'nearest': {'document': nearest['name'], 'page': nearest['page_number']}})
            if len(matches) >= 5:
                break
        return {'gaps': matches, 'disclaimer': 'Possible coverage gaps, ordered by retrieval similarity — NOT a test of knowledge or proof of missing material.'}
    except HTTPException:
        raise
    except Exception as exc:
        _error(exc, 'Coverage Radar')


@app.post('/api/recall')
def recall(payload: ModelRequest):
    if payload.model not in ALLOWED_MODELS:
        raise HTTPException(400, 'Unsupported local model')
    try:
        if payload.course_id:
            if payload.doc_ids:
                raise ValueError('Choose one course or explicit files.')
            ids = db.course_doc_ids(payload.course_id)
        else:
            ids = payload.doc_ids or None
        return {'cards': recall_cards(payload.model, ids, difficulty=payload.difficulty, advanced=payload.advanced)}
    except Exception as exc:
        _error(exc, 'Recall Lab')


@app.post('/api/claim')
def claim(payload: ClaimRequest):
    if payload.model not in ALLOWED_MODELS:
        raise HTTPException(400, 'Unsupported local model')
    try:
        return inspect_claim(payload.claim, payload.model)
    except Exception as exc:
        _error(exc, 'Claim Inspector')


class CreateChatRequest(BaseModel):
    title: str = Field(default='New conversation', max_length=110)
    doc_ids: list[str] = Field(default_factory=list, max_length=100)
    course_id: str | None = None


class UpdateChatRequest(BaseModel):
    title: str | None = Field(default=None, max_length=110)
    doc_ids: list[str] | None = Field(default=None, max_length=100)
    course_id: str | None = None


class ChatAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1800)
    model: str = MODEL_DEFAULT
    response_mode: str = 'auto'


def _chat_or_404(chat_id):
    if not re.fullmatch(r'[0-9a-f]{32}', chat_id):
        raise HTTPException(404, 'Conversation not found')
    chat = db.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, 'Conversation not found')
    return chat


@app.get('/api/chats')
def list_chats():
    return {'chats': db.chats()}


@app.post('/api/chats')
def create_chat(payload: CreateChatRequest):
    try:
        return {'chat': db.create_chat(payload.title, payload.doc_ids, payload.course_id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/api/chats/{chat_id}')
def chat_detail(chat_id: str):
    return {'chat': _chat_or_404(chat_id)}


@app.patch('/api/chats/{chat_id}')
def patch_chat(chat_id: str, payload: UpdateChatRequest):
    _chat_or_404(chat_id)
    try:
        return {'chat': db.update_chat(chat_id, title=payload.title, doc_ids=payload.doc_ids, course_id=payload.course_id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete('/api/chats/{chat_id}')
def remove_chat(chat_id: str):
    _chat_or_404(chat_id)
    db.delete_chat(chat_id)
    return {'ok': True}


@app.post('/api/chats/{chat_id}/ask')
def chat_ask(chat_id: str, payload: ChatAskRequest):
    chat = _chat_or_404(chat_id)
    if payload.model not in ALLOWED_MODELS:
        raise HTTPException(400, 'Unsupported local model')
    # Course chats resolve live membership and never read files from another course.
    try:
        db.validate_doc_ids(chat['doc_ids'])
        db.validate_course(chat['course_id'])
    except ValueError as exc:
        raise HTTPException(422, 'A source in this chat was deleted. Re-select sources for this conversation.') from exc
    history = [{'role': m['role'], 'content': m['content'][:450]} for m in chat['messages'][-8:]]
    try:
        source_ids = db.course_doc_ids(chat['course_id']) if chat['course_id'] else chat['doc_ids'] or None
        selected = [d for d in db.docs() if source_ids is None or d['id'] in source_ids]
        course_name = next((c['name'] for c in db.courses() if c['id']==chat['course_id']), 'your course')
        result = _inventory_answer(payload.question, selected, course_name if chat['course_id'] else 'your selected sources')
        if result is None:
            result = answer(payload.question.strip(), history, payload.model, doc_ids=source_ids, response_mode=payload.response_mode)
        db.add_chat_exchange(chat_id, payload.question.strip(), result)
        return result
    except Exception as exc:
        _error(exc, 'Conversation answer')


app.mount('/', StaticFiles(directory=str(BASE / 'static'), html=True), name='ui')
