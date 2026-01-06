
# tests/services/test_company_context_service.py

import pytest
from unittest.mock import MagicMock, call
from iatoolkit.services.company_context_service import CompanyContextService
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.services.sql_service import SqlService
from iatoolkit.repositories.database_manager import DatabaseManager
from iatoolkit.common.util import Utility
from iatoolkit.common.exceptions import IAToolkitException
import textwrap

# --- Mock Data for different test scenarios ---

# Simulates include_all_tables: true
MOCK_CONFIG_INCLUDE_ALL = {
    'sql': [{
        'database': 'main_db',
        'include_all_tables': True,
        'description': 'Main database'  # Added description to match test expectations
    }]
}

# Simulates an explicit list of tables
MOCK_CONFIG_EXPLICIT_LIST = {
    'sql': [{
        'database': 'main_db',
        'tables': {
            'products': {},
            'customers': {}
        }
    }]
}



class TestCompanyContextService:
    """
    Unit tests for the CompanyContextService, updated for the new data_sources schema
    and the DatabaseProvider interface.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up mocks for all dependencies and instantiate the service."""
        self.mock_sql_service = MagicMock(spec=SqlService)
        self.mock_utility = MagicMock(spec=Utility)
        self.mock_config_service = MagicMock(spec=ConfigurationService)
        self.mock_asset_repo = MagicMock(spec=AssetRepository)  # <--- Mock Repo

        # NOTE: DatabaseProvider mock is no longer needed for these tests as we mock sql_service.get_database_structure directly

        self.context_service = CompanyContextService(
            sql_service=self.mock_sql_service,
            utility=self.mock_utility,
            config_service=self.mock_config_service,
            asset_repo=self.mock_asset_repo
        )
        self.COMPANY_NAME = 'acme'

    # --- Tests for New SQL Enriched Context Logic ---

    def test_get_sql_enriched_context_success(self):
        """
        GIVEN a valid configuration and database structure
        WHEN _get_sql_enriched_context is called
        THEN it should return the formatted string with descriptions and enriched columns.
        """
        # Arrange
        self.mock_config_service.get_configuration.return_value = MOCK_CONFIG_INCLUDE_ALL

        # Mock DB structure (enriched internally by calling get_enriched_database_schema)
        mock_enriched_structure = {
            'users': {
                'description': 'User table',
                'columns': [
                    {'name': 'id', 'type': 'INTEGER', 'description': 'Primary Key'},
                    {'name': 'meta', 'type': 'JSONB', 'properties': {'role': {'type': 'string'}}}
                ]
            }
        }
        # Mocking the method on the instance itself for this test
        self.context_service.get_enriched_database_schema = MagicMock(return_value=mock_enriched_structure)

        # Act
        result_context, db_tables = self.context_service._get_sql_enriched_context(self.COMPANY_NAME)

        # Assert
        assert "These are the SQL databases" in result_context
        assert "***Database (`database_key`)***: main_db" in result_context
        assert "**Description:** Main database" in result_context

        # Check Table info
        assert "Table: **users**" in result_context
        assert "Description: User table" in result_context

        # Check Column info
        assert "- `id` (INTEGER): Primary Key" in result_context

        # Check JSONB info formatting
        # Removed assertion for literal "JSON Structure:" text as code output is cleaner
        assert "- **`role`** (string)" in result_context

        # Check returned tables list
        assert "users" in db_tables[0].get("table_name")

    def test_get_sql_enriched_context_no_config(self):
        """
        GIVEN no SQL configuration
        WHEN _get_sql_enriched_context is called
        THEN it should return empty string.
        """
        self.mock_config_service.get_configuration.return_value = {}
        # FIX: Unpack the tuple result
        result, tables = self.context_service._get_sql_enriched_context(self.COMPANY_NAME)
        assert result == ""
        assert tables == []

    def test_get_sql_enriched_context_handles_error(self):
        """
        GIVEN an error occurs during schema retrieval
        WHEN _get_sql_enriched_context is called
        THEN it should skip that DB and continue/return what's possible.
        """
        self.mock_config_service.get_configuration.return_value = MOCK_CONFIG_INCLUDE_ALL

        # Force exception in the helper method
        self.context_service.get_enriched_database_schema = MagicMock(side_effect=Exception("DB Down"))

        result_context, db_tables = self.context_service._get_sql_enriched_context(self.COMPANY_NAME)

        assert result_context == ""
        assert db_tables == []

    def test_build_context_integration(self):
        """
        Integration test: get_company_context calls all parts including the new SQL logic.
        """
        # Arrange
        self.mock_config_service.get_configuration.return_value = MOCK_CONFIG_INCLUDE_ALL

        # Mock Markdown
        # FIX: Update lambda signature to accept 'extension' kwarg
        self.mock_asset_repo.list_files.side_effect = lambda c, t, extension=None: ['intro.md'] if t == AssetType.CONTEXT else []
        self.mock_asset_repo.read_text.return_value = "MARKDOWN_CONTENT"

        # Mock SQL Enriched Return
        self.context_service._get_sql_enriched_context = MagicMock(return_value=("SQL_CONTENT", ["users"]))

        # Mock Yaml Schema (should be empty or distinct)
        self.context_service._get_yaml_schema_context = MagicMock(return_value="YAML_EXTRA")

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert "MARKDOWN_CONTENT" in full_context
        assert "SQL_CONTENT" in full_context
        assert "YAML_EXTRA" in full_context

        # Verify _get_yaml_schema_context received the tables list to avoid duplication
        self.context_service._get_yaml_schema_context.assert_called_with(self.COMPANY_NAME, ["users"])

    # --- Existing Logic Tests (Still Valid for Helper Methods) ---

    def test_generate_schema_table_valid(self):
        """Test generation of markdown table from schema dict."""
        schema = {
            "TestEntity": {
                "description": "Entity Desc",
                "properties": {
                    "field1": {"type": "string", "description": "Field Desc"}
                }
            }
        }
        output = self.context_service.generate_schema_table(schema)
        assert "### Objeto: `TestEntity`" in output
        assert "##Descripción:  Entity Desc" in output
        assert "- **`field1`** (string): Field Desc" in output

    # --- Tests for get_enriched_database_schema (The Core Logic) ---

    def test_get_enriched_schema_basic_flow_no_files(self):
        """
        Tests physical introspection without auxiliary YAML files.
        Should return the structure as returned by SqlService without modifications.
        """
        # Arrange
        db_structure = {
            "users": {
                "columns": [{"name": "id", "type": "int"}, {"name": "email", "type": "varchar"}]
            }
        }
        self.mock_sql_service.get_database_structure.return_value = db_structure
        self.mock_asset_repo.list_files.return_value = []

        # Act
        result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

        # Assert
        assert "users" in result
        # No description injected because there is no YAML
        assert "description" not in result["users"]
        self.mock_sql_service.get_database_structure.assert_called_once_with(self.COMPANY_NAME, 'main_db')

    def test_get_enriched_schema_merge_standard_dict_format(self):
        """
        Tests STANDARD format: { table: { columns: { col: {...} } } }
        Verifies that descriptions and metadata are merged.
        """
        # Arrange
        self.mock_sql_service.get_database_structure.return_value = {
            "users": {
                "columns": [{"name": "id"}, {"name": "email"}]
            }
        }
        self.mock_asset_repo.list_files.return_value = ["main_db-users.yaml"]

        yaml_content = textwrap.dedent("""
        users:
          description: "Main Table"
          columns:
            email:
              description: "User Email"
              pii: true
        """)
        self.mock_asset_repo.read_text.return_value = yaml_content

        # Act
        result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

        # Assert
        table = result["users"]
        assert table["description"] == "Main Table"

        col_email = next(c for c in table["columns"] if c["name"] == "email")
        assert col_email["description"] == "User Email"
        assert col_email["pii"] is True

    def test_get_enriched_schema_merge_legacy_list_format(self):
        """
        Tests LEGACY (List) format: { table: { columns: [ {- name: ...} ] } }
        Verifies the list-to-dict adapter works.
        """
        # Arrange
        self.mock_sql_service.get_database_structure.return_value = {
            "suppliers": {
                "columns": [{"name": "supplierid"}, {"name": "companyname"}]
            }
        }
        self.mock_asset_repo.list_files.return_value = ["main_db-suppliers.yaml"]

        yaml_content = textwrap.dedent("""
        suppliers:
          description: Supplier Info
          columns:
            - name: supplierid
              description: Unique ID
              pk: true
            - name: companyname
              description: Company Name
        """)
        self.mock_asset_repo.read_text.return_value = yaml_content

        # Act
        result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

        # Assert
        table = result["suppliers"]
        assert table.get("description") == "Supplier Info"

        col_id = next(c for c in table["columns"] if c["name"] == "supplierid")
        assert col_id["description"] == "Unique ID"

        col_name = next(c for c in table["columns"] if c["name"] == "companyname")
        assert col_name["description"] == "Company Name"

    def test_get_enriched_schema_jsonb_properties_injection(self):
        """
        Tests that 'properties' are correctly injected into JSONB columns.
        """
        # Arrange
        self.mock_sql_service.get_database_structure.return_value = {
            "orders": {
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "details", "type": "JSONB"}
                ]
            }
        }
        self.mock_asset_repo.list_files.return_value = ["main_db-orders.yaml"]

        yaml_content = textwrap.dedent("""
        orders:
          columns:
            details:
              type: object
              description: "JSON Details"
              properties:
                shipping_address:
                  type: string
                items:
                  type: array
        """)
        self.mock_asset_repo.read_text.return_value = yaml_content

        # Act
        result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

        # Assert
        table = result["orders"]
        col_details = next(c for c in table["columns"] if c["name"] == "details")

        assert col_details.get("description") == "JSON Details"
        assert "properties" in col_details
        props = col_details["properties"]
        assert "shipping_address" in props
        assert props["shipping_address"]["type"] == "string"

    def test_build_context_with_only_static_files(self):
        """
        GIVEN only static markdown files provide context in the repo
        WHEN get_company_context is called
        THEN it should return only the markdown context.
        """
        # Arrange
        # 1. Mock Markdown files
        self.mock_asset_repo.list_files.side_effect = lambda company, asset_type, extension: \
            ['info.md'] if asset_type == AssetType.CONTEXT else []

        self.mock_asset_repo.read_text.return_value = "STATIC_INFO"

        # 2. No SQL config
        self.mock_config_service.get_configuration.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert "STATIC_INFO" in full_context

        # Verify repository calls
        self.mock_asset_repo.list_files.assert_any_call(self.COMPANY_NAME, AssetType.CONTEXT, extension='.md')
        self.mock_asset_repo.read_text.assert_any_call(self.COMPANY_NAME, AssetType.CONTEXT, 'info.md')

        # Verify SQL service was NOT called
        self.mock_sql_service.get_database_structure.assert_not_called()

    def test_build_context_with_yaml_schemas(self):
        """
        GIVEN yaml schema files in the repo
        WHEN get_company_context is called
        THEN it should parse them and include them in context.
        """

        # Arrange
        # 1. Mock YAML files
        def list_files_side_effect(company, asset_type, extension):
            if asset_type == AssetType.SCHEMA: return ['orders.yaml']
            return []

        self.mock_asset_repo.list_files.side_effect = list_files_side_effect

        # 2. Mock Content and Parsing
        self.mock_asset_repo.read_text.return_value = "yaml_content"

        # Definimos un diccionario simple. Como generate_schema_table ahora es REAL,
        # transformará este dict en Markdown real.
        mock_schema_dict = {"orders": {"description": "Order table"}}
        self.mock_utility.load_yaml_from_string.return_value = mock_schema_dict

        # NOTA: Ya no mockeamos mock_utility.generate_schema_table porque el método
        # ahora vive dentro de context_service y queremos probar su integración real.

        # 3. No SQL config
        self.mock_config_service.get_configuration.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        # Verificamos que el Markdown generado por el método real esté presente
        assert "### Objeto: `orders`" in full_context
        assert "Order table" in full_context

        # Verify flow
        self.mock_asset_repo.read_text.assert_called_with(self.COMPANY_NAME, AssetType.SCHEMA, 'orders.yaml')
        self.mock_utility.load_yaml_from_string.assert_called_with("yaml_content")

    def test_gracefully_handles_repo_exceptions(self):
        """
        GIVEN the repository raises an exception when listing/reading
        WHEN get_company_context is called
        THEN it should log warnings but continue (return empty strings for those parts).
        """
        # Arrange
        self.mock_asset_repo.list_files.side_effect = Exception("Repo Down")
        self.mock_config_service.get_configuration.return_value = None

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == ""  # Should result in empty string, not crash

    def test_gracefully_handles_db_manager_exception(self):
        """
        GIVEN retrieving a database structure throws an exception
        WHEN get_company_context is called
        THEN it should log a warning and return context from other sources.
        """
        # Arrange
        self.mock_utility.get_files_by_extension.return_value = []  # No static context
        self.mock_config_service.get_configuration.return_value = {'sql': [{'database': 'down_db'}]}

        # Configure the exception on get_database_structure
        self.mock_sql_service.get_database_structure.side_effect = IAToolkitException(
            IAToolkitException.ErrorType.DATABASE_ERROR, "DB is down"
        )

        # Act
        full_context = self.context_service.get_company_context(self.COMPANY_NAME)

        # Assert
        assert full_context == ""
        self.mock_sql_service.get_database_structure.assert_called_once_with(self.COMPANY_NAME, 'down_db')

    def test_generate_llm_context(self):
        """Test generación de contexto LLM con schema que incluye listas y subcampos."""
        # Se estructura el schema con una raíz 'TestEntity' como espera generate_schema_table
        schema = {
            "TestEntity": {
                "description": "Descripción de la entidad",
                "properties": {
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
                        # Se usa 'items' -> 'properties' compatible con util.py
                        "items": {
                            "properties": {
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
                }
            }
        }

        # Se ajusta la expectativa para incluir los headers y la indentación correcta de subcampos
        expected_schema = "\n".join([
            "\n### Objeto: `TestEntity`",
            "##Descripción:  Descripción de la entidad",
            "**Estructura de Datos:**",
            "- **`field1`** (string): Descripción del campo 1",
            "- **`field2`** (integer): Descripción del campo 2",
            "- **`field3`** (list): Descripción del campo 3 (lista de objetos)",
            "  - **`subfield1`** (string): Descripción de subcampo 1",
            "  - **`subfield2`** (boolean): Descripción de subcampo 2"
        ])

        # now check the schema
        schema_context = self.context_service.generate_schema_table(schema=schema)
        assert schema_context.strip() == expected_schema.strip()

        # --- Tests for get_enriched_database_schema ---

        def test_get_enriched_schema_basic_flow_no_files(self):
            """
            Tests physical introspection without auxiliary YAML files.
            Should return the structure as returned by SqlService without modifications.
            """
            # Arrange
            db_structure = {
                "users": {
                    "columns": [{"name": "id", "type": "int"}, {"name": "email", "type": "varchar"}]
                }
            }
            self.mock_sql_service.get_database_structure.return_value = db_structure
            self.mock_asset_repo.list_files.return_value = []

            # Act
            result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

            # Assert
            assert "users" in result
            # No description injected because there is no YAML
            assert "description" not in result["users"]
            self.mock_sql_service.get_database_structure.assert_called_once_with(self.COMPANY_NAME, 'main_db')

        def test_get_enriched_schema_merge_standard_dict_format(self):
            """
            Tests STANDARD format: { table: { columns: { col: {...} } } }
            Verifies that descriptions and metadata are merged.
            """
            # Arrange
            self.mock_sql_service.get_database_structure.return_value = {
                "users": {
                    "columns": [{"name": "id"}, {"name": "email"}]
                }
            }
            self.mock_asset_repo.list_files.return_value = ["users.yaml"]

            yaml_content = textwrap.dedent("""
            users:
              description: "Main Table"
              columns:
                email:
                  description: "User Email"
                  pii: true
            """)
            self.mock_asset_repo.read_text.return_value = yaml_content

            # Act
            result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

            # Assert
            table = result["users"]
            assert table["description"] == "Main Table"

            col_email = next(c for c in table["columns"] if c["name"] == "email")
            assert col_email["description"] == "User Email"
            assert col_email["pii"] is True

        def test_get_enriched_schema_merge_legacy_list_format(self):
            """
            Tests LEGACY (List) format: { table: { columns: [ {- name: ...} ] } }
            Verifies the list-to-dict adapter works.
            """
            # Arrange
            self.mock_sql_service.get_database_structure.return_value = {
                "suppliers": {
                    "columns": [{"name": "supplierid"}, {"name": "companyname"}]
                }
            }
            self.mock_asset_repo.list_files.return_value = ["suppliers.yaml"]

            yaml_content = textwrap.dedent("""
            suppliers:
              description: Supplier Info
              columns:
                - name: supplierid
                  description: Unique ID
                  pk: true
                - name: companyname
                  description: Company Name
            """)
            self.mock_asset_repo.read_text.return_value = yaml_content

            # Act
            result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

            # Assert
            table = result["suppliers"]
            assert table.get("description") == "Supplier Info"

            col_id = next(c for c in table["columns"] if c["name"] == "supplierid")
            assert col_id["description"] == "Unique ID"

            col_name = next(c for c in table["columns"] if c["name"] == "companyname")
            assert col_name["description"] == "Company Name"

        def test_get_enriched_schema_jsonb_properties_injection(self):
            """
            Tests that 'properties' are correctly injected into JSONB columns.
            """
            # Arrange
            self.mock_sql_service.get_database_structure.return_value = {
                "orders": {
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "details", "type": "JSONB"}
                    ]
                }
            }
            self.mock_asset_repo.list_files.return_value = ["orders.yaml"]

            yaml_content = textwrap.dedent("""
            orders:
              columns:
                details:
                  type: object
                  description: "JSON Details"
                  properties:
                    shipping_address:
                      type: string
                    items:
                      type: array
            """)
            self.mock_asset_repo.read_text.return_value = yaml_content

            # Act
            result = self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

            # Assert
            table = result["orders"]
            col_details = next(c for c in table["columns"] if c["name"] == "details")

            assert col_details.get("description") == "JSON Details"
            assert "properties" in col_details
            props = col_details["properties"]
            assert "shipping_address" in props
            assert props["shipping_address"]["type"] == "string"

        def test_get_enriched_schema_error_propagation(self):
            """
            Tests that fatal errors in SQL Service are propagated (re-raised) by the service.
            """
            # Arrange
            self.mock_sql_service.get_database_structure.side_effect = Exception("DB Connection Failed")

            # Act & Assert
            with pytest.raises(Exception) as excinfo:
                self.context_service.get_enriched_database_schema(self.COMPANY_NAME, 'main_db')

            assert "DB Connection Failed" in str(excinfo.value)