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
- Email services
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

### 2.2 Repository Pattern

The repository pattern abstracts data access logic, providing a clean interface between the business logic and data persistence layers.
Each repository is responsible for a specific domain entity.

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

### 3.3 Dispatcher (`dispatcher_service.py`)

**Purpose**: Routes and executes tool/function calls requested by the LLM.

**Key Responsibilities:**
- Loads and validates company configurations
- Registers available tools for each company
- Executes tool calls with proper error handling
- Manages tool execution context

The Dispatcher is the bridge between the LLM's function calling capability and your actual business logic implementations.

#todo: mostrar como el dsipatcher ejecuta una tool definida en Company Class.
---

### 3.4 ConfigurationService (`configuration_service.py`)

**Purpose**: Centralized configuration management for companies.

**Key Responsibilities:**
- Loads and parses `company.yaml` files
- Provides typed access to configuration values
- Validates configuration schemas
- Caches configurations for performance

---
### 3.5 Company Context Service (`company_context_service.py`) and user_session_context

**Purpose**: Centralizes all *per-company* and *per-session* context that is needed across views, services, and prompts.

While `ConfigurationService` focuses on static configuration (mainly from `company.yaml`),  
the **Company Context Service** is responsible for providing a *runtime view* of:

- Which company is currently active.
- Which user (if any) is associated with the session.
- Which language, branding, and feature flags apply to the current request.

This context is exposed through a small, session-scoped structure usually referred to as `user_session_context`.

**Key Responsibilities:**

- Resolve the **current company** based on:
  - URL prefix (e.g., `/sample_company/...`)
  - Session variables (e.g., `company_short_name`)
  - Authentication information
- Load and cache:
  - Company configuration (`company.yaml`) via `ConfigurationService`
  - Branding information (`BrandingService`)
  - Language/locale (`LanguageService` / `I18nService`)
- Build a unified context object (`user_session_context`) that can be:
  - Injected into services and views.
  - Passed to prompts and tools to ensure they operate in the correct tenant context.

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
### 3.10 EmbeddingService (`embedding_service.py`)

**Purpose**: Provides text embedding capabilities for semantic search.

**Key Responsibilities:**
- Generates vector embeddings from text
- Supports multiple embedding providers (OpenAI, HuggingFace)
- Manages provider-specific client configurations per company
- Caches embedding clients for performance

**Architecture Highlight:**
Uses the Factory pattern (`EmbeddingClientFactory`) to create provider-specific wrappers, ensuring a consistent interface regardless of the underlying embedding service.

---
### 3.11 ProfileService (`profile_service.py`)

**Purpose**: Manages user profile data and exposes a unified view of the “current user” within a given session and company.

**Key Responsibilities:**
- Retrieves the current user’s profile based on the active session.
- Resolves the current company for the user (especially when a user can access multiple companies).
- Provides helper methods such as:
  - `get_current_session_info()` – returns a dict with user and company info used by templates and services.
  - Accessors for common profile fields (email, display name, roles, flags like `user_is_local`, etc.).
- Integrates with `SessionManager` and `AuthService` to keep the profile in sync with the authentication state.

**Typical Usage:**
- In templates, via context processors, to show user-related information in the header.
- In services, to adapt behavior based on user role or company-specific permissions.

---

### 3.12 HistoryService and UserFeedbackService

> Exact filenames may vary slightly depending on your version (e.g., `history_service.py`, `user_feedback_service.py`), but conceptually they cover two closely related areas: **interaction history** and **feedback loops**.

#### HistoryService

**Purpose**: Stores and retrieves the history of user interactions with the assistant (queries, responses, tool calls).

**Key Responsibilities:**
- Persist conversation turns (question, answer, timestamp, company, user).
- Provide APIs to:
  - Load recent history for a given user/company/session.
  - Filter history by date, tool usage, or tags.
- Support features like:
  - Conversation continuation across sessions.
  - Auditing and compliance (who asked what, when, and what was answered).

This history is often used by `QueryService` to build richer prompts, including previous messages from the same conversation.

#### UserFeedbackService

**Purpose**: Collects and stores user feedback about responses (e.g., thumbs up/down, comments).

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

### 3.13 TaskService (`tasks_service.py`) *(in construction)*

**Purpose**: Orchestrates background and long-running tasks such as document ingestion, batch analyses, or scheduled jobs.

**Key Responsibilities (current and planned):**
- Define a common interface for tasks:
  - Creation (enqueueing a new task).
  - Status tracking (pending, running, completed, failed).
  - Result storage (logs, outputs, errors).
- Integrate with:
  - Document loading pipelines (e.g., bulk ingestion into the vector store).
  - Company-specific batch processes (e.g., periodic reports, data refresh).
- Provide APIs for:
  - Listing tasks for a given company and/or user.
  - Inspecting task logs and outputs.
  - Retrying failed tasks (planned).

