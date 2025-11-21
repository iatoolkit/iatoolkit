# IAToolkit Deployment Guide

This guide provides step-by-step instructions for deploying a production-ready instance of IAToolkit. We will focus on a robust and scalable strategy where your company-specific code is managed in a separate, private repository that consumes the IAToolkit framework as a dependency.

This approach is highly recommended for production as it cleanly separates your proprietary business logic from the core framework, simplifying updates and maintenance.

## 1. Prerequisites

Before you begin, ensure you have the following resources provisioned on your cloud provider of choice (e.g., Heroku, AWS, Google Cloud):

1.  **A PostgreSQL Database**: For the core IAToolkit system (users, queries, etc.).
2.  **A Redis Instance**: For session management and caching.
3.  **(Optional) A second PostgreSQL Database**: For your company-specific data (e.g., the demo SampleCompany database).
4.  **(Optional) An S3-compatible Object Storage Bucket**: If you plan to use the RAG feature with documents in production.

## 2. Deployment Strategy: Decoupled Company Repository

For maximum isolation and portability, the recommended production architecture is to have the IAToolkit framework act as an external dependency, while all code for your company resides in its own dedicated GitHub repository.

### Company Repository Structure

Your private repository will not contain the IAToolkit source code. Instead, it will have the following structure:

```text
my-client-project/
├── companies/
│   └── my_company/          # The complete company module
│       ├── config/
│       ├── context/
│       ├── prompts/
│       ├── schema/
│       └── my_company.py
│
├── app.py                    # Flask application entry point
├── requirements.txt          # Project dependencies, including iatoolkit
├── Procfile                  # Command for the web server (e.g., Gunicorn)
└── .env                      # For local development ONLY. Do NOT commit.
```

## 3. Key Deployment Files

These three files are the heart of your deployment package. They tell your hosting platform how to build and run your IAToolkit instance.

## 3.1 requirements.txt
This file lists your project's Python dependencies. The most important dependency is iatoolkit itself, which should be pinned to a specific version for stable, reproducible builds.

```text
# requirements.txt

# Pin the IAToolkit framework to a specific version
iatoolkit==1.0.0

# Add any other libraries your company's custom logic might need
gunicorn
psycopg2-binary
pandas
boto3
```
## 3.2 app.py (Application Entry Point)

This file is responsible for creating the Flask application. 
It imports and registers only the companies that should be active in this 
specific deployment.
It's also the perfect place to initialize production-only services 
like Application Performance Monitoring (APM).

```python
# app.py

from dotenv import load_dotenv
from iatoolkit.iatoolkit import IAToolkit
from iatoolkit.company_registry import register_company

# Import your company class from the local directory
from companies.my_company.my_company import MyCompany

# Load environment variables from .env for local development
load_dotenv()


def create_app():
    """
    App factory that registers companies and creates the IAToolkit app.
    """
    # IMPORTANT: Register only the companies from this repository
    register_company('my_company', MyCompany)

    # Create the IAToolkit instance (which in turn creates the Flask app)
    toolkit = IAToolkit()
    app = toolkit.create_iatoolkit()

    # --- Production Monitoring (Optional) ---
    # Configure Elastic APM only in production environments
    environment = os.environ.get("FLASK_ENV", "development")
    if environment in ("prod", "production"):
        try:
            from elasticapm.contrib.flask import ElasticAPM
            
            ElasticAPM(app,
               server_url=os.getenv("ELASTIC_URL"),
               service_name=os.getenv("ELASTIC_APP_NAME", "iatoolkit"),
               environment=os.getenv("ELASTIC_APM_ENVIRONMENT", "production"),
               secret_token=os.getenv("ELASTIC_TOKEN"),
               logging=True)
            
            logging.warning("Elastic APM configured for the application.")
        except ImportError:
            logging.warning("elastic-apm library not found. Skipping APM configuration.")
        except Exception as e:
            logging.error(f"Failed to configure Elastic APM: {e}")

    return app



# Create the app instance so it can be run by a WSGI server like Gunicorn
app = create_app()

if __name__ == "__main__":
    # Allows running for development with "python app.py"
    if app:
        app.run(debug=True, port=5000)

```

## 3.3 Procfile
This file tells your hosting platform (like Heroku) how to run your web process. We use Gunicorn, a production-grade WSGI server, to serve the Flask application.

```text
# Procfile

web: gunicorn app:app --log-file -
```
This command tells the platform to start a web process by running gunicorn. app:app points to the app object inside your app.py file.

