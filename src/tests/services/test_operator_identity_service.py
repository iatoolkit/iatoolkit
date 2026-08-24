# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.operator_identity_service import OperatorIdentityService


@pytest.fixture(autouse=True)
def _forget_the_resolved_name():
    """The answer is cached for the whole process, deliberately: it is read on
    every request and on every invoice, and it cannot change without a deploy.
    Which means a test that resolves it would otherwise decide it for the next."""
    OperatorIdentityService.reset_cache()
    yield
    OperatorIdentityService.reset_cache()


def _service():
    return OperatorIdentityService()


class TestWhichCompanyOperatesThisDeployment:
    """Identity: where the operator's own accounts live, which company you must be
    signed into to reach the console, which one the portfolio leaves out."""

    def test_the_setting_answers_it(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            assert _service().company_short_name() == "integrador_x"

    def test_the_setting_is_normalized(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "  Integrador_X  "}, clear=True):
            assert _service().company_short_name() == "integrador_x"

    def test_a_deployment_that_says_nothing_fails_and_names_the_setting(self):
        """No fallback, on purpose. The name of another deployment travelling into
        this one is what made a monthly close resolve the payment configuration of
        a company that was not there and mark every invoice `failed` — which reads
        as a customer payment problem."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(IAToolkitException) as exc:
                _service().company_short_name()

        assert "IAT_OPERATOR_COMPANY" in str(exc.value)

    def test_the_collector_setting_does_not_answer_identity(self):
        """They were synonyms, and that is what hid the second question. Naming a
        merchant account says nothing about who operates the deployment."""
        with patch.dict(os.environ, {"IAT_BILLING_COMPANY_SHORT_NAME": "integrador_x"}, clear=True):
            with pytest.raises(IAToolkitException):
                _service().company_short_name()

    def test_the_answer_is_resolved_once(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            assert _service().company_short_name() == _service().company_short_name()


class TestWhichCompanyCollects:
    """Money: whose merchant account charges a card, whose bank details sign a
    transfer notice, whose Stripe configuration holds the webhook secret."""

    def test_it_defaults_to_the_operator(self):
        # The common case: one company runs the deployment and invoices from it.
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            assert _service().billing_company_short_name() == "integrador_x"

    def test_it_can_name_a_different_entity(self):
        """The company that runs the deployment and the one that issues the
        invoices can be in different countries."""
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x",
                                     "IAT_BILLING_COMPANY_SHORT_NAME": "integrador_x_spa"}, clear=True):
            assert _service().billing_company_short_name() == "integrador_x_spa"

    def test_collecting_without_an_operator_is_still_possible(self):
        """A deployment can collect for an entity that is not the one operating
        it, and nothing about identity is needed to charge a card."""
        with patch.dict(os.environ, {"IAT_BILLING_COMPANY_SHORT_NAME": "integrador_x_spa"}, clear=True):
            assert _service().billing_company_short_name() == "integrador_x_spa"

    def test_with_nothing_set_the_error_is_about_collecting(self):
        """Pointing at the identity setting here sends somebody to configure who
        operates the deployment for what is a payment problem."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(IAToolkitException) as exc:
                _service().billing_company_short_name()

        assert "IAT_BILLING_COMPANY_SHORT_NAME" in str(exc.value)


class TestTheNameCallersReadWithoutADatabase:
    """Auth paths and a webhook need the name and have no repository at hand."""

    def test_identity_reads_the_operator_setting(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x",
                                     "IAT_BILLING_COMPANY_SHORT_NAME": "otra"}, clear=True):
            assert OperatorIdentityService.stated_name() == "integrador_x"

    def test_the_collector_reads_its_own_and_falls_back(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            assert OperatorIdentityService.stated_billing_name() == "integrador_x"
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x",
                                     "IAT_BILLING_COMPANY_SHORT_NAME": "otra"}, clear=True):
            assert OperatorIdentityService.stated_billing_name() == "otra"

    def test_with_nothing_set_it_is_empty_rather_than_a_guess(self):
        """Empty fails in the open: a company that does not exist authenticates
        nobody and holds no payment configuration."""
        with patch.dict(os.environ, {}, clear=True):
            assert OperatorIdentityService.stated_name() == ""
            assert OperatorIdentityService.stated_billing_name() == ""


class TestTheNameIsNotTypedAnywhereElse:
    """It used to be typed in nine places across three repositories, including the
    one that decides whose merchant account collects an invoice."""

    def test_only_the_resolver_spells_it(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[3]
        repos = [raiz / "src" / "iatoolkit",
                 raiz.parent / "iatoolkit-enterprise" / "src" / "iat_enterprise",
                 raiz.parent / "iatoolkit-website" / "src" / "website"]

        culpables = []
        for repo in repos:
            if not repo.exists():
                continue
            for archivo in repo.rglob("*.py"):
                if "__pycache__" in str(archivo):
                    continue
                for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
                    if '"iat_store"' not in linea or linea.lstrip().startswith(("#", "*", "'", '"')):
                        continue
                    # The two files that are the mechanism, and one column
                    # default that stores the name as data on each lead row.
                    if archivo.name in ("operator_identity_service.py",
                                        "operator_identity.py",
                                        "models.py"):
                        continue
                    culpables.append(f"{archivo.name}:{numero}")

        assert not culpables, f"the operator's name is typed again in: {culpables}"


class TestItIsResolvedOncePerProcessNotPerCaller:
    """Three identical "Operator company:" lines appeared in one boot.

    The cache lived on the instance, and the callers with a repository at hand
    build their own instance rather than asking the injector — so the answer was
    resolved, logged, and (without the setting) queried from the database once per
    request.
    """

    def test_a_second_instance_reuses_the_first_answer(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            assert _service().company_short_name() == "integrador_x"
            assert _service().company_short_name() == "integrador_x"

    def test_it_is_logged_once(self, caplog):
        import logging as _logging

        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            with caplog.at_level(_logging.INFO):
                for _ in range(3):
                    _service().company_short_name()

        lines = [r for r in caplog.records if "Operator company" in r.getMessage()]
        assert len(lines) == 1, f"logged {len(lines)} times"
