# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from typing import Dict, List, Optional
from google.genai import types
from iatoolkit.common.exceptions import IAToolkitException
import logging
import json
import uuid
import mimetypes
import re


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
                        ) -> LLMResponse:
        try:

            # Separamos las instrucciones del sistema del resto del contenido
            system_instruction, filtered_input = self._extract_system_and_filter_input(
                (context_history or []) + input
            )

            # prepare tools and contents
            contents = self._prepare_gemini_contents(
                (context_history or []) + input,
                images
            )

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                safety_settings=self.safety_settings,
                tools=self._prepare_gemini_tools(tools),
                temperature=float(text.get("temperature", 0.7)) if text else 0.7,
                max_output_tokens=int(text.get("max_tokens", 2048)) if text else 2048,
                top_p=float(text.get("top_p", 0.95)) if text else 0.95,
                candidate_count=1,
                # response_modalities=['TEXT', 'IMAGE']
            )

            # call the new SDK
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
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
            error_message = f"Error calling Gemini API: {str(e)}"
            logging.error(error_message)

            # handle gemini specific errors
            if "quota" in str(e).lower():
                error_message = "Se ha excedido la cuota de la API de Gemini"
            elif "blocked" in str(e).lower():
                error_message = "El contenido fue bloqueado por las políticas de seguridad de Gemini"
            elif "token" in str(e).lower():
                error_message = "Tu consulta supera el límite de contexto de Gemini"

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

    def _prepare_gemini_contents(self, input: List[Dict], images: Optional[List[Dict]] = None) -> List[types.Content]:
        gemini_contents = []

        # Encontrar el último mensaje de usuario para las imágenes
        last_user_idx = -1
        for i, m in enumerate(input):
            if m.get("role") == "user" and m.get("content"):
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
                        parts.append(types.Part.from_bytes(
                            data=img.get('base64', ''),
                            mime_type=mimetypes.guess_type(img.get('name', ''))[0] or 'image/jpeg'
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


    def _clean_openai_specific_fields(self, parameters: Dict) -> Dict:
        """Limpiar campos específicos de OpenAI que Gemini no entiende"""
        clean_params = {}

        # Campos permitidos por Gemini según su Schema protobuf
        # Estos son los únicos campos que Gemini acepta en sus esquemas
        allowed_fields = {
            "type",  # Tipo de datos: string, number, object, array, boolean
            "properties",  # Para objetos: define las propiedades
            "required",  # Array de propiedades requeridas
            "items",  # Para arrays: define el tipo de elementos
            "description",  # Descripción del campo
            "enum",  # Lista de valores permitidos
            # Gemini NO soporta estos campos comunes de JSON Schema:
            # "pattern", "format", "minimum", "maximum", "minItems", "maxItems",
            # "minLength", "maxLength", "additionalProperties", "strict"
        }

        for key, value in parameters.items():
            if key in allowed_fields:
                if key == "properties" and isinstance(value, dict):
                    # Limpiar recursivamente las propiedades
                    clean_props = {}
                    for prop_name, prop_def in value.items():
                        if isinstance(prop_def, dict):
                            clean_props[prop_name] = self._clean_openai_specific_fields(prop_def)
                        else:
                            clean_props[prop_name] = prop_def
                    clean_params[key] = clean_props
                elif key == "items" and isinstance(value, dict):
                    # Limpiar recursivamente los items de array
                    clean_params[key] = self._clean_openai_specific_fields(value)
                else:
                    clean_params[key] = value
            else:
                logging.debug(f"Campo '{key}' removido (no soportado por Gemini)")

        return clean_params

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

        # Si no hay datos de usage o son cero, hacer estimación básica
        if total_tokens == 0 and output_tokens == 0:
            # Obtener texto de salida para estimación
            output_text = ""
            if (hasattr(gemini_response, 'candidates') and
                    gemini_response.candidates and
                    len(gemini_response.candidates) > 0):

                candidate = gemini_response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            output_text += part.text

            # Estimación básica (4 caracteres por token aproximadamente)
            estimated_output_tokens = len(output_text) // 4 if output_text else 0
            output_tokens = estimated_output_tokens
            total_tokens = estimated_output_tokens

        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens
        )