## 4. Environment Variables in Production

In a production environment, you must not use a .env file. Instead, configure your environment variables using your hosting provider's secure configuration management system.
Heroku: Go to your app's "Settings" tab and click "Reveal Config Vars".
AWS: Use AWS Secrets Manager or Parameter Store.
Google Cloud: Use Secret Manager.
You will need to set all the variables required by IAToolkit and your specific company configuration (company.yaml), such as:
- FLASK_ENV=production
- DATABASE_URI (for the IAToolkit core database)
- REDIS_URL
- IATOOLKIT_SECRET_KEY
- FERNET_KEY
- OPENAI_API_KEY (or other LLM provider keys)
- SAMPLE_DATABASE_URI (for your company's external database)
Any other keys referenced in your company.yaml (e.g., BREVO_API_KEY, AWS_ACCESS_KEY_ID).

## 5. Deploying the Application

- Commit your code to your private Git repository.
- Connect your repository to your hosting provider (e.g., via the Heroku dashboard or AWS CodePipeline).
- Configure the environment variables as described in the previous step.
- Trigger a deployment. The platform will use requirements.txt to install iatoolkit and other dependencies, then use the Procfile to start the Gunicorn server.

## 6. Running One-Off Administrative Commands
After a successful deployment, your application will be running, but your databases will be empty. You need to run the same setup commands from the Quickstart Guide, but this time on your production server.
Most hosting platforms provide a way to run a one-off command in the context of your deployed application.
On Heroku: You can run commands using `heroku run`.

**Populate your company's external database:**
```bash
    heroku run flask populate-sample-db
```
**Load documents into the vector store:**
```bash
    heroku run flask load
```

After these commands complete, your production instance will be fully configured and ready to use.

## 7. Mail Service Configuration

IAToolkit uses a mail service to send notifications like account verification and password resets. 
It also use this service when the user order the chatbot to send emails.
To enable this in production, you must configure your mail provider in `company.yaml` and set 
the required credentials as environment variables in your hosting environment.

The system supports multiple providers, such as Brevo (formerly Sendinblue) 
and standard SMTP servers, as detailed in the [Companies and Components](./companies_and_components.md) guide.

### Environment Variables for Mail Service

Depending on the provider you configured in your `company.yaml`, 
you will need to add the following variables to your production environment 
configuration (e.g., in Heroku Config Vars):

#### For Brevo (`provider: "brevo_mail"`)
*   `BREVO_API_KEY`: Your API key from Brevo. The name of this environment variable is what you define in the `brevo_api` key inside `company.yaml`.

#### For SMTP (`provider: "smtplib"`)
*   `SMTP_HOST`: Your SMTP server hostname.
*   `SMTP_PORT`: The port for the SMTP server.
*   `SMTP_USERNAME`: Your SMTP username.
*   `SMTP_PASSWORD`: Your SMTP password.
*   `SMTP_USE_TLS`: Set to "true" to enable TLS.
*   `SMTP_USE_SSL`: Set to "true" to enable SSL.

**Note**: The names for the SMTP environment variables (`SMTP_HOST`, `SMTP_PORT`, etc.) are configurable in the `smtplib` section of your `company.yaml` file.

Once these variables are set according to your `company.yaml` configuration, the mail service will be operational.

## 8. IAToolkit API-Key

To enable integrations and allow external systems to communicate securely with your IAToolkit instance, 
you need to generate an API key. This key is used to authenticate API calls.

The main uses for the API key are:

1.  **Executing Prompts via API**: Allows internal company processes to programmatically call predefined IAToolkit prompts. For example, a CRM system could trigger a prompt to have the LLM summarize a customer's history based on a customer object.
2.  **Corporate Portal Integration**: Enables the external login flow from an internal company portal, providing a seamless Single Sign-On (SSO) experience for users, as detailed in the next chapter.


### 8.1. API Key Generation

The API key is generated using a Flask CLI command. You will need to run this command in your production server environment 
for the desired company.

```bash
flask api-key sample_company
```

and the following output will be displayed:

```bash
(venv) iatoolkit %flask api-key sample_company
...
2025-11-21 15:07:56,439 - IATOOLKIT - root - INFO - 🎉 IAToolkit v0.74.0 inicializado correctamente
🔑 Generating API-KEY for company: 'sample_company'...
✅ ¡Api-key is ready! add this variable to your environment:
IATOOLKIT_API_KEY='ntyFHTob55TCHFdLoOkCxSi0WhyOfMGRJcqH5qIM'```
```

### 8.2. Configuration

The `IATOOLKIT_API_KEY` environment variable must be configured in the environment of the **client system** that 
will be making calls to the IAToolkit API (for example, your internal corporate portal's server). 
You should **not** configure this variable in the IAToolkit server environment itself.

This key should be treated with the same confidentiality as a password.

## 9. External Login

IAToolkit offers an "external login" feature designed to smoothly integrate the chat platform into a company portal or 
intranet where users are already authenticated.

This allows a user to navigate from the internal portal to IAToolkit and be logged in automatically, 
without needing to re-enter their credentials, providing a Single Sign-On (SSO) experience.

### 9.1. Authentication Flow

1.  **API Call**: The external system (your corporate portal) must make an authenticated `POST` call to the following IAToolkit endpoint:
    `/external_login/<company_short_name>`

2.  **Authentication**: The call must include the `IATOOLKIT_API_KEY` (generated in the previous step) in the authorization headers to be validated. Additionally, the `auth_service` expects to receive the corporate user's identity.

3.  **Session Creation**: If authentication is successful, IAToolkit internally creates a session context for the user and generates a single-use token.

4.  **Chat Access**: IAToolkit returns a URL that includes this token, to which the user can be redirected to finalize the login process and directly access the chat.

The reference implementation for this flow can be found in the file `src/iatoolkit/views/external_login_view.py`.


## 10. Appendix: Available API

The following section describes the key API endpoints available for programmatic integration. All API calls must be authenticated by including the `IATOOLKIT_API_KEY` in the `Authorization` header as a Bearer token.

```text
Authorization: Bearer <your_api_key>
```

---

### `POST /api/<company_short_name>/init-context`

This endpoint initializes or resets the conversation context for a specific user. It's useful for starting a new conversation from scratch, ensuring that no previous history is carried over.

**Example Call:**
```bash
curl -X POST \
  https://your-iatoolkit-instance.com/api/my_company/init-context \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "model": "gpt-4"
      }'
