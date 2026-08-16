# tests/services/test_embedding_service_batching.py

import pytest
from unittest.mock import MagicMock

from iatoolkit.services.embedding_service import (
    EmbeddingClientWrapper,
    EmbeddingService,
    HuggingFaceClientWrapper,
)


class _BatchingWrapper(EmbeddingClientWrapper):
    """A wrapper whose backend takes lists, so batches are one call each."""

    def __init__(self, fail_batches_containing=None):
        super().__init__(client=None, model="test-model")
        self.batch_calls = []
        self.single_calls = []
        self.fail_batches_containing = fail_batches_containing

    def supports_batching(self) -> bool:
        return True

    def get_embedding(self, text, suppress_error_logging=False):
        self.single_calls.append(text)
        return [float(len(text)), 0.0]

    def get_embeddings(self, texts, suppress_error_logging=False):
        self.batch_calls.append(list(texts))
        if self.fail_batches_containing and self.fail_batches_containing in texts:
            raise RuntimeError("backend rejected the batch")
        return [[float(len(text)), 0.0] for text in texts]


class _SingleOnlyWrapper(EmbeddingClientWrapper):
    """A wrapper with no batch support: must still work, one call per text."""

    def __init__(self):
        super().__init__(client=None, model="test-model")
        self.single_calls = []

    def get_embedding(self, text, suppress_error_logging=False):
        self.single_calls.append(text)
        return [float(len(text)), 1.0]


def _service(wrapper):
    service = EmbeddingService.__new__(EmbeddingService)
    service.profile_repo = MagicMock()
    service.profile_repo.get_company_by_short_name.return_value = MagicMock(id=1)
    service.i18n_service = MagicMock()
    service.client_factory = MagicMock()
    service.client_factory.get_client.return_value = wrapper
    return service


def test_embed_texts_resolves_company_and_client_once_per_call():
    """The per-text company lookup was pure overhead on large backfills."""
    wrapper = _BatchingWrapper()
    service = _service(wrapper)

    service.embed_texts("acme", [f"text-{i}" for i in range(70)])

    assert service.profile_repo.get_company_by_short_name.call_count == 1
    assert service.client_factory.get_client.call_count == 1


def test_embed_texts_batches_by_count():
    wrapper = _BatchingWrapper()
    service = _service(wrapper)

    result = service.embed_texts("acme", [f"t{i}" for i in range(70)], batch_size=32)

    assert [len(batch) for batch in wrapper.batch_calls] == [32, 32, 6]
    assert len(result) == 70


def test_embed_texts_also_splits_on_the_character_budget():
    """A few long texts must not oversize a batch that is small by count."""
    wrapper = _BatchingWrapper()
    service = _service(wrapper)

    service.embed_texts(
        "acme",
        ["x" * 400 for _ in range(10)],
        batch_size=32,
        max_chars_per_batch=1000,
    )

    assert all(sum(len(t) for t in batch) <= 1000 for batch in wrapper.batch_calls)
    assert sum(len(batch) for batch in wrapper.batch_calls) == 10


def test_embed_texts_preserves_input_order():
    wrapper = _BatchingWrapper()
    service = _service(wrapper)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]

    result = service.embed_texts("acme", texts, batch_size=2)

    assert [vector[0] for vector in result] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_embed_texts_retries_individually_when_a_batch_fails():
    """One bad input must not lose the other 31 in its batch."""
    wrapper = _BatchingWrapper(fail_batches_containing="poison")
    service = _service(wrapper)

    result = service.embed_texts("acme", ["ok-1", "poison", "ok-2"], batch_size=8)

    assert len(result) == 3
    assert wrapper.single_calls == ["ok-1", "poison", "ok-2"]


def test_embed_texts_works_without_provider_batch_support():
    wrapper = _SingleOnlyWrapper()
    service = _service(wrapper)

    result = service.embed_texts("acme", ["a", "bb", "ccc"])

    assert len(result) == 3
    assert wrapper.single_calls == ["a", "bb", "ccc"]


def test_embed_texts_returns_empty_without_calling_the_backend():
    wrapper = _BatchingWrapper()
    service = _service(wrapper)

    assert service.embed_texts("acme", []) == []
    assert wrapper.batch_calls == []


# --- HuggingFaceClientWrapper -------------------------------------------------

def _hf_wrapper(tool_config):
    inference_service = MagicMock()
    inference_service._get_tool_config.return_value = tool_config
    wrapper = HuggingFaceClientWrapper(
        client=None,
        model="sentence-transformers/all-MiniLM-L6-v2",
        inference_service=inference_service,
        company_short_name="acme",
        tool_name="text_embeddings",
    )
    return wrapper, inference_service


def test_hf_wrapper_does_not_batch_until_the_endpoint_declares_support():
    """An endpoint on the old handler would reject inputs.texts, so this stays off."""
    wrapper, inference_service = _hf_wrapper({})
    inference_service.predict.return_value = {"embedding": [0.1, 0.2]}

    wrapper.get_embeddings(["a", "b"])

    assert wrapper.supports_batching() is False
    assert inference_service.predict.call_count == 2
    for call_args in inference_service.predict.call_args_list:
        assert "text" in call_args.args[2]


def test_hf_wrapper_sends_one_request_when_batching_is_enabled():
    wrapper, inference_service = _hf_wrapper({"supports_batch_embedding": True})
    inference_service.predict.return_value = {"embeddings": [[0.1], [0.2], [0.3]]}

    result = wrapper.get_embeddings(["a", "b", "c"])

    assert inference_service.predict.call_count == 1
    assert inference_service.predict.call_args.args[2] == {"mode": "text", "texts": ["a", "b", "c"]}
    assert result == [[0.1], [0.2], [0.3]]


def test_hf_wrapper_fails_on_a_length_mismatch_instead_of_misaligning():
    """Pairing the wrong vector with a text is invisible downstream; fail loudly."""
    wrapper, inference_service = _hf_wrapper({"supports_batch_embedding": True})
    inference_service.predict.return_value = {"embeddings": [[0.1]]}

    with pytest.raises(ValueError, match="1 vectors for 3 inputs"):
        wrapper.get_embeddings(["a", "b", "c"])
