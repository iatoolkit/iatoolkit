# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit.common.util import Utility
from iatoolkit.common.interfaces.asset_storage import AssetRepository, AssetType
from iatoolkit.services.sql_source_service import SqlSourceService
from iatoolkit.services.sql_service import SqlService
import logging
import yaml
from injector import inject
from typing import List, Dict


class CompanyContextService:
    """
    Responsible for building the complete context string for a given company
    to be sent to the Language Model.
    """

    @inject
    def __init__(self,
                 sql_service: SqlService,
                 utility: Utility,
                 sql_source_service: SqlSourceService,
                 asset_repo: AssetRepository):
        self.sql_service = sql_service
        self.utility = utility
        self.sql_source_service = sql_source_service
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
        sql_sources = self.sql_source_service.list_sources(company_short_name, include_inactive=False)
        if not sql_sources:
            return '', []

        context_output = []
        db_tables=[]

        for source in sql_sources:
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

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        if value is None:
            return ""
        return str(value).strip().strip('"').strip("'").lower()

    @classmethod
    def _table_name_candidates(cls, table_name: str) -> set[str]:
        normalized = cls._normalize_identifier(table_name)
        if not normalized:
            return set()

        candidates = {normalized}
        if "." in normalized:
            candidates.add(normalized.split(".")[-1])
        return candidates

    @classmethod
    def _resolve_schema_filename_for_table(cls, files_map: dict, table_name: str) -> str | None:
        for candidate in cls._table_name_candidates(table_name):
            if candidate in files_map:
                return files_map[candidate]
        return None

    @classmethod
    def _resolve_yaml_root_data(cls, meta: dict, table_name: str) -> dict | None:
        if not isinstance(meta, dict) or not meta:
            return None

        table_candidates = cls._table_name_candidates(table_name)

        # 1) Standard: root key equals table name (possibly qualified/unqualified)
        for candidate in table_candidates:
            node = meta.get(candidate)
            if isinstance(node, dict):
                return node

        lowered_meta_keys = {
            cls._normalize_identifier(k): v
            for k, v in meta.items()
            if isinstance(v, dict)
        }
        for candidate in table_candidates:
            node = lowered_meta_keys.get(candidate)
            if isinstance(node, dict):
                return node

        # 2) Legacy fallback: single root object
        if len(meta) == 1:
            only_value = list(meta.values())[0]
            if isinstance(only_value, dict):
                return only_value

        # 3) Flat format: top-level "table/schema/columns/..." definition
        yaml_cols = meta.get("columns", meta.get("fields"))
        if isinstance(yaml_cols, (dict, list)):
            declared_table = cls._normalize_identifier(meta.get("table") or meta.get("name"))
            if not declared_table:
                return meta

            declared_candidates = cls._table_name_candidates(declared_table)
            if declared_candidates & table_candidates:
                return meta

        return None

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
            normalized_db_name = self._normalize_identifier(db_name)
            for f in available_files:
                clean = str(f).strip().lower()
                if clean.endswith('.yaml'):
                    clean = clean[:-5]
                elif clean.endswith('.yml'):
                    clean = clean[:-4]
                if '-' not in clean:
                    continue            # skip non-table files

                dbname, table = clean.split("-", 1)
                # filter by the database
                if dbname != normalized_db_name:
                    continue
                for table_candidate in self._table_name_candidates(table):
                    files_map[table_candidate] = f

            logging.debug(f"🔍 [CompanyContextService] Enriching schema for {db_name}. Files found: {len(files_map)}")

            # 3. fusion between physical structure and YAML files
            for table_name, table_data in structure.items():
                real_filename = self._resolve_schema_filename_for_table(files_map, table_name)
                if not real_filename:
                    continue

                try:
                    content = self.asset_repo.read_text(company_short_name, AssetType.SCHEMA, real_filename)
                    if not content:
                        continue

                    meta = yaml.safe_load(content) or {}

                    # detect root in standard nested or flat schema formats
                    root_data = self._resolve_yaml_root_data(meta, table_name)
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
