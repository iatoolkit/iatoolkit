from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.decision_types import DecisionResult
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_proxy import LLMProxy
from iatoolkit.infra.openrouter_decision_client import OpenRouterDecisionClient
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.decision_attachments import DecisionImage
from iatoolkit.services.decision_service import DecisionService, is_decision_model
from tests.common.test_decision_types import RESPONSE, SPEC

MODEL = "typesafe/jev-1.14"
DECISION_CONFIG = {"id": MODEL, "provider": "openrouter", "capabilities": {"kind": "decision"}, "context_window": 100}


class TestDecisionService:
    def setup_method(self):
        self.config = MagicMock(spec=ConfigurationService)
        self.config.get_llm_configuration.return_value = (None, [{"id": MODEL}, {"id": "gpt-5-mini"}])
        self.config.get_llm_model_config.return_value = dict(DECISION_CONFIG)
        self.config.get_configuration.return_value = {}
        self.proxy = MagicMock(spec=LLMProxy)
        self.proxy.resolve_client_config.return_value = {
            "api_key": "sk-test",
            "base_url": "https://openrouter.ai/api/v1",
            "default_headers": {},
            "connect_timeout_seconds": 5.0,
            "read_timeout_seconds": 30.0,
            "max_retries": 0,
        }
        self.proxy.wire_model.side_effect = lambda model, _config: model
        self.client = MagicMock(spec=OpenRouterDecisionClient)
        self.client.decisions_url.side_effect = OpenRouterDecisionClient.decisions_url
        self.client.decide.return_value = DecisionResult.from_response(RESPONSE, requested_model=MODEL, latency_ms=5)
        self.service = DecisionService(self.config, self.proxy, client=self.client)
        self.release = patch.object(LLMProxy, "_release_database_transaction").start()

    def teardown_method(self):
        patch.stopall()

    def _decide(self, **kwargs):
        params = dict(model=MODEL, state="Asunto: factura vencida", decision_spec=SPEC)
        params.update(kwargs)
        return self.service.decide("acme", **params)

    def test_calls_openrouter_with_the_company_credentials(self):
        result = self._decide(user_identifier="u1")

        assert result.answers["area"].value == "cobranza"
        self.proxy.resolve_client_config.assert_called_once_with("acme", "openrouter", model_config=DECISION_CONFIG)
        kwargs = self.client.decide.call_args.kwargs
        assert kwargs["url"] == "https://openrouter.ai/api/alpha/decisions"
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["state"] == "Asunto: factura vencida"
        assert kwargs["provider_policy"] is None
        assert kwargs["user"] == "u1"
        assert list(kwargs["questions"]) == ["es_cobranza", "area", "urgencia"]
        self.release.assert_called_once()

    def test_sends_the_company_data_policy_and_path_when_configured(self):
        self.config.get_configuration.return_value = {
            "decisions": {"provider": {"zdr": True}, "path": "/api/v1/systemone"}
        }
        self._decide()
        kwargs = self.client.decide.call_args.kwargs
        assert kwargs["provider_policy"] == {"zdr": True}
        assert kwargs["url"] == "https://openrouter.ai/api/v1/systemone"

    def test_a_structured_state_is_sent_as_text(self):
        self._decide(state={"asunto": "factura"})
        assert self.client.decide.call_args.kwargs["state"] == '{"asunto": "factura"}'

    @pytest.mark.parametrize("model, fragment", [
        ("", "needs a decision model"),
        ("~typesafe/jev-latest", "alias"),
        ("typesafe/jev-9", "not a decision model enabled"),
    ])
    def test_rejects_models_it_cannot_use(self, model, fragment):
        with pytest.raises(IAToolkitException) as exc:
            self._decide(model=model)
        assert fragment in str(exc.value)
        self.client.decide.assert_not_called()

    def test_rejects_a_chat_model(self):
        self.config.get_llm_model_config.return_value = {"id": "gpt-5-mini", "provider": "openai", "capabilities": {}}
        with pytest.raises(IAToolkitException) as exc:
            self._decide(model="gpt-5-mini")
        assert "not a decision model" in str(exc.value)

    def test_rejects_a_decision_model_not_routed_to_openrouter(self):
        self.config.get_llm_model_config.return_value = {**DECISION_CONFIG, "provider": "openai"}
        with pytest.raises(IAToolkitException) as exc:
            self._decide()
        assert "only OpenRouter" in str(exc.value)

    def test_rejects_an_invalid_spec_before_calling(self):
        with pytest.raises(IAToolkitException) as exc:
            self._decide(decision_spec={"questions": {}})
        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
        self.client.decide.assert_not_called()

    def test_rejects_an_empty_case(self):
        with pytest.raises(IAToolkitException) as exc:
            self._decide(state="   ")
        assert "empty" in str(exc.value)

    def test_warns_when_the_case_exceeds_the_context_window(self, caplog):
        self._decide(state="x" * 1000)
        assert "over the model's 100-token window" in caplog.text

    def test_logs_a_telemetry_span(self):
        telemetry = MagicMock()
        self._decide(telemetry_execution=telemetry)
        telemetry.start_child_span.assert_called_once()
        assert telemetry.log_child_span.call_args.args[1]["metrics"]["prompt_tokens"] == 567
        telemetry.end_child_span.assert_called_once()

    # --- Images (Etapa 2) ---

    IMAGES = [DecisionImage(name="img_1", data=b"jpeg-1", source="a.png"),
              DecisionImage(name="img_2", data=b"jpeg-2", source="b.pdf", page=1)]

    def test_images_go_as_assets_referenced_from_an_array_state(self):
        self.config.get_llm_model_config.return_value = {
            **DECISION_CONFIG, "capabilities": {"kind": "decision", "input_modalities": ["text", "image"]},
        }
        self._decide(images=self.IMAGES)
        kwargs = self.client.decide.call_args.kwargs
        assert kwargs["state"] == ["Asunto: factura vencida", "img_1", "img_2"]
        assert kwargs["assets"]["img_2"] == {"data_base64": "anBlZy0y", "format": "jpg"}

    def test_scaledown_reads_one_image_as_a_document(self):
        model = "scaledown/classify-1"
        self.config.get_llm_configuration.return_value = (None, [{"id": model}])
        self.config.get_llm_model_config.return_value = {
            **DECISION_CONFIG, "id": model, "capabilities": {"kind": "decision", "input_modalities": ["image"]},
        }
        self._decide(model=model, images=self.IMAGES[:1])
        kwargs = self.client.decide.call_args.kwargs
        assert kwargs["state"] == {"text": "Asunto: factura vencida", "document": "anBlZy0x",
                                   "document_mime_type": "image/jpeg"}
        assert kwargs["assets"] is None
        with pytest.raises(IAToolkitException):
            self._decide(model=model, images=self.IMAGES)

    def test_a_model_that_does_not_read_images_is_refused_before_calling(self):
        with pytest.raises(IAToolkitException) as exc:
            self._decide(images=self.IMAGES)
        assert "does not read images" in str(exc.value)
        self.client.decide.assert_not_called()

    def test_without_images_the_state_stays_text(self):
        self._decide()
        kwargs = self.client.decide.call_args.kwargs
        assert kwargs["state"] == "Asunto: factura vencida" and kwargs["assets"] is None


def test_is_decision_model_reads_the_catalogue_kind():
    assert is_decision_model({"capabilities": {"kind": "decision"}})
    assert is_decision_model({"kind": "decision"})
    assert not is_decision_model({"capabilities": {"supported_parameters": ["tools"]}})
    assert not is_decision_model(None)
