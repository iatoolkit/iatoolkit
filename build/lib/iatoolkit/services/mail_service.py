# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.storage_service import StorageService
from iatoolkit.common.interfaces.secret_provider import SecretProvider
from iatoolkit.common.secret_resolver import resolve_secret
from iatoolkit.infra.brevo_mail_app import BrevoMailApp
from injector import inject
import base64
import smtplib
from email.message import EmailMessage
from iatoolkit.common.exceptions import IAToolkitException

class MailService:
    @inject
    def __init__(self,
                 config_service: ConfigurationService,
                 mail_app: BrevoMailApp,
                 i18n_service: I18nService,
                 brevo_mail_app: BrevoMailApp,
                 storage_service: StorageService,
                 secret_provider: SecretProvider):
        self.mail_app = mail_app
        self.config_service = config_service
        self.i18n_service = i18n_service
        self.brevo_mail_app = brevo_mail_app
        self.storage_service = storage_service
        self.secret_provider = secret_provider


    def send_mail(self, company_short_name: str, **kwargs):
        recipient = kwargs.get('recipient')
        subject = kwargs.get('subject')
        body = kwargs.get('body')
        attachments = kwargs.get('attachments')

        # Normalizar a payload de BrevoMailApp (name + base64 content)
        norm_attachments = []
        for a in attachments or []:
            if a.get("attachment_token"):
                raw = self._read_token_bytes(company_short_name, a["attachment_token"])
                norm_attachments.append({
                    "filename": a["filename"],
                    "content": base64.b64encode(raw).decode("utf-8"),
                })
            else:
                # asumo que ya viene un base64
                norm_attachments.append({
                    "filename": a["filename"],
                    "content": a["content"]
                })

        # build provider configuration from company.yaml
        provider, provider_config = self._build_provider_config(company_short_name)

        # define the email sender
        sender = {
            "email": provider_config.get("sender_email"),
            "name": provider_config.get("sender_name"),
        }

        # select provider and send the email through it
        if provider == "brevo_mail":
            response = self.brevo_mail_app.send_email(
                provider_config=provider_config,
                sender=sender,
                to=recipient,
                subject=subject,
                body=body,
                attachments=norm_attachments
            )
        elif provider == "smtplib":
            response = self._send_with_smtplib(
                provider_config=provider_config,
                sender=sender,
                recipient=recipient,
                subject=subject,
                body=body,
                attachments=norm_attachments,
            )
            response = None
        else:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MAIL_ERROR,
                f"Unknown mail provider '{provider}'"
            )

        return self.i18n_service.t('services.mail_sent')

    def _build_provider_config(self, company_short_name: str) -> tuple[str, dict]:
        """
        Determina el provider activo (brevo_mail / smtplib) y construye
        el diccionario de configuración a partir de las variables de entorno
        cuyos nombres están en company.yaml (mail_provider).
        """
        # get company mail configuration and provider
        mail_config = self.config_service.get_configuration(company_short_name, "mail_provider")
        provider = mail_config.get("provider", "brevo_mail")

        # get mail common parameteres
        sender_email = mail_config.get("sender_email")
        sender_name = mail_config.get("sender_name")

        # get parameters depending on provider
        if provider == "brevo_mail":
            brevo_cfg = mail_config.get("brevo_mail", {})
            api_key_ref = brevo_cfg.get("brevo_api_secret_ref") or brevo_cfg.get("brevo_api", "BREVO_API_KEY")
            return provider, {
                "api_key": resolve_secret(self.secret_provider, company_short_name, api_key_ref),
                "sender_name": sender_name,
                "sender_email": sender_email,
            }

        if provider == "smtplib":
            smtp_cfg = mail_config.get("smtplib", {})
            host_ref = smtp_cfg.get("host_secret_ref") or smtp_cfg.get("host_env", "SMTP_HOST")
            port_ref = smtp_cfg.get("port_secret_ref") or smtp_cfg.get("port_env", "SMTP_PORT")
            username_ref = smtp_cfg.get("username_secret_ref") or smtp_cfg.get("username_env", "SMTP_USERNAME")
            password_ref = smtp_cfg.get("password_secret_ref") or smtp_cfg.get("password_env", "SMTP_PASSWORD")
            use_tls_ref = smtp_cfg.get("use_tls_secret_ref") or smtp_cfg.get("use_tls_env", "SMTP_USE_TLS")
            use_ssl_ref = smtp_cfg.get("use_ssl_secret_ref") or smtp_cfg.get("use_ssl_env", "SMTP_USE_SSL")

            host = resolve_secret(self.secret_provider, company_short_name, host_ref)
            port = resolve_secret(self.secret_provider, company_short_name, port_ref)
            username = resolve_secret(self.secret_provider, company_short_name, username_ref)
            password = resolve_secret(self.secret_provider, company_short_name, password_ref)
            use_tls = resolve_secret(self.secret_provider, company_short_name, use_tls_ref)
            use_ssl = resolve_secret(self.secret_provider, company_short_name, use_ssl_ref)

            return provider, {
                "host": host,
                "port": int(port) if port is not None else None,
                "username": username,
                "password": password,
                "use_tls": str(use_tls).lower() == "true",
                "use_ssl": str(use_ssl).lower() == "true",
                "sender_name": sender_name,
                "sender_email": sender_email,
            }

        # Fallback simple si el provider no es reconocido
        raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                 f"missing mail provider in mail configuration for company '{company_short_name}'")

    def _send_with_smtplib(self,
                           provider_config: dict,
                           sender: dict,
                           recipient: str,
                           subject: str,
                           body: str,
                           attachments: list[dict] | None):
        """
        Envía correo usando smtplib, utilizando la configuración normalizada
        en provider_config.
        """
        host = provider_config.get("host")
        port = provider_config.get("port")
        username = provider_config.get("username")
        password = provider_config.get("password")
        use_tls = provider_config.get("use_tls")
        use_ssl = provider_config.get("use_ssl")

        if not host or not port:
            raise IAToolkitException(
                IAToolkitException.ErrorType.MAIL_ERROR,
                "smtplib configuration is incomplete (host/port missing)"
            )

        msg = EmailMessage()
        msg["From"] = f"{sender.get('name', '')} <{sender.get('email')}>"
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body, subtype="html")

        # Adjuntos: ya vienen como filename + base64 content
        for a in attachments or []:
            filename = a.get("filename")
            content_b64 = a.get("content")
            if not filename or not content_b64:
                continue
            try:
                raw = base64.b64decode(content_b64, validate=True)
            except Exception:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.MAIL_ERROR,
                    f"Invalid base64 for attachment '{filename}'"
                )
            msg.add_attachment(
                raw,
                maintype="application",
                subtype="octet-stream",
                filename=filename,
            )

        if use_ssl:
            with smtplib.SMTP_SSL(host, port) as server:
                if username and password:
                    server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                if use_tls:
                    server.starttls()
                if username and password:
                    server.login(username, password)
                server.send_message(msg)


    def _read_token_bytes(self, company_short_name: str, token: str) -> bytes:
        if not token:
            raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR, "attachment_token invalid")

        try:
            payload = self.storage_service.resolve_download_token(token)
            token_company = payload.get("company")
            storage_key = payload.get("storage_key")
            if token_company != company_short_name:
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR, "attachment_token company mismatch")
            return self.storage_service.get_document_content(company_short_name, storage_key)
        except IAToolkitException as e:
            if e.error_type == IAToolkitException.ErrorType.CALL_ERROR:
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR, "attachment_token invalid")
            raise
