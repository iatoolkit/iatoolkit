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
