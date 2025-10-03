import pandas as pd
from sqlalchemy import text


class SampleCompanyDatabase:
    def __init__(self, db_manager):
        """
        Initializes the database manager for the sample company.
        :param db_manager: An instance of DatabaseManager.
        """
        self.db_manager = db_manager

    def create_database(self):
        """
        Crea el modelo relacional estilo Northwind en la base de datos.
        Las tablas existentes se eliminan y se vuelven a crear.
        """
        create_statements = [
            # Borrar en orden inverso de dependencias
            "DROP TABLE IF EXISTS employee_territories;",
            "DROP TABLE IF EXISTS territories;",
            "DROP TABLE IF EXISTS regions;",
            "DROP TABLE IF EXISTS order_details;",
            "DROP TABLE IF EXISTS orders;",
            "DROP TABLE IF EXISTS shippers;",
            "DROP TABLE IF EXISTS employees;",
            "DROP TABLE IF EXISTS customers;",
            "DROP TABLE IF EXISTS products;",
            "DROP TABLE IF EXISTS suppliers;",
            "DROP TABLE IF EXISTS categories;",

            # Categories
            """
            CREATE TABLE categories
            (
                CategoryID   INTEGER PRIMARY KEY,
                CategoryName VARCHAR(100) NOT NULL,
                Description  TEXT
            );
            """,

            # Suppliers
            """
            CREATE TABLE suppliers
            (
                SupplierID  INTEGER PRIMARY KEY,
                CompanyName VARCHAR(255) NOT NULL,
                ContactName VARCHAR(255),
                Country     VARCHAR(100),
                City        VARCHAR(100),
                Phone       VARCHAR(50),
                Address     VARCHAR(255)
            );
            """,

            # Products
            """
            CREATE TABLE products
            (
                ProductID       INTEGER PRIMARY KEY,
                ProductName     VARCHAR(255) NOT NULL,
                SupplierID      INTEGER,
                CategoryID      INTEGER,
                QuantityPerUnit VARCHAR(100),
                UnitPrice       REAL         NOT NULL,
                UnitsInStock    INTEGER,
                UnitsOnOrder    INTEGER,
                ReorderLevel    INTEGER,
                Discontinued    INTEGER DEFAULT 0,
                FOREIGN KEY (SupplierID) REFERENCES suppliers (SupplierID),
                FOREIGN KEY (CategoryID) REFERENCES categories (CategoryID)
            );
            """,

            # Customers
            """
            CREATE TABLE customers
            (
                CustomerID   VARCHAR(10) PRIMARY KEY,
                CompanyName  VARCHAR(255) NOT NULL,
                ContactName  VARCHAR(255),
                ContactTitle VARCHAR(100),
                Address      VARCHAR(255),
                City         VARCHAR(100),
                Region       VARCHAR(50),
                PostalCode   VARCHAR(20),
                Country      VARCHAR(100),
                Phone        VARCHAR(50)
            );
            """,

            # Employees
            """
            CREATE TABLE employees
            (
                EmployeeID INTEGER PRIMARY KEY,
                LastName   VARCHAR(100),
                FirstName  VARCHAR(100),
                Title      VARCHAR(100),
                BirthDate  DATE,
                HireDate   DATE,
                City       VARCHAR(100),
                Country    VARCHAR(100),
                ReportsTo  INTEGER,
                FOREIGN KEY (ReportsTo) REFERENCES employees (EmployeeID)
            );
            """,

            # Shippers
            """
            CREATE TABLE shippers
            (
                ShipperID   INTEGER PRIMARY KEY,
                CompanyName VARCHAR(255),
                Phone       VARCHAR(50)
            );
            """,

            # Orders
            """
            CREATE TABLE orders
            (
                OrderID        INTEGER PRIMARY KEY,
                CustomerID     VARCHAR(10) NOT NULL,
                EmployeeID     INTEGER     NOT NULL,
                OrderDate      DATE,
                RequiredDate   DATE,
                ShippedDate    DATE,
                ShipVia        INTEGER,
                Freight        REAL,
                ShipName       VARCHAR(255),
                ShipAddress    VARCHAR(255),
                ShipCity       VARCHAR(100),
                ShipRegion     VARCHAR(50),
                ShipPostalCode VARCHAR(20),
                ShipCountry    VARCHAR(100),
                FOREIGN KEY (CustomerID) REFERENCES customers (CustomerID),
                FOREIGN KEY (EmployeeID) REFERENCES employees (EmployeeID),
                FOREIGN KEY (ShipVia) REFERENCES shippers (ShipperID)
            );
            """,

            # OrderDetails
            """
            CREATE TABLE order_details
            (
                OrderID   INTEGER NOT NULL,
                ProductID INTEGER NOT NULL,
                UnitPrice REAL    NOT NULL,
                Quantity  INTEGER NOT NULL,
                Discount  REAL,
                PRIMARY KEY (OrderID, ProductID),
                FOREIGN KEY (OrderID) REFERENCES orders (OrderID),
                FOREIGN KEY (ProductID) REFERENCES products (ProductID)
            );
            """,

            # Regions
            """
            CREATE TABLE regions
            (
                RegionID          INTEGER PRIMARY KEY,
                RegionDescription VARCHAR(100) NOT NULL
            );
            """,

            # Territories
            """
            CREATE TABLE territories
            (
                TerritoryID          INTEGER PRIMARY KEY,
                TerritoryDescription VARCHAR(100),
                RegionID             INTEGER,
                FOREIGN KEY (RegionID) REFERENCES regions (RegionID)
            );
            """,

            # EmployeeTerritories
            """
            CREATE TABLE employee_territories
            (
                EmployeeID  INTEGER NOT NULL,
                TerritoryID INTEGER NOT NULL,
                PRIMARY KEY (EmployeeID, TerritoryID),
                FOREIGN KEY (EmployeeID) REFERENCES employees (EmployeeID),
                FOREIGN KEY (TerritoryID) REFERENCES territories (TerritoryID)
            );
            """
        ]

        with self.db_manager.get_connection() as connection:
            for statement in create_statements:
                connection.execute(text(statement))

            connection.commit()

        print("Northwind tables created successfully.")

    def populate_from_excel(self, xlsx_path: str) -> dict:
        """
        Populate the Northwind schema by reading data from an Excel file (one sheet per table).
        Requires the schema to be created first (call create_database()).
        :param xlsx_path: Path to the .xlsx file (e.g., 'northwind_realish.xlsx')
        :return: dict with number of rows inserted per table
        """
        # Mapping: Excel sheet -> (SQL table, column order, date columns if any)
        schema_plan = [
            ("Categories", "categories", ["CategoryID", "CategoryName", "Description"], []),
            ("Suppliers", "suppliers",
             ["SupplierID", "CompanyName", "ContactName", "Country", "City", "Phone", "Address"], []),
            ("Products", "products",
             ["ProductID", "ProductName", "SupplierID", "CategoryID", "QuantityPerUnit", "UnitPrice", "UnitsInStock",
              "UnitsOnOrder", "ReorderLevel", "Discontinued"], []),
            ("Customers", "customers",
             ["CustomerID", "CompanyName", "ContactName", "ContactTitle", "Address", "City", "Region", "PostalCode",
              "Country", "Phone"], []),
            ("Employees", "employees",
             ["EmployeeID", "LastName", "FirstName", "Title", "BirthDate", "HireDate", "City", "Country", "ReportsTo"],
             ["BirthDate", "HireDate"]),
            ("Shippers", "shippers", ["ShipperID", "CompanyName", "Phone"], []),
            ("Orders", "orders",
             ["OrderID", "CustomerID", "EmployeeID", "OrderDate", "RequiredDate", "ShippedDate", "ShipVia", "Freight",
              "ShipName", "ShipAddress", "ShipCity", "ShipRegion", "ShipPostalCode", "ShipCountry"],
             ["OrderDate", "RequiredDate", "ShippedDate"]),
            ("OrderDetails", "order_details", ["OrderID", "ProductID", "UnitPrice", "Quantity", "Discount"], []),
            ("Regions", "regions", ["RegionID", "RegionDescription"], []),
            ("Territories", "territories", ["TerritoryID", "TerritoryDescription", "RegionID"], []),
            ("EmployeeTerritories", "employee_territories", ["EmployeeID", "TerritoryID"], []),
        ]

        # Load all sheets into a dictionary {sheet_name: DataFrame}
        xls = pd.read_excel(xlsx_path, sheet_name=None, dtype=object)

        # Normalize dataframe: replace NaN with None, convert date columns
        def _normalize_df(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
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

        # Insert dataframe into a SQL table
        def _insert_df(connection, table: str, df: pd.DataFrame, cols: list[str]) -> int:
            if df.empty:
                return 0
            # Keep only the required columns in the right order
            df_final = df[[c for c in cols if c in df.columns]].copy()

            # Build SQL insert statement
            placeholders = ", ".join([f":{c}" for c in df_final.columns])
            colnames = ", ".join(df_final.columns)
            sql = text(f"INSERT INTO {table} ({colnames}) VALUES ({placeholders})")

            # Convert DataFrame to list of dicts for executemany
            records = df_final.to_dict(orient="records")
            connection.execute(sql, records)
            return len(records)

        results = {}
        with self.db_manager.get_connection() as connection:
            if connection.dialect.name == 'sqlite':
                try:
                    connection.execute(text("PRAGMA foreign_keys = ON;"))
                except Exception:
                    # Ignore if it fails, although it shouldn't for SQLite
                    pass

            # A transaction is started automatically on the first execute (autobegin).
            # We just need to commit or rollback.
            try:
                for sheet_name, table, cols, date_cols in schema_plan:
                    if sheet_name not in xls:
                        results[table] = 0
                        continue

                    df = xls[sheet_name]
                    df = _normalize_df(df, date_cols)
                    if table == 'order_details':
                        df.drop_duplicates(subset=['OrderID', 'ProductID'], keep='first', inplace=True)

                    inserted = _insert_df(connection, table, df, cols)
                    results[table] = inserted

                connection.commit()
            except Exception as e:
                connection.rollback()
                raise RuntimeError(f"Error inserting data from '{xlsx_path}' into table '{table}': {e}")

        return results

