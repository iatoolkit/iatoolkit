# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
"""The execution path honours a suspended runtime, and fails open otherwise."""

from unittest.mock import MagicMock

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.llm_client_service import llmClient


def _company(parameters):
    company = MagicMock()
    company.parameters = parameters
    return company


class TestRuntimeGuardOnExecution:
    def test_a_suspended_company_cannot_execute(self):
        with pytest.raises(IAToolkitException) as raised:
            llmClient._assert_runtime_not_suspended(
                _company({"runtime_guard": {"suspended": True, "state": "suspended"}})
            )

        assert "spend limit" in str(raised.value)

    def test_a_company_under_its_limit_executes(self):
        llmClient._assert_runtime_not_suspended(
            _company({"runtime_guard": {"suspended": False, "state": "notify"}})
        )

    def test_a_company_without_a_guard_executes(self):
        llmClient._assert_runtime_not_suspended(_company({}))
        llmClient._assert_runtime_not_suspended(_company(None))

    def test_an_unreadable_guard_fails_open(self):
        """A billing lookup problem must never take a customer's operation down."""
        broken = MagicMock()
        type(broken).parameters = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

        llmClient._assert_runtime_not_suspended(broken)

    def test_a_malformed_guard_fails_open(self):
        llmClient._assert_runtime_not_suspended(_company({"runtime_guard": "nonsense"}))
