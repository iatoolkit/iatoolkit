# deepseek_adapter.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
from typing import Dict, List, Optional, Any

from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.common.exceptions import IAToolkitException
import json

class DeepseekAdapter:
    """
    Adapter for DeepSeek using the OpenAI-compatible Chat Completions API.
    It translates IAToolkit's common request/response format into
    DeepSeek chat.completions calls.
    """

    def __init__(self, deepseek_client):
        # deepseek_client is an OpenAI client configured with base_url="https://api.deepseek.com"
        self.client = deepseek_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def create_response(self, model: str, input: List[Dict], **kwargs) -> LLMResponse:
        """
        Entry point called by LLMProxy.

        :param model: DeepSeek model name (e.g. "deepseek-chat").
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

        if images:
            logging.warning(
                f"[DeepseekAdapter] Images provided but DeepSeek models are not multimodal. "
                f"Ignoring {len(images)} images."
            )

        try:
            # 1) Build messages from history (if any)
            messages: List[Dict[str, Any]] = []
            if context_history:
                history_messages = self._build_messages_from_input(context_history)
                messages.extend(history_messages)

            # 2) Append current turn messages
            current_messages = self._build_messages_from_input(input)
            messages.extend(current_messages)

            # Detect if this input already contains function_call_output items.
            # That means we are in the "second phase" after executing tools.
            has_function_outputs = any(
                item.get("type") == "function_call_output" for item in input
            )

            # 3) Build the tools payload
            tools_payload = self._build_tools_payload(tools)

            # If we already have function_call_output messages and the caller did not force
            # a specific tool_choice (e.g. "required" for SQL retry), we disable tools and
            # tool_choice to avoid infinite tool-calling loops (especially with iat_sql_query).
            if has_function_outputs and tool_choice == "auto":
                logging.debug(
                    "[DeepseekAdapter] Detected function_call_output in input; "
                    "disabling tools and tool_choice to avoid tool loop."
                )
                tools_payload = None
                tool_choice = None

            logging.debug(f"[DeepseekAdapter] messages={messages}")
            logging.debug(f"[DeepseekAdapter] tools={tools_payload}, tool_choice={tool_choice}")

            # Build kwargs for API call, skipping empty parameters
            call_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
            }
            if tools_payload:
                call_kwargs["tools"] = tools_payload
            if tool_choice:
                call_kwargs["tool_choice"] = tool_choice

            logging.debug(f"[DeepseekAdapter] Calling DeepSeek chat.completions API...: {json.dumps(messages, indent=2)}")
            response = self.client.chat.completions.create(**call_kwargs)

            return self._map_deepseek_chat_response(response)

        except IAToolkitException:
            # Re-raise IAToolkit exceptions as is
            raise
        except Exception as ex:
            logging.exception("Unexpected error calling DeepSeek")
            raise IAToolkitException(
                IAToolkitException.ErrorType.LLM_ERROR,
                f"DeepSeek error: {ex}"
            ) from ex

    # ------------------------------------------------------------------
    # Helpers to build the request
    # ------------------------------------------------------------------

    def _build_messages_from_input(self, input_items: List[Dict]) -> List[Dict]:
        """
        Transform IAToolkit 'input' items into ChatCompletion 'messages'.

        We handle:
        - Standard messages with 'role' and 'content'.
        - function_call_output items by converting them into assistant messages
          containing the tool result, so the model can use them to answer.
        """
        messages: List[Dict[str, Any]] = []

        for item in input_items:
            # Tool call outputs are mapped to assistant messages with the tool result.
            if item.get("type") == "function_call_output":
                output = item.get("output", "")
                if not output:
                    logging.warning(
                        "[DeepseekAdapter] function_call_output item without 'output': %s",
                        item
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

            # Skip tool-role messages completely for DeepSeek
            if role == "tool":
                logging.warning(f"[DeepseekAdapter] Skipping tool-role message: {item}")
                continue

            if not role:
                logging.warning(f"[DeepseekAdapter] Skipping message without role: {item}")
                continue

            messages.append({"role": role, "content": content})

        return messages

    def _build_tools_payload(self, tools: List[Dict]) -> Optional[List[Dict]]:
        """
        Transform IAToolkit tool definitions into DeepSeek/OpenAI chat tools format.

        Expected internal tool format:
        {
            "type": "function",
            "name": ...,
            "description": ...,
            "parameters": {...},
            "strict": True/False
        }
        Or already in OpenAI tools format with "function" key.
        """
        if not tools:
            return None

        tools_payload: List[Dict[str, Any]] = []

        for tool in tools:
            # If it's already in OpenAI 'function' format, reuse it
            if "function" in tool:
                func_def = tool["function"]
            else:
                # Build function definition from flattened structure
                func_def = {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}) or {},
                }

            # Ensure parameters is a dict
            if "parameters" in func_def and not isinstance(func_def["parameters"], dict):
                logging.warning(
                    "Tool parameters must be a dict; got %s",
                    type(func_def["parameters"])
                )
                func_def["parameters"] = {}

            ds_tool: Dict[str, Any] = {
                "type": tool.get("type", "function"),
                "function": func_def,
            }

            if tool.get("strict") is True:
                ds_tool["strict"] = True

            tools_payload.append(ds_tool)

        return tools_payload or None

    # ------------------------------------------------------------------
    # Mapping DeepSeek response -> LLMResponse
    # ------------------------------------------------------------------

    def _map_deepseek_chat_response(self, response: Any) -> LLMResponse:
        """
        Map DeepSeek Chat Completion response to our common LLMResponse.
        Handles both plain assistant messages and tool_calls.
        """
        # We only look at the first choice
        if not response.choices:
            raise IAToolkitException(
                IAToolkitException.ErrorType.LLM_ERROR,
                "DeepSeek response has no choices."
            )

        choice = response.choices[0]
        message = choice.message

        # Usage mapping
        usage = Usage(
            input_tokens=getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0,
            output_tokens=getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0,
            total_tokens=getattr(getattr(response, "usage", None), "total_tokens", 0) or 0,
        )

        # Capture reasoning content (specific to deepseek-reasoner)
        reasoning_content = getattr(message, "reasoning_content", "") or ""

        # If the model produced tool calls, fills this list
        tool_calls_out: List[ToolCall] = []

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            # No tool calls: standard assistant message
            output_text = getattr(message, "content", "") or ""
            status = "completed"

        else:
            logging.debug(f"[DeepSeek] RAW tool_calls: {tool_calls}")

            for tc in tool_calls:
                func = getattr(tc, "function", None)
                if not func:
                    continue

                name = getattr(func, "name", "")
                arguments = getattr(func, "arguments", "") or "{}"

                # DeepSeek/OpenAI return arguments as JSON string
                logging.debug(
                    f"[DeepSeek] ToolCall generated -> id={getattr(tc, 'id', '')} "
                    f"name={name} arguments_raw={arguments}"
                )
                tool_calls_out.append(
                    ToolCall(
                        call_id=getattr(tc, "id", ""),
                        type="function_call",
                        name=name,
                        arguments=arguments,
                    )
                )

            status = "tool_calls"
            output_text = ""  # caller will inspect tool_calls in .output

        return LLMResponse(
            id=getattr(response, "id", "deepseek-unknown"),
            model=getattr(response, "model", "deepseek-unknown"),
            status=status,
            output_text=output_text,
            output=tool_calls_out,
            usage=usage,
            reasoning_content=reasoning_content
        )