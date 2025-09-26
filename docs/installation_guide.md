# IAToolkit — New Company Onboarding Guide

This guide explains how to create and register a new company using the `sample_company` template. 
Follow these steps to get a working “Hello World” company and then customize it.

## Prerequisites

- Python 3.12
- A valid `DATABASE_URI` (SQLite/PostgreSQL/MySQL)
- Optional: `REDIS_URL` for session storage
- LLM provider api-key required: `OPENAI_API_KEY`, `GOOGLE_API_KEY`
- Environment variables loaded from `.env`

## 1) Scaffold your company module

Duplicate the sample implementation and rename it:

1. Go to `companies/`
2. Copy the folder `sample_company` → `my_company`
3. Inside your new folder, rename `sample_company.py` to `my_company.py`
4. In `my_company.py` update the class name to your company (e.g., `SampleCompany` → `MyCompany`)
5. Replace references of `sample_fintech`/`sample_company` with `my_company` where applicable (short name, identifiers, etc.)
6. Edit the `register_company_method` in the new module for use the new company short_name (`my_company`)
7. and name (`the name of my company`)
Expected structure:

## 2) Register the company

Register your company before the app is created editting the file app.py on the line:

register_company("sample_company", SampleCompany)

# example: sample key/class
register_company("my_company", MyCompany)  # your new company

- The registry key (e.g., `"my_company"`) should be lowercase and stable.
- Ensure the value your company’s short_name in the companies table  matches this name.

## 3) Configure environment

update `.env` at the project root with your own values.


## 4) Initialize DB and generate API key

Run the built-in setup command (initializes system/company data and creates the first API key):
flask setup-company my_company

you will see this:
```
🚀 step 1 of 2: init companies in the database...
✅ database is ready.
🔑 step 2 of 2: generating api-key for use in 'sample_company'...
Configuration es ready, add this variable to your environment
IATOOLKIT_API_KEY=S1UGpvMwuuuuud118Xc0wyxzkbM0FaGdQCL0hALfo
```

after this you can see on the databases serveral tables created: 
user, companies, user_companies, functions, llm_queries, ...

you should add the IATOOLKIT_API_KEY to your .env file


## 5) Customize your company

- `companies/my_company/prompts/`: Prompt templates and system instructions
- `companies/my_company/context/`: Markdown docs used as domain context
- `companies/my_company/schema/`: YAML schemas (tables, API responses)
- `companies/my_company/my_company.py`: Custom tools and business logic
- `companies/my_company/configuration.py`: Model/provider settings

Start minimal, then iterate.

## 6) Run and test

Start the app:


Visit your frontend and enter into the application.
navigate into the home page, and enter the chat by registering yourself
into the toolkit.

## 7) Aditionals configuration

Allow additional CORS configuration by setting:



