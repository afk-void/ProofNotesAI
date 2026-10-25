"""Local-only Ollama transport. No cloud endpoints or API keys are supported."""
import ipaddress
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
MODEL_DEFAULT = os.getenv('ANSWER_MODEL', 'qwen3.5:9b')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'qwen3-embedding:0.6b')
ALLOWED_MODELS = {'qwen3.5:9b', 'qwen3.5:4b', 'qwen3.6:27b', 'qwen3.6:35b'}


def _local_url():
    parts = urlparse(OLLAMA_URL)
    if parts.scheme != 'http' or parts.username or parts.password or parts.path not in ('', '/') or parts.query or parts.fragment:
        raise ValueError('OLLAMA_URL must be a loopback HTTP URL.')
    if parts.hostname == 'localhost':
        return OLLAMA_URL
    try:
        if ipaddress.ip_address(parts.hostname or '').is_loopback:
            return OLLAMA_URL
    except ValueError:
        pass
    raise ValueError('Remote Ollama is disabled: inference must stay on this computer.')


def _request(route: str, body=None, timeout=240):
    base = _local_url()
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = Request(base + route, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read(10_000_000))
    except HTTPError as exc:
        msg = exc.read(600).decode('utf-8', errors='replace')
        if exc.code == 404:
            raise ValueError('The Ollama model is missing. Run the model setup script (or ollama pull).') from exc
        raise ValueError(f'Ollama returned HTTP {exc.code}: {msg[:180]}') from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError('Cannot reach local Ollama. Start the Ollama app/service and try again.') from exc


def installed_models():
    names = _request('/api/tags', timeout=4).get('models', [])
    return [x.get('name', '') for x in names]


def vectors(texts: list[str]) -> list[list[float]]:
    result = []
    for i in range(0, len(texts), 16):
        batch = texts[i:i + 16]
        payload = _request('/api/embed', {'model': EMBEDDING_MODEL, 'input': batch, 'truncate': True}, timeout=200)
        vecs = payload.get('embeddings', [])
        if len(vecs) != len(batch) or any(not isinstance(v, list) or not v for v in vecs):
            raise ValueError('Local embedder returned invalid vectors.')
        result.extend(vecs)
    return result


def structured(system: str, user: str, schema: dict, *, model: str | None = None, max_tokens: int = 1700, temperature: float = 0, timeout: int = 300):
    model = model or MODEL_DEFAULT
    if model not in ALLOWED_MODELS:
        raise ValueError('Unsupported local model.')
    result = _request('/api/chat', {
        'model': model,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        'stream': False,
        'think': False,
        'format': schema,
        'options': {'temperature': temperature, 'num_ctx': 8192, 'num_predict': max_tokens},
        'keep_alive': '3m',
    }, timeout=timeout)
    raw = (result.get('message') or {}).get('content', '')
    if not raw.strip():
        raise ValueError('Local model returned an empty response. Increase available memory or reduce the question.')
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Local model response was not valid structured JSON; no answer was accepted.') from exc


def plain_chat(system: str, question: str, history: list[dict], *, model: str | None = None, max_tokens: int = 1500):
    """Natural, clearly unsourced local chat. Does not make evidence claims."""
    model = model or MODEL_DEFAULT
    if model not in ALLOWED_MODELS:
        raise ValueError('Unsupported local model.')
    messages = [{'role': 'system', 'content': system}]
    messages.extend({'role': item['role'], 'content': item['content'][:900]}
                    for item in history[-8:] if item.get('role') in ('user', 'assistant'))
    messages.append({'role': 'user', 'content': question})
    result = _request('/api/chat', {
        'model': model, 'messages': messages, 'stream': False, 'think': False,
        'options': {'temperature': 0.25, 'num_ctx': 8192, 'num_predict': max_tokens},
        'keep_alive': '3m',
    }, timeout=300)
    raw = (result.get('message') or {}).get('content', '').strip()
    if not raw:
        raise ValueError('The local model returned no answer.')
    return raw[:12000]
