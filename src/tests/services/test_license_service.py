import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.license_service import LicenseService


class TestLicenseService:
    def test_defaults_to_community_limits(self):
        service = LicenseService()

        assert service.get_license_type() == "Community Edition"
        assert service.get_plan_name() == "Open Source (Community Edition)"
        assert service.get_max_companies() == 1
        assert service.get_license_info() == "Plan: Open Source (Community Edition), Companies: 1"

    def test_feature_flags_default_to_disabled(self):
        service = LicenseService()

        assert service.has_feature("multi_tenant") is False
        assert service.has_feature("rag_advanced") is False
        assert service.has_feature("missing") is False

    def test_validate_company_limit_allows_current_count_within_limit(self):
        service = LicenseService()

        service.validate_company_limit(1)

    def test_validate_company_limit_raises_when_limit_is_exceeded(self):
        service = LicenseService()

        with pytest.raises(IAToolkitException) as exc_info:
            service.validate_company_limit(2)

        assert exc_info.value.error_type == IAToolkitException.ErrorType.PERMISSION
        assert "Company limit (1) reached" in str(exc_info.value)

    def test_validate_company_limit_allows_unlimited_plan(self):
        service = LicenseService()
        service.limits["max_companies"] = -1

        service.validate_company_limit(999)

    def test_getters_use_fallbacks_when_limit_payload_is_sparse(self):
        service = LicenseService()
        service.limits = {}

        assert service.get_license_type() == "Community Edition"
        assert service.get_plan_name() == "Unknown"
        assert service.get_max_companies() == 1
        assert service.has_feature("anything") is False
