# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.util import Utility
from iatoolkit.services.configuration_service import ConfigurationService
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.services.sql_service import SqlService
import logging
import yaml
from injector import inject
from typing import List, Dict
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
        db_tables = []
        try:
            sql_context, db_tables = self._get_sql_enriched_context(company_short_name)
            if sql_context:
                context_parts.append(sql_context)
        except Exception as e:
            logging.warning(f"Could not generate SQL context for '{company_short_name}': {e}")

        # 3. Context from yaml (schema/*.yaml) files
        try:
            yaml_schema_context = self._get_yaml_schema_context(company_short_name, db_tables)
            if yaml_schema_context:
                context_parts.append(yaml_schema_context)
        except Exception as e:
            logging.warning(f"Could not load Yaml context for '{company_short_name}': {e}")

        # Join all parts with a clear separator
        return "\n\n---\n\n".join(context_parts)


    def _get_sql_enriched_context(self, company_short_name: str):
        """
        Generates the SQL context for the LLM using the enriched schema logic.
        It iterates over configured databases, fetches their enriched structure,
        and formats it into a prompt-friendly string.
        """
        data_sources_config = self.config_service.get_configuration(company_short_name, 'data_sources')
        if not data_sources_config or not data_sources_config.get('sql'):
            return '', []

        context_output = []
        db_tables=[]

        for source in data_sources_config.get('sql', []):
            logging.error(f"COMPANY_CONTEXT_SERVICE SOURCE: {source}")
            db_name = source.get('database')
            if not db_name:
                continue

            try:
                # 1. Get the Enriched Schema (Physical + YAML)
                enriched_structure = self.get_enriched_database_schema(company_short_name, db_name)
                if not enriched_structure:
                    continue

                # 2. Build Header for this Database
                db_context = f"***Database (`database_key`)***: {db_name}\n"

                # Optional: Add DB description from config if available (useful context)
                db_desc = source.get('description', '')
                if db_desc:
                    db_context += f"**Description:** {db_desc}\n"

                db_context += (
                    f"IMPORTANT: To query this database you MUST use the service/tool "
                    f"**iat_sql_query**, with `database_key='{db_name}'`.\n"
                )

                # 3. Format Tables
                for table_name, table_data in enriched_structure.items():
                    table_desc = table_data.get('description', '')
                    columns = table_data.get('columns', [])

                    # Table Header
                    table_str = f"\nTable: **{table_name}**"
                    if table_desc:
                        table_str += f"\nDescription: {table_desc}"

                    table_str += "\nColumns:"

                    # Format Columns
                    for col in columns:
                        col_name = col.get('name')
                        col_type = col.get('type', 'unknown')
                        col_desc = col.get('description', '')
                        col_props = col.get('properties') # Nested JSONB structure

                        col_line = f"\n  - `{col_name}` ({col_type})"
                        if col_desc:
                            col_line += f": {col_desc}"

                        table_str += col_line

                        # If it has nested properties (JSONB enriched from YAML), format them
                        if col_props:
                            table_str += "\n"
                            table_str += self._format_json_schema(col_props, 2) # Indent level 2

                    db_context += table_str

                    # collect the table names for later use
                    db_tables.append(
                        {'db_name': db_name,
                         'table_name': table_name,
                         }
                    )

                context_output.append(db_context)

            except Exception as e:
                logging.warning(f"Could not generate enriched SQL context for '{db_name}': {e}")

        if not context_output:
            return "", []

        header = "These are the SQL databases you can query using the **`iat_sql_service`**. The schema below includes enriched metadata:\n"
        return header + "\n\n---\n\n".join(context_output), db_tables


    def _get_yaml_schema_context(self, company_short_name: str, db_tables: List[Dict]) -> str:
        # Get context from .yaml schema files using the repository
        yaml_schema_context = ''

        try:
            # 1. List yaml files in the schema "folder"
            schema_files = self.asset_repo.list_files(company_short_name, AssetType.SCHEMA, extension='.yaml')

            for filename in schema_files:
                # skip tables that are already in the SQL context
                if '-' in filename:
                    dbname, f = filename.split("-", 1)
                    table_name = f.split('.')[0]

                    exists = any(
                        item["db_name"] == dbname and item["table_name"] == table_name
                        for item in db_tables
                    )
                    if exists:
                        continue

                try:
                    # 2. Read content
                    content = self.asset_repo.read_text(company_short_name, AssetType.SCHEMA, filename)

                    # 3. Parse YAML content into a dict
                    schema_dict = self.utility.load_yaml_from_string(content)

                    # 4. Generate markdown description from the dict
                    if schema_dict:
                        # We use generate_schema_table which accepts a dict directly
                        yaml_schema_context += self.generate_schema_table(schema_dict)

                except Exception as e:
                    logging.warning(f"Error processing schema file {filename}: {e}")

        except Exception as e:
            logging.warning(f"Error listing schema files for {company_short_name}: {e}")

        return yaml_schema_context

    def generate_schema_table(self, schema: dict) -> str:
        if not schema or not isinstance(schema, dict):
            return ""

        # root detection
        keys = list(schema.keys())
        if not keys:
            return ""

        root_name = keys[0]
        root_data = schema[root_name]
        output = [f"\n### Objeto: `{root_name}`"]

        # table description
        root_description = root_data.get('description', '')
        if root_description:
            clean_desc = root_description.replace('\n', ' ').strip()
            output.append(f"##Descripción:  {clean_desc}")

        # extract columns and properties from the root object
        # priority: columns > properties > fields
        properties = root_data.get('columns', root_data.get('properties', {}))
        if properties:
            output.append("**Estructura de Datos:**")

            # use indent_level 0 for the main columns
            # call recursive function to format the properties
            output.append(self._format_json_schema(properties, 0))
        else:
            output.append("\n_Sin definición de estructura._")

        return "\n".join(output)

    def _format_json_schema(self, properties: dict, indent_level: int) -> str:
        output = []
        indent_str = '  ' * indent_level

        if not isinstance(properties, dict):
            return ""

        for name, details in properties.items():
            if not isinstance(details, dict): continue

            description = details.get('description', '')
            data_type = details.get('type', 'any')

            # NORMALIZACIÓN VISUAL: jsonb -> object
            if data_type and data_type.lower() == 'jsonb':
                data_type = 'object'

            line = f"{indent_str}- **`{name}`**"
            if data_type:
                line += f" ({data_type})"
            if description:
                clean_desc = description.replace('\n', ' ').strip()
                line += f": {clean_desc}"

            output.append(line)

            # Recursividad: buscar hijos en 'properties', 'fields' o 'columns'
            children = details.get('properties', details.get('fields'))

            # Caso Array (items -> properties)
            if not children and details.get('items'):
                items = details['items']
                if isinstance(items, dict):
                    if items.get('description'):
                        output.append(f"{indent_str}  _Items: {items['description']}_")
                    children = items.get('properties', items.get('fields'))

            if children:
                output.append(self._format_json_schema(children, indent_level + 1))

        return "\n".join(output)


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

    def get_enriched_database_schema(self, company_short_name: str, db_name: str) -> dict:
        """
        Retrieves the physical database structure and enriches it with metadata
        found in the AssetRepository (YAML files).
        """
        try:
            # 1. Physical Structure (Real Source)
            structure = self.sql_service.get_database_structure(company_short_name, db_name)

            # 2. YAML files
            available_files = self.asset_repo.list_files(company_short_name, AssetType.SCHEMA)
            files_map = {}
            for f in available_files:
                clean = f.lower().replace('.yaml', '').replace('.yml', '')
                if '-' not in clean:
                    continue            # skip non-table files

                dbname, table = clean.split("-", 1)
                # filter by the database
                if dbname != db_name:
                    continue
                files_map[table] = f

            logging.debug(f"🔍 [CompanyContextService] Enriching schema for {db_name}. Files found: {len(files_map)}")

            # 3. fusion between physical structure and YAML files
            for table_name, table_data in structure.items():
                t_name = table_name.lower().strip()

                real_filename = files_map.get(t_name)
                if not real_filename:
                    continue

                try:
                    content = self.asset_repo.read_text(company_short_name, AssetType.SCHEMA, real_filename)
                    if not content:
                        continue

                    meta = yaml.safe_load(content) or {}

                    # detect root, usually table name
                    root_data = meta.get(table_name) or meta.get(t_name)
                    if not root_data and len(meta) == 1:
                        root_data = list(meta.values())[0]

                    if not root_data:
                        continue

                    # A. Table description
                    if 'description' in root_data:
                        table_data['description'] = root_data['description']

                    # B. get the map of columns from the YAML
                    yaml_cols = root_data.get('columns', root_data.get('fields', {}))

                    # --- LEGACY ADAPTER: List -> Dictionary ---
                    if isinstance(yaml_cols, list):
                        temp_map = {}
                        for c in yaml_cols:
                            if isinstance(c, dict) and 'name' in c:
                                col_name = c['name']
                                temp_map[col_name] = c
                        yaml_cols = temp_map
                    # --------------------------------------------

                    if isinstance(yaml_cols, dict):
                        # map in lower case for lookup
                        y_cols_lower = {str(k).lower(): v for k, v in yaml_cols.items()}

                        # Iterate over columns
                        for col in table_data.get('columns', []):
                            c_name = str(col['name']).lower()  # Real DB Name

                            if c_name in y_cols_lower:
                                y_col = y_cols_lower[c_name]

                                # copy the basic metadata from database
                                if y_col.get('description'): col['description'] = y_col['description']
                                if y_col.get('pii'): col['pii'] = y_col['pii']
                                if y_col.get('synonyms'): col['synonyms'] = y_col['synonyms']

                                # C. inject the json schema from the YAML
                                props = y_col.get('properties')
                                if props:
                                    col['properties'] = props
                    else:
                        if yaml_cols:
                            logging.warning(f"⚠️ [CompanyContextService] Unrecognized column format in {real_filename}")

                except Exception as e:
                    logging.error(f"❌ Error processing schema file {real_filename}: {e}")

            return structure

        except Exception as e:
            logging.exception(f"Error generating enriched schema for {db_name}")
            # Depending on policy, re-raise or return empty structure
            raise e

