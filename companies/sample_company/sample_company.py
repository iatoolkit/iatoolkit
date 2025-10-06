# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit import IAToolkit, BaseCompany, Company, Function, PromptCategory
from iatoolkit import ProfileRepo, LLMQueryRepo, PromptService, DatabaseManager
from iatoolkit import SqlService, LoadDocumentsService, SearchService
from injector import inject
from companies.sample_company.configuration import FUNCTION_LIST
from companies.sample_company.sample_database import SampleCompanyDatabase
import os
import click
import logging


class SampleCompany(BaseCompany):
    @inject
    def __init__(self,
            profile_repo: ProfileRepo,
            llm_query_repo: LLMQueryRepo,
            prompt_service: PromptService,
            sql_service: SqlService,
            search_service: SearchService):
        super().__init__(profile_repo, llm_query_repo)
        self.sql_service = sql_service
        self.search_service = search_service
        self.prompt_service = prompt_service
        self.sample_db_manager = None
        self.sample_database = None

        # set the company object
        self.company = self.profile_repo.get_company_by_short_name('sample_company')

        # connect to Internal database
        sample_db_uri = os.getenv('NORTHWIND_DATABASE_URI')
        if not sample_db_uri:
            # if not exists use the same iatoolkit database
            sample_db_uri = os.getenv('DATABASE_URI')

        if sample_db_uri:
            self.sample_db_manager = DatabaseManager(sample_db_uri, register_pgvector=False)
            self.sample_database = SampleCompanyDatabase(self.sample_db_manager)

    def register_company(self):
        # Initialize the company in the database if not exists
        c = Company(name='Sample Company',
                    short_name='sample_company',
                    allow_jwt=True,
                    parameters={})

        # set the company object
        self.company = self.profile_repo.create_company(c)

        # create or update the function list
        for function in FUNCTION_LIST:
            self.llm_query_repo.create_or_update_function(
                Function(
                    company_id=self.company.id,
                    name=function['function_name'],
                    description=function['description'],
                    parameters=function['params'],
                    system_function=False
                )
            )

            c_general = self.llm_query_repo.create_or_update_prompt_category(
                PromptCategory(name='General', order=1, company_id=self.company.id))

            c_comercial = self.llm_query_repo.create_or_update_prompt_category(
                PromptCategory(name='Comercial', order=2, company_id=self.company.id))

            prompt_list = [
                {
                    'name': 'analisis_ventas',
                    'description': 'Analisis de ventas',
                    'category': c_general,
                    'order': 1,
                    'custom_fields': [
                        {
                            "id": "sales_id_input_from",
                            "label": "Fecha desde",
                            "placeholder": "desde ...",
                            "type": "date",
                            "data_key": "fecha_inicio"
                        },
                        {
                            "id": "sales_id_input_to",
                            "label": "Fecha hasta",
                            "placeholder": "hasta...",
                            "type": "date",
                            "data_key": "fecha_fin"
                        }
                    ]
                },
                {
                    'name': 'supplier_report',
                    'description': 'Análisis de proveedores',
                    'category': c_general,
                    'order': 2,
                    'custom_fields': [
                        {
                            "id": "supplier_id_input",
                            "label": "Identificador del Proveedor",
                            "placeholder": "Ingrese nombre del proveedor...",
                            "type": "text",
                            "data_key": "supplier_id"
                        }
                    ]
                }
            ]

            # create the company prompts
            for prt in prompt_list:
                self.prompt_service.create_prompt(
                    prompt_name=prt['name'],
                    description=prt['description'],
                    order=prt['order'],
                    company=self.company,
                    category=prt['category'],
                    active=prt.get('active', True),
                    custom_fields=prt.get('custom_fields', [])
                )

    # Return a global context used by this company: business description, schemas, database models
    def get_company_context(self, **kwargs) -> str:
        company_context = ''
        if self.sample_db_manager:
            company_context += self.get_schema_definitions(self.sample_db_manager)

        return company_context

    def start_execution(self) -> dict:
        return {}

    def get_metadata_from_filename(self, filename: str) -> dict:
        if filename.startswith('contract_'):
            return {'type': 'employee_contract'}
        return {}

    def handle_request(self, action: str, **kwargs) -> str:
        if action == "sql_query":
            sql_query = kwargs.get('query')
            return self.sql_service.exec_sql(self.sample_db_manager, sql_query)
        elif action == "document_search":
            query_string = kwargs.get('query')
            return self.search_service.search(self.company.id, query_string)
        else:
            return self.unsupported_operation(action)

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

    def get_schema_definitions(self, db_manager: DatabaseManager) -> str:
        """
        Genera las definiciones de esquema para todas las tablas del modelo.
        """
        model_tables = [
            {'table_name': 'products', 'schema_name': 'product'},
            {'table_name': 'regions', 'schema_name': 'region'},
            {'table_name': 'shippers', 'schema_name': 'shipper'},
            {'table_name': 'suppliers', 'schema_name': 'supplier'},
            {'table_name': 'categories', 'schema_name': 'category'},
            {'table_name': 'customers', 'schema_name': 'customer' },
            {'table_name': 'territories', 'schema_name': 'territory'},
            {'table_name': 'employees', 'schema_name': 'employee'},
            {'table_name': 'employee_territories', 'schema_name': 'employee_territory' },
            {'table_name': 'orders', 'schema_name': 'order' },
            {'table_name': 'order_details', 'schema_name': 'order_detail'},

        ]

        db_context = ''
        for table in model_tables:
            try:
                table_definition = db_manager.get_table_schema(
                    table_name=table['table_name'],
                    schema_name=table['schema_name'],
                    exclude_columns=[]
                )
                db_context += table_definition
            except RuntimeError as e:
                logging.warning(f"Advertencia al generar esquema para {table['table_name']}: {e}")

        return db_context

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
                    click.echo(f'folder {doc["folder"]}:  {result} dodumentos procesados exitosamente.')
                except Exception as e:
                    logging.exception(e)
                    click.echo(f"Error: {str(e)}")




