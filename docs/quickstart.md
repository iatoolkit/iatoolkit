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

Configure the core settings of the application by creating a `.env` file.

1.  **Create the `.env` file** in the project's root directory. 
2. You can copy the provided `.env.example` if it exists.
3. add values for the following variables:
    - `OPENAI_API_KEY` or `GEMINI_API_KEY` (see company.yaml)
    - `DATABASE_URI` like: 'postgresql://postgres:xxxxxxx@127.0.0.1:5432/iatoolkit'
    - `REDIS_URL`: "redis://localhost:6379/0"
    - `IATOOLKIT_SECRET_KEY`: "company key for encripyting"
    - `FERNET_KEY`: "define-your-own-tH9Y0PlZcOGIC3Vz"

    
### Step 3: Run the Application
You are now ready to start the IAToolkit web server.
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

Now you can enter into the toolkkit main page:
http://127.0.0.1:5007/sample_company/home

### Possible Issues and How to Solve Them

- **Port 5000 is already in use**  
  If the default port is busy, you can change it in your `.env` file:  
  ```env
  FLASK_RUN_PORT=5007
    ```
    Or override it directly when running the server: 
  ```bash
  flask run -port 5007.

- **Registration mail **
    This instance is configured for **not sending any emails**, so you won't receive 
    any confirmation emails (see company.yaml for more details).

### Step 4: Populate the SampleCompany Database 
Most companies need access to their own data. IAToolkit allows you to define custom CLI commands for this purpose. 
The sample_company provides a powerful example of how to do this.
To populate the sample database, first ensure SAMPLE_DATABASE_URI is set in your .env file, and then run:
```
flask populate-sample-db
```

This command will create tables for a tipical company with: customers, products, orders, countries, employees with dummy data.
You can use is as an example of sql access to your own data

## Next Steps

Now that you have IAToolkit running, you're ready to create your own company and customize it for your specific needs.

➡️ **[Learn how to create and configure your own Company →](./companies_and_components.md#2-the-companyyaml-configuration-file)**