**Status:**
- The service is under active development.
- Expect the interface and capabilities to evolve as more use cases (scheduled jobs, multi-step workflows) are standardized.

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

### 4.2 Flow of a query

This section describes the end-to-end flow of a user query, from the moment it is sent from the browser until it reaches the LLM provider (e.g., OpenAI) and comes back as a response.

At a high level, the flow crosses the following layers:

1. **View (Flask route)** – Receives the HTTP request from the UI.
2. **QueryService** – Orchestrates the query: builds prompts, calls tools, and talks to the LLM.
3. **Dispatcher** – Executes tools (functions) defined by each Company.
4. **LLM Client / Proxy** – Routes the request to the correct provider (OpenAI, Gemini, etc.).
5. **Provider Adapter** – Adapts IAToolkit’s internal format to the provider SDK (e.g., `openai`).
6. **LLM Provider** – Executes the model and returns a completion.
7. **Back to QueryService** – Combines results, logs, and returns the final answer to the view.

#### High-level sequence diagram

```text
[Browser] 
   |
   | 1. POST /<company>/api/llm_query (message)
   v
[Flask View (views/)]
   |
   | 2. Build request + resolve company/user
   |    DI -> QueryService
   v
[QueryService]
   |
   | 3. Load company config, context, history
   | 4. Build system/user messages
   |
   |--(optional)--> [Dispatcher] --(call tool)--> [Company Tool / Repo]
   |                                ^                  |
   |                                |-- tool result ---|
   |
   | 5. Call LLMProxy/llmClient(model, messages, tools)
   v
[LLMProxy]
   |
   | 6. Route to provider adapter (OpenAIAdapter / GeminiAdapter)
   v
[OpenAIAdapter]
   |
   | 7. openai.Client(...) -> chat/completions.create(...)
   v
[OpenAI API]
   |
   | 8. Completion
   v
[OpenAIAdapter] -> [LLMProxy] -> [QueryService]
   |
   | 9. Log query, store history/feedback context
   | 10. Return final answer text
   v
[Flask View] -> JSON response -> [Browser UI]
```


#### Step-by-step

1. **UI → View (Flask)**  
   - The user types a message in the chat UI and clicks “Send”.  
   - The browser sends a `POST` request to an endpoint like:  
     `/<company_short_name>/api/llm_query`.  
   - The Flask view (defined in `views/` and registered via `routes.py`) validates:
     - Session or API key (security).
     - Required fields (e.g., `message`, optional metadata).

2. **View → QueryService**  
   - Using dependency injection, the view obtains an instance of `QueryService`.  
   - It builds a `QueryRequest` object (or equivalent dict) with:
     - `company_short_name`
     - User message
     - Conversation history / `user_session_context`
     - Optional tool hints or prompt identifiers  
   - It calls `query_service.llm_query(...)`.

3. **QueryService: building the LLM request**  
   Inside `llm_query()`:

   - Loads **company configuration** from `ConfigurationService` and `CompanyContextService`:
     - LLM model
     - Available tools
     - Language/branding settings
   - Loads **context** (system prompts) from:
     - `context/` files for the active company.
   - Optionally retrieves **recent history** from `HistoryService` to build a conversation-aware prompt.
   - Constructs the final **system + user + (optional tool) messages** to send to the LLM.

4. **QueryService ↔ Dispatcher (tool calls)**  
   - If the LLM response requests a tool call (e.g., `document_search`, `sql_query`):
     - `QueryService` delegates execution to `Dispatcher`.
     - The Dispatcher:
       - Finds the corresponding tool implementation registered by the Company class.
       - Executes it (e.g., calls `VSRepo` for document search, or a custom Company function).
       - Returns the tool result back to `QueryService`.
   - `QueryService` then:
     - Feeds the tool result back into the LLM as a follow-up message.
     - Continues the conversation until a final answer is produced.

5. **QueryService → LLM Client / Proxy**  
   - When ready to call the LLM, `QueryService` uses a client such as `llmClient` or `LLMProxy` (from `infra/`):
     - It passes:
       - `model` (e.g., `gpt-4`, `gpt-4o-mini`)
       - The list of messages
       - Optional tool/function definitions.
   - `LLMProxy` decides which provider to use:
     - If `util.is_openai_model(model)` → use **OpenAIAdapter**.
     - If `util.is_gemini_model(model)` → use **GeminiAdapter**, etc.

6. **LLMProxy → OpenAIAdapter → OpenAI SDK**  
   - `OpenAIAdapter` transforms the internal `create_response` call into an SDK call, for example:
     - `client.chat.completions.create(...)` or  
     - `client.responses.create(...)` (depending on SDK version).
   - The adapter ensures:
     - Proper mapping of messages and tools.
     - Correct timeout and error handling.
   - The OpenAI Python client sends the request to the OpenAI API and returns the raw response.

