from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.conversation_repo import ConversationRepo
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.repositories.models import Company, Conversation, ConversationMessage, LLMQuery
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.conversation_service import ConversationService

ANA = "ana@acme.cl"
BETO = "beto@acme.cl"


class TestConversationService:
    def setup_method(self):
        self.db = DatabaseManager("sqlite:///:memory:")
        self.db.create_all()
        self.session = self.db.get_session()
        self.acme = Company(name="Acme", short_name="acme")
        self.other = Company(name="Other", short_name="other")
        self.session.add_all([self.acme, self.other])
        self.session.commit()
        self.repo = ConversationRepo(self.db)
        self.service = ConversationService(self.repo, ProfileRepo(self.db))

    def _query(self, output="respuesta"):
        query = LLMQuery(company_id=self.acme.id, user_identifier=ANA, query="q", output=output)
        self.session.add(query)
        self.session.commit()
        return query

    # -------------------------------------------------------------- create / read
    def test_create_gives_a_public_id_and_starts_active(self):
        conversation = self.service.create("acme", ANA, title="Ventas 2026", model="gpt-5.2")

        assert len(conversation.public_id) == 32
        assert conversation.status == Conversation.STATUS_ACTIVE
        assert conversation.title_source == Conversation.TITLE_AUTO
        assert conversation.project_id is None

    def test_a_conversation_of_someone_else_is_not_found(self):
        conversation = self.service.create("acme", ANA)

        assert self.service.get_for_user("acme", ANA, conversation.public_id) is not None
        assert self.service.get_for_user("acme", BETO, conversation.public_id) is None
        assert self.service.get_for_user("other", ANA, conversation.public_id) is None
        with pytest.raises(IAToolkitException) as error:
            self.service.require_for_user("acme", BETO, conversation.public_id)
        assert error.value.error_type == IAToolkitException.ErrorType.NOT_FOUND

    def test_list_is_the_owners_newest_first_by_status_and_title(self):
        first = self.service.create("acme", ANA, title="Garantías por mes")
        second = self.service.create("acme", ANA, title="Ventas por país")
        self.service.create("acme", BETO, title="De Beto")
        self.service.append_turn(first, question="otra", answer_text="r", llm_query_id=None, user_identifier=ANA)
        archived = self.service.archive(self.service.create("acme", ANA, title="Vieja"))

        titles = [c.title for c in self.service.list_for_user("acme", ANA)]
        assert titles == ["Garantías por mes", "Ventas por país"]
        assert [c.title for c in self.service.list_for_user("acme", ANA, search="país")] == ["Ventas por país"]
        assert [c.public_id for c in self.service.list_for_user("acme", ANA, archived=True)] == [archived.public_id]
        assert second.public_id in [c.public_id for c in self.service.list_for_user("acme", ANA, limit=5)]

    def test_deleted_is_gone_but_archived_comes_back(self):
        conversation = self.service.create("acme", ANA)

        self.service.archive(conversation)
        self.service.restore(conversation)
        assert self.service.list_for_user("acme", ANA)[0].public_id == conversation.public_id
        self.service.delete(conversation)
        assert self.service.get_for_user("acme", ANA, conversation.public_id) is None
        assert self.service.list_for_user("acme", ANA) == []

    # -------------------------------------------------------------- titles
    def test_the_initial_title_is_the_question_cut_short(self):
        long_question = "dame un pie chart con los productos top 10 del año 2026 separados por categoría y región"

        title = ConversationService.initial_title(long_question)

        assert len(title) <= ConversationService.INITIAL_TITLE_CHARS + 1
        assert title.endswith("…") and title.startswith("dame un pie chart")
        assert ConversationService.initial_title("", prompt_name="analisis_ventas") == "analisis ventas"

    def test_a_title_the_person_chose_is_never_replaced(self):
        conversation = self.service.create("acme", ANA, title="dame las ventas")

        assert self.service.set_generated_title(conversation, '"Ventas 2026"') is True
        assert conversation.title == "Ventas 2026"
        assert conversation.title_source == Conversation.TITLE_GENERATED
        self.service.rename(conversation, "Mis ventas")
        assert self.service.set_generated_title(conversation, "Otra cosa") is False
        assert conversation.title == "Mis ventas"

    def test_an_empty_rename_is_refused(self):
        conversation = self.service.create("acme", ANA)

        with pytest.raises(IAToolkitException):
            self.service.rename(conversation, "   ")

    # -------------------------------------------------------------- turns
    def test_a_turn_is_the_question_and_the_answer_linked_to_its_query(self):
        conversation = self.service.create("acme", ANA)
        query = self._query("Hay **42**.")

        user, assistant = self.service.append_turn(conversation, question="¿cuántos?", answer_text="Hay **42**.",
                                                   llm_query_id=query.id, user_identifier=ANA)

        messages = self.service.messages(conversation)
        assert [m.role for m in messages] == [ConversationMessage.ROLE_USER, ConversationMessage.ROLE_ASSISTANT]
        assert messages[0].author_user_identifier == ANA
        assert messages[1].llm_query_id == query.id
        assert self.repo.get_queries(self.acme.id, [query.id])[query.id].output == "Hay **42**."

    def test_failed_and_cancelled_turns_are_recorded(self):
        conversation = self.service.create("acme", ANA)

        self.service.append_failed_turn(conversation, question="x", error_message="el modelo falló",
                                        user_identifier=ANA)
        self.service.append_cancelled_turn(conversation, question="y", user_identifier=ANA)

        roles = [(m.role, m.content, m.meta) for m in self.service.messages(conversation)]
        assert roles[1] == (ConversationMessage.ROLE_SYSTEM_EVENT, "el modelo falló", {"event": "error"})
        assert roles[2] == (ConversationMessage.ROLE_USER, "y", {"stopped": True})

    def test_recent_turns_are_the_latest_oldest_first(self):
        conversation = self.service.create("acme", ANA)
        for index in range(4):
            self.service.append_turn(conversation, question=f"q{index}", answer_text=f"a{index}",
                                     llm_query_id=None, user_identifier=ANA)

        recent = self.service.recent_turns(conversation, 4)

        assert [m.content for m in recent] == ["q2", "a2", "q3", "a3"]

    def test_first_turn(self):
        conversation = self.service.create("acme", ANA)
        self.service.append_turn(conversation, question="q", answer_text="a", llm_query_id=None, user_identifier=ANA)
        assert self.service.is_first_turn(conversation) is True
        self.service.append_turn(conversation, question="q", answer_text="a", llm_query_id=None, user_identifier=ANA)
        assert self.service.is_first_turn(conversation) is False

    def test_meta_keeps_what_was_there(self):
        conversation = self.service.create("acme", ANA)

        self.service.save_meta(conversation, compaction_summary="resumen")
        self.service.save_meta(conversation, other=1)

        assert conversation.meta == {"compaction_summary": "resumen", "other": 1}


