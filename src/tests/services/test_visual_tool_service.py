# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock
from iatoolkit.services.visual_tool_service import VisualToolService
from iatoolkit.services.visual_kb_service import VisualKnowledgeBaseService
from iatoolkit.services.i18n_service import I18nService
from iatoolkit.common.util import Utility

class TestVisualToolService:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_visual_kb_service = MagicMock(spec=VisualKnowledgeBaseService)
        self.mock_util = MagicMock(spec=Utility)
        self.mock_i18n_service = MagicMock(spec=I18nService)

        # Configurar un side_effect para t() que devuelva un string predecible para aserciones
        def mock_translate(key, **kwargs):
            if kwargs:
                # Simular formateo básico para verificar que pasan los kwargs
                params = ",".join([f"{k}={v}" for k, v in kwargs.items()])
                return f"translated[{key}|{params}]"
            return f"translated[{key}]"

        self.mock_i18n_service.t.side_effect = mock_translate

        self.service = VisualToolService(
            visual_kb_service=self.mock_visual_kb_service,
            util=self.mock_util,
            i18n_service=self.mock_i18n_service
        )
        self.company_short_name = "test_company"

    # --- Tests para image_search (Texto a Imagen) ---

    def test_image_search_success(self):
        """Debe retornar HTML formateado con traducciones cuando se encuentran resultados."""
        # Arrange
        mock_results = [
            {'filename': 'logo.png', 'score': 0.95, 'url': 'http://img.url/1',
             'document_url': 'http://doc.url/1',
             'page': 2, 'image_index': 1,
             'meta': {'caption_text': 'Logo principal'},
             'document_meta': {'type': 'brand_asset'}},
            {'filename': 'banner.jpg', 'score': 0.88, 'url': None}  # Sin URL pública
        ]
        self.mock_visual_kb_service.search_images.return_value = mock_results

        # Act
        response = self.service.image_search(self.company_short_name, "buscar logo")

        # Assert
        # Verificar llamada al servicio KB
        self.mock_visual_kb_service.search_images.assert_called_with(
            company_short_name=self.company_short_name,
            query="buscar logo",
            n_results=5,
            collection=None,
            metadata_filter=None
        )

        # Verificar título traducido
        assert "translated[rag.visual.found_images]" in response

        # Verificar item con URL
        assert "translated[rag.visual.view_image]" in response
        assert '<a href="http://img.url/1"' in response
        assert '<a href="http://doc.url/1"' in response
        assert "Logo principal" in response
        assert "Document metadata" in response

        # Verificar item sin URL
        assert "translated[rag.visual.image_unavailable]" in response

    def test_image_search_no_results(self):
        """Debe retornar mensaje traducido de 'sin resultados'."""
        self.mock_visual_kb_service.search_images.return_value = []

        response = self.service.image_search(self.company_short_name, "algo inexistente")

        # Verificar que devuelve la key de traducción correcta con el parámetro title
        expected_title = "translated[rag.visual.found_images]"
        # Nota: El title se traduce ANTES de llamar a _format_response en image_search,
        # pero cuando entra a _format_response y ve lista vacía, usa ese título para el mensaje de error.

        # Revisando la implementación:
        # image_search llama a _format_response(results, t('found_images'))
        # si results vacio -> t('no_results_for', title=title)

        assert "translated[rag.visual.no_results_for|title=translated[rag.visual.found_images]]" in response

    # --- Tests para visual_search (Imagen a Imagen) ---

    def test_visual_search_success(self):
        """Debe realizar la búsqueda visual y usar el título traducido correspondiente."""
        # Arrange
        request_images = [{'name': 'q.jpg', 'base64': 'AAAA'}]
        self.mock_util.normalize_base64_payload.return_value = b'bytes'
        self.mock_visual_kb_service.search_similar_images.return_value = [{'filename': 'res.jpg'}]

        # Act
        response = self.service.visual_search(self.company_short_name, request_images)

        # Assert
        self.mock_visual_kb_service.search_similar_images.assert_called_with(
            company_short_name=self.company_short_name,
            image_content=b'bytes',
            n_results=5,
            collection=None,
            metadata_filter=None
        )
        assert "translated[rag.visual.similar_images_found]" in response

    def test_visual_search_no_images_provided(self):
        """Debe retornar error traducido si la lista de imágenes está vacía."""
        response = self.service.visual_search(self.company_short_name, [])

        assert response == "translated[rag.visual.no_images_attached]"

    def test_visual_search_invalid_index(self):
        """Debe retornar error traducido con parámetros si el índice es inválido."""
        request_images = [{'name': 'img1.jpg'}]

        # Índice fuera de rango
        response = self.service.visual_search(self.company_short_name, request_images, image_index=5)

        assert "translated[rag.visual.invalid_index|index=5,total=1]" in response

    def test_visual_search_processing_error(self):
        """Debe capturar excepciones y retornar error traducido."""
        request_images = [{'name': 'bad.jpg', 'base64': 'bad'}]
        self.mock_util.normalize_base64_payload.side_effect = Exception("DecodeError")

        response = self.service.visual_search(self.company_short_name, request_images)

        assert "translated[rag.visual.processing_error|error=DecodeError]" in response

    def test_image_search_passes_metadata_filter(self):
        self.mock_visual_kb_service.search_images.return_value = []

        self.service.image_search(
            self.company_short_name,
            "buscar logo",
            metadata_filter={"image.page": 1}
        )

        self.mock_visual_kb_service.search_images.assert_called_with(
            company_short_name=self.company_short_name,
            query="buscar logo",
            n_results=5,
            collection=None,
            metadata_filter={"image.page": 1}
        )

    def test_visual_search_passes_metadata_filter(self):
        request_images = [{'name': 'q.jpg', 'base64': 'AAAA'}]
        self.mock_util.normalize_base64_payload.return_value = b'bytes'
        self.mock_visual_kb_service.search_similar_images.return_value = []

        self.service.visual_search(
            self.company_short_name,
            request_images,
            metadata_filter={"doc.type": "invoice"}
        )

        self.mock_visual_kb_service.search_similar_images.assert_called_with(
            company_short_name=self.company_short_name,
            image_content=b'bytes',
            n_results=5,
            collection=None,
            metadata_filter={"doc.type": "invoice"}
        )

    def test_image_search_structured_output_serializes_filename_as_document_link(self):
        self.mock_visual_kb_service.search_images.return_value = [
            {
                "filename": "contract.pdf",
                "document_url": "https://doc.example/contract.pdf",
                "url": "https://img.example/contract.png",
                "score": 0.9,
                "meta": {},
                "document_meta": {},
                "page": 1,
                "image_index": 1,
            }
        ]

        payload = self.service.image_search(
            self.company_short_name,
            "contract",
            structured_output=True,
        )

        assert payload["status"] == "success"
        assert "[contract.pdf](https://doc.example/contract.pdf)" in payload["serialized_context"]
