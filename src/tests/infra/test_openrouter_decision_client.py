import json

import httpx
import pytest

from iatoolkit.common.decision_types import parse_decision_spec
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.openrouter_decision_client import OpenRouterDecisionClient
from tests.common.test_decision_types import RESPONSE, SPEC

URL = "https://openrouter.ai/api/alpha/decisions"


def _client(responses, calls):
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return OpenRouterDecisionClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )


def _decide(client, **kwargs):
    params = dict(
        api_key="sk-test",
        url=URL,
        model="typesafe/jev-1.14",
        state="Asunto: factura vencida",
        questions=parse_decision_spec(SPEC),
    )
    params.update(kwargs)
    return client.decide(**params)


class TestDecisionsUrl:
    @pytest.mark.parametrize("base_url, path, expected", [
        ("https://openrouter.ai/api/v1", None, URL),
        (None, None, URL),
        ("https://gw.example.com/openrouter/v1", "/api/v1/systemone", "https://gw.example.com/api/v1/systemone"),
        ("https://openrouter.ai/api/v1", "api/alpha/decisions", URL),
    ])
    def test_keeps_the_origin_and_uses_the_decisions_path(self, base_url, path, expected):
        assert OpenRouterDecisionClient.decisions_url(base_url, path) == expected


class TestDecide:
    def test_sends_the_contract_and_parses_the_answers(self):
        calls = []
        client = _client([(200, RESPONSE)], calls)

        result = _decide(client, provider_policy={"zdr": True}, default_headers={"X-Title": "IAToolkit"}, user="u1")

        assert result.answers["area"].value == "cobranza"
        sent = json.loads(calls[0].content)
        assert sent["model"] == "typesafe/jev-1.14"
        assert sent["state"] == "Asunto: factura vencida"
        assert sent["provider"] == {"zdr": True}
        assert sent["user"] == "u1"
        assert sent["questions"]["area"]["criteria"]["legal"] == "Reclamos formales."
        assert calls[0].headers["authorization"] == "Bearer sk-test"
        assert calls[0].headers["x-title"] == "IAToolkit"

    def test_omits_provider_when_there_is_no_policy(self):
        calls = []
        _decide(_client([(200, RESPONSE)], calls))
        assert "provider" not in json.loads(calls[0].content)

    def test_retries_429_and_5xx(self):
        calls = []
        client = _client([(429, {"error": {"code": 429, "message": "slow down"}}), (502, {}), (200, RESPONSE)], calls)
        assert _decide(client).model == "typesafe/jev-1.14-20261014"
        assert len(calls) == 3

    def test_does_not_retry_a_400(self):
        calls = []
        client = _client([(400, {"error": {"code": 400, "message": "questions.area.criteria: Required"}})], calls)
        with pytest.raises(IAToolkitException) as exc:
            _decide(client)
        assert len(calls) == 1
        assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
        assert "questions.area.criteria" in str(exc.value)

    def test_a_404_is_reported_as_the_data_policy(self):
        calls = []
        client = _client([(404, {"error": {"code": 404, "message": "No endpoints found matching your data policy"}})], calls)
        with pytest.raises(IAToolkitException) as exc:
            _decide(client)
        assert len(calls) == 1
        assert "llm.decisions.provider" in str(exc.value)

    def test_gives_up_after_the_retries(self):
        calls = []
        client = _client([(503, {})] * 3, calls)
        with pytest.raises(IAToolkitException) as exc:
            _decide(client)
        assert len(calls) == 3
        assert exc.value.error_type == IAToolkitException.ErrorType.LLM_ERROR

    def test_with_images_a_server_error_is_not_retried_but_a_rate_limit_is(self):
        assets = {"img_1": {"data_base64": "eA==", "format": "jpg"}}
        calls = []
        with pytest.raises(IAToolkitException):
            _decide(_client([(500, {}), (200, RESPONSE)], calls), state=["caso", "img_1"], assets=assets)
        assert len(calls) == 1
        calls = []
        _decide(_client([(429, {}), (200, RESPONSE)], calls), state=["caso", "img_1"], assets=assets)
        assert len(calls) == 2
        sent = json.loads(calls[1].content)
        assert sent["assets"] == assets and sent["state"] == ["caso", "img_1"]
