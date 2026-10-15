from iatoolkit.common.search_terms import search_terms


def test_stopwords_and_punctuation_go_inner_punctuation_stays():
    assert search_terms("¿Cuál es el plazo del contrato AX-2241 con Pérez?") == "plazo contrato AX-2241 Pérez"
    assert search_terms("What is the RUT 76.123.456-7 of v3.2?") == "RUT 76.123.456-7 v3.2"


def test_keywords_win_and_keep_every_word():
    assert search_terms("cómo se paga", keywords=["de", "AX-2241"]) == "de AX-2241"
    assert search_terms("cómo se paga", keywords="N° 1234") == "N° 1234"


def test_nothing_meaningful_is_empty_and_repeats_count_once():
    assert search_terms("¿qué es eso?") == ""
    assert search_terms("contrato Contrato CONTRATO") == "contrato"
    assert search_terms("") == ""
