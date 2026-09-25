"""Pins RecursiveCharacterTextSplitter to the output langchain used to produce.

The values below were captured from langchain_text_splitters 0.3.6 while it was
still installed, then the dependency was dropped. They are not "whatever the
code does today": if a change here moves a single boundary, documents embedded
before and after that change get chunked differently, and the same question
retrieves different passages depending on when a document was ingested.

A failure means the split changed, not that the fixture is stale. Re-capturing
it is only correct together with a decision to re-ingest the corpus.
"""

import hashlib
import random
import string

from iatoolkit.common.text_splitter import RecursiveCharacterTextSplitter


# What KnowledgeBaseService configures.
PRODUCTION_CONFIG = {
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "separators": ["\n\n", "\n", ".", " ", ""],
}


def _split(text, **overrides):
    config = {**PRODUCTION_CONFIG, **overrides}
    return RecursiveCharacterTextSplitter(**config).split_text(text)


class TestRecursiveCharacterTextSplitter:

    def test_text_under_chunk_size_is_returned_whole(self):
        text = "uno dos tres.\n\ncuatro cinco seis.\n\nsiete ocho nueve."
        assert _split(text) == [text]

    def test_separator_is_kept_at_the_start_of_the_following_piece(self):
        # Joining on the separator instead of "" would duplicate every dot.
        assert _split("a.b.c." * 6) == ["a.b.c.a.b.c.a.b.c.a.b.c.a.b.c.a.b.c."]

    def test_a_word_longer_than_chunk_size_is_cut_by_the_empty_separator(self):
        chunks = _split("inicio " + "z" * 1200)
        assert chunks[0] == "inicio"
        assert len(chunks) == 3
        assert "".join(chunks[1:]) == "z" * 1200 + "z" * 100  # 100 = the overlap
        assert all(len(c) <= PRODUCTION_CONFIG["chunk_size"] for c in chunks[1:])

    def test_empty_text_produces_no_chunks(self):
        assert _split("") == []

    def test_overlap_larger_than_chunk_size_is_rejected(self):
        try:
            RecursiveCharacterTextSplitter(chunk_size=10, chunk_overlap=20)
        except ValueError as exc:
            assert "larger chunk overlap" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_generated_corpus_matches_the_langchain_baseline(self):
        """Exact-output check over 60 pseudo-random documents.

        The seed and the alphabet are fixed, so the corpus is the same on every
        run and on every machine. The hash covers every chunk of every document
        in order, which is the whole boundary decision in one value.
        """
        rnd = random.Random(20260925)
        alphabet = string.ascii_letters + " \n."
        digest = hashlib.sha256()
        for _ in range(60):
            text = "".join(rnd.choices(alphabet, k=rnd.randint(0, 6000)))
            for chunk in _split(text):
                digest.update(chunk.encode())
                digest.update(b"\x00")

        assert digest.hexdigest() == (
            "38735b5d1e6f3356201ef8396dd020bf898f40d0bf8d188a051e383ff78526c7"
        )
