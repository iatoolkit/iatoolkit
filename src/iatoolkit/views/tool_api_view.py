# src/iatoolkit/views/tools_api_view.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from injector import inject
from iatoolkit.services.auth_service import AuthService
from iatoolkit.repositories.profile_repo import ProfileRepo
from iatoolkit.services.tool_service import ToolService
from iatoolkit.services.dispatcher_service import Dispatcher
from iatoolkit.repositories.models import Tool
from iatoolkit.common.exceptions import IAToolkitException
import logging

class ToolApiView(MethodView):
    """
    API for managing AI Tools (CRUD).
    Allows listing, creating, updating, and deleting tools via the GUI.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 profile_repo: ProfileRepo,
                 tool_service: ToolService,
                 dispatcher: Dispatcher):
        self.auth_service = auth_service
        self.profile_repo = profile_repo
        self.tool_service = tool_service
        self.dispatcher = dispatcher

    def dispatch_request(self, *args, **kwargs):
        """
        Allows custom action mapping from routes using defaults={'action': '...'}.
        """
        action = kwargs.pop('action', None)
        if action:
            method = getattr(self, action, None)
            if method:
                return method(*args, **kwargs)
            raise AttributeError(f"Action '{action}' not found in ToolApiView")
        return super().dispatch_request(*args, **kwargs)

    def get(self, company_short_name: str, tool_id: int = None):
        """
        GET /<company>/api/tools       -> List all tools
        GET /<company>/api/tools/<id>  -> Get specific tool details
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        try:
            if tool_id:
                tool = self.tool_service.get_tool(company_short_name, tool_id)
                return jsonify(tool), 200
            else:
                tools = self.tool_service.list_tools(company_short_name)
                return jsonify(tools), 200

        except IAToolkitException as e:
            return self._handle_iat_exception(e)
        except Exception as e:
            logging.exception(f"Tool API Error (GET): {e}")
            return jsonify({"error": "Internal server error"}), 500

    def post(self, company_short_name: str):
        """
        POST /<company>/api/tools -> Create a new tool
        Body: { "name": "...", "description": "...", "tool_type": "...", ... }
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        try:
            data = request.get_json() or {}
            new_tool = self.tool_service.create_tool(company_short_name, data)
            return jsonify(new_tool), 201

        except IAToolkitException as e:
            return self._handle_iat_exception(e)
        except Exception as e:
            logging.exception(f"Tool API Error (POST): {e}")
            return jsonify({"error": "Internal server error"}), 500

    def put(self, company_short_name: str, tool_id: int):
        """
        PUT /<company>/api/tools/<id> -> Update an existing tool
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        try:
            data = request.get_json() or {}
            updated_tool = self.tool_service.update_tool(company_short_name, tool_id, data)
            return jsonify(updated_tool), 200

        except IAToolkitException as e:
            return self._handle_iat_exception(e)
        except Exception as e:
            logging.exception(f"Tool API Error (PUT): {e}")
            return jsonify({"error": "Internal server error"}), 500

    def delete(self, company_short_name: str, tool_id: int):
        """
        DELETE /<company>/api/tools/<id> -> Delete a tool
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        try:
            self.tool_service.delete_tool(company_short_name, tool_id)
            return jsonify({"status": "success"}), 200

        except IAToolkitException as e:
            return self._handle_iat_exception(e)
        except Exception as e:
            logging.exception(f"Tool API Error (DELETE): {e}")
            return jsonify({"error": "Internal server error"}), 500

    def execute(self, company_short_name: str):
        """
        POST /<company>/api/tools/execute -> Execute a NATIVE tool by name.
        Body:
        {
            "tool_name": "identity_risk",
            "kwargs": {...}
        }
        """
        auth_result = self.auth_service.verify()
        if not auth_result.get("success"):
            return jsonify(auth_result), auth_result.get("status_code", 401)

        try:
            data = request.get_json() or {}
            tool_name = data.get("tool_name") or data.get("name")
            if not tool_name:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.MISSING_PARAMETER,
                    "tool_name is required"
                )

            call_kwargs = data.get("kwargs", data.get("arguments", data.get("params", {})))
            if not isinstance(call_kwargs, dict):
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_PARAMETER,
                    "kwargs must be a JSON object"
                )

            tool_def = self.tool_service.get_tool_definition(company_short_name, tool_name)
            if not tool_def:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.NOT_FOUND,
                    f"Tool '{tool_name}' not found"
                )

            if tool_def.tool_type != Tool.TYPE_NATIVE:
                raise IAToolkitException(
                    IAToolkitException.ErrorType.INVALID_OPERATION,
                    f"Tool '{tool_name}' is not NATIVE"
                )

            # Reuse dispatcher invocation for exact NATIVE execution path.
            result = self.dispatcher.dispatch(
                company_short_name=company_short_name,
                function_name=tool_name,
                **call_kwargs
            )

            return jsonify({
                "result": "success",
                "tool_name": tool_name,
                "data": result
            }), 200

        except IAToolkitException as e:
            return self._handle_iat_exception(e)
        except Exception as e:
            logging.exception(f"Tool API Error (EXECUTE): {e}")
            return jsonify({"error": "Internal server error"}), 500

    def _handle_iat_exception(self, e: IAToolkitException):
        """Helper to map IAToolkitExceptions to HTTP responses."""
        status_code = 500

        if e.error_type in [IAToolkitException.ErrorType.NOT_FOUND, IAToolkitException.ErrorType.INVALID_NAME]:
            status_code = 404
        elif e.error_type in [IAToolkitException.ErrorType.MISSING_PARAMETER, IAToolkitException.ErrorType.INVALID_PARAMETER]:
            status_code = 400
        elif e.error_type in [IAToolkitException.ErrorType.DUPLICATE_ENTRY, IAToolkitException.ErrorType.INVALID_OPERATION]:
            status_code = 409

        return jsonify({"error": str(e), "error_type": e.error_type.value}), status_code