7. **Backpropagating the response**  
   - `OpenAIAdapter` converts the raw SDK response into an internal `LLMResponse` object.
   - `LLMProxy` returns it to `QueryService`.
   - `QueryService`:
     - Logs the interaction in `LLMQuery` (tokens, model, cost, etc.).
     - Optionally stores history and feedback context.
     - Extracts the final answer text and any structured payload.
   - The **view** receives the `LLMResponse`, converts it to JSON, and sends it back to the browser.
   - The UI renders the assistant’s answer in the chat.

---

## 5. Front end

The IAToolkit front end is a lightweight, server‑rendered UI built on top of **Flask**, **Jinja2 templates**, and a small amount of **JavaScript**. The goal is to provide a clean chat experience that can be easily branded and extended per Company, without requiring a complex SPA framework.

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
  - Optional controls such as:
    - Model selector (if enabled).
    - Prompt templates dropdown.
    - Buttons to open help or feedback modals.

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

The JavaScript included in `chat.html` (or a linked `.js` file) is responsible for:

1. **Capturing user input** from the text area and handling the Send button (or Enter key).
2. **Sending an AJAX request** (typically `fetch` with `POST`) to the backend endpoint:
   - Example: `/<company_short_name>/api/llm_query`
   - Payload: JSON with the message text, optional prompt ID, and additional metadata.
3. **Handling the response**:
   - Parsing the JSON payload.
   - Appending the assistant’s response to the chat history area.
   - Optionally updating tokens, cost, or debug information (if exposed).


This keeps the chat experience responsive without a full page reload.

Common JS responsibilities:

- Disable the Send button while a request is in progress.
- Show a “typing…” indicator while waiting for the LLM response.
- Handle errors (e.g., network issues, server errors) and show a friendly message in the chat.

---

### 5.3 Modals: Help, Onboarding, and Feedback

The UI may include several **modals** (pop-up overlays) that provide additional functionality:

- **Onboarding / Help modals**:
  - Content driven by `onboarding_cards.yaml` and `help_content.yaml`.
  - Explain what the assistant can do, provide example questions, and describe key concepts.
- **Feedback modal**:
  - Allows users to rate responses (e.g., thumbs up/down) and optionally leave comments.
  - Feedback is sent back to the backend (UserFeedbackService) along with context:
    - Which query/response is being rated.
    - User and company identifiers.

Implementation details:

- Modals are defined as hidden `<div>` sections in `chat.html` (or shared templates).
- CSS and JS are used to:
  - Show/hide modals (adding/removing `visible` / `open` classes).
  - Populate modal content dynamically when needed.
- All modal content can be filtered through the i18n layer, so text is localized based on the current `locale`.

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

---

### 5.5 Putting It All Together

From a developer perspective, the front end behaves as follows:

1. **Initial page load**:
   - Flask renders `chat.html` with company/user context and branding.
   - CSS and JS are loaded from `static/`.

2. **User interaction**:
   - JS listens for message submissions.
   - Requests are sent to the backend APIs.
   - Responses are rendered into the chat history.

3. **Optional modals**:
   - Help/onboarding modals are populated from YAML-driven content.
   - Feedback modals send structured feedback to the backend.

4. **Branding and localization**:
   - Colors and logos come from `company.yaml`.
   - Text can be localized through the i18n services.

The overall design keeps the front end **simple, extensible, and company-aware**, making it easy to:

- Customize the look and feel per tenant.
- Integrate new modals or controls.
- Evolve the UI without changing the core backend architecture.

---
## 6. Testing Strategy

IAToolkit maintains **90%+ test coverage** to ensure reliability and facilitate safe refactoring. 
Tests are organized to mirror the source code structure.

### 6.1 Test Categories

**Unit Tests**: Test individual components in isolation with mocked dependencies
- Located in `tests/services/`, `tests/repositories/`, etc.
- Use `pytest` fixtures for setup
- Mock external dependencies using `unittest.mock`

**Integration Tests**: Test interactions between multiple components
- Database interactions with test fixtures
- Service coordination tests

**Example Test Structure:**

## 7. Best Practices

### 7.1 Error Handling

Always use IAToolkitException for application errors:
```python
from iatoolkit.common.exceptions import IAToolkitException

raise IAToolkitException(
    IAToolkitException.ErrorType.VALIDATION_ERROR,
    "Clear error message for debugging"
)
```
### 7.2 Logging
Use Python's standard logging:
```python

import logging

logging.info("Informational message")
logging.error(f"Error occurred: {error_details}")
logging.debug("Detailed debug information")
```

### 7.3 Configuration Management

Never hardcode configuration values. Always use:
Environment variables for secrets
company.yaml for company-specific settings
ConfigurationService for accessing configuration

## 8. Contributing Guidelines
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








