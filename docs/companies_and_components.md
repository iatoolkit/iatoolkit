# Understanding and Configuring a Company in IAToolkit

## 1. The "Company" Concept

IAToolkit is a multi-tenant framework designed to serve multiple, isolated "Companies" (or projects) from a single core application. A **Company** is the central concept for this isolation. It's not just a user profile; it is a self-contained Python module that encapsulates all the specific data, logic, branding, and context required for the AI to operate within a particular business domain.

This modular approach allows you to create highly customized AI agents for different clients or internal departments, each with its own unique knowledge and capabilities, without them interfering with one another.

### Anatomy of a Company Module

Each Company module is a self-contained directory that encapsulates all company-specific 
resources—from configuration and AI context to prompt templates and sample data. 
The structure below shows the organization of a typical company module, 
using `sample_company` as the reference implementation:

companies/sample_company/              # Company module directory
├── config/                            # Configuration files
│   ├── company.yaml                   # Main company configuration
│   ├── onboarding_cards.yaml          # UI onboarding content
│   └── help_content.yaml              # Help system content
│
├── context/                           # AI context (Markdown files)
│   ├── company_overview.md            # General company information
│   ├── business_rules.md              # Business logic and rules
│   ├── procedures.md                  # Standard operating procedures
│   └── faqs.md                        # Frequently asked questions
│
├── schema/                            # Data structure definitions (YAML)
│   ├── database_schemas.yaml          # Database table schemas
│   └── api_schemas.yaml               # API response structures
│
├── prompts/                           # Jinja2 prompt templates
│   ├── analisis_ventas.prompt         # Sales analysis prompt
│   ├── supplier_report.prompt         # Supplier report prompt
│   └── analisis_despachos.prompt      # Shipment analysis prompt
│
├── templates/                         # Company-specific HTML templates
│   └── custom_page.html               # Custom pages for this company
│
├── sample_data/                       # Sample documents for RAG
│   ├── supplier_manuals/              # Supplier manual documents
│   └── employee_contracts/            # Employee contract documents
│
└── sample_company.py                  # Company module entry point (Python class)

---

## 2. The `company.yaml` Configuration File

The `company.yaml` file is the central configuration hub for your AI assistant. 
It declaratively defines all aspects of your company's behavior, from LLM selection and database connections to UI branding and knowledge base sources. 
The diagram below illustrates the complete structure and hierarchy of the configuration file:

company.yaml
│
├── General Information              # Company identity and LLM configuration
│   ├── id, name, locale
│   └── llm (model, api-key)
│
├── Embedding Provider               # Vector embeddings for semantic search
│   ├── provider (openai/huggingface)
│   ├── model
│   └── api_key_name
│
├── Data Sources                     # SQL database connections
│   └── sql[]
│       ├── database
│       ├── connection_string_env
│       ├── description
│       ├── include_all_tables
│       ├── exclude_tables[]
│       ├── exclude_columns[]
│       └── tables{}
│           ├── schema_name
│           ├── exclude_columns[]
│           └── description
│
├── Tools (Functions)                # Custom AI capabilities
│   └── []
│       ├── function_name
│       ├── description
│       └── params (OpenAPI schema)
│
├── Prompts                          # UI prompt configuration
│   ├── prompt_categories[]
│   └── prompts[]
│       ├── category
│       ├── name
│       ├── description
│       ├── order
│       └── custom_fields[]
│
├── Parameters                       # Custom company settings
│   ├── cors_origin[]
│   ├── user_feedback{}
│   └── external_urls{}
│
├── Branding                         # UI customization
│   ├── header_background_color
│   ├── header_text_color
│   ├── brand_primary_color
│   └── brand_secondary_color
│
├── Help Files                       # User assistance content
│   ├── onboarding_cards
│   └── help_content
│
└── Knowledge Base (RAG)             # Document indexing for semantic search
    ├── connectors{}
    │   ├── development (type: local)
    │   └── production (type: s3)
    └── document_sources{}
        └── [source_name]
            ├── path
            └── metadata{}



The configuration file for the Sample Company can be found at **[`companies/sample_company/config/company.yaml`](../companies/sample_company/config/company.yaml)**

