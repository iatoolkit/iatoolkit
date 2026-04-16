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
