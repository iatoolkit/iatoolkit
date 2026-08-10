from types import SimpleNamespace

import pytest

from iatoolkit.repositories.models import ServiceModel


class TestServiceModelQuestions:
    """The two questions live with the values so a new member cannot skip them."""

    @pytest.mark.parametrize(
        "member,billable,support",
        [
            (ServiceModel.internal, False, False),
            (ServiceModel.hosted, True, True),
            # Billed on the operator's platform, but their deployment is
            # elsewhere: a case filed there lands in their own database.
            (ServiceModel.self_hosted, True, False),
        ],
    )
    def test_each_member_answers_both(self, member, billable, support):
        assert member.is_billable is billable
        assert member.offers_support is support

    def test_every_member_is_covered_by_this_test(self):
        # Adding a member without extending the table above fails here rather
        # than silently defaulting to "no" wherever someone reads it.
        assert {m.value for m in ServiceModel} == {"internal", "hosted", "self_hosted"}


class TestParsing:

    @pytest.mark.parametrize("raw", [None, "", "   ", "unknown", "HOSTED_X", 0])
    def test_anything_unrecognised_is_internal(self, raw):
        # The restrictive direction: not billing someone by mistake is
        # recoverable, billing them is not.
        assert ServiceModel.parse(raw) is ServiceModel.internal

    @pytest.mark.parametrize("raw", ["hosted", "  Hosted ", "HOSTED"])
    def test_case_and_whitespace_do_not_matter(self, raw):
        assert ServiceModel.parse(raw) is ServiceModel.hosted

    def test_an_enum_like_value_is_unwrapped(self):
        assert ServiceModel.parse(SimpleNamespace(value="self_hosted")) is ServiceModel.self_hosted

    def test_a_member_parses_to_itself(self):
        assert ServiceModel.parse(ServiceModel.self_hosted) is ServiceModel.self_hosted


class TestReadingACompany:

    def test_reads_the_column_off_a_company(self):
        assert ServiceModel.of(SimpleNamespace(service_model="hosted")) is ServiceModel.hosted

    def test_a_company_without_the_column_is_internal(self):
        # An older row, or an object that never had the attribute.
        assert ServiceModel.of(SimpleNamespace()) is ServiceModel.internal

    def test_a_null_column_is_internal(self):
        assert ServiceModel.of(SimpleNamespace(service_model=None)) is ServiceModel.internal


class TestComparisonHabits:

    def test_the_value_is_still_a_plain_string(self):
        # str-backed so it can be written to the column and rendered without
        # callers reaching for `.value` everywhere.
        assert ServiceModel.hosted == "hosted"
        assert f"{ServiceModel.hosted.value}" == "hosted"
