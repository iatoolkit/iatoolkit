# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.infra.llm_proxy import LLMProxy
from iatoolkit.repositories.models import Company, LLMQuery
from iatoolkit.repositories.llm_query_repo import LLMQueryRepo
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from iatoolkit.common.util import Utility
from iatoolkit.common.model_registry import ModelRegistry
from injector import inject
import time
import markdown2
import os
import logging
import json
import yaml
from html import unescape
from iatoolkit.common.exceptions import IAToolkitException
import threading
import re
import tiktoken
from typing import Dict, Optional, List, Any
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.services.storage_service import StorageService
from iatoolkit.services.structured_output_service import StructuredOutputService
from iatoolkit.services.telemetry_service import NoopTelemetryService

CONTEXT_ERROR_MESSAGE = 'Tu consulta supera el límite de contexto, utiliza el boton de recarga de contexto.'
TELEMETRY_MAX_STRING_LENGTH = 1000
TELEMETRY_MAX_COLLECTION_ITEMS = 20
TELEMETRY_MAX_DEPTH = 4
TELEMETRY_REDACTED_VALUE = "[REDACTED]"

class llmClient:
    _llm_clients_cache = {}      # class attribute, for the clients cache
    _clients_cache_lock = threading.Lock()  # secure lock cache access

    @inject
    def __init__(self,
                 llmquery_repo: LLMQueryRepo,
                 llm_proxy: LLMProxy,
                 model_registry: ModelRegistry,
                 storage_service: StorageService,
                 util: Utility,
                 telemetry_service=None,
                 ):
        self.llmquery_repo = llmquery_repo
        self.llm_proxy = llm_proxy
        self.model_registry = model_registry
        self.storage_service = storage_service
        self.util = util
        self._dispatcher = None # Cache for the lazy-loaded dispatcher
        self._telemetry_service = telemetry_service

        # Lazy init to avoid network/bootstrap failures during app startup.
        self.encoding = None

        # max number of sql retries
        self.MAX_SQL_RETRIES = 1

    @property
    def dispatcher(self) -> 'Dispatcher':
        """Lazy-loads and returns the Dispatcher instance."""
        if self._dispatcher is None:
            # Import what you need, right when you need it.
            from iatoolkit import current_iatoolkit
            from iatoolkit.services.dispatcher_service import Dispatcher
            # Use the global context proxy to get the injector, then get the service
            self._dispatcher = current_iatoolkit().get_injector().get(Dispatcher)
        return self._dispatcher

    @property
    def telemetry_service(self):
        if self._telemetry_service is None:
            try:
                from iatoolkit import current_iatoolkit
                from iatoolkit.services.telemetry_service import TelemetryService

                self._telemetry_service = current_iatoolkit().get_injector().get(TelemetryService)
            except Exception:
                self._telemetry_service = NoopTelemetryService()
        return self._telemetry_service


    def invoke(self,
               company: Company,
               user_identifier: str,
               previous_response_id: str,
               question: str,
               context: str,
               tools: list[dict],
               text: dict,
               model: str,
               tool_choice_override: Optional[str] = None,
               context_history: Optional[List[Dict]] = None,
               images: list = None,
               attachments: list = None,
               reasoning: Optional[Dict[str, Any]] = None,
               store: Optional[bool] = None,
               task_id: Optional[int] = None,
               execution_metadata: Optional[Dict[str, Any]] = None,
               request_metadata: Optional[Dict[str, str]] = None,
               telemetry_request: Optional[Dict[str, Any]] = None,
               response_contract: Optional[Dict[str, Any]] = None
               ) -> dict:

        images = images or []
        attachments = attachments or []
        active_attachments = list(attachments)
        f_calls = []  # keep track of the function calls executed by the LLM
        f_call_time = 0
        history_messages = []
        response = None
        sql_retry_count = 0
        force_tool_name = None
        company_id = getattr(company, "id", None)

        # Resolve per-model defaults and apply overrides (without mutating inputs).
        request_params = self.model_registry.resolve_request_params(
            model=model,
            text=text,
            reasoning=reasoning,
        )
        text_payload = request_params["text"]
        reasoning_payload = request_params["reasoning"]
        telemetry_execution = self.telemetry_service.start_execution(telemetry_request)
        request_source = str((execution_metadata or {}).get("request_source") or "").strip().lower()

        try:
            start_time = time.time()
            reasoning_mode = str((reasoning_payload or {}).get("effort") or "none").strip().lower() or "none"
            transport_mode = self.llm_proxy.describe_transport(company.short_name, model)
            logging.info(
                (
                    "calling llm model '%s' with %s tokens...and %s images...and %s native attachments..."
                    "and reasoning mode '%s'...and transport '%s'..."
                ),
                model,
                self.count_tokens(context, context_history),
                len(images),
                len(attachments),
                reasoning_mode,
                transport_mode,
            )

            # this is the first call to the LLM on the iteration
            try:
                input_messages = [{
                    "role": "user",
                    "content": context
                }]

                initial_tool_choice = tool_choice_override or "auto"
                if not tools:
                    initial_tool_choice = None

                response = self.llm_proxy.create_response(
                    company_short_name=company.short_name,
                    model=model,
                    input=input_messages,
                    previous_response_id=previous_response_id,
                    context_history=context_history,
                    tools=tools,
                    tool_choice=initial_tool_choice,
                    text=text_payload,
                    reasoning=reasoning_payload,
                    images=images,
                    attachments=active_attachments,
                    store=store,
                    metadata=request_metadata,
                    telemetry_request=telemetry_request,
                    telemetry_execution=telemetry_execution,
                )
                history_messages.extend(self._build_history_messages_from_response(response))
                stats = self.get_stats(response)

            except Exception as e:
                # if the llm api fails: context, api-key, etc
                # log the error and envolve in our own exception
                error_message = f"Error calling LLM API: {str(e)}"
                logging.error(error_message)

                # in case of context error
                if "context_length_exceeded" in str(e):
                    error_message = CONTEXT_ERROR_MESSAGE

                raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR, error_message)

            while True:
                # check if there are function calls to execute
                function_calls = False
                stats_fcall = {}
                has_pending_tool_calls = any(
                    tool_call.type == "function_call" for tool_call in (response.output or [])
                )
                if has_pending_tool_calls:
                    pending_response_history_messages = self._build_history_messages_from_response(response)
                    response_assistant_messages = [
                        message
                        for message in pending_response_history_messages
                        if isinstance(message, dict) and message.get("role") == "assistant"
                    ]
                    if response_assistant_messages:
                        input_messages.extend(response_assistant_messages)

                for tool_call in response.output:
                    if tool_call.type != "function_call":
                        continue

                    # execute the function call through the dispatcher
                    fcall_time = time.time()
                    function_name = tool_call.name

                    try:
                        args = json.loads(tool_call.arguments)
                    except Exception as e:
                        logging.error(f"[Dispatcher] json.loads failed: {e}")
                        raise
                    logging.debug(f"[Dispatcher] Parsed args = {args}")

                    tool_call_id = str(getattr(tool_call, "call_id", "") or "").strip()
                    tool_span = None
                    tool_status = None
                    tool_result_for_telemetry = None
                    tool_error_message = None
                    tool_output_type = None
                    tool_attachments_count = 0
                    tool_elapsed_seconds = 0.0

                    try:
                        call_kwargs = dict(args)
                        if images:
                            call_kwargs["request_images"] = images

                        tool_span = telemetry_execution.start_child_span(
                            name=f"tool.{function_name}",
                            span_type="tool",
                            event=self._build_tool_telemetry_start_event(
                                company_short_name=company.short_name,
                                function_name=function_name,
                                call_id=tool_call_id,
                                args=call_kwargs,
                                request_source=request_source,
                            ),
                        )

                        try:
                            result = self.dispatcher.dispatch(
                                company_short_name=company.short_name,
                                function_name=function_name,
                                user_identifier=user_identifier,
                                _iat_runtime_source=request_source,
                                **call_kwargs
                            )
                            force_tool_name = None
                            tool_status = "completed"
                        except IAToolkitException as e:
                            if (e.error_type == IAToolkitException.ErrorType.DATABASE_ERROR and
                                sql_retry_count < self.MAX_SQL_RETRIES):
                                sql_retry_count += 1
                                sql_query_with_error = args.get('query', 'No se pudo extraer la consulta.')
                                original_db_error = str(e.__cause__) if e.__cause__ else str(e)

                                logging.warning(
                                        f"Error de SQL capturado, intentando corregir con el LLM (Intento {sql_retry_count}/{self.MAX_SQL_RETRIES}).")
                                result = self._create_sql_retry_prompt(function_name, sql_query_with_error, original_db_error)

                                # force the next call to be this function
                                force_tool_name = function_name
                                tool_status = "retry_generated"
                            else:
                                error_message = f"**LLM_DISPATCHER** error en dispatch para tool: '{function_name}': {str(e)}"
                                tool_status = "error"
                                tool_error_message = error_message
                                raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR, error_message)
                        except Exception as e:
                            error_message = f"Dispatch error en tool {function_name} con args {args} -******- {str(e)}"
                            tool_status = "error"
                            tool_error_message = error_message
                            raise IAToolkitException(IAToolkitException.ErrorType.CALL_ERROR, error_message)

                        result, tool_native_attachments = self._split_tool_result_and_native_attachments(result)
                        active_attachments = self._merge_native_attachments(active_attachments, tool_native_attachments)
                        tool_result_for_telemetry = result
                        tool_output_type = type(result).__name__
                        tool_attachments_count = len(tool_native_attachments or [])

                        # add the return value into the list of messages
                        input_messages.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "status": "completed",
                            "output": self._serialize_tool_output(result)
                        })
                        history_messages.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "status": "completed",
                            "output": self._serialize_tool_output(result),
                        })
                        function_calls = True
                    finally:
                        tool_elapsed_seconds = time.time() - fcall_time
                        telemetry_execution.log_child_span(
                            tool_span,
                            self._build_tool_telemetry_finish_event(
                                function_name=function_name,
                                call_id=tool_call_id,
                                status=tool_status,
                                elapsed_seconds=tool_elapsed_seconds,
                                result=tool_result_for_telemetry,
                                error_message=tool_error_message,
                                output_type=tool_output_type,
                                attachments_count=tool_attachments_count,
                            ),
                        )
                        telemetry_execution.end_child_span(tool_span)

                    # log the function call parameters and execution time in secs
                    elapsed = tool_elapsed_seconds
                    f_call_identity = {function_name:args, 'time': f'{elapsed:.1f}' }
                    f_calls.append(f_call_identity)
                    f_call_time += elapsed

                    logging.info(f"[{company.short_name}] end execution of tool: {function_name} in {elapsed:.1f} secs.")

                if not function_calls:
                    break           # no more function calls, the answer to send back to llm

                # send results back to the LLM
                tool_choice_value = "auto"
                if force_tool_name:
                    tool_choice_value = "required"

                response = self.llm_proxy.create_response(
                    company_short_name=company.short_name,
                    model=model,
                    input=input_messages,
                    previous_response_id=response.id,
                    context_history=context_history,
                    reasoning=reasoning_payload,
                    tool_choice=tool_choice_value,
                    tools=tools,
                    text=text_payload,
                    images=images,
                    attachments=active_attachments,
                    store=store,
                    metadata=request_metadata,
                    telemetry_request=telemetry_request,
                    telemetry_execution=telemetry_execution,
                )
                history_messages.extend(self._build_history_messages_from_response(response))
                stats_fcall = self.add_stats(stats_fcall, self.get_stats(response))

            # --- IMAGE PROCESSING ---
            # before save or respond, upload the images to S3 and clean content_parts
            self._process_generated_images(response, company.short_name)

            # save the statistices
            stats['response_time']=int(time.time() - start_time)
            stats['sql_retry_count'] = sql_retry_count
            stats['model'] = model

            combined_stats = self.add_stats(stats, stats_fcall)
            combined_stats["tool_call_count"] = len(f_calls)
            combined_stats["tool_time_ms_total"] = int(round(f_call_time * 1000))
            if isinstance(execution_metadata, dict):
                combined_stats = dict(combined_stats or {})
                request_source = str(execution_metadata.get("request_source") or "").strip().lower()
                if request_source:
                    combined_stats["request_source"] = request_source
                for key, value in execution_metadata.items():
                    if key == "request_source":
                        continue
                    if value is not None:
                        combined_stats[key] = value

            # decode the LLM response
            decoded_response = self.decode_response(response)
            decoded_response = self._apply_response_contract(decoded_response, response_contract)

            # Extract reasoning from the final response object
            final_reasoning = getattr(response, 'reasoning_content', '')

            # save the query and response
            query = LLMQuery(user_identifier=user_identifier,
                             company_id=company_id,
                             task_id=task_id,
                             query=question,
                             output=decoded_response.get('answer', ''),
                             valid_response=decoded_response.get('status', False),
                             response=self.serialize_response(response, decoded_response),
                             function_calls=f_calls,
                             stats=combined_stats,
                             answer_time=stats['response_time']
                             )
            self.llmquery_repo.add_query(query)
            telemetry_execution.finalize(
                query_id=query.id,
                success=decoded_response.get('status', False),
                output_payload=self._build_root_telemetry_output(decoded_response),
                metrics={
                    "total_tokens": combined_stats.get("total_tokens"),
                    "response_time": combined_stats.get("response_time"),
                    "sql_retry_count": combined_stats.get("sql_retry_count"),
                    "tool_call_count": combined_stats.get("tool_call_count"),
                    "tool_time_ms_total": combined_stats.get("tool_time_ms_total"),
                },
            )
            telemetry_stats = telemetry_execution.build_stats()
            if telemetry_stats:
                query.stats = dict(query.stats or {})
                query.stats["telemetry"] = telemetry_stats
                self.llmquery_repo.commit()
                combined_stats = dict(query.stats or {})
            logging.info(f"finish llm call in {int(time.time() - start_time)} secs..")
            if function_calls:
                logging.info(f"time within the function calls {f_call_time:.1f} secs.")

            result = {
                'valid_response': decoded_response.get('status', False),
                'answer': self.format_answer(
                    decoded_response.get('answer', ''),
                    execution_metadata=execution_metadata,
                ),
                'stats': combined_stats,
                'answer_format': decoded_response.get('answer_format', ''),
                'error_message': decoded_response.get('error_message', ''),
                'additional_data': self._extract_additional_data_payload(decoded_response),
                'query_id': query.id,
                'model': model,
                'reasoning_content': final_reasoning,
                'content_parts': response.content_parts,
                'structured_output': decoded_response.get('structured_output'),
                'schema_valid': decoded_response.get('schema_valid'),
                'schema_errors': decoded_response.get('schema_errors', []),
                'schema_mode': decoded_response.get('schema_mode'),
                'schema_applied': decoded_response.get('schema_applied', False),
                'history_messages': history_messages,
            }
            if getattr(response, 'id', None):
                result['response_id'] = response.id
            return result
        except SQLAlchemyError as db_error:
            # rollback
            self.llmquery_repo.session.rollback()
            telemetry_execution.finalize(
                success=False,
                error_message=str(db_error),
            )
            logging.error(f"Error de base de datos: {str(db_error)}")
            raise db_error
        except OperationalError as e:
            telemetry_execution.finalize(
                success=False,
                error_message=str(e),
            )
            logging.error(f"Operational error: {str(e)}")
            raise e
        except Exception as e:
            error_message= str(e)

            # log the error in the llm_query table
            query = LLMQuery(user_identifier=user_identifier,
                             company_id=company_id,
                             task_id=task_id,
                             query=question,
                             output=error_message,
                             response={},
                             valid_response=False,
                             function_calls=f_calls,
                             )
            self.llmquery_repo.add_query(query)
            telemetry_execution.finalize(
                query_id=query.id,
                success=False,
                error_message=error_message,
            )
            telemetry_stats = telemetry_execution.build_stats()
            if telemetry_stats:
                query.stats = {"telemetry": telemetry_stats}
                self.llmquery_repo.commit()

            # in case of context error
            if "context_length_exceeded" in str(e):
                error_message = CONTEXT_ERROR_MESSAGE
            elif "string_above_max_length" in str(e):
                error_message = 'La respuesta es muy extensa, trata de filtrar/restringuir tu consulta'

            raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR, error_message)

    @staticmethod
    def _build_root_telemetry_output(decoded_response: dict[str, Any] | None) -> dict[str, Any]:
        payload = {
            "success": bool((decoded_response or {}).get("status", False)),
        }

        result: dict[str, Any] = {}
        answer = (decoded_response or {}).get("answer")
        if answer not in (None, ""):
            result["answer"] = answer

        structured_output = (decoded_response or {}).get("structured_output")
        if structured_output is not None:
            result["structured_output"] = structured_output

        if result:
            payload["result"] = result
        return payload

    @staticmethod
    def _serialize_tool_output(result) -> str:
        if isinstance(result, str):
            return result

        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            return str(result)

    @staticmethod
    def _split_tool_result_and_native_attachments(result):
        if not isinstance(result, dict):
            return result, []

        attachments = result.get("__native_attachments__")
        if not isinstance(attachments, list):
            return result, []

        sanitized = dict(result)
        sanitized.pop("__native_attachments__", None)
        return sanitized, attachments

    @staticmethod
    def _merge_native_attachments(current_attachments, new_attachments):
        merged = list(current_attachments or [])
        seen = {
            (
                str(item.get("name") or item.get("filename") or "").strip(),
                str(item.get("mime_type") or item.get("type") or "").strip().lower(),
                str(item.get("base64") or item.get("content") or "").strip(),
            )
            for item in merged
            if isinstance(item, dict)
        }

        for attachment in new_attachments or []:
            if not isinstance(attachment, dict):
                continue
            signature = (
                str(attachment.get("name") or attachment.get("filename") or "").strip(),
                str(attachment.get("mime_type") or attachment.get("type") or "").strip().lower(),
                str(attachment.get("base64") or attachment.get("content") or "").strip(),
            )
            if not signature[0] or not signature[2] or signature in seen:
                continue
            seen.add(signature)
            merged.append(attachment)

        return merged

    @staticmethod
    def _build_tool_telemetry_start_event(
        company_short_name: str,
        function_name: str,
        call_id: str,
        args: dict[str, Any],
        request_source: str = "",
    ) -> dict[str, Any]:
        metadata = {
            "company": company_short_name,
            "tool_name": function_name,
        }
        if call_id:
            metadata["call_id"] = call_id
        if request_source:
            metadata["request_source"] = request_source

        return {
            "metadata": metadata,
            "input": {
                "arguments": llmClient._sanitize_tool_payload_for_telemetry(args),
            },
        }

    @staticmethod
    def _build_tool_telemetry_finish_event(
        function_name: str,
        call_id: str,
        status: Optional[str],
        elapsed_seconds: float,
        result: Any = None,
        error_message: Optional[str] = None,
        output_type: Optional[str] = None,
        attachments_count: int = 0,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "tool_name": function_name,
            "status": status or "unknown",
            "elapsed_ms": int(round(max(elapsed_seconds, 0.0) * 1000)),
        }
        if call_id:
            metadata["call_id"] = call_id
        if output_type:
            metadata["output_type"] = output_type
        if attachments_count:
            metadata["attachments_count"] = attachments_count
        if error_message:
            metadata["error_message"] = llmClient._truncate_telemetry_string(str(error_message))

        event: dict[str, Any] = {"metadata": metadata}
        if result is not None:
            event["output"] = {
                "preview": llmClient._sanitize_tool_payload_for_telemetry(result, parent_key="output"),
            }
        return event

    @staticmethod
    def _sanitize_tool_payload_for_telemetry(
        value: Any,
        *,
        parent_key: str = "",
        depth: int = 0,
    ) -> Any:
        if depth >= TELEMETRY_MAX_DEPTH:
            return "[TRUNCATED_DEPTH]"

        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            items = list(value.items())
            for index, (key, item) in enumerate(items):
                if index >= TELEMETRY_MAX_COLLECTION_ITEMS:
                    sanitized["__truncated_items__"] = len(items) - TELEMETRY_MAX_COLLECTION_ITEMS
                    break

                key_str = str(key)
                key_name = key_str.strip().lower()
                if llmClient._is_sensitive_telemetry_key(key_name):
                    sanitized[key_str] = TELEMETRY_REDACTED_VALUE
                    continue

                if key_name in {"request_images", "images"} and isinstance(item, list):
                    sanitized[key_str] = {"count": len(item), "content": "[OMITTED_IMAGES]"}
                    continue

                if key_name in {"attachments", "native_attachments", "request_attachments"} and isinstance(item, list):
                    sanitized[key_str] = {"count": len(item), "content": "[OMITTED_ATTACHMENTS]"}
                    continue

                sanitized[key_str] = llmClient._sanitize_tool_payload_for_telemetry(
                    item,
                    parent_key=key_name,
                    depth=depth + 1,
                )
            return sanitized

        if isinstance(value, (list, tuple, set)):
            items = list(value)
            sanitized_items = [
                llmClient._sanitize_tool_payload_for_telemetry(item, parent_key=parent_key, depth=depth + 1)
                for item in items[:TELEMETRY_MAX_COLLECTION_ITEMS]
            ]
            if len(items) > TELEMETRY_MAX_COLLECTION_ITEMS:
                sanitized_items.append(f"[TRUNCATED_ITEMS:{len(items) - TELEMETRY_MAX_COLLECTION_ITEMS}]")
            return sanitized_items

        if isinstance(value, (bytes, bytearray)):
            return f"[BINARY:{len(value)} bytes]"

        if isinstance(value, str):
            if llmClient._looks_like_base64(value) or parent_key in {"base64", "data"}:
                return "[REDACTED_BINARY_TEXT]"
            return llmClient._truncate_telemetry_string(value)

        if isinstance(value, (int, float, bool)) or value is None:
            return value

        return llmClient._truncate_telemetry_string(str(value))

    @staticmethod
    def _is_sensitive_telemetry_key(key_name: str) -> bool:
        if not key_name:
            return False

        return any(
            marker in key_name
            for marker in (
                "api_key",
                "apikey",
                "secret",
                "password",
                "token",
                "authorization",
                "credential",
            )
        )

    @staticmethod
    def _looks_like_base64(value: str) -> bool:
        candidate = str(value or "").strip()
        if len(candidate) < 256 or len(candidate) % 4 != 0:
            return False
        return bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", candidate))

    @staticmethod
    def _truncate_telemetry_string(value: str, max_length: int = TELEMETRY_MAX_STRING_LENGTH) -> str:
        text = str(value or "")
        if len(text) <= max_length:
            return text
        return f"{text[:max_length]}...[truncated]"

    @staticmethod
    def _build_history_messages_from_response(response) -> list[dict]:
        if response is None:
            return []

        assistant_message = {
            "role": "assistant",
            "content": getattr(response, "output_text", "") or "",
        }

        tool_calls = llmClient._serialize_history_tool_calls(getattr(response, "output", None) or [])
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls

        reasoning_content = str(getattr(response, "reasoning_content", "") or "").strip()
        if reasoning_content:
            assistant_message["reasoning_content"] = reasoning_content

        has_assistant_payload = bool(assistant_message.get("content")) or bool(tool_calls) or bool(reasoning_content)
        if not has_assistant_payload:
            return []

        return [assistant_message]

    @staticmethod
    def _serialize_history_tool_calls(tool_calls) -> list[dict]:
        serialized: list[dict] = []
        for tool_call in tool_calls or []:
            if getattr(tool_call, "type", None) != "function_call":
                continue

            call_id = str(getattr(tool_call, "call_id", "") or "").strip()
            name = str(getattr(tool_call, "name", "") or "").strip()
            arguments = str(getattr(tool_call, "arguments", "{}") or "{}")
            if not call_id or not name:
                continue

            serialized.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            })

        return serialized

    def set_company_context(self,
            company: Company,
            company_base_context: str,
            model) -> str:

        logging.info(f"initializing model '{model}' with company context: {self.count_tokens(company_base_context)} tokens...")

        try:
            response = self.llm_proxy.create_response(
                company_short_name=company.short_name,
                model=model,
                input=[{
                    "role": "system",
                    "content": company_base_context
                }],

            )

        except Exception as e:
            error_message = f"Error calling LLM API: {str(e)}"
            logging.error(error_message)
            raise IAToolkitException(IAToolkitException.ErrorType.LLM_ERROR, error_message)

        return response.id

    def _process_generated_images(self, response, company_short_name: str):
        """
        Traverse content_parts, detect images in Base64, upload to S3 and update content_parts.
        """
        if not response.content_parts:
            return

        for part in response.content_parts:
            if part.get('type') == 'image':
                source = part.get('source', {})
                if source.get('type') in ['base64', 'url']:
                    try:
                        if source.get('type') == 'url':
                            url = source.get('url')
                            storage_key = None
                        else:
                            # upload image to S3
                            result = self.storage_service.store_generated_image(
                                company_short_name,
                                source.get('data'),
                                source.get('media_type', 'image/png')
                            )
                            url = result['url']
                            storage_key = result['storage_key']

                        # Update content_part: Now it's a remote reference, not base64 anymore.
                        # We keep 'url' for the frontend to display it itself, and storage_key for internal reference.
                        part['source'] = {
                            'type': 'url',
                            'url': url,
                            'storage_key': storage_key,
                            'media_type': source.get('media_type')
                        }

                        # clean data
                        logging.info(f"Imagen procesada y subida: {url}")

                    except Exception as e:
                        logging.error(f"Fallo al subir imagen generada: {e}")

                        # Fallback: keep the base64 and signal the error
                        part['error'] = "Failed to upload image"


    def decode_response(self, response) -> dict:
        message = response.output_text
        decoded_response = {
            "status": False,
            "output_text": message,
            "answer": "",
            "additional_data": {},
            "answer_format": "",
            "error_message": "",
            "parsed_json": None,
        }

        if response.status != 'completed':
            decoded_response[
                'error_message'] = f'LLM ERROR {response.status}: no se completo tu pregunta, intenta de nuevo ...'
            return decoded_response

        if isinstance(message, dict):
            decoded_response["parsed_json"] = message
            if 'answer' not in message or not self._has_additional_data_key(message):
                decoded_response['error_message'] = 'El llm respondio un diccionario invalido: missing "answer" or "additional_data" key'
                return decoded_response

            additional_data = self._extract_additional_data_payload(message)
            decoded_response['status'] = True
            decoded_response['answer'] = message.get('answer', '')
            decoded_response['additional_data'] = additional_data
            decoded_response['answer_format'] = "dict"
            return decoded_response

        clean_message = re.sub(r'^\s*//.*$', '', message, flags=re.MULTILINE)

        if not ('```json' in clean_message or clean_message.strip().startswith('{')):
            additional_data, clean_answer = self._extract_embedded_additional_data_from_text(clean_message)
            decoded_response['status'] = True
            decoded_response['answer'] = clean_answer
            if additional_data is not None:
                decoded_response['additional_data'] = additional_data
            decoded_response['answer_format'] = "plaintext"
            return decoded_response

        try:
            # prepare the message for json load
            json_string = clean_message.strip()
            if json_string.startswith('```json'):
                json_string = json_string[7:]
            if json_string.endswith('```'):
                json_string = json_string[:-3]

            response_dict = json.loads(json_string.strip())
        except Exception as e:
            # --- ESTRATEGIA DE RESPALDO (FALLBACK) CON RESCATE DE DATOS ---
            decoded_response['error_message'] = f'Error decodificando JSON: {str(e)}'

            # Intenta rescatar el contenido de "answer" con una expresión regular más robusta.
            # Este patrón busca "answer": "..." y captura hasta que encuentra el campo de metadata.
            # re.DOTALL es crucial para que `.` coincida con los saltos de línea en el HTML.
            match = re.search(r'"answer"\s*:\s*"(.*?)"\s*,\s*"(?:additional_data|aditional_data)"', clean_message, re.DOTALL)

            if match:
                # ¡Éxito! Se encontró y extrajo el "answer".
                # Se limpia el contenido de escapes JSON para obtener el HTML puro.
                rescued_answer = match.group(1).replace('\\n', '\n').replace('\\"', '"')

                decoded_response['status'] = True
                decoded_response['answer'] = rescued_answer
                additional_data = self._extract_additional_data_from_jsonish_text(clean_message)
                if additional_data is not None:
                    decoded_response['additional_data'] = additional_data
                decoded_response['answer_format'] = "plaintext_fallback_rescued"
            else:
                # Si la regex no encuentra nada, usar el texto completo como último recurso.
                decoded_response['status'] = True
                decoded_response['answer'] = clean_message
                decoded_response['answer_format'] = "plaintext_fallback_full"
        else:
            # --- SOLO SE EJECUTA SI EL TRY FUE EXITOSO ---
            decoded_response["parsed_json"] = response_dict
            if 'answer' not in response_dict or not self._has_additional_data_key(response_dict):
                decoded_response['error_message'] = f'faltan las claves "answer" o "additional_data" en el JSON'

                # fallback
                decoded_response['status'] = True
                decoded_response['answer'] = str(response_dict)
                decoded_response['answer_format'] = "json_fallback"
            else:
                # El diccionario JSON es perfecto.
                additional_data = self._extract_additional_data_payload(response_dict)
                decoded_response['status'] = True
                decoded_response['answer'] = response_dict.get('answer', '')
                decoded_response['additional_data'] = additional_data
                decoded_response['answer_format'] = "json_string"

        return decoded_response

    @staticmethod
    def _has_additional_data_key(payload: dict) -> bool:
        return isinstance(payload, dict) and (
            "additional_data" in payload or "aditional_data" in payload
        )

    @staticmethod
    def _extract_additional_data_payload(payload: dict):
        if not isinstance(payload, dict):
            return {}
        value = (
            payload.get("additional_data")
            if "additional_data" in payload
            else payload.get("aditional_data", {})
        )
        return {} if value is None else value

    @staticmethod
    def _extract_additional_data_from_jsonish_text(text: str):
        if not isinstance(text, str) or not text.strip():
            return None

        match = re.search(r'"(?:additional_data|aditional_data)"\s*:', text)
        if not match:
            return None

        value_start = match.end()
        while value_start < len(text) and text[value_start].isspace():
            value_start += 1
        if value_start >= len(text):
            return None

        raw_value = llmClient._extract_jsonish_value(text, value_start)
        if raw_value is None:
            return None

        for loader in (json.loads, yaml.safe_load):
            try:
                parsed = loader(raw_value)
            except Exception:
                continue
            return {} if parsed is None else parsed

        return None

    @staticmethod
    def _extract_embedded_additional_data_from_text(text: str):
        if not isinstance(text, str) or not text.strip():
            return None, text

        for match in re.finditer(r'"(?:additional_data|aditional_data)"\s*:', text):
            object_start = text.rfind("{", 0, match.start())
            while object_start != -1:
                raw_object = llmClient._extract_jsonish_value(text, object_start)
                if raw_object:
                    for loader in (json.loads, yaml.safe_load):
                        try:
                            parsed = loader(raw_object)
                        except Exception:
                            continue
                        if llmClient._has_additional_data_key(parsed):
                            additional_data = llmClient._extract_additional_data_payload(parsed)
                            clean_text = (text[:object_start] + text[object_start + len(raw_object):]).strip()
                            return additional_data, clean_text

                object_start = text.rfind("{", 0, object_start)

        return None, text

    @staticmethod
    def _extract_jsonish_value(text: str, start: int) -> str | None:
        opener = text[start]
        matching = {"{": "}", "[": "]"}
        if opener in matching:
            stack = [matching[opener]]
            quote = None
            escaped = False

            for pos in range(start + 1, len(text)):
                char = text[pos]
                if quote:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                    continue

                if char in {"'", '"'}:
                    quote = char
                    continue

                if char in matching:
                    stack.append(matching[char])
                    continue

                if stack and char == stack[-1]:
                    stack.pop()
                    if not stack:
                        return text[start:pos + 1].strip()

            return None

        if opener in {"'", '"'}:
            quote = opener
            escaped = False
            for pos in range(start + 1, len(text)):
                char = text[pos]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    return text[start:pos + 1].strip()
            return None

        value_end = start
        while value_end < len(text) and text[value_end] not in {",", "}", "\n"}:
            value_end += 1

        return text[start:value_end].strip() or None

    def _apply_response_contract(self, decoded_response: dict, response_contract: Optional[Dict[str, Any]]) -> dict:
        if not isinstance(decoded_response, dict):
            return decoded_response

        decoded_response.setdefault("structured_output", None)
        decoded_response.setdefault("schema_valid", None)
        decoded_response.setdefault("schema_errors", [])
        decoded_response.setdefault("schema_mode", None)
        decoded_response.setdefault("schema_applied", False)

        if not isinstance(response_contract, dict):
            return self._apply_legacy_structured_fallback(decoded_response)

        schema = response_contract.get("schema")
        if not isinstance(schema, dict):
            return self._apply_legacy_structured_fallback(decoded_response)

        schema_mode = str(response_contract.get("schema_mode") or "best_effort").strip().lower()
        response_mode = str(response_contract.get("response_mode") or "chat_compatible").strip().lower()
        provider = str(response_contract.get("provider") or "").strip().lower()
        allow_additional_property_repair = provider in {"deepseek", "openai_compatible"}
        candidates: list[Any] = []
        seen: set[str] = set()

        def _add_candidate(value: Any):
            if value is None:
                return
            try:
                signature = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
            except Exception:
                signature = str(value)
            if signature in seen:
                return
            seen.add(signature)
            candidates.append(value)

        parsed_json = decoded_response.get("parsed_json")
        _add_candidate(parsed_json)

        if isinstance(parsed_json, dict):
            _add_candidate(parsed_json.get("answer"))
            _add_candidate(self._extract_additional_data_payload(parsed_json))

        _add_candidate(decoded_response.get("additional_data"))
        _add_candidate(decoded_response.get("answer"))
        _add_candidate(decoded_response.get("output_text"))

        evaluations = [
            StructuredOutputService.evaluate_output(raw_output=candidate, schema=schema)
            for candidate in candidates
        ]
        repaired_evaluations = []
        if allow_additional_property_repair:
            repaired_evaluations = [
                StructuredOutputService.evaluate_output(
                    raw_output=candidate,
                    schema=schema,
                    drop_additional_properties=True,
                )
                for candidate in candidates
            ]

        fallback_evaluations = [
            StructuredOutputService.evaluate_output(
                raw_output=decoded_response.get("output_text"),
                schema=schema,
            )
        ]
        if allow_additional_property_repair:
            fallback_evaluations.append(
                StructuredOutputService.evaluate_output(
                    raw_output=decoded_response.get("output_text"),
                    schema=schema,
                    drop_additional_properties=True,
                )
            )

        evaluation = next(
            (
                item
                for item in (evaluations + repaired_evaluations + fallback_evaluations)
                if item.get("schema_valid")
            ),
            (
                evaluations[0]
                if evaluations
                else repaired_evaluations[0]
                if repaired_evaluations
                else fallback_evaluations[0]
            ),
        )

        decoded_response["schema_applied"] = bool(evaluation.get("schema_present"))
        decoded_response["schema_valid"] = bool(evaluation.get("schema_valid"))
        decoded_response["schema_errors"] = evaluation.get("errors") or []
        decoded_response["schema_mode"] = schema_mode

        if not decoded_response["schema_valid"]:
            if schema_mode == "strict":
                raise IAToolkitException(
                    IAToolkitException.ErrorType.LLM_ERROR,
                    f"The response does not match the configured output schema: {'; '.join(decoded_response['schema_errors'])}",
                )
            return decoded_response

        structured_output = evaluation.get("structured_output")
        decoded_response["structured_output"] = structured_output
        decoded_response["status"] = True
        decoded_response["error_message"] = ""

        if response_mode == "structured_only":
            decoded_response["answer"] = ""
            decoded_response["answer_format"] = "structured_only"
            return decoded_response

        if not decoded_response.get("answer"):
            decoded_response["answer"] = StructuredOutputService.render_structured_output_as_html(structured_output)
            decoded_response["answer_format"] = "structured_fallback_html"

        return decoded_response

    def _apply_legacy_structured_fallback(self, decoded_response: dict) -> dict:
        """
        Compatibility fallback:
        if no schema contract was applied, expose additional_data as structured_output when present.
        """
        if not isinstance(decoded_response, dict):
            return decoded_response

        decoded_response.setdefault("structured_output", None)
        decoded_response.setdefault("schema_valid", None)
        decoded_response.setdefault("schema_errors", [])
        decoded_response.setdefault("schema_mode", None)
        decoded_response.setdefault("schema_applied", False)

        if decoded_response.get("structured_output") is not None:
            return decoded_response

        additional_data = self._extract_additional_data_payload(decoded_response)
        if isinstance(additional_data, (dict, list)):
            if isinstance(additional_data, dict) and not additional_data:
                return decoded_response
            if isinstance(additional_data, list) and len(additional_data) == 0:
                return decoded_response
            decoded_response["structured_output"] = additional_data

        return decoded_response

    def serialize_response(self, response, decoded_response):
        response_dict = {
            "format": decoded_response.get('answer_format', ''),
            "error_message": decoded_response.get('error_message', ''),
            "output": decoded_response.get('output_text', ''),
            "id": response.id,
            "model": response.model,
            "status": response.status,
            "additional_data": self._extract_additional_data_payload(decoded_response),
            "structured_output": decoded_response.get("structured_output"),
            "schema_valid": decoded_response.get("schema_valid"),
            "schema_errors": decoded_response.get("schema_errors", []),
            "schema_mode": decoded_response.get("schema_mode"),
            "schema_applied": decoded_response.get("schema_applied", False),
        }
        return response_dict

    def get_stats(self, response):
        stats_dict = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens
        }
        return stats_dict

    def add_stats(self, stats1: dict, stats2: dict) -> dict:
        stats_dict = {
            "model": stats1.get('model', ''),
            "input_tokens": (stats1.get('input_tokens') or 0) + (stats2.get('input_tokens') or 0),
            "output_tokens": (stats1.get('output_tokens') or 0) + (stats2.get('output_tokens') or 0),
            "total_tokens": (stats1.get('total_tokens') or 0) + (stats2.get('total_tokens') or 0),
        }
        return stats_dict


    def _create_sql_retry_prompt(self, function_name: str, sql_query: str, db_error: str) -> str:
        return f"""
        ## ERROR DE EJECUCIÓN DE HERRAMIENTA

        **Estado:** Fallido
        **Herramienta:** `{function_name}`

        La ejecución de la consulta SQL falló.

        **Error específico de la base de datos:**
        {db_error}
        **Consulta SQL que causó el error:**
        sql {sql_query}

        **INSTRUCCIÓN OBLIGATORIA:**
        1.  Analiza el error y corrige la sintaxis de la consulta SQL anterior.
        2.  Llama a la herramienta `{function_name}` **OTRA VEZ**, inmediatamente, con la consulta corregida.
        3.  **NO** respondas al usuario con este mensaje de error. Tu ÚNICA acción debe ser volver a llamar a la herramienta con la solución.
        """

    def format_answer(self, answer: str, execution_metadata: Optional[Dict[str, Any]] = None):
        delivery_channel = str((execution_metadata or {}).get("delivery_channel") or "").strip().lower()
        if delivery_channel == "whatsapp":
            return self.format_plaintext(answer)
        return self.format_html(answer)

    def format_html(self, answer: str):
        if not answer:
            return ""

        # Heurística simple: si contiene tags, lo tratamos como HTML ya renderizable
        if re.search(r"</?[a-zA-Z][\s\S]*>", answer):
            return answer.replace("\n", "")

        html_answer = markdown2.markdown(answer).replace("\n", "")
        return html_answer

    def format_plaintext(self, answer: str):
        if not answer:
            return ""

        normalized = str(answer)
        normalized = re.sub(r"<\s*br\s*/?\s*>", "\n", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"</\s*p\s*>", "\n\n", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"</\s*div\s*>", "\n", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"<\s*li\s*>", "- ", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"</\s*li\s*>", "\n", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"<[^>]+>", "", normalized)
        normalized = unescape(normalized)
        normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+\n", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def count_tokens(self, text, history = []):
        content = (text or "") + json.dumps(history)

        try:
            if self.encoding is None:
                try:
                    # Preferred encoder for GPT-4o family.
                    self.encoding = tiktoken.encoding_for_model("gpt-4o")
                except KeyError as model_error:
                    # tiktoken raises KeyError when it can't map the model name to a
                    # tokeniser (e.g. a newer model it doesn't recognize yet) - that's
                    # the only failure this fallback is meant to handle. A broader
                    # `except Exception` here would also swallow unrelated signals like
                    # RQ's injected JobTimeoutException if a job timeout happens to fire
                    # mid-call, silently absorbing the timeout instead of letting the
                    # task fail/retry.
                    logging.warning(f"tiktoken encoding_for_model failed, fallback to cl100k_base: {model_error}")
                    # Local fallback for startup/offline compatibility.
                    self.encoding = tiktoken.get_encoding("cl100k_base")

            tokens = self.encoding.encode(content)
            return len(tokens)
        except Exception as e:
            if type(e).__module__ == "rq.timeouts" and type(e).__name__ == "JobTimeoutException":
                # Must propagate, not be absorbed by the approximation fallback below:
                # this is RQ's job-timeout signal (checked by name/module rather than
                # imported, since core iatoolkit has no dependency on rq). RQ's
                # SIGALRM-based timeout only fires once, so swallowing it here would
                # let the task keep running for the rest of its execution with no
                # timeout protection at all instead of properly failing/retrying.
                raise
            # Safe approximation to keep request flow alive.
            logging.warning(f"Token counting fallback in use: {e}")
            return max(1, len(content) // 4)
