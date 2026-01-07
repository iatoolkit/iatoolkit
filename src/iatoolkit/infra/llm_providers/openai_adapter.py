# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import Dict, List, Optional
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.common.exceptions import IAToolkitException
import html
from typing import List
import mimetypes


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
        """Mapear respuesta de OpenAI a estructura común"""
        # Mapear tool calls
        tool_calls = []
        if hasattr(openai_response, 'output') and openai_response.output:
            for tool_call in openai_response.output:
                if hasattr(tool_call, 'type') and tool_call.type == "function_call":
                    tool_calls.append(ToolCall(
                        call_id=getattr(tool_call, 'call_id', ''),
                        type=tool_call.type,
                        name=getattr(tool_call, 'name', ''),
                        arguments=getattr(tool_call, 'arguments', '{}')
                    ))

        # Mapear usage
        usage = Usage(
            input_tokens=openai_response.usage.input_tokens if openai_response.usage else 0,
            output_tokens=openai_response.usage.output_tokens if openai_response.usage else 0,
            total_tokens=openai_response.usage.total_tokens if openai_response.usage else 0
        )

        # Reasoning content extracted from Responses output items (type="reasoning")
        reasoning_list = self._extract_reasoning_content(openai_response)
        reasoning_str = "\n".join(reasoning_list)

        return LLMResponse(
            id=openai_response.id,
            model=openai_response.model,
            status=openai_response.status,
            output_text=getattr(openai_response, 'output_text', ''),
            output=tool_calls,
            usage=usage,
            reasoning_content=reasoning_str
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
