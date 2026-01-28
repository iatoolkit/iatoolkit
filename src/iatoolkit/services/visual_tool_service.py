# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from injector import inject
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

    def image_search(self, company_short_name: str, query: str, collection: str = None, request_images: list = []):
        """
        Handle the search for text to image (iat_image_search).
        """
        results = self.visual_kb_service.search_images(
            company_short_name=company_short_name,
            query=query,
            collection=collection
        )
        return self._format_response(results, self.i18n_service.t('rag.visual.found_images'))

    def visual_search(self, company_short_name: str, request_images: list, n_results: int = 5, image_index: int = 0, collection: str = None, ):
        """
        Handle the visual search (image to image) (iat_visual_search).
        Receive the full list of images from the request, decode and call the KB service.
        """
        if not request_images:
            return self.i18n_service.t('rag.visual.no_images_attached')

        # validate image index
        if image_index < 0 or image_index >= len(request_images):
            return self.i18n_service.t('rag.visual.invalid_index', index=image_index, total=len(request_images))

        try:
            target_image = request_images[image_index]
            base64_content = target_image.get('base64')

            # decode the image
            image_bytes = self.util.normalize_base64_payload(base64_content)

            results = self.visual_kb_service.search_similar_images(
                company_short_name=company_short_name,
                image_content=image_bytes,
                n_results=n_results,
                collection=collection
            )

            return self._format_response(results, self.i18n_service.t('rag.visual.similar_images_found'))

        except Exception as e:
            return self.i18n_service.t('rag.visual.processing_error', error=str(e))


    def _format_response(self, results: list, title: str) -> str:
        """Helper interno para formatear la respuesta HTML consistente."""
        if not results:
            return self.i18n_service.t('rag.visual.no_results_for', title=title)

        response = f"<p><strong>{title}:</strong></p><ul>"

        for item in results:
            filename = item.get("filename", "imagen")
            score = item.get("score", 0.0)
            url = item.get("url")

            response += f"<li><strong>{filename}</strong> (Score: {score:.2f})"
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