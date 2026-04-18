# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from typing import Any, Dict, List, Optional
from google.genai import types
from iatoolkit.common.exceptions import IAToolkitException
import logging
import json
import uuid
import mimetypes
import re
import base64


class GeminiAdapter:

    def __init__(self, gemini_client):
        self.client = gemini_client

        # Nueva estructura de safety settings para el SDK v2
        self.safety_settings = [
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_NONE"
            ),
        ]

    def create_response(self,
                        model: str,
                        input: List[Dict],
                        previous_response_id: Optional[str] = None,
                        context_history: Optional[List[Dict]] = None,
                        tools: Optional[List[Dict]] = None,
                        text: Optional[Dict] = None,
                        reasoning: Optional[Dict] = None,
                        tool_choice: str = "auto",
                        images: Optional[List[Dict]] = None,
                        attachments: Optional[List[Dict]] = None,
                        ) -> LLMResponse:
        try:

            # Separamos las instrucciones del sistema del resto del contenido
            system_instruction, filtered_input = self._extract_system_and_filter_input(
                (context_history or []) + input
            )

            # prepare tools and contents
            contents = self._prepare_gemini_contents(
                (context_history or []) + input,
                images=images,
                attachments=attachments,
            )

            config_kwargs = {
                "system_instruction": system_instruction,
                "safety_settings": self.safety_settings,
                "tools": self._prepare_gemini_tools(tools),
                "temperature": float(text.get("temperature", 0.7)) if text else 0.7,
                "max_output_tokens": int(text.get("max_tokens", 10000)) if text else 10000,
                "top_p": float(text.get("top_p", 0.95)) if text else 0.95,
                "candidate_count": 1,
                # "response_modalities": ['TEXT', 'IMAGE']
            }

            if isinstance(text, dict):
                response_schema = text.get("response_schema")
                if response_schema is not None:
                    config_kwargs["response_mime_type"] = str(
                        text.get("response_mime_type") or "application/json"
                    )
                    config_kwargs["response_schema"] = self._prepare_response_schema(response_schema)

            try:
                config = types.GenerateContentConfig(**config_kwargs)
            except TypeError as e:
                # Backward compatibility with older google-genai SDK versions.
                if "response_schema" in config_kwargs or "response_mime_type" in config_kwargs:
                    logging.warning(
                        "Gemini SDK doesn't support response_schema fields in GenerateContentConfig. "
                        "Falling back to prompt-instruction-only mode: %s",
                        e
                    )
                    config_kwargs.pop("response_schema", None)
                    config_kwargs.pop("response_mime_type", None)
                    config = types.GenerateContentConfig(**config_kwargs)
                else:
                    raise

            # call the new SDK
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
            self._log_structured_response_debug(response=response, used_response_schema="response_schema" in config_kwargs)
            self._raise_for_truncated_structured_output(response=response, used_response_schema="response_schema" in config_kwargs)
            # map the answer to a common structure
            llm_response = self._map_gemini_response(response, model)

            # add the model answer to the history
            if context_history and llm_response.output_text:
                context_history.append(
                    {
                        'role': 'assistant',
                        'context': llm_response.output_text
                    }
                )

            return llm_response

        except Exception as e:
            if isinstance(e, IAToolkitException):
                raise

            error_message = f"Error calling Gemini API: {str(e)}"
            logging.error(error_message)

            # handle gemini specific errors
            if "quota" in str(e).lower():
                error_message = "Se ha excedido la cuota de la API de Gemini"
            elif "blocked" in str(e).lower():
                error_message = "El contenido fue bloqueado por las políticas de seguridad de Gemini"
            elif "token" in str(e).lower():
                error_message = f"Tu consulta supera el límite de contexto de Gemini: {str(e)}"

            raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR, error_message)

    def _extract_system_and_filter_input(self, input_list: List[Dict]) -> tuple[Optional[str], List[Dict]]:
        """Extrae el mensaje de sistema para usarlo en system_instruction."""
        system_parts = []
        filtered_messages = []

        for msg in input_list:
            if msg.get("role") == "system":
                system_parts.append(msg.get("content", ""))
            else:
                filtered_messages.append(msg)

        system_str = "\n".join(system_parts) if system_parts else None
        return system_str, filtered_messages

    def _prepare_gemini_contents(
        self,
        input: List[Dict],
        images: Optional[List[Dict]] = None,
        attachments: Optional[List[Dict]] = None,
    ) -> List[types.Content]:
        gemini_contents = []

        # Encontrar el último mensaje de usuario para las imágenes
        last_user_idx = -1
        for i, m in enumerate(input):
            if m.get("role") == "user":
                last_user_idx = i

        for i, message in enumerate(input):
            # DETECCIÓN DE ROL CORREGIDA
            role = message.get("role")
            msg_type = message.get("type")

            parts = []

            # 1. Turno de Usuario
            if role == "user":
                content = message.get("content", "")
                if content:
                    parts.append(types.Part.from_text(text=content))

                if images and i == last_user_idx:
                    for img in images:
                        image_bytes = self._decode_base64_payload(img.get('base64', ''))
                        if not image_bytes:
                            continue
                        parts.append(types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mimetypes.guess_type(img.get('name', ''))[0] or 'image/jpeg'
                        ))
                if attachments and i == last_user_idx:
                    for attachment in attachments:
                        payload = attachment.get("base64") or attachment.get("content")
                        attachment_bytes = self._decode_base64_payload(payload)
                        if not attachment_bytes:
                            continue
                        filename = attachment.get("name") or attachment.get("filename") or "attachment"
                        mime_type = (
                            attachment.get("mime_type")
                            or attachment.get("type")
                            or mimetypes.guess_type(filename)[0]
                            or "application/octet-stream"
                        )
                        parts.append(types.Part.from_bytes(
                            data=attachment_bytes,
                            mime_type=mime_type
                        ))

            # 2. Turno del Modelo (Asistente)
            elif role == "assistant" or role == "model":
                role = "model" # Forzar nombre de rol para Gemini SDK

                # Reconstruir llamadas a herramientas si existen
                if "tool_calls" in message:
                    for tc in message["tool_calls"]:
                        args = tc["arguments"]
                        if isinstance(args, str):
                            args = json.loads(args)
                        parts.append(types.Part.from_function_call(name=tc["name"], args=args))

                content = message.get("context") or message.get("content", "")
                if content:
                    parts.append(types.Part.from_text(text=content))

            # 3. Turno de Herramienta (Respuesta)
            elif msg_type == "function_call_output" or role == "tool":
                role = "tool"
                func_name = message.get("call_id") or message.get("name")
                output_raw = message.get("output", "")

                try:
                    # Gemini prefiere objetos, no strings JSON
                    output_data = json.loads(output_raw) if isinstance(output_raw, str) else output_raw
                except:
                    output_data = {"result": output_raw}

                parts.append(types.Part.from_function_response(
                    name=func_name,
                    response=output_data if isinstance(output_data, dict) else {"result": output_data}
                ))

            if parts:
                gemini_contents.append(types.Content(role=role, parts=parts))

        return gemini_contents

    @staticmethod
    def _decode_base64_payload(payload: Any) -> bytes:
        if payload is None:
            return b""
        if isinstance(payload, bytes):
            return payload

        payload_str = str(payload).strip()
        if not payload_str:
            return b""
        if payload_str.lower().startswith("data:") and "," in payload_str:
            payload_str = payload_str.split(",", 1)[1]

        try:
            return base64.b64decode(payload_str)
        except Exception:
            logging.warning("GeminiAdapter: invalid base64 payload for attachment/image; skipping part.")
            return b""

    def _prepare_gemini_tools(self, tools: List[Dict]) -> Optional[List[types.Tool]]:
        """Prepara las herramientas en el formato correcto para el SDK google-genai."""
        if not tools:
            return None

        function_declarations = []
        for tool in tools:
            if tool.get("type") == "function":
                # Limpiamos parámetros para cumplir con el esquema estricto de Gemini
                clean_params = self._clean_openai_specific_fields(tool.get("parameters", {}))

                function_declarations.append(
                    types.FunctionDeclaration(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        parameters=clean_params
                    )
                )

        if function_declarations:
            # El constructor de Tool espera las declaraciones así
            return [types.Tool(function_declarations=function_declarations)]

        return None

    def _prepare_response_schema(self, schema: Any) -> Any:
        """Normalize OpenAI-style JSON schema into a Gemini-compatible schema subset."""
        if isinstance(schema, dict):
            return self._clean_openai_specific_fields(schema)
        if isinstance(schema, list):
            return [self._prepare_response_schema(item) for item in schema]
        return schema


    def _clean_openai_specific_fields(self, parameters: Dict) -> Dict:
        """Limpiar campos específicos de OpenAI que Gemini no entiende"""
        clean_params = {}

        # Campos permitidos por Gemini (SDK google-genai / Schema).
        allowed_fields = {
            "type",
            "properties",
            "required",
            "items",
            "description",
            "enum",
            "nullable",
            "anyOf",
            "oneOf",
            "pattern",
            "format",
            "minimum",
            "maximum",
            "minItems",
            "maxItems",
            "minLength",
            "maxLength",
        }

        for key, value in parameters.items():
            if key in allowed_fields:
                if key == "type":
                    clean_params.update(self._normalize_type_field(value))
                elif key == "properties" and isinstance(value, dict):
                    # Limpiar recursivamente las propiedades
                    clean_props = {}
                    for prop_name, prop_def in value.items():
                        if isinstance(prop_def, dict):
                            clean_props[prop_name] = self._clean_openai_specific_fields(prop_def)
                        else:
                            clean_props[prop_name] = prop_def
                    clean_params[key] = clean_props
                elif key == "enum" and isinstance(value, list):
                    clean_enum = self._normalize_enum_field(value)
                    if clean_enum:
                        clean_params[key] = clean_enum
                elif key == "items" and isinstance(value, dict):
                    # Limpiar recursivamente los items de array
                    clean_params[key] = self._clean_openai_specific_fields(value)
                elif key in {"anyOf", "oneOf"} and isinstance(value, list):
                    clean_params[key] = [
                        self._clean_openai_specific_fields(item)
                        for item in value
                        if isinstance(item, dict)
                    ]
                else:
                    clean_params[key] = value
            else:
                logging.debug(f"Campo '{key}' removido (no soportado por Gemini)")

        return clean_params

    def _normalize_enum_field(self, value: List[Any]) -> List[str]:
        """
        Gemini SDK modela Schema.enum como list[str].

        Reglas:
        - eliminar null/None del enum y dejar que `nullable` controle ese caso
        - convertir valores primitivos a string
        - deduplicar preservando el orden
        """
        normalized: List[str] = []
        seen: set[str] = set()

        for item in value:
            if item is None:
                continue

            if isinstance(item, bool):
                item_str = "true" if item else "false"
            else:
                item_str = str(item)

            if item_str in seen:
                continue

            seen.add(item_str)
            normalized.append(item_str)

        return normalized

    def _normalize_type_field(self, value: Any) -> Dict:
        """
        Gemini no acepta type como lista (ej: ["string", "null"]).
        Convierte ese formato a:
        - {"type": "string", "nullable": True} cuando aplica
        - {"anyOf": [...]} para uniones de múltiples tipos no-null.
        """
        if isinstance(value, str):
            return {"type": value.lower()}

        if not isinstance(value, list):
            return {}

        normalized_types = []
        for item in value:
            if isinstance(item, str):
                item_lower = item.lower()
                if item_lower not in normalized_types:
                    normalized_types.append(item_lower)

        if not normalized_types:
            return {}

        has_null = "null" in normalized_types
        non_null_types = [item for item in normalized_types if item != "null"]

        if not non_null_types:
            return {"type": "null"}

        if len(non_null_types) == 1:
            result = {"type": non_null_types[0]}
            if has_null:
                result["nullable"] = True
            return result

        union_types = [{"type": type_name} for type_name in non_null_types]
        if has_null:
            union_types.append({"type": "null"})

        return {"anyOf": union_types}

    def _prepare_generation_config(self, text: Optional[Dict], tool_choice: str) -> Dict:
        """Preparar configuración de generación para Gemini"""
        config = {"candidate_count": 1}

        if text:
            if "temperature" in text:
                config["temperature"] = float(text["temperature"])
            if "max_tokens" in text:
                config["max_output_tokens"] = int(text["max_tokens"])
            if "top_p" in text:
                config["top_p"] = float(text["top_p"])

        return config

    def _map_gemini_response(self, response, model: str) -> LLMResponse:
        output_text = ""
        tool_calls = []
        content_parts = []

        if response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for idx, part in enumerate(candidate.content.parts):

                    # 1. Texto
                    if part.text:
                        output_text += part.text
                        content_parts.append({"type": "text", "text": part.text})

                    # 2. Llamada a Herramienta
                    elif part.function_call:
                        args = self._extract_function_call_args(part.function_call)

                        tool_calls.append(ToolCall(
                            call_id=part.function_call.name,
                            type="function_call",
                            name=part.function_call.name,
                            arguments=json.dumps(args)
                        ))

                    # 3. Imagen Generada (Nativo Gemini / Imagen 3)
                    # El nuevo SDK suele usar part.inline_data o part.blob para esto
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": part.inline_data.mime_type,
                                "data": part.inline_data.data
                            }
                        })
                        output_text += "\n[Imagen Generada]\n"

                    elif hasattr(part, 'blob') and part.blob:
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": part.blob.mime_type,
                                "data": part.blob.data
                            }
                        })
                        output_text += "\n[Imagen Generada]\n"

        if not output_text:
            output_text = self._extract_structured_output_text(response)
            if output_text:
                content_parts.append({"type": "text", "text": output_text})

        # Extraer usage
        usage = self._extract_usage_metadata(response)

        return LLMResponse(
            id=str(uuid.uuid4()),
            model=model,
            status="completed", # Simplificado, puedes mapear candidate.finish_reason si quieres
            output_text=output_text,
            output=tool_calls,
            usage=usage,
            content_parts=content_parts
        )

    def _extract_structured_output_text(self, response: Any) -> str:
        """Recover native structured output when Gemini does not emit it in text parts."""
        parsed_response = self._get_native_response_attr(response, "parsed")
        if parsed_response not in (None, ""):
            return self._serialize_structured_value(parsed_response)

        response_text = self._get_native_response_attr(response, "text")
        if isinstance(response_text, str) and response_text.strip():
            return response_text

        if isinstance(response_text, (dict, list)):
            serialized = self._serialize_structured_value(response_text)
            if serialized:
                return serialized

        return ""

    @staticmethod
    def _serialize_structured_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)

    @staticmethod
    def _get_native_response_attr(response: Any, attr_name: str) -> Any:
        try:
            value = getattr(response, attr_name)
        except Exception:
            return None

        if type(value).__module__.startswith("unittest.mock"):
            return None

        return value

    def _log_structured_response_debug(self, response: Any, used_response_schema: bool) -> None:
        if not used_response_schema:
            return

        try:
            parsed_value = self._get_native_response_attr(response, "parsed")
            response_text = self._get_native_response_attr(response, "text")
            candidate = response.candidates[0] if getattr(response, "candidates", None) else None
            parts = []
            if candidate and getattr(candidate, "content", None) and getattr(candidate.content, "parts", None):
                parts = candidate.content.parts

            part_kinds = []
            for part in parts:
                kinds = []
                if getattr(part, "text", None) not in (None, ""):
                    kinds.append("text")
                if getattr(part, "function_call", None) is not None:
                    kinds.append("function_call")
                if getattr(part, "inline_data", None) is not None:
                    kinds.append("inline_data")
                if getattr(part, "blob", None) is not None:
                    kinds.append("blob")
                if not kinds:
                    kinds.append("other")
                part_kinds.append("+".join(kinds))

            parsed_keys = None
            if isinstance(parsed_value, dict):
                parsed_keys = list(parsed_value.keys())[:10]

            logging.debug(
                "Gemini structured output debug | text_present=%s text_preview=%r parsed_type=%s parsed_keys=%s part_kinds=%s finish_reason=%s",
                bool(isinstance(response_text, str) and response_text.strip()),
                (response_text[:300] if isinstance(response_text, str) else response_text),
                type(parsed_value).__name__ if parsed_value is not None else None,
                parsed_keys,
                part_kinds,
                getattr(candidate, "finish_reason", None),
            )
        except Exception as exc:
            logging.warning("Gemini structured output debug logging failed: %s", exc)

    def _raise_for_truncated_structured_output(self, response: Any, used_response_schema: bool) -> None:
        if not used_response_schema:
            return

        candidate = response.candidates[0] if getattr(response, "candidates", None) else None
        finish_reason = getattr(candidate, "finish_reason", None)
        if not self._is_max_tokens_finish_reason(finish_reason):
            return

        raise IAToolkitException(
            IAToolkitException.ErrorType.LLM_ERROR,
            "Gemini truncó la respuesta JSON por límite de salida (MAX_TOKENS). "
            "Aumenta max_output_tokens o divide la extracción en varias llamadas.",
        )

    @staticmethod
    def _is_max_tokens_finish_reason(finish_reason: Any) -> bool:
        if finish_reason is None:
            return False

        finish_reason_name = getattr(finish_reason, "name", None)
        if isinstance(finish_reason_name, str) and finish_reason_name.upper() == "MAX_TOKENS":
            return True

        return "MAX_TOKENS" in str(finish_reason).upper()

    def _extract_function_call_args(self, function_call) -> Dict:
        """
        Extract tool-call arguments from Gemini SDK objects.
        Current google-genai SDK exposes `args` directly.
        """
        try:
            direct_args = getattr(function_call, "args", None)
            if direct_args is None:
                return {}

            if isinstance(direct_args, dict):
                return direct_args
            if isinstance(direct_args, str):
                try:
                    return json.loads(direct_args)
                except Exception:
                    return {"value": direct_args}
            if hasattr(direct_args, "items"):
                return {k: v for k, v in direct_args.items()}
            if hasattr(direct_args, "to_dict"):
                return direct_args.to_dict()
            if hasattr(direct_args, "model_dump"):
                return direct_args.model_dump()
        except Exception as e:
            logging.debug(f"Could not read function_call.args directly: {e}")

        return {}

    def _extract_usage_metadata(self, gemini_response) -> Usage:
        """Extraer información de uso de tokens de manera segura"""
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

        try:
            # Verificar si existe usage_metadata
            if hasattr(gemini_response, 'usage_metadata') and gemini_response.usage_metadata:
                usage_metadata = gemini_response.usage_metadata

                # Acceder a los atributos directamente, no con .get()
                if hasattr(usage_metadata, 'prompt_token_count'):
                    input_tokens = usage_metadata.prompt_token_count
                if hasattr(usage_metadata, 'candidates_token_count'):
                    output_tokens = usage_metadata.candidates_token_count
                if hasattr(usage_metadata, 'total_token_count'):
                    total_tokens = usage_metadata.total_token_count

        except Exception as e:
            logging.warning(f"No se pudo extraer usage_metadata de Gemini: {e}")

        # Cuando Gemini no entrega total_token_count pero sí prompt/candidates,
        # mantenemos una semántica consistente calculando el total desde esos valores.
        if total_tokens == 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens

        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens
        )