class TestGeneratedTitle:
    """The conversation_title system agent (BL-001, PR-5)."""

    def setup_method(self):
        TestConversationService.setup_method(self)
        self.runner = MagicMock()
        self.runner.run.return_value = {"structured_output": {"title": "Garantías emitidas por mes 2026"}}
        self.service.system_agent_runner = self.runner

    def _answered(self):
        conversation = self.service.create("acme", ANA, title="genera un gráfico con las garantías…")
        self.service.append_turn(conversation, question="genera un gráfico con las garantías por mes",
                                 answer_text="Así fue el año " + "x" * 3000, llm_query_id=None, user_identifier=ANA)
        return conversation

    def test_the_agent_titles_a_new_conversation_from_its_first_turn(self):
        conversation = self._answered()

        with patch("iatoolkit.services.system_agent_runner.SystemAgentRunner.is_enabled", return_value=True):
            self.service.generate_title("acme", ANA, conversation)

        assert conversation.title == "Garantías emitidas por mes 2026"
        assert conversation.title_source == Conversation.TITLE_GENERATED
        company, key, inputs = self.runner.run.call_args.args
        assert key == "conversation_title" and company.short_name == "acme"
        assert inputs["question"] == "genera un gráfico con las garantías por mes"
        assert len(inputs["answer"]) == ConversationService.TITLE_ANSWER_CHARS
        assert self.runner.run.call_args.kwargs == {"user_identifier": ANA}

    def test_a_title_already_generated_or_chosen_is_kept(self):
        conversation = self._answered()
        self.service.rename(conversation, "Mío")

        with patch("iatoolkit.services.system_agent_runner.SystemAgentRunner.is_enabled", return_value=True):
            self.service.generate_title("acme", ANA, conversation)

        self.runner.run.assert_not_called()
        assert conversation.title == "Mío"

    def test_without_an_answer_or_with_the_agent_off_nothing_happens(self):
        empty = self.service.create("acme", ANA, title="x")
        answered = self._answered()

        with patch("iatoolkit.services.system_agent_runner.SystemAgentRunner.is_enabled", return_value=False):
            self.service.generate_title("acme", ANA, empty)
            self.service.generate_title("acme", ANA, answered)

        self.runner.run.assert_not_called()
        assert answered.title_source == Conversation.TITLE_AUTO

    def test_a_failing_agent_keeps_the_title(self):
        conversation = self._answered()
        self.runner.run.side_effect = RuntimeError("model down")

        with patch("iatoolkit.services.system_agent_runner.SystemAgentRunner.is_enabled", return_value=True):
            self.service.generate_title("acme", ANA, conversation)

        assert conversation.title == "genera un gráfico con las garantías…"
