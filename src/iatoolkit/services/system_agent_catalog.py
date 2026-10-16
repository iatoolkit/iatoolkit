# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
System agents: the model calls the platform makes on its own, defined in code.

A system agent is not a tenant agent. It does not converse or call tools: the
code builds its inputs, the model answers JSON following `output_schema`, and
the code validates and repairs that answer. So a tenant may pick its model but
never its prompt, inputs or schema, which would break the code that reads the
answer and fall behind when the platform improves the prompt.

Each package that defines agents ships a `system_agents_pack.yaml` next to a
`system_agents/` folder with the `.prompt` templates (Jinja). Core's pack is
always loaded; another package (enterprise) adds its own with `register_pack`
when it boots, and every caller sees one catalog.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from importlib import resources

import yaml


CORE_PACKAGE = "iatoolkit.config"
PACK_FILENAME = "system_agents_pack.yaml"
PROMPTS_DIRNAME = "system_agents"
PROMPT_NAME_PREFIX = "system_agent:"
# Keys go into company.yaml paths written with dot notation (system_agents.<key>.model).
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SCHEMA_MODES = {"best_effort", "strict"}
RESPONSE_MODES = {"structured_only", "chat_compatible"}


@dataclass(frozen=True)
class SystemAgent:
    key: str
    name: str
    description: str
    module: str
    prompt_filename: str
    prompt_template: str
    output_schema: dict
    inputs: tuple[str, ...] = ()
    default_model: str | None = None
    schema_mode: str = "best_effort"
    response_mode: str = "structured_only"
    package: str = CORE_PACKAGE
    name_en: str | None = None
    description_en: str | None = None
    # It reads images: only models whose provider takes native images (BL-014).
    requires_vision: bool = False

    @property
    def prompt_name(self) -> str:
        """How its executions are marked in iat_queries.prompt_name."""
        return f"{PROMPT_NAME_PREFIX}{self.key}"

    def response_contract(self) -> dict:
        return {
            "schema": copy.deepcopy(self.output_schema),
            "schema_mode": self.schema_mode,
            "response_mode": self.response_mode,
        }


@dataclass
class _Catalog:
    agents: dict[str, SystemAgent] = field(default_factory=dict)


class SystemAgentCatalog:
    """Loads the registered packs once per process; `reload()` drops that cache."""

    _extra_packages: list[str] = []
    _cache: _Catalog | None = None

    @classmethod
    def register_pack(cls, package: str) -> None:
        """Adds a package's `system_agents_pack.yaml` (and its prompts) to the catalog."""
        package = str(package or "").strip()
        if package and package != CORE_PACKAGE and package not in cls._extra_packages:
            cls._extra_packages.append(package)
            cls._cache = None

    @classmethod
    def reload(cls) -> None:
        cls._cache = None

    @classmethod
    def list(cls) -> list[SystemAgent]:
        return list(cls._load().agents.values())

    @classmethod
    def get(cls, key: str) -> SystemAgent:
        agent = cls._load().agents.get(str(key or "").strip())
        if agent is None:
            raise KeyError(f"unknown system agent '{key}'")
        return agent

    @classmethod
    def find(cls, key: str) -> SystemAgent | None:
        return cls._load().agents.get(str(key or "").strip())

    @classmethod
    def _load(cls) -> _Catalog:
        if cls._cache is None:
            catalog = _Catalog()
            for package in [CORE_PACKAGE, *cls._extra_packages]:
                for agent in load_pack(package):
                    if agent.key in catalog.agents:
                        raise ValueError(
                            f"system agent '{agent.key}' is defined by both "
                            f"{catalog.agents[agent.key].package} and {package}"
                        )
                    catalog.agents[agent.key] = agent
            cls._cache = catalog
        return cls._cache


def load_pack(package: str) -> list[SystemAgent]:
    root = resources.files(package)
    pack_resource = root.joinpath(PACK_FILENAME)
    if not pack_resource.is_file():
        raise ValueError(f"{package} has no {PACK_FILENAME}")
    pack = yaml.safe_load(pack_resource.read_text(encoding="utf-8")) or {}
    if not isinstance(pack, dict):
        raise ValueError(f"{package}/{PACK_FILENAME} must be an object")

    schemas = pack.get("schemas") or {}
    if not isinstance(schemas, dict):
        raise ValueError(f"{package}/{PACK_FILENAME}: schemas must be an object")
    entries = pack.get("agents") or []
    if not isinstance(entries, list):
        raise ValueError(f"{package}/{PACK_FILENAME}: agents must be a list")

    agents = []
    for index, entry in enumerate(entries):
        where = f"{package}/{PACK_FILENAME} agents[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{where} must be an object")
        key = str(entry.get("key") or "").strip()
        if not KEY_PATTERN.match(key):
            raise ValueError(f"{where}.key must be lowercase snake_case")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise ValueError(f"{where}.name is required")

        prompt_filename = str(entry.get("prompt") or "").strip()
        prompt_resource = root.joinpath(PROMPTS_DIRNAME, prompt_filename) if prompt_filename else None
        if prompt_resource is None or not prompt_resource.is_file():
            raise ValueError(f"{where}.prompt '{prompt_filename}' not found in {package}/{PROMPTS_DIRNAME}")

        output_schema = entry.get("output_schema")
        if isinstance(output_schema, str):
            # A schema shared by several agents, declared once under `schemas:`.
            output_schema = schemas.get(output_schema)
        if not isinstance(output_schema, dict) or not output_schema:
            raise ValueError(f"{where}.output_schema must be an object or the name of one under schemas")

        schema_mode = str(entry.get("schema_mode") or "best_effort").strip()
        response_mode = str(entry.get("response_mode") or "structured_only").strip()
        if schema_mode not in SCHEMA_MODES:
            raise ValueError(f"{where}.schema_mode must be one of {sorted(SCHEMA_MODES)}")
        if response_mode not in RESPONSE_MODES:
            raise ValueError(f"{where}.response_mode must be one of {sorted(RESPONSE_MODES)}")

        inputs = entry.get("inputs") or []
        if not isinstance(inputs, list) or not all(isinstance(item, str) and item.strip() for item in inputs):
            raise ValueError(f"{where}.inputs must be a list of names")

        agents.append(SystemAgent(
            key=key,
            name=name,
            name_en=str(entry.get("name_en") or "").strip() or None,
            description=str(entry.get("description") or "").strip(),
            description_en=str(entry.get("description_en") or "").strip() or None,
            module=str(entry.get("module") or "").strip() or "platform",
            prompt_filename=prompt_filename,
            prompt_template=prompt_resource.read_text(encoding="utf-8"),
            output_schema=copy.deepcopy(output_schema),
            inputs=tuple(item.strip() for item in inputs),
            default_model=str(entry.get("default_model") or "").strip() or None,
            schema_mode=schema_mode,
            response_mode=response_mode,
            package=package,
            requires_vision=bool(entry.get("requires_vision")),
        ))
    return agents
