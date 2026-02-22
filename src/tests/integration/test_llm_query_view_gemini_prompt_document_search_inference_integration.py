import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask

from iatoolkit.common.util import Utility
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.repositories.models import Company
from iatoolkit.services.context_builder_service import ContextBuilderService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.embedding_service import EmbeddingClientFactory, EmbeddingService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.query_service import QueryService
from iatoolkit.services.tool_service import ToolService
from iatoolkit.views.llmquery_api_view import LLMQueryApiView


COMPANY_SHORT_NAME = "test-api-comp"
USER_IDENTIFIER = "api-user-789"
MODEL = "gemini-2.5-flash"
PROMPT_NAME = "reporte_semantico"


class FakeI18nService:
    def t(self, key, **kwargs):
        return f"translated:{key}"


class FakeProfileRepo:
    def __init__(self, company):
        self.company = company

    def get_company_by_short_name(self, short_name=None, **kwargs):
        return self.company if short_name == self.company.short_name else None


class FakeProfileService:
    def get_profile_by_identifier(self, company_short_name, user_identifier):
        return {"role": "analista"}


class FakePromptService:
    def get_prompt_content(self, company, prompt_name):
        assert prompt_name == PROMPT_NAME
        return (
            "PROMPT-EJECUTADO {{ company.short_name }} "
            "usuario={{ user_identifier }} region={{ region }} role={{ role }}"
        )


class FakeConfigService:
    def get_configuration(self, company_short_name, section):
        if section == "embedding_provider":
            return {
                "provider": "huggingface",
                "model": "bge-base-es",
                "tool_name": "text_embeddings",
            }
        return {}


class FakeInferenceService:
    def __init__(self):
        self.calls = []

    def predict(self, company_short_name, tool_name, input_data):
        self.calls.append(
            {
                "company_short_name": company_short_name,
                "tool_name": tool_name,
                "input_data": input_data,
            }
        )
        return {"embedding": [0.11, 0.22, 0.33]}


class FakeSemanticKnowledgeBaseService:
    def __init__(self, embedding_service):
        self.embedding_service = embedding_service
        self.search_calls = []

    def search(self, company_short_name, query, n_results=5, collection=None, metadata_filter=None):
        embedding = self.embedding_service.embed_text(company_short_name, query)
        self.search_calls.append(
            {
                "company_short_name": company_short_name,
                "query": query,
                "n_results": n_results,
                "collection": collection,
                "metadata_filter": metadata_filter,
                "embedding": embedding,
            }
        )

        return [
            {
                "id": 1,
                "document_id": 10,
                "filename": "manual_seguridad.pdf",
                "url": "https://signed.example/manual_seguridad.pdf",
                "text": "El manual exige casco y guantes en planta.",
                "meta": {"type": "manual"},
                "chunk_meta": {"source_type": "text", "page": 3},
            }
        ]


class FakeToolLLMQueryRepo:
    def __init__(self):
        self.saved_queries = []
        self.tool_record = SimpleNamespace(
            name="iat_document_search",
            description="Busca documentos por similitud semántica",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "collection": {"type": "string"},
                    "n_results": {"type": "integer"},
                    "metadata_filter": {"type": "object"},
                },
                "required": ["query"],
            },
            is_active=True,
        )
        self.system_tool_definition = SimpleNamespace(tool_type="SYSTEM")

    def add_query(self, query):
        query.id = len(self.saved_queries) + 1
        self.saved_queries.append(query)

    def rollback(self):
        return None

    def get_company_tools(self, company):
        return [self.tool_record]

    def get_tool_definition(self, company, tool_name):
        return None

    def get_system_tool(self, tool_name):
        if tool_name == "iat_document_search":
            return self.system_tool_definition
        return None


class FakeModelRegistry:
    def get_history_type(self, model):
        return "client_side"

    def resolve_request_params(self, model, text):
        return {
            "text": text or {},
            "reasoning": {},
        }


class FakeHistoryManager:
    def __init__(self):
        self.updates = []

    def populate_request_params(self, handle, user_turn_prompt, ignore_history):
        handle.request_params = {
            "previous_response_id": "ctx_gemini_prev_1",
            "context_history": [],
        }
        return False

    def update_history(self, handle, user_turn_prompt, response):
        self.updates.append(
            {
                "handle": handle,
                "user_turn_prompt": user_turn_prompt,
                "response": response,
            }
        )


class FakeCompanyRegistry:
    def __init__(self, company_short_name):
        self._revision = 1
        self._instances = {company_short_name: object()}

    def get_revision(self):
        return self._revision

    def get_all_company_instances(self):
        return self._instances


class FakeLLMProxy:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def create_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[len(self.calls) - 1]


