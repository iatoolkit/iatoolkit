# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.operator_identity_service import OperatorIdentityService


def _service(company_exists=True, raises=False):
    repo = MagicMock()
    if raises:
        repo.get_company_by_short_name.side_effect = RuntimeError("database is down")
    else:
        repo.get_company_by_short_name.return_value = MagicMock() if company_exists else None
    return OperatorIdentityService(profile_repo=repo), repo


class TestWhichCompanyOperatesThisDeployment:
    """The question four places used to answer with the same typed string."""

    def test_the_setting_wins(self):
        service, repo = _service()

        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x"}, clear=True):
            assert service.company_short_name() == "integrador_x"

        # No lookup needed when the deployment says who it is.
        repo.get_company_by_short_name.assert_not_called()

    def test_the_setting_is_normalized(self):
        service, _ = _service()

        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "  Integrador_X  "}, clear=True):
            assert service.company_short_name() == "integrador_x"

    def test_without_the_setting_the_legacy_name_is_used_when_it_exists(self):
        # This platform configures nothing and keeps working.
        service, repo = _service(company_exists=True)

        with patch.dict(os.environ, {}, clear=True):
            assert service.company_short_name() == "iat_store"
        repo.get_company_by_short_name.assert_called_once_with("iat_store")

    def test_a_deployment_without_that_company_fails_and_says_what_to_set(self):
        """The failure this replaces was silent.

        The name travelled down to the payment configuration of a company that was
        not there, the collection raised, and the monthly close marked every
        invoice `failed` — which reads as a customer payment problem.
        """
        service, _ = _service(company_exists=False)

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(IAToolkitException) as exc:
                service.company_short_name()

        assert "IAT_OPERATOR_COMPANY" in str(exc.value)

    def test_an_unreadable_database_is_not_read_as_absent_silently(self):
        service, _ = _service(raises=True)

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(IAToolkitException):
                service.company_short_name()

    def test_the_answer_is_resolved_once(self):
        # Read per request and per invoice; it cannot change without a deployment.
        service, repo = _service(company_exists=True)

        with patch.dict(os.environ, {}, clear=True):
            first = service.company_short_name()
            second = service.company_short_name()

        assert first == second
        assert repo.get_company_by_short_name.call_count == 1


class TestTheNameCallersReadWithoutADatabase:
    """Auth paths and a webhook need the name and have no repository at hand."""

    def test_the_new_setting_wins(self):
        with patch.dict(os.environ, {"IAT_OPERATOR_COMPANY": "integrador_x",
                                     "IAT_BILLING_COMPANY_SHORT_NAME": "otra"}, clear=True):
            assert OperatorIdentityService.stated_name() == "integrador_x"

    def test_the_setting_that_predates_this_service_is_still_honoured(self):
        # The Stripe webhook already read it; a deployment that set it keeps
        # working without being asked for a second variable for the same fact.
        with patch.dict(os.environ, {"IAT_BILLING_COMPANY_SHORT_NAME": "integrador_x"}, clear=True):
            assert OperatorIdentityService.stated_name() == "integrador_x"

    def test_with_nothing_set_it_falls_back_to_the_legacy_name(self):
        with patch.dict(os.environ, {}, clear=True):
            assert OperatorIdentityService.stated_name() == "iat_store"


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
