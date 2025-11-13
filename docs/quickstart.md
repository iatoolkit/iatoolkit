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
    - `OPENAI_API_KEY` or `GEMINI_API_KEY`
    - `LLM_MODEL`: can use 'gpt5' or 'gemini'
    - `DATABASE_URI` like: 'postgresql://postgres:xxxxxxx@127.0.0.1:5432/iatoolkit'
    - `IATOOLKIT_BASE_URL`: "http://127.0.0.1:5008"
    - `REDIS_URL`: "redis://localhost:6379/0"

### Step 3: Run the Application
You are now ready to start the IAToolkit web server.
```
flask run
```

The application will be available at `IATOOLKIT_BASE_URL`. 
You can now navigate to the web interface, register as a new user, 
and start chatting with your newly configured AI!


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