def test_prompt_execution_with_gemini_document_search_and_inference_embeddings():
    app = Flask(__name__)
    client = app.test_client()

    company = Company(id=1, name="Test Company", short_name=COMPANY_SHORT_NAME)
    i18n_service = FakeI18nService()
    utility = Utility()

    profile_repo = FakeProfileRepo(company)

    inference_service = FakeInferenceService()
    embedding_factory = EmbeddingClientFactory(
        config_service=FakeConfigService(),
        call_service=MagicMock(),
        inference_service=inference_service,
        secret_provider=MagicMock(),
    )
    embedding_service = EmbeddingService(
        client_factory=embedding_factory,
        profile_repo=profile_repo,
        i18n_service=i18n_service,
    )

    semantic_kb_service = FakeSemanticKnowledgeBaseService(embedding_service)
    llmquery_repo = FakeToolLLMQueryRepo()

    tool_service = ToolService(
        llm_query_repo=llmquery_repo,
        knowledge_base_service=semantic_kb_service,
        visual_kb_service=MagicMock(),
        visual_tool_service=MagicMock(),
        profile_repo=profile_repo,
        sql_service=MagicMock(),
        excel_service=MagicMock(),
        mail_service=MagicMock(),
    )

    dispatcher = Dispatcher(
        llmquery_repo=llmquery_repo,
        inference_service=MagicMock(),
        util=utility,
    )
    dispatcher._tool_service = tool_service
    dispatcher._company_registry = FakeCompanyRegistry(COMPANY_SHORT_NAME)

    context_builder = ContextBuilderService(
        profile_service=FakeProfileService(),
        profile_repo=profile_repo,
        company_context_service=MagicMock(),
        parsing_service=MagicMock(),
        tool_service=tool_service,
        prompt_service=FakePromptService(),
        util=utility,
    )

    first_response = LLMResponse(
        id="resp_gemini_1",
        model=MODEL,
        status="completed",
        output_text="",
        output=[
            ToolCall(
                call_id="call_doc_1",
                type="function_call",
                name="iat_document_search",
                arguments=json.dumps(
                    {
                        "query": "manual de seguridad",
                        "collection": "manuales",
                        "n_results": 3,
                        "metadata_filter": {"doc.type": "manual"},
                    }
                ),
            )
        ],
        usage=Usage(input_tokens=120, output_tokens=30, total_tokens=150),
    )

    second_response = LLMResponse(
        id="resp_gemini_2",
        model=MODEL,
        status="completed",
        output_text=json.dumps(
            {
                "answer": "Según el manual de seguridad, se exige casco y guantes.",
                "aditional_data": {},
            }
        ),
        output=[],
        usage=Usage(input_tokens=40, output_tokens=18, total_tokens=58),
    )

    llm_proxy = FakeLLMProxy([first_response, second_response])

    llm_client = llmClient(
        llmquery_repo=llmquery_repo,
        llm_proxy=llm_proxy,
        model_registry=FakeModelRegistry(),
        storage_service=MagicMock(),
        util=utility,
    )
    llm_client._dispatcher = dispatcher
    llm_client.count_tokens = lambda text, history=None: 15

    query_service = QueryService(
        dispatcher=dispatcher,
        tool_service=tool_service,
        llm_client=llm_client,
        profile_repo=profile_repo,
        i18n_service=i18n_service,
        session_context=MagicMock(),
        configuration_service=MagicMock(),
        history_manager=FakeHistoryManager(),
        model_registry=FakeModelRegistry(),
        context_builder=context_builder,
    )

    auth_service = MagicMock()
    auth_service.verify.return_value = {"success": True, "user_identifier": USER_IDENTIFIER}

    view = LLMQueryApiView.as_view(
        "llm_query_api_gemini_integration",
        auth_service=auth_service,
        query_service=query_service,
        profile_service=MagicMock(),
        i18n_service=i18n_service,
    )
    app.add_url_rule("/<company_short_name>/api/query", view_func=view, methods=["POST"])

    response = client.post(
        f"/{COMPANY_SHORT_NAME}/api/query",
        json={
            "prompt_name": PROMPT_NAME,
            "client_data": {"region": "latam"},
            "model": MODEL,
        },
    )

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["valid_response"] is True
    assert payload["model"] == MODEL
    assert payload["response_id"] == "resp_gemini_2"
    assert "casco y guantes" in payload["answer"]

    assert len(llm_proxy.calls) == 2

    first_user_prompt = llm_proxy.calls[0]["input"][0]["content"]
    assert "PROMPT-EJECUTADO test-api-comp" in first_user_prompt
    assert "region=latam" in first_user_prompt
    assert "role=analista" in first_user_prompt

    assert llm_proxy.calls[0]["tools"][0]["name"] == "iat_document_search"

    function_output_event = llm_proxy.calls[1]["input"][1]
    assert function_output_event["type"] == "function_call_output"
    assert function_output_event["call_id"] == "call_doc_1"

    tool_output = json.loads(function_output_event["output"])
    assert tool_output["status"] == "success"
    assert tool_output["count"] == 1
    assert "serialized_context" in tool_output

    assert len(semantic_kb_service.search_calls) == 1
    kb_call = semantic_kb_service.search_calls[0]
    assert kb_call["query"] == "manual de seguridad"
    assert kb_call["embedding"] == [0.11, 0.22, 0.33]

    assert len(inference_service.calls) == 1
    inference_call = inference_service.calls[0]
    assert inference_call["tool_name"] == "text_embeddings"
    assert inference_call["input_data"] == {
        "mode": "text",
        "text": "manual de seguridad",
    }

    assert len(llmquery_repo.saved_queries) == 1
