# Welcome to IAToolkit

## 1. What is IAToolkit?

IAToolkit is a powerful, flexible framework designed to build sophisticated, 
AI-powered assistants that integrate seamlessly with your corporate data. 
Its primary purpose is to bridge the gap between the advanced reasoning capabilities 
of Large Language Models (LLMs) and the valuable, often siloed, data within your organization.

With IAToolkit, you can create secure, multi-tenant, and highly customizable chat assistants 
that can query databases, process documents, and execute custom business logic on behalf 
of your users or clients.

---

## 2. The Problem it Solves

In today's enterprise landscape, data is everything. 
However, this data is often locked away in SQL databases, proprietary systems, 
and vast collections of documents. 
Integrating this private, structured, and unstructured data with modern AI in a secure and reliable 
way is a significant challenge.

IAToolkit solves this by providing a structured, scalable, and developer-friendly architecture to:

*   **Connect securely** to corporate SQL databases.
*   **Index and search** through private document repositories (like PDFs).
*   **Define and execute** custom business functions and workflows.
*   **Manage multiple tenants** (or "Companies") with isolated data, branding, and configurations.

---

## 3. Multi-LLM by Design

The world of AI is evolving rapidly. To ensure your application remains future-proof, 
IAToolkit is built with a provider-agnostic approach. You are not locked into a single LLM vendor.

*   **Built-in Support**: Out-of-the-box support for leading models from providers like **OpenAI** (e.g., GPT-4) and **Google** (e.g., Gemini).
*   **Extensible Architecture**: A clean, dependency-injected architecture makes it straightforward to add new LLM providers as they emerge.
*   **Per-Company Configuration**: You can even configure different LLMs for different "Companies," allowing you to optimize for cost, performance, or specific capabilities.

---

## 4. Key Components of the Toolkit

IAToolkit is composed of several key building blocks that work together to deliver a rich user experience:

*   **Companies**: The core concept for multi-tenancy. Each "Company" is an isolated environment with its own data sources, branding, prompts, business logic, and LLM configuration. [Learn more about Companies →](./companies_and_components.md)
*   **YAML Schema & Data Integration**: A declarative YAML-based schema allows you to map your corporate SQL databases. The toolkit uses this schema to automatically generate SQL queries from natural language, enabling the LLM to interact directly with your data.
*   **Branding & Configuration**: Each "Company" can have a unique look and feel, including custom logos, colors, and UI text (i18n support).
*   **Prompt & Function Management**: A powerful prompt manager using Jinja templates allows for dynamic and context-aware interactions. You can define custom Python functions (e.g., for calling external APIs, sending emails, generating reports) that the LLM can invoke.
*   **Document & Vector Stores (RAG)**: The toolkit includes a built-in system for uploading documents (like PDFs). These are automatically indexed into a vector store, enabling Retrieval-Augmented Generation (RAG) for question-answering over your private knowledge base.

---

## 5. How to Get Started

Ready to build your first AI assistant? Jump right into our quickstart guide to get your server up and running in minutes.

➡️ **[Quickstart: Installation and First Queries](./quickstart.md)**