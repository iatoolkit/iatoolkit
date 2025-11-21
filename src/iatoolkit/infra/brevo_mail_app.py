# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from iatoolkit.common.exceptions import IAToolkitException
import os
import base64
import logging

MAX_ATTACH_BYTES = int(os.getenv("BREVO_MAX_ATTACH_BYTES", str(5 * 1024 * 1024)))  # 5MB seguro


class BrevoMailApp:
    def _init_brevo(self, provider_config: dict, sender: dict = None):
        # config and init the brevo client
        self.configuration = sib_api_v3_sdk.Configuration()
        self.configuration.api_key['api-key'] = provider_config.get("api_key")
        self.mail_api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(self.configuration))


    @staticmethod
    def _strip_data_url_prefix(b64: str) -> str:
        if not isinstance(b64, str):
            return b64
        i = b64.find("base64,")
        return b64[i + 7:] if i != -1 else b64

    def _normalize_attachments(self, attachments: list[dict] | None):
        if not attachments:
            return None
        sdk_attachments = []
        for idx, a in enumerate(attachments, start=1):
            # 1) claves obligatorias
            if "filename" not in a:
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                   f"Adjunto #{idx} inválido: falta 'filename'")
            if "content" not in a:
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                   f"Adjunto '{a.get('filename', '(sin nombre)')}' inválido: falta 'content'")

            name = a["filename"]
            content_b64 = a["content"]

            # 2) quitar prefijo data URL si vino así
            content_b64 = self._strip_data_url_prefix(content_b64)

            # 3) validar base64 (y que no esté vacío)
            try:
                raw = base64.b64decode(content_b64, validate=True)
            except Exception:
                logging.error("Adjunto '%s' con base64 inválido (primeros 16 chars: %r)",
                              name, str(content_b64)[:16])
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                   f"Adjunto '{name}' trae base64 inválido")

            if not raw:
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                   f"Adjunto '{name}' está vacío")

            # 4) volver a base64 limpio (sin prefijos, sin espacios)
            clean_b64 = base64.b64encode(raw).decode("utf-8")

            # 5) construir objeto del SDK
            sdk_attachments.append(
                sib_api_v3_sdk.SendSmtpEmailAttachment(
                    name=name,
                    content=clean_b64
                )
            )
            return sdk_attachments


    def send_email(self,
                   provider_config: dict,
                   to: str,
                   subject: str,
                   body: str,
                   sender: dict,
                   attachments: list[dict] = None):

        if not provider_config.get("api_key"):
            logging.error(f'Try to send brevo_mail without api_key in provider_config')
            raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                     f"Invalid mail configuration for Brevo: missing api-key")

        # init the Brevo client
        self._init_brevo(provider_config)

        try:
            sdk_attachments = self._normalize_attachments(attachments)
            email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": to}],
                sender=sender,
                subject=subject,
                html_content=body,
                attachment=sdk_attachments
            )
            api_response = self.mail_api.send_transac_email(email)

            # Validación de respuesta
            message_id = getattr(api_response, "message_id", None) or getattr(api_response, "messageId", None)
            message_ids = getattr(api_response, "message_ids", None) or getattr(api_response, "messageIds", None)
            if not ((isinstance(message_id, str) and message_id.strip()) or
                    (isinstance(message_ids, (list, tuple)) and len(message_ids) > 0)):
                logging.error("MAIL ERROR: Respuesta sin message_id(s): %r", api_response)
                raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                                   "Brevo no retornó message_id; el envío podría haber fallado.")

            return api_response

        except ApiException as e:
            logging.exception("MAIL ERROR (ApiException): status=%s reason=%s body=%s",
                              getattr(e, "status", None), getattr(e, "reason", None), getattr(e, "body", None))
            raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                               f"Error Brevo (status={getattr(e, 'status', 'N/A')}): {getattr(e, 'reason', str(e))}") from e
        except Exception as e:
            logging.exception("MAIL ERROR: %s", str(e))
            raise IAToolkitException(IAToolkitException.ErrorType.MAIL_ERROR,
                               f"No se pudo enviar correo: {str(e)}") from e

