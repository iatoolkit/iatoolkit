from iatoolkit.common.model_registry import ModelRegistry


class TestModelRegistry:
    def setup_method(self):
        self.registry = ModelRegistry()

    def test_anthropic_models_use_client_side_history(self):
        assert self.registry.get_provider("claude-3-5-sonnet-latest") == "anthropic"
        assert self.registry.get_history_type("claude-3-5-sonnet-latest") == "client_side"

    def test_openai_models_keep_server_side_history(self):
        assert self.registry.get_provider("gpt-5.2") == "openai"
        assert self.registry.get_history_type("gpt-5.2") == "server_side"
