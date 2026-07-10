# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
from unittest.mock import MagicMock, patch

from iatoolkit.services.attachment_policy_service import AttachmentPolicyService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.util import Utility


class TestAttachmentPolicyService:
    def setup_method(self):
        self.config_service = MagicMock(spec=ConfigurationService)
        self.config_service.get_configuration.return_value = {}

        self.util = MagicMock(spec=Utility)
        self.util.load_schema_from_yaml.return_value = {
            "openai": {
                "supports_native_files": True,
                "supports_native_images": True,
                "supported_mime_types": ["application/pdf", "text/csv", "text/plain"],
                "preferred_native_mime_types": ["application/pdf"],
                "max_file_size_mb": 20,
                "max_files_per_request": 10,
            },
            "unknown": {
                "supports_native_files": False,
                "supports_native_images": False,
                "supported_mime_types": [],
                "preferred_native_mime_types": [],
                "max_file_size_mb": 0,
                "max_files_per_request": 0,
            },
        }
        self.util.normalize_base64_payload.side_effect = lambda content: base64.b64decode(
            content.split(",", 1)[1] if isinstance(content, str) and content.startswith("data:") else content
        )
        self.config_service.get_llm_provider_config.return_value = {
            "base_url": "https://openrouter.ai/api/v1",
        }

        self.service = AttachmentPolicyService(
            configuration_service=self.config_service,
            util=self.util,
        )

    def test_extracted_only_routes_all_non_images_to_context(self):
        plan = self.service.build_attachment_plan(
            company_short_name="acme",
            provider="openai",
            files=[{"filename": "sales.csv", "base64": "U0FNUExF"}],
            policy={"attachment_mode": "extracted_only", "attachment_fallback": "extract"},
        )

        assert len(plan["files_for_context"]) == 1
        assert plan["native_attachments"] == []
        assert plan["errors"] == []

    def test_native_only_routes_supported_files_as_native(self):
        plan = self.service.build_attachment_plan(
            company_short_name="acme",
            provider="openai",
            files=[{"filename": "report.pdf", "base64": "U0FNUExF"}],
            policy={"attachment_mode": "native_only", "attachment_fallback": "fail"},
        )

        assert plan["errors"] == []
        assert plan["files_for_context"] == []
        assert len(plan["native_attachments"]) == 1
        assert plan["native_attachments"][0]["mime_type"] == "application/pdf"
        assert plan["stats"]["native_sent_count"] == 1

    def test_native_only_fails_when_provider_does_not_support_native(self):
        plan = self.service.build_attachment_plan(
            company_short_name="acme",
            provider="unknown",
            files=[{"filename": "report.pdf", "base64": "U0FNUExF"}],
            policy={"attachment_mode": "native_only", "attachment_fallback": "fail"},
        )

        assert len(plan["errors"]) == 1
        assert "cannot be sent as native file" in plan["errors"][0]
        assert plan["native_attachments"] == []
        assert plan["files_for_context"] == []

    def test_extracted_only_routes_images_to_text_extraction_when_provider_cannot_accept_images(self):
        plan = self.service.build_attachment_plan(
            company_short_name="acme",
            provider="unknown",
            files=[{"filename": "photo.png", "base64": "U0FNUExF"}],
            policy={"attachment_mode": "extracted_only", "attachment_fallback": "extract"},
        )

        assert plan["errors"] == []
        assert len(plan["files_for_context"]) == 1
        assert plan["files_for_context"][0]["force_text_extraction"] is True
        assert plan["stats"]["extract_candidates"] == 1

    def test_native_only_fails_when_provider_cannot_accept_images(self):
        plan = self.service.build_attachment_plan(
            company_short_name="acme",
            provider="unknown",
            files=[{"filename": "photo.png", "base64": "U0FNUExF"}],
            policy={"attachment_mode": "native_only", "attachment_fallback": "fail"},
        )

        assert len(plan["errors"]) == 1
        assert "cannot be sent as native image" in plan["errors"][0]
        assert plan["files_for_context"] == []

    def test_openrouter_native_image_validation_returns_clear_error_when_model_is_text_only(self):
        self.util.load_schema_from_yaml.return_value["openrouter"] = {
            "supports_native_files": True,
            "supports_native_images": True,
            "supported_mime_types": ["application/pdf", "text/csv", "text/plain"],
            "preferred_native_mime_types": ["application/pdf"],
            "max_file_size_mb": 20,
            "max_files_per_request": 10,
        }
        self.service._default_capabilities = None

        with patch.object(
            self.service,
            "_get_openrouter_native_image_error",
            return_value=(
                "El modelo de OpenRouter 'deepseek/deepseek-v4-pro' no publica 'image' en "
                "'input_modalities' (publica: text), por lo que no puede recibir imagenes nativas."
            ),
        ):
            plan = self.service.build_attachment_plan(
                company_short_name="acme",
                provider="openrouter",
                files=[{"filename": "photo.png", "base64": "U0FNUExF"}],
                policy={"attachment_mode": "native_only", "attachment_fallback": "fail"},
                model="deepseek/deepseek-v4-pro",
            )

        assert len(plan["errors"]) == 1
        assert "no publica 'image' en 'input_modalities'" in plan["errors"][0]
        assert plan["files_for_context"] == []

    def test_get_openrouter_native_image_error_accepts_models_that_publish_image_input(self):
        with patch("iatoolkit.services.attachment_policy_service.requests.get") as mock_get:
            response = MagicMock()
            response.json.return_value = {
                "data": [
                    {
                        "id": "openai/gpt-5.2",
                        "architecture": {"input_modalities": ["text", "image", "file"]},
                    }
                ]
            }
            response.raise_for_status.return_value = None
            mock_get.return_value = response

            error = self.service._get_openrouter_native_image_error("acme", "openai/gpt-5.2")

        assert error is None

    def test_get_openrouter_native_image_error_reports_text_only_catalog_entry(self):
        with patch("iatoolkit.services.attachment_policy_service.requests.get") as mock_get:
            response = MagicMock()
            response.json.return_value = {
                "data": [
                    {
                        "id": "deepseek/deepseek-v4-pro",
                        "architecture": {"input_modalities": ["text"]},
                    }
                ]
            }
            response.raise_for_status.return_value = None
            mock_get.return_value = response

            error = self.service._get_openrouter_native_image_error("acme", "deepseek-v4-pro")

        assert error is not None
        assert "deepseek/deepseek-v4-pro" in error
        assert "input_modalities" in error
        assert "text" in error

    def test_native_plus_extracted_keeps_context_when_native_is_not_supported(self):
        plan = self.service.build_attachment_plan(
            company_short_name="acme",
            provider="unknown",
            files=[{"filename": "report.pdf", "base64": "U0FNUExF"}],
            policy={"attachment_mode": "native_plus_extracted", "attachment_fallback": "fail"},
        )

        assert plan["errors"] == []
        assert len(plan["files_for_context"]) == 1
        assert plan["native_attachments"] == []
        assert plan["stats"]["extract_candidates"] == 1

    def test_get_company_default_policy_uses_llm_defaults(self):
        self.config_service.get_configuration.return_value = {
            "default_attachment_mode": "native_only",
            "default_attachment_fallback": "fail",
        }

        policy = self.service.get_company_default_policy("acme")
        assert policy == {
            "attachment_mode": "native_only",
            "attachment_fallback": "fail",
        }
