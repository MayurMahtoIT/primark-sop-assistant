"""Section-aware chunking with sentence-boundary packing and a small overlap."""

import re
from dataclasses import dataclass

from app.ingestion.parsers import Section

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
MIN_CHARS = 40


@dataclass(frozen=True)
class TextChunk:
    index: int
    section: str
    page: int | None
    text: str


def _units(text: str, max_chars: int) -> list[str]:
    """Paragraphs, falling back to sentences (then hard splits) for oversized paragraphs."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            out.append(para)
            continue
        for sent in _SENTENCE_RE.split(para):
            while len(sent) > max_chars:
                out.append(sent[:max_chars])
                sent = sent[max_chars:]
            if sent.strip():
                out.append(sent.strip())
    return out


def chunk_sections(
    sections: list[Section], max_chars: int = 1800, overlap_chars: int = 200
) -> list[TextChunk]:
    chunks: list[TextChunk] = []

    def emit(buf: list[str], sec: Section) -> None:
        text = "\n\n".join(buf).strip()
        if len(text) >= MIN_CHARS or (text and not chunks):
            chunks.append(TextChunk(len(chunks), sec.heading, sec.page, text))

    for sec in sections:
        buf: list[str] = []
        size = 0
        for unit in _units(sec.text, max_chars):
            if buf and size + len(unit) + 2 > max_chars:
                emit(buf, sec)
                # carry the tail of the previous chunk forward for context continuity
                tail: list[str] = []
                tail_size = 0
                for prev in reversed(buf):
                    if tail_size + len(prev) > overlap_chars:
                        break
                    tail.insert(0, prev)
                    tail_size += len(prev)
                buf, size = tail, tail_size
            buf.append(unit)
            size += len(unit) + 2
        if buf:
            emit(buf, sec)
    return chunks
