# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.mail_service import MailService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.infra.brevo_mail_app import BrevoMailApp
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.interfaces.secret_provider import SecretProvider


class TestMailService:

    def setup_method(self):
        # Mocks de dependencias
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_brevo_mail_app = MagicMock(spec=BrevoMailApp)
        self.mock_i18n_service = MagicMock(spec=I18nService)
        self.mock_storage_service = MagicMock(spec=StorageService)
        self.mock_secret_provider = MagicMock(spec=SecretProvider)
        self.mock_secret_provider.get_secret.side_effect = (
            lambda _company, key_name, default=None: os.getenv(
                key_name,
                {
                    "BREVO_API_KEY": "dummy_key",
                    "SMTP_HOST": "smtp.test.com",
                    "SMTP_PORT": "587",
                    "SMTP_USERNAME": "user",
                    "SMTP_PASSWORD": "pass",
                    "SMTP_USE_TLS": "true",
                    "SMTP_USE_SSL": "false",
                }.get(key_name, default),
            )
        )

        # Traducción mock
        self.mock_i18n_service.t.side_effect = lambda key, **kwargs: f"translated:{key}"

        # mail_app está en el __init__ de MailService pero no se usa en el código actual;
        # lo mockeamos igual para respetar la firma.
        self.mock_mail_app = MagicMock()

        # Instancia de MailService con dependencias mockeadas
        self.mail_service = MailService(
            config_service=self.mock_config_service,
            mail_app=self.mock_mail_app,
            i18n_service=self.mock_i18n_service,
            brevo_mail_app=self.mock_brevo_mail_app,
            storage_service=self.mock_storage_service,
            secret_provider=self.mock_secret_provider,
        )

        # Default behavior: invalid token
        self.mock_storage_service.resolve_download_token.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.CALL_ERROR,
            "Invalid download token."
        )

        # Datos comunes
        self.company_short_name = "test_company"
        self.recipient = "destinatario@test.com"
        self.subject = "Prueba"
        self.body = "<p>Contenido del mensaje</p>"

    # -----------------------
    # Helpers de configuración
    # -----------------------

    def _set_brevo_config(self):
        self.mock_config_service.get_configuration.return_value = {
            "provider": "brevo_mail",
            "sender_email": "ia@test.com",
            "sender_name": "Test IA",
            "brevo_mail": {
                "brevo_api": "BREVO_API_KEY"
            }
        }

    def _set_smtplib_config(self):
        self.mock_config_service.get_configuration.return_value = {
            "provider": "smtplib",
            "sender_email": "ia@test.com",
            "sender_name": "Test IA",
            "smtplib": {
                "host_env": "SMTP_HOST",
                "port_env": "SMTP_PORT",
                "username_env": "SMTP_USERNAME",
                "password_env": "SMTP_PASSWORD",
                "use_tls_env": "SMTP_USE_TLS",
                "use_ssl_env": "SMTP_USE_SSL",
            },
        }

    # -----------------------
    # Tests para Brevo
    # -----------------------

    def test_send_mail_brevo_success_without_attachments(self, monkeypatch):
        """Debe usar BrevoMailApp cuando provider=brevo_mail y retornar mensaje traducido."""
        self._set_brevo_config()

        # Evitar dependencias de entorno
        monkeypatch.setenv("BREVO_API_KEY", "dummy_key")

        result = self.mail_service.send_mail(
            company_short_name=self.company_short_name,
            recipient=self.recipient,
            subject=self.subject,
            body=self.body,
            attachments=[],
        )

        # Se debe haber llamado a BrevoMailApp con los parámetros correctos
        self.mock_brevo_mail_app.send_email.assert_called_once()
        call_args = self.mock_brevo_mail_app.send_email.call_args.kwargs

        assert call_args["to"] == self.recipient
        assert call_args["subject"] == self.subject
        assert call_args["body"] == self.body
        assert call_args["sender"]["email"] == 'ia@test.com'
        assert call_args["sender"]["name"] == 'Test IA'
        assert call_args["attachments"] == []

        assert result == "translated:services.mail_sent"

    def test_send_mail_brevo_with_attachment_token(self, monkeypatch):
        """Cuando hay attachment_token válido debe leerse desde storage y normalizar a base64."""
        self._set_brevo_config()
        monkeypatch.setenv("BREVO_API_KEY", "dummy_key")
        self.mock_storage_service.resolve_download_token.side_effect = None
        self.mock_storage_service.resolve_download_token.return_value = {
            "company": self.company_short_name,
            "storage_key": "companies/test_company/generated_downloads/1/test.txt"
        }
        content_bytes = b"hello world"
        self.mock_storage_service.get_document_content.return_value = content_bytes

        attachment = {
            "filename": "test.txt",
            "attachment_token": "signed-token",
        }

        result = self.mail_service.send_mail(
            company_short_name=self.company_short_name,
            recipient=self.recipient,
            subject=self.subject,
            body=self.body,
            attachments=[attachment],
        )

        self.mock_brevo_mail_app.send_email.assert_called_once()
        call_args = self.mock_brevo_mail_app.send_email.call_args.kwargs
        attachments_sent = call_args["attachments"]
        assert len(attachments_sent) == 1
        assert attachments_sent[0]["filename"] == "test.txt"

        decoded = base64.b64decode(attachments_sent[0]["content"])
        assert decoded == content_bytes

        assert result == "translated:services.mail_sent"

    # -----------------------
    # Tests para smtplib
    # -----------------------

    def test_send_mail_smtplib_success(self, monkeypatch):
        """Debe usar _send_with_smtplib cuando provider=smtplib."""
        self._set_smtplib_config()

        # Mock de variables de entorno usadas en _build_provider_config
        monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "user")
        monkeypatch.setenv("SMTP_PASSWORD", "pass")
        monkeypatch.setenv("SMTP_USE_TLS", "true")
        monkeypatch.setenv("SMTP_USE_SSL", "false")

        # Espiamos/Mockeamos el método interno _send_with_smtplib
        self.mail_service._send_with_smtplib = MagicMock()

        result = self.mail_service.send_mail(
            company_short_name=self.company_short_name,
            recipient=self.recipient,
            subject=self.subject,
            body=self.body,
            attachments=[],
        )

        # Debe haberse llamado el método interno para smtplib
        self.mail_service._send_with_smtplib.assert_called_once()
        call_args = self.mail_service._send_with_smtplib.call_args.kwargs

        assert call_args["recipient"] == self.recipient
        assert call_args["subject"] == self.subject
        assert call_args["body"] == self.body
        assert call_args["attachments"] == []
        assert call_args["sender"]["email"] == 'ia@test.com'
        assert call_args["sender"]["name"] == "Test IA"

        # provider_config debe tener host y port correctos
        provider_config = call_args["provider_config"]
        assert provider_config["host"] == "smtp.test.com"
        assert provider_config["port"] == 587
        assert provider_config["username"] == "user"
        assert provider_config["password"] == "pass"
        assert provider_config["use_tls"] is True
        assert provider_config["use_ssl"] is False

        assert result == "translated:services.mail_sent"

    def test_send_mail_smtplib_real_flow_uses_smtplib(self, monkeypatch):
        """
        Flujo completo smtplib: se ejecuta _send_with_smtplib y se verifica que
        smtplib.SMTP se use correctamente (mockeado).
        """
        self._set_smtplib_config()

        # Configuración de entorno para smtplib
        monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "user")
        monkeypatch.setenv("SMTP_PASSWORD", "pass")
        monkeypatch.setenv("SMTP_USE_TLS", "true")
        monkeypatch.setenv("SMTP_USE_SSL", "false")

        # Patch de smtplib.SMTP en el módulo de mail_service
        with patch("iatoolkit.services.mail_service.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_instance = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance

            result = self.mail_service.send_mail(
                company_short_name=self.company_short_name,
                recipient=self.recipient,
                subject=self.subject,
                body=self.body,
                attachments=[],
            )

        # Verifica que se llamó SMTP con host y port correctos
        mock_smtp_cls.assert_called_once_with("smtp.test.com", 587)
        # Verifica que se haya hecho starttls y login
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("user", "pass")
        mock_smtp_instance.send_message.assert_called_once()

        assert result == "translated:services.mail_sent"


    def test_send_mail_unknown_provider_raises(self):
        """Si el provider es desconocido, se debe lanzar un MAIL_ERROR."""
        self.mock_config_service.get_configuration.return_value = {
            "provider": "unknown_provider"
        }

        with pytest.raises(IAToolkitException) as exc:
            self.mail_service.send_mail(
                company_short_name=self.company_short_name,
                recipient=self.recipient,
                subject=self.subject,
                body=self.body,
                attachments=[],
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.MAIL_ERROR
        assert "missing mail provider" in str(exc.value)

    def test_send_mail_partial_args_defaults(self):
        """Si faltan subject/body se pasan como None pero igual se envía y retorna mensaje."""
        self._set_brevo_config()

        result = self.mail_service.send_mail(
            company_short_name=self.company_short_name,
            recipient=self.recipient,
            # Sin subject ni body
        )

        self.mock_brevo_mail_app.send_email.assert_called_once()
        call_args = self.mock_brevo_mail_app.send_email.call_args.kwargs
        assert call_args["subject"] is None
        assert call_args["body"] is None
        assert result == "translated:services.mail_sent"

    def test_send_mail_invalid_attachment_token_raises(self, monkeypatch):
        """attachment_token inválido debe levantar IAToolkitException de tipo MAIL_ERROR."""
        self._set_brevo_config()
        monkeypatch.setenv("BREVO_API_KEY", "dummy_key")

        attachment = {
            "filename": "test.txt",
            "attachment_token": "no_existe",
        }

        with pytest.raises(IAToolkitException) as exc:
            self.mail_service.send_mail(
                company_short_name=self.company_short_name,
                recipient=self.recipient,
                subject=self.subject,
                body=self.body,
                attachments=[attachment],
            )

        assert exc.value.error_type == IAToolkitException.ErrorType.MAIL_ERROR
        assert "attachment_token invalid" in str(exc.value)

    def test_send_mail_brevo_with_signed_attachment_token_from_storage(self, monkeypatch):
        self._set_brevo_config()
        monkeypatch.setenv("BREVO_API_KEY", "dummy_key")
        self.mock_storage_service.resolve_download_token.side_effect = None
        self.mock_storage_service.resolve_download_token.return_value = {
            "company": self.company_short_name,
            "storage_key": "companies/test_company/generated_downloads/1/test.xlsx"
        }
        self.mock_storage_service.get_document_content.return_value = b"signed-bytes"

        attachment = {
            "filename": "test.xlsx",
            "attachment_token": "signed-token",
        }

        result = self.mail_service.send_mail(
            company_short_name=self.company_short_name,
            recipient=self.recipient,
            subject=self.subject,
            body=self.body,
            attachments=[attachment],
        )

        self.mock_storage_service.resolve_download_token.assert_called_once_with("signed-token")
        self.mock_storage_service.get_document_content.assert_called_once_with(
            self.company_short_name,
            "companies/test_company/generated_downloads/1/test.xlsx"
        )
        self.mock_brevo_mail_app.send_email.assert_called_once()
        call_args = self.mock_brevo_mail_app.send_email.call_args.kwargs
        decoded = base64.b64decode(call_args["attachments"][0]["content"])
        assert decoded == b"signed-bytes"
        assert result == "translated:services.mail_sent"
