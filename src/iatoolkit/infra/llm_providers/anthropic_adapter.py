# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import json
import logging
import mimetypes
from typing import Any, Dict, List, Optional

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage


class AnthropicAdapter:
    """Adapter for Anthropic Messages API."""

    def __init__(self, anthropic_client):
        self.client = anthropic_client
        # call_id -> {"name": str, "input": dict}
        # Used to reconstruct required tool_use blocks when receiving function_call_output.
        self._tool_calls_by_id: Dict[str, Dict[str, Any]] = {}

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
        """
        Calls Anthropic Messages API and maps the response to common LLMResponse.

        Notes:
        - Anthropic is integrated as client-side history, so previous_response_id is ignored.
        - reasoning is currently not sent as a provider-specific parameter.
        """
        _ = previous_response_id
        _ = reasoning

        try:
            full_input = (context_history or []) + input
            system_prompt, messages = self._prepare_messages(full_input, images or [])

            params: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "max_tokens": int((text or {}).get("max_tokens", 2048)),
            }

            if system_prompt:
                params["system"] = system_prompt

            temperature = self._safe_float((text or {}).get("temperature"))
            if temperature is not None:
                params["temperature"] = temperature

            top_p = self._safe_float((text or {}).get("top_p"))
            if top_p is not None:
                params["top_p"] = top_p

            tools_payload = self._prepare_tools_payload(tools or [])
            if tools_payload:
                params["tools"] = tools_payload

                tool_choice_payload = self._map_tool_choice(tool_choice, tools_payload)
                if tool_choice_payload:
                    params["tool_choice"] = tool_choice_payload

            anthropic_response = self.client.messages.create(**params)
            return self._map_anthropic_response(anthropic_response, model)

        except Exception as e:
            error_message = f"Error calling Anthropic API: {str(e)}"
            logging.error(error_message)
            raise IAToolkitException(
                IAToolkitException.ErrorType.LLM_ERROR,
                error_message
            ) from e

    def _prepare_messages(self, input_items: List[Dict], images: List[Dict]) -> tuple[Optional[str], List[Dict]]:
        system_parts: List[str] = []
        messages: List[Dict] = []

        for item in input_items:
            if item.get("role") == "system":
                content = item.get("content")
                if content:
                    system_parts.append(str(content))
                continue

            if item.get("type") == "function_call_output":
                output_text = self._serialize_tool_output(item.get("output", ""))
                tool_use_id = item.get("call_id") or item.get("name") or "tool_call_unknown"
                tool_use_id_str = str(tool_use_id)

                # Anthropic requires each tool_result to match a tool_use block in the previous message.
                # If we can resolve the previous tool_use from adapter state, we build that pair.
                # Otherwise we fallback to plain text to avoid hard API errors.
                prev_tool_use = self._tool_calls_by_id.pop(tool_use_id_str, None)
                if prev_tool_use:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": tool_use_id_str,
                                    "name": prev_tool_use.get("name", "tool_call"),
                                    "input": prev_tool_use.get("input", {}) or {},
                                }
                            ],
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_id_str,
                                    "content": output_text,
                                }
                            ],
                        }
                    )
                else:
                    logging.warning(
                        "[AnthropicAdapter] Missing prior tool_use for call_id=%s. "
                        "Sending tool output as plain text fallback.",
                        tool_use_id_str,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Tool result:\n{output_text}",
                        }
                    )
                continue

            role = item.get("role")
            if role in ("assistant", "model"):
                role = "assistant"
            elif role != "user":
                logging.debug(f"[AnthropicAdapter] Skipping unsupported role: {item}")
                continue

            content = item.get("content", "")
            normalized_content = self._normalize_content_to_text(content)
            messages.append(
                {
                    "role": role,
                    "content": normalized_content,
                }
            )

        if images:
            self._attach_images_to_last_user_message(messages, images)

        system_prompt = "\n".join(system_parts) if system_parts else None
        return system_prompt, messages

    def _attach_images_to_last_user_message(self, messages: List[Dict], images: List[Dict]):
        target_index = -1
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.get("role") == "user" and not self._is_tool_result_message(msg):
                target_index = i
                break

        if target_index == -1:
            messages.append({"role": "user", "content": ""})
            target_index = len(messages) - 1

        target = messages[target_index]
        content = target.get("content", "")

        if isinstance(content, str):
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            blocks = content.copy()
        else:
            blocks = [{"type": "text", "text": str(content)}] if content is not None else []

        for img in images:
            filename = img.get("name", "")
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = "image/jpeg"
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": img.get("base64", ""),
                }
            })

        target["content"] = blocks

    @staticmethod
    def _is_tool_result_message(message: Dict) -> bool:
        content = message.get("content")
        if not isinstance(content, list) or not content:
            return False
        if len(content) != 1:
            return False
        first = content[0]
        return isinstance(first, dict) and first.get("type") == "tool_result"

    @staticmethod
    def _normalize_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    ptype = part.get("type")
                    if ptype in ("text", "output_text", "input_text"):
                        text = part.get("text")
                        if text:
                            parts.append(str(text))
            return "\n".join(parts)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _prepare_tools_payload(tools: List[Dict]) -> Optional[List[Dict]]:
        if not tools:
            return None

        payload: List[Dict] = []
        for tool in tools:
            if tool.get("type") != "function" and "function" not in tool and "name" not in tool:
                continue

            function_data = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            name = function_data.get("name")
            if not name:
                continue

            payload.append(
                {
                    "name": name,
                    "description": function_data.get("description", "") or "",
                    "input_schema": function_data.get("parameters") or {"type": "object", "properties": {}},
                }
            )

        return payload or None

    @staticmethod
    def _map_tool_choice(tool_choice: str, tools_payload: List[Dict]) -> Optional[Dict]:
        if not tools_payload:
            return None

        if tool_choice == "required":
            return {"type": "any"}

        if tool_choice in ("auto", "", None):
            return {"type": "auto"}

        if tool_choice == "none":
            return None

        tool_names = {t.get("name") for t in tools_payload}
        if tool_choice in tool_names:
            return {"type": "tool", "name": tool_choice}

        return {"type": "auto"}

    def _map_anthropic_response(self, response: Any, fallback_model: str) -> LLMResponse:
        output_text = ""
        tool_calls: List[ToolCall] = []
        content_parts: List[Dict] = []
        reasoning_fragments: List[str] = []

        blocks = getattr(response, "content", None) or []
        for block in blocks:
            block_type = getattr(block, "type", None)

            if block_type == "text":
                text = getattr(block, "text", "") or ""
                if text:
                    output_text += text
                    content_parts.append({"type": "text", "text": text})
                continue

            if block_type == "thinking":
                thinking = getattr(block, "thinking", "") or ""
                if thinking:
                    reasoning_fragments.append(str(thinking))
                continue

            if block_type == "tool_use":
                args = getattr(block, "input", None)
                call_id = getattr(block, "id", "") or ""
                name = getattr(block, "name", "") or ""
                if call_id:
                    normalized_args = self._normalize_tool_input(args)
                    self._tool_calls_by_id[call_id] = {
                        "name": name,
                        "input": normalized_args,
                    }
                tool_calls.append(
                    ToolCall(
                        call_id=call_id,
                        type="function_call",
                        name=name,
                        arguments=self._serialize_tool_arguments(args),
                    )
                )
                continue

            if block_type == "image":
                source = getattr(block, "source", None)
                if source:
                    media_type = getattr(source, "media_type", None) or "image/png"
                    data = getattr(source, "data", None) or ""
                    if data:
                        content_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            }
                        })

        usage_obj = getattr(response, "usage", None)
        input_tokens = getattr(usage_obj, "input_tokens", 0) if usage_obj else 0
        output_tokens = getattr(usage_obj, "output_tokens", 0) if usage_obj else 0
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

        status = "tool_calls" if tool_calls else "completed"

        return LLMResponse(
            id=getattr(response, "id", "") or "anthropic-unknown",
            model=getattr(response, "model", "") or fallback_model,
            status=status,
            output_text=output_text,
            output=tool_calls,
            usage=Usage(
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                total_tokens=total_tokens or 0,
            ),
            reasoning_content="\n".join(reasoning_fragments),
            content_parts=content_parts,
        )

    @staticmethod
    def _serialize_tool_output(output: Any) -> str:
        if isinstance(output, str):
            return output
        try:
            return json.dumps(output, ensure_ascii=False, default=str)
        except Exception:
            return str(output)

    @staticmethod
    def _serialize_tool_arguments(args: Any) -> str:
        if args is None:
            return "{}"
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                return json.dumps(parsed, ensure_ascii=False)
            except Exception:
                return json.dumps({"value": args}, ensure_ascii=False)
        if isinstance(args, dict):
            return json.dumps(args, ensure_ascii=False)
        try:
            return json.dumps(dict(args), ensure_ascii=False)
        except Exception:
            return json.dumps({"value": str(args)}, ensure_ascii=False)

    @staticmethod
    def _normalize_tool_input(args: Any) -> Dict[str, Any]:
        if args is None:
            return {}
        if isinstance(args, dict):
            return args
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    return parsed
                return {"value": parsed}
            except Exception:
                return {"value": args}
        try:
            return dict(args)
        except Exception:
            return {"value": str(args)}

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None
