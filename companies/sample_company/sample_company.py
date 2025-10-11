# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit import IAToolkit, BaseCompany, DatabaseManager
from iatoolkit import SqlService, LoadDocumentsService, SearchService
from injector import inject
from companies.sample_company.configuration import FUNCTION_LIST, PROMPT_LIST
from companies.sample_company.sample_database import SampleCompanyDatabase
import os
import click
import logging


class SampleCompany(BaseCompany):
    @inject
    def __init__(self,
            sql_service: SqlService,
            search_service: SearchService):
        super().__init__()
        self.sql_service = sql_service
        self.search_service = search_service
        self.sample_db_manager = None
        self.sample_database = None

        # set the company object
        self._load_company_by_short_name('sample_company')

        # connect to Internal database
        sample_db_uri = os.getenv('NORTHWIND_DATABASE_URI')
        if not sample_db_uri:
            # if not exists use the same iatoolkit database
            sample_db_uri = os.getenv('DATABASE_URI')

        if sample_db_uri:
            self.sample_db_manager = DatabaseManager(sample_db_uri, register_pgvector=False)
            self.sample_database = SampleCompanyDatabase(self.sample_db_manager)

    def handle_request(self, action: str, **kwargs) -> str:
        if action == "sql_query":
            sql_query = kwargs.get('query')
            return self.sql_service.exec_sql(self.sample_db_manager, sql_query)
        elif action == "document_search":
            query_string = kwargs.get('query')
            return self.search_service.search(self.company.id, query_string)
        else:
            return self.unsupported_operation(action)

    def register_company(self):
        # Initialize the company in the database if not exists

        # 1. define the branding style
        sample_company_branding = {
            "header_background_color": "#EFF6FF",  # Un azul pastel muy claro
            "header_text_color": "#1E3A8A",  # Un azul oscuro y profesional
            "primary_font_weight": "600",  # Semibold, para un look refinado
            "primary_font_size": "1.1rem",  # Ligeramente más grande para jerarquía

            # for modals and buttons
            "brand_primary_color": "#1E3A8A",  # Mismo azul oscuro del texto para consistencia
            "brand_text_on_primary": "#FFFFFF",  # Texto blanco para el botón primario
            "brand_secondary_color": "#6c757d",  # Un gris neutro y profesional para acciones secundarias
            "brand_text_on_secondary": "#FFFFFF",  # Texto blanco para el botón secundario
        }


        self.company = self._create_company(
            name='Sample Company',
            short_name='sample_company',
            branding=sample_company_branding
        )

        # create or update the function list
        for function in FUNCTION_LIST:
            self._create_function(
                function_name=function['function_name'],
                description=function['description'],
                params=function['params']
            )

        c_general = self._create_prompt_category(name='General', order=1)

        # create the company prompts
        for prt in PROMPT_LIST:
            self._create_prompt(
                prompt_name=prt['name'],
                description=prt['description'],
                order=prt['order'],
                category=c_general,
                active=prt.get('active', True),
                custom_fields=prt.get('custom_fields', [])
            )
            
    # Return company specific context
    def get_company_context(self, **kwargs) -> str:
        if not self.sample_db_manager:
            return ''

        # this list should contain all the tables that are used
        # by this company and the schema file for the table.
        # the schema should exist in the schema folder.
        database_tables = [
            {'table_name': 'products', 'schema_name': 'product'},
            {'table_name': 'regions', 'schema_name': 'region'},
            {'table_name': 'shippers', 'schema_name': 'shipper'},
            {'table_name': 'suppliers', 'schema_name': 'supplier'},
            {'table_name': 'categories', 'schema_name': 'category'},
            {'table_name': 'customers', 'schema_name': 'customer'},
            {'table_name': 'territories', 'schema_name': 'territory'},
            {'table_name': 'employees', 'schema_name': 'employee'},
            {'table_name': 'employee_territories', 'schema_name': 'employee_territory'},
            {'table_name': 'orders', 'schema_name': 'order'},
            {'table_name': 'order_details', 'schema_name': 'order_detail'},

        ]

        db_context = ''
        for table in database_tables:
            try:
                table_definition = self.sample_db_manager.get_table_schema(
                    table_name=table['table_name'],
                    schema_name=table['schema_name'],
                    exclude_columns=[]
                )
                db_context += table_definition
            except RuntimeError as e:
                logging.warning(f"Advertencia al generar esquema para {table['table_name']}: {e}")

        return db_context


    def start_execution(self) -> dict:
        return {}

    def get_metadata_from_filename(self, filename: str) -> dict:
        if filename.startswith('contract_'):
            return {'type': 'employee_contract'}
        return {}

    def get_user_info(self, user_identifier: str) -> dict:
        user_data = {
            "id": user_identifier,
            "user_email": 'sample@sample_company.com',
            "user_fullname": 'Sample User',
            "company_id": self.company.id,
            "company_name": self.company.name,
            "company_short_name": self.company.short_name,
            "is_local": False,
            "extras": {}
        }
        return user_data


    def register_cli_commands(self, app):

        @app.cli.command("populate-database")
        def populate_sample_db():
            """📦 Crea y puebla la base de datos de sample_company."""
            if not self.sample_database:
                click.echo("❌ Error: La base de datos no está configurada.")
                click.echo("👉 Asegúrate de que 'SAMPLE_DATABASE_URI' esté definida en tu entorno.")
                return

            try:
                click.echo(
                    "⚙️  Creando y poblando la base de datos, esto puede tardar unos momentos...")
                self.sample_database.create_database()
                self.sample_database.populate_from_excel('companies/sample_company/sample_data/northwind.xlsx')
                click.echo("✅ Base de datos de poblada exitosamente.")
            except Exception as e:
                logging.exception(e)
                click.echo(f"❌ Ocurrió un error inesperado: {e}")

        @app.cli.command("load")
        def load_documents():
            if os.getenv('FLASK_ENV') == 'dev':
                connector_config = {'type': 'local', 'path': "" }

            else:
                connector_config = {'type': 's3',
                                  'bucket': "iatoolkit",
                                  'prefix': 'sample_company'}

            load_documents_service = IAToolkit.get_instance().get_injector().get(LoadDocumentsService)

            # documents are loaded from 2 different folders
            # as a sample, only add metadata 'type' for one of them: supplier_manual
            # for the other one, we will add metadata from the filename in get_metadata_from_filename method
            # metadata es optional always
            types_to_load = [
                {'type': 'supplier_manual', 'folder': 'supplier_manuals'},
                {'folder': 'employee_contracts'}
                ]

            for doc in types_to_load:
                connector_config['path'] = f"companies/sample_company/sample_data/{doc['folder']}"
                try:
                    predefined_metadata = {'type': doc['type']} if 'type' in doc else {}
                    result = load_documents_service.load_company_files(
                        company=self.company,
                        connector_config=connector_config,
                        predefined_metadata=predefined_metadata,
                        filters={"filename_contains": ".pdf"})
                    click.echo(f'folder {doc["folder"]}:  {result} documentos procesados exitosamente.')
                except Exception as e:
                    logging.exception(e)
                    click.echo(f"Error: {str(e)}")




