<div align="center">
  <h1>IAToolkit</h1>
  <p><strong>The Open-Source Framework for Building Real-World AI Assistants on Your Private Data</strong></p>
  <p>
    <a href="https://www.iatoolkit.com">Website</a> |
    <a href="./docs/index.md">Full Documentation</a> |
    <a href="./docs/quickstart.md">Quickstart Guide</a>
  </p>
</div>

---

## ✨ Why IAToolkit?

IAToolkit is an **open-source framework** for building real-world, enterprise-grade AI assistants that run
**inside your environment**, access **your databases and documents**, and execute **your workflows**.

Whether you’re:

- building a production chatbot for your company, or  
- learning how serious AI applications are architected,

IAToolkit gives you a structured foundation designed for real business use.

---

## 🧱 Architecture in a Nutshell

At the heart of IAToolkit is a structured internal architecture:

- **Interfaces & Chat**  
  Handle HTTP/JSON/HTML, sessions, and the conversational flow between users, the server, and the LLM.

- **Intelligence Layer**  
  The core of the system. Interprets user intent, reads each Company’s configuration, and orchestrates
  SQL queries, document retrieval, prompts, tools, and RAG. This is where real-world behavior lives.

- **Connectors & Tools Layer**  
  Bridges the intelligence with your systems. Provides access to SQL databases, internal documents,
  APIs, and custom Python tools so the assistant can execute workflows, not just answer questions.

- **Data Access Layer**  
  Uses SQLAlchemy to offer structured and predictable access to the internal database, making it safe to
  grow from one Company to many.

- **Company Modules**  
  Each Company has its own `company.yaml`, context, prompts, tools, and branding, forming a clean
  boundary within a shared IAToolkit Core.

For a deeper explanation of these concepts, see:

- 🏛️ **[Foundation Article](https://www.iatoolkit.com/pages/foundation)**  
- 🗓️ **[Implementation Plan](https://www.iatoolkit.com/pages/implementation_plan)**

These two documents explain the “why” behind the architecture and how to build a full assistant in 3 months.

---

## 🔌 Connect to Anything

Build AI assistants that truly understand your business.

- Connect to **SQL databases** (PostgreSQL, MySQL, SQLite)
- Query structured data using natural language
- Perform **semantic search** on PDFs, DOCX, TXT, XLSX
- Use IAToolkit as a full **RAG engine** out-of-the-box
- Combine database queries, document retrieval, and tools in a single answer

Your assistant isn’t limited to the chat history — it can see real numbers, real entities, and real documents.

---

## 🏢 Multi-Tenant by Design

IAToolkit is built for scenarios where you serve more than one “domain”:

- SaaS products serving multiple customers  
- Agencies or consultancies building assistants for several clients  
- Large enterprises with multiple business units

Each **Company** is a logical tenant, defined by:

- a `company.yaml` configuration file (data sources, LLM choices, tools, roles, branding)  
- contextual resources (schemas, prompts, documents, examples)  
- optional Python tools that the LLM can call (SQL helpers, API calls, custom business actions)

This gives you:

- Clear isolation between tenants  
- Clean separation for multi-client deployments  
- A straightforward path to scale from 1 to 100+ customers, without rewriting your core

---

## 🧠 Built for Real-World Systems

IAToolkit is designed with production in mind — reliable, maintainable, and adaptable:

- Swap between **OpenAI (GPT)**, **Google Gemini**, or future LLM providers
- Keep a clean separation between UI, business logic, and LLM orchestration
- Use an **Intelligence Layer** to organize prompts, tools, and RAG in a consistent way
- Integrated authentication and session handling
- Detailed logging of prompts, tool calls, and token usage
- Runs anywhere: local machine, Docker, cloud, serverless

You can start small on a laptop and grow into a full-scale internal assistant without changing frameworks.

---

## 🚀 Getting Started in 3 Minutes

Get your first AI assistant running locally by following our “Hello World” example.

Our **Quickstart Guide** walks you through:

- creating and activating a virtual environment  
- configuring your `.env` file with API keys and basic settings  
- launching the application and talking to your first Company

➡️ **[Start the Quickstart Guide](./docs/quickstart.md)**

---

## 📚 Documentation

The documentation is designed to grow with you — from basic setup to extending the framework with
your own Companies, tools, and workflows.

| Guide                                                                                       | Description                                                                                               |
|---------------------------------------------------------------------------------------------| --------------------------------------------------------------------------------------------------------- |
| 🚀 **[Quickstart Guide](./docs/quickstart.md)**                                             | The fastest way to install, configure, and run IAToolkit for the first time.                             |
| ⚙️ **[Companies & Components](./docs/companies_and_components.md)**                         | A deep dive into the `company.yaml` file, the core of all configuration.                                 |
| 💻 **[Programming Guide](./docs/programming_guide.md)**                                     | Understand the internal architecture, services, and design patterns to extend the framework.             |
| ☁️ **[Deployment Guide](./docs/deployment_guide.md)**                                       | Learn how to deploy your IAToolkit application to a production environment.                              |
| 🗃️ **[Database Guide](./docs/database_guide.md)**                                          | An overview of the core database schema used by the IAToolkit framework itself.                          |
| 🏛️ **[Foundation Article](https://www.iatoolkit.com/pages/foundation)**                    | The “why” behind IAToolkit’s architecture for enterprise-grade assistants.                               |
| 🗓️ **[Implementation Plan](https://www.iatoolkit.com/pages/implementation_plan)**          | A 3-month mini-project plan to deploy a real AI assistant integrated with corporate data.                |

➡️ **[Explore all documentation](./docs/index.md)**

---
## 🆓 Community Edition vs Enterprise Edition

IAToolkit follows a modern **open-core model** similar to GitLab, PostHog, and Airbyte.  
The Core of the framework is fully open-source under the MIT license — transparent, modifiable, extensible.

### 🟦 Community Edition (MIT License)

The Community Edition is ideal for learning, prototypes, and single-business deployments.  
It includes:

- full access to the Intelligence Layer  
- SQL orchestration  
- RAG (basic)  
- the full Interfaces & Chat experience  
- customizable tools  
- **support for one (1) Company only**

This “single-Company mode” provides a clean separation between Community and Enterprise:  
the entire system works exactly the same, but is scoped to one business configuration.

Unlimited customization remains possible by forking the MIT-licensed repository, as allowed by open source.

---

### 🟥 Enterprise Edition (Commercial License)

Enterprise Edition unlocks **multi-Company** and **multi-tenant** capabilities, 
plus additional features designed for real corporate environments:

- **Unlimited Companies** with isolated configurations  
- **Advanced RAG pipelines**  
- **External connectors** (S3, APIs, emails, file storage)  
- **Audit logs & activity tracing**  
- **Higher request and token ceilings**  
- **SSO integrations** (Google, Microsoft, Okta, etc.)  
- **Priority support and onboarding**

These features are exclusive and **not included** in the Community Edition.

---

## 🤝 Contributing

We welcome contributions of all kinds — new features, bug fixes, documentation improvements, or ideas
for better developer experience.

Please read our **[Contributing Guide](./contributing.md)** to get started.

---

## 📄 Licensing

IAToolkit is open-core:

- **Community Edition (MIT)** — full open-source Core, limited to one Company  
- **Enterprise Edition** — multi-Company capabilities and advanced features  
- Licensing details:  
  - [MIT License (Community Edition)](LICENSE_COMMUNITY.md)  
  - [Enterprise License](ENTERPRISE_LICENSE.md)  