# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from iatoolkit.repositories.models import ModelBillingPolicy


class TestWhatEachPolicyMeans:

    def test_a_metered_model_needs_a_price_before_it_is_offered(self):
        assert ModelBillingPolicy.metered.requires_rate_card is True

    def test_a_model_that_costs_nothing_to_serve_does_not(self):
        # A local model, a self-hosted HuggingFace endpoint, the customer's own
        # gateway: no provider bills IAToolkit per token, so there is nothing to
        # price and requiring a rate card would only block the model.
        assert ModelBillingPolicy.not_billable.requires_rate_card is False

    def test_it_is_a_string_enum_so_the_stored_value_is_the_name(self):
        assert ModelBillingPolicy.not_billable == "not_billable"


class TestReadingAStoredValue:
    """parse() reads data; it never decides policy."""

    def test_the_two_known_values_round_trip(self):
        for policy in ModelBillingPolicy:
            assert ModelBillingPolicy.parse(policy.value) is policy

    def test_case_and_padding_are_tolerated(self):
        assert ModelBillingPolicy.parse("  NOT_BILLABLE ") is ModelBillingPolicy.not_billable

    def test_an_enum_member_parses_to_itself(self):
        assert ModelBillingPolicy.parse(ModelBillingPolicy.metered) is ModelBillingPolicy.metered

    def test_an_unknown_value_reads_as_metered(self):
        # Keeping the rate card requirement is recoverable. Treating a paid model
        # as free is consumption nobody charged for, and it surfaces a month
        # later at the close.
        assert ModelBillingPolicy.parse("free") is ModelBillingPolicy.metered

    def test_an_empty_or_missing_value_reads_as_metered(self):
        for raw in (None, "", "   "):
            assert ModelBillingPolicy.parse(raw) is ModelBillingPolicy.metered
