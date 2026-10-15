from datetime import datetime, timedelta

import pytest

from iatoolkit.repositories.memory_question_repo import MemoryQuestionRepo
from iatoolkit.repositories.models import LLMQuery, MemoryCapture, MemoryQuestion, MemoryQuestionCandidate
from iatoolkit.services.memory_question_service import MemoryQuestionService
from iatoolkit.services.system_agent_catalog import SystemAgentCatalog
from tests.services.memory_test_support import MemoryStack


@pytest.fixture
def stack():
    stack = MemoryStack()
    stack.question_repo = MemoryQuestionRepo(stack.db_manager)
    stack.questions = MemoryQuestionService(
        profile_repo=stack.profile_repo,
        question_repo=stack.question_repo,
        memory_service=stack.memory_service,
        system_agent_runner=stack.system_agent_runner,
        db_manager=stack.db_manager,
    )
    return stack


def turn(stack, question, answer, tools=("iat_memory_search",), user="carmen@acme.cl"):
    query = LLMQuery(company_id=stack.company.id, user_identifier=user, query=question, output=answer,
                     function_calls=[{tool: {"query": question}, "time": "0.2"} for tool in tools],
                     created_at=datetime.now() - timedelta(hours=2))
    stack.session.add(query)
    stack.session.commit()
    return query


def model_says(stack, *responses):
    stack.llm_client.invoke.side_effect = [{"structured_output": {"items": items}} for items in responses]


def open_questions(stack):
    return stack.question_repo.list_questions(stack.company.id)


def test_only_turns_that_searched_the_company_are_classified(stack):
    first = turn(stack, "¿Cuál es el plazo de pago a proveedores?", "No encontré esa información.")
    turn(stack, "Escribe un correo", "Listo", tools=())
    turn(stack, "¿Cuántos clientes?", "No sé", user="service:pipeline")
    model_says(stack, [{"ref": f"q{first.id}", "answered": False,
                        "question": "¿Cuál es el plazo de pago a proveedores?", "topic": "pagos"}])

    result = stack.questions.scan_company("acme")

    assert result["counts"]["new_questions"] == 1
    [inputs] = stack.agent_calls("memory_question_review")
    assert [turn["question"] for turn in inputs["turns"]] == ["¿Cuál es el plazo de pago a proveedores?"]
    assert stack.llm_client.invoke.call_args.kwargs["user_identifier"] == "service:memory-questions"
    [question] = open_questions(stack)
    assert question.topic == "pagos"
    assert question.times_asked == 1
    assert stack.question_repo.find_cursor(stack.company.id).last_query_id == first.id + 2


def test_answered_turns_add_no_question(stack):
    first = turn(stack, "¿Plazo de pago?", "45 días, según la política de pagos.")
    model_says(stack, [{"ref": f"q{first.id}", "answered": True}])

    assert stack.questions.scan_company("acme")["counts"]["answered"] == 1
    assert open_questions(stack) == []


def test_a_repeated_question_counts_once_more_and_who_asked_is_not_kept(stack):
    first = turn(stack, "¿Plazo de pago?", "No lo encontré.")
    model_says(stack, [{"ref": f"q{first.id}", "answered": False, "question": "¿Plazo de pago a proveedores?", "topic": "pagos"}])
    stack.questions.scan_company("acme")
    [question] = open_questions(stack)

    second = turn(stack, "¿Cuántos días tenemos para pagar?", "No tengo ese dato.", user="juan@acme.cl")
    third = turn(stack, "y a proveedores grandes?", "No sé.", user="juan@acme.cl")
    model_says(stack, [
        {"ref": f"q{second.id}", "answered": False, "same_as_question_id": question.id},
        {"ref": f"q{third.id}", "answered": False, "question": "¿Plazo para grandes proveedores?", "same_as_ref": None},
    ])
    stack.questions.scan_company("acme")

    questions = open_questions(stack)
    assert [q.times_asked for q in questions] == [2, 1]
    open_in_review = stack.agent_calls("memory_question_review")[-1]["open_questions"]
    assert question.id in [entry["id"] for entry in open_in_review]
    columns = {column.name for column in MemoryQuestion.__table__.columns}
    assert not {"user_identifier", "asked_by"} & columns


