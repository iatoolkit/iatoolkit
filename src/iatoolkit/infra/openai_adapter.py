# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import Dict, List, Optional
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.common.exceptions import IAToolkitException


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
                        tool_choice: str = "auto") -> LLMResponse:
        """Llamada a la API de OpenAI y mapeo a estructura común"""
        try:
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

            # En caso de error de contexto
            if "context_length_exceeded" in str(e):
                error_message = 'Tu consulta supera el limite de contexto. Reinicia el contexto con el boton de la barra superior.'

            raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR, error_message)

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

        return LLMResponse(
            id=openai_response.id,
            model=openai_response.model,
            status=openai_response.status,
            output_text=getattr(openai_response, 'output_text', ''),
            output=tool_calls,
            usage=usage
        )