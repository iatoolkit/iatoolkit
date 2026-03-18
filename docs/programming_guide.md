# IAToolkit Programming Guide

## Introduction

This guide is designed for developers who want to understand the internal architecture of 
IAToolkit, contribute to the core framework, or extend it with custom functionality. 
We'll explore the codebase structure, design patterns, key services, and best practices 
that make IAToolkit a robust, maintainable, and testable framework.

IAToolkit follows clean architecture principles with clear separation of concerns, 
dependency injection for loose coupling, and comprehensive test coverage to ensure 
reliability.

---

## 1. Project Structure Overview

The IAToolkit codebase is organized following a layered architecture pattern. 
Understanding this structure is essential for navigating the code and knowing where 
to add new features. 
The diagram below illustrates the complete project organization:

```text
iatoolkit/
├── src/
│   ├── iatoolkit/                    # Core framework code
│   │   ├── common/                   # Cross-cutting concerns and utilities
│   │   ├── infra/                    # Infrastructure layer (external integrations)
│   │   ├── repositories/             # Data access layer
│   │   ├── services/                 # Business logic layer
│   │   ├── views/                    # Presentation layer (Flask routes)
│   │   ├── templates/                # HTML Jinja2 templates
│   │   ├── static/                   # CSS, JavaScript, images
│   │   ├── cli_commands.py           # Flask CLI commands
│   │   ├── iatoolkit.py              # Main application factory
│   │   └── base_company.py           # Base class for company modules
│   │
│   └── tests/                        # Comprehensive test suite (90%+ coverage)
│
├── companies/                        # Company-specific modules
│   └── sample_company/               # Reference implementation
│       ├── context/                  # Markdown files for AI context
│       ├── schema/                   # YAML schema definitions
│       ├── prompts/                  # Jinja2 prompt templates
│       ├── templates/                # Jinja2 html templates: home.html
│       ├── config/                   # Company configuration files
│       └── sample_company.py         # Company module entry point
│
├── docs/                             # Documentation files
├── app.py                            # Application entry point
└── README.md                         # Project overview
```

### Layer Responsibilities

**Views Layer (`views/`)**
The presentation layer that handles HTTP requests and renders responses:
- Route handlers for web pages and API endpoints
- Request validation and parameter extraction
- Response formatting (HTML, JSON)
- Integration with templates for server-side rendering
- Security checks: session or api-key

**Service Layer (`services/`)**
Contains the core business logic:
- Query processing and routing
- Document management
- User authentication
- Configuration management
- And much more (detailed below)

**Repository Layer (`repositories/`)**
Manages all data persistence and retrieval:
- Database models (SQLAlchemy ORM)
- Data access objects (DAOs)
- Query builders
- Database connection management

**Infrastructure Layer (`infra/`)**
Handles all external system integrations:
- LLM provider adapters (OpenAI, Gemini)
- Email services (brevo mail)
- Cloud storage connectors (S3, GCS)
- Google Chat integration

**Common Layer (`common/`)**
Contains cross-cutting concerns and utilities used throughout the application:
- `exceptions.py`: Custom exception classes for error handling
- `util.py`: Helper functions (encryption, validation, rendering, etc.)
- `routes.py`: Route registration and view handlers
- `session_manager.py`: Session handling utilities

**Templates & Static Assets**
- `templates/`: Jinja2 HTML templates for rendering web pages
- `static/`: CSS stylesheets, JavaScript files, and images for the UI

---

## 2. Key Design Patterns

### 2.1 Dependency Injection

IAToolkit uses the `injector` library to implement dependency injection throughout the 
application. This pattern provides several critical benefits:

- **Testability**: Easy to mock dependencies in unit tests
- **Loose Coupling**: Components depend on abstractions, not concrete implementations
- **Flexibility**: Swap implementations without changing consuming code
- **Maintainability**: Clear dependencies make the code easier to understand

All dependencies are configured in `iatoolkit.py` within the `_configure_core_dependencies()` method, 
which acts as the composition root for the entire application.

### 2.2 Service Layer Pattern

The Service Layer is the heart of the application's business logic. 
It sits between the presentation layer (Views) and the data access layer (Repositories), 
orchestrating complex operations and business workflows. 
Services provide a clean and robust API for the rest of the application to interact with core functionalities.

#### Core Principles

