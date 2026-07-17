"""RAG chunker — split documents into overlapping semantic chunks.

Strategy:
  1. Split on paragraph boundaries (double newlines)
  2. Merge paragraphs into chunks targeting chunk_size tokens
  3. Overlap chunks by chunk_overlap tokens worth of text
"""

import re as _re
from typing import Optional

from ct2.rag.parser import estimate_tokens

# Sentence-ending boundary: period/exclamation/question + space + capital letter or newline
_SENTENCE_BOUNDARY = _re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-Ö])")


def chunk_text(
    text: str,
    chunk_size: int = 400,
    chunk_overlap: int = 100,
    min_chunk_tokens: int = 50,
    source: str = "",
) -> list[dict]:
    """Split text into overlapping chunks for embedding.

    Args:
        text: Full document text.
        chunk_size: Target tokens per chunk.
        chunk_overlap: Token overlap between consecutive chunks.
        min_chunk_tokens: Drop chunks smaller than this (noise).
        source: Filename or source identifier for metadata.

    Returns:
        List of dicts: {"text": str, "tokens": int, "source": str, "chunk_index": int}
    """
    if not text or not text.strip():
        return []

    # Step 1: Split into paragraphs on blank lines
    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Step 2: For very long paragraphs (>2x chunk_size), split on sentence
    #         boundaries so we don't get a single monster chunk.
    paragraphs: list[str] = []
    for para in raw_paragraphs:
        para_tokens = estimate_tokens(para)
        if para_tokens <= chunk_size * 2:
            paragraphs.append(para)
        else:
            # Split on sentence boundaries
            parts = _SENTENCE_BOUNDARY.split(para)
            current = ""
            for part in parts:
                tentative = f"{current} {part}".strip() if current else part
                if estimate_tokens(tentative) <= chunk_size * 2:
                    current = tentative
                else:
                    if current:
                        paragraphs.append(current)
                    current = part
            if current:
                paragraphs.append(current)

    if not paragraphs:
        return []

    # Step 3: Merge paragraphs into chunks with overlap
    chunks: list[dict] = []
    chunk_index = 0
    current_chunk = ""
    current_tokens = 0

    # Build forward. For overlap, we keep track of where the overlap window
    # should start from the PREVIOUS chunk's end.
    overlap_start_chars = ""

    for i, para in enumerate(paragraphs):
        para_tokens = estimate_tokens(para)

        # If adding this paragraph exceeds chunk_size and we already have content, save
        if current_chunk and current_tokens + para_tokens > chunk_size:
            chunk_text = current_chunk.strip()
            chunk_tokens = estimate_tokens(chunk_text)

            if chunk_tokens >= min_chunk_tokens:
                chunks.append({
                    "text": chunk_text,
                    "tokens": chunk_tokens,
                    "source": source,
                    "chunk_index": chunk_index,
                })
                chunk_index += 1

                # Save the tail of this chunk for overlap into the next chunk.
                # We want ~chunk_overlap tokens of tail text.
                overlap_chars = _extract_overlap_tail(chunk_text, chunk_overlap)
                current_chunk = overlap_chars + "\n\n" + para
                current_tokens = estimate_tokens(current_chunk)
            else:
                # Too small — keep accumulating
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
                current_tokens = estimate_tokens(current_chunk)
        else:
            current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            current_tokens = estimate_tokens(current_chunk)

    # Don't forget the final chunk.
    # Skip the min_chunk_tokens floor if this is the only chunk — small files
    # (contacts, notes, snippets) should be indexable regardless of size.
    if current_chunk:
        chunk_text = current_chunk.strip()
        chunk_tokens = estimate_tokens(chunk_text)
        if chunk_tokens >= min_chunk_tokens or not chunks:
            chunks.append({
                "text": chunk_text,
                "tokens": chunk_tokens,
                "source": source,
                "chunk_index": chunk_index,
            })

    return chunks


def _extract_overlap_tail(text: str, target_tokens: int) -> str:
    """Extract the end of `text` that's ~target_tokens long, starting
    at a paragraph boundary when possible."""
    if not text:
        return ""

    target_chars = target_tokens * 3
    if len(text) <= target_chars:
        return text

    tail = text[-target_chars:]

    # Try to start at a paragraph boundary
    para_split = tail.split("\n\n", 1)
    if len(para_split) > 1:
        return para_split[1]

    # Fall back to sentence boundary
    boundary = _SENTENCE_BOUNDARY.search(tail)
    if boundary:
        return tail[boundary.end():]

    return tail
