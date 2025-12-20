# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.util import Utility
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.services.sql_service import SqlService
from iatoolkit.common.exceptions import IAToolkitException
import logging
from injector import inject


class CompanyContextService:
    """
    Responsible for building the complete context string for a given company
    to be sent to the Language Model.
    """

    @inject
    def __init__(self,
                 sql_service: SqlService,
                 utility: Utility,
                 config_service: ConfigurationService,
                 asset_repo: AssetRepository):
        self.sql_service = sql_service
        self.utility = utility
        self.config_service = config_service
        self.asset_repo = asset_repo

    def get_company_context(self, company_short_name: str) -> str:
        """
        Builds the full context by aggregating three sources:
        1. Static context files (Markdown).
        2. Static schema files (YAML files for SQL data sources).
        """
        context_parts = []

        # 1. Context from Markdown (context/*.md)  files
        try:
            md_context = self._get_static_file_context(company_short_name)
            if md_context:
                context_parts.append(md_context)
        except Exception as e:
            logging.warning(f"Could not load Markdown context for '{company_short_name}': {e}")

        # 2. Context from company-specific SQL databases
        try:
            sql_context = self._get_sql_schema_context(company_short_name)
            if sql_context:
                context_parts.append(sql_context)
        except Exception as e:
            logging.warning(f"Could not generate SQL context for '{company_short_name}': {e}")

        # 3. Context from yaml (schema/*.yaml) files
        try:
            yaml_schema_context = self._get_yaml_schema_context(company_short_name)
            if yaml_schema_context:
                context_parts.append(yaml_schema_context)
        except Exception as e:
            logging.warning(f"Could not load Yaml context for '{company_short_name}': {e}")

        # Join all parts with a clear separator
        return "\n\n---\n\n".join(context_parts)

    def _get_static_file_context(self, company_short_name: str) -> str:
        # Get context from .md files using the repository
        static_context = ''

        try:
            # 1. List markdown files in the context "folder"
            # Note: The repo handles where this folder actually is (FS or DB)
            md_files = self.asset_repo.list_files(company_short_name, AssetType.CONTEXT, extension='.md')

            for filename in md_files:
                try:
                    # 2. Read content
                    content = self.asset_repo.read_text(company_short_name, AssetType.CONTEXT, filename)
                    static_context += content + "\n"  # Append content
                except Exception as e:
                    logging.warning(f"Error reading context file {filename}: {e}")

        except Exception as e:
            # If listing fails (e.g. folder doesn't exist), just log and return empty
            logging.warning(f"Error listing context files for {company_short_name}: {e}")

        return static_context

    def _get_sql_schema_context(self, company_short_name: str) -> str:
        """
        Generates the SQL schema context by inspecting live database connections
        based on the flexible company.yaml configuration.
        It supports including all tables and providing specific overrides for a subset of them.
        """
        data_sources_config = self.config_service.get_configuration(company_short_name, 'data_sources')
        if not data_sources_config or not data_sources_config.get('sql'):
            return ''

        sql_context = ''
        for source in data_sources_config.get('sql', []):
            db_name = source.get('database')
            if not db_name:
                continue

            try:
                db_provider = self.sql_service.get_database_provider(company_short_name, db_name)
            except IAToolkitException as e:
                logging.warning(f"Could not get DB provider for '{db_name}': {e}")
                continue

            db_description = source.get('description', '')
            sql_context = f"***Database (`database_key`)***: {db_name}\n"

            if db_description:
                sql_context += (
                    f"**Description:** : {db_description}\n"
                )

            sql_context += (
                f"IMPORTANT: To query this database you MUST use the service/tool "
                f"**iat_sql_query**, with `database_key={db_name}`.\n"
            )

            sql_context += (
                f"IMPORTANT: The value of **database_key** is ALWAYS the literal string "
                f"'{db_name}'. Do not invent or infer alternative names. "
                f"Use exactly: `database_key='{db_name}'`.\n"
            )

            # 1. get the list of tables to process.
            tables_to_process = []
            if source.get('include_all_tables', False):
                all_tables = db_provider.get_all_table_names()
                tables_to_exclude = set(source.get('exclude_tables', []))
                tables_to_process = [t for t in all_tables if t not in tables_to_exclude]
            elif 'tables' in source:
                # if not include_all_tables, use the list of tables explicitly specified in the map.
                tables_to_process = list(source['tables'].keys())

            # 2. get the global settings and overrides.
            global_exclude_columns = source.get('exclude_columns', [])
            table_prefix = source.get('table_prefix')

            # get database schema definition, for this source.
            database_schema_name = source.get('schema')

            table_overrides = source.get('tables', {})

            # 3. iterate over the tables.
            for table_name in tables_to_process:
                try:
                    # 4. get the table specific configuration.
                    table_config = table_overrides.get(table_name, {})

                    # 5. define the schema object name, using the override if it exists.
                    # Priority 1: Explicit override from the 'tables' map.
                    schema_object_name = table_config.get('schema_name')

                    if not schema_object_name:
                        # Priority 3: Automatic prefix stripping.
                        if table_prefix and table_name.startswith(table_prefix):
                            schema_object_name = table_name[len(table_prefix):]
                        else:
                            # Priority 4: Default to the table name itself.
                            schema_object_name = table_name

                    # 6. define the list of columns to exclude, (local vs. global).
                    local_exclude_columns = table_config.get('exclude_columns')
                    final_exclude_columns = local_exclude_columns if local_exclude_columns is not None else global_exclude_columns

                    # 7. get the table schema definition.
                    table_definition = db_provider.get_table_schema(
                        table_name=table_name,
                        db_schema=db_provider.schema,
                        schema_object_name=schema_object_name,
                        exclude_columns=final_exclude_columns
                    )
                    sql_context += table_definition
                except (KeyError, RuntimeError) as e:
                    logging.warning(f"Could not generate schema for table '{table_name}': {e}")

        if sql_context:
            sql_context = "These are the SQL databases you can query using the **`iat_sql_service`**: \n" + sql_context
        return sql_context

    def _get_yaml_schema_context(self, company_short_name: str) -> str:
        # Get context from .yaml schema files using the repository
        yaml_schema_context = ''

        try:
            # 1. List yaml files in the schema "folder"
            schema_files = self.asset_repo.list_files(company_short_name, AssetType.SCHEMA, extension='.yaml')

            for filename in schema_files:
                try:
                    # 2. Read content
                    content = self.asset_repo.read_text(company_short_name, AssetType.SCHEMA, filename)

                    # 3. Parse YAML content into a dict
                    schema_dict = self.utility.load_yaml_from_string(content)

                    # 4. Generate markdown description from the dict
                    if schema_dict:
                        # We use generate_schema_table which accepts a dict directly
                        yaml_schema_context += self.utility.generate_schema_table(schema_dict)

                except Exception as e:
                    logging.warning(f"Error processing schema file {filename}: {e}")

        except Exception as e:
            logging.warning(f"Error listing schema files for {company_short_name}: {e}")

        return yaml_schema_context