This file serves as a complete, working example that you can use as a template when creating your own company configurations.
```yaml
# IAToolkit Company Configuration for: sample_company
# Location: companies/sample_company/config/company.yaml

# General Company Information
id: "sample_company"
name: "Sample Company"
locale: "es_ES"
llm:
  model: "gpt-5"
  api-key: "OPENAI_API_KEY"

# Embeddings: supported only openai and huggingface. only one at a atime
embedding_provider:
  provider: "openai"
  model: "text-embedding-ada-002"
  api_key_name: "OPENAI_API_KEY"

# Data Sources
# Defines the SQL data sources available to the LLM.
data_sources:
  sql:
    - database: "sample_database"
      connection_string_env: "SAMPLE_DATABASE_URI"
      description: |
        Esta es la base de datos principal de  Sample Company.
 
      # Loads all the databases tables automatically
      include_all_tables: true


# Tools (Functions)
# Defines the custom actions the LLM can take, including their parameters.
tools:
  - function_name: "document_search"
    description: "Busquedas sobre documentos: manuales, contratos de trabajo de empleados, manuales de procedimientos, y documentos legales."
    params:
      type: "object"
      properties:
        query:
          type: "string"
          description: "Texto o pregunta a buscar en los documentos."
      required: ["query"]

# Prompts
# Defines the ordered list of categories and the prompts available in the UI.
prompt_categories:
  - "General"
  - "Análisis Avanzado" 

prompts:
  - category: "General"   
    name: "analisis_ventas"
    description: "Analisis de ventas"
    order: 1
  - category: "General"
    name: "supplier_report"
    description: "Análisis de proveedores"
    order: 2
    custom_fields:
      - data_key: "supplier_id"
        label: "Identificador del Proveedor"

# Branding and Content Files
# this section defines the colors used in the UI
branding:
  header_background_color: "#4C6A8D"
  header_text_color: "#FFFFFF"
  brand_primary_color: "#4C6A8D"

# Knowledge Base (RAG)
# Defines the sources of unstructured documents for indexing.
knowledge_base:

  # Connectors
  # Defines how to connect to the document storage for different environments.
  # El comando 'load' usará el conector apropiado según el FLASK_ENV.
  connectors:
    development:
      type: "local"
    production:
      type: "s3"
      bucket: "iatoolkit"
 
  # Document Sources
  # A map defining the logical groups of documents to be indexed.
  # Cada clave es un tipo de fuente, que contiene su ubicación y metadatos.
  document_sources:
    supplier_manuals:
      path: "companies/sample_company/sample_data/supplier_manuals"
      # Metadatos que se aplicarán a todos los documentos de esta fuente.
      metadata:
        type: "supplier_manual"
```
In the following sections, we'll walk through each component of the `company.yaml` file 
in detail, explaining its purpose, available options, and best practices. 
By understanding these building blocks, you'll be able to fully customize your 
AI assistant to meet your specific business requirements.

### 2.1 General Information

This section establishes the core identity of your company within IAToolkit. 
Here you define the unique identifier that will be used in URLs and routing, 
the display name shown to users, and the default language/locale for the interface.
Most importantly, this is where you specify which Large Language Model (LLM) your AI 
assistant will use for reasoning and generating responses. 
The LLM configuration includes both the model name and a reference to the environment 
variable that securely stores your API key.
```yaml
# General Company Information
id: "sample_company"
name: "Sample Company"
locale: "es_ES"
llm:
  model: "gpt-5"
  api-key: "OPENAI_API_KEY"
```

*   **`id`**: A unique, lowercase string identifier used in URLs and internal lookups.
*   **`name`**: The full, user-facing name of the company.
*   **`locale`**: The default language and region for internationalization (i18n).
*   **`llm`**:
    *   **`model`**: The specific LLM to use for chat and tool execution (e.g., `gpt-4`, `gemini-pro`).
    *   **`api-key`**: The **name of the environment variable** that holds the API key for the LLM provider.

### 2.2 Embedding Provider

Embeddings are numerical representations of text that enable semantic search capabilities. 
This section configures which embedding model your company will use to convert documents and queries into vectors for similarity matching. IAToolkit supports multiple providers, allowing you to choose between OpenAI's models (offering high quality at a cost) or HuggingFace's open-source alternatives (offering flexibility and potential cost savings). The embedding provider works behind the scenes to power your document search and RAG (Retrieval-Augmented Generation) features. Note that you can use a different provider for embeddings than you use for your main LLM.
```yaml
# Embeddings: supported only openai and huggingface. only one at a atime
embedding_provider:
  provider: "openai"
  model: "text-embedding-ada-002"
  api_key_name: "OPENAI_API_KEY"
```
*   **`provider`**: The embedding service. Currently supports `openai` and `huggingface`.
*   **`model`**: The specific embedding model to use.
*   **`api_key_name`**: The **name of the environment variable** that holds the API key for the embedding provider. Often, this is the same as the LLM's API key.

**Alternative configuration for HuggingFace:**

