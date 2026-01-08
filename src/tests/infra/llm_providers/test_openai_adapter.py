# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.


import pytest
from unittest.mock import MagicMock
from iatoolkit.infra.llm_providers.openai_adapter import OpenAIAdapter
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.common.exceptions import IAToolkitException


class TestOpenAIAdapter:

    def setup_method(self):
        """Setup común para todos los tests"""
        self.mock_openai_client = MagicMock()
        self.adapter = OpenAIAdapter(openai_client=self.mock_openai_client)

    def test_create_response_success(self):
        """Prueba una llamada exitosa a create_response sin herramientas."""
        # Arrange
        mock_response = MagicMock()
        mock_response.id = 'chatcmpl-123'
        mock_response.model = 'gpt-4'
        mock_response.status = 'completed'
        mock_response.output_text = 'Hello, world!'
        mock_response.output = []
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.usage.total_tokens = 15

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'Hello'}]

        # Act
        result = self.adapter.create_response(model='gpt-4', input=input_data)

        # Assert
        self.mock_openai_client.responses.create.assert_called_once()
        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert call_kwargs['model'] == 'gpt-4'
        assert call_kwargs['input'] == input_data
        assert isinstance(result, LLMResponse)
        assert result.id == 'chatcmpl-123'
        assert result.output_text == 'Hello, world!'
        assert result.usage.total_tokens == 15

    def test_create_response_with_tools(self):
        """Prueba create_response cuando la respuesta incluye llamadas a herramientas."""
        # Arrange
        mock_tool_call = MagicMock()
        mock_tool_call.type = 'function_call'
        mock_tool_call.call_id = 'call_abc'
        mock_tool_call.name = 'get_weather'
        mock_tool_call.arguments = '{"location": "London"}'

        mock_response = MagicMock()
        mock_response.id = 'chatcmpl-456'
        mock_response.model = 'gpt-4'
        mock_response.status = 'completed'
        mock_response.output_text = ''  # Usually empty when calling tools
        mock_response.output = [mock_tool_call]
        mock_response.usage.input_tokens = 20
        mock_response.usage.output_tokens = 10
        mock_response.usage.total_tokens = 30

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'Weather in London?'}]
        tools = [{'type': 'function', 'function': {'name': 'get_weather'}}]

        # Act
        result = self.adapter.create_response(model='gpt-4', input=input_data, tools=tools)

        # Assert
        self.mock_openai_client.responses.create.assert_called_once()
        assert len(result.output) == 1
        assert isinstance(result.output[0], ToolCall)
        assert result.output[0].name == 'get_weather'
        assert result.output[0].arguments == '{"location": "London"}'

    def test_create_response_multimodal_input(self):
        """Prueba que los mensajes de texto se transforman a multimodal cuando hay imágenes."""
        # Arrange
        mock_response = MagicMock()
        mock_response.id = 'chatcmpl-mm'
        mock_response.model = 'gpt-4-turbo'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.usage = None
        mock_response.output_text = ""
        self.mock_openai_client.responses.create.return_value = mock_response

        # Input inicial (solo texto)
        input_data = [{'role': 'user', 'content': 'Describe this image'}]

        # Imágenes adjuntas (simuladas)
        images = [
            {'name': 'photo.jpg', 'base64': 'AAAA'},
            {'name': 'chart.png', 'base64': 'BBBB'}
        ]

        # Act
        self.adapter.create_response(model='gpt-4-turbo', input=input_data, images=images)

        # Assert
        self.mock_openai_client.responses.create.assert_called_once()
        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        final_input = call_kwargs['input']

        # Verificaciones:
        # 1. El contenido del mensaje user debe ser una lista ahora
        user_msg = final_input[0]
        assert isinstance(user_msg['content'], list)
        assert len(user_msg['content']) == 3  # 1 texto + 2 imágenes

        # 2. Verificar texto (Responses API)
        assert user_msg['content'][0] == {'type': 'input_text', 'text': 'Describe this image'}

        # 3. Verificar imágenes (Responses API)
        img1 = user_msg['content'][1]
        assert img1['type'] == 'input_image'
        assert img1['image_url'] == 'data:image/jpeg;base64,AAAA'  # fallback jpeg

        img2 = user_msg['content'][2]
        assert img2['type'] == 'input_image'
        assert img2['image_url'] == 'data:image/png;base64,BBBB'

    def test_create_response_api_error(self):
        """Prueba que los errores de la API se capturan y lanzan como IAToolkitException."""
        # Arrange
        self.mock_openai_client.responses.create.side_effect = Exception("API Error")

        input_data = [{'role': 'user', 'content': 'Hello'}]

        # Act & Assert
        with pytest.raises(IAToolkitException) as excinfo:
            self.adapter.create_response(model='gpt-4', input=input_data)

        assert excinfo.value.error_type == IAToolkitException.ErrorType.LLM_ERROR
        assert "Error calling OpenAI API" in str(excinfo.value)
        assert "API Error" in str(excinfo.value)

    def test_create_response_passes_optional_params(self):
        """Prueba que los parámetros opcionales se pasan correctamente a la API."""
        # Arrange
        mock_response = MagicMock()
        # Minimal attributes needed for mapping
        mock_response.id = 'id'
        mock_response.model = 'model'
        mock_response.status = 'status'
        mock_response.output = []
        mock_response.output_text = ""
        mock_response.usage = None

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'test'}]

        # Act
        self.adapter.create_response(
            model='gpt-4',
            input=input_data,
            previous_response_id='prev_123',
            tool_choice='none',
            text={'some': 'text'},
            reasoning={'some': 'reasoning'}
        )

        # Assert
        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert call_kwargs['previous_response_id'] == 'prev_123'
        assert call_kwargs['tool_choice'] == 'none'
        assert call_kwargs['text'] == {'some': 'text'}
        assert call_kwargs['reasoning'] == {'some': 'reasoning'}

    def test_create_response_with_generated_image(self):
        """Prueba que procesa una imagen generada en la respuesta."""
        # Arrange
        mock_response = MagicMock()
        mock_response.id = 'resp-img'
        mock_response.model = 'gpt-4'
        mock_response.status = 'completed'
        mock_response.output_text = ''
        mock_response.usage = None

        # Simulamos output_items mixtos: texto + imagen
        text_item = MagicMock()
        text_item.type = 'text'
        text_item.text = 'Here is the image:'

        image_item = MagicMock()
        image_item.type = 'image'
        image_item.image = 'BASE64DATA' # Simula el contenido binario
        image_item.media_type = 'image/png'

        mock_response.output = [text_item, image_item]

        self.mock_openai_client.responses.create.return_value = mock_response

        # Act
        result = self.adapter.create_response(model='gpt-4', input=[])

        # Assert
        # Verificar que content_parts tiene la estructura correcta
        assert len(result.content_parts) == 2

        # Parte 1: Texto
        assert result.content_parts[0]['type'] == 'text'
        assert result.content_parts[0]['text'] == 'Here is the image:'

        # Parte 2: Imagen
        assert result.content_parts[1]['type'] == 'image'
        assert result.content_parts[1]['source']['type'] == 'base64'
        assert result.content_parts[1]['source']['data'] == 'BASE64DATA'
        assert result.content_parts[1]['source']['media_type'] == 'image/png'

        # Verificar fallback de texto plano
        assert "[Imagen Generada]" in result.output_text