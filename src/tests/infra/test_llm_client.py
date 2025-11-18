# tests/test_llm_client.py

import pytest
from unittest.mock import patch, MagicMock
from iatoolkit.infra.llm_client import llmClient
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
        self.llm_proxy_factory = MagicMock()
        self.injector_mock = MagicMock()

        # Mock del LLMProxy que será devuelto por la fábrica
        self.mock_proxy = MagicMock()
        self.llm_proxy_factory.create_for_company.return_value = self.mock_proxy

        # Mock company
        self.company = Company(id=1, name='Test Company', short_name='test_company')

        # Mock de variables de entorno
        self.env_patcher = patch.dict('os.environ', {'LLM_MODEL': 'gpt-4o'})
        self.env_patcher.start()

        # Mock tiktoken
        self.tiktoken_patcher = patch('iatoolkit.infra.llm_client.tiktoken')
        self.mock_tiktoken = self.tiktoken_patcher.start()
        self.mock_tiktoken.encoding_for_model.return_value = MagicMock()

        # Instance of the client under test
        self.client = llmClient(
            llmquery_repo=self.llmquery_repo,
            util=self.util_mock,
            llm_proxy_factory=self.llm_proxy_factory
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
            model='gpt-5',question='q', context='c', tools=[], text={}
        )

        self.llm_proxy_factory.create_for_company.assert_called_once_with(self.company)
        self.mock_proxy.create_response.assert_called_once()
        assert result['valid_response'] is True
        assert 'Test response' in result['answer']
        assert result['response_id'] == 'response_123'
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

        # 4. Use patch to replace `current_iatoolkit` with our mock toolkit
        with patch('iatoolkit.current_iatoolkit', return_value=toolkit_mock):
            # 5. Define the sequence of LLM responses
            tool_call = ToolCall('call1', 'function_call', 'test_func', '{"a": 1}')
            response_with_tools = LLMResponse('r1', 'gpt-4o', 'completed', '', [tool_call], Usage(10, 5, 15))
            self.mock_proxy.create_response.side_effect = [response_with_tools, self.mock_llm_response]

            # 6. Invoke the client. Now, when it calls current_iatoolkit, it will get our mock.
            self.client.invoke(
                company=self.company, user_identifier='user1', previous_response_id='prev1',
                model='gpt-5',question='q', context='c', tools=[{}], text={}
            )

        # 7. Assertions
        assert self.mock_proxy.create_response.call_count == 2

        # Verify that the dispatcher was correctly retrieved and called
        dispatcher_mock.dispatch.assert_called_once_with(
            company_short_name='test_company', function_name='test_func', a=1
        )

        # Verify that the function output was reinjected into the history
        second_call_args = self.mock_proxy.create_response.call_args_list[1].kwargs
        function_output_message = second_call_args['input'][1]
        assert function_output_message.get('type') == 'function_call_output'
        assert function_output_message.get('output') == '{"status": "ok"}'

    def test_invoke_llm_api_error_propagates(self):
        """Test que los errores de la API del LLM se propagan como IAToolkitException."""
        self.mock_proxy.create_response.side_effect = Exception("API Communication Error")

        with pytest.raises(IAToolkitException, match="Error calling LLM API"):
            self.client.invoke(
                company=self.company, user_identifier='user1', previous_response_id='prev1',
                model='gpt-5', question='q', context='c', tools=[], text={}
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
        self.llm_proxy_factory.create_for_company.assert_called_once_with(self.company)
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