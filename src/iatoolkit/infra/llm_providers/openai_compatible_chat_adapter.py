# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
import logging
import mimetypes
import threading
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
    supports_reasoning = True
    supports_reasoning_effort = False
    supports_reasoning_content_messages = False
    supports_metadata = False
    supports_parallel_tool_calls = False
    supports_thinking = False
    allow_follow_up_tool_calls = True

    def __init__(self, openai_compatible_client, provider_label: str = "OpenAI-compatible"):
        self.client = openai_compatible_client
        self.provider_label = provider_label
        self._pending_assistant_tool_messages: Dict[str, Dict[str, Any]] = {}
        self._pending_assistant_tool_messages_lock = threading.Lock()

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
        telemetry_execution = kwargs.get("telemetry_execution")

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

            tools_payload = self._build_tools_payload(tools)
            if not tools_payload:
                tool_choice = None
            elif not self.allow_follow_up_tool_calls:
                has_function_outputs = any(
                    item.get("type") == "function_call_output" for item in input
                )
                if has_function_outputs and tool_choice == "auto":
                    logging.debug(
                        "[%sAdapter] Detected function_call_output in input; disabling tools/tool_choice for this provider.",
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

            self._apply_reasoning_request_options(
                call_kwargs=call_kwargs,
                model=model,
                reasoning=reasoning,
                kwargs=kwargs,
            )

            if self.supports_metadata and metadata:
                call_kwargs["metadata"] = metadata

            if self.supports_parallel_tool_calls and kwargs.get("parallel_tool_calls") is not None:
                call_kwargs["parallel_tool_calls"] = bool(kwargs.get("parallel_tool_calls"))

            self._extend_call_kwargs(call_kwargs, kwargs)
            self._record_telemetry_input(telemetry_execution, call_kwargs)

            logging.debug(
                "[%sAdapter] Calling chat.completions API with %s messages.",
                self.provider_label,
                len(messages),
            )
            response = self._create_chat_completion(call_kwargs)

            return self._map_chat_completion_response(response)

        except IAToolkitException:
            raise
        except Exception as ex:
            logging.exception("Unexpected error calling %s provider", self.provider_label)
            raise IAToolkitException(
                IAToolkitException.ErrorType.LLM_ERROR,
                f"{self.provider_label} error: {ex}"
            ) from ex

    @staticmethod
    def _record_telemetry_input(telemetry_execution: Any, payload: Dict[str, Any]) -> None:
        record_input = getattr(telemetry_execution, "record_input", None)
        if callable(record_input):
            record_input(payload)

    def _extend_call_kwargs(self, call_kwargs: Dict[str, Any], kwargs: Dict[str, Any]) -> None:
        _ = call_kwargs
        _ = kwargs

    def _create_chat_completion(self, call_kwargs: Dict[str, Any]) -> Any:
        try:
            return self.client.chat.completions.create(**call_kwargs)
        except Exception as ex:
            retry_call_kwargs = self._build_retry_without_tool_choice_kwargs(call_kwargs, ex)
            if retry_call_kwargs is None:
                raise

            logging.warning(
                "[%sAdapter] Provider rejected tool_choice for model '%s'; retrying without tool_choice.",
                self.provider_label,
                call_kwargs.get("model"),
            )
            return self.client.chat.completions.create(**retry_call_kwargs)

    @staticmethod
    def _build_retry_without_tool_choice_kwargs(
        call_kwargs: Dict[str, Any],
        ex: Exception,
    ) -> Optional[Dict[str, Any]]:
        if "tool_choice" not in call_kwargs:
            return None

        error_message = str(ex or "").lower()
        if "does not support this tool_choice" not in error_message:
            return None

        retry_call_kwargs = dict(call_kwargs)
        retry_call_kwargs.pop("tool_choice", None)
        return retry_call_kwargs

    def _apply_reasoning_request_options(
        self,
        call_kwargs: Dict[str, Any],
        model: str,
        reasoning: Optional[Dict[str, Any]],
        kwargs: Dict[str, Any],
    ) -> None:
        reasoning_payload = self._build_reasoning_payload(reasoning, kwargs)
        if self.supports_reasoning and reasoning_payload:
            call_kwargs["reasoning"] = reasoning_payload

        reasoning_effort = self._extract_reasoning_effort(reasoning, kwargs)
        if self.supports_reasoning_effort:
            mapped_effort = self._map_reasoning_effort(model, reasoning_effort, kwargs)
            if mapped_effort:
                call_kwargs["reasoning_effort"] = mapped_effort

        if self.supports_thinking:
            thinking_payload = self._build_thinking_payload(model, reasoning, kwargs)
            if thinking_payload is not None:
                extra_body = dict(call_kwargs.get("extra_body") or {})
                extra_body["thinking"] = thinking_payload
                call_kwargs["extra_body"] = extra_body

    @staticmethod
    def _extract_reasoning_effort(reasoning: Optional[Dict[str, Any]], kwargs: Dict[str, Any]) -> str:
        explicit_effort = kwargs.get("reasoning_effort")
        if explicit_effort is not None:
            return str(explicit_effort or "").strip().lower()

        if isinstance(reasoning, dict):
            return str(reasoning.get("effort") or "").strip().lower()

        return ""

    def _build_reasoning_payload(
        self,
        reasoning: Optional[Dict[str, Any]],
        kwargs: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if isinstance(reasoning, dict):
            normalized_reasoning = dict(reasoning)
            normalized_effort = self._extract_reasoning_effort(reasoning, kwargs)
            if normalized_effort:
                normalized_reasoning["effort"] = normalized_effort
            if normalized_reasoning:
                return normalized_reasoning

        reasoning_effort = self._extract_reasoning_effort(reasoning, kwargs)
        if reasoning_effort:
            return {"effort": reasoning_effort}

        return None

    def _map_reasoning_effort(self, model: str, effort: str, kwargs: Dict[str, Any]) -> Optional[str]:
        _ = model
        _ = kwargs
        return effort or None

    def _build_thinking_payload(
        self,
        model: str,
        reasoning: Optional[Dict[str, Any]],
        kwargs: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        _ = model
        _ = reasoning
        return self._normalize_thinking_payload(kwargs.get("thinking"))

    @staticmethod
    def _normalize_thinking_payload(raw_thinking: Any) -> Optional[Dict[str, Any]]:
        if raw_thinking is None:
            return None

        if isinstance(raw_thinking, dict):
            normalized = dict(raw_thinking)
            thinking_type = str(normalized.get("type") or "").strip().lower()
            if thinking_type:
                normalized["type"] = thinking_type
            return normalized

        if isinstance(raw_thinking, bool):
            return {"type": "enabled" if raw_thinking else "disabled"}

        thinking_type = str(raw_thinking or "").strip().lower()
        if not thinking_type:
            return None

        return {"type": thinking_type}

    def _build_messages_from_input(self, input_items: List[Dict]) -> List[Dict]:
        messages: List[Dict[str, Any]] = []
        seen_tool_call_ids: set[str] = set()

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

                call_id = str(item.get("call_id") or "").strip()
                if call_id and call_id not in seen_tool_call_ids:
                    pending_assistant_message = self._consume_pending_assistant_tool_message(call_id)
                    if pending_assistant_message is not None:
                        messages.append(pending_assistant_message)
                        seen_tool_call_ids.update(
                            self._extract_tool_call_ids(pending_assistant_message.get("tool_calls"))
                        )

                tool_message: Dict[str, Any] = {
                    "role": "tool",
                    "content": output,
                }
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
            tool_calls = self._normalize_tool_calls(item.get("tool_calls"))
            if tool_calls:
                message["tool_calls"] = tool_calls
                seen_tool_call_ids.update(self._extract_tool_call_ids(tool_calls))

            if self.supports_reasoning_content_messages:
                reasoning_content = str(item.get("reasoning_content") or "").strip()
                if reasoning_content:
                    message["reasoning_content"] = reasoning_content

            tool_call_id = str(item.get("tool_call_id") or "").strip()
            if role == "tool" and tool_call_id:
                message["tool_call_id"] = tool_call_id

            annotations = item.get("annotations")
            if annotations is not None:
                message["annotations"] = annotations

            messages.append(message)

        return messages

    def _consume_pending_assistant_tool_message(self, call_id: str) -> Optional[Dict[str, Any]]:
        if not call_id:
            return None

        with self._pending_assistant_tool_messages_lock:
            pending_entry = self._pending_assistant_tool_messages.get(call_id)
            if not pending_entry:
                return None

            for pending_call_id in pending_entry.get("call_ids", []):
                self._pending_assistant_tool_messages.pop(pending_call_id, None)

            assistant_message = pending_entry.get("assistant_message")
            return dict(assistant_message) if isinstance(assistant_message, dict) else None

    @staticmethod
    def _extract_tool_call_ids(tool_calls: Any) -> List[str]:
        call_ids: List[str] = []
        if not isinstance(tool_calls, list):
            return call_ids

        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                call_id = str(tool_call.get("id") or "").strip()
            else:
                call_id = str(getattr(tool_call, "id", "") or "").strip()
            if call_id:
                call_ids.append(call_id)

        return call_ids

    def _normalize_tool_calls(self, tool_calls: Any) -> List[Dict[str, Any]]:
        normalized_tool_calls: List[Dict[str, Any]] = []
        if not isinstance(tool_calls, list):
            return normalized_tool_calls

        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                function = tool_call.get("function") or {}
                normalized_tool_call = {
                    "id": str(tool_call.get("id") or "").strip(),
                    "type": str(tool_call.get("type") or "function").strip() or "function",
                    "function": {
                        "name": str(function.get("name") or "").strip(),
                        "arguments": str(function.get("arguments") or "{}"),
                    },
                }
            else:
                function = getattr(tool_call, "function", None)
                normalized_tool_call = {
                    "id": str(getattr(tool_call, "id", "") or "").strip(),
                    "type": str(getattr(tool_call, "type", "function") or "function").strip() or "function",
                    "function": {
                        "name": str(getattr(function, "name", "") or "").strip(),
                        "arguments": str(getattr(function, "arguments", "{}") or "{}"),
                    },
                }

            if normalized_tool_call["id"] and normalized_tool_call["function"]["name"]:
                normalized_tool_calls.append(normalized_tool_call)

        return normalized_tool_calls

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

            if tool.get("strict") is True and "strict" not in func_def:
                func_def["strict"] = True

            compat_tool: Dict[str, Any] = {
                "type": tool.get("type", "function"),
                "function": func_def,
            }

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
            normalized_tool_calls = self._normalize_tool_calls(tool_calls)
            self._cache_pending_assistant_tool_message(
                response=response,
                message=message,
                normalized_tool_calls=normalized_tool_calls,
                reasoning_content=reasoning_content,
            )

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

    def _cache_pending_assistant_tool_message(
        self,
        response: Any,
        message: Any,
        normalized_tool_calls: List[Dict[str, Any]],
        reasoning_content: str,
    ) -> None:
        if not normalized_tool_calls:
            return

        assistant_message: Dict[str, Any] = {
            "role": "assistant",
            "content": getattr(message, "content", "") or "",
            "tool_calls": normalized_tool_calls,
        }
        if self.supports_reasoning_content_messages and reasoning_content:
            assistant_message["reasoning_content"] = reasoning_content

        group_id = str(getattr(response, "id", "") or normalized_tool_calls[0]["id"]).strip()
        pending_entry = {
            "group_id": group_id,
            "call_ids": [tool_call["id"] for tool_call in normalized_tool_calls],
            "assistant_message": assistant_message,
        }

        with self._pending_assistant_tool_messages_lock:
            for tool_call in normalized_tool_calls:
                self._pending_assistant_tool_messages[tool_call["id"]] = pending_entry
