from __future__ import annotations

import copy
import importlib.resources
from functools import lru_cache
from typing import Any

import yaml


SYSTEM_PROMPTS_CONFIG_PACKAGE = "iatoolkit.config"
SYSTEM_PROMPTS_CONFIG_FILENAME = "system_prompts_pack.yaml"
SYSTEM_PROMPTS_PACKAGE = "iatoolkit.system_prompts"


def _read_catalog_text() -> str:
    return importlib.resources.read_text(SYSTEM_PROMPTS_CONFIG_PACKAGE, SYSTEM_PROMPTS_CONFIG_FILENAME)


def _normalize_capability_list(value: Any, field_name: str, index: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"prompts[{index}].include.{field_name} must be a list")

    normalized: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"prompts[{index}].include.{field_name}[{item_index}] must be a string")
        capability = item.strip()
        if not capability:
            raise ValueError(f"prompts[{index}].include.{field_name}[{item_index}] cannot be empty")
        if capability not in normalized:
            normalized.append(capability)
    return normalized


def _normalize_mode_list(
    value: Any,
    *,
    field_name: str,
    index: int,
    allowed_values: set[str],
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"prompts[{index}].include.{field_name} must be a list")

    normalized: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"prompts[{index}].include.{field_name}[{item_index}] must be a string")
        mode = item.strip().lower()
        if not mode:
            raise ValueError(f"prompts[{index}].include.{field_name}[{item_index}] cannot be empty")
        if mode not in allowed_values:
            raise ValueError(
                f"prompts[{index}].include.{field_name}[{item_index}] must be one of {sorted(allowed_values)}"
            )
        if mode not in normalized:
            normalized.append(mode)
    return normalized


def _normalize_pattern_list(value: Any, index: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"prompts[{index}].include.any_patterns must be a list")

    normalized: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"prompts[{index}].include.any_patterns[{item_index}] must be a string")
        pattern = item.strip().lower()
        if not pattern:
            raise ValueError(f"prompts[{index}].include.any_patterns[{item_index}] cannot be empty")
        if pattern not in normalized:
            normalized.append(pattern)
    return normalized


def _normalize_include_rule(value: Any, index: int) -> dict:
    if value in (None, "always"):
        return {
            "type": "always",
            "all_capabilities": [],
            "any_capabilities": [],
            "any_patterns": [],
            "execution_modes": [],
            "response_modes": [],
        }

    if not isinstance(value, dict):
        raise ValueError(f"prompts[{index}].include must be 'always' or an object")

    unknown_keys = [
        key
        for key in value.keys()
        if key not in {
            "all_capabilities",
            "any_capabilities",
            "any_patterns",
            "execution_modes",
            "response_modes",
        }
    ]
    if unknown_keys:
        raise ValueError(f"prompts[{index}].include has unsupported keys: {sorted(unknown_keys)}")

    all_capabilities = _normalize_capability_list(value.get("all_capabilities"), "all_capabilities", index)
    any_capabilities = _normalize_capability_list(value.get("any_capabilities"), "any_capabilities", index)
    any_patterns = _normalize_pattern_list(value.get("any_patterns"), index)
    execution_modes = _normalize_mode_list(
        value.get("execution_modes"),
        field_name="execution_modes",
        index=index,
        allowed_values={"chat", "agent"},
    )
    response_modes = _normalize_mode_list(
        value.get("response_modes"),
        field_name="response_modes",
        index=index,
        allowed_values={"chat_compatible", "structured_only"},
    )
    if not all_capabilities and not any_capabilities and not any_patterns and not execution_modes and not response_modes:
        raise ValueError(
            f"prompts[{index}].include must define at least one of "
            "'all_capabilities', 'any_capabilities', 'any_patterns', 'execution_modes', or 'response_modes'"
        )

    return {
        "type": "capabilities",
        "all_capabilities": all_capabilities,
        "any_capabilities": any_capabilities,
        "any_patterns": any_patterns,
        "execution_modes": execution_modes,
        "response_modes": response_modes,
    }


