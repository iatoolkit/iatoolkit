# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import json
import logging
import threading

from flask import Response, copy_current_request_context, jsonify, request
from flask.views import MethodView
from injector import inject

from iatoolkit.services.auth_service import AuthService
from iatoolkit.services.chat_stream import QueueEventSink
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.services.query_service import QueryService
from iatoolkit.views.llmquery_api_view import build_llm_query_kwargs, compact_llm_query_result


class LLMQueryStreamApiView(MethodView):
    """The chat web's live turn (BL-023): the same request as `/api/llm_query`,
    answered as Server-Sent Events.

    Only for a signed-in person in the chat. An API key gets the complete
    response from `/api/llm_query`, as always.

    The turn runs in its own thread (a greenlet under gevent) and reports on a
    queue; this response only relays the queue, with a heartbeat while nothing
    happens so proxies keep the connection open. The last event is `final`
    (the very dict `/api/llm_query` returns) or `error`. When the browser goes
    away the turn is told to stop.
    """

    HEARTBEAT_SECONDS = 15

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 query_service: QueryService,
                 config_service: ConfigurationService,
                 i18n_service: I18nService):
        self.auth_service = auth_service
        self.query_service = query_service
        self.config_service = config_service
        self.i18n_service = i18n_service

    def post(self, company_short_name: str):
        try:
            auth_result = self.auth_service.verify_for_company(company_short_name)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")
            if auth_result.get("auth_type") == "api_key":
                return jsonify({
                    "error": True,
                    "error_message": "Streaming is only available in the chat; use /api/llm_query.",
                }), 403
            if not self.config_service.is_chat_streaming_enabled(company_short_name):
                return jsonify({"error": True, "error_message": "Chat streaming is not enabled."}), 404

            data = request.get_json(silent=True)
            if not data:
                return jsonify({"error": "Invalid JSON body"}), 400

            user_identifier = auth_result.get('user_identifier')
            query_kwargs = build_llm_query_kwargs(data)
        except Exception as e:
            logging.exception(f"Unexpected error: {e}")
            return jsonify({"error": True, "error_message": self.i18n_service.t('errors.general.unexpected_error')}), 500

        sink = QueueEventSink()
        unexpected_error_message = self.i18n_service.t('errors.general.unexpected_error')

        @copy_current_request_context
        def run_turn():
            try:
                result = self.query_service.llm_query(
                    company_short_name=company_short_name,
                    user_identifier=user_identifier,
                    event_sink=sink,
                    **query_kwargs,
                )
                if 'error' in result:
                    sink.emit("error", {
                        "error_message": result.get("error_message") or unexpected_error_message,
                    })
                else:
                    sink.emit("final", compact_llm_query_result(result))
            except Exception as e:
                logging.exception(f"chat stream: turn failed: {e}")
                sink.emit("error", {"error_message": unexpected_error_message})
            finally:
                sink.close()

        threading.Thread(target=run_turn, name="chat-stream-turn", daemon=True).start()

        return Response(
            self._relay(sink),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                # nginx-style proxies otherwise hold the events until the end.
                "X-Accel-Buffering": "no",
            },
        )

    def _relay(self, sink: QueueEventSink):
        try:
            # Sent at once, so the browser's fetch resolves before the first model call.
            yield ": stream open\n\n"
            for item in sink.events(heartbeat_seconds=self.HEARTBEAT_SECONDS):
                if item is None:
                    yield ": ping\n\n"
                    continue
                event, payload = item
                yield format_sse(event, payload)
        except GeneratorExit:
            # The browser went away (stop button, closed tab): stop the turn.
            sink.cancel()
            raise


def format_sse(event: str, payload) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"
