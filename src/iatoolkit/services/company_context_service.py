# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.util import Utility
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.services.sql_service import SqlService
from iatoolkit.common.exceptions import IAToolkitException
import logging
from injector import inject
import os


class CompanyContextService:
    """
    Responsible for building the complete context string for a given company
    to be sent to the Language Model.
    """

    @inject
    def __init__(self,
                 sql_service: SqlService,
                 utility: Utility,
                 config_service: ConfigurationService):
        self.sql_service = sql_service
        self.utility = utility
        self.config_service = config_service

    def get_company_context(self, company_short_name: str) -> str:
        """
        Builds the full context by aggregating three sources:
        1. Static context files (Markdown).
        2. Static schema files (YAML files for SQL data sources).
        """
        context_parts = []

        # 1. Context from Markdown (context/*.md) and yaml (schema/*.yaml) files
        try:
            md_context = self._get_static_file_context(company_short_name)
            if md_context:
                context_parts.append(md_context)
        except Exception as e:
            logging.warning(f"Could not load Markdown context for '{company_short_name}': {e}")

        # 2. Context from company-specific database schemas (schema/*.yaml files)
        try:
            sql_context = self._get_sql_schema_context(company_short_name)
            if sql_context:
                context_parts.append(sql_context)
        except Exception as e:
            logging.warning(f"Could not generate SQL context for '{company_short_name}': {e}")

        # Join all parts with a clear separator
        return "\n\n---\n\n".join(context_parts)

    def _get_static_file_context(self, company_short_name: str) -> str:
        # Get context from .md and .yaml schema files.
        static_context = ''

        # Part 1: Markdown context files
        context_dir = f'companies/{company_short_name}/context'
        if os.path.exists(context_dir):
            context_files = self.utility.get_files_by_extension(context_dir, '.md', return_extension=True)
            for file in context_files:
                filepath = os.path.join(context_dir, file)
                static_context += self.utility.load_markdown_context(filepath)

        # Part 2: YAML schema files
        schema_dir = f'companies/{company_short_name}/schema'
        if os.path.exists(schema_dir):
            schema_files = self.utility.get_files_by_extension(schema_dir, '.yaml', return_extension=True)
            for file in schema_files:
                schema_name = file.split('.')[0]  # Use full filename as entity name
                filepath = os.path.join(schema_dir, file)
                static_context += self.utility.generate_context_for_schema(schema_name, filepath)

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
                db_manager = self.sql_service.get_database_manager(db_name)
            except IAToolkitException as e:
                logging.warning(f"Could not get DB manager for '{db_name}': {e}")
                continue

            db_description = source.get('description', '')
            sql_context = f'***Base de datos (database_name)***: {db_name}\n'
            sql_context += f"**Descripción:**: {db_description}\n" if db_description else ""
            sql_context += "Para consultar esta base de datos debes utilizar el servicio ***iat_sql_query***.\n"

            # 1. get the list of tables to process.
            tables_to_process = []
            if source.get('include_all_tables', False):
                all_tables = db_manager.get_all_table_names()
                tables_to_exclude = set(source.get('exclude_tables', []))
                tables_to_process = [t for t in all_tables if t not in tables_to_exclude]
            elif 'tables' in source:
                # if not include_all_tables, use the list of tables explicitly specified in the map.
                tables_to_process = list(source['tables'].keys())

            # 2. get the global settings and overrides.
            global_exclude_columns = source.get('exclude_columns', [])
            table_prefix = source.get('table_prefix')

            # get the global schema definition, for this source.
            global_schema_name = source.get('schema')

            table_overrides = source.get('tables', {})

            # 3. iterate over the tables.
            for table_name in tables_to_process:
                try:
                    # 4. get the table specific configuration.
                    table_config = table_overrides.get(table_name, {})

                    # 5. define the schema name, using the override if it exists.
                    # Priority 1: Explicit override from the 'tables' map.
                    schema_name = table_config.get('schema_name')

                    # Priority 2: Global schema defined in the source.
                    if not schema_name and global_schema_name:
                        schema_name = global_schema_name

                    if not schema_name:
                        # Priority 3: Automatic prefix stripping.
                        if table_prefix and table_name.startswith(table_prefix):
                            schema_name = table_name[len(table_prefix):]
                        else:
                            # Priority 4: Default to the table name itself.
                            schema_name = table_name

                    # 6. define the list of columns to exclude, (local vs. global).
                    local_exclude_columns = table_config.get('exclude_columns')
                    final_exclude_columns = local_exclude_columns if local_exclude_columns is not None else global_exclude_columns

                    # 7. get the table schema definition.
                    table_definition = db_manager.get_table_schema(
                        table_name=table_name,
                        schema_name=schema_name,
                        exclude_columns=final_exclude_columns
                    )
                    sql_context += table_definition
                except (KeyError, RuntimeError) as e:
                    logging.warning(f"Could not generate schema for table '{table_name}': {e}")

        return sql_context