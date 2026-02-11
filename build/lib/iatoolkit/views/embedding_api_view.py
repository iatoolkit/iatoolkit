# iatoolkit/views/embedding_api_view.py
# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import request, jsonify
from flask.views import MethodView
from iatoolkit.services.embedding_service import EmbeddingService
from iatoolkit.services.auth_service import AuthService
from injector import inject
import logging

class EmbeddingApiView(MethodView):
    """
    Handles API requests to generate an embedding for a given text.
    Authentication is based on the active Flask session.
    """

    @inject
    def __init__(self,
                 auth_service: AuthService,
                 embedding_service: EmbeddingService):
        self.auth_service = auth_service
        self.embedding_service = embedding_service

    def post(self, company_short_name: str):
        """
        Generates an embedding for the text provided in the request body.
        Expects a JSON payload with a "text" key.
        """
        try:
            # 1. Authenticate the user from the current session
            auth_result = self.auth_service.verify(anonymous=True)
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code", 401)

            # 2. Validate incoming request data
            if not request.is_json:
                return jsonify({"error": "Request must be JSON"}), 400

            data = request.get_json()
            text = data.get('text')

            if not text:
                return jsonify({"error": "The 'text' key is required."}), 400

            # 3. Call the embedding service, now passing the company_short_name
            embedding_b64 = self.embedding_service.embed_text(
                company_short_name=company_short_name,
                text=text,
                to_base64=True
            )

            model_name = self.embedding_service.get_model_name(company_short_name)
            response = {
                "embedding": embedding_b64,
                "model": model_name
            }
            return jsonify(response), 200

        except Exception as e:
            logging.exception(f"Unexpected error in EmbeddingApiView: {e}")
            # Return a generic error message to the client
            return jsonify({"error": "An internal error occurred while generating the embedding."}), 500
