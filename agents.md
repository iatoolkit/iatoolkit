# AGENTS.md

Global IAToolkit architecture context:

- Shared architecture memory:
  `/Users/fernando/Documents/software/architecture/iatoolkit-architecture.md`
- Parent Codex context:
  `/Users/fernando/Documents/software/AGENTS.md`
- This repo is the open-source core framework. Generic assistant behavior,
  base services, SQL/RAG/tool primitives, prompts, repositories and reusable
  company-module mechanics belong here.
- Do not create GitHub branches automatically. Only create or switch branches
  when Fernando explicitly asks for it.
- Preserve tenant/company isolation across prompts, credentials, schemas,
  tools, documents, vector stores and business rules.

Environment rules:

- Always use project virtualenv
- Python path: ./venv/bin/python
- Use PYTHONPATH=./src

Testing:
./venv/bin/python -m pytest
