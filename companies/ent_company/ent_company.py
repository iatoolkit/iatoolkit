# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from iatoolkit import BaseCompany
from iatoolkit import IngestorService, KnowledgeBaseService, SqlService
from injector import inject
from companies.ent_company.sample_database import SampleCompanyDatabase
import click
import logging


class EntCompany(BaseCompany):
    @inject
    def __init__(self,
                sql_service: SqlService,
                search_service: KnowledgeBaseService,
                ingestor_service: IngestorService,):
        super().__init__()
        self.sql_service = sql_service
        self.search_service = search_service
        self.ingestor_service = ingestor_service

    def handle_request(self, action: str, **kwargs) -> str:
        if action == "document_search":
            query_string = kwargs.get('query')
            return self.search_service.search(self.company_short_name, query_string)
        else:
            return self.unsupported_operation(action)


    def get_user_info(self, user_identifier: str) -> dict:
        user_data = {
            "id": user_identifier,
            "user_email": 'sample@sample_company.com',
            "user_fullname": 'Sample User',
            "extras": {}
        }
        return user_data


    def register_cli_commands(self, app):
        @app.cli.command("create-sample-db")
        def create_sample_db():
            # get the handler to the database
            sample_db_manager = self.sql_service.get_database_manager('sample_db')
            self.sample_database = SampleCompanyDatabase(sample_db_manager)

            """📦 create and populate the database."""
            if not self.sample_database:
                click.echo("❌ Error: database is not configured.")
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

        @app.cli.command("load-documents")
        def load_documents():
            try:
                self.ingestor_service.load_sources(
                            company=self.company,
                            sources_to_load=["employee_contracts", "supplier_manuals"]
                        )
            except Exception as e:
                logging.exception(e)
                click.echo(f"Error: {str(e)}")

