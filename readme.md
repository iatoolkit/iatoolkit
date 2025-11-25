<div align="center">
  <h1>IAToolkit</h1>
  <p><strong>The Open-Source Framework for Building AI Assistants on Your Private Data</strong></p>
  <p>
    <a href="https://www.iatoolkit.com">Website</a> |
    <a href="./docs/index.md">Full Documentation</a> |
    <a href="./docs/quickstart.md">Quickstart Guide</a>
  </p>
</div>

![IAToolkit Demo](./docs/assets/iatoolkit-demo.gif)

---

## ✨ Why IAToolkit?

IAToolkit is more than a framework — it's a complete foundation for building **enterprise-grade AI assistants** 
capable of understanding your proprietary data, automating workflows, and integrating seamlessly with 
your existing systems.

Whether you’re building a production chatbot for your company or learning how real AI applications are architected, 
IAToolkit gives you everything you need to build secure, production-grade assistants — from data access, 
multi-tenant architecture, and tool execution to prompt orchestration, semantic search, 
and full UI integration — all powered by a clean, extensible Python API.

---

### 🔌 Connect to Anything  
Build AI assistants that truly understand your business.

- Connect to **SQL databases** (PostgreSQL, MySQL, SQLite)
- Query structured data using natural language
- Perform **semantic search** on PDFs, DOCX, TXT, XLSX
- Works as a full RAG engine out-of-the-box

---

### 🏢 Multi-Tenant by Design  
Ideal for SaaS, agencies, consultancies, or large enterprises.

- Isolated **Company Modules**  
- Each company defines its own: data sources, prompts, tools, and branding
- Clean separation for multi-client deployments  
- Add **custom tools** the LLM can call (SQL, API, Python functions)
- Perfect for scaling from 1 to 100 customers
- Configure everything using simple YAML 

---


### 🛡️ Built for Production  
Designed for real-world systems — reliable, maintainable, and scalable.

- Swap between **OpenAI (GPT)**, **Google Gemini**, or future models
- Integrated authentication and session handling  
- Detailed logging of prompts, tool calls, and token usage  
- Clean separation of UI, business logic, and LLM orchestration  
- Runs anywhere: local machine, docker, cloud, serverless  

---


## 🚀 Getting Started in 3 Minutes

Get your first AI assistant running locally by following our "Hello World" example.
Our detailed guide will walk you through setting up your virtual environment, configuring your `.env` file, 
and launching the application.

➡️ **[Start the Quickstart Guide](./docs/quickstart.md)**

## 📚 Documentation

Our documentation is designed for users of all levels, from initial setup to advanced development.

| Guide                                                                                       | Description                                                                                               |
|---------------------------------------------------------------------------------------------| --------------------------------------------------------------------------------------------------------- |
| 🚀 **[Quickstart Guide](./docs/quickstart.md)**                                             | The fastest way to install, configure, and run IAToolkit for the first time.                                |
| ⚙️ **[Companies & Components](./docs/companies_and_components.md)**                         | A deep dive into the `company.yaml` file, the core of all configuration.                  |
| 💻 **[Programming Guide](./docs/programming_guide.md)**                                     | Understand the internal architecture, services, and design patterns to extend the framework.      |
| ☁️ **[Deployment Guide](./docs/deployment_guide.md)**                                       | Learn how to deploy your IAToolkit application to a production environment.                             |
| 🗃️ **[Database Guide](./docs/database_guide.md)**                                          | An overview of the core database schema used by the IAToolkit framework itself.                         |
| 🏛️ **[Foundation Article](https://www.iatoolkit.com/pages/foundation)**           | An article explaining the "Why" behind IAToolkit's architecture for enterprise-grade assistants. |
| 🗓️ **[Implementation Plan](https://www.iatoolkit.com/pages/implementation_plan)** | A 3-month mini-project plan to deploy a real AI assistant integrated with corporate data. |
➡️ **[Explore all documentation](./docs/index.md)**

## 🤝 Contributing

We welcome contributions of all kinds! Whether it's a new feature, a bug fix, or an improvement to the documentation, your help is appreciated. Please read our **[Contributing Guide](./contributing.md)** to get started.

## 📄 License

IAToolkit is open-source software licensed under the **[MIT License](./LICENSE)**.