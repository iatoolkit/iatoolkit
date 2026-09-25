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

- Dependencies are managed with uv: `pyproject.toml` + `uv.lock`, environment in
  `.venv`, created and updated by `uv sync`.
- Python path: `./.venv/bin/python`, or run through `uv run <cmd>`.
- The legacy `venv/` is no longer maintained by uv and will drift — do not use it.
- `PYTHONPATH=./src` is no longer needed: `pyproject.toml` declares `pythonpath`
  and `testpaths` for pytest.

Testing:
uv run pytest
