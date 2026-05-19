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
    section: identity
    include: always
  - key: sql_rules
    filename: sql_rules.prompt
    section: data_access_rules
    include:
      all_capabilities:
        - can_query_sql
"""
    parsed = system_prompt_catalog._parse_catalog(payload)
    assert parsed == [
        {
            "key": "query_main",
            "filename": "query_main.prompt",
            "section": "identity",
            "include": {
                "type": "always",
                "all_capabilities": [],
                "any_capabilities": [],
                "any_patterns": [],
                "execution_modes": [],
                "response_modes": [],
                "agent_roles": [],
            },
        },
        {
            "key": "sql_rules",
            "filename": "sql_rules.prompt",
            "section": "data_access_rules",
            "include": {
                "type": "capabilities",
                "all_capabilities": ["can_query_sql"],
                "any_capabilities": [],
                "any_patterns": [],
                "execution_modes": [],
                "response_modes": [],
                "agent_roles": [],
            },
        },
    ]


def test_parse_catalog_rejects_invalid_include():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    section: identity
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
    section: identity
    include: always
  - key: sql_rules
    filename: sql_rules.prompt
    section: data_access_rules
    include:
      all_capabilities: [can_query_sql]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        without_sql = system_prompt_catalog.select_system_prompt_entries(set())
        with_sql = system_prompt_catalog.select_system_prompt_entries({"can_query_sql"})

    assert [item["key"] for item in without_sql] == ["query_main"]
    assert [item["key"] for item in with_sql] == ["query_main", "sql_rules"]


def test_select_entries_by_memory_capability():
    payload = """
prompts:
  - key: core_identity
    filename: core_identity.prompt
    section: identity
    include:
      execution_modes: [chat, agent]
  - key: memory_usage
    filename: memory_usage.prompt
    section: conversation_rules
    include:
      execution_modes: [chat, agent]
      all_capabilities: [can_use_memory]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        without_memory = system_prompt_catalog.select_system_prompt_entries(
            set(),
            execution_mode="chat",
            response_mode="chat_compatible",
        )
        with_memory = system_prompt_catalog.select_system_prompt_entries(
            {"can_use_memory"},
            execution_mode="chat",
            response_mode="chat_compatible",
        )

    assert [item["key"] for item in without_memory] == ["core_identity"]
    assert [item["key"] for item in with_memory] == ["core_identity", "memory_usage"]


def test_select_entries_by_execution_mode_and_response_mode():
    payload = """
prompts:
  - key: core_identity
    filename: core_identity.prompt
    section: identity
    include:
      execution_modes: [chat, agent]
  - key: chat_user_profile
    filename: chat_user_profile.prompt
    section: identity
    include:
      execution_modes: [chat]
  - key: output_basics
    filename: output_basics.prompt
    section: output_contract
    include:
      execution_modes: [chat, agent]
      response_modes: [chat_compatible]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        chat = system_prompt_catalog.select_system_prompt_entries(
            set(),
            execution_mode="chat",
            response_mode="chat_compatible",
        )
        agent_structured = system_prompt_catalog.select_system_prompt_entries(
            set(),
            execution_mode="agent",
            response_mode="structured_only",
        )

    assert [item["key"] for item in chat] == ["core_identity", "chat_user_profile", "output_basics"]
    assert [item["key"] for item in agent_structured] == ["core_identity"]


def test_select_entries_by_agent_role():
    payload = """
