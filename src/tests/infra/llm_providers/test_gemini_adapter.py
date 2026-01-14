import pytest
from unittest.mock import patch, MagicMock
import uuid
import json

from iatoolkit.infra.llm_providers.gemini_adapter import GeminiAdapter
from iatoolkit.infra.llm_response import LLMResponse, ToolCall
from iatoolkit.common.exceptions import IAToolkitException


class TestGeminiAdapter:
    """Tests para la clase GeminiAdapter."""

    def setup_method(self):
        """Configura el entorno de prueba antes de cada test."""
        self.mock_gemini_client = MagicMock()

        self.mock_generative_model = MagicMock()
        self.mock_gemini_client.models = self.mock_generative_model

        # Mantenemos compatibilidad con el estilo antiguo por si acaso
        self.mock_gemini_client.GenerativeModel.return_value = self.mock_generative_model

        self.adapter = GeminiAdapter(gemini_client=self.mock_gemini_client)

        patch('iatoolkit.infra.llm_providers.gemini_adapter.uuid.uuid4', return_value=uuid.UUID('12345678-1234-5678-1234-567812345678')).start()

        self.message_to_dict_patcher = patch('iatoolkit.infra.llm_providers.gemini_adapter.MessageToDict')
        self.mock_message_to_dict = self.message_to_dict_patcher.start()

        # Mockear types.Part para el test multimodal
        self.types_patcher = patch('iatoolkit.infra.llm_providers.gemini_adapter.types')
        self.mock_types = self.types_patcher.start()

    def teardown_method(self):
        patch.stopall()

    def _create_mock_gemini_response(self, text_content=None, function_call=None, finish_reason="STOP",
                                     usage_metadata=None):
        """Crea un objeto de respuesta mock de Gemini de forma robusta."""
        mock_response = MagicMock()
        parts = []

        if text_content:
            part = MagicMock()
            part.text = text_content
            # CORRECCIÓN: Asignar None en lugar de 'del' para evitar AttributeError
            part.function_call = None
            part.inline_data = None
            part.blob = None
            parts.append(part)

        if function_call:
            # Crea un mock para el objeto `function_call` y asigna sus atributos directamente.
            mock_fc_obj = MagicMock()
            mock_fc_obj.name = function_call['name']
            mock_fc_obj._pb = "mock_pb"  # Simular el objeto protobuf interno

            # Configura el mock del conversor para que devuelva los args esperados
            self.mock_message_to_dict.return_value = {'args': function_call['args']}

            part = MagicMock()
            part.function_call = mock_fc_obj
            # CORRECCIÓN: Asignar None en lugar de 'del' para evitar AttributeError
            part.text = None
            part.inline_data = None
            part.blob = None
            parts.append(part)

        mock_candidate = MagicMock()
        mock_candidate.content.parts = parts
        mock_candidate.finish_reason = finish_reason
        mock_response.candidates = [mock_candidate]

        if usage_metadata:
            mock_response.usage_metadata = MagicMock(**usage_metadata)
        else:
            # Para usage_metadata usamos del porque el código usa hasattr para chequearlo
            del mock_response.usage_metadata

        return mock_response

    def test_create_response_text_only(self):
        """Prueba una llamada simple que devuelve solo texto."""
        mock_response = self._create_mock_gemini_response(text_content="Hola mundo")
        self.mock_generative_model.generate_content.return_value = mock_response

        response = self.adapter.create_response(model="gemini-pro", input=[])

        assert isinstance(response, LLMResponse)
        assert response.output_text == "Hola mundo"
        assert len(response.output) == 0

    def test_create_response_text_with_history(self):
        """Prueba una llamada simple que devuelve solo texto."""
        mock_response = self._create_mock_gemini_response(text_content="Hola mundo")
        self.mock_generative_model.generate_content.return_value = mock_response

        context_history = [{"role": "user", "content": "Pregunta"}]

        response = self.adapter.create_response(model="gemini-pro",
                                                input=[],
                                                context_history=context_history)

        assert isinstance(response, LLMResponse)
        assert response.output_text == "Hola mundo"
        assert len(context_history) == 2

    def test_create_response_with_tool_call(self):
        """Prueba una llamada que devuelve una function_call."""
        func_call_data = {'name': 'get_weather', 'args': {'location': 'Santiago'}}
        mock_response = self._create_mock_gemini_response(function_call=func_call_data)
        self.mock_generative_model.generate_content.return_value = mock_response

        response = self.adapter.create_response(model="gemini-flash", input=[], tools=[{}])

        assert len(response.output) == 1
        tool_call = response.output[0]
        assert isinstance(tool_call, ToolCall)
        assert tool_call.name == "get_weather"
        assert tool_call.arguments == json.dumps(func_call_data['args'])
        self.mock_message_to_dict.assert_called_once_with("mock_pb")

    def test_create_response_multimodal_input(self):
        """Prueba que se fusionan las imágenes en el mensaje de usuario."""
        # Configurar los mocks de types
        self.mock_types.Content = MagicMock(side_effect=lambda **kwargs: MagicMock(**kwargs))
        self.mock_types.Part.from_text = MagicMock(side_effect=lambda text: MagicMock(text=text, inline_data=None))

        def mock_from_bytes(data, mime_type):
            mock_part = MagicMock()
            mock_part.text = None
            mock_part.inline_data = MagicMock(data=data, mime_type=mime_type)
            return mock_part

        self.mock_types.Part.from_bytes = MagicMock(side_effect=mock_from_bytes)
        self.mock_types.SafetySetting = MagicMock()
        self.mock_types.GenerateContentConfig = MagicMock()
        self.mock_types.Tool = MagicMock()
        self.mock_types.FunctionDeclaration = MagicMock()

        mock_response = self._create_mock_gemini_response(text_content="Ok, veo la imagen")
        self.mock_generative_model.generate_content.return_value = mock_response

        input_data = [{"role": "user", "content": "Que ves?"}]
        images = [
            {'name': 'foto.jpg', 'base64': 'AAAA'},
            {'name': 'grafico.png', 'base64': 'BBBB'}
        ]

        self.adapter.create_response(model="gemini-1.5-flash", input=input_data, images=images)

        # Verificar que from_bytes fue llamado con los datos correctos
        calls = self.mock_types.Part.from_bytes.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs == {'data': 'AAAA', 'mime_type': 'image/jpeg'}
        assert calls[1].kwargs == {'data': 'BBBB', 'mime_type': 'image/png'}


    def test_history_not_modified_if_no_content_in_response(self):
        """Prueba que el historial no se modifica si la respuesta está vacía."""
        mock_response = self._create_mock_gemini_response()  # Sin texto ni tool calls
        self.mock_generative_model.generate_content.return_value = mock_response

        context_history = [{"role": "user", "content": "Pregunta"}]
        self.adapter.create_response(model="gemini-pro", input=[], context_history=context_history)

        assert len(context_history) == 1  # El historial no debe cambiar

    @pytest.mark.parametrize("error_msg, expected_app_msg", [
        ("Quota exceeded", "Se ha excedido la cuota de la API de Gemini"),
        ("Content blocked", "El contenido fue bloqueado"),
        ("Invalid token", "Tu consulta supera el límite de contexto de Gemini"),
        ("Other API error", "Error calling Gemini API: Other API error"),
    ])
    def test_api_error_handling(self, error_msg, expected_app_msg):
        self.mock_generative_model.generate_content.side_effect = Exception(error_msg)
        with pytest.raises(IAToolkitException, match=expected_app_msg):
            self.adapter.create_response(model="gemini-pro", input=[])


    def test_create_response_with_generated_image(self):
        """Prueba una respuesta que incluye texto e imagen generada."""
        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_candidate.finish_reason = "STOP"

        # Parte 1: Texto
        part_text = MagicMock()
        part_text.text = "Mira este dibujo:"
        # CORRECCIÓN: Asignar None explícitamente
        part_text.inline_data = None
        part_text.function_call = None
        part_text.blob = None

        # Parte 2: Imagen (Inline Data)
        part_img = MagicMock()
        # CORRECCIÓN: Asignar None explícitamente
        part_img.text = None
        part_img.function_call = None
        part_img.inline_data.mime_type = "image/png"
        part_img.inline_data.data = "FAKE_BASE64"
        part_img.blob = None

        mock_candidate.content.parts = [part_text, part_img]
        mock_response.candidates = [mock_candidate]
        del mock_response.usage_metadata # Simplificar usage

        self.mock_generative_model.generate_content.return_value = mock_response

        # Act
        response = self.adapter.create_response(model="gemini-1.5-pro", input=[])

        # Assert
        assert isinstance(response, LLMResponse)
        assert len(response.content_parts) == 2

        # Verificar Texto
        assert response.content_parts[0]['type'] == 'text'
        assert response.content_parts[0]['text'] == "Mira este dibujo:"

        # Verificar Imagen
        assert response.content_parts[1]['type'] == 'image'
        source = response.content_parts[1]['source']
        assert source['type'] == 'base64'
        assert source['media_type'] == 'image/png'
        assert source['data'] == 'FAKE_BASE64'

        # Verificar que output_text tenga el placeholder
        assert "[Imagen Generada]" in response.output_text