*   **Single Responsibility**: Each service is designed to manage a specific business domain or capability. For instance, `AuthService` handles authentication, while `QueryService` manages llm query flow. This keeps the codebase organized and easy to understand.

*   **Orchestration, Not Implementation**: A service's primary role is to orchestrate tasks, not to implement low-level details. It defines a business workflow by coordinating calls to repositories (for data access), other services, or infrastructure components (like an email client). For example, a service might fetch data from two different repositories, combine it, and then use another service to send a notification.

*   **Stateless by Design**: Services should be stateless. All the data required for an operation should be passed as arguments to its methods. This makes services highly reusable, predictable, and easier to test, as their output depends only on their input, not on previous interactions.

*   **Dependency Injected**: All services are managed by the `injector` container. They declare their dependencies (such as repositories or other services) in their `__init__` method, and the DI container automatically provides the necessary instances.

### 2.3 Repository Pattern

The repository pattern abstracts data access logic, providing a clean interface between the business logic and data persistence layers.
Each repository is responsible for a specific domain entity.

**Benefits:**
- Centralized data access logic
- Easier to test business logic in isolation
- Database-agnostic business layer
- Simplified query management


### 2.4 Adapter Pattern (Infrastructure Layer)

External services are integrated using the adapter pattern, providing a uniform 
interface regardless of the underlying provider. 
This is particularly important for LLM integrations, 
where you might want to switch between OpenAI and Gemini without changing your business 
logic.

---

## 3. Core Services Reference

The service layer is the heart of IAToolkit's business logic. Here's a detailed overview of each major service:

### 3.1 QueryService (`query_service.py`)

**Purpose**: Orchestrates the entire query processing pipeline from user input to AI response.

**Key Responsibilities:**
- Receives user queries from the UI
- Manages conversation context and history
- Handle the rendering of prompt templates through the prompt manager
- Interfaces with LLM providers through the LLMClient
- Logs all interactions for auditing and cost tracking

---

### 3.2 DocumentService (`document_service.py`)

**Purpose**: Manages the lifecycle of documents within the system.

**Key Responsibilities:**
- Document upload to the iatoolkit database: `documents` and `vsdocs`tables
- Documents can be uploaded using the `/api/load` api-view (for a single document) or through a cli command. 
- File format handling (PDF, DOCX, TXT, etc.)
- Document chunking for vector storage
- Metadata management
- Integration with vector store for RAG capabilities

---
### 3.3 Dispatcher (`dispatcher_service.py`)

**Purpose**: The Dispatcher is the central router between the LLM’s tool/function calls and the actual business logic implemented per company. 
It takes a high‑level request (typically coming from the iatoolkit chat or an API endpoint), resolves which company and tools are involved, 
and then orchestrates the execution of the appropriate methods on the company service.

The Dispatcher is the bridge between:
- **LLM function calling** (structured tool calls)
- **Company-specific services** (implementations derived from `BaseCompany`)

---

#### Relationship with `BaseCompany`

Each company in the system is represented by a concrete class that extends `BaseCompany`. 
`BaseCompany` defines the common interface and shared behavior that all company services must implement.

- How to **load configuration** and credentials
- How to **fetch user information** (`user_info`) from the company’s data source (e.g., internal API, database, SSO)
- Which **tools / actions** are exposed (`handle_request`) to the LLM and how they should be invoked 

The Dispatcher does **not** implement business logic itself. Instead, it:

1. **Identifies the target company** (e.g. from a `company_short_name`).
2. **Retrieves** the corresponding `BaseCompany` subclass (e.g. `AcmeCompany`, `ContosoCompany`) using the loaded configuration.
3. **Delegates tool calls** to methods defined on that company instance.

This separation allows:
- A single Dispatcher implementation for all companies.
- Company‑specific variability (APIs, data models, permissions) encapsulated inside `BaseCompany` subclasses.
- Easier onboarding of new companies: you create a new `BaseCompany` implementation and register its tools; the Dispatcher logic remains unchanged.

---
#### Why this design?

- **Clear separation of concerns**  
  The Dispatcher focuses on orchestration (routing, validation, context management) and delegates all company-specific details (APIs, user model, permissions) to `BaseCompany` implementations.

- **Scalability for multi-tenant / multi-company environments**  
  Adding a new company does not require changes to the Dispatcher; you only provide a new `BaseCompany` subclass and register its tools.

- **LLM‑friendly interface**  
  Because all tools are invoked through the Dispatcher with stable schemas and error formats, the LLM sees a consistent, predictable set of tools, even though the underlying business logic may vary significantly per company.---

