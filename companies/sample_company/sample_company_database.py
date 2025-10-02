import pandas as pd
from sqlalchemy import text
import random
from datetime import datetime, timedelta
import os

PREFIX_TABLE_NAME = 'sample_'

class SampleCompanyDatabase:
    def __init__(self, db_manager):
        """
        Initializes the database manager for the sample company.
        :param db_manager: An instance of DatabaseManager.
        """
        self.db_manager = db_manager

    def create_database(self):
        """
        Creates the relational model tables in the database.
        Existing tables are dropped and re-created.
        """
        create_statements = [
            f"DROP TABLE IF EXISTS {PREFIX_TABLE_NAME}order_items;",
            f"DROP TABLE IF EXISTS {PREFIX_TABLE_NAME}orders;",
            f"DROP TABLE IF EXISTS {PREFIX_TABLE_NAME}products;",
            f"DROP TABLE IF EXISTS {PREFIX_TABLE_NAME}customers;",

            f"""
            CREATE TABLE {PREFIX_TABLE_NAME}customers
            (
                id    INTEGER PRIMARY KEY,
                name  VARCHAR(255)        NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL
            );
            """,
            f"""
            CREATE TABLE {PREFIX_TABLE_NAME}products
            (
                id    INTEGER PRIMARY KEY,
                name  VARCHAR(255) NOT NULL,
                price REAL         NOT NULL
            );
            """,
            f"""
            CREATE TABLE {PREFIX_TABLE_NAME}orders
            (
                id          INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date  DATE    NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES {PREFIX_TABLE_NAME}customers (id)
            );
            """,
            f"""
            CREATE TABLE {PREFIX_TABLE_NAME}order_items
            (
                id         INTEGER PRIMARY KEY,
                order_id   INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity   INTEGER NOT NULL,
                FOREIGN KEY (order_id) REFERENCES {PREFIX_TABLE_NAME}orders (id),
                FOREIGN KEY (product_id) REFERENCES {PREFIX_TABLE_NAME}products (id)
            );
            """
        ]
        with self.db_manager.get_connection() as connection:
            for statement in create_statements:
                connection.execute(text(statement))
        print("Tables created successfully.")

    def populate_database(self, num_customers=1000, num_products=50, num_orders=30000):
        """
        Generates dummy data, saves it to a temporary Excel file,
        populates the database from the file, and then deletes the file.
        """
        temp_excel_path = 'temp_sample_data.xlsx'
        try:
            # Step 1: Generate simulated data in memory
            print("Generating simulated data...")
            df_customers, df_products, df_orders, df_order_items = self._generate_data(
                num_customers, num_products, num_orders
            )

            # Step 2: Create the Excel file
            print(f"Creating temporary Excel file at '{temp_excel_path}'...")
            with pd.ExcelWriter(temp_excel_path, engine='openpyxl') as writer:
                df_customers.to_excel(writer, sheet_name='customers', index=False)
                df_products.to_excel(writer, sheet_name='products', index=False)
                df_orders.to_excel(writer, sheet_name='orders', index=False)
                df_order_items.to_excel(writer, sheet_name='order_items', index=False)

            # Step 3: Populate the tables from the Excel file
            print("Populating database tables from temporary excel file...")
            engine = self.db_manager.get_engine()
            df_customers.to_sql(f'{PREFIX_TABLE_NAME}customers', con=engine, if_exists='append', index=False)
            df_products.to_sql(f'{PREFIX_TABLE_NAME}products', con=engine, if_exists='append', index=False)
            df_orders.to_sql(f'{PREFIX_TABLE_NAME}orders', con=engine, if_exists='append', index=False)
            df_order_items.to_sql(f'{PREFIX_TABLE_NAME}order_items', con=engine, if_exists='append', index=False)

        except Exception as e:
            print(f"An error occurred while populating the database: {e}")
        finally:
            # Step 4: Delete the temporary Excel file
            if os.path.exists(temp_excel_path):
                os.remove(temp_excel_path)

    def _generate_data(self, num_customers, num_products, num_orders):
        """Internal method to generate all necessary dataframes."""

        # Customer generation
        nombres = ["Carlos", "Luis", "Ana", "Maria", "Jose", "Sofia", "Diego", "Laura", "Javier", "Elena", "Miguel",
                   "Isabel", "Juan", "Carmen", "Pedro", "Lucia", "Andres", "Paula", "Fernando", "Marta", "David",
                   "Sara", "Alejandro", "Cristina", "Daniel", "Patricia"]
        apellidos = ["Garcia", "Rodriguez", "Gonzalez", "Fernandez", "Lopez", "Martinez", "Sanchez", "Perez", "Gomez",
                     "Martin", "Jimenez", "Ruiz", "Hernandez", "Diaz", "Moreno", "Alvarez", "Romero", "Navarro",
                     "Torres", "Dominguez", "Vazquez", "Ramos", "Gil", "Serrano", "Blanco", "Molina"]

        customers_data = []
        for i in range(1, num_customers + 1):
            nombre = random.choice(nombres)
            apellido = random.choice(apellidos)
            nombre_completo = f"{nombre} {apellido}"
            email_prefix = f"{nombre.lower()}.{apellido.lower()}{random.randint(1, 99)}"
            email = f"{email_prefix}@emailaleatorio.com"
            customers_data.append({'id': i, 'name': nombre_completo, 'email': email})
        df_customers = pd.DataFrame(customers_data)

        # Product generation
        product_names = [
            "Laptop Pro", "Smartphone X", "Tablet Air", "Monitor 4K", "Teclado Mecánico", "Mouse Inalámbrico",
            "Auriculares con Micrófono", "Webcam HD", "Impresora Multifunción", "Router WiFi 6",
            "Disco Duro Externo 1TB", "Memoria USB 64GB", "Silla Ergonómica", "Mesa de Escritorio", "Lámpara LED",
            "Batería Externa", "Funda para Laptop", "Mochila Tecnológica", "Cable HDMI", "Adaptador USB-C",
            "Tarjeta Gráfica RTX", "Procesador Core i9", "Memoria RAM 16GB", "Placa Base Z790", "SSD 1TB",
            "Refrigeración Líquida", "Fuente de Poder 750W", "Gabinete ATX", "Parlantes Bluetooth",
            "Micrófono de Condensador",
            "Licencia de Software Antivirus", "Suite de Ofimática", "Editor de Video Pro", "Software de Diseño Gráfico",
            "Sistema Operativo", "Libro de Programación Avanzada", "Curso de Machine Learning",
            "Suscripción a Plataforma de Streaming", "Taza de Café Geek", "Póster de Videojuego",
            "Figura de Colección", "Cargador Rápido", "Protector de Pantalla", "Hub USB", "Repetidor WiFi",
            "Cámara de Seguridad IP", "Termo Inteligente", "Reloj Inteligente", "Banda de Fitness", "Drone Básico"
        ]
        products_data = []
        for i in range(1, num_products + 1):
            products_data.append({
                'id': 100 + i,
                'name': product_names[i - 1] if i <= len(product_names) else f'Producto Genérico {i}',
                'price': round(random.uniform(10.5, 2500.99), 2)
            })
        df_products = pd.DataFrame(products_data)

        # Order generation
        orders_data = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3 * 365)
        total_days = (end_date - start_date).days
        customer_ids = df_customers['id'].tolist()
        for i in range(1, num_orders + 1):
            random_days = random.randint(0, total_days)
            order_date = start_date + timedelta(days=random_days)
            orders_data.append({
                'id': 1000 + i,
                'customer_id': random.choice(customer_ids),
                'order_date': order_date.strftime('%Y-%m-%d')
            })
        df_orders = pd.DataFrame(orders_data)

        # Order items generation
        order_items_data = []
        item_id_counter = 1
        order_ids = df_orders['id'].tolist()
        product_ids = df_products['id'].tolist()
        for order_id in order_ids:
            num_items_in_order = random.randint(1, 4)
            products_for_this_order = random.sample(product_ids, num_items_in_order)
            for product_id in products_for_this_order:
                order_items_data.append({
                    'id': item_id_counter,
                    'order_id': order_id,
                    'product_id': product_id,
                    'quantity': random.randint(1, 5)
                })
                item_id_counter += 1
        df_order_items = pd.DataFrame(order_items_data)

        return df_customers, df_products, df_orders, df_order_items