"""Tests for spanforge.schema — JSON Schema validator."""
from __future__ import annotations

import pytest

from spanforge.schema import SchemaValidationError, validate, validate_strict


class TestValidateType:
    def test_string_valid(self):
        assert validate("hello", {"type": "string"}) == []

    def test_string_invalid(self):
        errors = validate(42, {"type": "string"})
        assert len(errors) == 1
        assert "expected type string" in errors[0]
        assert "int" in errors[0]

    def test_number_valid_int(self):
        assert validate(42, {"type": "number"}) == []

    def test_number_valid_float(self):
        assert validate(3.14, {"type": "number"}) == []

    def test_number_invalid(self):
        errors = validate("3.14", {"type": "number"})
        assert errors

    def test_integer_valid(self):
        assert validate(7, {"type": "integer"}) == []

    def test_integer_rejects_float(self):
        errors = validate(7.5, {"type": "integer"})
        assert errors

    def test_integer_rejects_bool(self):
        # bool is subclass of int in Python but not in JSON Schema
        errors = validate(True, {"type": "integer"})
        assert errors

    def test_boolean_valid(self):
        assert validate(True, {"type": "boolean"}) == []
        assert validate(False, {"type": "boolean"}) == []

    def test_boolean_invalid(self):
        errors = validate(1, {"type": "boolean"})
        assert errors

    def test_array_valid(self):
        assert validate([1, 2, 3], {"type": "array"}) == []

    def test_object_valid(self):
        assert validate({"a": 1}, {"type": "object"}) == []

    def test_null_valid(self):
        assert validate(None, {"type": "null"}) == []

    def test_null_invalid(self):
        errors = validate(0, {"type": "null"})
        assert errors


class TestValidateEnum:
    def test_enum_valid(self):
        assert validate("red", {"type": "string", "enum": ["red", "green", "blue"]}) == []

    def test_enum_invalid(self):
        errors = validate("purple", {"enum": ["red", "green", "blue"]})
        assert len(errors) == 1
        assert "not in enum" in errors[0]

    def test_enum_with_null(self):
        assert validate(None, {"enum": [None, "yes"]}) == []


class TestValidateObject:
    def test_required_present(self):
        schema = {"type": "object", "required": ["name", "age"]}
        assert validate({"name": "Alice", "age": 30}, schema) == []

    def test_required_missing(self):
        schema = {"type": "object", "required": ["name", "age"]}
        errors = validate({"name": "Alice"}, schema)
        assert any("age" in e for e in errors)

    def test_nested_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
        }
        assert validate({"score": 0.75}, schema) == []
        errors = validate({"score": "high"}, schema)
        assert errors

    def test_path_in_error_message(self):
        schema = {
            "type": "object",
            "properties": {"child": {"type": "integer"}},
        }
        errors = validate({"child": "not-int"}, schema)
        assert any("$.child" in e for e in errors)

    def test_multiple_missing_required(self):
        schema = {"type": "object", "required": ["a", "b", "c"]}
        errors = validate({}, schema)
        assert len(errors) == 3


class TestValidateArray:
    def test_items_valid(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        assert validate([1, 2, 3], schema) == []

    def test_items_invalid(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        errors = validate([1, "two", 3], schema)
        assert any("[1]" in e for e in errors)

    def test_nested_array_path(self):
        schema = {
            "type": "array",
            "items": {"type": "object", "required": ["id"]},
        }
        errors = validate([{"id": 1}, {}], schema)
        assert any("[1]" in e for e in errors)


class TestValidateNumericBounds:
    def test_minimum_valid(self):
        assert validate(5, {"type": "integer", "minimum": 0}) == []

    def test_minimum_invalid(self):
        errors = validate(-1, {"type": "integer", "minimum": 0})
        assert errors

    def test_maximum_valid(self):
        assert validate(0.5, {"type": "number", "maximum": 1.0}) == []

    def test_maximum_invalid(self):
        errors = validate(1.5, {"type": "number", "maximum": 1.0})
        assert errors

    def test_exact_boundary_allowed(self):
        assert validate(0, {"type": "integer", "minimum": 0, "maximum": 0}) == []


class TestValidateStringLength:
    def test_min_length_valid(self):
        assert validate("abc", {"type": "string", "minLength": 2}) == []

    def test_min_length_invalid(self):
        errors = validate("a", {"type": "string", "minLength": 3})
        assert errors
        assert "minLength" in errors[0]

    def test_max_length_valid(self):
        assert validate("hi", {"type": "string", "maxLength": 10}) == []

    def test_max_length_invalid(self):
        errors = validate("toolongstring", {"type": "string", "maxLength": 5})
        assert errors
        assert "maxLength" in errors[0]


class TestValidatePath:
    def test_custom_root_path(self):
        errors = validate("not-int", {"type": "integer"}, path="$.field")
        assert errors[0].startswith("$.field")

    def test_default_root_path(self):
        errors = validate("not-int", {"type": "integer"})
        assert errors[0].startswith("$")


class TestValidateStrict:
    def test_raises_on_error(self):
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_strict("not-int", {"type": "integer"})
        assert exc_info.value.errors

    def test_no_raise_on_valid(self):
        validate_strict(42, {"type": "integer"})  # should not raise

    def test_error_message_contains_errors(self):
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_strict({}, {"type": "object", "required": ["x", "y"]})
        msg = str(exc_info.value)
        assert "x" in msg or "y" in msg


class TestValidateComplex:
    def test_full_schema(self):
        schema = {
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {
                "answer": {"type": "string", "minLength": 1},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }
        valid = {"answer": "Paris", "confidence": 0.95, "sources": ["wiki", "news"]}
        assert validate(valid, schema) == []

        # Bad confidence type
        errors = validate({"answer": "Paris", "confidence": "high"}, schema)
        assert errors  # missing 'confidence' (required) and type error

    def test_empty_schema_always_valid(self):
        assert validate("anything", {}) == []
        assert validate(42, {}) == []
        assert validate(None, {}) == []
