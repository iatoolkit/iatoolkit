# tests/test_llm_client.py

import pytest
from unittest.mock import patch, MagicMock
from iatoolkit.services.llm_client_service import llmClient
from iatoolkit.services.storage_service import StorageService
from iatoolkit.common.model_registry import ModelRegistry
from iatoolkit.infra.llm_response import LLMResponse, ToolCall, Usage
from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.repositories.models import Company
import json


class TestLLMClient:
    def setup_method(self):
        """Setup común para todos los tests"""
        # Mocks de dependencias inyectadas
        self.dispatcher_mock = MagicMock()
        self.llmquery_repo = MagicMock()
        self.util_mock = MagicMock()
        self.model_registry_mock = MagicMock(spec=ModelRegistry)
        self.storage_service_mock = MagicMock(spec=StorageService)
        self.mock_proxy = MagicMock()
        self.injector_mock = MagicMock()

        # Mock company
        self.company = Company(id=1, name='Test Company', short_name='test_company')

        # Mock de variables de entorno
        self.env_patcher = patch.dict('os.environ', {'LLM_MODEL': 'gpt-4o'})
        self.env_patcher.start()

        # Mock tiktoken
        self.tiktoken_patcher = patch('iatoolkit.services.llm_client_service.tiktoken')
        self.mock_tiktoken = self.tiktoken_patcher.start()
        self.mock_tiktoken.encoding_for_model.return_value = MagicMock()

        # Instance of the client under test
        self.client = llmClient(
            llmquery_repo=self.llmquery_repo,
            util=self.util_mock,
            llm_proxy=self.mock_proxy,
            model_registry=self.model_registry_mock,
            storage_service=self.storage_service_mock
        )

        # Respuesta mock estándar del LLM
        self.mock_llm_response = LLMResponse(
            id='response_123', model='gpt-4o', status='completed',
            output_text=json.dumps({"answer": "Test response", "aditional_data": {}}),
            output=[], usage=Usage(input_tokens=100, output_tokens=50, total_tokens=150)
        )

    def teardown_method(self):
        """Limpieza después de cada test"""
        patch.stopall()

    def test_invoke_success(self):
        """Test de una llamada invoke exitosa."""
        self.mock_proxy.create_response.return_value = self.mock_llm_response

        result = self.client.invoke(
            company=self.company, user_identifier='user1', previous_response_id='prev1',
            model='gpt-5',question='q', context='c', tools=[], text={}, images=[]
        )

        self.mock_proxy.create_response.assert_called_once()
        call_kwargs = self.mock_proxy.create_response.call_args.kwargs
        assert call_kwargs['images'] == []
        assert call_kwargs['attachments'] == []

        assert result['valid_response'] is True
        assert 'Test response' in result['answer']
        assert result['response_id'] == 'response_123'

        assert 'content_parts' in result
        assert len(result['content_parts']) > 0

        self.llmquery_repo.add_query.assert_called_once()

    def test_invoke_passes_tool_choice_override_to_initial_llm_call(self):
        self.mock_proxy.create_response.return_value = self.mock_llm_response

        self.client.invoke(
            company=self.company,
            user_identifier='user1',
            previous_response_id='prev1',
            model='gpt-5',
            question='q',
            context='c',
            tools=[{"name": "iat_memory_search"}],
            tool_choice_override='iat_memory_search',
            text={},
            images=[],
        )

        call_kwargs = self.mock_proxy.create_response.call_args.kwargs
        assert call_kwargs['tool_choice'] == 'iat_memory_search'

    def test_invoke_processes_generated_images(self):
        """Test que verifica que las imágenes generadas se suben al storage y se actualiza la respuesta."""
        # 1. Configurar respuesta del LLM con una imagen en Base64
        base64_data = "SGVsbG8="  # 'Hello' en base64
        mime_type = "image/png"

        mock_response = LLMResponse(
            id='resp_img', model='gpt-4o', status='completed',
            output_text='{"answer": "Look at this", "aditional_data": {}}',
            output=[], usage=Usage(10, 10, 20),
            content_parts=[
                {'type': 'text', 'text': 'Look at this'},
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': mime_type,
                        'data': base64_data
                    }
                }
            ]
        )
        self.mock_proxy.create_response.return_value = mock_response

        # 2. Configurar el mock de storage para devolver URLs simuladas
        self.storage_service_mock.store_generated_image.return_value = {
            'storage_key': 'companies/test_company/generated_images/uuid.png',
            'url': 'https://s3.amazonaws.com/bucket/uuid.png?token=...'
        }

        # 3. Invocar
        result = self.client.invoke(
            company=self.company, user_identifier='user1', previous_response_id='p1',
            question='q', context='c', tools=[], text={}, model='gpt-5', images=[]
        )

        # 4. Validar llamada a storage service
        self.storage_service_mock.store_generated_image.assert_called_once_with(
            'test_company', base64_data, mime_type
        )

        # 5. Validar que la respuesta final contiene la URL y no el base64
        content_parts = result['content_parts']
        assert len(content_parts) == 2

        image_part = content_parts[1]
        assert image_part['type'] == 'image'
        # El tipo de fuente debe haber cambiado a 'url'
        assert image_part['source']['type'] == 'url'
        assert image_part['source']['url'] == 'https://s3.amazonaws.com/bucket/uuid.png?token=...'
        assert image_part['source']['storage_key'] == 'companies/test_company/generated_images/uuid.png'
        # Asegurarse que el campo data (base64) ya no existe para ahorrar espacio
        assert 'data' not in image_part['source']


    def test_invoke_success_with_images(self):
        """Test de una llamada invoke exitosa con imagenes."""
        self.mock_proxy.create_response.return_value = self.mock_llm_response
        fake_images = [{'name': 'x.png', 'base64': '...'}]

        result = self.client.invoke(
            company=self.company, user_identifier='user1', previous_response_id='prev1',
            model='gpt-5',question='q', context='c', tools=[], text={}, images=fake_images
        )

        self.mock_proxy.create_response.assert_called_once()
        call_kwargs = self.mock_proxy.create_response.call_args.kwargs
        assert call_kwargs['images'] == fake_images
        assert call_kwargs['attachments'] == []

        assert result['valid_response'] is True
        self.llmquery_repo.add_query.assert_called_once()

    def test_invoke_handles_function_calls(self):
        """Tests that invoke correctly handles function calls."""
        # 1. Create a mock for the dispatcher service
        dispatcher_mock = MagicMock()
        dispatcher_mock.dispatch.return_value = '{"status": "ok"}'

        # 2. Create a mock injector that knows how to provide the dispatcher mock
        injector_mock = MagicMock()
        injector_mock.get.return_value = dispatcher_mock

        # 3. Create a mock IAToolkit instance
        toolkit_mock = MagicMock()
        # Make its _get_injector() method return our mock injector
        toolkit_mock.get_injector.return_value = injector_mock

        fake_images = [{'name': 'x.png', 'base64': '...'}]

        # 4. Use patch to replace `current_iatoolkit` with our mock toolkit
        with patch('iatoolkit.current_iatoolkit', return_value=toolkit_mock):
            # 5. Define the sequence of LLM responses
            tool_call = ToolCall('call1', 'function_call', 'test_func', '{"a": 1}')
            response_with_tools = LLMResponse('r1', 'gpt-4o', 'completed', '', [tool_call], Usage(10, 5, 15))
            self.mock_proxy.create_response.side_effect = [response_with_tools, self.mock_llm_response]

            # 6. Invoke the client. Now, when it calls current_iatoolkit, it will get our mock.
            self.client.invoke(
                company=self.company, user_identifier='user1', previous_response_id='prev1',
                model='gpt-5', question='q', context='c', tools=[{}], text={}, images=fake_images
            )

        # 7. Assertions
        assert self.mock_proxy.create_response.call_count == 2

        # Verify that the dispatcher was correctly retrieved and called (including request_images)
        dispatcher_mock.dispatch.assert_called_once_with(
            company_short_name='test_company',
            function_name='test_func',
            user_identifier='user1',
            request_images=fake_images,
            a=1
        )

        # Verify that the function output was reinjected into the history
        second_call_args = self.mock_proxy.create_response.call_args_list[1].kwargs
        function_output_message = second_call_args['input'][1]
        assert function_output_message.get('type') == 'function_call_output'
        assert function_output_message.get('output') == '{"status": "ok"}'
        assert second_call_args['attachments'] == []

    def test_invoke_passes_native_attachments_to_llm_proxy(self):
        self.mock_proxy.create_response.return_value = self.mock_llm_response
        native_attachments = [
            {"name": "sales.csv", "mime_type": "text/csv", "base64": "U0FNUExF"}
        ]

        self.client.invoke(
            company=self.company,
            user_identifier='user1',
            previous_response_id='prev1',
            model='gpt-5',
            question='q',
            context='c',
            tools=[],
            text={},
            images=[],
            attachments=native_attachments,
        )

        self.mock_proxy.create_response.assert_called_once()
        call_kwargs = self.mock_proxy.create_response.call_args.kwargs
        assert call_kwargs['attachments'] == native_attachments

    def test_invoke_reinjects_native_attachments_returned_by_tool(self):
        dispatcher_mock = MagicMock()
        dispatcher_mock.dispatch.return_value = {
            "status": "success",
            "page": {"page_id": 14, "title": "Reporte"},
            "__native_attachments__": [
                {"name": "sales.csv", "mime_type": "text/csv", "base64": "U0FNUExF"}
            ],
        }

        injector_mock = MagicMock()
        injector_mock.get.return_value = dispatcher_mock

        toolkit_mock = MagicMock()
        toolkit_mock.get_injector.return_value = injector_mock

        with patch('iatoolkit.current_iatoolkit', return_value=toolkit_mock):
            tool_call = ToolCall('call1', 'function_call', 'iat_memory_get_page', '{"page_id": 14}')
            response_with_tools = LLMResponse('r1', 'gpt-4o', 'completed', '', [tool_call], Usage(10, 5, 15))
            self.mock_proxy.create_response.side_effect = [response_with_tools, self.mock_llm_response]

            self.client.invoke(
                company=self.company, user_identifier='user1', previous_response_id='prev1',
                model='gpt-5', question='q', context='c', tools=[{}], text={}, images=[]
            )

        second_call_args = self.mock_proxy.create_response.call_args_list[1].kwargs
        function_output_message = second_call_args['input'][1]
        parsed_output = json.loads(function_output_message.get('output'))
        assert "__native_attachments__" not in parsed_output
        assert second_call_args['attachments'] == [
            {"name": "sales.csv", "mime_type": "text/csv", "base64": "U0FNUExF"}
        ]

    def test_invoke_serializes_dict_function_output_as_json(self):
        dispatcher_mock = MagicMock()
        dispatcher_mock.dispatch.return_value = {"status": "ok", "count": 2}

        injector_mock = MagicMock()
        injector_mock.get.return_value = dispatcher_mock

        toolkit_mock = MagicMock()
        toolkit_mock.get_injector.return_value = injector_mock

        with patch('iatoolkit.current_iatoolkit', return_value=toolkit_mock):
            tool_call = ToolCall('call1', 'function_call', 'test_func', '{"a": 1}')
            response_with_tools = LLMResponse('r1', 'gpt-4o', 'completed', '', [tool_call], Usage(10, 5, 15))
            self.mock_proxy.create_response.side_effect = [response_with_tools, self.mock_llm_response]

            self.client.invoke(
                company=self.company, user_identifier='user1', previous_response_id='prev1',
                model='gpt-5', question='q', context='c', tools=[{}], text={}, images=[]
            )

        second_call_args = self.mock_proxy.create_response.call_args_list[1].kwargs
        function_output_message = second_call_args['input'][1]
        parsed_output = json.loads(function_output_message.get('output'))
        assert parsed_output == {"status": "ok", "count": 2}

    def test_invoke_llm_api_error_propagates(self):
        """Test que los errores de la API del LLM se propagan como IAToolkitException."""
        self.mock_proxy.create_response.side_effect = Exception("API Communication Error")

        with pytest.raises(IAToolkitException, match="Error calling LLM API"):
            self.client.invoke(
                company=self.company, user_identifier='user1', previous_response_id='prev1',
                model='gpt-5', question='q', context='c', tools=[], text={}, images=[]
            )
        # Verificar que se guarda un registro de error en la BD
        self.llmquery_repo.add_query.assert_called_once()
        log_arg = self.llmquery_repo.add_query.call_args[0][0]
        assert log_arg.valid_response is False
        assert "API Communication Error" in log_arg.output

    def test_set_company_context_success(self):
        """Test de la configuración exitosa del contexto de la empresa."""
        context_response = LLMResponse('ctx1', 'gpt-4o', 'completed', 'OK', [], Usage(10, 2, 12))
        self.mock_proxy.create_response.return_value = context_response

        response_id = self.client.set_company_context(
            company=self.company, company_base_context="System prompt", model = "gpt"
        )

        assert response_id == 'ctx1'
        self.mock_proxy.create_response.assert_called_once()
        call_args = self.mock_proxy.create_response.call_args.kwargs['input'][0]
        assert call_args['role'] == 'system'
        assert call_args['content'] == 'System prompt'

    def test_decode_response_valid_json(self):
        """Test de decodificación de una respuesta JSON válida."""
        response = LLMResponse('r1', 'm1', 'completed', '```json\n{"answer": "hola"}\n```', [], Usage(1, 1, 2))

        # Simular una respuesta con fallback
        with patch('json.loads', return_value={'answer': 'hola'}):
            decoded = self.client.decode_response(response)
            assert decoded['answer_format'] == 'json_fallback'

        # Simular una respuesta completa y válida
        with patch('json.loads', return_value={'answer': 'hola', 'aditional_data': {}}):
            decoded = self.client.decode_response(response)
            assert decoded['status'] is True
            assert decoded['answer'] == 'hola'
            assert decoded['answer_format'] == 'json_string'

    def test_apply_response_contract_sets_structured_output_on_valid_schema(self):
        decoded = {
            "status": False,
            "output_text": '{"customer_id":"c-100"}',
            "answer": "",
            "aditional_data": {},
            "answer_format": "plaintext",
            "error_message": "legacy error",
        }
        contract = {
            "schema": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                },
            },
            "schema_mode": "strict",
            "response_mode": "structured_only",
        }

        result = self.client._apply_response_contract(decoded, contract)

        assert result["status"] is True
        assert result["schema_applied"] is True
        assert result["schema_valid"] is True
        assert result["structured_output"]["customer_id"] == "c-100"
        assert result["answer_format"] == "structured_only"

    def test_apply_response_contract_accepts_legacy_answer_with_aditional_data_payload(self):
        decoded = {
            "status": True,
            "output_text": json.dumps({
                "answer": "ok",
                "aditional_data": {"customer_id": "c-legacy"},
            }),
            "parsed_json": {
                "answer": "ok",
                "aditional_data": {"customer_id": "c-legacy"},
            },
            "answer": "ok",
            "aditional_data": {"customer_id": "c-legacy"},
            "answer_format": "json_string",
            "error_message": "",
        }
        contract = {
            "schema": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                },
            },
            "schema_mode": "best_effort",
            "response_mode": "chat_compatible",
        }

        result = self.client._apply_response_contract(decoded, contract)

        assert result["schema_applied"] is True
        assert result["schema_valid"] is True
        assert result["structured_output"] == {"customer_id": "c-legacy"}
        # Keeps chat-compatible answer but exposes structured payload.
        assert result["answer"] == "ok"

    def test_apply_response_contract_raises_on_strict_schema_mismatch(self):
        decoded = {
            "status": True,
            "output_text": '{"score": 10}',
            "answer": "fallback",
            "aditional_data": {},
            "answer_format": "plaintext",
            "error_message": "",
        }
        contract = {
            "schema": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                    "customer_id": {"type": "string"},
                },
            },
            "schema_mode": "strict",
            "response_mode": "chat_compatible",
        }

        with pytest.raises(IAToolkitException):
            self.client._apply_response_contract(decoded, contract)

    def test_apply_response_contract_accepts_json_payload_embedded_in_answer_field(self):
        decoded = {
            "status": True,
            "output_text": json.dumps({
                "answer": "{\"sales_2025\":[{\"id\":1,\"country\":\"Chile\",\"sales\":100.5}]}",
                "aditional_data": {},
            }),
            "parsed_json": {
                "answer": "{\"sales_2025\":[{\"id\":1,\"country\":\"Chile\",\"sales\":100.5}]}",
                "aditional_data": {},
            },
            "answer": "{\"sales_2025\":[{\"id\":1,\"country\":\"Chile\",\"sales\":100.5}]}",
            "aditional_data": {},
            "answer_format": "json_string",
            "error_message": "",
        }
        contract = {
            "schema": {
                "type": "object",
                "required": ["sales_2025"],
                "properties": {
                    "sales_2025": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "country", "sales"],
                            "properties": {
                                "id": {"type": "integer"},
                                "country": {"type": "string"},
                                "sales": {"type": "number"},
                            },
                        },
                    }
                },
            },
            "schema_mode": "strict",
            "response_mode": "chat_compatible",
        }

        result = self.client._apply_response_contract(decoded, contract)

        assert result["schema_applied"] is True
        assert result["schema_valid"] is True
        assert result["structured_output"]["sales_2025"][0]["country"] == "Chile"

    def test_apply_response_contract_uses_legacy_aditional_data_when_no_contract(self):
        decoded = {
            "status": True,
            "output_text": '{"answer":"ok","aditional_data":{"employees":[{"id":1}]}}',
            "answer": "ok",
            "aditional_data": {"employees": [{"id": 1}]},
            "answer_format": "json_string",
            "error_message": "",
        }

        result = self.client._apply_response_contract(decoded, None)

        assert result["structured_output"] == {"employees": [{"id": 1}]}
        assert result["schema_applied"] is False
        assert result["schema_valid"] is None
