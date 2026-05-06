"""RAG parser — extract plain text from supported file types.

Handles: .pdf (PyMuPDF), .txt/.md/.py/.js/... (plain UTF-8),
         .csv/.tsv (rows to text), .json (flattened)
"""

import csv as _csv
import io as _io
import json as _json
import re as _re
from pathlib import Path
from typing import Optional


def _read_utf8(path: Path) -> str:
    """Read a file as UTF-8. Falls back to latin-1 on decode errors."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="replace")


def _parse_pdf(path: Path) -> str:
    """Extract text from a PDF using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF
    doc = fitz.open(str(path))
    try:
        parts: list[str] = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            if text and text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts)
    finally:
        doc.close()


def _parse_csv(path: Path) -> str:
    """Convert CSV/TSV to readable text rows."""
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    content = _read_utf8(path)
    # Sniff delimiter for .csv files
    if path.suffix.lower() == ".csv":
        try:
            dialect = _csv.Sniffer().sniff(content[:4096])
            delimiter = dialect.delimiter
        except _csv.Error:
            delimiter = ","
    reader = _csv.reader(_io.StringIO(content), delimiter=delimiter)
    lines: list[str] = []
    for i, row in enumerate(reader):
        if i == 0:
            # Header row
            lines.append(" | ".join(str(c).strip() for c in row))
            lines.append("-" * min(len(lines[-1]), 80))
        else:
            lines.append(" | ".join(str(c).strip() for c in row))
    return "\n".join(lines)


def _parse_json(path: Path) -> str:
    """Flatten JSON into readable key: value pairs. Keeps nested structure."""
    data = _json.loads(_read_utf8(path))
    return _json.dumps(data, indent=2, ensure_ascii=False)


_TRIM_RE = _re.compile(r"\n{3,}")


def parse_file(path: Path, max_chars: int = 0) -> tuple[str, int, str | None]:
    """Extract text from a file. Returns (text, char_count, error).

    Args:
        path: File to parse
        max_chars: If > 0, truncate output to this many characters (keeps start + end).

    Returns:
        Tuple of (extracted_text, original_character_count, error_string_or_None).
    """
    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            text = _parse_pdf(path)
        elif suffix in (".csv", ".tsv"):
            text = _parse_csv(path)
        elif suffix == ".json":
            text = _parse_json(path)
        else:
            # Plain text for everything else
            text = _read_utf8(path)

        if not text or not text.strip():
            return "", 0, f"File appears empty: {path.name}"

        # Collapse runs of 3+ newlines to double newlines
        text = _TRIM_RE.sub("\n\n", text)
        original_len = len(text)

        if max_chars > 0 and len(text) > max_chars:
            half = max_chars // 2
            text = text[:half] + "\n\n... [truncated] ...\n\n" + text[-half:]

        return text, original_len, None

    except FileNotFoundError:
        return "", 0, f"File not found: {path.name}"
    except _json.JSONDecodeError as e:
        return "", 0, f"Invalid JSON in {path.name}: {e}"
    except Exception as e:
        return "", 0, f"Failed to parse {path.name}: {e}"


def estimate_tokens(text: str) -> int:
    """Rough token count: chars / 3 (pessimistic for code, optimistic for prose)."""
    return max(1, len(text) // 3)
