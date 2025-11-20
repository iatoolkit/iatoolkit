# Quickstart: Your First AI Assistant

This guide provides the fastest way to get IAToolkit up and running. 
We'll start by launching the pre-configured "Sample Company" demo in 
your local environment.

We call this the "Hello World" of AI assistants.
We'll download the toolkit, install its dependencies, 
and run the local web server.

### Step 1: Clone and Install

First, set up your local environment and install the necessary dependencies.

1.  **Clone the Repository**:
    ```bash
    git clone <https://github.com/flibedinsky/iatoolkit>
    cd iatoolkit
    ```

2.  **Create and Activate a Virtual Environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### Step 2: Environment Configuration

To function correctly, IAToolkit requires a few secret keys and core settings. 
These sensitive values are managed in a .env file to keep them out of version control, which is a fundamental security best practice.
1.  **Create the `.env` file** in the project's root directory. 
2. You can copy the provided `.env.example` 
3. add values for the following variables:
    - `OPENAI_API_KEY` (see company.yaml)
    - `DATABASE_URI` like: 'postgresql://postgres:xxxxxxx@127.0.0.1:5432/iatoolkit'
    - `SAMPLE_DATABASE_URI` like: 'postgresql://postgres:xxxxxxx@127.0.0.1:5432/sample_company'
    - `REDIS_URL`: "redis://localhost:6379/0"
    - `IATOOLKIT_SECRET_KEY`: 'jwt-IaTool$%&-739' # "company key for encryption"
    - `FERNET_KEY`: "define-your-own-tH9Y0PlZcOGIC3Vz"

4. Understand the Link Between .env and company.yaml:
- The .env file stores the secrets themselves: API keys, database passwords, etc.
- The company.yaml file defines a company's configuration and refers to the secrets by their variable name.
This separation makes your company configurations portable and secure. For example, company.yaml might specify that the LLM API key should be read from a variable named OPENAI_API_KEY, while the actual key value sk-xxxx... lives only in your local .env file.

### Step 3: Run the Application
You are now ready to start the IAToolkit web server.
```bash
  flask run 
``` 
you will see something like this:

```bash
(venv) iatoolkit %flask run
2025-11-19 13:30:41,137 - IATOOLKIT - root - INFO - ✅ Base de datos configurada correctamente
2025-11-19 13:30:41,143 - IATOOLKIT - root - INFO - ✅ Dependencias configuradas correctamente
2025-11-19 13:30:41,156 - IATOOLKIT - root - INFO - ✅ Routes registered.
2025-11-19 13:30:41,227 - IATOOLKIT - root - INFO - ✅ Redis y sesiones configurados correctamente
2025-11-19 13:30:41,227 - IATOOLKIT - root - INFO - ✅ CORS configurado para: ['https://portal-interno.empresa_de_ejemplo.cl']
2025-11-19 13:30:41,227 - IATOOLKIT - root - INFO - ✅ Comandos CLI del núcleo registrados.
2025-11-19 13:30:41,227 - IATOOLKIT - root - INFO - ✅ download dir created in: /Users/fernando/Documents/software/iatoolkit/iatoolkit-downloads
2025-11-19 13:30:41,227 - IATOOLKIT - root - INFO - 🎉 IAToolkit v0.73.1 inicializado correctamente
 * Debug mode: off
2025-11-19 13:30:41,229 - IATOOLKIT - werkzeug - INFO - WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on http://127.0.0.1:5000
```

Now you can enter into the IAToolkit main page:
http://127.0.0.1:5000/sample_company/home

### Step 4: Populate the SampleCompany Database 

The sample_company instance is pre-configured to demonstrate one of IAToolkit's most powerful features: 
answering questions by querying an external SQL database.
This database connection is declared in companies/sample_company/config/company.yaml under the data_sources.sql section. 
As shown below, it is given the logical 
name sample_database and gets its connection string from the SAMPLE_DATABASE_URI environment variable.
```yaml
# In companies/sample_company/config/company.yaml
data_sources:
  sql:
    - database: "sample_database"
      connection_string_env: "SAMPLE_DATABASE_URI"
      description: |
        This is Sample Company’s main database...
```
To enable this functionality, we must first create and populate this database. 
The following command uses the connection string from SAMPLE_DATABASE_URI to set up the schema and load it with 
sample data (based on the "Northwind" dataset).. The following command handles the entire process, 
creating the necessary tables and filling them with sample data for products, orders, customers, and more.