### 3.4 ConfigurationService (`configuration_service.py`)

**Purpose**: Centralized configuration management for companies.

**Key Responsibilities:**
- Loads and parses `company.yaml` files
- Provides typed access to configuration values
- Validates configuration schemas
- Caches configurations for performance

---
### 3.5 Company Context Service (`company_context_service.py`) 

**Purpose**: Centralizes all *per-company* and *per-session* context that is needed across views, services, and prompts.

While `ConfigurationService` focuses on static configuration (mainly from `company.yaml`),  
the **Company Context Service** is responsible for providing a *runtime view* of:

- Which company is currently active.
- Which user (if any) is associated with the session (`user_session_context_service`)
- Which language, branding, and feature flags apply to the current request.

**Key Responsibilities:**

- create the company context based on: schema and context files in the company directory
- store and retrieve the company/user context from redis store.
 
Another service  `user_session_context_service` keeps session-scoped structure based
on the current user_identity.

---

### 3.6 AuthService (`auth_service.py`)

**Purpose**: Handles user authentication and authorization.

**Key Responsibilities:**
- User login validation
- Session management
- Password hashing (bcrypt)
- API key validation for programmatic access
- log the access events `iat_access_log` table

---

### 3.7 PromptService (`prompt_manager_service.py`)

**Purpose**: Manages Jinja2-based prompt templates.

**Key Responsibilities:**
- Loads `.prompt` files from company directories
- Renders templates with dynamic context
- Validates template syntax
- Provides prompt versioning support

---

### 3.8 I18nService & LanguageService

**Purpose**: Internationalization and localization support.

**Key Responsibilities:**
- Loads translation files
- Provides the `t()` function for translating UI strings
- Manages language detection and switching
- Per-company locale configuration

---

### 3.9 BrandingService (`branding_service.py`)

**Purpose**: Manages company-specific UI customization.

**Key Responsibilities:**
- Loads branding configurations from `company.yaml`
- Provides color schemes to templates
- Manages company logos and assets
- Enables white-label experiences

---
### 3.10 EmbeddingService (`embedding_service.py`)

**Purpose**: Provides text embedding capabilities for semantic search.

**Key Responsibilities:**
- Generates vector embeddings from text
- Supports multiple embedding providers (OpenAI, HuggingFace)
- Manages provider-specific client configurations per company
- Caches embedding clients for performance

---
### 3.11 ProfileService (`profile_service.py`)

**Purpose**: Manages user profile data and exposes a unified view of the “current user” within a given session and company.

**Key Responsibilities:**
- signin/signup business logic
- Retrieves the current user’s profile based on the active session.
- Resolves the current company for the user (especially when a user can access multiple companies).
- Integrates with `SessionManager` and `AuthService` to keep the profile in sync with the authentication state.

---

### 3.12 HistoryService 

**Purpose**: Retrieves the history of user interactions with the assistant (queries, responses, tool calls).

**Key Responsibilities:**
- Provide APIs to:
  - Load recent history for a given `company/user_identification`.
  - Conversation continuation across sessions.
  - display the history in the UI.

This history can be consulted by the UI to provide a rich chat experience.

### 3.13  UserFeedbackService

**Purpose**: Collects and stores user feedback about the toolkit

**Key Responsibilities:**
- Capture feedback events from the UI:
  - Whether an answer was helpful.
  - Free-text comments explaining why.
- Link feedback to:
  - A specific query or response in the history.
  - A specific user and company.
- Provide aggregated views for:
  - Quality monitoring.
  - Continuous improvement of prompts, tools, and data sources.

Feedback configuration (channel, destination) is usually defined in `company.yaml` under `parameters.user_feedback`.

---

### 3.14 TaskService (`tasks_service.py`) *(in construction)*

**Purpose**: Orchestrates background and long-running tasks such as document ingestion, batch analyses, or scheduled jobs.

**Key Responsibilities (current and planned):**
- Define a common interface for tasks:
  - Creation (enqueueing a new task).
  - Status tracking (pending, running, completed, failed).
- Provide APIs for:
  - Listing tasks for a given company and/or user.
  - Inspecting task logs and outputs.
  - Retrying failed tasks.
  - user authorization of llm results

**Status:**
- The service is under active development.
- Expect the interface and capabilities to evolve as more use cases (scheduled jobs, multi-step workflows) are standardized.

