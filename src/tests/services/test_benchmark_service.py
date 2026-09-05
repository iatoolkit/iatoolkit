from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.benchmark_service import BenchmarkService


def _service(company=None):
    query_service = MagicMock()
    profile_repo = MagicMock()
    profile_repo.get_company_by_short_name.return_value = company or SimpleNamespace(short_name="acme")
    return BenchmarkService(query_service=query_service, profile_repo=profile_repo), query_service, profile_repo


def _write_benchmark(path, rows):
    pd.DataFrame(rows).to_excel(path, index=False)


def test_run_executes_cases_and_writes_result_workbook(tmp_path):
    input_path = tmp_path / "bench.xlsx"
    _write_benchmark(input_path, [
        {
            "username": "u1",
            "client_identity": "c1",
            "prompt_name": "prompt_a",
            "question": "Question A",
            "model": "gpt-5",
        },
        {
            "username": "u2",
            "client_identity": "c2",
            "prompt_name": "prompt_b",
            "question": "Question B",
            "model": "gpt-5-mini",
        },
    ])
    service, query_service, _profile_repo = _service()
    query_service.llm_query.side_effect = [
        {
            "valid_response": True,
            "answer": "Answer A",
            "query_id": 101,
            "stats": {"input_tokens": 11, "output_tokens": 7, "sql_retry_count": 1},
        },
        {
            "error": True,
            "valid_response": False,
            "error_message": "Bad answer",
            "query_id": 102,
        },
    ]
    output_path = service.run("acme", str(input_path))

    assert output_path == str(input_path).replace(".xlsx", "_results.xlsx")
    results = pd.read_excel(output_path, keep_default_na=False)
    assert list(results["status"]) == ["OK", "FAILED"]
    assert list(results["answer"]) == ["Answer A", ""]
    assert list(results["error_message"]) == ["", "Bad answer"]
    assert list(results["query_id"]) == [101, 102]
    assert list(results["in_tokens"]) == [11, 0]
    assert list(results["out_tokens"]) == [7, 0]
    assert list(results["retry"]) == [1, 0]
    query_service.llm_init_context.assert_any_call("acme", external_user_id="u1", model="gpt-5")
    query_service.llm_query.assert_any_call(
        company_short_name="acme",
        prompt_name="prompt_a",
        question="Question A",
        external_user_id="u1",
        client_data={"client_identity": "c1"},
    )


def test_run_rejects_non_xlsx_files():
    service, _query_service, _profile_repo = _service()

    with pytest.raises(IAToolkitException) as exc_info:
        service.run("acme", "bench.csv")

    assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER


def test_run_rejects_missing_file(tmp_path):
    service, _query_service, _profile_repo = _service()

    with pytest.raises(IAToolkitException) as exc_info:
        service.run("acme", str(tmp_path / "missing.xlsx"))

    assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_NAME


def test_run_rejects_workbook_missing_required_columns(tmp_path):
    input_path = tmp_path / "bench.xlsx"
    pd.DataFrame([{"username": "u1"}]).to_excel(input_path, index=False)
    service, _query_service, _profile_repo = _service()

    with pytest.raises(IAToolkitException) as exc_info:
        service.run("acme", str(input_path))

    assert exc_info.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
    assert "La planilla debe contener las columnas" in str(exc_info.value)


def test_run_rejects_unknown_company(tmp_path):
    input_path = tmp_path / "bench.xlsx"
    _write_benchmark(input_path, [{
        "username": "u1",
        "client_identity": "c1",
        "prompt_name": "prompt",
        "question": "Question",
        "model": "gpt-5",
    }])
    service, _query_service, profile_repo = _service(company=None)
    profile_repo.get_company_by_short_name.return_value = None

    with pytest.raises(IAToolkitException) as exc_info:
        service.run("acme", str(input_path))

    assert exc_info.value.error_type == IAToolkitException.ErrorType.CONFIG_ERROR
