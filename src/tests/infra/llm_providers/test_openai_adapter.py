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

    def test_create_response_records_exact_request_payload_for_telemetry(self):
        mock_response = MagicMock()
        mock_response.id = 'chatcmpl-telemetry'
        mock_response.model = 'gpt-5'
        mock_response.status = 'completed'
        mock_response.output_text = 'ok'
        mock_response.output = []
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.usage.total_tokens = 15
        self.mock_openai_client.responses.create.return_value = mock_response

        telemetry_execution = MagicMock()
        input_data = [{'role': 'user', 'content': 'Hello'}]

        self.adapter.create_response(
            model='gpt-5',
            input=input_data,
            telemetry_execution=telemetry_execution,
            text={'verbosity': 'medium'},
        )

        telemetry_execution.record_input.assert_called_once_with({
            'model': 'gpt-5',
            'input': input_data,
            'store': False,
            'include': ['reasoning.encrypted_content'],
            'text': {'verbosity': 'medium'},
        })

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

    def test_create_response_multimodal_with_native_attachments(self):
        mock_response = MagicMock()
        mock_response.id = 'chatcmpl-mm-file'
        mock_response.model = 'gpt-4.1'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.usage = None
        mock_response.output_text = ""
        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'Analiza este CSV'}]
        attachments = [
            {'name': 'sales.csv', 'mime_type': 'text/csv', 'base64': 'U0FNUExF'}
        ]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
            attachments=attachments,
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        user_msg = call_kwargs['input'][0]
        assert isinstance(user_msg['content'], list)
        assert user_msg['content'][0] == {'type': 'input_text', 'text': 'Analiza este CSV'}
        assert user_msg['content'][1]['type'] == 'input_file'
        assert user_msg['content'][1]['filename'] == 'sales.csv'
        assert user_msg['content'][1]['file_data'] == 'data:text/csv;base64,U0FNUExF'

    def test_create_response_multimodal_accepts_image_data_urls(self):
        mock_response = MagicMock()
        mock_response.id = 'chatcmpl-mm-image-data-url'
        mock_response.model = 'gpt-4.1'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.usage = None
        mock_response.output_text = ""
        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'Describe esta imagen'}]
        images = [
            {'name': 'photo.jpg', 'base64': 'data:image/jpeg;base64,AAAA'}
        ]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
            images=images,
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        user_msg = call_kwargs['input'][0]
        assert isinstance(user_msg['content'], list)
        assert user_msg['content'][0] == {'type': 'input_text', 'text': 'Describe esta imagen'}
        assert user_msg['content'][1]['type'] == 'input_image'
        assert user_msg['content'][1]['image_url'] == 'data:image/jpeg;base64,AAAA'

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
            tool_choice='none',
            text={'some': 'text'},
            reasoning={'some': 'reasoning'},
            store=True,
            metadata={'prompt_name': 'sales_prompt', 'prompt_version': '2', 'prompt_variant': 'baseline'},
        )

        # Assert
        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert 'previous_response_id' not in call_kwargs
        assert call_kwargs['tool_choice'] == 'none'
        assert call_kwargs['text'] == {'some': 'text'}
        assert call_kwargs['reasoning'] == {'some': 'reasoning'}
        # Nothing is kept at OpenAI, whatever a prompt or company.yaml declares.
        assert call_kwargs['store'] is False
        assert call_kwargs['metadata'] == {
            'prompt_name': 'sales_prompt',
            'prompt_version': '2',
            'prompt_variant': 'baseline',
        }

    def test_create_response_includes_context_history_without_previous_response_id(self):
        mock_response = MagicMock()
        mock_response.id = 'resp-client-history'
        mock_response.model = 'gpt-4.1'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.output_text = 'ok'
        mock_response.usage = None
        self.mock_openai_client.responses.create.return_value = mock_response

        context_history = [
            {'role': 'system', 'content': 'Base context'},
            {'role': 'user', 'content': 'Earlier question'},
            {'role': 'assistant', 'content': 'Earlier answer'},
        ]
        input_data = [{'role': 'user', 'content': 'Current question'}]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
            context_history=context_history,
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert call_kwargs['input'] == context_history + input_data
        assert 'previous_response_id' not in call_kwargs

    def test_create_response_maps_specific_function_tool_choice(self):
        mock_response = MagicMock()
        mock_response.id = 'id'
        mock_response.model = 'model'
        mock_response.status = 'status'
        mock_response.output = []
        mock_response.output_text = ""
        mock_response.usage = None

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'test'}]
        tools = [
            {'type': 'function', 'name': 'iat_memory_search', 'description': 'memory', 'parameters': {}}
        ]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
            tools=tools,
            tool_choice='iat_memory_search',
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert call_kwargs['tool_choice'] == {'type': 'function', 'name': 'iat_memory_search'}

    def test_create_response_does_not_mutate_shared_tools_list(self):
        mock_response = MagicMock()
        mock_response.id = 'id'
        mock_response.model = 'model'
        mock_response.status = 'status'
        mock_response.output = []
        mock_response.output_text = ""
        mock_response.usage = None

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [{'role': 'user', 'content': 'test'}]
        tools = [{'type': 'function', 'name': 'iat_memory_search', 'description': 'memory', 'parameters': {}}]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
            tools=tools,
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert call_kwargs['tools'] == tools
        assert tools == [{'type': 'function', 'name': 'iat_memory_search', 'description': 'memory', 'parameters': {}}]

    def test_create_response_with_generated_image(self):
        """Prueba que procesa una imagen generada en la respuesta (Responses API)."""
        # Arrange
        mock_response = MagicMock()
        mock_response.id = 'resp-img'
        mock_response.model = 'gpt-4'
        mock_response.status = 'completed'
        mock_response.output_text = ''
        mock_response.usage = None

        # Simulamos output_items (Responses API): message con texto + image_generation_call con base64 en result
        message_item = MagicMock()
        message_item.type = 'message'

        text_part = MagicMock()
        text_part.type = 'output_text'
        text_part.text = 'Here is the image:'

        message_item.content = [text_part]

        image_item = MagicMock()
        image_item.type = 'image_generation_call'
        image_item.result = 'BASE64DATA'

        mock_response.output = [message_item, image_item]

        self.mock_openai_client.responses.create.return_value = mock_response

        # Act
        result = self.adapter.create_response(model='gpt-4', input=[])

        # Assert
        assert len(result.content_parts) == 3

        # Parte 1: Texto
        assert result.content_parts[0] == {'type': 'text', 'text': 'Here is the image:'}

        # Parte 2: Imagen (base64)
        assert result.content_parts[1]['type'] == 'image'
        assert result.content_parts[1]['source']['type'] == 'base64'
        assert result.content_parts[1]['source']['data'] == 'BASE64DATA'
        assert result.content_parts[1]['source']['media_type'] == 'image/png'

        # Parte 3: marcador de imagen en texto (markdown)
        assert result.content_parts[2] == {
            'type': 'text',
            'text': '![Imagen Generada](data:image/png;base64,BASE64DATA)'
        }

        # output_text debe incluir texto (la imagen está en content_parts)
        assert 'Here is the image:' in result.output_text

    def test_a_tool_follow_up_sends_the_whole_conversation(self):
        mock_response = MagicMock()
        mock_response.id = 'resp-follow-up'
        mock_response.model = 'gpt-4.1'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.output_text = 'done'
        mock_response.usage = None

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [
            {'role': 'user', 'content': 'Weather in London?'},
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call_abc',
                        'type': 'function',
                        'function': {
                            'name': 'get_weather',
                            'arguments': '{"location":"London"}',
                        },
                    }
                ],
            },
            {
                'type': 'function_call_output',
                'call_id': 'call_abc',
                'status': 'completed',
                'output': '{"temperature":21}',
            },
        ]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert 'previous_response_id' not in call_kwargs
        assert call_kwargs['input'] == [
            {'role': 'user', 'content': 'Weather in London?'},
            {
                'type': 'function_call',
                'call_id': 'call_abc',
                'name': 'get_weather',
                'arguments': '{"location":"London"}',
            },
            {
                'type': 'function_call_output',
                'call_id': 'call_abc',
                'output': '{"temperature":21}',
            },
        ]

    def _empty_response(self, response_id='resp'):
        mock_response = MagicMock()
        mock_response.id = response_id
        mock_response.model = 'gpt-5'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.output_text = 'done'
        mock_response.usage = None
        return mock_response

    def test_encrypted_reasoning_is_requested_only_from_reasoning_models(self):
        self.mock_openai_client.responses.create.return_value = self._empty_response()

        for model, expected in (
            ('gpt-5', True), ('gpt-5-mini', True), ('o3', True),
            ('gpt-4.1', False), ('gpt-5-chat-latest', False), ('grok-4', False),
        ):
            self.adapter.create_response(model=model, input=[{'role': 'user', 'content': 'x'}])
            call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
            assert ('include' in call_kwargs) is expected, model
            assert call_kwargs['store'] is False

    def test_reasoning_items_are_mapped_for_the_next_call(self):
        reasoning_item = MagicMock()
        reasoning_item.type = 'reasoning'
        reasoning_item.id = 'rs_1'
        reasoning_item.encrypted_content = 'ENC'
        summary_part = MagicMock()
        summary_part.text = 'thinking'
        reasoning_item.summary = [summary_part]
        reasoning_item.content = []
        unencrypted = MagicMock()
        unencrypted.type = 'reasoning'
        unencrypted.encrypted_content = None
        unencrypted.summary = []
        unencrypted.content = []
        response = self._empty_response()
        response.output = [reasoning_item, unencrypted]
        self.mock_openai_client.responses.create.return_value = response

        result = self.adapter.create_response(model='gpt-5', input=[{'role': 'user', 'content': 'x'}])

        assert result.reasoning_details == [{
            'type': 'reasoning',
            'summary': [{'type': 'summary_text', 'text': 'thinking'}],
            'encrypted_content': 'ENC',
            'id': 'rs_1',
        }]
        assert result.reasoning_content == 'thinking'

    def test_reasoning_goes_back_in_front_of_the_calls_it_produced(self):
        self.mock_openai_client.responses.create.return_value = self._empty_response()
        input_data = [
            {'role': 'user', 'content': 'question'},
            {
                'role': 'assistant',
                'content': '',
                'reasoning_details': [
                    {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'encrypted_content': 'ENC'},
                    # OpenRouter-shaped detail from another adapter: never sent to OpenAI.
                    {'type': 'reasoning.text', 'text': 'other provider'},
                    # Without encrypted content OpenAI cannot use it.
                    {'type': 'reasoning', 'id': 'rs_2', 'summary': []},
                ],
                'tool_calls': [
                    {'id': 'call_1', 'type': 'function',
                     'function': {'name': 'iat_sql_query', 'arguments': '{"query":"SELECT 1"}'}},
                ],
            },
            {'type': 'function_call_output', 'call_id': 'call_1', 'status': 'completed', 'output': 'rows'},
        ]

        self.adapter.create_response(model='gpt-5', input=input_data)

        assert self.mock_openai_client.responses.create.call_args.kwargs['input'] == [
            {'role': 'user', 'content': 'question'},
            {'type': 'reasoning', 'summary': [], 'encrypted_content': 'ENC', 'id': 'rs_1'},
            {'type': 'function_call', 'call_id': 'call_1', 'name': 'iat_sql_query',
             'arguments': '{"query":"SELECT 1"}'},
            {'type': 'function_call_output', 'call_id': 'call_1', 'output': 'rows'},
        ]

    def test_every_tool_round_is_sent_again(self):
        """The tool loop keeps every round in its input and nothing is stored at
        OpenAI, so each follow-up must carry all of them."""
        self.mock_openai_client.responses.create.return_value = self._empty_response()

        def assistant_calling(*call_ids):
            return {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {'id': call_id, 'type': 'function',
                     'function': {'name': 'iat_sql_query', 'arguments': '{}'}}
                    for call_id in call_ids
                ],
            }

        def output(call_id):
            return {'type': 'function_call_output', 'call_id': call_id,
                    'status': 'completed', 'output': f'rows for {call_id}'}

        input_data = [
            {'role': 'user', 'content': 'the whole prompt context'},
            assistant_calling('call_1'),
            output('call_1'),
            assistant_calling('call_2', 'call_3'),
            output('call_2'),
            output('call_3'),
        ]

        self.adapter.create_response(model='gpt-4.1', input=input_data)

        sent = self.mock_openai_client.responses.create.call_args.kwargs['input']
        assert [item.get('call_id') for item in sent if item.get('type') == 'function_call_output'] == [
            'call_1', 'call_2', 'call_3',
        ]
        assert [item.get('call_id') for item in sent if item.get('type') == 'function_call'] == [
            'call_1', 'call_2', 'call_3',
        ]

    def test_create_response_converts_assistant_tool_calls_to_function_call_items(self):
        mock_response = MagicMock()
        mock_response.id = 'resp-client-history'
        mock_response.model = 'gpt-4.1'
        mock_response.status = 'completed'
        mock_response.output = []
        mock_response.output_text = 'done'
        mock_response.usage = None

        self.mock_openai_client.responses.create.return_value = mock_response

        input_data = [
            {'role': 'user', 'content': 'Weather in London?'},
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call_abc',
                        'type': 'function',
                        'function': {
                            'name': 'get_weather',
                            'arguments': '{"location":"London"}',
                        },
                    }
                ],
            },
            {
                'type': 'function_call_output',
                'call_id': 'call_abc',
                'status': 'completed',
                'output': '{"temperature":21}',
            },
        ]

        self.adapter.create_response(
            model='gpt-4.1',
            input=input_data,
        )

        call_kwargs = self.mock_openai_client.responses.create.call_args.kwargs
        assert call_kwargs['input'] == [
            {'role': 'user', 'content': 'Weather in London?'},
            {
                'type': 'function_call',
                'call_id': 'call_abc',
                'name': 'get_weather',
                'arguments': '{"location":"London"}',
            },
            {
                'type': 'function_call_output',
                'call_id': 'call_abc',
                'output': '{"temperature":21}',
            },
        ]


def test_the_proxy_decides_whether_reasoning_travels():
    client = MagicMock()
    response = MagicMock()
    response.id, response.model, response.status = 'r', 'gpt-4.1', 'completed'
    response.output, response.output_text, response.usage = [], 'ok', None
    client.responses.create.return_value = response
    adapter = OpenAIAdapter(openai_client=client)

    adapter.create_response(model='gpt-5', input=[{'role': 'user', 'content': 'x'}], carries_reasoning=False)
    assert 'include' not in client.responses.create.call_args.kwargs

    adapter.create_response(model='some-new-model', input=[{'role': 'user', 'content': 'x'}], carries_reasoning=True)
    assert client.responses.create.call_args.kwargs['include'] == ['reasoning.encrypted_content']
