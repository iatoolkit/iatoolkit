import pandas as pd
from sqlalchemy import text, inspect
import os


class SampleCompanyDatabase:
    def __init__(self, db_manager):
        """
        Initializes the database manager for the sample company.
        :param db_manager: An instance of DatabaseManager.
        """
        self.db_manager = db_manager

    def create_database(self):
        """
        Creates the relational model by executing an external SQL script.
        """
        # Adjust this path if you place the SQL file elsewhere
        sql_script_path = 'companies/sample_company/sample_data/sample_database_schema.sql'

        if not os.path.exists(sql_script_path):
            raise FileNotFoundError(f"SQL script not found. Expected at: {sql_script_path}")

        with open(sql_script_path, 'r', encoding='utf-8') as f:
            # Split script into individual statements for safer execution
            sql_script = f.read()
            statements = [s.strip() for s in sql_script.split(';') if s.strip()]

        with self.db_manager.get_connection() as connection:
            backend_name = self.db_manager.url.get_backend_name()
            is_postgres = backend_name in ('postgresql', 'postgres')

            # create the schema if it doesn't exist'
            with connection.begin():
                if self.db_manager.schema and is_postgres:
                    print(f"⚙️  Creating schema '{self.db_manager.schema}'...")

                    # 1. create the schema and confirm
                    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.db_manager.schema}"))

                    # 2. Force the search_path in the same transaction
                    connection.execute(text(f"SET search_path TO {self.db_manager.schema}, public"))

                # 3. execute the table script (inherit the search_path from above)
                for statement in statements:
                    connection.execute(text(statement))

        print(f"Database schema created successfully from '{sql_script_path}'.")

    @staticmethod
    def _normalize_df(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
        """
        Normalizes a DataFrame by handling NaNs and converting date columns.
        """
        df = df.copy()
        # Ensure missing date columns exist
        for col in date_cols:
            if col not in df.columns:
                df[col] = None

        # Convert date-like columns to Python date objects
        for c in date_cols:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors="coerce").dt.date

        # Replace NaN with None for SQLAlchemy
        df = df.where(pd.notnull(df), None)
        return df

    def populate_from_excel(self, xlsx_path: str) -> dict:
        """
        Populate the Northwind schema by reading data from an Excel file.
        This version is more robust, less redundant, and more efficient.
        :param xlsx_path: Path to the .xlsx file (e.g., 'northwind.xlsx')
        :return: dict with number of rows inserted per table
        """
        # Simplified mapping: (Excel sheet, SQL table, date columns, columns for deduplication)
        schema_plan = [
            ("Categories", "categories", [], None),
            ("Suppliers", "suppliers", [], None),
            ("Products", "products", [], None),
            ("Customers", "customers", [], None),
            ("Employees", "employees", ["birthdate", "hiredate"], None),
            ("Shippers", "shippers", [], None),
            ("Orders", "orders", ["orderdate", "requireddate", "shippeddate"], None),
            ("OrderDetails", "order_details", [], ["orderid", "productid"]),  # Correction: Deduplicate on PK
            ("Regions", "regions", [], None),
            ("Territories", "territories", [], None),
            ("EmployeeTerritories", "employee_territories", [], ["employeeid", "territoryid"]),
        ]

        xls = pd.read_excel(xlsx_path, sheet_name=None, dtype=object)
        results = {}
        table_name = ""

        try:
            with self.db_manager.get_connection() as connection:
                with connection.begin():  # Manages the transaction (commit/rollback)
                    inspector = inspect(connection.engine)

                    if connection.dialect.name == 'sqlite':
                        connection.execute(text("PRAGMA foreign_keys = ON;"))

                    for sheet_name, table_name, date_cols, deduplicate_on in schema_plan:
                        if sheet_name not in xls:
                            results[table_name] = 0
                            continue

                        df = xls[sheet_name]

                        # Standardize DataFrame columns to lowercase to match the database schema.
                        df.columns = [c.lower() for c in df.columns]

                        df = self._normalize_df(df, date_cols)

                        if deduplicate_on:
                            df.drop_duplicates(subset=deduplicate_on, keep='first', inplace=True)

                        # This intersection will now work perfectly.
                        db_columns = [col['name'] for col in inspector.get_columns(table_name, schema=self.db_manager.schema)]
                        df_filtered = df[[col for col in db_columns if col in df.columns]].copy()

                        if not df_filtered.empty:
                            df_filtered.to_sql(
                                table_name,
                                con=connection,
                                schema=self.db_manager.schema,
                                if_exists='append',
                                index=False,
                                method='multi'
                            )
                            results[table_name] = len(df_filtered)
                        else:
                            results[table_name] = 0

        except Exception as e:
            raise RuntimeError(f"Error populating data from '{xlsx_path}' for table '{table_name}': {e}") from e

        return results