def test_same_question_twice_in_a_batch_is_one(stack):
    first = turn(stack, "¿Horario de bodega?", "No sé.")
    second = turn(stack, "¿A qué hora abre la bodega?", "No lo encontré.")
    model_says(stack, [
        {"ref": f"q{first.id}", "answered": False, "question": "¿Horario de la bodega?", "topic": "bodega"},
        {"ref": f"q{second.id}", "answered": False, "same_as_ref": f"q{first.id}"},
    ])

    stack.questions.scan_company("acme")

    [question] = open_questions(stack)
    assert question.times_asked == 2


def test_a_failed_batch_leaves_the_cursor_before_it(stack):
    first = turn(stack, "¿Plazo?", "No sé.")
    stack.llm_client.invoke.side_effect = RuntimeError("model down")

    result = stack.questions.scan_company("acme")

    assert result["status"] == "partial"
    assert stack.question_repo.find_cursor(stack.company.id).last_query_id < first.id


def test_mcp_search_misses_are_classified_with_the_turns(stack):
    stack.questions.record_search_miss("acme", "política de viáticos")
    candidate = stack.session.query(MemoryQuestionCandidate).one()
    model_says(stack, [{"ref": f"m{candidate.id}", "answered": False, "question": "¿Cuál es la política de viáticos?",
                        "topic": "viáticos"}])

    stack.questions.scan_company("acme")

    [question] = open_questions(stack)
    assert question.channels == {"mcp": 1}
    assert candidate.processed_at is not None
    assert not stack.questions.has_pending_work("acme")


def test_nothing_new_does_not_call_the_model(stack):
    turn(stack, "Escribe un poema", "…", tools=())

    stack.questions.scan_company("acme")

    stack.llm_client.invoke.assert_not_called()
    assert not stack.questions.has_pending_work("acme")


def test_answer_saves_a_capture_by_whoever_answered(stack):
    question = stack.question_repo.add(MemoryQuestion(company_id=stack.company.id, question="¿Plazo de pago?"))
    stack.question_repo.commit()

    result = stack.questions.answer("acme", question.id, "45 días desde la factura.", "carmen@acme.cl")

    assert result["question"]["status"] == "answered"
    capture = stack.session.query(MemoryCapture).one()
    assert capture.user_identifier == "carmen@acme.cl"
    assert capture.meta == {"origin": "memory_question", "question_id": question.id}
    assert capture.items[0].content_text == "Pregunta: ¿Plazo de pago?\nRespuesta: 45 días desde la factura."
    assert question.answer_capture_id == capture.id
    stack.trigger.trigger.assert_called_once()
    assert stack.questions.answer("acme", question.id, "otra", "juan@acme.cl")["error_code"] == "already_resolved"


def test_dismiss_and_empty_answer(stack):
    question = stack.question_repo.add(MemoryQuestion(company_id=stack.company.id, question="¿Algo?"))
    stack.question_repo.commit()

    assert stack.questions.answer("acme", question.id, "  ", "carmen@acme.cl")["status"] == "error"
    assert stack.questions.dismiss("acme", question.id, "carmen@acme.cl")["question"]["status"] == "dismissed"
    assert open_questions(stack) == []
    assert stack.questions.dismiss("acme", 999, "carmen@acme.cl")["error_message"] == "question not found"


def test_the_first_scan_starts_with_the_last_days_not_the_whole_history(stack):
    old = turn(stack, "¿Pregunta vieja?", "No sé.")
    old.created_at = datetime.now() - timedelta(days=30)
    stack.session.commit()
    recent = turn(stack, "¿Plazo de pago?", "No lo encontré.")
    recent.created_at = datetime.now() - timedelta(hours=1)
    stack.session.commit()
    model_says(stack, [{"ref": f"q{recent.id}", "answered": False, "question": "¿Plazo de pago?"}])

    stack.questions.scan_company("acme")

    [inputs] = stack.agent_calls("memory_question_review")
    assert [turn["question"] for turn in inputs["turns"]] == ["¿Plazo de pago?"]
    assert [q.question for q in open_questions(stack)] == ["¿Plazo de pago?"]


