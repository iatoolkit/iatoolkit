from __future__ import annotations

from unittest.mock import patch

import pytest

from iatoolkit.services import system_tools


def test_parse_system_tools_catalog_valid_payload():
    payload = """
version: 1
pack:
  key: system
  name: System Tools
tools:
  - function_name: custom_tool
    description: Custom description
    parameters:
      type: object
      properties: {}
      required: []
"""
    result = system_tools._parse_system_tools_catalog(payload)
    assert result == [
        {
            "function_name": "custom_tool",
            "description": "Custom description",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]


def test_parse_system_tools_catalog_accepts_routing_force_include_capability():
    payload = """
tools:
  - function_name: custom_tool
    description: Custom description
    routing:
      force_include_capability: has_custom_capability
    parameters:
      type: object
      properties: {}
      required: []
"""
    result = system_tools._parse_system_tools_catalog(payload)
    assert result == [
        {
            "function_name": "custom_tool",
            "description": "Custom description",
            "routing": {"force_include_capability": "has_custom_capability"},
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]


def test_parse_system_tools_catalog_accepts_routing_profile():
    payload = """
tools:
  - function_name: custom_tool
    description: Custom description
    routing_profile:
      tags: [a, b]
      intents: ["Intent A"]
      examples: ["custom_tool(query=\\"x\\")"]
      cost:
        penalty: 0.12
        latency_class: medium
    parameters:
      type: object
      properties: {}
      required: []
"""
    result = system_tools._parse_system_tools_catalog(payload)
    assert result == [
        {
            "function_name": "custom_tool",
            "description": "Custom description",
            "routing_profile": {
                "tags": ["a", "b"],
                "intents": ["Intent A"],
                "examples": ['custom_tool(query="x")'],
                "cost": {"penalty": 0.12, "latency_class": "medium"},
            },
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]


def test_parse_system_tools_catalog_rejects_unknown_routing_keys():
    payload = """
tools:
  - function_name: custom_tool
    description: Custom description
    routing:
      unknown: value
    parameters:
      type: object
"""
    with pytest.raises(ValueError) as excinfo:
        system_tools._parse_system_tools_catalog(payload)
    assert "routing has unsupported keys" in str(excinfo.value)


def test_parse_system_tools_catalog_rejects_unknown_routing_profile_keys():
    payload = """
tools:
  - function_name: custom_tool
    description: Custom description
    routing_profile:
      unsupported: true
    parameters:
      type: object
"""
    with pytest.raises(ValueError) as excinfo:
        system_tools._parse_system_tools_catalog(payload)
    assert "routing_profile has unsupported keys" in str(excinfo.value)


def test_parse_system_tools_catalog_rejects_duplicate_names():
    payload = """
tools:
  - function_name: duplicated_tool
    description: A
    parameters:
      type: object
  - function_name: duplicated_tool
    description: B
    parameters:
      type: object
"""
    with pytest.raises(ValueError) as excinfo:
        system_tools._parse_system_tools_catalog(payload)
    assert "duplicated system tool function_name" in str(excinfo.value)


def test_load_system_tools_definitions_raises_when_catalog_read_fails():
    with patch.object(system_tools, "_read_system_tools_catalog_text", side_effect=FileNotFoundError("missing")):
        with pytest.raises(FileNotFoundError):
            system_tools.load_system_tools_definitions()


def test_load_system_tools_definitions_sets_yaml_catalog_source_when_load_succeeds():
    payload = """
tools:
  - function_name: custom_tool
    description: Custom description
    parameters:
      type: object
      properties: {}
      required: []
"""
    with patch.object(system_tools, "_read_system_tools_catalog_text", return_value=payload):
        loaded = system_tools.load_system_tools_definitions()

    assert loaded == [
        {
            "function_name": "custom_tool",
            "description": "Custom description",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]
    assert system_tools.get_system_tools_catalog_source() == "yaml"


def test_get_system_tool_force_include_capabilities():
    with patch.object(
        system_tools,
        "SYSTEM_TOOLS_DEFINITIONS",
        [
            {
                "function_name": "tool_a",
                "description": "A",
                "parameters": {"type": "object"},
                "routing": {"force_include_capability": "cap_a"},
            },
            {
                "function_name": "tool_b",
                "description": "B",
                "parameters": {"type": "object"},
            },
        ],
    ):
        assert system_tools.get_system_tool_force_include_capabilities() == {"tool_a": "cap_a"}


def test_get_system_tool_routing_profile():
    with patch.object(
        system_tools,
        "SYSTEM_TOOLS_DEFINITIONS",
        [
            {
                "function_name": "tool_a",
                "description": "A",
                "parameters": {"type": "object"},
                "routing_profile": {
                    "tags": ["a"],
                    "intents": ["intent"],
                    "examples": ["tool_a()"],
                    "cost": {"penalty": 0.1},
                },
            },
        ],
    ):
        profile = system_tools.get_system_tool_routing_profile("tool_a")
        assert profile == {
            "tags": ["a"],
            "intents": ["intent"],
            "examples": ["tool_a()"],
            "cost": {"penalty": 0.1},
        }
        assert system_tools.get_system_tool_routing_profile("tool_missing") is None
