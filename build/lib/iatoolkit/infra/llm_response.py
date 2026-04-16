# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from dataclasses import dataclass
from typing import Dict, List, Any, Optional

@dataclass
class ToolCall:
    """Representa una llamada a herramienta en formato común"""
    call_id: str
    type: str  # 'function_call'
    name: str
    arguments: str


@dataclass
class Usage:
    """Información de uso de tokens en formato común"""
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    """Estructura común para respuestas de diferentes LLMs"""
    id: str
    model: str
    status: str  # 'completed', 'failed', etc.
    output_text: str
    output: List[ToolCall]  # lista de tool calls
    usage: Usage
    reasoning_content: str = None # campo opcional para Chain of Thought

    # ordered list of content blocks (text and image mixed)
    # Example: [{"type": "text", "text": "..."}, {"type": "image", "source": {"type": "base64", "data": "..."}}]
    content_parts: List[Dict] = None

    def __post_init__(self):
        """Asegura que output sea una lista"""
        if self.output is None:
            self.output = []

        if self.reasoning_content is None:
            self.reasoning_content = ""

        if self.content_parts is None:
            self.content_parts = []

            # if the response has legacy text and no content parts, create a default text part
            if self.output_text:
                self.content_parts.append({
                    "type": "text",
                    "text": self.output_text
                })

