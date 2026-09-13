"""HTML text extraction and chunking. PRD §16.1.

`extract_text` prefers trafilatura, which already strips nav/script/ad noise
and boilerplate; when trafilatura finds nothing worth extracting (e.g. a
near-empty JS shell, or genuinely tiny fixture HTML in tests) a tag-stripping
regex fallback recovers whatever text is present so the caller can still
decide whether the page is "thin" and worth a reader-service retry.
"""
import re

import trafilatura

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def _strip_tags(html: str) -> str:
    """Best-effort fallback when trafilatura returns nothing: drop script/style
    blocks wholesale (their content is never prose), then strip remaining
    tags and collapse whitespace."""
    text = _SCRIPT_STYLE.sub(" ", html)
    text = _TAG.sub(" ", text)
    text = _WS.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def extract_text(html: str, url: str) -> str:
    extracted = trafilatura.extract(
        html, url=url, include_tables=True, favor_precision=True,
    )
    if extracted and extracted.strip():
        return extracted.strip()
    return _strip_tags(html)


def chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    """Slide a window of `size` characters over `text` with `overlap`
    characters of repetition between consecutive chunks, breaking on
    whitespace so a chunk boundary never splits a word.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # Back off to the last whitespace inside the window so the chunk
            # stays word-aligned, unless the window has no whitespace at all.
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(chunk_text)
        if end >= n:
            break
        start = max(end - overlap, start + 1)

    return chunks
