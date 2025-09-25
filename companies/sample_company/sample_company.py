# Copyright (c) 2024 Fernando Libedinsky
# Producto: IAToolkit
# Todos los derechos reservados.
# En trámite de registro en el Registro de Propiedad Intelectual de Chile.

from iatoolkit import Company, Function
from iatoolkit import ProfileRepo
from iatoolkit import LLMQueryRepo
from iatoolkit import DatabaseManager
from iatoolkit import SqlService
from iatoolkit import BaseCompany
from injector import inject
from companies.sample_company.configuration import FUNCTION_LIST
import os


class SampleCompany(BaseCompany):
    @inject
    def __init__(self,
            profile_repo: ProfileRepo,
            llm_query_repo: LLMQueryRepo,
            sql_service: SqlService):
        super().__init__(profile_repo, llm_query_repo)
        self.sql_service = sql_service

        # connect to Internal database
        sample_db_uri = os.getenv('SAMPLE_DATABASE_URI')
        if sample_db_uri:
            self.sample_db_manager = DatabaseManager(sample_db_uri, register_pgvector=False)

    def register_company(self):
        # Initialize the company in the database if not exists
        c = Company(name='Sample Company',
                    short_name='sample_company',
                    allow_jwt=True,
                    parameters={})
        c = self.profile_repo.create_company(c)

        # create or update the function list
        for function in FUNCTION_LIST:
            self.llm_query_repo.create_or_update_function(
                Function(
                    company_id=c.id,
                    name=function['function_name'],
                    description=function['description'],
                    parameters=function['params']
                )
            )

    # Return a global context used by this company: business description, schemas, database models
    def get_company_context(self, **kwargs) -> str:
        company_context = 'simplemente una empresa de banca de cajas.'
        # add the schema for the bcu tables
        # if self.sample_db_manager:
        #     company_context += self.load_sample_schema()

        return company_context

    def start_execution(self) -> dict:
        return {}

    def get_metadata_from_filename(self, filename: str) -> dict:
        return {}

    def handle_request(self, action: str, **kwargs) -> str:
        if action == "sql_query":
            sql_query = kwargs.get('query')
            return self.sql_service.exec_sql(self.sample_db_manager, sql_query)
        else:
            return self.unsupported_operation(action)

    def get_user_info(self, **kwargs) -> dict:
        user_id = kwargs.get('user_id', '')
        return {'user_name': user_id,
                'user_full_name': 'Sample User',
                'user_email': 'fernando.libedinsky@gmail.com'
                }

    def load_sample_schema(self):
        # each one of these entries must be a database table and
        # the schema that describes it in /schema
        model_tables = [
            {'table_name': 'bcu_customer', 'schema_name': 'client'},
            {'table_name': 'bcu_certificate', 'schema_name': 'certificate'},
         ]

        db_context = ''
        for table in model_tables:
            table_definition = self.sample_db_manager.get_table_schema(
                        table_name=table['table_name'],
                        schema_name=table['schema_name'],
                        exclude_columns=['id', 'created', 'updated']
                        )
            db_context += table_definition

        return db_context