def _parse_catalog(text: str) -> list[dict]:
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("system prompts catalog must be a YAML object")

    prompts = payload.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("system prompts catalog must include a non-empty 'prompts' list")

    normalized: list[dict] = []
    seen_keys: set[str] = set()

    for index, raw_prompt in enumerate(prompts):
        if not isinstance(raw_prompt, dict):
            raise ValueError(f"prompts[{index}] must be an object")

        key = str(raw_prompt.get("key") or "").strip()
        if not key:
            raise ValueError(f"prompts[{index}].key is required")
        if key in seen_keys:
            raise ValueError(f"duplicated system prompt key '{key}'")

        filename = str(raw_prompt.get("filename") or "").strip()
        if not filename:
            raise ValueError(f"prompts[{index}].filename is required")

        include_rule = _normalize_include_rule(raw_prompt.get("include"), index)

        normalized.append(
            {
                "key": key,
                "filename": filename,
                "include": include_rule,
            }
        )
        seen_keys.add(key)

    return normalized


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[dict, ...]:
    return tuple(_parse_catalog(_read_catalog_text()))


@lru_cache(maxsize=64)
def _read_prompt_text(filename: str) -> str:
    return importlib.resources.read_text(SYSTEM_PROMPTS_PACKAGE, filename)


def get_system_prompt_entries() -> list[dict]:
    return [copy.deepcopy(item) for item in _load_catalog()]


def _matches_include_rule(
    rule: dict,
    capabilities: set[str],
    *,
    query_text: str | None = None,
    execution_mode: str | None = None,
    response_mode: str | None = None,
) -> bool:
    if rule.get("type") == "always":
        return True

    all_capabilities = rule.get("all_capabilities") or []
    any_capabilities = rule.get("any_capabilities") or []
    any_patterns = rule.get("any_patterns") or []
    execution_modes = rule.get("execution_modes") or []
    response_modes = rule.get("response_modes") or []

    normalized_execution_mode = str(execution_mode or "").strip().lower()
    normalized_response_mode = str(response_mode or "").strip().lower()

    if execution_modes:
        if not normalized_execution_mode or normalized_execution_mode not in execution_modes:
            return False

    if response_modes:
        if not normalized_response_mode or normalized_response_mode not in response_modes:
            return False

    if all_capabilities and not set(all_capabilities).issubset(capabilities):
        return False

    if any_capabilities and not set(any_capabilities).intersection(capabilities):
        return False

    if any_patterns:
        haystack = (query_text or "").strip().lower()
        if not haystack:
            return False
        if not any(pattern in haystack for pattern in any_patterns):
            return False

    return True


def select_system_prompt_entries(
    capabilities: set[str] | list[str] | tuple[str, ...] | None = None,
    query_text: str | None = None,
    execution_mode: str | None = None,
    response_mode: str | None = None,
) -> list[dict]:
    capability_set = {item for item in (capabilities or []) if isinstance(item, str) and item.strip()}
    selected: list[dict] = []

    for entry in _load_catalog():
        include_rule = entry.get("include") or {"type": "always"}
        if _matches_include_rule(
            include_rule,
            capability_set,
            query_text=query_text,
            execution_mode=execution_mode,
            response_mode=response_mode,
        ):
            selected.append(copy.deepcopy(entry))

    return selected


def build_system_prompt_payload(
    capabilities: set[str] | list[str] | tuple[str, ...] | None = None,
    query_text: str | None = None,
    execution_mode: str | None = None,
    response_mode: str | None = None,
) -> dict:
    selected_entries = select_system_prompt_entries(
        capabilities,
        query_text=query_text,
        execution_mode=execution_mode,
        response_mode=response_mode,
    )

    selected_keys: list[str] = []
    content_parts: list[str] = []
    for entry in selected_entries:
        filename = str(entry.get("filename") or "").strip()
        key = str(entry.get("key") or "").strip()
        if not filename or not key:
            continue
        content_parts.append(_read_prompt_text(filename))
        selected_keys.append(key)

    return {
        "content": "\n".join(content_parts),
        "selected_keys": selected_keys,
    }


def clear_system_prompt_catalog_cache():
    _load_catalog.cache_clear()
    _read_prompt_text.cache_clear()