def test_a_bare_list_in_the_answer_is_understood(stack):
    first = turn(stack, "¿Horario?", "No sé.")
    stack.llm_client.invoke.side_effect = [{
        "structured_output": None, "parsed_output": None,
        "answer": '```json\n[{"id": "q%d", "answered": "false", "question": "¿Horario de atención?"}]\n```' % first.id,
    }]

    result = stack.questions.scan_company("acme")

    assert result["status"] == "success"
    assert [q.question for q in open_questions(stack)] == ["¿Horario de atención?"]


def test_items_under_another_key_are_understood(stack):
    first = turn(stack, "¿Horario?", "No sé.")
    stack.llm_client.invoke.side_effect = [{"structured_output": None, "parsed_output": {
        "turns": [{"turn_ref": f"q{first.id}", "answered": False, "question": "¿Horario?"}]}}]

    assert stack.questions.scan_company("acme")["counts"]["new_questions"] == 1


def test_an_answer_that_cannot_be_read_is_logged_and_the_cursor_stays(stack, caplog):
    first = turn(stack, "¿Horario?", "No sé.")
    stack.llm_client.invoke.side_effect = [{"structured_output": None, "parsed_output": None, "answer": "Lo siento"}]

    result = stack.questions.scan_company("acme")

    assert result["status"] == "partial"
    assert "did not understand the model's answer: Lo siento" in caplog.text
    assert stack.question_repo.find_cursor(stack.company.id).last_query_id < first.id


def test_classification_schema_accepts_nulls():
    from iatoolkit.services.structured_output_service import StructuredOutputService

    result = StructuredOutputService.evaluate_output(
        raw_output={"items": [{"ref": "q1", "answered": False, "same_as_question_id": None, "same_as_ref": None}]},
        schema=SystemAgentCatalog.get(MemoryQuestionService.REVIEW_AGENT).output_schema)
    assert result["schema_valid"] is True


def test_a_bare_list_in_the_raw_output_is_understood_even_when_answer_is_html(stack):
    """As DeepSeek answered in Render (2026-10-15): a bare list, answer rendered to HTML."""
    first = turn(stack, "como se planifican los presupuestos de venta", "No encontré un procedimiento.")
    raw = ('[\n  {"ref": "q%d", "answered": false, "question": "¿Cómo se planifican los presupuestos de venta '
           'en la empresa?", "topic": "presupuestos de venta", "same_as_question_id": null, "same_as_ref": null}\n]'
           % first.id)
    stack.llm_client.invoke.side_effect = [{
        "structured_output": None, "parsed_output": None, "output_text": raw,
        "answer": "<p>[ {&quot;ref&quot;: &quot;q%d&quot; ...} ]</p>" % first.id,
    }]

    result = stack.questions.scan_company("acme")

    assert result["status"] == "success"
    [question] = open_questions(stack)
    assert question.question == "¿Cómo se planifican los presupuestos de venta en la empresa?"
    assert question.topic == "presupuestos de venta"


def test_with_the_review_agent_off_nothing_is_reviewed_and_the_cursor_stays(stack):
    from iatoolkit.services.system_agent_runner import PlatformAgentSettings, SystemAgentRunner

    turn(stack, "¿Plazo de pago?", "No lo encontré.")
    SystemAgentRunner.register_platform_settings_provider(
        lambda key: PlatformAgentSettings(enabled=False) if key == "memory_question_review" else None)
    try:
        result = stack.questions.scan_company("acme")
    finally:
        SystemAgentRunner.register_platform_settings_provider(None)

    assert result["status"] == "skipped"
    stack.llm_client.invoke.assert_not_called()
    cursor = stack.question_repo.find_cursor(stack.company.id)
    before = cursor.last_query_id if cursor else 0
    model_says(stack, [])
    stack.questions.scan_company("acme")
    assert stack.llm_client.invoke.called
    assert stack.question_repo.find_cursor(stack.company.id).last_query_id > before
