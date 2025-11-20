<div align="center">
  <img src="https://www.iatoolkit.com/static/images/logo.png" alt="IAToolkit Logo" width="150"/>
  <h1>IAToolkit</h1>
  <p><strong>The Open-Source Framework for Building Enterprise-Grade AI Assistants on Your Private Data</strong></p>
  <p>
    <a href="https://www.iatoolkit.com">Website</a> |
    <a href="./docs/index.md">Full Documentation</a> |
    <a href="./docs/quickstart.md">Quickstart Guide</a>
  </p>
</div>

![IAToolkit Demo](./docs/assets/iatoolkit-demo.gif)

---

## ✨ Why IAToolkit?

IAToolkit is more than a framework — it's a complete foundation for building **enterprise-grade AI assistants** capable of understanding your proprietary data, automating workflows, and integrating seamlessly with your existing systems.

Whether you're building a production chatbot for your company **or learning how real AI applications are architected**, IAToolkit gives you the structure, tooling, and best practices you need.

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
- Each company defines its own:
  - data sources  
  - prompts  
  - custom tools  
  - branding + UI theme  
- Clean separation for multi-client deployments  
- Perfect for scaling from 1 to 100 customers
- Configure everything using simple YAML — **no boilerplate needed**

---

### 🧩 Extensible & Provider-Agnostic  
Customize every layer and keep full control.

- Add **custom tools** the LLM can call (SQL, API, Python functions)
- Swap between **OpenAI (GPT)**, **Google Gemini**, or future models
- Built on dependency injection for maximum modularity
- Extend prompts, dispatchers, services, and LLM clients effortlessly

---

### 🛡️ Built for Production  
Designed for real-world systems — reliable, maintainable, and scalable.

- Integrated authentication and session handling  
- Secure secret management via environment variables  
- Detailed logging of prompts, tool calls, and token usage  
- Structured architecture with **90%+ automated test coverage**  
- Clean separation of UI, business logic, and LLM orchestration  
- Runs anywhere: local machine, Docker, cloud, serverless  

---

### 🎓 Learn How Real AI Applications Are Built  
IAToolkit is also an excellent learning resource:

- Understand how to orchestrate multiple LLM calls  
- Learn how tools, SQL, vector search and prompts interact  
- Explore a complete architecture for real AI products  
- Use the Sample Company demo to practice building AI assistants  
- Perfect for developers, students, and teams exploring enterprise AI

---

IAToolkit helps you go from *idea* to *production-ready assistant* in minutes —  
without reinventing the wheel.

## 🚀 Getting Started in 3 Minutes

Get your first AI assistant running locally by following our "Hello World" example.
Our detailed guide will walk you through setting up your virtual environment, configuring your `.env` file, 
and launching the application.

➡️ **[Start the Quickstart Guide](./docs/quickstart.md)**

## 📚 Documentation

Our documentation is designed for users of all levels, from initial setup to advanced development.

| Guide                                         | Description                                                                                               |
| --------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 🚀 **[Quickstart Guide](./docs/quickstart.md)** | The fastest way to install, configure, and run IAToolkit for the first time.                                |
| ⚙️ **[Companies & Components](./docs/companies_and_components.md)** | A deep dive into the `company.yaml` file, the core of all configuration.                  |
| 💻 **[Programming Guide](./docs/programming_guide.md)** | Understand the internal architecture, services, and design patterns to extend the framework.      |
| ☁️ **[Deployment Guide](./docs/deployment_guide.md)** | Learn how to deploy your IAToolkit application to a production environment.                             |
| 🗃️ **[Database Guide](./docs/database_guide.md)** | An overview of the core database schema used by the IAToolkit framework itself.                         |

➡️ **[Explore all documentation](./docs/index.md)**

## 🤝 Contributing

We welcome contributions of all kinds! Whether it's a new feature, a bug fix, or an improvement to the documentation, your help is appreciated. Please read our **[Contributing Guide](./contributing.md)** to get started.

## 📄 License

IAToolkit is open-source software licensed under the **[MIT License](./LICENSE)**.