### 2.3 Data Sources (SQL)

This is one of the most powerful features of IAToolkit: the ability to connect your 
AI directly to your corporate databases. 
In this section, you declaratively define which databases the AI can access, 
along with metadata that helps the LLM understand when and how to query them. 
The framework supports automatic table discovery, meaning it can inspect your 
database schema and make all tables available to the AI with minimal configuration. 
You also have fine-grained control to exclude sensitive tables or columns, 
and you can provide custom descriptions to guide the AI toward better query generation. 
This zero-code approach to database integration is what enables natural language to 
SQL translation without manual schema mapping.
```yaml
# Data Sources
data_sources:
  sql:
    - database: "sample_database"
      connection_string_env: "SAMPLE_DATABASE_URI"
      description: |
        Esta es la base de datos principal de  Sample Company.
        Contiene toda la información comercial y operativa la empresa.
        Es la fuente principal para responder preguntas sobre ventas, despachos,
        ordenes de compra, empleados, paises y territorios.

      # Loads all the databases tables automatically
      include_all_tables: true
      # ...but ignore these specific tables
      exclude_tables:
        - "test_table"
        - "logs"
      # exclude these columns from all tables
      exclude_columns: [ 'created', 'updated' ]
      #    El servicio usará esta sección para añadir detalles a las tablas
      #    que se cargaron automáticamente con 'include_all_tables'.
      tables:
        employee_territories:
          # Para esta tabla, usa un nombre de esquema personalizado.
          schema_name: "employee_territory"

        orders:
          # Para la tabla 'orders', ignora la lista global 'exclude_columns'
          # y usa esta lista más específica en su lugar.
          exclude_columns: [ 'internal_notes', 'processing_id' ]

        products:
          # Para la tabla 'products', no hay overrides, pero podríamos
          # añadir una descripción personalizada aquí si quisiéramos.
          description: "Catálogo de productos de la compañía."
```

*   **`database`**: A logical name for this database.
*   **`connection_string_env`**: The name of the environment variable containing the database connection URI.
*   **`description`**: A crucial high-level summary that helps the AI understand when to use this database.
*   **`include_all_tables`**: If `true`, IAToolkit will automatically inspect the database and load all table schemas.
*   **`exclude_tables`**: Global rules to hide specific tables from the AI.
*   **`exclude_columns`**: Global rules to hide specific columns from all tables.
*   **`tables`**: An optional block to provide table-specific overrides:
    *   **`schema_name`**: Use a custom schema name for this table.
    *   **`exclude_columns`**: Override the global exclude_columns for this specific table.
    *   **`description`**: Provide a more detailed description for this table.

### 2.4 Tools (Functions)

Tools (also called functions or actions) extend your AI assistant's capabilities beyond 
simple conversation. They are custom operations that the LLM can invoke to perform 
specific tasks—from searching documents and querying databases to sending emails, 
generating reports, or calling external APIs. In this section, 
you declare what tools are available to your AI, along with clear descriptions 
that help the LLM understand when each tool should be used. 
The parameter schemas follow the OpenAPI standard, ensuring type safety and providing 
the LLM with precise information about what inputs each tool expects. 
This declarative approach means you can add powerful capabilities to your assistant
without complex integration code—just define the tool in YAML and implement its logic 
in Python.
```yaml
# ools (Functions)
# Defines the custom actions the LLM can take, including their parameters.
tools:
  - function_name: "document_search"
    description: "Busquedas sobre documentos: manuales, contratos de trabajo de empleados, manuales de procedimientos, y documentos legales."
    params:
      type: "object"
      properties:
        query:
          type: "string"
          description: "Texto o pregunta a buscar en los documentos."
      required: ["query"]
```

*   **`function_name`**: The name of the function the LLM will invoke. This maps to a function you implement in your Company's Python code.
*   **`description`**: A clear, natural language description telling the AI *when* and *why* it should use this tool.
*   **`params`**: An OpenAPI-style schema defining the parameters the function accepts.

### 2.5 Prompts

Prompts are pre-configured, reusable conversation starters that appear in your 
application's user interface. They serve as guided entry points for common tasks,
helping users get started quickly without needing to know exactly what to ask. 
This section allows you to organize prompts into categories and define custom 
input fields for each one. For example, a "Sales Analysis" prompt might include 
date pickers for selecting a time range, or a "Supplier Report" prompt might have 
a text field for entering a supplier ID. These structured prompts combine the power 
of your custom Jinja2 templates (stored in the `prompts/` directory) with a 
user-friendly UI, making complex multi-step tasks accessible to non-technical users.

