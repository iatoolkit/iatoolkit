# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
import json
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.common.util import Utility
from iatoolkit.services.i18n_service import I18nService


class VisualToolService:
    @inject
    def __init__(self,
                 visual_kb_service: VisualKnowledgeBaseService,
                 util: Utility,
                 i18n_service: I18nService):
        self.visual_kb_service = visual_kb_service
        self.util = util
        self.i18n_service = i18n_service

    def image_search(self,
                     company_short_name: str,
                     query: str,
                     collection: str = None,
                     metadata_filter: dict | None = None,
                     request_images: list | None = None,
                     n_results: int = 5,
                     structured_output: bool = False):
        """
        Handle the search for text to image (iat_image_search).
        """
        results = self.visual_kb_service.search_images(
            company_short_name=company_short_name,
            query=query,
            n_results=n_results,
            collection=collection,
            metadata_filter=metadata_filter,
        )
        title = self.i18n_service.t('rag.visual.found_images')
        if structured_output:
            return self._build_visual_payload(results, title)
        return self._format_response(results, title)

    def visual_search(self,
                      company_short_name: str,
                      request_images: list,
                      n_results: int = 5,
                      image_index: int = 0,
                      collection: str = None,
                      metadata_filter: dict | None = None,
                      structured_output: bool = False):
        """
        Handle the visual search (image to image) (iat_visual_search).
        Receive the full list of images from the request, decode and call the KB service.
        """
        if not request_images:
            message = self.i18n_service.t('rag.visual.no_images_attached')
            if structured_output:
                return {
                    "status": "error",
                    "message": message,
                    "count": 0,
                    "results": [],
                    "serialized_context": message,
                    "summary_html": "",
                }
            return message

        # validate image index
        if image_index < 0 or image_index >= len(request_images):
            message = self.i18n_service.t('rag.visual.invalid_index', index=image_index, total=len(request_images))
            if structured_output:
                return {
                    "status": "error",
                    "message": message,
                    "count": 0,
                    "results": [],
                    "serialized_context": message,
                    "summary_html": "",
                }
            return message

        try:
            target_image = request_images[image_index]
            base64_content = target_image.get('base64')

            # decode the image
            image_bytes = self.util.normalize_base64_payload(base64_content)

            results = self.visual_kb_service.search_similar_images(
                company_short_name=company_short_name,
                image_content=image_bytes,
                n_results=n_results,
                collection=collection,
                metadata_filter=metadata_filter,
            )

            title = self.i18n_service.t('rag.visual.similar_images_found')
            if structured_output:
                return self._build_visual_payload(results, title)
            return self._format_response(results, title)

        except Exception as e:
            message = self.i18n_service.t('rag.visual.processing_error', error=str(e))
            if structured_output:
                return {
                    "status": "error",
                    "message": message,
                    "count": 0,
                    "results": [],
                    "serialized_context": message,
                    "summary_html": "",
                }
            return message


    def _format_response(self, results: list, title: str) -> str:
        """Helper interno para formatear la respuesta HTML consistente."""
        if not results:
            return self.i18n_service.t('rag.visual.no_results_for', title=title)

        response = f"<p><strong>{title}:</strong></p><ul>"

        for item in results:
            filename = item.get("filename", "imagen")
            score = item.get("score", 0.0)
            url = item.get("url")
            document_url = item.get("document_url")
            page = item.get("page")
            image_index = item.get("image_index")
            image_meta = item.get("meta") or {}
            doc_meta = item.get("document_meta") or {}
            caption_text = image_meta.get("caption_text")
            filename_html = filename
            if document_url:
                filename_html = (
                    f'<a href="{document_url}" target="_blank" rel="noopener noreferrer">{filename}</a>'
                )

            response += f"<li><strong>{filename_html}</strong> (Score: {score:.2f})"
            if page is not None:
                response += f"<br><small>Page: {page}</small>"
            if image_index is not None:
                response += f"<br><small>Image index: {image_index}</small>"
            if caption_text:
                response += f"<br><small>Caption: {caption_text}</small>"

            if image_meta:
                response += (
                    f"<br><details><summary>Image metadata</summary><pre>{self._safe_json(image_meta)}</pre></details>"
                )
            if doc_meta:
                response += (
                    f"<br><details><summary>Document metadata</summary><pre>{self._safe_json(doc_meta)}</pre></details>"
                )

            if url:
                view_text = self.i18n_service.t('rag.visual.view_image')
                response += (
                    f' — <a href="{url}" target="_blank" rel="noopener noreferrer">{view_text}</a>'
                    f'<br><img src="{url}" alt="{filename}" style="max-width: 300px; height: auto; border-radius: 5px; margin-top: 5px;" />'
                )
            else:
                unavailable_text = self.i18n_service.t('rag.visual.image_unavailable')
                response += f"<br><em>({unavailable_text})</em>"
            response += "</li>"

        response += "</ul>"
        return response

    def _build_visual_payload(self, results: list, title: str) -> dict:
        return {
            "status": "success",
            "title": title,
            "count": len(results),
            "results": results,
            "serialized_context": self._serialize_visual_results(results),
            "summary_html": self._format_response(results, title),
        }

    @staticmethod
    def _serialize_visual_results(results: list) -> str:
        if not results:
            return "No image results found."

        lines = []
        for index, item in enumerate(results, start=1):
            meta = item.get("meta") or {}
            doc_meta = item.get("document_meta") or {}
            filename = item.get("filename")
            document_url = item.get("document_url")
            filename_link = VisualToolService._to_markdown_link(filename, document_url)
            lines.append(
                f"[image {index}] filename={filename_link} score={item.get('score')} "
                f"page={item.get('page')} image_index={item.get('image_index')} "
                f"url={item.get('url')} document_url={document_url}"
            )
            if meta:
                lines.append(f"meta={json.dumps(meta, ensure_ascii=False, default=str)}")
            if doc_meta:
                lines.append(f"document_meta={json.dumps(doc_meta, ensure_ascii=False, default=str)}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _to_markdown_link(label: str | None, url: str | None) -> str:
        text = label or "imagen"
        if not url:
            return text
        return f"[{text}]({url})"

    @staticmethod
    def _safe_json(value: dict) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return str(value)
