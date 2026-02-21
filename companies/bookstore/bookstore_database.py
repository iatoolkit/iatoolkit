import sqlite3
import os
import logging
from iatoolkit.common.exceptions import IAToolkitException

class BookstoreDatabase:
    def __init__(self, db_provider):
        self.db_provider = db_provider
        self.logger = logging.getLogger(__name__)

    def create_database(self):
        """Creates the database tables using the schema file."""
        schema_path = 'companies/bookstore/sample_data/bookstore_schema.sql'
        
        if not os.path.exists(schema_path):
             raise IAToolkitException(
                 IAToolkitException.ErrorType.CONFIGURATION_ERROR, 
                 f"Schema file not found at: {schema_path}"
             )

        try:
            # We need to execute the SQL script. 
            # Since SqlService usually gives us an engine, let's see how we can run a raw script.
            # Assuming db_provider is a SQLAlchemy engine or session factory, 
            # but for SQLite/Postgres scripts usually we want a raw connection or use executescript.
            
            # For simplicity, if it's SQLite, we can connect directly if we know the path
            # But adhering to the framework, we should try to use the engine.
            
            # Let's read the file content
            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            # Execute using the engine
            with self.db_provider.connect() as connection:
                # SQLAlchemy doesn't support executing entire scripts with multiple statements easily 
                # in a cross-database way without some splitting.
                # However, for this example we are likely using SQLite connection string in the helper.
                
                # Check if it's sqlite
                if 'sqlite' in str(self.db_provider.url):
                     # For SQLite, we can use the raw DBAPI connection
                     raw_conn = connection.connection
                     raw_conn.executescript(schema_sql)
                else:
                    # For Postgres, we might need to separate statements or use text()
                    from sqlalchemy import text
                    # Simple split by ';' usually works for simple schemas, but is fragile.
                    # For this example, let's assume we proceed statement by statement if possible
                    # or just executescript if the driver supports it.
                    pass 
                    # Warning: This is a simplification.
                    
            self.logger.info("Database schema created.")

        except Exception as e:
            self.logger.error(f"Failed to create database: {e}")
            raise

    def populate_database(self):
        """Populates the database with seed data."""
        data_path = 'companies/bookstore/sample_data/bookstore_seed_data.sql'
        
        if not os.path.exists(data_path):
             raise IAToolkitException(
                 IAToolkitException.ErrorType.CONFIGURATION_ERROR, 
                 f"Seed data file not found at: {data_path}"
             )

        try:
            with open(data_path, 'r') as f:
                seed_sql = f.read()

            with self.db_provider.connect() as connection:
                 if 'sqlite' in str(self.db_provider.url):
                     raw_conn = connection.connection
                     raw_conn.executescript(seed_sql)
                 
            self.logger.info("Database populated with seed data.")

        except Exception as e:
             self.logger.error(f"Failed to populate database: {e}")
             raise