```yaml
# Prompts
# Defines the ordered list of categories and the prompts available in the UI.
prompt_categories:
  - "General"
  - "Análisis Avanzado"     # sample for adding more categories

prompts:
  - category: "General"     # assign this prompt to the category "General"
    name: "analisis_ventas"
    description: "Analisis de ventas"
    order: 1
  - category: "General"
    name: "supplier_report"
    description: "Análisis de proveedores"
    order: 2
    custom_fields:
      - data_key: "supplier_id"
        label: "Identificador del Proveedor"
  - category: "General"
    name: "analisis_despachos"
    description: "Analisis de despachos"
    order: 3
    custom_fields:
      - data_key: "init_date"
        label: "Fecha desde"
        type: "date"
      - data_key: "end_date"
        label: "Fecha hasta"
        type: "date"

```

*   **`prompt_categories`**: Defines the groups for organizing prompts in the UI.
*   **`prompts`**: A list of available prompts.
    *   **`category`**: The category this prompt belongs to.
    *   **`name`**: The internal identifier for the prompt (should match a `.prompt` file in the `prompts/` directory).
    *   **`description`**: User-facing description displayed in the UI.
    *   **`order`**: Display order within its category.
    *   **`custom_fields`**: Defines additional input fields that will be displayed in the UI for this prompt:
        *   **`data_key`**: The parameter name that will be passed to the prompt template.
        *   **`label`**: User-facing label for the field.
        *   **`type`**: Field type (e.g., `"text"`, `"date"`).

### 2.6 Company-specific Parameters

This section acts as a flexible storage area for any custom configuration parameters 
your company might need. It's a key-value map where you can define company-specific 
settings that don't fit into the other structured sections. 
Common uses include CORS origin configurations for web integrations, 
user feedback channels (email, webhooks, etc.), 
external URLs for logout redirects or SSO integrations, 
and any other custom parameters your business logic requires. 
This flexibility ensures that IAToolkit can adapt to unique requirements without 
requiring framework modifications.

```yaml
parameters:
  cors_origin:
    - "https://portal-interno.empresa_de_ejemplo.cl"
  user_feedback:
    channel: "email"
    destination: "fernando.libedinsky@gmail.com"
  external_urls:
    logout_url: ""
```
*   **`cors_origin`**: List of allowed origins for CORS (Cross-Origin Resource Sharing).
*   **`user_feedback`**: Configuration for user feedback collection.
*   **`external_urls`**: External URLs for integration (e.g., custom logout redirects).

### 2.7 Branding

One of IAToolkit's most powerful multi-tenant features is the ability to fully 
customize the look and feel of the interface for each company. 
In this section, you define the color scheme that will be applied throughout 
the user interface—from headers and buttons to text and backgrounds. 
This allows you to create white-labeled experiences where each client or 
department sees an interface that matches their brand identity. 
All customization is done through simple hexadecimal color values, 
with no front-end coding required. The system automatically applies 
these colors to all UI components, ensuring a consistent branded experience.

```yaml
# Branding and Content Files
branding:
  header_background_color: "#4C6A8D"
  header_text_color: "#FFFFFF"
  brand_primary_color: "#4C6A8D"
  brand_secondary_color: "#9EADC0"
  brand_text_on_primary: "#FFFFFF"
  brand_text_on_secondary: "#FFFFFF"
```
All colors are specified in hexadecimal format. These values control various UI elements, allowing each company to have its own visual identity.

### 2.8 Help Files

User assistance and onboarding are critical for adoption. 
This section points to additional YAML files that contain structured content 
for help systems, onboarding tutorials, and contextual assistance. 
These files allow you to create rich, interactive help experiences—such as 
step-by-step onboarding cards that guide new users through the system, 
or context-sensitive help content that appears when users need assistance. 
By keeping this content in separate, structured files, you can easily update 
help documentation without touching code, and even localize it for different languages.

```yaml
# Help files
help_files:
  onboarding_cards: "onboarding_cards.yaml"
  help_content: "help_content.yaml"
```

These files should be located in the company's `config/` directory.

### 2.9 Knowledge Base (RAG)

This section enables one of the most valuable AI capabilities: the ability to answer 
questions based on your organization's private documents. 
Here you define where your unstructured documents (PDFs, Word files, text files, etc.) 
are stored and how they should be organized. The system automatically handles the complex 
process of chunking documents, generating embeddings, 
and storing them in a vector database for fast semantic search. 
You can configure different storage connectors for different environments 
(local files for development, S3 for production), and you can organize documents 
into logical groups with metadata tags that enable filtered searches. 
This Retrieval-Augmented Generation (RAG) capability transforms your static 
documents into an interactive knowledge base that your AI can query and reason over.

