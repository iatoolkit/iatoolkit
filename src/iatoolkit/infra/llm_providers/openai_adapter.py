# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import Dict, List, Optional
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.common.exceptions import IAToolkitException
from typing import List
import mimetypes
import re


class OpenAIAdapter:
    """Adaptador para la API de OpenAI"""

    def __init__(self, openai_client):
        self.client = openai_client

    def create_response(self,
                        model: str,
                        input: List[Dict],
                        previous_response_id: Optional[str] = None,
                        context_history: Optional[List[Dict]] = None,
                        tools: Optional[List[Dict]] = None,
                        text: Optional[Dict] = None,
                        reasoning: Optional[Dict] = None,
                        tool_choice: str = "auto",
                        images: Optional[List[Dict]] = None) -> LLMResponse:
        """Llamada a la API de OpenAI y mapeo a estructura común"""
        try:
            # Handle multimodal input if images are present
            if images:
                input = self._prepare_multimodal_input(input, images)

            # Preparar parámetros para OpenAI
            params = {
                'model': model,
                'input': input
            }

            # add image generation tool
            if tools:
                tools.append({"type": "image_generation"})

            if previous_response_id:
                params['previous_response_id'] = previous_response_id
            if tools:
                params['tools'] = tools
            if text:
                params['text'] = text
            if reasoning:
                params['reasoning'] = reasoning
            if tool_choice != "auto":
                params['tool_choice'] = tool_choice

            # Llamar a la API de OpenAI
            openai_response = self.client.responses.create(**params)

            # Mapear la respuesta a estructura común
            return self._map_openai_response(openai_response)

        except Exception as e:
            error_message = f"Error calling OpenAI API: {str(e)}"
            logging.error(error_message)

            raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR, error_message)

    def _prepare_multimodal_input(self, messages: List[Dict], images: List[Dict]) -> List[Dict]:
        """
        Transforma el mensaje del usuario de texto simple a contenido multimodal (texto + imágenes)
        usando el formato de Responses API (input_text/input_image).
        """
        # Encontrar el último mensaje del usuario
        target_message = None
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                target_message = msg
                break

        if not target_message:
            return messages

        text_content = target_message.get('content', '')
        content_parts = []

        # Agregar parte de texto (Responses API)
        if text_content:
            content_parts.append({"type": "input_text", "text": text_content})

        # Agregar partes de imagen (Responses API)
        for img in images:
            filename = img.get('name', '')
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'image/jpeg'

            base64_data = img.get('base64', '')
            url = f"data:{mime_type};base64,{base64_data}"

            content_parts.append({
                "type": "input_image",
                "image_url": url
            })

        # Construir nueva lista de mensajes con el contenido actualizado
        final_messages = []
        for msg in messages:
            if msg is target_message:
                new_msg = msg.copy()
                new_msg['content'] = content_parts
                final_messages.append(new_msg)
            else:
                final_messages.append(msg)

        return final_messages

    def _map_openai_response(self, openai_response) -> LLMResponse:
        """Mapear respuesta de OpenAI (Responses API) a estructura común."""
        tool_calls: List[ToolCall] = []
        content_parts: List[Dict] = []
        output_text = ""

        output_items = getattr(openai_response, "output", None) or []

        for item in output_items:
            item_type = getattr(item, "type", "") or ""

            # 1) Tool calls: function_call
            if item_type == "function_call":
                tool_calls.append(ToolCall(
                    call_id=getattr(item, "call_id", "") or "",
                    type=item_type,
                    name=getattr(item, "name", "") or "",
                    arguments=getattr(item, "arguments", "{}") or "{}",
                ))
                continue

            # 2) Tool calls: image_generation_call -> base64 en item.result
            if item_type == "image_generation_call":
                b64 = getattr(item, "result", None) or ""
                if b64:
                    content_parts.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64
                        }
                    })
                    content_parts.append({
                        "type": "text",
                        "text": f"![Imagen Generada](data:image/png;base64,{b64})"
                    })
                continue

            # 3) Mensajes: solo texto
            if item_type == "message":
                msg_content = getattr(item, "content", None) or []
                for part in msg_content:
                    part_type = getattr(part, "type", "") or ""
                    if part_type in ("output_text", "text"):
                        text_content = getattr(part, "text", "") or ""
                        if text_content:
                            output_text += text_content
                            content_parts.append({"type": "text", "text": text_content})
                continue

        # Fallback: si la API rellenó output_text directo
        if not output_text:
            output_text = getattr(openai_response, "output_text", "") or ""
            if output_text and not content_parts:
                content_parts.append({"type": "text", "text": output_text})

        usage = Usage(
            input_tokens=openai_response.usage.input_tokens if openai_response.usage else 0,
            output_tokens=openai_response.usage.output_tokens if openai_response.usage else 0,
            total_tokens=openai_response.usage.total_tokens if openai_response.usage else 0
        )

        reasoning_list = self._extract_reasoning_content(openai_response)
        reasoning_str = "\n".join(reasoning_list)

        return LLMResponse(
            id=openai_response.id,
            model=openai_response.model,
            status=openai_response.status,
            output_text=output_text,
            output=tool_calls,
            usage=usage,
            reasoning_content=reasoning_str,
            content_parts=content_parts
        )

    def _extract_reasoning_content(self, openai_response) -> List[str]:
        """
        Extract reasoning summaries (preferred) or reasoning content fragments from Responses API output.

        Format required by caller:
          1. reason is ...
          2. reason is ...
        """
        reasons: List[str] = []

        output_items = getattr(openai_response, "output", None) or []
        for item in output_items:
            if getattr(item, "type", None) != "reasoning":
                continue

            # 1) Preferred: reasoning summaries (requires reasoning={"summary":"auto"} or similar)
            summary = getattr(item, "summary", None) or []
            for s in summary:
                text = getattr(s, "text", None)
                if text:
                    reasons.append(str(text).strip())

            # 2) Fallback: some responses may carry reasoning content in "content"
            # (e.g., content parts like {"type":"reasoning_text","text":"..."}).
            content = getattr(item, "content", None) or []
            for c in content:
                text = getattr(c, "text", None)
                if text:
                    reasons.append(str(text).strip())

        return reasons
