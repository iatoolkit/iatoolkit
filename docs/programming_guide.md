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
│       ├── config/                   # Company configuration files
│       └── sample_company.py         # Company module entry point
│
├── docs/                             # Documentation files
├── requirements.txt                  # Python dependencies
├── .env.example                      # Environment variables template
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
- Session management and user context handling

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
- Email services
- Cloud storage connectors (S3, GCS)
- Google Chat integration

**Common Layer (`common/`)**
Contains cross-cutting concerns and utilities used throughout the application:
- `exceptions.py`: Custom exception classes for error handling
- `util.py`: Helper functions (encryption, validation, etc.)
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

**Example:**


All dependencies are configured in `iatoolkit.py` within the `_configure_core_dependencies()` method, 
which acts as the composition root for the entire application.

### 2.2 Repository Pattern

The repository pattern abstracts data access logic, providing a clean interface between the business logic and data persistence layers. Each repository is responsible for a specific domain entity.

**Benefits:**
- Centralized data access logic
- Easier to test business logic in isolation
- Database-agnostic business layer
- Simplified query management

### 2.3 Adapter Pattern (Infrastructure Layer)

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
- Coordinates with the Dispatcher to route tool calls
- Interfaces with LLM providers through the LLMClient
- Handles streaming responses
- Logs all interactions for auditing and cost tracking

**Notable Methods:**
- `llm_query()`: Main entry point for processing user queries
- `_build_system_prompt()`: Constructs context-aware system prompts

---

### 3.2 DocumentService (`document_service.py`)

**Purpose**: Manages the lifecycle of documents within the system.

**Key Responsibilities:**
- Document upload and validation
- File format handling (PDF, DOCX, TXT, etc.)
- Document chunking for vector storage
- Metadata management
- Integration with vector store for RAG capabilities

---

### 3.3 EmbeddingService (`embedding_service.py`)

**Purpose**: Provides text embedding capabilities for semantic search.

**Key Responsibilities:**
- Generates vector embeddings from text
- Supports multiple embedding providers (OpenAI, HuggingFace)
- Manages provider-specific client configurations per company
- Caches embedding clients for performance

**Architecture Highlight:**
Uses the Factory pattern (`EmbeddingClientFactory`) to create provider-specific wrappers, ensuring a consistent interface regardless of the underlying embedding service.

---

### 3.4 Dispatcher (`dispatcher_service.py`)

**Purpose**: Routes and executes tool/function calls requested by the LLM.

**Key Responsibilities:**
- Loads and validates company configurations
- Registers available tools for each company
- Executes tool calls with proper error handling
- Manages tool execution context

The Dispatcher is the bridge between the LLM's function calling capability and your actual business logic implementations.

---

### 3.5 ConfigurationService (`configuration_service.py`)

**Purpose**: Centralized configuration management for companies.

**Key Responsibilities:**
- Loads and parses `company.yaml` files
- Provides typed access to configuration values
- Validates configuration schemas
- Caches configurations for performance

---

### 3.6 AuthService (`auth_service.py`)

**Purpose**: Handles user authentication and authorization.

**Key Responsibilities:**
- User login/logout
- Session management
- Password hashing (bcrypt)
- API key validation for programmatic access
- Integration with external auth providers (when configured)

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

## 4. The IAToolkit Object and Application Lifecycle

The `IAToolkit` class (`iatoolkit.py`) is the core application factory and implements the Singleton pattern to ensure only one instance exists throughout the application lifecycle.

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

### 4.2 Key Methods

**`create_iatoolkit()`**
The main factory method that orchestrates the entire setup process. This is where the application is bootstrapped.

**`get_injector()`**
Returns the configured Injector instance, allowing you to manually resolve dependencies when needed (typically in CLI commands or custom extensions).

**`get_dispatcher()`**
Provides access to the Dispatcher service, useful for testing or manual tool execution.

**`get_database_manager()`**
Returns the DatabaseManager instance for direct database operations.

---

## 5. Testing Strategy

IAToolkit maintains **90%+ test coverage** to ensure reliability and facilitate safe refactoring. Tests are organized to mirror the source code structure.

### 5.1 Test Categories

**Unit Tests**: Test individual components in isolation with mocked dependencies
- Located in `tests/services/`, `tests/repositories/`, etc.
- Use `pytest` fixtures for setup
- Mock external dependencies using `unittest.mock`

**Integration Tests**: Test interactions between multiple components
- Database interactions with test fixtures
- Service coordination tests

**Example Test Structure:**

## 6. Best Practices

### 6.1 Error Handling

Always use IAToolkitException for application errors:
```python
from iatoolkit.common.exceptions import IAToolkitException

raise IAToolkitException(
    IAToolkitException.ErrorType.VALIDATION_ERROR,
    "Clear error message for debugging"
)
```
### 6.2 Logging
Use Python's standard logging:
```python

import logging

logging.info("Informational message")
logging.error(f"Error occurred: {error_details}")
logging.debug("Detailed debug information")
```

### 6.3 Configuration Management

Never hardcode configuration values. Always use:
Environment variables for secrets
company.yaml for company-specific settings
ConfigurationService for accessing configuration

## 7. Contributing Guidelines
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