prompts:
  - key: core_identity
    filename: core_identity.prompt
    section: identity
    include:
      execution_modes: [agent]
  - key: channel_business_identity
    filename: channel_business_identity.prompt
    section: business_context
    include:
      execution_modes: [agent]
      agent_roles: [channels]
  - key: operations_guardrails
    filename: operations_guardrails.prompt
    section: conversation_rules
    include:
      execution_modes: [agent]
      agent_roles: [operations]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        channels = system_prompt_catalog.select_system_prompt_entries(
            set(),
            execution_mode="agent",
            response_mode="chat_compatible",
            agent_role="channels",
        )
        operations = system_prompt_catalog.select_system_prompt_entries(
            set(),
            execution_mode="agent",
            response_mode="chat_compatible",
            agent_role="operations",
        )
        generic_agent = system_prompt_catalog.select_system_prompt_entries(
            set(),
            execution_mode="agent",
            response_mode="chat_compatible",
            agent_role="workspace_agent",
        )

    assert [item["key"] for item in channels] == ["core_identity", "channel_business_identity"]
    assert [item["key"] for item in operations] == ["core_identity", "operations_guardrails"]
    assert [item["key"] for item in generic_agent] == ["core_identity"]


def test_select_entries_by_query_pattern():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    section: identity
    include: always
  - key: format_styles
    filename: format_styles.prompt
    section: output_contract
    include:
      any_patterns: [html, tabla, link]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        plain = system_prompt_catalog.select_system_prompt_entries(
            set(),
            query_text="resume la reunion",
            execution_mode="chat",
        )
        html = system_prompt_catalog.select_system_prompt_entries(
            set(),
            query_text="dame una tabla en html",
            execution_mode="chat",
        )

    assert [item["key"] for item in plain] == ["query_main"]
    assert [item["key"] for item in html] == ["query_main", "format_styles"]


def test_select_entries_by_sql_dialect_capabilities():
    payload = """
prompts:
  - key: sql_core
    filename: sql_core.prompt
    section: data_access_rules
    include:
      all_capabilities: [can_query_sql]
  - key: sql_postgres
    filename: sql_jsonb.prompt
    section: data_access_rules
    include:
      all_capabilities: [can_query_sql_postgres]
  - key: sql_redshift
    filename: sql_redshift_basics.prompt
    section: data_access_rules
    include:
      all_capabilities: [can_query_sql_redshift]
  - key: sql_mysql
    filename: sql_mysql_json.prompt
    section: data_access_rules
    include:
      all_capabilities: [can_query_sql_mysql]
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload):
        postgres = system_prompt_catalog.select_system_prompt_entries(
            {"can_query_sql", "can_query_sql_postgres"},
            execution_mode="chat",
        )
        redshift = system_prompt_catalog.select_system_prompt_entries(
            {"can_query_sql", "can_query_sql_redshift"},
            execution_mode="chat",
        )
        mysql = system_prompt_catalog.select_system_prompt_entries(
            {"can_query_sql", "can_query_sql_mysql"},
            execution_mode="chat",
        )
        mixed = system_prompt_catalog.select_system_prompt_entries(
            {"can_query_sql"},
            execution_mode="chat",
        )

    assert [item["key"] for item in postgres] == ["sql_core", "sql_postgres"]
    assert [item["key"] for item in redshift] == ["sql_core", "sql_redshift"]
    assert [item["key"] for item in mysql] == ["sql_core", "sql_mysql"]
    assert [item["key"] for item in mixed] == ["sql_core"]


def test_catalog_loader_is_cached_in_memory():
    payload = """
prompts:
  - key: query_main
    filename: query_main.prompt
    section: identity
    include: always
"""
    with patch.object(system_prompt_catalog, "_read_catalog_text", return_value=payload) as mock_read_catalog, \
         patch.object(system_prompt_catalog, "_read_prompt_text", return_value="main prompt"):
        first = system_prompt_catalog.build_system_prompt_payload(set(), execution_mode="chat")
        second = system_prompt_catalog.build_system_prompt_payload(set(), execution_mode="chat")

    assert first == {
        "content": "main prompt",
        "selected_keys": ["query_main"],
        "sections": [
            {
                "section": "identity",
                "content": "main prompt",
                "selected_keys": ["query_main"],
            }
        ],
    }
    assert second == first
    assert mock_read_catalog.call_count == 1
