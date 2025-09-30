# iatoolkit

IAToolkit is a comprehensive, open-source framework designed for building enterprise-grade 
AI chatbots and conversational applications. 
With IAToolkit, you can build production-ready, context-aware chatbots and agents that 
can query relational databases, perform semantic searches on documents, 
and connect to your internal APIs in minutes.

IAToolkit bridges the gap between powerful LLMs and your company's data. 


## 🚀 Key Features

*   **🔗 Unified Data Connection**:
    *   **Natural Language to SQL**: Let your chatbot query relational databases (PostgreSQL, MySQL, SQLite) using everyday language.
    *   **Semantic Document Search**: Automatically chunk, embed, and search across your private documents (PDFs, Word, etc.) to provide contextually accurate answers.

*   **🏢 Enterprise-Ready Multi-Tenancy**:
    *   Deploy isolated "Company" modules, each with its own data, tools, and context. Perfect for SaaS products or internal departmental agents.

**🧠 LLM Agnostic**:
    *   Switch between **OpenAI (GPT-*)** and **Google (Gemini-*)** with a single line change in your configuration. No code refactoring needed.

**🛠️ Developer-First Experience**:
    *   Built with Flask using a clean, **Dependency Injection** architecture.
    *   High-quality code base with **90%+ test coverage**.
    *   Powerful Flask-based **CLI** for database setup, API key generation, and more.

**🔒 Security & Observability Built-In**:
    *   Comes with JWT-based authentication, user management, and secure session handling out of the box.
    *   Full traceability with detailed logging of all queries, function calls, token usage, and costs.

## ⚡ Quick Start: Create a Custom Tool in 30 Seconds

See how easy it is to give your AI a new skill. Just define a method inside your Company class and describe it. 
IAToolkit handles the rest.

## 🤝 Contributing

We welcome contributions! Whether it's adding a new feature, improving documentation, or fixing a bug, 
please feel free to open a pull request.

## 📄 License

IAToolkit is open-source and licensed under the [MIT License](LICENSE).