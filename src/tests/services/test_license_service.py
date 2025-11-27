# tests/services/test_license_service.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

import pytest
from unittest.mock import patch, mock_open, MagicMock
import jwt
import time
from iatoolkit.services.license_service import LicenseService
from iatoolkit.common.exceptions import IAToolkitException
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


# --- Helper to generate EC keys for testing (since we use ES256) ---
def generate_test_keys():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    pem_public = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    return pem_private, pem_public


TEST_PRIVATE_KEY, TEST_PUBLIC_KEY = generate_test_keys()


class TestLicenseService:

    @pytest.fixture
    def mock_public_key_file(self):
        """Mock the reading of public_key.pem to return our test key."""
        with patch("pathlib.Path.exists", return_value=True), \
                patch("pathlib.Path.read_text", return_value=TEST_PUBLIC_KEY.decode('utf-8')):
            yield

    def create_token(self, payload, expired=False):
        """Helper to create a signed JWT token."""
        if expired:
            payload['exp'] = time.time() - 3600  # Expired 1 hour ago
        else:
            payload['exp'] = time.time() + 3600  # Valid for 1 hour

        return jwt.encode(payload, TEST_PRIVATE_KEY, algorithm="ES256")

    def test_init_no_license_env_var(self, mock_public_key_file):
        """
        GIVEN no IAT_LICENSE_KEY env var
        WHEN initializing LicenseService
        THEN it should load default Community limits
        """
        with patch.dict("os.environ", {}, clear=True):
            service = LicenseService()

            assert service.get_plan_name() == "Open Source (Community Edition)"
            assert service.get_max_companies() == 1
            assert service.get_max_tools_per_company() == 3
            assert service.has_feature("multi_tenant") is False

    def test_init_valid_enterprise_license(self, mock_public_key_file):
        """
        GIVEN a valid signed JWT in env var
        WHEN initializing LicenseService
        THEN it should load limits from the token
        """
        payload = {
            "client_name": "Test Corp",
            "plan": "Enterprise Gold",
            "max_companies": 10,
            "max_tools": 50,
            "features": {"multi_tenant": True}
        }
        token = self.create_token(payload)

        with patch.dict("os.environ", {"IAT_LICENSE_KEY": token}):
            service = LicenseService()

            assert service.get_plan_name() == "Enterprise Gold"
            assert service.get_max_companies() == 10
            assert service.get_max_tools_per_company() == 50
            assert service.has_feature("multi_tenant") is True

    def test_init_expired_license(self, mock_public_key_file):
        """
        GIVEN an expired license token
        WHEN initializing LicenseService
        THEN it should fallback to Community limits and log warning
        """
        payload = {"plan": "Enterprise", "max_companies": 100}
        token = self.create_token(payload, expired=True)

        with patch.dict("os.environ", {"IAT_LICENSE_KEY": token}):
            service = LicenseService()

            # Should revert to defaults
            assert service.get_plan_name() == "Open Source (Community Edition)"
            assert service.get_max_companies() == 1  # Default, not 100

    def test_init_invalid_signature(self, mock_public_key_file):
        """
        GIVEN a token signed with a WRONG private key
        WHEN initializing LicenseService
        THEN it should fallback to Community limits (invalid signature)
        """
        # Generate a DIFFERENT key pair for signing
        wrong_priv, _ = generate_test_keys()
        payload = {"plan": "Fake Enterprise", "max_companies": 999}
        # Sign with wrong key
        token = jwt.encode(payload, wrong_priv, algorithm="ES256")

        with patch.dict("os.environ", {"IAT_LICENSE_KEY": token}):
            service = LicenseService()

            assert service.get_plan_name() == "Open Source (Community Edition)"
            assert service.get_max_companies() == 1

    def test_public_key_file_missing(self):
        """
        GIVEN the public_key.pem file is missing
        WHEN initializing LicenseService
        THEN it should log error and use Community limits (safe fallback)
        """
        with patch("pathlib.Path.exists", return_value=False):
            # Set a token that would be valid if key was present
            with patch.dict("os.environ", {"IAT_LICENSE_KEY": "some.token"}):
                service = LicenseService()

                # Since key is None, validation fails/skips to default
                assert service.public_key is None
                assert service.get_plan_name() == "Open Source (Community Edition)"

    # --- Validation Logic Tests ---

    def test_validate_company_limit_exceeded(self, mock_public_key_file):
        """
        GIVEN current count exceeds max companies
        WHEN validate_company_limit is called
        THEN it raises IAToolkitException
        """
        # Default limit is 1
        with patch.dict("os.environ", {}, clear=True):
            service = LicenseService()

            # Count 0 -> OK
            service.validate_company_limit(0)

            # Count 1 -> Fail (limit is inclusive in logic '>=')
            # wait, logic is: if limit != -1 and current_count > limit:
            # In code provided: if limit != -1 and current_count > limit:
            # If limit is 1, count 1 is OK (1 > 1 is False). Count 2 is Fail.

            # Re-checking logic provided in prompt:
            # "if limit != -1 and current_count > limit:"
            # So for limit=1, 1 company is allowed. 2 is not.

            service.validate_company_limit(1)  # Should pass

            with pytest.raises(IAToolkitException) as exc:
                service.validate_company_limit(2)
            assert exc.value.error_type == IAToolkitException.ErrorType.PERMISSION
            assert "Company limit" in str(exc.value)

    def test_validate_company_limit_unlimited(self, mock_public_key_file):
        """
        GIVEN an enterprise license with unlimited companies (-1)
        WHEN validate_company_limit is called with high number
        THEN it passes
        """
        payload = {"max_companies": -1, "max_tools": -1}
        token = self.create_token(payload)

        with patch.dict("os.environ", {"IAT_LICENSE_KEY": token}):
            service = LicenseService()
            # Validar un numero alto
            service.validate_company_limit(1000)  # Should not raise

    def test_validate_tool_config_limit(self, mock_public_key_file):
        """
        GIVEN a config list longer than limit
        WHEN validate_tool_config_limit is called
        THEN it raises exception
        """
        # Default limit is 3
        with patch.dict("os.environ", {}, clear=True):
            service = LicenseService()

            # Config with 4 tools
            tools = [{}, {}, {}, {}]

            with pytest.raises(IAToolkitException) as exc:
                service.validate_tool_config_limit(tools)
            assert "Configuration defines 4 tools" in str(exc.value)

    def test_get_license_info(self, mock_public_key_file):
        """Test string representation of license info"""
        with patch.dict("os.environ", {}, clear=True):
            service = LicenseService()
            info = service.get_license_info()
            assert "Plan: Open Source" in info
            assert "Companies: 1" in info
            assert "Tools: 3" in info