## 4. The IAToolkit Object and Application Lifecycle

The `IAToolkit` class (`iatoolkit.py`) is the core application factory and implements the 
Singleton pattern to ensure only one instance exists throughout the application lifecycle.

### 4.1 Initialization Flow

When you call `create_app()`, the following happens:

1. **Configuration Loading**: Environment variables and config dictionaries are processed
2. **Flask App Creation**: A Flask instance is created with proper settings
3. **Database Setup**: Database connection is established and tables are created
4. **Dependency Injection**: The Injector is configured with all service bindings
5. **Route Registration**: All views and API endpoints are registered
6. **Company Initialization**: Company modules are loaded and instantiated
7. **Dispatcher Configuration**: Tools and configurations are loaded for each company
8. **Middleware Setup**: CORS, session management, and other middleware are configured

### 4.2 Flow of a Query

This section provides a high-level overview of how a user's query is processed by IAToolkit, 
from the initial request to the final answer. The entire process is designed to be a conversation, 
where the system can use tools to gather information before formulating a response.

#### High-Level Sequence Diagram

The flow is orchestrated primarily by the `QueryService`, which acts as the central "brain" for 
handling a user's request.

```text
[] User / Browser
        |
        v
[1] Flask View (receives request, authenticates)
        |
        v
[2] QueryService (builds full prompt using config + context)
        |
        v
[3] LLM (first call: decides answer OR requests a tool)
        |
        +--> If tool is needed:
               |
               v
        [5] Dispatcher (executes the tool function)
               |
               v
        [] Data Sources (DB, APIs, documents)
               |
               v
        [6] Dispatcher → QueryService (returns tool result)
               |
               v
        [7] LLM (second call with tool result → final answer)
        |
        v
[8] llmClient (logs everything, formats response)
        |
        v
[] Flask View → Browser (final JSON answer)

```


#### Step-by-Step Breakdown

1.  **Request Reception (The View)**
    The user sends a message from the browser. A Flask view (like `LLMQueryApiView`) receives the HTTP request, authenticates the user (via session or API key), and passes the query to the `QueryService`.

2.  **Orchestration (`QueryService`)**
    The `QueryService` is the main orchestrator. It loads the company's configuration and context (system prompts, available tools from `company.yaml`, etc.) and combines it with the user's message and conversation history to build a complete prompt for the Large Language Model (LLM).

3.  **First LLM Call**
    The `QueryService` sends the prompt to the configured LLM provider (e.g., OpenAI, Gemini). This is the "thinking" step where the LLM decides what to do next.

4.  **Tool Call (Optional)**
    Often, the LLM can't answer directly and needs more information. In this case, it will respond not with an answer, but with a structured request to call a tool. For example, it might ask to execute `document_search(query="company vacation policy")`.

5.  **Tool Execution (`Dispatcher`)**
    The `QueryService` receives the tool call request and delegates it to the `Dispatcher`. The Dispatcher is responsible for finding the correct Python function that corresponds to the tool's name and executing it with the provided arguments. This is how the AI interacts with your databases, APIs, and other data sources.

6.  **Continuing the Conversation**
    The result from the tool (e.g., the content of a document or the result of a SQL query) is returned to the  LLM in a second call, essentially saying, "I ran the tool you asked for, here is the result. Now, can you answer the user's original question?"

7.  **Final Response**
    With all the necessary information in hand, the LLM generates the final, human-readable answer.

8.  **Logging and Return**
    The `llmClient` receives this final text. Before sending it back to `QueryService`, it logs the entire interaction, including token usage and any tool calls, for analytics and auditing. The formatted answer is then as a JSON response.

## 5. Front end

The IAToolkit front end is a lightweight, server‑rendered UI built on top of **Flask**, **Jinja2 templates**, and a small amount of **JavaScript**. 
The goal is to provide a clean chat experience that can be easily branded and extended per Company, 
without requiring a complex SPA framework.

At a high level:

- **HTML structure** is defined in Jinja2 templates (e.g., `chat.html`).
- **Dynamic behavior** (sending messages, updating the chat, handling modals) is implemented with plain JavaScript or minimal libraries.
- **Styling and layout** are handled through CSS, with color and branding coming from `company.yaml`.

---

### 5.1 Main Chat Template: `chat.html`

The core user experience is the chat interface, typically rendered by a template like `chat.html`:

- Contains:
  - A **message history area** where user and assistant messages are displayed.
  - A **message input box** (textarea or input) and a **Send** button.
  - Prompt templates dropdown.
  - Buttons to open help or feedback modals.
  - Button for refresh the llm context
  - Button for upload files to the llm

- Uses Jinja2 to inject:
  - Company name, branding colors, and logo.
  - User information (`user_session_context` / `ProfileService` output).
  - Per-company configuration (e.g., available prompts).

Rendering flow:

1. A Flask view resolves the current company and user session.
2. It loads the relevant context (branding, prompts, locale).
3. It calls `render_template("chat.html", ...)` with all necessary variables.
4. `chat.html` uses these variables to build the initial page.

---

### 5.2 JavaScript: Sending Messages and Updating the Chat

The JavaScript included in `chat_main.js`  is responsible for:

1. **Capturing user input** from the text area and handling the Send button (or Enter key).
2. **Sending an AJAX request** (`fetch` with `POST`) to the backend endpoint:
   - Example: `/<company_short_name>/api/llm_query`
   - Payload: JSON with the message text, optional prompt ID, attached files.
3. **Handling the response**:
   - Parsing the JSON payload.
   - Appending the assistant’s response to the chat history area.

This keeps the chat experience responsive without a full page reload.

Common JS responsibilities:

- Disable the Send button while a request is in progress.
- Show a “loading…” indicator while waiting for the LLM response.
- Handle errors (e.g., network issues, server errors) and show a friendly message in the chat.

---

### 5.3 Modals: Help, Onboarding, History, and Feedback

The UI include several **modals** (pop-up overlays) that provide additional functionality:

- **Onboarding / Help modals**:
  - Content driven by `onboarding_cards.yaml` and `help_content.yaml`.
  - Explain what the assistant can do, provide example questions, and describe key concepts.
- **History modal**:
  - Display the list of queries send by the user to the llm
- **Feedback modal**:
  - Allows users to rate responses and  leave comments.
  - Feedback is sent back to the backend (UserFeedbackService)

Implementation details:

- Modals are defined as hidden `<div>` sections in `chat.html` (or shared templates).
- CSS and JS are used to:
  - Show/hide modals (adding/removing `visible` / `open` classes).
  - Populate modal content dynamically when needed.

---

### 5.4 CSS and Branding

Styling is handled through a combination of global CSS and per-company branding:

- **Global CSS** (in `static/`):
  - Base layout (header, sidebar, chat area).
  - Common components (buttons, text inputs, modals).
  - Responsive behavior for different screen sizes.

- **Branding** from `company.yaml`:
  - Colors such as:
    - `brand_primary_color`
    - `brand_secondary_color`
    - `header_background_color`
    - `header_text_color`
  - These values are injected into templates via Jinja2 and used to:
    - Set CSS variables (e.g., `--brand-primary: #4C6A8D;`).
    - Inline styles for critical components if needed.


This allows each Company to have a **fully branded experience** (colors, logos, sometimes additional CSS) without duplicating templates.

## 6. CLI Commands

IAToolkit extends Flask's command-line interface (CLI) to provide a powerful way to perform administrative, 
setup, and maintenance tasks directly from your terminal. 
You can define custom commands for each company, allowing you to build administrative scripts that 
are tightly integrated with your company's specific logic and configuration.

To add custom CLI commands to a company, you need to implement the `register_cli_commands` 
method in your company's main class. This method is defined in `BaseCompany` and is called by the IAToolkit framework during 
the application startup process.

The `sample_company` provides an excellent example of a custom CLI command: `flask load`. 
This command is responsible for populating the vector database with documents 
for Retrieval-Augmented Generation (RAG). 
It reads the `knowledge_base` configuration from `company.yaml` to find and process the 
specified document sources.

#### 6.1 The `company.yaml` Configuration

First, let's look at the `knowledge_base` section in `companies/sample_company/config/company.yaml`. This section declaratively defines the logical groups of documents to be indexed.

```yaml
# ... other configurations ...

# Knowledge Base (RAG)
# Defines the sources of unstructured documents for indexing.
knowledge_base:
  parsing_provider: auto
  collections:
    - name: supplier_manual
      parser_provider: docling
    - name: employee_contract
      parser_provider: basic

  # Document Sources define the logical groups of documents to be indexed.
  # Each key (e.g., "supplier_manuals") is a unique source identifier.
  document_sources:
    supplier_manuals:
      path: "companies/sample_company/sample_data/supplier_manuals"
      metadata:
        type: "supplier_manual"

    employee_contracts:
      path: "companies/sample_company/sample_data/employee_contracts"
      metadata:
        type: "employee_contract"
```
Here, we have defined two document sources: `supplier_manuals` and `employee_contracts`, 
each pointing to a specific path where the files are located.

