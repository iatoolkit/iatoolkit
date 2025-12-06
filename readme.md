# 🧠 IAToolkit — Open-Source Framework for Real-World AI Assistants

Build private, production-grade AI assistants that run entirely inside your environment and speak the language of your business.

IAToolkit is not a demo wrapper or a prompt playground — it is a **full architecture** for implementing intelligent systems that combine LLMs, SQL data, internal documents, tools, workflows, and multi-tenant business logic.

---

## 🚀 Why IAToolkit?

Modern AI development is fragmented: LangChain handles chains, LlamaIndex handles documents, 
your backend handles SQL, your frontend handles chats, and your devs glue everything together.

**IAToolkit brings all of this into one unified, production-ready framework.**

It focuses on:

- **real-world data** (SQL + documents)
- **real workflows** (LLM tools + python services)
- **real multi-tenant architecture** (1 company → many companies)
- **real constraints** (security, reproducibility, governance)
- **real deployment** (your servers, your infrastructure)

IAToolkit lets you build the assistant that *your* organization needs — not a generic chatbot.

---

## 🧩 Architecture in a Nutshell

IAToolkit is a structured, layered framework:

Interfaces (Web & API)
        ↓
Intelligence Layer (prompts, tools, SQL orchestration, RAG)
        ↓
Execution Layer (services, workflows, validation)
        ↓
Data Access (SQLAlchemy, connectors)
        ↓
Company Modules (company.yaml + custom tools)

### ✔ Interfaces  
Chat UI, REST API, auth, sessions, JSON/HTML responses.

### ✔ Intelligence Layer  
Core logic: prompt rendering, SQL orchestration, RAG, LLM tool dispatching.

### ✔ Execution Layer  
Python services that implement real workflows: querying data, generating reports, retrieving documents, executing business logic.

### ✔ Data Access  
A clean repository pattern using SQLAlchemy.

### ✔ Company Modules  
Each company has:

- its own `company.yaml`
- its own prompts
- its own tools
- its own services
- its own vector store & SQL context

This modularity allows **true multi-tenancy**.

---

## 🔌 Connect to Anything

IAToolkit integrates naturally with:

- **SQL databases** (PostgreSQL, MySQL, SQL Server, etc.)
- **Document retrieval** (PDF, text, embeddings)
- **External APIs**
- **Internal microservices**
- **Custom Python tools**

It also includes a **production-grade RAG pipeline**, combining:

- embeddings  
- chunking  
- hybrid search  
- SQL queries + document retrieval  
- tool execution  

Everything orchestrated through the Intelligence Layer.

---

## 🏢 Multi-Tenant Architecture

A single installation of IAToolkit can power assistants for multiple companies, departments, or customers.
```text
companies/
    company_a
    company_b
    company_c
```
Each Company is fully isolated:

- prompts  
- tools  
- credentials  
- documents  
- SQL contexts  
- business rules  

This makes IAToolkit ideal for SaaS products, agencies, consultancies, and organizations with multiple business units.

---

## 🆓 Community Edition vs Enterprise Edition

IAToolkit follows a modern **open-core** model:

### 🟦 Community Edition (MIT License)
- Full Open-Source Core  
- SQL + Basic RAG  
- One Company  
- Custom Python tools  
- Self-managed deployment  

Perfect for developers, small teams, single-business use cases, and experimentation.

### 🟥 Enterprise Edition (Commercial License)
- Unlimited Companies (multi-tenant)  
- Payment services integration 
- Advanced RAG pipelines  
- External connectors (S3, APIs, email)  
- SSO, auditing, access controls  
- Priority support & continuous updates  
- Activation via **License Key**  

👉 Licensing information:  
- [Community Edition (MIT)](LICENSE_COMMUNITY.md)  
- [Enterprise License](ENTERPRISE_LICENSE.md)

---

## 🧩 Who Is IAToolkit For?

- Companies building internal “ChatGPT for the business”  
- SaaS products adding AI assistants for multiple customers  
- AI teams that need reproducible prompts and controlled tools  
- Developers who want real workflows, not toy demos  
- Organizations requiring privacy, security, and self-hosting  
- Teams working with SQL-heavy business logic  
- Consultancies deploying AI for multiple clients  

---

## ⭐ Key Differentiators

- prioritizes **architecture-first design**, not chains or wrappers  
- supports **multi-company** out of the box  
- integrates **SQL, RAG, and tools** into a single intelligence layer  
- keeps **business logic isolated** inside Company modules  
- runs entirely **on your own infrastructure**  
- ships with a **full web chat**, and API.  
- is built for **production**, not prototypes  

---

## 📚 Documentation

- 🚀 **[Quickstart](docs/quickstart.md)** – Set up your environment and run the project
- ☁️ **[Deployment Guide](docs/deployment_guide.md)** – Production deployment instructions
- 🏗️ **[Companies & Components](docs/companies_and_components.md)** – how Company modules work
- 🧠 **[Programming Guide](docs/programming_guide.md)** – services, intelligence layer, dispatching
- 🗃️ **[Database Guide](docs/database_guide.md)** – internal schema overview
- 🌱 **[Foundation Article](https://iatoolkit.com/pages/foundation)** – the “Why” behind the architecture
- 📘 **[Mini-Project (3 months)](https://iatoolkit.com/pages/mini_project)** – how to deploy a corporate AI assistant


---

## 🤝 Contributing

IAToolkit is open-source and community-friendly.  
PRs, issues, ideas, and feedback are always welcome.

---

## ⭐ Support the Project

If you find IAToolkit useful, please **star the GitHub repo** — it helps visibility and adoption.
