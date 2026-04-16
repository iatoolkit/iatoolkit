from __future__ import annotations

from unittest.mock import patch

import pytest

from iatoolkit.services import system_prompt_catalog


@pytest.fixture(autouse=True)
def _clear_cache():
    system_prompt_catalog.clear_system_prompt_catalog_cache()
    yield
    system_prompt_catalog.clear_system_prompt_catalog_cache()


def test_parse_catalog_valid_payload():
    payload = """
version: 1
prompts:
  - key: query_main
    filename: query_main.prompt
    include: always
  - key: sql_rules
    filename: sql_rules.prompt
    include:
      all_capabilities:
        - has_sql_sources
"""
    parsed = system_prompt_catalog._parse_catalog(payload)
    assert parsed == [
        {
            "key": "query_main",
            "filename": "query_main.prompt",
            "include": {"type": "always", "all_capabilities": [], "any_capabilities": [], "any_patterns": []},
        },
        {
            "key": "sql_rules",
            "filename": "sql_rules.prompt",
            "include": {
                "type": "capabilities",
                "all_capabilities": ["has_sql_sources"],
                "any_capabilities": [],
                "any_patterns": [],
            },
        },
    ]


def test_parse_catalog_rejects_invalid_include():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    include:
      unsupported: true
"""
    with pytest.raises(ValueError) as excinfo:
        system_prompt_catalog._parse_catalog(payload)

    assert "include has unsupported keys" in str(excinfo.value)


def test_select_entries_by_capability():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    include: always
  - key: sql_rules
    filename: sql_rules.prompt
    include:
      all_capabilities: [has_sql_sources]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        without_sql = system_prompt_catalog.select_system_prompt_entries(set())
        with_sql = system_prompt_catalog.select_system_prompt_entries({"has_sql_sources"})

    assert [item["key"] for item in without_sql] == ["query_main"]
    assert [item["key"] for item in with_sql] == ["query_main", "sql_rules"]


def test_select_entries_by_query_pattern():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    include: always
  - key: format_styles
    filename: format_styles.prompt
    include:
      any_patterns: [html, tabla, link]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        plain = system_prompt_catalog.select_system_prompt_entries(set(), query_text="resume la reunion")
        html = system_prompt_catalog.select_system_prompt_entries(set(), query_text="dame una tabla en html")

    assert [item["key"] for item in plain] == ["query_main"]
    assert [item["key"] for item in html] == ["query_main", "format_styles"]


def test_catalog_loader_is_cached_in_memory():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    include: always
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload) as mock_read_catalog, \
         patch.object(system_prompt_catalog, "_read_prompt_text", return_value="main prompt"):
        first = system_prompt_catalog.build_system_prompt_payload(set())
        second = system_prompt_catalog.build_system_prompt_payload(set())

    assert first == {"content": "main prompt", "selected_keys": ["query_main"]}
    assert second == {"content": "main prompt", "selected_keys": ["query_main"]}
    assert mock_read_catalog.call_count == 1
