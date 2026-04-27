# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
import logging
import mimetypes
from typing import Any, Dict, List, Optional

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage


class OpenAICompatibleChatAdapter:
    """
    Adapter for Chat Completions-style providers.

    This adapter targets providers that expose a `chat.completions` compatible
    endpoint with `messages`, `tools`, `tool_calls`, and `response_format`.
    """

    supports_multimodal = False
    supports_reasoning = False
    supports_metadata = False
    supports_parallel_tool_calls = False

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
        attachments = kwargs.get("attachments") or []
        text = kwargs.get("text") or {}
        reasoning = kwargs.get("reasoning")
        metadata = kwargs.get("metadata")

        try:
            messages: List[Dict[str, Any]] = []
            if context_history:
                history_messages = self._build_messages_from_input(context_history)
                messages.extend(history_messages)

            current_messages = self._build_messages_from_input(input)
            messages.extend(current_messages)

            if images or attachments:
                if self.supports_multimodal:
                    messages = self._prepare_multimodal_messages(messages, images, attachments)
                else:
                    logging.warning(
                        "[%sAdapter] Multimodal content provided but this provider is configured as text-only. "
                        "Ignoring %s images and %s attachments.",
                        self.provider_label,
                        len(images),
                        len(attachments),
                    )

            has_function_outputs = any(
                item.get("type") == "function_call_output" for item in input
            )

            tools_payload = self._build_tools_payload(tools)
            if not tools_payload:
                tool_choice = None

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

            tool_choice_payload = self._map_tool_choice(tool_choice, tools_payload or [])
            if tool_choice_payload is not None:
                call_kwargs["tool_choice"] = tool_choice_payload

            response_format = self._extract_response_format(text)
            if response_format:
                call_kwargs["response_format"] = response_format

            if self.supports_reasoning and reasoning:
                call_kwargs["reasoning"] = reasoning

            if self.supports_metadata and metadata:
                call_kwargs["metadata"] = metadata

            if self.supports_parallel_tool_calls and kwargs.get("parallel_tool_calls") is not None:
                call_kwargs["parallel_tool_calls"] = bool(kwargs.get("parallel_tool_calls"))

            self._extend_call_kwargs(call_kwargs, kwargs)

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

    def _extend_call_kwargs(self, call_kwargs: Dict[str, Any], kwargs: Dict[str, Any]) -> None:
        _ = call_kwargs
        _ = kwargs

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

                tool_message: Dict[str, Any] = {
                    "role": "tool",
                    "content": output,
                }
                call_id = str(item.get("call_id") or "").strip()
                if call_id:
                    tool_message["tool_call_id"] = call_id
                messages.append(tool_message)
                continue

            role = str(item.get("role") or "").strip().lower()
            content = item.get("content")

            if not role:
                logging.warning("[%sAdapter] Skipping message without role: %s", self.provider_label, item)
                continue

            if role == "model":
                role = "assistant"

            message: Dict[str, Any] = {"role": role, "content": content}
            tool_call_id = str(item.get("tool_call_id") or "").strip()
            if role == "tool" and tool_call_id:
                message["tool_call_id"] = tool_call_id

            annotations = item.get("annotations")
            if annotations is not None:
                message["annotations"] = annotations

            messages.append(message)

        return messages

    def _prepare_multimodal_messages(
        self,
        messages: List[Dict[str, Any]],
        images: List[Dict],
        attachments: List[Dict],
    ) -> List[Dict[str, Any]]:
        target_index = None
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                target_index = index
                break

        if target_index is None:
            return messages

        target_message = dict(messages[target_index])
        content_parts = self._coerce_content_to_parts(target_message.get("content"))

        for img in images:
            image_part = self._build_image_part(img)
            if image_part is not None:
                content_parts.append(image_part)

        for attachment in attachments:
            file_part = self._build_file_part(attachment)
            if file_part is not None:
                content_parts.append(file_part)

        target_message["content"] = content_parts
        updated_messages = list(messages)
        updated_messages[target_index] = target_message
        return updated_messages

    @staticmethod
    def _coerce_content_to_parts(content: Any) -> List[Dict[str, Any]]:
        if isinstance(content, list):
            return list(content)
        if content in (None, ""):
            return []
        return [{"type": "text", "text": str(content)}]

    def _build_image_part(self, image: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(image, dict):
            return None

        filename = str(image.get("name") or image.get("filename") or "").strip()
        mime_type = str(image.get("mime_type") or image.get("type") or "").strip().lower()
        if not mime_type:
            mime_type = mimetypes.guess_type(filename)[0] or "image/jpeg"

        raw_url = str(image.get("url") or image.get("image_url") or "").strip()
        if raw_url:
            data_url = raw_url
        else:
            base64_data = str(image.get("base64") or image.get("content") or "").strip()
            if not base64_data:
                return None
            data_url = self._to_data_url(base64_data, mime_type)

        return {
            "type": "image_url",
            "image_url": {
                "url": data_url,
            },
        }

    def _build_file_part(self, attachment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(attachment, dict):
            return None

        filename = str(attachment.get("name") or attachment.get("filename") or "attachment").strip()
        mime_type = str(
            attachment.get("mime_type")
            or attachment.get("type")
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        ).strip().lower()

        raw_file_data = str(attachment.get("file_data") or attachment.get("url") or "").strip()
        if raw_file_data:
            file_data = raw_file_data
        else:
            base64_data = str(attachment.get("base64") or attachment.get("content") or "").strip()
            if not base64_data:
                return None
            file_data = self._to_data_url(base64_data, mime_type)

        return {
            "type": "file",
            "file": {
                "filename": filename,
                "file_data": file_data,
            },
        }

    @staticmethod
    def _to_data_url(base64_data: str, mime_type: str) -> str:
        payload = str(base64_data or "").strip()
        if payload.lower().startswith("data:") and "," in payload:
            return payload
        try:
            base64.b64decode(payload, validate=True)
            return f"data:{mime_type};base64,{payload}"
        except Exception:
            return payload

    def _build_tools_payload(self, tools: List[Dict]) -> Optional[List[Dict]]:
        if not tools:
            return None

        tools_payload: List[Dict[str, Any]] = []

        for tool in tools:
            if "function" in tool:
                func_def = dict(tool["function"] or {})
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

    @staticmethod
    def _map_tool_choice(
        tool_choice: Any,
        tools_payload: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any] | str]:
        if tool_choice in ("", None, "auto"):
            return None

        if isinstance(tool_choice, dict):
            return tool_choice

        if tool_choice in {"none", "required"}:
            return tool_choice

        tool_names = {
            str((tool.get("function") or {}).get("name") or "").strip()
            for tool in (tools_payload or [])
            if isinstance(tool, dict)
        }
        if str(tool_choice).strip() in tool_names:
            return {
                "type": "function",
                "function": {
                    "name": str(tool_choice).strip(),
                },
            }

        return str(tool_choice)

    @staticmethod
    def _extract_response_format(text: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if isinstance(text, dict) and isinstance(text.get("response_format"), dict):
            return dict(text["response_format"])
        return None

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