```

**Example Response:**
```json
{
  "status": "Context initialized",
  "response_id": "chatcmpl-xxxxxxxxxxxxxxxxxxxxxx",
  "model": "gpt-4"
}
```

---

### `POST /api/<company_short_name>/llm_query`

This is the primary endpoint for interacting with the assistant. You can send a direct question or invoke a predefined prompt with associated data.

**Example Call (direct question):**
```bash
curl -X POST \
  https://your-iatoolkit-instance.com/api/my_company/llm_query \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "question": "What were the total sales last month?"
      }'
```

**Example Call (using a prompt):**
```bash
curl -X POST \
  https://your-iatoolkit-instance.com/api/my_company/llm_query \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "prompt_name": "summarize_customer_activity",
        "client_data": {
          "customer_id": "CUST-12345",
          "last_purchase_date": "2025-10-15"
        }
      }'
```

**Example Response:**
```json
{
  "answer": "The total sales for last month were $150,000.",
  "response_id": "chatcmpl-yyyyyyyyyyyyyyyyyyyyyy",
  "valid_response": true
}
```

---
### `POST /api/<company_short_name>/file-store`

This endpoint uploads a temporary file and returns a token. This token can then be used in a `llm_query` call to provide the file's content as context for a single query. This is useful for analyzing documents on-the-fly without permanently adding them to the knowledge base.

**Step 1: Upload the file**
```bash
curl -X POST \
  https://your-iatoolkit-instance.com/api/my_company/file-store \
  -H "Authorization: Bearer <your_api_key>" \
  -F "file=@/path/to/your/document.pdf"
```

**Response:**
```json
{
  "token": "a-unique-file-token-xxxxxxxx",
  "filename": "document.pdf"
}
```

---

### `POST /api/<company_short_name>/embedding`

This endpoint generates a vector embedding for a given string of text using the company's configured embedding model.

**Example Call:**
```bash
curl -X POST \
  https://your-iatoolkit-instance.com/api/my_company/embedding \
  -H "Authorization: Bearer <your_api_key>" \
  -H "Content-Type: application/json" \
  -d '{
        "text": "This is the text to embed."
      }'
```

**Example Response:**
```json
{
  "embedding": "AbCdEfGhIjKlMnOp... (base64 encoded string) ...=",
  "model": "text-embedding-3-small"
}
```







