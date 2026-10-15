# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""The words the hybrid search looks for (BL-005, Fase 4).

The word branch searches the chunks' full text with Postgres' 'simple'
configuration, which has no stopwords: a question would match every chunk with
"de" or "the". So the question is reduced here to the words that mean something,
and Postgres ORs them (see VSRepo). Exact terms the model passes as `keywords`
take the place of the question.
"""

from __future__ import annotations

import re

# Spanish and English function words. Only what never identifies a document:
# no domain words, no numbers.
STOPWORDS = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes aquel aquella aquello aqui asi aun cada como con
contra cual cuales cualquier cuando cuanto de del desde donde dos el ella ellas ellos en entre era eran es
esa esas ese eso esos esta estaba estado estan estar estas este esto estos fue fueron ha hay hace hacer hacia
han hasta la las le les lo los mas me mi mis mucho muy nada ni no nos nosotros o otra otras otro otros para
pero poco por porque que quien quienes se sea ser si sido sin sobre son su sus tambien tan tanto te tiene
tienen todo todos tu tus un una unas uno unos usted ustedes ya yo
cómo cuál cuáles cuándo cuánto dónde qué quién quiénes también aquí así aún más está están sí tú
a an and are as at be been but by can could did do does for from had has have how i if in into is it its
me my no not of on or our should so than that the their them then there these they this those to was we
were what when where which who why will with would you your
""".split())

# Leading and trailing punctuation that is never part of a term. Inner
# punctuation is kept: AX-2241, 76.123.456-7, v3.2.
_EDGE_PUNCTUATION = "¿?¡!.,;:\"'()[]{}«»“”‘’…"
_MAX_TERMS = 24
_MAX_TERM_CHARS = 64


def search_terms(query_text: str | None, keywords: str | list | None = None) -> str:
    """
    The text the word branch looks for: the keywords when given, else the query
    without stopwords. Empty when nothing is left, and the caller then searches
    by meaning only.
    """
    if keywords:
        raw = keywords if isinstance(keywords, list) else [keywords]
        source = " ".join(str(item) for item in raw if str(item or "").strip())
        return _clean(source, drop_stopwords=False)
    return _clean(str(query_text or ""), drop_stopwords=True)


def _clean(text: str, *, drop_stopwords: bool) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"\s+", text):
        term = token.strip(_EDGE_PUNCTUATION)
        if not term or not any(char.isalnum() for char in term):
            continue
        if drop_stopwords and term.lower() in STOPWORDS:
            continue
        term = term[:_MAX_TERM_CHARS]
        if term.lower() in seen:
            continue
        seen.add(term.lower())
        terms.append(term)
        if len(terms) >= _MAX_TERMS:
            break
    return " ".join(terms)
