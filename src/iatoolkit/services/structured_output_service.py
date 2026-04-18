# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

import html
import json
import re
from typing import Any

import yaml


class StructuredOutputService:
    """Helpers for prompt output schema parsing, normalization and validation."""

    _SCHEMA_KEYWORDS = {
        "type",
        "properties",
        "fields",
        "required",
        "items",
        "enum",
        "anyOf",
        "oneOf",
        "allOf",
        "$ref",
        "format",
        "nullable",
        "additionalProperties",
        "description",
        "title",
        "default",
        "examples",
    }

    _TYPE_MAP = {
        "str": "string",
        "string": "string",
        "text": "string",
        "int": "integer",
        "integer": "integer",
        "float": "number",
        "double": "number",
        "decimal": "number",
        "number": "number",
        "bool": "boolean",
        "boolean": "boolean",
        "dict": "object",
        "map": "object",
        "json": "object",
        "jsonb": "object",
        "object": "object",
        "list": "array",
        "array": "array",
    }

    @classmethod
    def parse_yaml_schema(cls, yaml_content: str | None) -> dict | None:
        text = (yaml_content or "").strip()
        if not text:
            return None

        parsed = yaml.safe_load(text)
        if parsed is None:
            return None
        if not isinstance(parsed, dict):
            raise ValueError("output_schema_yaml must be a YAML object.")
        return parsed

    @classmethod
    def dump_yaml_schema(cls, schema: dict | None) -> str | None:
        if schema is None:
            return None
        return yaml.safe_dump(schema, sort_keys=False, allow_unicode=True)

    @classmethod
    def normalize_schema(cls, raw_schema: dict | None) -> dict | None:
        if raw_schema is None:
            return None
        if not isinstance(raw_schema, dict):
            raise ValueError("output schema must be an object.")

        schema = dict(raw_schema)
        if cls._looks_like_fields_map(schema):
            schema = {
                "type": "object",
                "properties": schema,
            }
        elif isinstance(schema.get("fields"), dict):
            schema = dict(schema)
            schema["type"] = str(schema.get("type") or "object").lower()
            schema["properties"] = schema.get("fields") or {}
            schema.pop("fields", None)

        normalized = cls._normalize_schema_node(schema, path="$")
        cls.validate_schema_contract(normalized)
        return normalized

    @classmethod
    def validate_schema_contract(cls, schema: dict | None):
        if schema is None:
            return
        if not isinstance(schema, dict):
            raise ValueError("output schema must be an object.")

        root_type = schema.get("type")
        if isinstance(root_type, list):
            if "object" not in root_type:
                raise ValueError("Root output schema must include type 'object'.")
        elif root_type != "object":
            raise ValueError("Root output schema must be type 'object'.")

        max_depth = 14
        max_nodes = 1000
        depth = cls._schema_depth(schema)
        if depth > max_depth:
            raise ValueError(f"output schema depth exceeds limit ({max_depth}).")
        nodes = cls._count_schema_nodes(schema)
        if nodes > max_nodes:
            raise ValueError(f"output schema node count exceeds limit ({max_nodes}).")

    @classmethod
    def evaluate_output(
        cls,
        raw_output: Any,
        schema: dict | None,
    ) -> dict:
        if not schema:
            return {
                "schema_present": False,
                "schema_valid": True,
                "structured_output": None,
                "errors": [],
            }

        candidate, parse_error = cls.extract_json_candidate(raw_output)
        if parse_error:
            return {
                "schema_present": True,
                "schema_valid": False,
                "structured_output": None,
                "errors": [parse_error],
            }

        candidate = cls.normalize_instance(candidate, schema)
        errors = cls.validate_instance(candidate, schema, path="$")
        return {
            "schema_present": True,
            "schema_valid": len(errors) == 0,
            "structured_output": candidate if len(errors) == 0 else None,
            "errors": errors,
        }

    @classmethod
    def extract_json_candidate(cls, raw_output: Any) -> tuple[Any | None, str | None]:
        if isinstance(raw_output, (dict, list)):
            return raw_output, None

        if raw_output is None:
            return None, "Empty output: expected JSON object."
        if not isinstance(raw_output, str):
            return None, f"Unsupported output type '{type(raw_output)}': expected JSON text."

        text = raw_output.strip()
        if not text:
            return None, "Empty output: expected JSON object."

        # Remove full-line JS comments sometimes produced by models.
        text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE).strip()
        text = cls._strip_fenced_json(text)

        try:
            return json.loads(text), None
        except Exception:
            pass

        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start == -1 or end == -1 or end <= start:
                continue

            snippet = text[start:end + 1]
            try:
                return json.loads(snippet), None
            except Exception:
                continue

        return None, "The model output is not valid JSON."

    @classmethod
    def validate_instance(cls, instance: Any, schema: dict, path: str = "$") -> list[str]:
        if not isinstance(schema, dict):
            return [f"{path}: invalid schema node."]

        errors: list[str] = []
        schema_type = schema.get("type")
        nullable = bool(schema.get("nullable", False))

        if instance is None:
            if nullable or cls._allows_null(schema_type):
                return []
            return [f"{path}: value is null but schema does not allow null."]

        any_of = schema.get("anyOf")
        if isinstance(any_of, list) and any_of:
            if not cls._matches_any(instance, any_of, path):
                errors.append(f"{path}: value does not match anyOf schemas.")
            return errors

        one_of = schema.get("oneOf")
        if isinstance(one_of, list) and one_of:
            match_count = cls._count_matches(instance, one_of, path)
            if match_count != 1:
                errors.append(f"{path}: value must match exactly one schema in oneOf.")
            return errors

        if not cls._matches_type(instance, schema_type):
            expected = schema_type if schema_type is not None else "any"
            errors.append(f"{path}: expected type '{expected}', got '{type(instance).__name__}'.")
            return errors

        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values and instance not in enum_values:
            errors.append(f"{path}: value {instance!r} is not in enum set {enum_values}.")

        if cls._is_type(schema_type, "string"):
            fmt = str(schema.get("format") or "").lower()
            if fmt == "date" and not cls._is_iso_date(instance):
                errors.append(f"{path}: expected ISO date string (YYYY-MM-DD).")

        if cls._is_type(schema_type, "object"):
            if not isinstance(instance, dict):
                errors.append(f"{path}: expected object.")
                return errors

            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required = schema.get("required")
            if isinstance(required, list):
                for field in required:
                    if isinstance(field, str) and field not in instance:
                        errors.append(f"{path}.{field}: is required.")

            additional = schema.get("additionalProperties", True)
            for key, value in instance.items():
                child_path = f"{path}.{key}"
                if key in properties:
                    errors.extend(cls.validate_instance(value, properties[key], path=child_path))
                    continue

                if additional is False:
                    errors.append(f"{child_path}: additional property is not allowed.")
                    continue

                if isinstance(additional, dict):
                    errors.extend(cls.validate_instance(value, additional, path=child_path))

        if cls._is_type(schema_type, "array"):
            if not isinstance(instance, list):
                errors.append(f"{path}: expected array.")
                return errors
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(instance):
                    errors.extend(cls.validate_instance(item, item_schema, path=f"{path}[{index}]"))

        return errors

    @classmethod
    def normalize_instance(cls, instance: Any, schema: dict | None) -> Any:
        if not isinstance(schema, dict):
            return instance

        if instance is None:
            return None

        schema_type = schema.get("type")
        nullable = bool(schema.get("nullable", False)) or cls._allows_null(schema_type)

        if isinstance(instance, str):
            stripped = instance.strip()
            if nullable and stripped.lower() in {"null", "none"}:
                return None
            instance = stripped

        if cls._is_type(schema_type, "object") and isinstance(instance, dict):
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            additional = schema.get("additionalProperties", True)
            normalized_object: dict[str, Any] = {}

            for key, value in instance.items():
                child_schema = properties.get(key)
                if isinstance(child_schema, dict):
                    normalized_object[key] = cls.normalize_instance(value, child_schema)
                elif isinstance(additional, dict):
                    normalized_object[key] = cls.normalize_instance(value, additional)
                else:
                    normalized_object[key] = value.strip() if isinstance(value, str) else value

            return normalized_object

        if cls._is_type(schema_type, "array") and isinstance(instance, list):
            item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
            if item_schema is None:
                return [item.strip() if isinstance(item, str) else item for item in instance]
            return [cls.normalize_instance(item, item_schema) for item in instance]

        enum_values = schema.get("enum")
        if isinstance(instance, str) and isinstance(enum_values, list) and enum_values:
            normalized_enum = cls._normalize_string_enum_value(instance, enum_values)
            if normalized_enum is not None:
                return normalized_enum

        return instance

    @classmethod
    def render_structured_output_as_html(cls, value: Any) -> str:
        pretty = json.dumps(value, ensure_ascii=False, indent=2)
        escaped = html.escape(pretty)
        return f"<pre class='mb-0'><code>{escaped}</code></pre>"

    @classmethod
    def _strip_fenced_json(cls, text: str) -> str:
        candidate = text.strip()
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
        return candidate.strip()

    @classmethod
    def _normalize_schema_node(cls, node: dict, path: str) -> dict:
        if not isinstance(node, dict):
            raise ValueError(f"{path}: schema node must be an object.")

        normalized = dict(node)

        # Legacy alias
        if "fields" in normalized and "properties" not in normalized and isinstance(normalized["fields"], dict):
            normalized["properties"] = normalized.pop("fields")

        normalized_type = cls._normalize_type_value(normalized.get("type"), path=path)
        if normalized_type is not None:
            normalized["type"] = normalized_type

        # Convert date pseudo-type into JSON Schema.
        if normalized.get("type") == "date":
            normalized["type"] = "string"
            normalized.setdefault("format", "date")

        properties = normalized.get("properties")
        if isinstance(properties, dict):
            normalized_properties = {}
            for key, child in properties.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(f"{path}: property keys must be non-empty strings.")
                normalized_properties[key] = cls._normalize_schema_node(child, path=f"{path}.properties.{key}")
            normalized["properties"] = normalized_properties
            if "type" not in normalized:
                normalized["type"] = "object"

        if normalized.get("type") == "object" and "properties" not in normalized:
            normalized["properties"] = {}

        if normalized.get("type") == "array" and "properties" in normalized and "items" not in normalized:
            # Legacy shorthand where array node has direct properties.
            props = normalized.pop("properties")
            normalized["items"] = {"type": "object", "properties": props}

        items = normalized.get("items")
        if isinstance(items, dict):
            normalized["items"] = cls._normalize_schema_node(items, path=f"{path}.items")

        required = normalized.get("required")
        if required is not None:
            if not isinstance(required, list):
                raise ValueError(f"{path}.required must be a list of property names.")
            normalized["required"] = [item for item in required if isinstance(item, str) and item.strip()]

        additional = normalized.get("additionalProperties")
        if isinstance(additional, dict):
            normalized["additionalProperties"] = cls._normalize_schema_node(
                additional, path=f"{path}.additionalProperties"
            )

        for key in ("anyOf", "oneOf"):
            candidates = normalized.get(key)
            if candidates is None:
                continue
            if not isinstance(candidates, list):
                raise ValueError(f"{path}.{key} must be a list.")
            normalized[key] = [
                cls._normalize_schema_node(candidate, path=f"{path}.{key}[{index}]")
                for index, candidate in enumerate(candidates)
                if isinstance(candidate, dict)
            ]

        return normalized

    @classmethod
    def _normalize_type_value(cls, type_value: Any, path: str) -> str | list[str] | None:
        if type_value is None:
            return None

        if isinstance(type_value, str):
            lowered = type_value.strip().lower()
            mapped = cls._TYPE_MAP.get(lowered, lowered)
            return mapped

        if isinstance(type_value, list):
            normalized_types: list[str] = []
            for item in type_value:
                if not isinstance(item, str):
                    raise ValueError(f"{path}.type list only supports string values.")
                lowered = item.strip().lower()
                mapped = cls._TYPE_MAP.get(lowered, lowered)
                if mapped not in normalized_types:
                    normalized_types.append(mapped)
            return normalized_types

        raise ValueError(f"{path}.type must be a string or list of strings.")

    @classmethod
    def _looks_like_fields_map(cls, schema: dict) -> bool:
        if not schema:
            return False
        if any(key in cls._SCHEMA_KEYWORDS for key in schema.keys()):
            return False
        for value in schema.values():
            if not isinstance(value, dict):
                return False
        return True

    @classmethod
    def _schema_depth(cls, schema: dict, current_depth: int = 1) -> int:
        children = []
        props = schema.get("properties")
        if isinstance(props, dict):
            children.extend(props.values())

        items = schema.get("items")
        if isinstance(items, dict):
            children.append(items)

        for key in ("anyOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list):
                children.extend([item for item in options if isinstance(item, dict)])

        if not children:
            return current_depth
        return max(cls._schema_depth(child, current_depth + 1) for child in children)

    @classmethod
    def _count_schema_nodes(cls, schema: dict) -> int:
        count = 1
        props = schema.get("properties")
        if isinstance(props, dict):
            for child in props.values():
                if isinstance(child, dict):
                    count += cls._count_schema_nodes(child)

        items = schema.get("items")
        if isinstance(items, dict):
            count += cls._count_schema_nodes(items)

        for key in ("anyOf", "oneOf"):
            options = schema.get(key)
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict):
                        count += cls._count_schema_nodes(option)

        return count

    @classmethod
    def _allows_null(cls, schema_type: Any) -> bool:
        if isinstance(schema_type, list):
            return "null" in schema_type
        return schema_type == "null"

    @classmethod
    def _matches_any(cls, instance: Any, schemas: list[dict], path: str) -> bool:
        for schema in schemas:
            if not isinstance(schema, dict):
                continue
            if not cls.validate_instance(instance, schema, path=path):
                return True
        return False

    @classmethod
    def _count_matches(cls, instance: Any, schemas: list[dict], path: str) -> int:
        count = 0
        for schema in schemas:
            if not isinstance(schema, dict):
                continue
            if not cls.validate_instance(instance, schema, path=path):
                count += 1
        return count

    @classmethod
    def _is_type(cls, schema_type: Any, expected: str) -> bool:
        if schema_type is None:
            return False
        if isinstance(schema_type, list):
            return expected in schema_type
        return schema_type == expected

    @classmethod
    def _matches_type(cls, instance: Any, schema_type: Any) -> bool:
        if schema_type is None:
            return True

        allowed_types = schema_type if isinstance(schema_type, list) else [schema_type]
        for expected in allowed_types:
            if expected == "null":
                if instance is None:
                    return True
            elif expected == "object" and isinstance(instance, dict):
                return True
            elif expected == "array" and isinstance(instance, list):
                return True
            elif expected == "string" and isinstance(instance, str):
                return True
            elif expected == "integer" and isinstance(instance, int) and not isinstance(instance, bool):
                return True
            elif expected == "number" and (
                (isinstance(instance, int) and not isinstance(instance, bool)) or isinstance(instance, float)
            ):
                return True
            elif expected == "boolean" and isinstance(instance, bool):
                return True
        return False

    @classmethod
    def _is_iso_date(cls, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value.strip()))

    @classmethod
    def _normalize_string_enum_value(cls, instance: str, enum_values: list[Any]) -> Any | None:
        string_values = [item for item in enum_values if isinstance(item, str)]
        if not string_values:
            return None

        if instance in string_values:
            return instance

        lowered = instance.lower()
        lowered_matches = [item for item in string_values if item.lower() == lowered]
        if len(lowered_matches) == 1:
            return lowered_matches[0]

        canonical_instance = cls._canonicalize_enum_token(instance)
        canonical_matches = [
            item for item in string_values
            if cls._canonicalize_enum_token(item) == canonical_instance
        ]
        if len(canonical_matches) == 1:
            return canonical_matches[0]

        return None

    @staticmethod
    def _canonicalize_enum_token(value: str) -> str:
        lowered = value.strip().lower()
        lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
        lowered = re.sub(r"_+", "_", lowered)
        return lowered.strip("_")
