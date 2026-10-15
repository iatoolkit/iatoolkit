from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iatoolkit.services.system_agent_catalog import SystemAgentCatalog
from iatoolkit.services.system_agent_runner import (
    PlatformAgentSettings,
    SystemAgentDisabled,
    SystemAgentRunner,
    SystemAgentUnavailable,
)

COMPANY = SimpleNamespace(short_name="acme", id=1)
ENABLED = [{"id": "gpt-default"}, {"id": "claude-fast"}, {"id": "claude-smart"}]


@pytest.fixture
def config():
    config = MagicMock()
    config.sections = {}
    config.get_llm_configuration.return_value = ("gpt-default", ENABLED)
    config.get_configuration.side_effect = lambda company, key: config.sections.get(key)

    def update(company, key, value):
        config.sections[key] = value
        return {}, []

    config.update_configuration_key.side_effect = update

    def remove(company, key):
        config.sections.pop(key, None)
        return {}, []

    config.remove_configuration_key.side_effect = remove
    return config


@pytest.fixture
def llm():
    llm = MagicMock()
    llm.invoke.return_value = {"structured_output": {"items": []}}
    return llm


@pytest.fixture
def runner(llm, config):
    return SystemAgentRunner(llm_client=llm, configuration_service=config)


def review_inputs():
    return {"open_questions": [], "turns": [{"ref": "q1", "question": "¿Horario?", "answer": "No sé"}]}


@pytest.fixture
def platform():
    """The platform's settings per agent key, as a deployment's provider would return them."""
    settings = {}
    SystemAgentRunner.register_platform_settings_provider(lambda key: settings.get(key))
    yield settings
    SystemAgentRunner.register_platform_settings_provider(None)


class TestCatalog:
    def test_core_defines_the_memory_agents_with_a_prompt_and_a_schema(self):
        keys = {agent.key for agent in SystemAgentCatalog.list()}
        assert {"memory_compiler", "memory_correction", "memory_question_review"} <= keys
        for agent in SystemAgentCatalog.list():
            assert agent.prompt_template.strip()
            assert agent.output_schema["type"] == "object"
            assert agent.prompt_name == f"system_agent:{agent.key}"

    def test_a_shared_schema_is_resolved_by_name(self):
        compiler = SystemAgentCatalog.get("memory_compiler")
        correction = SystemAgentCatalog.get("memory_correction")
        assert compiler.output_schema == correction.output_schema
        assert compiler.output_schema["properties"]["target_page_id"]["type"] == ["integer", "null"]

    def test_every_prompt_renders_with_its_declared_inputs(self):
        for agent in SystemAgentCatalog.list():
            inputs = {name: {"id": 1, "title": "t", "markdown": "m"} for name in agent.inputs}
            assert SystemAgentRunner.render_prompt(agent, inputs)

    def test_an_unknown_agent_is_an_error(self):
        with pytest.raises(KeyError):
            SystemAgentCatalog.get("nope")


class TestRun:
    def test_runs_with_the_agent_contract_and_marks_the_execution(self, runner, llm):
        runner.run(COMPANY, "memory_question_review", review_inputs(), user_identifier="service:x", question="Scan")

        kwargs = llm.invoke.call_args.kwargs
        assert kwargs["model"] == "gpt-default"
        assert kwargs["question"] == "Scan"
        assert kwargs["user_identifier"] == "service:x"
        assert kwargs["tools"] == []
        assert kwargs["execution_trace"] == {"prompt_name": "system_agent:memory_question_review"}
        assert kwargs["response_contract"]["response_mode"] == "structured_only"
        assert kwargs["response_contract"]["schema"]["required"] == ["items"]
        # The inputs reach the prompt as JSON, accents untouched.
        assert '"question": "¿Horario?"' in kwargs["context"]

    def test_a_missing_input_fails_before_calling_the_model(self, runner, llm):
        with pytest.raises(ValueError, match="turns"):
            runner.run(COMPANY, "memory_question_review", {"open_questions": []}, user_identifier="service:x")
        llm.invoke.assert_not_called()

    def test_without_any_model_the_agent_is_unavailable(self, runner, config):
        config.get_llm_configuration.return_value = (None, [])
        with pytest.raises(SystemAgentUnavailable):
            runner.run(COMPANY, "memory_question_review", review_inputs(), user_identifier="service:x")

    def test_a_failing_picked_model_is_retried_with_the_company_default(self, runner, llm, config):
        config.sections["system_agents"] = {"memory_question_review": {"model": "claude-fast"}}
        llm.invoke.side_effect = [RuntimeError("provider down"), {"structured_output": {"items": []}}]

        runner.run(COMPANY, "memory_question_review", review_inputs(), user_identifier="service:x")

        assert [call.kwargs["model"] for call in llm.invoke.call_args_list] == ["claude-fast", "gpt-default"]

    def test_the_company_default_failing_is_not_retried(self, runner, llm):
        llm.invoke.side_effect = RuntimeError("provider down")
        with pytest.raises(RuntimeError):
            runner.run(COMPANY, "memory_question_review", review_inputs(), user_identifier="service:x")
        assert llm.invoke.call_count == 1


