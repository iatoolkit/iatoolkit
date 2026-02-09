# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.knowledge_base_service import KnowledgeBaseService
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.services.auth_service import AuthService
from iatoolkit.common.util import Utility
from iatoolkit.services.i18n_service import I18nService
from flask import request, jsonify, send_file
from flask.views import MethodView
from injector import inject
from datetime import datetime
import io
import mimetypes
import json

class RagApiView(MethodView):
    """
    API Endpoints for managing the RAG Knowledge Base.
    """

    @inject
    def __init__(self,
                 knowledge_base_service: KnowledgeBaseService,
                 visual_kb_service: VisualKnowledgeBaseService,
                 auth_service: AuthService,
                 i18n_service: I18nService,
                 utility: Utility):
        self.knowledge_base_service = knowledge_base_service
        self.visual_kb_service = visual_kb_service
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

    def search_text(self, company_short_name):
        """
        POST /api/rag/<company_short_name>/search/text
        Direct vector text search (no LLM orchestration).
        """
        try:
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            data = request.get_json() or {}
            query = data.get("query")
            if not query:
                return self._bad_request("query is required", error_code="INVALID_REQUEST")

            collection, n_results, metadata_filter = self._parse_common_search_params(data)

            chunks = self.knowledge_base_service.search(
                company_short_name=company_short_name,
                query=query,
                n_results=n_results,
                collection=collection,
                metadata_filter=metadata_filter,
            )
            normalized_results = self._normalize_text_results(chunks)

            return jsonify({
                "result": "success",
                "mode": "text",
                "count": len(normalized_results),
                "collection": collection,
                "results": normalized_results,
                "serialized_context": self._serialize_text_results(normalized_results),
            }), 200
        except ValueError as e:
            return self._bad_request(str(e), error_code="INVALID_REQUEST")
        except IAToolkitException as e:
            return jsonify({"result": "error", "error_code": "INTERNAL_ERROR", "message": e.message}), e.http_code
        except Exception as e:
            return jsonify({"result": "error", "error_code": "INTERNAL_ERROR", "message": str(e)}), 500

    def search_image(self, company_short_name):
        """
        POST /api/rag/<company_short_name>/search/image
        Direct vector image search from text query (no LLM orchestration).
        """
        try:
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            data = request.get_json() or {}
            query = data.get("query")
            if not query:
                return self._bad_request("query is required", error_code="INVALID_REQUEST")

            collection, n_results, metadata_filter = self._parse_common_search_params(data)

            results = self.visual_kb_service.search_images(
                company_short_name=company_short_name,
                query=query,
                n_results=n_results,
                collection=collection,
                metadata_filter=metadata_filter,
            )
            normalized_results = self._normalize_visual_results(results)

            return jsonify({
                "result": "success",
                "mode": "image",
                "count": len(normalized_results),
                "collection": collection,
                "results": normalized_results,
                "serialized_context": self._serialize_visual_results(normalized_results),
            }), 200
        except ValueError as e:
            return self._bad_request(str(e), error_code="INVALID_REQUEST")
        except IAToolkitException as e:
            return jsonify({"result": "error", "error_code": "INTERNAL_ERROR", "message": e.message}), e.http_code
        except Exception as e:
            return jsonify({"result": "error", "error_code": "INTERNAL_ERROR", "message": str(e)}), 500

    def search_visual(self, company_short_name):
        """
        POST /api/rag/<company_short_name>/search/visual
        Direct visual search from one image (no LLM orchestration).
        """
        try:
            auth_result = self.auth_service.verify()
            if not auth_result.get("success"):
                return jsonify(auth_result), auth_result.get("status_code")

            data = request.get_json() or {}
            image_base64 = data.get("image_base64")
            if not image_base64:
                return self._bad_request("image_base64 is required", error_code="INVALID_REQUEST")

            collection, n_results, metadata_filter = self._parse_common_search_params(data)
            image_bytes = self.utility.normalize_base64_payload(image_base64)
            if not image_bytes:
                return self._bad_request("image_base64 is empty or invalid", error_code="INVALID_REQUEST")

            results = self.visual_kb_service.search_similar_images(
                company_short_name=company_short_name,
                image_content=image_bytes,
                n_results=n_results,
                collection=collection,
                metadata_filter=metadata_filter,
            )
            normalized_results = self._normalize_visual_results(results)

            return jsonify({
                "result": "success",
                "mode": "visual",
                "count": len(normalized_results),
                "collection": collection,
                "results": normalized_results,
                "serialized_context": self._serialize_visual_results(normalized_results),
            }), 200
        except ValueError as e:
            return self._bad_request(str(e), error_code="INVALID_REQUEST")
        except IAToolkitException as e:
            return jsonify({"result": "error", "error_code": "INTERNAL_ERROR", "message": e.message}), e.http_code
        except Exception as e:
            return jsonify({"result": "error", "error_code": "INTERNAL_ERROR", "message": str(e)}), 500

    @staticmethod
    def _to_markdown_link(label: str | None, url: str | None) -> str:
        text = label or "unknown"
        if not url:
            return text
        return f"[{text}]({url})"

    def _parse_common_search_params(self, data: dict) -> tuple[str | None, int, dict | list | None]:
        collection = data.get("collection")

        raw_n_results = data.get("n_results", data.get("k", 5))
        try:
            n_results = int(raw_n_results)
        except (ValueError, TypeError):
            raise ValueError("n_results must be an integer")

        if n_results < 1 or n_results > 20:
            raise ValueError("n_results must be between 1 and 20")

        metadata_filter = data.get("metadata_filter")
        if metadata_filter is not None and not isinstance(metadata_filter, (dict, list)):
            raise ValueError("metadata_filter must be a dictionary or a list of {key,value}")

        return collection, n_results, metadata_filter

    def _normalize_text_results(self, chunks: list[dict]) -> list[dict]:
        normalized = []
        for item in chunks or []:
            filename = item.get("filename")
            document_url = item.get("url")
            normalized.append({
                "chunk_id": item.get("id"),
                "document_id": item.get("document_id"),
                "filename": filename,
                "document_url": document_url,
                "filename_link": self._to_markdown_link(filename, document_url),
                "text": item.get("text"),
                "chunk_meta": item.get("chunk_meta") or {},
                "document_meta": item.get("meta") or {},
            })
        return normalized

    def _normalize_visual_results(self, results: list[dict]) -> list[dict]:
        normalized = []
        for item in results or []:
            filename = item.get("filename")
            document_url = item.get("document_url")
            image_url = item.get("image_url") or item.get("url")
            normalized.append({
                "document_id": item.get("id") or item.get("document_id"),
                "image_id": item.get("image_id"),
                "filename": filename,
                "document_url": document_url,
                "filename_link": self._to_markdown_link(filename, document_url),
                "image_url": image_url,
                "score": item.get("score"),
                "page": item.get("page"),
                "image_index": item.get("image_index"),
                "meta": item.get("meta") or {},
                "document_meta": item.get("document_meta") or {},
            })
        return normalized

    @staticmethod
    def _serialize_text_results(results: list[dict]) -> str:
        if not results:
            return "No text results found."

        lines = []
        for index, item in enumerate(results, start=1):
            header = {
                "index": index,
                "filename": item.get("filename_link") or item.get("filename"),
                "document_id": item.get("document_id"),
                "chunk_id": item.get("chunk_id"),
                "source_type": (item.get("chunk_meta") or {}).get("source_type"),
                "page": (item.get("chunk_meta") or {}).get("page") or (item.get("chunk_meta") or {}).get("page_start"),
            }
            lines.append(json.dumps(header, ensure_ascii=False))
            if item.get("text"):
                lines.append(item.get("text"))
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _serialize_visual_results(results: list[dict]) -> str:
        if not results:
            return "No image results found."

        lines = []
        for index, item in enumerate(results, start=1):
            lines.append(
                f"[image {index}] filename={item.get('filename_link') or item.get('filename')} "
                f"score={item.get('score')} page={item.get('page')} image_index={item.get('image_index')} "
                f"image_url={item.get('image_url')} document_url={item.get('document_url')}"
            )
            meta = item.get("meta") or {}
            doc_meta = item.get("document_meta") or {}
            if meta:
                lines.append(f"meta={json.dumps(meta, ensure_ascii=False, default=str)}")
            if doc_meta:
                lines.append(f"document_meta={json.dumps(doc_meta, ensure_ascii=False, default=str)}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _bad_request(message: str, error_code: str = "INVALID_REQUEST"):
        return jsonify({
            "result": "error",
            "error_code": error_code,
            "message": message
        }), 400
