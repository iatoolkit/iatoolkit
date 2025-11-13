# Understanding and Configuring a Company in IAToolkit

## 1. The "Company" Concept

IAToolkit is a multi-tenant framework designed to serve multiple, isolated "Companies" (or projects) from a single core application. A **Company** is the central concept for this isolation. It's not just a user profile; it is a self-contained Python module that encapsulates all the specific data, logic, branding, and context required for the AI to operate within a particular business domain.

This modular approach allows you to create highly customized AI agents for different clients or internal departments, each with its own unique knowledge and capabilities, without them interfering with one another.

### Anatomy of a Company Module

Every Company resides in its own directory within the `companies/` folder. The `companies/sample_company/` directory serves as a complete reference implementation. Here is a breakdown of its essential components:

*   **`sample_company.py`**: This is the heart of your module. It contains a primary class (e.g., `SampleCompany`) that inherits from `iatoolkit.base_company.BaseCompany`. This class acts as the entry point for registering your company with the core application.

*   **`config/company.yaml`**: This is the primary configuration file for your Company. It declaratively defines everything from database connections and branding to available LLM tools and knowledge base sources. We will explore this file in detail in the next section.

*   **`context/`**: This directory contains `.md` (Markdown) files. Any text you place here—business rules, operational procedures, product descriptions, FAQs—is automatically loaded into the AI's system prompt. This is the primary way to provide the AI with the static, domain-specific knowledge it needs to answer questions accurately.

*   **`schema/`**: This directory holds `.yaml` files that define data structures. These can be database table schemas, API response structures, or any other structured data. By providing these schemas, you enable the AI to understand your data models, allowing it to generate precise SQL queries or correctly interpret API responses.

*   **`prompts/`**: This directory is for `.prompt` files, which are powerful Jinja2 templates. They are used for complex, multi-step tasks or for generating structured outputs. You can instruct the AI to use a specific prompt to perform a task, guiding its reasoning process and ensuring consistent results.

---

## 2. The `company.yaml` Configuration File

The `company.yaml` file is where you define the behavior and resources for your Company. It's structured into several logical sections. Let's break down each part using the `sample_company` configuration as a reference.
The configuration file for the Sample Company can be found at:

**[`companies/sample_company/config/company.yaml`](../companies/sample_company/config/company.yaml)**

This file serves as a complete, working example that you can use as a template when creating your own company configurations.

### 2.1 General Information

This section defines the basic identity of the company and the primary LLM it will use.


*   **`id`**: A unique, lowercase string identifier used in URLs and internal lookups.
*   **`name`**: The full, user-facing name of the company.
*   **`locale`**: The default language and region for internationalization (i18n).
*   **`llm`**:
    *   **`model`**: The specific LLM to use for chat and tool execution (e.g., `gpt-4`, `gemini-pro`).
    *   **`api-key`**: The **name of the environment variable** that holds the API key for the LLM provider.

### 2.2 Embedding Provider

This configures the model used for creating vector embeddings, which is essential for semantic search (RAG).

*   **`provider`**: The embedding service. Currently supports `openai` and `huggingface`.
*   **`model`**: The specific embedding model to use.
*   **`api_key_name`**: The **name of the environment variable** that holds the API key for the embedding provider. Often, this is the same as the LLM's API key.

**Alternative configuration for HuggingFace:**

### 2.3 Data Sources (SQL)

This section defines the structured data sources (databases) the AI can query.

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

Here, you define custom functions the LLM can call to perform actions. This is the foundation of the agent's capabilities.

*   **`function_name`**: The name of the function the LLM will invoke. This maps to a function you implement in your Company's Python code.
*   **`description`**: A clear, natural language description telling the AI *when* and *why* it should use this tool.
*   **`params`**: An OpenAPI-style schema defining the parameters the function accepts.

### 2.5 Prompts

This section configures the list of pre-defined prompts that appear in the user interface, helping guide users toward common tasks.

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

A flexible key-value store for any custom parameters your company's logic might need.

*   **`cors_origin`**: List of allowed origins for CORS (Cross-Origin Resource Sharing).
*   **`user_feedback`**: Configuration for user feedback collection.
*   **`external_urls`**: External URLs for integration (e.g., custom logout redirects).

### 2.7 Branding

Defines the color scheme to give the UI a custom look and feel for this company.

All colors are specified in hexadecimal format. These values control various UI elements, allowing each company to have its own visual identity.

### 2.8 Help Files

Points to other YAML files containing content for UI elements like onboarding tutorials or help modals.


These files should be located in the company's `config/` directory.

### 2.9 Knowledge Base (RAG)

This powerful section defines the sources of unstructured documents (like PDFs, Word docs, etc.) that will be indexed into the vector store for Retrieval-Augmented Generation (RAG).

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