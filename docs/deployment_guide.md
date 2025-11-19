# IAToolkit Deployment Guide

This guide provides step-by-step instructions for deploying a production-ready instance of IAToolkit. We will focus on a robust and scalable strategy where your company-specific code is managed in a separate, private repository that consumes the IAToolkit framework as a dependency.

This approach is highly recommended for production as it cleanly separates your proprietary business logic from the core framework, simplifying updates and maintenance.

## 1. Prerequisites

Before you begin, ensure you have the following resources provisioned on your cloud provider of choice (e.g., Heroku, AWS, Google Cloud):

1.  **A PostgreSQL Database**: For the core IAToolkit system (users, queries, etc.).
2.  **A Redis Instance**: For session management and caching.
3.  **(Optional) A second PostgreSQL Database**: For your company-specific data (e.g., the Northwind sample database).
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
## 3.2 app.py  (Application Entry Point)

This file is responsible for creating the Flask application. It imports and registers only the companies that should be active in this specific deployment.
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
    return toolkit.create_iatoolkit()


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

## 5. Running One-Off Administrative Commands
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









