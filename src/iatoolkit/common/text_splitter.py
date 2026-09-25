"""Recursive character text splitting for the RAG ingestion path.

A drop-in replacement for `langchain_text_splitters.RecursiveCharacterTextSplitter`,
written out here because that single class was the only langchain import in the
whole fleet and it dragged langchain-core, langsmith, zstandard and orjson into
every deployment.

The behaviour is reproduced exactly, not approximated: the chunk boundaries this
produces decide how documents are embedded, so a corpus ingested before the swap
and one ingested after have to agree. `src/tests/common/test_text_splitter.py`
pins that with golden fixtures captured from the original implementation.

Two details are easy to get wrong when reading the algorithm:

- Separators are matched as regular expressions, but the caller passes literals,
  so each one is `re.escape`d before use. Without that, the "." separator this
  codebase configures would match every character.
- `keep_separator` is True here (langchain's own default for the recursive
  splitter, which overrides the False it inherits). The separator is attached to
  the *start* of the following piece, and the pieces are then joined with "" -
  not with the separator - when merging. Joining with the separator instead
  duplicates it in every chunk.
"""

import logging
import re
from typing import Callable, Iterable, List, Optional


logger = logging.getLogger(__name__)


class RecursiveCharacterTextSplitter:
    """Splits text by trying each separator in turn, falling back to the next.

    For every stretch of text the first separator that occurs in it is used. Any
    piece still larger than `chunk_size` is split again with the remaining
    separators, and the pieces that do fit are merged back up to `chunk_size`
    with `chunk_overlap` characters carried between neighbours.
    """

    def __init__(
        self,
        separators: Optional[List[str]] = None,
        chunk_size: int = 4000,
        chunk_overlap: int = 200,
        length_function: Callable[[str], int] = len,
        keep_separator: bool = True,
        strip_whitespace: bool = True,
    ) -> None:
        if chunk_overlap > chunk_size:
            raise ValueError(
                f"Got a larger chunk overlap ({chunk_overlap}) than chunk size "
                f"({chunk_size}), should be smaller."
            )
        self._separators = separators or ["\n\n", "\n", " ", ""]
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._length_function = length_function
        self._keep_separator = keep_separator
        self._strip_whitespace = strip_whitespace

    def split_text(self, text: str) -> List[str]:
        return self._split_text(text, self._separators)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        final_chunks: List[str] = []

        # The last separator is the fallback when none of the others occur.
        separator = separators[-1]
        new_separators: List[str] = []
        for i, candidate in enumerate(separators):
            if candidate == "":
                separator = candidate
                break
            if re.search(re.escape(candidate), text):
                separator = candidate
                new_separators = separators[i + 1:]
                break

        splits = self._split_with_separator(text, separator)

        # Pieces that already fit accumulate until one does not; that one is
        # flushed first so the recursion cannot reorder the output.
        good_splits: List[str] = []
        merge_separator = "" if self._keep_separator else separator
        for piece in splits:
            if self._length_function(piece) < self._chunk_size:
                good_splits.append(piece)
                continue
            if good_splits:
                final_chunks.extend(self._merge_splits(good_splits, merge_separator))
                good_splits = []
            if not new_separators:
                # No separator left to try: the piece goes out oversized rather
                # than being cut mid-word.
                final_chunks.append(piece)
            else:
                final_chunks.extend(self._split_text(piece, new_separators))
        if good_splits:
            final_chunks.extend(self._merge_splits(good_splits, merge_separator))
        return final_chunks

    def _split_with_separator(self, text: str, separator: str) -> List[str]:
        """Splits on `separator`, keeping it attached to the piece that follows."""
        if not separator:
            return [c for c in list(text) if c != ""]

        parts = re.split(f"({re.escape(separator)})", text)
        if self._keep_separator:
            # re.split with a capturing group alternates text, separator, text...
            # Pairing each separator with the following text is what puts the
            # separator at the start of its piece.
            splits = [parts[i] + parts[i + 1] for i in range(1, len(parts), 2)]
            if len(parts) % 2 == 0:
                splits += parts[-1:]
            splits = [parts[0]] + splits
        else:
            splits = re.split(re.escape(separator), text)
        return [s for s in splits if s != ""]

    def _join_docs(self, docs: List[str], separator: str) -> Optional[str]:
        text = separator.join(docs)
        if self._strip_whitespace:
            text = text.strip()
        return text or None

    def _merge_splits(self, splits: Iterable[str], separator: str) -> List[str]:
        """Packs consecutive pieces into chunks, carrying `chunk_overlap` over."""
        separator_len = self._length_function(separator)

        docs: List[str] = []
        current_doc: List[str] = []
        total = 0
        for piece in splits:
            piece_len = self._length_function(piece)
            if (
                total + piece_len + (separator_len if len(current_doc) > 0 else 0)
                > self._chunk_size
            ):
                if total > self._chunk_size:
                    logger.warning(
                        "Created a chunk of size %s, which is longer than the "
                        "specified %s",
                        total,
                        self._chunk_size,
                    )
                if len(current_doc) > 0:
                    doc = self._join_docs(current_doc, separator)
                    if doc is not None:
                        docs.append(doc)
                    # Drop from the front until what is left is small enough to
                    # serve as the overlap for the next chunk.
                    while total > self._chunk_overlap or (
                        total
                        + piece_len
                        + (separator_len if len(current_doc) > 0 else 0)
                        > self._chunk_size
                        and total > 0
                    ):
                        total -= self._length_function(current_doc[0]) + (
                            separator_len if len(current_doc) > 1 else 0
                        )
                        current_doc = current_doc[1:]
            current_doc.append(piece)
            total += piece_len + (separator_len if len(current_doc) > 1 else 0)
        doc = self._join_docs(current_doc, separator)
        if doc is not None:
            docs.append(doc)
        return docs
