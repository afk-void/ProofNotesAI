"""Pure parsing, chunking, lexical helpers, and evidence validation."""
import re
import math

# Common Wingdings/Symbol private-use glyphs in lecture PDFs.
_PDF_GLYPHS = str.maketrans({
    "\uf097": "•", "\uf0b7": "•", "\uf0a7": "•", "\uf0d8": "•",
    "\uf09e": "•", "\uf0fc": "✓", "\uf0e0": "→",
})

def readable_text(value: str) -> str:
    """Clean PDF font glyphs, without rewriting the indexed meaning."""
    return value.translate(_PDF_GLYPHS)
from typing import Optional


def chunks_from_page(text: str, max_chars: int = 1350, overlap_words: int = 42) -> list[str]:
    """Token-based windows that are literal substrings of the page, not rewritten text."""
    words = list(re.finditer(r"\S+", text))
    if not words:
        return []
    result: list[str] = []
    start = 0
    while start < len(words):
        end = start
        begin_offset = words[start].start()
        while end < len(words) and words[end].end() - begin_offset <= max_chars:
            end += 1
        if end == start:
            end = start + 1
        raw = text[begin_offset:words[end - 1].end()]
        if len(raw.strip()) >= 8:
            result.append(raw)
        if end >= len(words):
            break
        start = max(start + 1, end - overlap_words)
    return result


def fts_query(question: str) -> str:
    """Quote individual tokens: no user-supplied FTS operators."""
    tokens = re.findall(r"[\w]+", question.lower(), flags=re.UNICODE)
    words = list(dict.fromkeys(t for t in tokens if len(t) > 1))[:20]
    return " OR ".join('"' + t.replace('"', '') + '"' for t in words)


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    denom = math.sqrt(sum(v*v for v in a)) * math.sqrt(sum(v*v for v in b))
    return sum(x*y for x, y in zip(a, b)) / denom if denom else -1.0


def find_quote(source: str, quote: str) -> Optional[tuple[int, int]]:
    """Find case-insensitive, whitespace-insensitive *literal* quote; no paraphrase matching."""
    q = quote.strip()
    if len(q) < 12 or len(q) > 600:
        return None
    tokens = re.split(r"\s+", q)
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    found = re.search(pattern, source, re.IGNORECASE | re.DOTALL)
    return (found.start(), found.end()) if found else None


def fuse_rankings(vector_ids: list[int], lexical_ids: list[int], limit: int = 10) -> list[int]:
    scores: dict[int, float] = {}
    for ranking, weight in ((vector_ids, 1.0), (lexical_ids, 0.75)):
        for i, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + weight / (50 + i)
    return sorted(scores, key=scores.get, reverse=True)[:limit]