#### 6.2 The Python Implementation

Next, let's see how `sample_company.py` implements the `load` command. 
It overrides `register_cli_commands` and uses the injected `load_document_service` to perform the work.

**In `companies/sample_company/sample_company.py`:**
```python

def register_cli_commands(self, app):
    @app.cli.command("load")
    def load_documents():
        """📦 Ingests documents into the vector store based on company.yaml."""
        try:
            click.echo("⚙️  Loading documents into the vector store...")
            
            # This is the core logic:
            # It tells the service to load only the specified sources
            # from the knowledge_base configuration.
            self.load_document_service.load_sources(
                        company=self.company,
                        sources_to_load=["employee_contracts", "supplier_manuals"]
                    )
            
            click.echo("✅ Documents loaded successfully.")
        except Exception as e:
            logging.exception(e)
            click.echo(f"❌ Error during document loading: {str(e)}")

    # You can also register other commands here, like populate-sample-db
    @app.cli.command("populate-sample-db")
    def populate_sample_db():
        # ... implementation for populating the SQL database ...
        pass
```

**How It Works:**
1.  The `@app.cli.command("load")` decorator registers a new command, making it available as `flask load`.
2.  The `load_documents` function is executed when the command is run.
3.  It calls `self.load_document_service.load_sources()`, passing the `company` object and a list of `sources_to_load`.
4.  The service then looks into the `company.yaml` `knowledge_base.document_sources` section and processes only the sources whose keys match the 
5. ones in the `sources_to_load` list (`"employee_contracts"` and `"supplier_manuals"`). For each source, it reads the files from the specified `path`, applies the metadata, and ingests them into the vector database.

#### 6.3 Running the Command

With this setup, you can populate your vector store for the `sample_company` by running a single command from your terminal:

```bash
# Ensure your virtual environment is activated
(venv) iatoolkit % flask load
```

The output will show the progress as the service finds, processes, and indexes the documents from the configured paths. This powerful pattern allows you to create repeatable, version-controlled scripts for essential administrative tasks like data ingestion, database migrations, or system health checks.

---
## 7. Testing Strategy

IAToolkit maintains **90%+ test coverage** to ensure reliability and facilitate safe refactoring. 
Tests are organized to mirror the source code structure.

### 7.1 Test Categories

**Unit Tests**: Test individual components in isolation with mocked dependencies
- Located in `tests/services/`, `tests/repositories/`, etc.
- Use `pytest` fixtures for setup
- Mock external dependencies using `unittest.mock`

**Integration Tests**: Test interactions between multiple components
- Database interactions with test fixtures
- Service coordination tests

**Example Test Structure:**

## 8. Best Practices

### 8.1 Error Handling

Always use IAToolkitException for application errors:
```python
from iatoolkit.common.exceptions import IAToolkitException

raise IAToolkitException(
    IAToolkitException.ErrorType.VALIDATION_ERROR,
    "Clear error message for debugging"
)
```
### 8.2 Logging
Use Python's standard logging:
```python

import logging

logging.info("Informational message")
logging.error(f"Error occurred: {error_details}")
logging.debug("Detailed debug information")
```

### 8.3 Configuration Management

Never hardcode configuration values. Always use:
Environment variables for secrets
company.yaml for company-specific settings
ConfigurationService for accessing configuration

## 9. Contributing Guidelines
When contributing to IAToolkit:
1. Follow the existing structure: Place code in the appropriate layer
2. Write tests: Maintain the high test coverage standard
3. Document your code: Use docstrings for classes and methods
4. Use type hints: Help other developers understand interfaces
5. Keep commits atomic: One logical change per commit
6. Update documentation: If you add features, document them

## Conclusion
IAToolkit's architecture is designed for clarity, testability, and extensibility. By following the patterns and practices outlined in this guide, you'll be able to navigate the codebase confidently, add new features safely, and contribute to the framework's continued evolution.
For specific questions or advanced topics, refer to the inline code documentation or reach out to the community.
Happy coding! 🚀






