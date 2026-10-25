"""Document parsers -> ordered sections (heading + text + page)."""

import io
import re
from dataclasses import dataclass

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {"pdf", "docx", "md", "txt"}

# "4.2 Cash handling", "SECTION 3 - SCOPE", "PURPOSE"
_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?\s+[A-Z][^\n]{2,90}|[A-Z][A-Z0-9 &/,\-]{4,70})$")


@dataclass
class Section:
    heading: str
    text: str
    page: int | None = None


class _Builder:
    def __init__(self, default_heading: str = "Overview"):
        self.sections: list[Section] = []
        self._heading = default_heading
        self._page: int | None = None
        self._lines: list[str] = []

    def start(self, heading: str, page: int | None = None) -> None:
        self.flush()
        self._heading, self._page = heading.strip(" #:"), page

    def add(self, line: str, page: int | None = None) -> None:
        if self._page is None:
            self._page = page
        self._lines.append(line)

    def flush(self) -> None:
        text = "\n".join(self._lines).strip()
        if text:
            self.sections.append(Section(self._heading, text, self._page))
        self._lines, self._page = [], None

    def done(self) -> list[Section]:
        self.flush()
        return self.sections


def parse_pdf(data: bytes) -> list[Section]:
    reader = PdfReader(io.BytesIO(data))
    b = _Builder()
    for page_no, page in enumerate(reader.pages, start=1):
        for raw in (page.extract_text() or "").splitlines():
            line = raw.strip()
            if not line:
                b.add("", page_no)
            elif _HEADING_RE.match(line) and len(line) < 90:
                b.start(line, page_no)
            else:
                b.add(line, page_no)
    return b.done()


def parse_docx(data: bytes) -> list[Section]:
    doc = Document(io.BytesIO(data))
    b = _Builder()
    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                b.add("")
            elif (block.style.name or "").lower().startswith(("heading", "title")):
                b.start(text)
            else:
                b.add(text)
        elif isinstance(block, Table):
            for row in block.rows:
                cells = [c.text.strip() for c in row.cells]
                b.add(" | ".join(dict.fromkeys(cells)))  # de-dupe merged cells
            b.add("")
    return b.done()


def parse_text(data: bytes) -> list[Section]:
    b = _Builder()
    for raw in data.decode("utf-8", errors="replace").splitlines():
        if raw.lstrip().startswith("#"):
            b.start(raw.lstrip("# ").strip())
        else:
            b.add(raw.rstrip())
    return b.done()


def parse_document(data: bytes, ext: str) -> list[Section]:
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return parse_pdf(data)
    if ext == "docx":
        return parse_docx(data)
    if ext in {"md", "txt"}:
        return parse_text(data)
    raise ValueError(f"Unsupported file type: {ext}")
