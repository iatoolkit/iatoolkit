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
        self.mock_gemini_client.GenerativeModel.return_value = self.mock_generative_model
        self.adapter = GeminiAdapter(gemini_client=self.mock_gemini_client)

        patch('iatoolkit.infra.llm_providers.gemini_adapter.uuid.uuid4', return_value=uuid.UUID('12345678-1234-5678-1234-567812345678')).start()

        self.message_to_dict_patcher = patch('iatoolkit.infra.llm_providers.gemini_adapter.MessageToDict')
        self.mock_message_to_dict = self.message_to_dict_patcher.start()

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
            # Nos aseguramos que el otro atributo no exista para evitar ambigüedad
            del part.function_call
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
            del part.text
            parts.append(part)

        mock_candidate = MagicMock()
        mock_candidate.content.parts = parts
        mock_candidate.finish_reason = finish_reason
        mock_response.candidates = [mock_candidate]

        if usage_metadata:
            mock_response.usage_metadata = MagicMock(**usage_metadata)
        else:
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
        mock_response = self._create_mock_gemini_response(text_content="Ok, veo la imagen")
        self.mock_generative_model.generate_content.return_value = mock_response

        # Input de usuario
        input_data = [{"role": "user", "content": "Que ves?"}]
        # Imágenes
        images = [
            {'name': 'foto.jpg', 'base64': 'AAAA'},
            {'name': 'grafico.png', 'base64': 'BBBB'}
        ]

        self.adapter.create_response(model="gemini-1.5-flash", input=input_data, images=images)

        # Verificar la llamada a generate_content
        self.mock_generative_model.generate_content.assert_called_once()
        call_args = self.mock_generative_model.generate_content.call_args
        contents = call_args[0][0]  # Primer argumento posicional es 'contents'

        # Debe haber 1 mensaje de usuario
        assert len(contents) == 1
        user_msg = contents[0]
        assert user_msg['role'] == 'user'

        # El mensaje debe tener 3 partes: 1 texto + 2 imágenes
        parts = user_msg['parts']
        assert len(parts) == 3

        # Parte 1: Texto
        assert parts[0] == {'text': 'Que ves?'}

        # Parte 2: Imagen JPG
        assert 'inline_data' in parts[1]
        assert parts[1]['inline_data']['mime_type'] == 'image/jpeg'
        assert parts[1]['inline_data']['data'] == 'AAAA'

        # Parte 3: Imagen PNG
        assert 'inline_data' in parts[2]
        assert parts[2]['inline_data']['mime_type'] == 'image/png'
        assert parts[2]['inline_data']['data'] == 'BBBB'

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

    @pytest.mark.parametrize("finish_reason, expected_status", [
        ("SAFETY", "blocked"), ("MAX_TOKENS", "length_exceeded"), ("STOP", "completed")
    ])
    def test_map_finish_reason_to_status(self, finish_reason, expected_status):
        mock_response = self._create_mock_gemini_response(finish_reason=finish_reason)
        self.mock_generative_model.generate_content.return_value = mock_response
        response = self.adapter.create_response(model="gemini-pro", input=[])
        assert response.status == expected_status