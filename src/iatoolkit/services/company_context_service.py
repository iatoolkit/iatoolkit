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

    def get_company_context(self, company_short_name: str, *, selected_context_files: List[str] | None = None) -> str:
        blocks = self.get_company_context_blocks(
            company_short_name,
            selected_context_files=selected_context_files,
        )
        return "\n\n---\n\n".join(
            section
            for section in (
                blocks.get("markdown_context"),
                blocks.get("sql_context"),
                blocks.get("yaml_context"),
            )
            if section
        )

    def get_company_context_blocks(
        self,
        company_short_name: str,
        *,
        include_sql_context: bool = True,
        include_yaml_context: bool = True,
        selected_context_files: List[str] | None = None,
        allowed_databases: List[str] | None = None,
        table_filter=None,
    ) -> dict[str, str]:
        """
        Builds the full context by aggregating three sources:
        1. Static context files (Markdown).
        2. Physical SQL schemas and enriched metadata.
        3. Residual schema files (YAML files not already covered by SQL enrichment).
        """
        md_context = ""
        sql_context = ""
        yaml_context = ""
        db_tables = []

        # 1. Context from Markdown (context/*.md)  files
        try:
            md_context = self._get_static_file_context(
                company_short_name,
                selected_filenames=selected_context_files,
            ).strip()
        except Exception as e:
            logging.warning(f"Could not load Markdown context for '{company_short_name}': {e}")

        # 2. Resolve company-specific SQL databases. MCP can skip this expensive
        # schema expansion and expose SQL through dedicated schema/query tools.
        if include_sql_context:
            try:
                # allowed_databases: the sources this person may query (BL-010); None is all.
                sql_context, db_tables = self._get_sql_enriched_context(company_short_name,
                                                                        allowed_databases=allowed_databases,
                                                                        table_filter=table_filter)
                sql_context = sql_context.strip()
            except Exception as e:
                logging.warning(f"Could not generate SQL context for '{company_short_name}': {e}")

        # 3. Context from residual yaml (schema/*.yaml) files
        if include_yaml_context:
            try:
                yaml_schema_context = self._get_yaml_schema_context(
                    company_short_name,
                    db_tables,
                ).strip()
                if yaml_schema_context:
                    yaml_context = f"## Esquemas adicionales\n\n{yaml_schema_context}"
            except Exception as e:
                logging.warning(f"Could not load Yaml context for '{company_short_name}': {e}")

        return {
            "markdown_context": md_context,
            "sql_context": sql_context,
            "yaml_context": yaml_context,
        }

    def list_context_files(self, company_short_name: str) -> list[dict]:
        files = []
        for filename in self._list_context_markdown_filenames(company_short_name):
            title = ""
            preview = ""
            try:
                content = self.asset_repo.read_text(company_short_name, AssetType.CONTEXT, filename)
            except Exception as e:
                logging.warning(f"Error reading context file {filename}: {e}")
                content = ""

            for raw_line in str(content or "").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if not title and line.startswith("#"):
                    title = line.lstrip("#").strip()
                    continue
                if not preview:
                    preview = line
                if title and preview:
                    break

            files.append(
                {
                    "filename": filename,
                    "title": title or filename,
                    "preview": preview,
                }
            )
        return files

    def get_sql_context(self, company_short_name: str, allowed_databases: List[str] | None = None,
                        table_filter=None) -> str:
        try:
            sql_context, _ = self._get_sql_enriched_context(
                company_short_name,
                allowed_databases=allowed_databases,
                table_filter=table_filter,
            )
            return sql_context
        except Exception as e:
            logging.warning(f"Could not generate SQL context for '{company_short_name}': {e}")
            return ""

    def _resolve_allowed_tables_for_source(self, source: dict) -> set[str] | None:
        if bool(source.get("include_all_tables", True)):
            return None

        normalized_tables: set[str] = set()
        for table_name in source.get("included_tables") or []:
            normalized_tables.update(self._table_name_candidates(str(table_name or "")))
        return normalized_tables

    @classmethod
    def _table_is_allowed(cls, table_name: str, allowed_tables: set[str] | None) -> bool:
        if allowed_tables is None:
            return True
        if not allowed_tables:
            return False
        return bool(cls._table_name_candidates(table_name) & allowed_tables)

    @property
    def sql_catalog(self):
        """What of each SQL source a person sees (BL-017); built here, it reads this service's schema."""
        if getattr(self, "_sql_catalog", None) is None:
            from iatoolkit.services.sql_catalog_service import SqlCatalogService

            self._sql_catalog = SqlCatalogService(self, self.sql_source_service, self.sql_service)
        return self._sql_catalog

    def _get_sql_enriched_context(self, company_short_name: str, allowed_databases: List[str] | None = None,
                                  table_filter=None):
        """
        The SQL block of the base context: a map of each source the person may
        query, its tables with a one-line description and no columns (BL-017).

        The columns travel only when a question needs them, through
        `iat_sql_schema`: the whole schema in the base context was resent on
        every model call and never compacted (~33k tokens at Maxxa).
        Returns the block and the (db_name, table_name) pairs it covers.
        """
        sources = self.sql_catalog.sources(
            company_short_name, allowed_databases=allowed_databases, table_filter=table_filter,
        )
        db_tables = [
            {"db_name": source["database_key"], "table_name": table["name"]}
            for source in sources
            for table in source["tables"]
        ]
        return self.sql_catalog.render_map(sources), db_tables

    def _get_yaml_schema_context(
        self,
        company_short_name: str,
        db_tables: List[Dict],
    ) -> str:
        # Get context from .yaml schema files using the repository
        yaml_schema_context = ''

        try:
            # 1. List yaml files in the schema "folder"
            schema_files = self.asset_repo.list_files(company_short_name, AssetType.SCHEMA, extension='.yaml')

            # A `<db>-<table>.yaml` of a configured SQL source belongs to the SQL
            # schema, never to this block: it reaches the model through the
            # catalogue (map + iat_sql_schema), which applies every filter. Read
            # here, a table hidden from a person (a knowledge table they may not
            # use) came back whole as an "additional schema".
            sql_source_names = self._configured_sql_source_names(company_short_name)

            for filename in schema_files:
                if '-' in filename:
                    dbname = self._normalize_identifier(filename.split("-", 1)[0])
                    if dbname in sql_source_names:
                        continue

                try:
                    # 2. Read content
                    content = self.asset_repo.read_text(company_short_name, AssetType.SCHEMA, filename)

                    # 3. Parse YAML content into a dict
                    schema_dict = self.utility.load_yaml_from_string(content)

                    # 4. Generate markdown description from the dict
                    if schema_dict:
                        # We use generate_schema_table which accepts a dict directly
                        yaml_schema_context += self.generate_schema_table(schema_dict) + "\n\n"

                except Exception as e:
                    logging.warning(f"Error processing schema file {filename}: {e}")

        except Exception as e:
            logging.warning(f"Error listing schema files for {company_short_name}: {e}")

        return yaml_schema_context

    def _configured_sql_source_names(self, company_short_name: str) -> set[str]:
        """Every SQL source of the company, active or not, by normalized name."""
        try:
            sources = self.sql_source_service.list_sources(company_short_name, include_inactive=True) or []
        except Exception as e:
            logging.warning(f"Could not list the SQL sources of '{company_short_name}': {e}")
            return set()
        return {self._normalize_identifier(s.get("database")) for s in sources if s.get("database")}

    def generate_schema_table(self, schema: dict) -> str:
        if not schema or not isinstance(schema, dict):
            return ""

        # root detection
        keys = list(schema.keys())
        if not keys:
            return ""

        root_name = keys[0]
        root_data = schema[root_name]
        output = [f"### Objeto: `{root_name}`"]

        # table description
        root_description = root_data.get('description', '')
        if root_description:
            clean_desc = root_description.replace('\n', ' ').strip()
            output.append(f"- Descripcion: {clean_desc}")

        # extract columns and properties from the root object
        # priority: columns > properties > fields
        properties = root_data.get('columns', root_data.get('properties', {}))
        if properties:
            output.append("#### Estructura de datos")

            # use indent_level 0 for the main columns
            # call recursive function to format the properties
            output.append(self._format_json_schema(properties, 0))
        else:
            output.append("_Sin definicion de estructura._")

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


    def _get_static_file_context(self, company_short_name: str, *, selected_filenames: List[str] | None = None) -> str:
        # Get context from .md files using the repository
        static_context = ''

        try:
            for filename in self._resolve_context_filenames(
                company_short_name,
                selected_filenames=selected_filenames,
            ):
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

    def _list_context_markdown_filenames(self, company_short_name: str) -> list[str]:
        try:
            md_files = self.asset_repo.list_files(company_short_name, AssetType.CONTEXT, extension='.md')
        except Exception as e:
            logging.warning(f"Error listing context files for {company_short_name}: {e}")
            return []
        normalized_files = []
        for filename in md_files or []:
            value = str(filename or "").strip()
            if value and value not in normalized_files:
                normalized_files.append(value)
        return sorted(normalized_files)

    def _resolve_context_filenames(
        self,
        company_short_name: str,
        *,
        selected_filenames: List[str] | None = None,
    ) -> list[str]:
        available_files = self._list_context_markdown_filenames(company_short_name)
        if selected_filenames is None:
            return available_files

        allowed_files = set(available_files)
        ordered_selection = []
        for filename in selected_filenames or []:
            value = str(filename or "").strip()
            if value and value in allowed_files and value not in ordered_selection:
                ordered_selection.append(value)
        return ordered_selection

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

    def get_enriched_database_schema(self, company_short_name: str, db_name: str, *, fresh: bool = False) -> dict:
        """
        Retrieves the physical database structure and enriches it with metadata
        found in the AssetRepository (YAML files). The structure is cached for a
        few minutes (SqlService); `fresh` reads it from the database.
        """
        try:
            # 1. Physical Structure (Real Source)
            structure = self.sql_service.get_database_structure(company_short_name, db_name, fresh=fresh)

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
                database_prefix = f"{normalized_db_name}-"
                if not clean.startswith(database_prefix):
                    continue
                table = clean[len(database_prefix):]
                if not table:
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

                                # C. inject the JSON schema metadata from the YAML.
                                # Bundles use the explicit json_schema wrapper while
                                # legacy schema files keep properties/items directly.
                                json_schema = y_col.get('json_schema')
                                if isinstance(json_schema, dict):
                                    col['json_schema'] = json_schema

                                props = y_col.get('properties')
                                if not props and isinstance(json_schema, dict):
                                    props = json_schema.get('properties')
                                if props:
                                    col['properties'] = props

                                items = y_col.get('items')
                                if not items and isinstance(json_schema, dict):
                                    items = json_schema.get('items')
                                if items:
                                    col['items'] = items
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