class TestModelResolution:
    def agent(self):
        return SystemAgentCatalog.get("memory_compiler")

    def test_the_tenant_choice_wins(self, runner, config):
        config.sections["system_agents"] = {"memory_compiler": {"model": "claude-smart"}}
        resolved = runner.resolve_model("acme", self.agent())
        assert (resolved.model, resolved.source) == ("claude-smart", "tenant")

    def test_a_choice_no_longer_enabled_falls_through_to_the_company_default(self, runner, config):
        config.sections["system_agents"] = {"memory_compiler": {"model": "retired-model"}}
        resolved = runner.resolve_model("acme", self.agent())
        assert (resolved.model, resolved.source, resolved.ignored_choice) == ("gpt-default", "company", "retired-model")

    def test_the_catalog_default_comes_before_the_company_default(self, runner):
        resolved = runner.resolve_model("acme", SimpleNamespace(key="memory_compiler", default_model="claude-fast"))
        assert (resolved.model, resolved.source) == ("claude-fast", "catalog")

    def test_without_a_list_of_models_any_choice_is_accepted(self, runner, config):
        config.get_llm_configuration.return_value = ("gpt-default", [])
        config.sections["system_agents"] = {"memory_compiler": {"model": "anything"}}
        assert runner.resolve_model("acme", self.agent()).model == "anything"


class TestTenantChoice:
    def test_picking_and_clearing_a_model_writes_company_yaml(self, runner, config):
        assert runner.set_tenant_choice("acme", "memory_compiler", "claude-smart")["status"] == "success"
        assert config.sections["system_agents"] == {"memory_compiler": {"model": "claude-smart"}}

        assert runner.set_tenant_choice("acme", "memory_compiler", None)["status"] == "success"
        assert "system_agents" not in config.sections

    def test_only_enabled_models_can_be_picked(self, runner, config):
        result = runner.set_tenant_choice("acme", "memory_compiler", "not-enabled")
        assert result["error_code"] == "model_not_enabled"
        config.update_configuration_key.assert_not_called()

    def test_an_unknown_agent_cannot_be_configured(self, runner):
        assert runner.set_tenant_choice("acme", "nope", "claude-smart")["error_code"] == "unknown_agent"

    def test_describe_lists_each_agent_with_its_effective_model(self, runner, config):
        config.sections["system_agents"] = {"memory_compiler": {"model": "claude-smart"}}
        described = {entry["key"]: entry for entry in runner.describe("acme")}
        assert described["memory_compiler"]["effective_model"] == "claude-smart"
        assert described["memory_compiler"]["model_source"] == "tenant"
        assert described["memory_correction"]["effective_model"] == "gpt-default"
        assert described["memory_correction"]["prompt"]


class TestPlatformSettings:
    def test_the_platform_model_comes_after_the_tenant_and_before_the_catalog(self, runner, config, platform):
        platform["memory_compiler"] = PlatformAgentSettings(default_model="claude-fast")
        agent = SystemAgentCatalog.get("memory_compiler")
        assert (runner.resolve_model("acme", agent).model, runner.resolve_model("acme", agent).source) == (
            "claude-fast", "platform")

        config.sections["system_agents"] = {"memory_compiler": {"model": "claude-smart"}}
        assert runner.resolve_model("acme", agent).source == "tenant"

    def test_a_platform_model_the_company_does_not_have_is_skipped(self, runner, platform):
        platform["memory_compiler"] = PlatformAgentSettings(default_model="not-enabled-here")

        resolved = runner.resolve_model("acme", SystemAgentCatalog.get("memory_compiler"))

        assert (resolved.model, resolved.source) == ("gpt-default", "company")
        assert resolved.ignored_platform_model == "not-enabled-here"

    def test_a_disabled_agent_does_not_call_the_model(self, runner, llm, platform):
        platform["memory_question_review"] = PlatformAgentSettings(enabled=False)

        with pytest.raises(SystemAgentDisabled):
            runner.run(COMPANY, "memory_question_review", review_inputs(), user_identifier="service:x")
        llm.invoke.assert_not_called()
        assert issubclass(SystemAgentDisabled, SystemAgentUnavailable)
        assert SystemAgentRunner.is_enabled("memory_question_review") is False
        assert SystemAgentRunner.is_enabled("memory_compiler") is True

    def test_a_provider_that_fails_leaves_the_agents_running(self, runner, llm):
        def broken(key):
            raise RuntimeError("db down")

        SystemAgentRunner.register_platform_settings_provider(broken)
        try:
            runner.run(COMPANY, "memory_question_review", review_inputs(), user_identifier="service:x")
        finally:
            SystemAgentRunner.register_platform_settings_provider(None)
        assert llm.invoke.call_args.kwargs["model"] == "gpt-default"

    def test_describe_tells_the_platform_settings(self, runner, platform):
        platform["memory_correction"] = PlatformAgentSettings(default_model="claude-fast", enabled=False)

        described = {entry["key"]: entry for entry in runner.describe("acme")}

        assert described["memory_correction"]["platform_model"] == "claude-fast"
        assert described["memory_correction"]["enabled"] is False
        assert described["memory_compiler"]["enabled"] is True

