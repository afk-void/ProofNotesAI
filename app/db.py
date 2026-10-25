"""Local, single-user SQLite data store, including FTS5 index."""
import json
import os
from pathlib import Path
import sqlite3

from .core import readable_text

DATA = Path(os.getenv('PROOFNOTES_DATA_DIR', str(Path(__file__).parent / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS = DATA / 'uploads'
UPLOADS.mkdir(exist_ok=True)
DATABASE = DATA / 'proofnotes_local.sqlite3'


def connect():
    con = sqlite3.connect(str(DATABASE), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def setup():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
          ext TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          page_count INTEGER NOT NULL, chunk_count INTEGER NOT NULL, ocr_count INTEGER NOT NULL,
          embedding_model TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL,
          number INTEGER NOT NULL, text TEXT NOT NULL, ocr INTEGER NOT NULL,
          UNIQUE(doc_id, number), FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL,
          page_number INTEGER NOT NULL, text TEXT NOT NULL, vector TEXT NOT NULL,
          FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(text, chunk_id UNINDEXED);
        CREATE INDEX IF NOT EXISTS chunk_doc_idx ON chunks(doc_id);
        ''')
    setup_chats()
    with connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS courses (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE)')
        con.executescript('''
          CREATE TABLE IF NOT EXISTS chat_documents (
            chat_id TEXT NOT NULL, doc_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(chat_id, doc_id),
            FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
          );
        ''')
        for table in ('documents', 'chats'):
            columns = {r['name'] for r in con.execute(f'PRAGMA table_info({table})')}
            if 'course_id' not in columns:
                con.execute(f'ALTER TABLE {table} ADD COLUMN course_id TEXT')
        con.execute('CREATE INDEX IF NOT EXISTS documents_course_idx ON documents(course_id)')
        # Older uploads may have the same display name; repair them once on startup.
        # Keep every document ID, source citation and attached chat intact.
        existing = con.execute('SELECT id,name FROM documents ORDER BY created_at,id').fetchall()
        reserved = {row['name'].lower() for row in existing}
        seen = set()
        for row in existing:
            if row['name'].lower() in seen:
                name = unique_document_name(row['name'], reserved)
                con.execute('UPDATE documents SET name=? WHERE id=?', (name,row['id']))
                reserved.add(name.lower())
                seen.add(name.lower())
            else:
                seen.add(row['name'].lower())
        con.execute('CREATE UNIQUE INDEX IF NOT EXISTS documents_display_name_idx ON documents(name COLLATE NOCASE)')


def unique_document_name(name, taken):
    """Human-friendly suffixes; IDs/paths stay opaque and unique independently."""
    from pathlib import Path
    original = Path(name)
    # Re-uploading "Lecture (1).pdf" should become "Lecture (2).pdf".
    stem = __import__('re').sub(r' \(\d+\)$', '', original.stem)
    for i in range(1, 100000):
        candidate = f'{stem} ({i}){original.suffix}'
        if candidate.lower() not in taken:
            return candidate
    raise ValueError('Too many files with this name.')


def syllabus_rows(doc_ids=None):
    """Read only syllabus pages (not every embedded chunk/vector in the library)."""
    selected = list(dict.fromkeys(doc_ids)) if doc_ids is not None else None
    if selected is not None and not selected:
        return []
    scope = (' AND d.id IN (' + ','.join('?' for _ in selected) + ')') if selected is not None else ''
    with connect() as con:
        rows = con.execute('''
            SELECT d.id AS doc_id,d.name,d.sha256,d.kind,d.course_id,
                   p.number AS page_number,p.text,p.ocr
            FROM documents d JOIN pages p ON p.doc_id=d.id
            WHERE (lower(d.name) LIKE '%syllabus%' OR lower(d.name) LIKE '%syllabi%')
        ''' + scope + ' ORDER BY d.created_at,d.id,p.number', selected or []).fetchall()
    return [{**dict(x), 'text': readable_text(x['text']), '_full_page': True} for x in rows]


def docs():
    with connect() as con:
        return [dict(x) for x in con.execute('SELECT id,name,kind,ext,created_at,page_count,chunk_count,ocr_count,course_id FROM documents ORDER BY created_at DESC,id DESC')]


def pages_for(doc_id: str, page: int):
    with connect() as con:
        x = con.execute('SELECT number, text, ocr FROM pages WHERE doc_id=? AND number=?', (doc_id, page)).fetchone()
        return {**dict(x), "text": readable_text(x["text"])} if x else None


def rows_all():
    with connect() as con:
        return [{**dict(x), 'text': readable_text(x['text'])} for x in con.execute('SELECT chunks.id,doc_id,page_number,text,vector,documents.name,documents.kind,documents.embedding_model FROM chunks JOIN documents ON documents.id=chunks.doc_id')]




def indexed_rows(question: str, doc_ids=None, *, limit=320):
    'Bounded FTS5 candidates with scope pushed into SQL; no library-wide vector scan.'
    from .core import fts_query
    # Reject filler before BM25 so 'what is' cannot swamp specific terms.
    stop = {'what','which','when','where','why','how','are','was','were','the','this','that','these','those','does','for','and','from','with','tell','please','about','lecture','explain','define','can','you','give','me','is','a','an','of','to','in','on','my','your','slides','notes'}
    terms = [x for x in __import__('re').findall(r'[a-z0-9]+', question.lower()) if len(x)>1 and x not in stop][:18]
    # Basic singular/plural rescue, without rescanning the corpus.
    terms = list(dict.fromkeys(terms + [x[:-1] for x in terms if x.endswith('s') and len(x)>4]))
    query = fts_query(' '.join(terms)) if terms else ''
    if not query:
        return []
    selected = list(dict.fromkeys(doc_ids)) if doc_ids is not None else None
    if selected is not None and not selected:
        return []
    scope = (' AND c.doc_id IN (' + ','.join('?' for _ in selected) + ')') if selected is not None else ''
    sql = ('''SELECT c.id,c.doc_id,c.page_number,c.text,c.vector,d.name,d.kind,d.embedding_model
           FROM chunk_search JOIN chunks c ON c.id=chunk_search.rowid
           JOIN documents d ON d.id=c.doc_id
           WHERE chunk_search MATCH ?''' + scope + ''' ORDER BY chunk_search.rank LIMIT ?''')
    with connect() as con:
        try:
            rows = con.execute(sql, [query] + (selected or []) + [limit]).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{**dict(x), 'text': readable_text(x['text'])} for x in rows]


def chunk_count():
    with connect() as con:
        return con.execute('SELECT count(*) FROM chunks').fetchone()[0]

def chat_attachment_ids(chat_id):
    with connect() as con:
        return [r['doc_id'] for r in con.execute('SELECT doc_id FROM chat_documents WHERE chat_id=? ORDER BY created_at,doc_id', (chat_id,))]


def attach_to_chat(chat_id, doc_id):
    with connect() as con:
        con.execute('INSERT OR IGNORE INTO chat_documents(chat_id,doc_id) VALUES (?,?)', (chat_id,doc_id))


def delete_document(doc_id: str) -> bool:
    with connect() as con:
        d = con.execute('SELECT path FROM documents WHERE id=?', (doc_id,)).fetchone()
        if d is None:
            return False
        ids = [x['id'] for x in con.execute('SELECT id FROM chunks WHERE doc_id=?', (doc_id,))]
        for id_ in ids:
            con.execute('DELETE FROM chunk_search WHERE rowid=?', (id_,))
        con.execute('DELETE FROM documents WHERE id=?', (doc_id,))
    # Delete only known path after row removal.
    path = Path(d['path'])
    if path.parent.resolve() == UPLOADS.resolve():
        path.unlink(missing_ok=True)
    return True

def courses():
    with connect() as con:
        return [dict(r) for r in con.execute('SELECT id,name FROM courses ORDER BY name COLLATE NOCASE')]


def validate_course(course_id):
    if course_id is None:
        return
    if not isinstance(course_id, str) or not __import__('re').fullmatch(r'[0-9a-f]{32}', course_id):
        raise ValueError('Invalid course selection.')
    with connect() as con:
        if con.execute('SELECT id FROM courses WHERE id=?', (course_id,)).fetchone() is None:
            raise ValueError('Course not found. Refresh your sources.')


def create_course(name):
    import uuid
    name = ' '.join(name.strip().split())
    if not 2 <= len(name) <= 80:
        raise ValueError('Course name must contain 2–80 characters.')
    cid = uuid.uuid4().hex
    try:
        with connect() as con:
            con.execute('INSERT INTO courses(id,name) VALUES (?,?)', (cid,name))
    except sqlite3.IntegrityError as exc:
        raise ValueError('That course already exists.') from exc
    return {'id':cid,'name':name}


def assign_course(doc_id, course_id):
    validate_course(course_id)
    with connect() as con:
        cur=con.execute('UPDATE documents SET course_id=? WHERE id=?',(course_id,doc_id))
        return cur.rowcount > 0


def course_doc_ids(course_id):
    validate_course(course_id)
    with connect() as con:
        return [r['id'] for r in con.execute('SELECT id FROM documents WHERE course_id=? ORDER BY created_at,id',(course_id,))]


# Persistent, locally scoped study conversations. Empty doc_ids means entire library.
# Thread and message tables are additive: existing indexed notes remain untouched.

def setup_chats():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS chats (
          id TEXT PRIMARY KEY, title TEXT NOT NULL,
          doc_ids TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_id TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL,
          response_json TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS chat_messages_chat ON chat_messages(chat_id,id);
        ''')


def chats():
    with connect() as con:
        return [dict(x) | {'doc_ids': json.loads(x['doc_ids'])} for x in con.execute('''
          SELECT c.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id=c.id AND m.role='user') AS questions
          FROM chats c ORDER BY updated_at DESC, created_at DESC, id DESC''')]


def get_chat(chat_id: str, include_messages=True):
    with connect() as con:
        row = con.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
        if row is None:
            return None
        chat = dict(row)
        chat['doc_ids'] = json.loads(chat['doc_ids'])
        chat['attachments'] = [dict(d) for d in con.execute('''
            SELECT d.id,d.name,d.kind,d.ext,d.page_count FROM documents d
            JOIN chat_documents a ON a.doc_id=d.id WHERE a.chat_id=? ORDER BY a.created_at,d.id''', (chat_id,))]
        if include_messages:
            chat['messages'] = [dict(m) | {'response': json.loads(m['response_json']) if m['response_json'] else None}
                                for m in con.execute('SELECT id,role,content,response_json,created_at FROM chat_messages WHERE chat_id=? ORDER BY id', (chat_id,))]
            for m in chat['messages']:
                m.pop('response_json', None)
        return chat


def validate_doc_ids(doc_ids):
    if len(doc_ids) > 100 or len(set(doc_ids)) != len(doc_ids) or any(not isinstance(d, str) for d in doc_ids):
        raise ValueError('Invalid or duplicated source selection.')
    if doc_ids:
        with connect() as con:
            found = {r['id'] for r in con.execute('SELECT id FROM documents WHERE id IN (' + ','.join('?' for _ in doc_ids) + ')', doc_ids)}
        if found != set(doc_ids):
            raise ValueError('A selected document does not exist. Refresh the library.')


def create_chat(title, doc_ids, course_id=None):
    import uuid
    validate_doc_ids(doc_ids)
    validate_course(course_id)
    if course_id and doc_ids:
        raise ValueError('Choose a course OR individual documents.')
    uid = uuid.uuid4().hex
    with connect() as con:
        con.execute('INSERT INTO chats(id,title,doc_ids,course_id) VALUES (?,?,?,?)', (uid, title.strip()[:110] or 'New conversation', json.dumps(doc_ids),course_id))
    return get_chat(uid)


def update_chat(chat_id, *, title=None, doc_ids=None, course_id=None):
    if doc_ids is not None:
        validate_doc_ids(doc_ids)
    if course_id is not None:
        validate_course(course_id or None)
    with connect() as con:
        row = con.execute('SELECT id,doc_ids,course_id FROM chats WHERE id=?', (chat_id,)).fetchone()
        if row is None:
            return None
        if title is not None:
            con.execute('UPDATE chats SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (title.strip()[:110] or 'New conversation', chat_id))
        new_course = (course_id or None) if course_id is not None else row['course_id']
        new_docs = doc_ids if doc_ids is not None else json.loads(row['doc_ids'])
        if new_course and new_docs:
            raise ValueError('Choose a course OR individual documents.')
        if doc_ids is not None or course_id is not None:
            con.execute('UPDATE chats SET doc_ids=?, course_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (json.dumps(new_docs), new_course, chat_id))
    return get_chat(chat_id)


def delete_chat(chat_id):
    with connect() as con:
        result = con.execute('DELETE FROM chats WHERE id=?', (chat_id,))
        return result.rowcount > 0


def add_chat_exchange(chat_id, question, response):
    # Only commit both messages together after the model request succeeds.
    answer_text = ' '.join(s.get('text', '') for s in response.get('direct', []))[:3000]
    with connect() as con:
        con.execute('INSERT INTO chat_messages(chat_id,role,content) VALUES (?,?,?)', (chat_id, 'user', question))
        con.execute('INSERT INTO chat_messages(chat_id,role,content,response_json) VALUES (?,?,?,?)',
                    (chat_id, 'assistant', answer_text, json.dumps(response)))
        count = con.execute('SELECT COUNT(*) n FROM chat_messages WHERE chat_id=? AND role=?', (chat_id, 'user')).fetchone()['n']
        if count == 1:
            con.execute('UPDATE chats SET title=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (question[:75] + ('…' if len(question) > 75 else ''), chat_id))
        else:
            con.execute('UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (chat_id,))
