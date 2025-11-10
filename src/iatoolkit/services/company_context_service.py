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
        2. Static schema files (YAML for APIs, etc.).
        3. Dynamic SQL database schema from the live connection.
        """
        context_parts = []

        # 1. Context from Markdown (context/*.md) and yaml (schema/*.yaml) files
        try:
            md_context = self._get_static_file_context(company_short_name)
            if md_context:
                context_parts.append(md_context)
        except Exception as e:
            logging.warning(f"Could not load Markdown context for '{company_short_name}': {e}")

        # 2. Context from company-specific Python logic (SQL schemas)
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
        # generate schema from the live DB connection.
        # get the configuration for 'data_sources' from the ConfigurationService
        data_sources_config = self.config_service.get_company_content(company_short_name, 'data_sources')
        if not data_sources_config or not data_sources_config.get('sql'):
            return ''       # No SQL data sources configured for this company

        sql_context = ''
        sql_sources = data_sources_config.get('sql', [])

        # iterate over all SQL sources defined in the YAML configuration
        for source in sql_sources:
            db_name = source.get('database')
            if not db_name:
                continue

            try:
                # get a handle to the DB manager
                db_manager = self.sql_service.get_database_manager(db_name)
            except IAToolkitException as e:
                logging.warning(f"Could not get DB manager for '{db_name}': {e}")
                continue

            db_description = source.get('description', '')
            sql_context += f"{db_description}\n" if db_description else ""

            # iterate over all tables defined in the SQL source
            for table_info in source.get('tables', []):
                try:
                    table_name = table_info['table_name']

                    # if schema_name is not defined, use table_name as default value.
                    schema_name = table_info.get('schema_name', table_name)

                    # get the schema definition for the table, using ispector
                    table_definition = db_manager.get_table_schema(
                        table_name=table_name,
                        schema_name=schema_name,
                        exclude_columns=[]
                    )
                    sql_context += table_definition
                except (KeyError, RuntimeError) as e:
                    logging.warning(f"Could not generate schema for table '{table_info.get('table_name')}': {e}")

        return sql_context