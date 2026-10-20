from iatoolkit.common.model_registry import ModelRegistry


class TestModelRegistry:
    def setup_method(self):
        self.registry = ModelRegistry()

    def test_anthropic_models_resolve_to_anthropic(self):
        assert self.registry.get_provider("claude-3-5-sonnet-latest") == "anthropic"

    def test_openai_models_resolve_to_openai(self):
        assert self.registry.get_provider("gpt-5.2") == "openai"

    def test_the_registry_no_longer_chooses_a_history_strategy(self):
        # Every provider runs on client-side history (BL-009).
        assert not hasattr(self.registry, "get_history_type")
