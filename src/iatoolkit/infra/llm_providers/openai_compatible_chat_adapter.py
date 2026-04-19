# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import Any, Dict, List, Optional

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage


class OpenAICompatibleChatAdapter:
    """
    Adapter for OpenAI-compatible Chat Completions APIs.

    This adapter is used for providers that expose a `chat.completions` style
    interface with `messages`, `tools`, and `tool_calls`.
    """

    def __init__(self, openai_compatible_client, provider_label: str = "OpenAI-compatible"):
        self.client = openai_compatible_client
        self.provider_label = provider_label

    def create_response(self, model: str, input: List[Dict], **kwargs) -> LLMResponse:
        """
        Entry point called by LLMProxy.

        :param model: Model name exposed by the compatible endpoint.
        :param input: Common IAToolkit input list. It may contain:
                      - normal messages: {"role": "...", "content": "..."}
                      - function outputs: {"type": "function_call_output",
                                           "call_id": "...", "output": "..."}
        :param kwargs: extra options (tools, tool_choice, context_history, etc.).
        """
        tools = kwargs.get("tools") or []
        tool_choice = kwargs.get("tool_choice", "auto")
        context_history = kwargs.get("context_history") or []
        images = kwargs.get("images") or []
        text = kwargs.get("text") or {}

        if images:
            logging.warning(
                "[%sAdapter] Images provided but these models are not multimodal. Ignoring %s images.",
                self.provider_label,
                len(images),
            )

        try:
            messages: List[Dict[str, Any]] = []
            if context_history:
                history_messages = self._build_messages_from_input(context_history)
                messages.extend(history_messages)

            current_messages = self._build_messages_from_input(input)
            messages.extend(current_messages)

            has_function_outputs = any(
                item.get("type") == "function_call_output" for item in input
            )

            tools_payload = self._build_tools_payload(tools)

            if has_function_outputs and tool_choice == "auto":
                logging.debug(
                    "[%sAdapter] Detected function_call_output in input; disabling tools and tool_choice to avoid tool loop.",
                    self.provider_label,
                )
                tools_payload = None
                tool_choice = None

            call_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
            }
            if tools_payload:
                call_kwargs["tools"] = tools_payload
            if tool_choice:
                call_kwargs["tool_choice"] = tool_choice
            if isinstance(text, dict) and isinstance(text.get("response_format"), dict):
                call_kwargs["response_format"] = text["response_format"]

            logging.debug(
                "[%sAdapter] Calling chat.completions API with %s messages.",
                self.provider_label,
                len(messages),
            )
            response = self.client.chat.completions.create(**call_kwargs)

            return self._map_chat_completion_response(response)

        except IAToolkitException:
            raise
        except Exception as ex:
            logging.exception("Unexpected error calling %s provider", self.provider_label)
            raise IAToolkitException(
                IAToolkitException.ErrorType.LLM_ERROR,
                f"{self.provider_label} error: {ex}"
            ) from ex

    def _build_messages_from_input(self, input_items: List[Dict]) -> List[Dict]:
        messages: List[Dict[str, Any]] = []

        for item in input_items:
            if item.get("type") == "function_call_output":
                output = item.get("output", "")
                if not output:
                    logging.warning(
                        "[%sAdapter] function_call_output item without 'output': %s",
                        self.provider_label,
                        item,
                    )
                    continue

                messages.append(
                    {
                        "role": "user",
                        "content": f"Tool result:\n{output}",
                    }
                )
                continue

            role = item.get("role")
            content = item.get("content")

            if role == "tool":
                logging.warning("[%sAdapter] Skipping tool-role message: %s", self.provider_label, item)
                continue

            if not role:
                logging.warning("[%sAdapter] Skipping message without role: %s", self.provider_label, item)
                continue

            messages.append({"role": role, "content": content})

        return messages

    def _build_tools_payload(self, tools: List[Dict]) -> Optional[List[Dict]]:
        if not tools:
            return None

        tools_payload: List[Dict[str, Any]] = []

        for tool in tools:
            if "function" in tool:
                func_def = tool["function"]
            else:
                func_def = {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}) or {},
                }

            if "parameters" in func_def and not isinstance(func_def["parameters"], dict):
                logging.warning(
                    "Tool parameters must be a dict; got %s",
                    type(func_def["parameters"])
                )
                func_def["parameters"] = {}

            compat_tool: Dict[str, Any] = {
                "type": tool.get("type", "function"),
                "function": func_def,
            }

            if tool.get("strict") is True:
                compat_tool["strict"] = True

            tools_payload.append(compat_tool)

        return tools_payload or None

    def _map_chat_completion_response(self, response: Any) -> LLMResponse:
        if not response.choices:
            raise IAToolkitException(
                IAToolkitException.ErrorType.LLM_ERROR,
                f"{self.provider_label} response has no choices."
            )

        choice = response.choices[0]
        message = choice.message

        usage = Usage(
            input_tokens=getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0,
            output_tokens=getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0,
            total_tokens=getattr(getattr(response, "usage", None), "total_tokens", 0) or 0,
        )

        reasoning_content = getattr(message, "reasoning_content", "") or ""

        tool_calls_out: List[ToolCall] = []
        content_parts: List[Dict] = []

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            output_text = getattr(message, "content", "") or ""
            status = "completed"

            if output_text:
                content_parts.append({
                    "type": "text",
                    "text": output_text
                })

        else:
            logging.debug("[%s] RAW tool_calls: %s", self.provider_label, tool_calls)

            for tc in tool_calls:
                func = getattr(tc, "function", None)
                if not func:
                    continue

                name = getattr(func, "name", "")
                arguments = getattr(func, "arguments", "") or "{}"

                logging.debug(
                    "[%s] ToolCall generated -> id=%s name=%s arguments_raw=%s",
                    self.provider_label,
                    getattr(tc, "id", ""),
                    name,
                    arguments,
                )
                tool_calls_out.append(
                    ToolCall(
                        call_id=getattr(tc, "id", ""),
                        type="function_call",
                        name=name,
                        arguments=arguments,
                    )
                )

            output_text = ""
            status = "tool_calls"

        return LLMResponse(
            id=getattr(response, "id", ""),
            model=getattr(response, "model", ""),
            status=status,
            output_text=output_text,
            output=tool_calls_out,
            usage=usage,
            reasoning_content=reasoning_content,
            content_parts=content_parts,
        )

    # Backward-compatible alias retained while the old DeepSeek-specific name
    # is still referenced by a few tests/imports.
    def _map_deepseek_chat_response(self, response: Any) -> LLMResponse:
        return self._map_chat_completion_response(response)
