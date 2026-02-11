# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.common.util import Utility
from iatoolkit.services.i18n_service import I18nService
from flask import request, jsonify, send_file
from flask.views import MethodView
from injector import inject
from datetime import datetime
import io
import mimetypes

class RagApiView(MethodView):
    """
    API Endpoints for managing the RAG Knowledge Base.
    """

    @inject
    def __init__(self,
                 knowledge_base_service: KnowledgeBaseService,
                 auth_service: AuthService,
                 i18n_service: I18nService,
                 utility: Utility):
        self.knowledge_base_service = knowledge_base_service
        self.auth_service = auth_service
        self.utility = utility
        self.i18n_service = i18n_service

    def dispatch_request(self, *args, **kwargs):
        """
        Sobreescribimos el dispatch para soportar el mapeo de acciones personalizadas
        pasadas a través de 'defaults' en add_url_rule (ej: action='list_files').
        """
        action = kwargs.pop('action', None)
        if action:
            method = getattr(self, action, None)
            if method:
                return method(*args, **kwargs)
            else:
                raise AttributeError(self.i18n_service.t('rag.management.action_not_found', action=action))

        return super().dispatch_request(*args, **kwargs)

    def list_files(self, company_short_name):
        """
        POST /api/rag/<company_short_name>/files
        Returns a paginated list of documents based on filters provided in the JSON body.
        """
        try:
            # 1. Authenticate the user from the current session.
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            # 2. Parse Input
            data = request.get_json() or {}

            status = data.get('status', [])
            user_identifier = data.get('user_identifier')
            keyword = data.get('filename_keyword')
            from_date_str = data.get('from_date')
            to_date_str = data.get('to_date')
            collection = data.get('collection', '')
            limit = int(data.get('limit', 100))
            offset = int(data.get('offset', 0))

            from_date = datetime.fromisoformat(from_date_str) if from_date_str else None
            to_date = datetime.fromisoformat(to_date_str) if to_date_str else None

            # 3. Call Service
            documents = self.knowledge_base_service.list_documents(
                company_short_name=company_short_name,
                status=status,
                collection=collection,
                filename_keyword=keyword,
                user_identifier=user_identifier,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                offset=offset
            )

            # 4. Format Response
            response_list = []
            for doc in documents:
                response_list.append({
                    'id': doc.id,
                    'filename': doc.filename,
                    'user_identifier': doc.user_identifier,
                    'status': doc.status.value if hasattr(doc.status, 'value') else str(doc.status),
                    'created_at': doc.created_at.isoformat() if doc.created_at else None,
                    'metadata': doc.meta,
                    'error_message': doc.error_message,
                    'collection': doc.collection_type.name if doc.collection_type else None,
                })

            return jsonify({
                'result': 'success',
                'count': len(response_list),
                'documents': response_list
            }), 200

        except IAToolkitException as e:
            return jsonify({'result': 'error', 'message': e.message}), e.http_code
        except Exception as e:
            return jsonify({'result': 'error', 'message': str(e)}), 500

    def get_file_content(self, company_short_name, document_id):
        """
        GET /api/rag/<company_short_name>/files/<document_id>/content
        Streams the file content to the browser (inline view preferred).
        """
        try:
            # 1. Authenticate
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            # 2. Get content from service
            file_bytes, filename = self.knowledge_base_service.get_document_content(document_id)

            if not file_bytes:
                msg = self.i18n_service.t('rag.management.not_found')
                return jsonify({'result': 'error', 'message': msg}), 404

            # 3. Determine MIME type
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'application/octet-stream'

            # 4. Stream response
            return send_file(
                io.BytesIO(file_bytes),
                mimetype=mime_type,
                as_attachment=False,  # Inline view
                download_name=filename
            )

        except IAToolkitException as e:
            return jsonify({'result': 'error', 'message': e.message}), e.http_code
        except Exception as e:
            return jsonify({'result': 'error', 'message': str(e)}), 500

    def delete_file(self, company_short_name, document_id):
        """
        DELETE /api/rag/<company_short_name>/files/<document_id>
        Deletes a document and its vectors.
        """
        try:
            # 1. Authenticate
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            # 2. Call Service
            success = self.knowledge_base_service.delete_document(document_id)

            if success:
                msg = self.i18n_service.t('rag.management.delete_success')
                return jsonify({'result': 'success', 'message': msg}), 200
            else:
                msg = self.i18n_service.t('rag.management.not_found')
                return jsonify({'result': 'error', 'message': msg}), 404

        except IAToolkitException as e:
            return jsonify({'result': 'error', 'message': e.message}), e.http_code
        except Exception as e:
            return jsonify({'result': 'error', 'message': str(e)}), 500

    def search(self, company_short_name):
        """
        POST /api/rag/<company_short_name>/search
        Synchronous semantic search for the "Search Lab" UI.
        Returns detailed chunks with text and metadata using search_raw.
        """
        try:
            # 1. Authenticate
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            # 2. Parse Input
            data = request.get_json() or {}
            query = data.get('query')
            n_results = int(data.get('k', 5))
            collection = data.get('collection')
            metadata_filter = data.get('metadata_filter')

            if not query:
                msg = self.i18n_service.t('rag.search.query_required')
                return jsonify({'result': 'error', 'message': msg}), 400

            # 3. Call Service
            chunks = self.knowledge_base_service.search(
                company_short_name=company_short_name,
                query=query,
                n_results=n_results,
                collection=collection,
                metadata_filter=metadata_filter,
            )

            return jsonify({
                "result": "success",
                "chunks": chunks
            }), 200

        except IAToolkitException as e:
            return jsonify({'result': 'error', 'error_message': e.message}), 501
        except Exception as e:
            return jsonify({'result': 'error', 'error_message': str(e)}), 500