from iatoolkit.services.structured_output_service import StructuredOutputService


def test_normalize_schema_from_field_map():
    schema = {
        "customer_id": {"type": "string"},
        "score": {"type": "number"},
    }

    normalized = StructuredOutputService.normalize_schema(schema)

    assert normalized["type"] == "object"
    assert set((normalized.get("properties") or {}).keys()) == {"customer_id", "score"}


def test_evaluate_output_valid_against_schema():
    schema = StructuredOutputService.normalize_schema(
        {
            "type": "object",
            "required": ["customer_id"],
            "properties": {
                "customer_id": {"type": "string"},
                "score": {"type": "number"},
            },
        }
    )

    result = StructuredOutputService.evaluate_output(
        raw_output='{"customer_id": "c-1", "score": 0.97}',
        schema=schema,
    )

    assert result["schema_valid"] is True
    assert result["structured_output"]["customer_id"] == "c-1"


def test_evaluate_output_invalid_against_schema():
    schema = StructuredOutputService.normalize_schema(
        {
            "type": "object",
            "required": ["customer_id"],
            "properties": {
                "customer_id": {"type": "string"},
            },
        }
    )

    result = StructuredOutputService.evaluate_output(
        raw_output='{"score": 123}',
        schema=schema,
    )

    assert result["schema_valid"] is False
    assert result["errors"]


def test_evaluate_output_normalizes_string_enum_variants():
    schema = StructuredOutputService.normalize_schema(
        {
            "type": "object",
            "required": ["primary_statistical_test"],
            "properties": {
                "primary_statistical_test": {
                    "type": ["string", "null"],
                    "enum": [
                        "t_test",
                        "anova",
                        "linear_regression",
                        "other",
                        None,
                    ],
                },
            },
        }
    )

    result = StructuredOutputService.evaluate_output(
        raw_output='{"primary_statistical_test": "t-test"}',
        schema=schema,
    )

    assert result["schema_valid"] is True
    assert result["structured_output"]["primary_statistical_test"] == "t_test"


def test_evaluate_output_normalizes_string_null_to_null_when_allowed():
    schema = StructuredOutputService.normalize_schema(
        {
            "type": "object",
            "required": ["primary_statistical_test"],
            "properties": {
                "primary_statistical_test": {
                    "type": ["string", "null"],
                    "enum": [
                        "t_test",
                        "anova",
                        "other",
                        None,
                    ],
                },
            },
        }
    )

    result = StructuredOutputService.evaluate_output(
        raw_output='{"primary_statistical_test": "null"}',
        schema=schema,
    )

    assert result["schema_valid"] is True
    assert result["structured_output"]["primary_statistical_test"] is None


def test_evaluate_output_can_drop_additional_properties_when_requested():
    schema = StructuredOutputService.normalize_schema(
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["paper_title"],
            "properties": {
                "paper_title": {"type": ["string", "null"]},
            },
        }
    )

    result = StructuredOutputService.evaluate_output(
        raw_output='{"paper_title":"Study title","other":"noise"}',
        schema=schema,
        drop_additional_properties=True,
    )

    assert result["schema_valid"] is True
    assert result["structured_output"] == {"paper_title": "Study title"}


# --- strict provider schemas -------------------------------------------------

_CONTRACT_SCHEMA = {
    "type": "object",
    "required": ["customer_id", "lines"],
    "properties": {
        "customer_id": {"type": "string"},
        "segment": {"type": "string", "enum": ["pyme", "corporate"]},
        "note": {"type": ["string", "null"]},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["sku"],
                "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}},
            },
        },
        "extra": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}


def test_to_strict_schema_closes_objects_and_makes_optional_fields_nullable():
    strict = StructuredOutputService.to_strict_schema(_CONTRACT_SCHEMA)

    assert strict["additionalProperties"] is False
    assert strict["required"] == ["customer_id", "segment", "note", "lines", "extra"]
    assert strict["properties"]["customer_id"] == {"type": "string"}  # required: unchanged
    assert strict["properties"]["segment"] == {"type": ["string", "null"], "enum": ["pyme", "corporate", None]}
    assert strict["properties"]["note"] == {"type": ["string", "null"]}  # already nullable
    item = strict["properties"]["lines"]["items"]
    assert item["required"] == ["sku", "qty"] and item["additionalProperties"] is False
    assert item["properties"]["qty"] == {"type": ["integer", "null"]}
    # A map cannot be closed: it is left as written.
    assert strict["properties"]["extra"]["additionalProperties"] == {"type": "string"}


def test_to_strict_schema_returns_a_copy():
    StructuredOutputService.to_strict_schema(_CONTRACT_SCHEMA)

    assert _CONTRACT_SCHEMA["required"] == ["customer_id", "lines"]
    assert "additionalProperties" not in _CONTRACT_SCHEMA


def test_to_strict_schema_adds_a_null_option_to_an_optional_any_of():
    schema = {"type": "object", "properties": {"v": {"anyOf": [{"type": "string"}, {"type": "number"}]}}}

    strict = StructuredOutputService.to_strict_schema(schema)

    assert strict["properties"]["v"]["anyOf"][-1] == {"type": "null"}


def test_strict_answer_maps_back_to_the_stored_schema():
    """What a strict provider returns for absent optional fields - nulls - is
    turned back into absent, and the result validates against the original."""
    answer = {
        "customer_id": "c-1",
        "segment": None,
        "note": None,
        "lines": [{"sku": "A", "qty": None}],
        "extra": None,
    }

    result = StructuredOutputService.evaluate_output(answer, _CONTRACT_SCHEMA, drop_optional_nulls=True)

    assert result["schema_valid"] is True, result["errors"]
    assert result["structured_output"] == {
        "customer_id": "c-1",
        "note": None,  # nullable in the stored schema: its null is a real value
        "lines": [{"sku": "A"}],
    }


def test_without_the_flag_the_same_answer_fails_the_stored_schema():
    answer = {"customer_id": "c-1", "segment": None, "lines": []}

    result = StructuredOutputService.evaluate_output(answer, _CONTRACT_SCHEMA)

    assert result["schema_valid"] is False


def test_a_null_required_field_is_still_an_error():
    answer = {"customer_id": None, "lines": []}

    result = StructuredOutputService.evaluate_output(answer, _CONTRACT_SCHEMA, drop_optional_nulls=True)

    assert result["schema_valid"] is False
