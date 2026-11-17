"""The conversations API (BL-001, PR-4)."""

from unittest.mock import MagicMock

import pytest
from flask import Flask

from iatoolkit.repositories.conversation_repo import ConversationRepo
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, LLMQuery
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.conversation_service import ConversationService
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.views.conversations_api_view import ConversationsApiView

ANA, BETO = "ana@acme.cl", "beto@acme.cl"


@pytest.fixture
def api(tmp_path):
    db = DatabaseManager(f"sqlite:///{tmp_path / 'api.db'}")
    db.create_all()
    session = db.get_session()
    company = Company(name="Acme", short_name="acme")
    session.add(company)
    session.commit()
    service = ConversationService(ConversationRepo(db), ProfileRepo(db))
    auth = MagicMock(spec=AuthService)
    auth.verify_for_company.return_value = {"success": True, "user_identifier": ANA}
    llm = MagicMock(spec=llmClient)
    llm.format_answer.side_effect = lambda text, parts=None: f"<p>{text}</p>"
    i18n = MagicMock(**{"t.side_effect": lambda key, **kw: key})

    app = Flask(__name__)
    view = ConversationsApiView.as_view("conversations_api", auth_service=auth, conversation_service=service,
                                        i18n_service=i18n, llm_client=llm)
    app.add_url_rule('/<company_short_name>/api/conversations', view_func=view, methods=['GET', 'POST'])
    app.add_url_rule('/<company_short_name>/api/conversations/<string:conversation_id>', view_func=view,
                     methods=['GET', 'PATCH', 'DELETE'])
    app.add_url_rule('/<company_short_name>/api/conversations/<string:conversation_id>/<string:resource>',
                     view_func=view, methods=['GET', 'POST'])
    client = app.test_client()
    client.service, client.auth, client.session, client.company = service, auth, session, company
    return client


def _as(api, user):
    api.auth.verify_for_company.return_value = {"success": True, "user_identifier": user}


class TestConversationsApi:
    def test_create_list_and_read(self, api):
        created = api.post("/acme/api/conversations", json={"title": "Ventas"})
        assert created.status_code == 201
        conversation_id = created.get_json()["conversation"]["id"]
        api.post("/acme/api/conversations", json={"title": "Garantías"})

        listed = api.get("/acme/api/conversations").get_json()
        assert [c["title"] for c in listed["conversations"]] == ["Garantías", "Ventas"]
        assert listed["has_more"] is False
        assert api.get(f"/acme/api/conversations/{conversation_id}").get_json()["conversation"]["title"] == "Ventas"

    def test_search_pages_and_archived(self, api):
        for title in ("uno", "dos", "tres"):
            api.post("/acme/api/conversations", json={"title": title})

        page = api.get("/acme/api/conversations?limit=2").get_json()
        assert len(page["conversations"]) == 2 and page["has_more"] is True
        assert [c["title"] for c in api.get("/acme/api/conversations?q=do").get_json()["conversations"]] == ["dos"]

        conversation_id = page["conversations"][0]["id"]
        assert api.patch(f"/acme/api/conversations/{conversation_id}", json={"status": "archived"}).status_code == 200
        archived = api.get("/acme/api/conversations?archived=1").get_json()["conversations"]
        assert [c["id"] for c in archived] == [conversation_id]
        api.patch(f"/acme/api/conversations/{conversation_id}", json={"status": "active"})
        assert api.get("/acme/api/conversations?archived=1").get_json()["conversations"] == []

    def test_rename_and_delete(self, api):
        conversation_id = api.post("/acme/api/conversations", json={}).get_json()["conversation"]["id"]

        renamed = api.patch(f"/acme/api/conversations/{conversation_id}", json={"title": "Mi análisis"})
        assert renamed.get_json()["conversation"]["title_source"] == "user"
        assert api.patch(f"/acme/api/conversations/{conversation_id}", json={"title": " "}).status_code == 400
        assert api.delete(f"/acme/api/conversations/{conversation_id}").status_code == 200
        assert api.get(f"/acme/api/conversations/{conversation_id}").status_code == 404

    def test_someone_elses_conversation_is_404_on_every_route(self, api):
        conversation_id = api.post("/acme/api/conversations", json={}).get_json()["conversation"]["id"]
        _as(api, BETO)

        assert api.get(f"/acme/api/conversations/{conversation_id}").status_code == 404
        assert api.get(f"/acme/api/conversations/{conversation_id}/messages").status_code == 404
        assert api.patch(f"/acme/api/conversations/{conversation_id}", json={"title": "x"}).status_code == 404
        assert api.delete(f"/acme/api/conversations/{conversation_id}").status_code == 404
        assert api.get("/acme/api/conversations").get_json()["conversations"] == []

    def test_messages_render_each_answer_with_its_parts_and_activity(self, api):
        conversation = api.service.create("acme", ANA, title="Gráfico")
        query = LLMQuery(company_id=api.company.id, user_identifier=ANA, query="q", output="Así fue:\n\n[[chart:abc]]",
                         response={"parts": [{"id": "abc", "kind": "chart"}]},
                         stats={"response_time": 9, "stream": {"first_text_ms": 6200}},
                         function_calls=[{"iat_chart": {"x": "m"}, "time": "1.5", "result": {"status": "ok"}},
                                         {"iat_sql_query": {}, "time": "0.2", "result": {"status": "error"}}])
        api.session.add(query)
        api.session.commit()
        api.service.append_turn(conversation, question="grafica", answer_text="Así fue", llm_query_id=query.id,
                                user_identifier=ANA)
        api.service.append_failed_turn(conversation, question="otra", error_message="falló", user_identifier=ANA)

        body = api.get(f"/acme/api/conversations/{conversation.public_id}/messages").get_json()

        user, assistant, user2, event = body["messages"]
        assert user["role"] == "user" and user["content"] == "grafica"
        assert assistant["answer"] == "<p>Así fue:\n\n[[chart:abc]]</p>"
        assert assistant["parts"] == [{"id": "abc", "kind": "chart"}]
        assert assistant["activity"] == {"duration_ms": 6200, "tools": [
            {"name": "iat_chart", "ok": True, "ms": 1500}, {"name": "iat_sql_query", "ok": False, "ms": 200}]}
        assert event == {"id": event["id"], "role": "system_event", "created_at": event["created_at"],
                         "content": "falló", "event": "error"}

    def test_a_failed_authentication_is_returned(self, api):
        api.auth.verify_for_company.return_value = {"success": False, "status_code": 401, "error_message": "auth"}

        assert api.get("/acme/api/conversations").status_code == 401