```yaml
# Knowledge Base (RAG)
# Defines the sources of unstructured documents for indexing.
knowledge_base:

  # Connectors
  # Defines how to connect to the document storage for different environments.
  # El comando 'load' usará el conector apropiado según el FLASK_ENV.
  connectors:
    development:
      type: "local"
    production:
      type: "s3"
      bucket: "iatoolkit"
      prefix: "sample_company"

  # Document Sources
  # A map defining the logical groups of documents to be indexed.
  # Cada clave es un tipo de fuente, que contiene su ubicación y metadatos.
  document_sources:
    supplier_manuals:
      path: "companies/sample_company/sample_data/supplier_manuals"
      # Metadatos que se aplicarán a todos los documentos de esta fuente.
      metadata:
        type: "supplier_manual"

    employee_contracts:
      path: "companies/sample_company/sample_data/employee_contracts"
      metadata:
        type: "employee_contract"

```
*   **`connectors`**: Defines where to find the documents depending on the environment (`development` vs. `production`). This allows you to test with local files and use cloud storage like S3 in production.
    *   **`development`**: Typically uses `type: "local"` to read from the local filesystem.
    *   **`production`**: Typically uses `type: "s3"` for AWS S3 storage, requiring bucket name, prefix, and AWS credentials from environment variables.

*   **`document_sources`**: A map of logical document groups. Each source has:
    *   **`path`**: The local or S3 path where the documents are located.
    *   **`metadata`**: Key-value pairs that will be automatically attached to every document indexed from this source. This is extremely useful for filtering searches later (e.g., searching *only* within employee contracts using `metadata_filter={"type": "employee_contract"}`).

---

## 3. Creating a New Company

To create a new company, you can scaffold it from the `sample_company` template:

1. **Duplicate the Folder**: In the `companies/` directory, copy `sample_company` and rename the copy to `my_company`.

2. **Rename the Core File**: Inside `companies/my_company/`, rename `sample_company.py` to `my_company.py`.

3. **Update the Class Name**: Open `my_company.py` and change the class name from `SampleCompany` to `MyCompany`.

4. **Update the Configuration**: Edit `companies/my_company/config/company.yaml` and update all the configuration values according to your needs.

5. **Register the New Company**: Open `app.py` and add the following lines:

6. **Add Context and Resources**:
   - Place Markdown files in `companies/my_company/context/`
   - Add schema files to `companies/my_company/schema/`
   - Create prompt templates in `companies/my_company/prompts/`

7. **Set Environment Variables**: Ensure all required environment variables referenced in your `company.yaml` (like database URIs and API keys) are properly set.

---

## 4. Best Practices

### 4.1 Organizing Context Files

Structure your context files logically. For example:
- `context/company_overview.md` - General company information
- `context/business_rules.md` - Business logic and rules
- `context/procedures.md` - Standard operating procedures
- `context/faqs.md` - Frequently asked questions

### 4.2 Writing Good Tool Descriptions

The `description` field in your tools configuration is critical. Write descriptions that:
- Clearly state what the tool does
- Explain when the AI should use it
- Mention the types of questions it can answer
- Include relevant examples if helpful

### 4.3 Database Configuration

When configuring data sources:
- Provide clear, comprehensive descriptions for databases
- Use `exclude_columns` to hide sensitive data or irrelevant fields
- Add table-specific descriptions for complex or important tables
- Test your queries to ensure the AI has access to the right data

### 4.4 Prompt Templates

When creating `.prompt` files:
- Use clear, descriptive filenames that match the `name` in `company.yaml`
- Leverage Jinja2 features for dynamic content
- Include comments to explain complex logic
- Test prompts thoroughly with various inputs

---

## 5. Summary

By combining the Python module for logic and the `company.yaml` for configuration, you can create a powerful, context-aware, and fully customized AI agent that is deeply integrated with your unique business environment. The modular design of IAToolkit ensures that each company operates in complete isolation while sharing the robust core infrastructure.

The key benefits of this architecture are:
- **Isolation**: Each company has its own data, context, and configuration
- **Customization**: Branding, prompts, and behavior can be tailored per company
- **Scalability**: Add new companies without affecting existing ones
- **Maintainability**: Clear separation between core framework and company-specific code
- **Flexibility**: Mix and match different LLM providers, databases, and storage solutions per company

Start by exploring the `sample_company` implementation, then create your own company following the steps outlined above. The configuration file is your primary tool for customization, while the Python module gives you the flexibility to implement custom business logic when needed.