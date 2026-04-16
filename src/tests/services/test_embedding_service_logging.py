from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.repositories.models import Company
from iatoolkit.services.embedding_service import EmbeddingService, HuggingFaceClientWrapper


class TestEmbeddingServiceLogging:
    def test_embed_text_suppresses_error_logging_when_requested(self):
        client_factory = MagicMock()
        profile_repo = MagicMock()
        i18n_service = MagicMock()

        profile_repo.get_company_by_short_name.return_value = Company(id=1, short_name="acme")

        wrapper = MagicMock()
        wrapper.get_embedding.side_effect = RuntimeError("endpoint warming up")
        client_factory.get_client.return_value = wrapper

        service = EmbeddingService(
            client_factory=client_factory,
            profile_repo=profile_repo,
            i18n_service=i18n_service,
        )

        with patch("iatoolkit.services.embedding_service.logging.error") as mock_log_error:
            with pytest.raises(RuntimeError, match="endpoint warming up"):
                service.embed_text("acme", "hello", suppress_error_logging=True)

        mock_log_error.assert_not_called()

    def test_embed_text_keeps_normal_error_logging_by_default(self):
        client_factory = MagicMock()
        profile_repo = MagicMock()
        i18n_service = MagicMock()

        profile_repo.get_company_by_short_name.return_value = Company(id=1, short_name="acme")

        wrapper = MagicMock()
        wrapper.get_embedding.side_effect = RuntimeError("endpoint down")
        client_factory.get_client.return_value = wrapper

        service = EmbeddingService(
            client_factory=client_factory,
            profile_repo=profile_repo,
            i18n_service=i18n_service,
        )

        with patch("iatoolkit.services.embedding_service.logging.error") as mock_log_error:
            with pytest.raises(RuntimeError, match="endpoint down"):
                service.embed_text("acme", "hello")

        mock_log_error.assert_called_once()

    def test_huggingface_wrapper_forwards_suppress_error_logging(self):
        inference_service = MagicMock()
        inference_service.predict.return_value = {"embedding": [0.1, 0.2]}

        wrapper = HuggingFaceClientWrapper(
            client=None,
            model="hf-model",
            inference_service=inference_service,
            company_short_name="acme",
            tool_name="text_embeddings",
        )

        result = wrapper.get_embedding("hello", suppress_error_logging=True)

        assert result == [0.1, 0.2]
        inference_service.predict.assert_called_once_with(
            "acme",
            "text_embeddings",
            {"mode": "text", "text": "hello"},
            suppress_error_logging=True,
        )
