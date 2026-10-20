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


class TestCatalogCapabilities:
    """Capabilities narrowed by what the model catalogue says (BL-009, Fase F)."""

    def setup_method(self):
        from iatoolkit.common.model_registry import ModelRegistry

        self.registry = ModelRegistry()

    def test_without_catalogue_data_the_provider_decides(self):
        caps = self.registry.get_capabilities("gpt-4.1", provider="openai")

        assert caps["supports_reasoning_effort"] is True
        assert caps["capabilities_source"] == "provider"
        assert "supports_store" not in caps

    def test_a_model_that_does_not_declare_reasoning_offers_no_effort(self):
        caps = self.registry.get_capabilities(
            "gpt-4.1", provider="openai", capabilities={"supported_parameters": ["tools", "response_format"]},
        )

        assert caps["supports_reasoning_effort"] is False
        assert caps["allowed_reasoning_efforts"] == []
        assert caps["supports_text_verbosity"] is False
        assert caps["capabilities_source"] == "catalog"

    def test_the_catalogue_never_widens_what_the_adapter_sends(self):
        # The openai_compatible adapter forwards no reasoning field.
        caps = self.registry.get_capabilities(
            "local-model", provider="openai_compatible", capabilities={"supported_parameters": ["reasoning"]},
        )

        assert caps["supports_reasoning_effort"] is False

    def test_catalog_capabilities_reads_the_model_configuration(self):
        from iatoolkit.common.model_registry import ModelRegistry

        assert ModelRegistry.catalog_capabilities(None) is None
        assert ModelRegistry.catalog_capabilities({"capabilities": {}}) is None
        assert ModelRegistry.catalog_capabilities({"capabilities": {"input_modalities": ["text"]}}) == {
            "input_modalities": ["text"]
        }
