# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit import BaseCompany
from iatoolkit import KnowledgeBaseService, SqlService
from injector import inject
from companies.sample_company.sample_database import SampleCompanyDatabase
import click
import logging


class SampleCompany(BaseCompany):
    @inject
    def __init__(self,
                sql_service: SqlService,
                knowledge_service: KnowledgeBaseService):
        super().__init__()
        self.sql_service = sql_service
        self.knowledge_service = knowledge_service
        logging.info('companies: ok')

    def handle_request(self, action: str, **kwargs) -> str:
        if action == "document_search":
            query_string = kwargs.get('query')
            return self.knowledge_service.search(
                company_short_name=self.company_short_name,
                query=  query_string)
        else:
            return self.unsupported_operation(action)


    def register_cli_commands(self, app):
        @app.cli.command("create-sample-db")
        def create_sample_db():
            # get the handler to the database
            sample_db_provider = self.sql_service.get_database_provider('sample_company', 'sample_database')
            self.sample_database = SampleCompanyDatabase(sample_db_provider)

            """📦 create and populate the database."""
            if not self.sample_database:
                click.echo("❌ Error: La base de datos no está configurada.")
                click.echo("👉 make sure you have configured the database in the config.py file.")
                return

            try:
                click.echo(
                    "⚙️  creating and populating the database...")
                self.sample_database.create_database()
                self.sample_database.populate_from_excel('companies/sample_company/sample_data/northwind.xlsx')
                click.echo("✅ database created and populated successfully!")
            except Exception as e:
                logging.exception(e)
                click.echo(f"❌ an error: {e}")