Once the SAMPLE_DATABASE_URI variable is set, activate your virtual environment and run the 
following command from the project root:
```bash
flask create-sample-db
```
You should see an output similar to this, confirming that the schema was created and the data was loaded successfully:
```bash
(venv) iatoolkit-install %flask create-sample-db
2025-11-19 13:52:31,840 - IATOOLKIT - root - INFO - 🎉 IAToolkit v0.10.2 inicializado correctamente
⚙️  Creando y poblando la base de datos, esto puede tardar unos momentos...
Database schema created successfully from 'companies/sample_company/sample_data/sample_database_schema.sql'.
✅ Base de datos de poblada exitosamente.
```

This command will create the tables company with: customers, products, orders, countries, employees with dummy data.

### Step 5: Load documents into the vector store 

To enable the AI assistant to answer questions about your company's private documents (like manuals, policies, or contracts), 
you need to load them into a vector store. 
This process, known as Retrieval-Augmented Generation (RAG), 
converts your documents into a searchable format that the AI can use to find relevant information.

The `sample_company` is configured to look for documents in the `knowledge_base` section 
of its `companies/sample_company/config/company.yaml` file. 
It defines two sources: `employee_contracts` and `supplier_manuals`.

**Run the Load Command**

From your project's root directory, execute the following command:
```bash
    flask load
```

After running you will see the service processing each file from the configured sources:
```bash
(venv) iatoolkit-install %flask load
2025-11-19 18:17:58,893 - IATOOLKIT - root - INFO - ✅ Base de datos configurada correctamente
2025-11-19 18:17:58,899 - IATOOLKIT - root - INFO - ✅ Dependencias configuradas correctamente
2025-11-19 18:17:58,911 - IATOOLKIT - root - INFO - ✅ Routes registered.
2025-11-19 18:17:58,984 - IATOOLKIT - root - INFO - ✅ Redis y sesiones configurados correctamente
2025-11-19 18:17:58,984 - IATOOLKIT - root - INFO - ✅ CORS configurado para: ['https://portal-interno.empresa_de_ejemplo.cl']
2025-11-19 18:17:58,984 - IATOOLKIT - root - INFO - ✅ Comandos CLI del núcleo registrados.
2025-11-19 18:17:58,984 - IATOOLKIT - root - INFO - ✅ download dir created in: /Users/fernando/Documents/software/iatoolkit-install/iatoolkit-downloads
2025-11-19 18:17:58,984 - IATOOLKIT - root - INFO - 🎉 IAToolkit v0.10.2 inicializado correctamente
2025-11-19 18:17:58,993 - IATOOLKIT - root - INFO - Processing source 'employee_contracts' for company 'sample_company'...
loading 10 files
loading: contract_Noah_Hernandez.pdf
2025-11-19 18:18:00,142 - IATOOLKIT - root - INFO - Successfully processed file: companies/sample_company/sample_data/employee_contracts/contract_Noah_Hernandez.pdf
loading: contract_Chloe_Hernandez.pdf
2025-11-19 18:18:01,248 - IATOOLKIT - root - INFO - Successfully processed file: companies/sample_company/sample_data/employee_contracts/contract_Chloe_Hernandez.pdf

....

2025-11-19 18:18:47,020 - IATOOLKIT - root - INFO - Successfully processed file: companies/sample_company/sample_data/supplier_manuals/net shaped solutions.pdf
loading: huf_group_supplier_manual.pdf
```
Now that the documents are indexed, you can ask the assistant questions related to their content, 
such as *"What is the company's vacation policy?"* or *"Summarize the quality standards from the ACME supplier manual."*

## Next Steps

Now that you have IAToolkit running, you're ready to create your own company and customize it for your specific needs.

➡️ **[Learn how to create and configure your own Company →](./companies_and_components.md#2-the-companyyaml-configuration-file)**