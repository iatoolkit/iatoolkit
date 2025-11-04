# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from unittest.mock import MagicMock, patch, mock_open
from iatoolkit.common.exceptions import IAToolkitException
import os
from iatoolkit.common.util import Utility
from datetime import datetime, date
from decimal import Decimal
from cryptography.fernet import Fernet

# Generar una clave Fernet de prueba una vez y usarla en el fixture
ACTUAL_FERNET_KEY_FOR_ENV = Fernet.generate_key().decode('utf-8')


class TestUtil:
    def setup_method(self):
        self.util = Utility()


    @patch("jinja2.Environment.get_template")
    def test_util_when_jinja_error(self, mock_get_template):
        mock_template = MagicMock()
        mock_get_template.return_value = mock_template
        mock_template.render.side_effect = Exception('jinja error')

        with pytest.raises(IAToolkitException) as excinfo:
            self.util.render_prompt_from_template(
                template_pathname='a template',
                query='a query'
            )

        # Validar que la excepción es la esperada
        assert "TEMPLATE_ERROR" == excinfo.value.error_type.name

    @patch("jinja2.Environment.get_template")
    def test_util_when_ok(self, mock_get_template):
        mock_template = MagicMock()
        mock_get_template.return_value = mock_template
        mock_template.render.return_value = 'a large prompt'

        prompt = self.util.render_prompt_from_template(
                template_pathname='a template',
                query='a query'
        )

        # Validar que la excepción es la esperada
        assert "a large prompt" == prompt

    def test_serialize_datetime(self):
        """Test serialización de datetime"""
        test_datetime = datetime(2024, 1, 1, 12, 0, 0)
        result = self.util.serialize(test_datetime)
        assert result == "2024-01-01T12:00:00"

    def test_serialize_date(self):
        """Test serialización de date"""
        test_date = date(2024, 1, 1)
        result = self.util.serialize(test_date)
        assert result == "2024-01-01"

    def test_serialize_decimal(self):
        """Test serialización de Decimal"""
        test_decimal = Decimal('10.5')
        result = self.util.serialize(test_decimal)
        assert result == 10.5
        assert isinstance(result, float)

    def test_serialize_bytes(self):
        """Test serialización de bytes"""
        test_bytes = b"Hello World"
        result = self.util.serialize(test_bytes)
        assert result == "Hello World"
        assert isinstance(result, str)

    def test_serialize_unsupported_type(self):
        """Test serialización de tipo no soportado"""

        class UnsupportedClass:
            pass

        test_obj = UnsupportedClass()
        with pytest.raises(TypeError) as excinfo:
            self.util.serialize(test_obj)

        assert str(excinfo.value).startswith("Type <class")

    def test_load_schema_from_yaml(self):
        mock_yaml_content = """
        field1: "Descripción del campo 1"
        field2: "Descripción del campo 2"
        """
        with patch("builtins.open", mock_open(read_data=mock_yaml_content)) as mock_file:
            schema = self.util.load_schema_from_yaml("fake_path/schema.yaml")

            assert schema == {
                "field1": "Descripción del campo 1",
                "field2": "Descripción del campo 2"
            }

            # test file was open
            mock_file.assert_called_once_with("fake_path/schema.yaml", 'r', encoding='utf-8')

    def test_generate_llm_context(self):
        """Test generación de contexto LLM con schema que incluye listas y subcampos."""
        entity_name = "test_entity"
        client_json = {"field1": "valor1", "field2": 2}
        schema = {
            "field1": {
                "type": "string",
                "description": "Descripción del campo 1"
            },
            "field2": {
                "type": "integer",
                "description": "Descripción del campo 2",
                "values": ["1", "2", "3"]
            },
            "field3": {
                "type": "list",
                "description": "Descripción del campo 3 (lista de objetos)",
                "item_structure": {
                    "subfield1": {
                        "type": "string",
                        "description": "Descripción de subcampo 1"
                    },
                    "subfield2": {
                        "type": "boolean",
                        "description": "Descripción de subcampo 2"
                    }
                }
            }
        }

        expected_schema = "\n".join([
            "- **`field1`** (string): Descripción del campo 1",
            "- **`field2`** (integer): Descripción del campo 2",
            '- **`field3`** (list): Descripción del campo 3 (lista de objetos)',
        ])

        # now check the schema
        schema_context = self.util.generate_context_for_schema(entity_name, schema=schema)
        assert schema_context.strip() == expected_schema.strip()

    def test_markdown_context(self):
        md_content = "ejemplo de md context"
        with patch("builtins.open", mock_open(read_data=md_content)) as mock_file:
            context = self.util.load_markdown_context("company_content.md")

            assert context == md_content

            # test file was open
            mock_file.assert_called_once_with("company_content.md", 'r', encoding='utf-8')

    def test_encrypt_decrypt_key_successful(self):
        """Testa encriptación y desencriptación exitosa de una clave."""
        env_vars = {'FERNET_KEY': ACTUAL_FERNET_KEY_FOR_ENV}
        with patch.dict(os.environ, env_vars, clear=True):
            util_with_key = Utility() # Nueva instancia que lee el FERNET_KEY mockeado
            original_key = "mi_api_key_secreta_123_con_ñ_y_tildes_áéíóú"
            encrypted_key = util_with_key.encrypt_key(original_key)

            assert encrypted_key is not None
            assert isinstance(encrypted_key, str)
            assert encrypted_key != original_key

            decrypted_key = util_with_key.decrypt_key(encrypted_key)
            assert decrypted_key == original_key

    def test_encrypt_key_no_fernet_key_env(self):
        """Testa encrypt_key cuando FERNET_KEY no está en el entorno."""
        util_no_env_key = Utility()
        with pytest.raises(IAToolkitException) as excinfo:
            util_no_env_key.encrypt_key("testkey")
        assert excinfo.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
        assert "No se pudo obtener variable de ambiente para encriptar" in excinfo.value.message

    def test_encrypt_key_empty_input_key(self):
        """Testa encrypt_key cuando la clave de entrada está vacía, pero FERNET_KEY es válida."""
        env_vars = {'FERNET_KEY': ACTUAL_FERNET_KEY_FOR_ENV}
        with patch.dict(os.environ, env_vars, clear=True):
            util_with_key = Utility() # Nueva instancia con FERNET_KEY
            with pytest.raises(IAToolkitException) as excinfo_empty:
                util_with_key.encrypt_key("")
        assert excinfo_empty.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
        assert "falta la clave a encriptar" in excinfo_empty.value.message

    def test_decrypt_key_no_fernet_key_env(self):
        # Primero, encriptar una clave usando un Utility con FERNET_KEY
        # (podríamos usar self.util del setup si supiéramos que no usa FERNET_KEY en __init__,
        # pero es más seguro crear una instancia temporal con la clave para generar el dato de test)
        encrypted_key_valid = ""
        env_vars_for_encryption = {'FERNET_KEY': ACTUAL_FERNET_KEY_FOR_ENV}
        with patch.dict(os.environ, env_vars_for_encryption, clear=True):
            temp_util = Utility()
            encrypted_key_valid = temp_util.encrypt_key("mi_api_key_secreta_123")

        # Ahora, probar la desencriptación sin FERNET_KEY
        util_no_env_key = Utility()
        with pytest.raises(IAToolkitException) as excinfo:
            util_no_env_key.decrypt_key(encrypted_key_valid)
        assert excinfo.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
        assert "No se pudo obtener variable de ambiente para desencriptar" in excinfo.value.message

    def test_decrypt_key_empty_input_key(self):
        """Testa decrypt_key cuando la clave encriptada de entrada está vacía o es None, pero FERNET_KEY es válida."""
        env_vars = {'FERNET_KEY': ACTUAL_FERNET_KEY_FOR_ENV}
        with patch.dict(os.environ, env_vars, clear=True):
            util_with_key = Utility() # Nueva instancia con FERNET_KEY
            with pytest.raises(IAToolkitException) as excinfo_empty:
                util_with_key.decrypt_key("")
            assert excinfo_empty.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
            assert "falta la clave a encriptar" in excinfo_empty.value.message # Mensaje actual de la implementación

            with pytest.raises(IAToolkitException) as excinfo_none:
                util_with_key.decrypt_key(None)
            assert excinfo_none.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
            assert "falta la clave a encriptar" in excinfo_none.value.message # Mensaje actual de la implementación

    def test_encrypt_key_when_exception_in_fermet(self):
        """Testa encrypt_key si FERNET_KEY en el entorno es inválida."""
        invalid_env_fernet_key = "clave_no_valida_para_fernet"
        env_vars = {'FERNET_KEY': invalid_env_fernet_key}
        with patch.dict(os.environ, env_vars, clear=True):
            util_invalid_env_key = Utility()
            with pytest.raises(IAToolkitException) as excinfo:
                util_invalid_env_key.encrypt_key("testkey")
        assert excinfo.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
        # El mensaje exacto puede depender de cómo Utility maneje internamente el error de Fernet
        # "No se pudo encriptar la clave" es un buen candidato si hay un try-except genérico.
        # Si Fernet(key) se llama directamente y falla, el mensaje podría ser de Fernet/cryptography.
        # Basado en el código original, la excepción es reenvasada.
        assert "No se pudo encriptar la clave" in excinfo.value.message


    def test_decrypt_key_when_exception_in_fermet(self):
        """Testa decrypt_key si FERNET_KEY en el entorno es inválida."""
        # Encriptar primero con una clave válida
        encrypted_key_valid = ""
        valid_env_vars = {'FERNET_KEY': ACTUAL_FERNET_KEY_FOR_ENV}
        with patch.dict(os.environ, valid_env_vars, clear=True):
            temp_util_for_encrypt = Utility()
            encrypted_key_valid = temp_util_for_encrypt.encrypt_key("some_secret_data")

        # Ahora intentar desencriptar con una FERNET_KEY inválida en el entorno
        invalid_env_fernet_key = "clave_no_valida_para_fernet"
        invalid_env_vars = {'FERNET_KEY': invalid_env_fernet_key, 'PROMPTS_DIR': './prompts'}
        with patch.dict(os.environ, invalid_env_vars, clear=True):
            util_invalid_env_key = Utility()
            with pytest.raises(IAToolkitException) as excinfo:
                util_invalid_env_key.decrypt_key(encrypted_key_valid)
        assert excinfo.value.error_type == IAToolkitException.ErrorType.CRYPT_ERROR
        assert "No se pudo desencriptar la clave" in excinfo.value.message

    def test_validate_rut_when_not_ok(self):
        status = self.util.validate_rut("123456789")
        assert status == False

    def test_validate_rut_not_numeric(self):
        status = self.util.validate_rut("opensoft")
        assert status == False

    def test_validate_rut_when_ok(self):
        assert self.util.validate_rut("31456455-3") == True

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_success_with_extension(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test obtener archivos con extensión, retornando nombres con extensión"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file1.txt', 'file2.txt', 'file3.doc', 'subdir']
        mock_isfile.side_effect = lambda path: not path.endswith('subdir')
        
        result = self.util.get_files_by_extension('/test/directory', '.txt', return_extension=True)
        
        assert result == ['file1.txt', 'file2.txt']
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_success_without_extension(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test obtener archivos con extensión, retornando nombres sin extensión"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file1.txt', 'file2.txt', 'file3.doc', 'subdir']
        mock_isfile.side_effect = lambda path: not path.endswith('subdir')
        
        result = self.util.get_files_by_extension('/test/directory', '.txt', return_extension=False)
        
        assert result == ['file1', 'file2']
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_success_extension_without_dot(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test obtener archivos con extensión sin punto, retornando nombres sin extensión"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file1.txt', 'file2.txt', 'file3.doc', 'subdir']
        mock_isfile.side_effect = lambda path: not path.endswith('subdir')
        
        result = self.util.get_files_by_extension('/test/directory', 'txt', return_extension=False)
        
        assert result == ['file1', 'file2']
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_empty_result(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test cuando no hay archivos con la extensión especificada"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file1.doc', 'file2.pdf', 'subdir']
        mock_isfile.side_effect = lambda path: not path.endswith('subdir')
        
        result = self.util.get_files_by_extension('/test/directory', '.txt')
        
        assert result == []
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_sorted_result(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test que los resultados estén ordenados alfabéticamente"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['zebra.txt', 'alpha.txt', 'beta.txt', 'subdir']
        mock_isfile.side_effect = lambda path: not path.endswith('subdir')
        
        result = self.util.get_files_by_extension('/test/directory', '.txt', return_extension=True)
        
        assert result == ['alpha.txt', 'beta.txt', 'zebra.txt']
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    def test_get_files_by_extension_directory_not_exists(self, mock_exists):
        """Test cuando el directorio no existe"""
        mock_exists.return_value = False
        
        with pytest.raises(IAToolkitException) as excinfo:
            self.util.get_files_by_extension('/nonexistent/directory', '.txt')
        
        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert "El directorio no existe" in excinfo.value.message
        mock_exists.assert_called_once_with('/nonexistent/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_get_files_by_extension_not_a_directory(self, mock_isdir, mock_exists):
        """Test cuando la ruta existe pero no es un directorio"""
        mock_exists.return_value = True
        mock_isdir.return_value = False
        
        with pytest.raises(IAToolkitException) as excinfo:
            self.util.get_files_by_extension('/path/to/file.txt', '.txt')
        
        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert "La ruta no es un directorio" in excinfo.value.message
        mock_exists.assert_called_once_with('/path/to/file.txt')
        mock_isdir.assert_called_once_with('/path/to/file.txt')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    def test_get_files_by_extension_os_error(self, mock_listdir, mock_isdir, mock_exists):
        """Test cuando hay un error del sistema operativo al listar el directorio"""
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.side_effect = OSError("Permission denied")
        
        with pytest.raises(IAToolkitException) as excinfo:
            self.util.get_files_by_extension('/test/directory', '.txt')
        
        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert "Error al buscar archivos en el directorio" in excinfo.value.message
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_with_subdirectories(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test que solo se consideren archivos, no subdirectorios"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file1.txt', 'subdir1', 'file2.txt', 'subdir2']
        # Simular que solo los archivos son archivos, los subdirectorios no
        mock_isfile.side_effect = lambda path: 'subdir' not in path
        
        result = self.util.get_files_by_extension('/test/directory', '.txt', return_extension=True)
        
        assert result == ['file1.txt', 'file2.txt']
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    def test_get_files_by_extension_case_sensitive(self, mock_isfile, mock_listdir, mock_isdir, mock_exists):
        """Test que la búsqueda sea sensible a mayúsculas/minúsculas"""
        # Setup mocks
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_listdir.return_value = ['file1.txt', 'file2.TXT', 'file3.txt', 'subdir']
        mock_isfile.side_effect = lambda path: not path.endswith('subdir')
        
        result = self.util.get_files_by_extension('/test/directory', '.txt', return_extension=True)
        
        # Solo debe encontrar 'file1.txt' y 'file3.txt', no 'file2.TXT'
        assert result == ['file1.txt', 'file3.txt']
        mock_exists.assert_called_once_with('/test/directory')
        mock_isdir.assert_called_once_with('/test/directory')
        mock_listdir.assert_called_once_with('/test/directory')

    @patch('os.path.exists', return_value=True)
    def test_get_company_template_success(self, mock_exists):
        """
        Prueba que la plantilla de una compañía se cargue correctamente cuando el archivo existe.
        """
        # Arrange
        company_name = "sample_co"
        template_name = "welcome_email.txt"
        template_content = "Hola, bienvenido a {{ company_name }}!"
        expected_path = os.path.join(os.getcwd(), f'companies/{company_name}/templates/{template_name}')

        with patch("builtins.open", mock_open(read_data=template_content)) as mock_file:
            # Act
            result = self.util.get_company_template(company_name, template_name)

            # Assert
            mock_exists.assert_called_once_with(expected_path)
            mock_file.assert_called_once_with(expected_path, 'r')
            assert result == template_content

    @patch('os.path.exists', return_value=False)
    def test_get_company_template_file_not_found(self, mock_exists):
        """
        Prueba que la función retorne None si el archivo de la plantilla no existe.
        """
        # Arrange
        company_name = "no_template_co"
        template_name = "non_existent.txt"
        expected_path = os.path.join(os.getcwd(), f'companies/{company_name}/templates/{template_name}')

        with patch("builtins.open") as mock_file:
            # Act
            result = self.util.get_company_template(company_name, template_name)

            # Assert
            mock_exists.assert_called_once_with(expected_path)
            mock_file.assert_not_called()
            assert result is None

    @patch('os.path.exists', return_value=True)
    @patch('logging.exception')
    def test_get_company_template_read_error(self, mock_logging, mock_exists):
        """
        Prueba que la función retorne None y loguee una excepción si hay un error al leer el archivo.
        """
        # Arrange
        company_name = "error_co"
        template_name = "corrupt.txt"
        expected_path = os.path.join(os.getcwd(), f'companies/{company_name}/templates/{template_name}')

        with patch("builtins.open", side_effect=IOError("Permission denied")) as mock_file:
            # Act
            result = self.util.get_company_template(company_name, template_name)

            # Assert
            mock_exists.assert_called_once_with(expected_path)
            mock_file.assert_called_once_with(expected_path, 'r')
            mock_logging.assert_called_once()
            assert result is None