from __future__ import annotations

import copy
from importlib import resources
from typing import Any

import yaml


SYSTEM_TOOLS_CONFIG_PACKAGE = "iatoolkit.config"
SYSTEM_TOOLS_CONFIG_FILENAME = "system_tools_pack.yaml"
SYSTEM_TOOLS_CATALOG_SOURCE = "yaml"
_ROUTING_PROFILE_ALLOWED_KEYS = {"tags", "intents", "examples", "cost"}


def _read_system_tools_catalog_text() -> str:
    catalog_resource = resources.files(SYSTEM_TOOLS_CONFIG_PACKAGE).joinpath(SYSTEM_TOOLS_CONFIG_FILENAME)
    return catalog_resource.read_text(encoding="utf-8")


def _validate_system_tool_entry(entry: dict, index: int) -> dict:
    if not isinstance(entry, dict):
        raise ValueError(f"tools[{index}] must be an object")

    function_name = str(entry.get("function_name") or "").strip()
    if not function_name:
        raise ValueError(f"tools[{index}].function_name is required")

    description = str(entry.get("description") or "").strip()
    if not description:
        raise ValueError(f"tools[{index}].description is required")

    parameters = entry.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError(f"tools[{index}].parameters must be an object")

    routing = entry.get("routing")
    normalized_routing = None
    if routing is not None:
        if not isinstance(routing, dict):
            raise ValueError(f"tools[{index}].routing must be an object")
        unknown_routing_keys = [key for key in routing.keys() if key != "force_include_capability"]
        if unknown_routing_keys:
            raise ValueError(
                f"tools[{index}].routing has unsupported keys: {sorted(unknown_routing_keys)}"
            )

        force_include_capability = str(routing.get("force_include_capability") or "").strip()
        if force_include_capability:
            normalized_routing = {
                "force_include_capability": force_include_capability
            }

    routing_profile = entry.get("routing_profile")
    normalized_routing_profile = _validate_routing_profile(routing_profile, index)

    normalized = {
        "function_name": function_name,
        "description": description,
        "parameters": copy.deepcopy(parameters),
    }
    if normalized_routing is not None:
        normalized["routing"] = normalized_routing
    if normalized_routing_profile is not None:
        normalized["routing_profile"] = normalized_routing_profile
    return normalized


def _validate_routing_profile(routing_profile: Any, index: int) -> dict | None:
    if routing_profile is None:
        return None
    if not isinstance(routing_profile, dict):
        raise ValueError(f"tools[{index}].routing_profile must be an object")

    unknown_keys = [key for key in routing_profile.keys() if key not in _ROUTING_PROFILE_ALLOWED_KEYS]
    if unknown_keys:
        raise ValueError(
            f"tools[{index}].routing_profile has unsupported keys: {sorted(unknown_keys)}"
        )

    normalized: dict[str, Any] = {
        "tags": [],
        "intents": [],
        "examples": [],
        "cost": {},
    }
    for field_name in ("tags", "intents", "examples"):
        raw_values = routing_profile.get(field_name)
        if raw_values is None:
            continue
        if not isinstance(raw_values, list):
            raise ValueError(f"tools[{index}].routing_profile.{field_name} must be a list")

        normalized_values: list[str] = []
        for item_index, value in enumerate(raw_values):
            if not isinstance(value, str):
                raise ValueError(
                    f"tools[{index}].routing_profile.{field_name}[{item_index}] must be a string"
                )
            item = value.strip()
            if not item:
                raise ValueError(
                    f"tools[{index}].routing_profile.{field_name}[{item_index}] cannot be empty"
                )
            if item not in normalized_values:
                normalized_values.append(item)
        normalized[field_name] = normalized_values

    raw_cost = routing_profile.get("cost")
    if raw_cost is not None:
        if not isinstance(raw_cost, dict):
            raise ValueError(f"tools[{index}].routing_profile.cost must be an object")
        normalized_cost = copy.deepcopy(raw_cost)
        penalty = normalized_cost.get("penalty")
        if penalty is not None:
            if isinstance(penalty, bool) or not isinstance(penalty, (int, float)) or penalty < 0:
                raise ValueError(
                    f"tools[{index}].routing_profile.cost.penalty must be a non-negative number"
                )
            normalized_cost["penalty"] = float(penalty)
        normalized["cost"] = normalized_cost

    return normalized


def _parse_system_tools_catalog(catalog_text: str) -> list[dict]:
    payload = yaml.safe_load(catalog_text)
    if not isinstance(payload, dict):
        raise ValueError("system tools catalog must be a YAML object")

    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValueError("system tools catalog must include a non-empty 'tools' list")

    normalized: list[dict] = []
    seen_names: set[str] = set()
    for index, entry in enumerate(tools):
        item = _validate_system_tool_entry(entry, index)
        function_name = item["function_name"]
        if function_name in seen_names:
            raise ValueError(f"duplicated system tool function_name '{function_name}'")
        seen_names.add(function_name)
        normalized.append(item)

    return normalized


def load_system_tools_definitions() -> list[dict]:
    global SYSTEM_TOOLS_CATALOG_SOURCE
    catalog_text = _read_system_tools_catalog_text()
    SYSTEM_TOOLS_CATALOG_SOURCE = "yaml"
    return _parse_system_tools_catalog(catalog_text)


SYSTEM_TOOLS_DEFINITIONS = load_system_tools_definitions()


def get_system_tools_catalog_source() -> str:
    return SYSTEM_TOOLS_CATALOG_SOURCE


def get_system_tool_force_include_capabilities() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for tool in SYSTEM_TOOLS_DEFINITIONS:
        function_name = str(tool.get("function_name") or "").strip()
        if not function_name:
            continue
        routing = tool.get("routing")
        if not isinstance(routing, dict):
            continue
        capability = str(routing.get("force_include_capability") or "").strip()
        if capability:
            mapping[function_name] = capability
    return mapping


def get_system_tool_routing_profile(function_name: str) -> dict | None:
    target = str(function_name or "").strip()
    if not target:
        return None

    for tool in SYSTEM_TOOLS_DEFINITIONS:
        candidate_name = str(tool.get("function_name") or "").strip()
        if candidate_name != target:
            continue
        routing_profile = tool.get("routing_profile")
        if isinstance(routing_profile, dict):
            return copy.deepcopy(routing_profile)
        return None

    return None
