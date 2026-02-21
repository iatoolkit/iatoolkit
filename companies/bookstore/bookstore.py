
from iatoolkit import BaseCompany
from iatoolkit import KnowledgeBaseService, SqlService
from injector import inject
import click
import logging
from companies.bookstore.bookstore_database import BookstoreDatabase

class Bookstore(BaseCompany):
    @inject
    def __init__(self,
                sql_service: SqlService,
                knowledge_service: KnowledgeBaseService):
        super().__init__()
        self.sql_service = sql_service
        self.knowledge_service = knowledge_service
        self.company_id = 'bookstore'
        logging.info('Bookstore company initialized')

    def handle_request(self, action: str, **kwargs) -> str:
        # Placeholder for custom tool handling if needed
        # Most standard tools are handled by the framework's dispatcher
        return self.unsupported_operation(action)

    def register_cli_commands(self, app):
        @app.cli.command("create-bookstore-db")
        def create_bookstore_db():
            """📚 Create and populate the Bookstore database."""
            
            # Retrieve the database provider from the service
            # using the logical name 'bookstore_db' defined in company.yaml
            try:
                db_provider = self.sql_service.get_database_provider(self.company_id, 'bookstore_db')
                bookstore_db = BookstoreDatabase(db_provider)
                
                click.echo("⚙️  Creating Bookstore database schema...")
                bookstore_db.create_database()
                
                click.echo("🌱 Populating Bookstore database with seed data...")
                bookstore_db.populate_database()
                
                click.echo("✅ Bookstore database ready!")
            except Exception as e:
                logging.exception(e)
                click.echo(f"❌ Error setting up database: {e}")
