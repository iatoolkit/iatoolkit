
<div align="center">
<h1>
    IAToolkit
</h1>

  <p><strong>The Open-Source Framework for Building AI Chatbots on Your Private Data.</strong></p>
<h4>
  <a href="https://www.iatoolkit.com" target="_blank" style="text-decoration: none; color: inherit;">
    www.iatoolkit.com
  </a>
</h4>
</div>

IAToolkit is a comprehensive, Python open-source framework designed for building enterprise-grade 
AI chatbots and conversational applications. It bridges the gap between the power of 
Large Language Models (LLMs) and the valuable, 
private data locked within your organization's databases and documents.

With IAToolkit, you can build production-ready, context-aware chatbots and agents that 
can query relational databases, perform semantic searches on documents, 
and connect to your internal APIs in minutes.

Create secure, branded chat interfaces that can reason over your data, answer questions, and execute custom business logic, 
all powered by leading models from OpenAI, Google Gemini, and more.


## 🚀 Key Features

* **⚙️ Configuration-First Architecture**
    * **Zero-Code Data Integration**: Connect your databases with a simple YAML configuration—no coding required. Just declare your data sources, and IAToolkit handles the rest.
    * **Declarative Setup**: Define everything from database connections, embedding providers, custom tools, and UI branding in a single, intuitive `company.yaml` file.
    * **Smart Table Mapping**: Automatically discover and map all your database tables, or selectively include/exclude specific tables and columns with simple YAML directives.

* **🔗 Unified Data Connection**
    * **Natural Language to SQL**: Let your chatbot query relational databases (PostgreSQL, MySQL, SQLite) using everyday language.
    * **Semantic Document Search (RAG)**: Automatically chunk, embed, and search across your private documents (PDFs, Word, etc.) to provide contextually accurate answers.
    * **Flexible Embedding Options**: Choose between OpenAI or HuggingFace embedding models. Switch providers with a single configuration change—no code modifications needed.

* **🏢 Enterprise-Ready Multi-Tenancy**
    * Deploy isolated "Company" modules, each with its own data sources, tools, context, and branding.
    * Perfect for SaaS products serving multiple clients or for managing different internal departments.
    * Each company gets its own configuration file, ensuring complete isolation and customization.

* **🎨 Fully Brandable UI**
    * Customize the look and feel for each "Company" with its own colors, logos, and even language settings (i18n).
    * Define your brand identity in YAML—from header colors to button styles.
    * Provides a white-labeled experience for your users with zero front-end coding.

* **🧠 Multi-LLM by Design**
    * **Provider Agnostic**: Switch between **OpenAI (GPT-4, GPT-4o)** and **Google (Gemini Pro, Gemini Flash)** with a single configuration line.
    * **Future-Proof**: Easily add support for new LLM providers as they emerge.
    * **Per-Company Configuration**: Mix and match different LLM providers across companies based on cost, performance, or feature requirements.

* **🛠️ Powerful Tool System**
    * Define custom functions (tools) that your AI can invoke to perform actions—from database queries to API calls.
    * Declare tools in YAML with OpenAPI-style schemas.
    * Built-in support for common operations like document search, with easy extensibility for custom business logic.

* **🔒 Security & Observability Built-In**
    * Integrated user authentication, API key management, and secure session handling out of the box.
    * Full traceability with detailed logging of all queries, function calls, token usage, and costs.
    * Production-ready security features including CORS configuration and environment-based secrets management.

* **👨‍💻 Developer-First Experience**
    * Built with a clean **Dependency Injection** architecture for maximum testability and maintainability.
    * High-quality codebase with **90%+ test coverage**.
    * Comprehensive documentation and working examples to get you started quickly.

## 💡 Why IAToolkit?

**Build in Minutes, Not Months**: Traditional AI chatbot development requires months of infrastructure setup, security hardening, and complex integrations. IAToolkit provides all of this out-of-the-box, letting you focus on your business logic and user experience.

**Configuration Over Code**: Most AI frameworks force you to write extensive boilerplate code. With IAToolkit, you describe what you want in YAML, and the framework does the heavy lifting. Connect databases, configure embeddings, define tools—all declaratively.

**Multi-Tenant by Design**: Whether you're building a SaaS product for multiple clients or managing different departments within your organization, IAToolkit's Company architecture provides true isolation with shared infrastructure efficiency.

**Production-Ready from Day One**: No need to retrofit security, logging, or monitoring later. IAToolkit includes enterprise-grade features from the start, so you can deploy confidently.

## 📚 Documentation

For comprehensive guides, tutorials, and API references, visit our complete documentation:

➡️ **[Read the Full Documentation](./docs/index.md)**

## ⚡ Quick Start: Try our 'hello world' example

Ready to see it in action? Our Quickstart Guide will walk you through downloading, configuring, and launching your first AI assistant in just a few minutes. 
It's the best way to experience the toolkit's capabilities firsthand.

➡️ **[Get Started with the Quickstart Guide](./docs/quickstart.md)**

## 🤝 Contributing

We welcome contributions! Whether it's adding a new feature, improving documentation, or fixing a bug, 
please feel free to open a pull request.

➡️ **[Contributing guide](./contributing.md)**

## 📄 License

IAToolkit is open-source and licensed under the [MIT License](LICENSE).