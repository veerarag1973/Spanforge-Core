"""spanforge.schema — Lightweight JSON Schema validator.

Provides :func:`validate`, a zero-dependency validator that supports the most
commonly needed JSON Schema keywords: ``type``, ``required``, ``properties``,
``items``, ``enum``, ``minimum``, ``maximum``, ``minLength``, and
``maxLength``.  It returns a list of human-readable error strings (empty list
= valid), making it easy to surface schema violations in log messages or
CI output without throwing exceptions.

Intended for validating structured LLM output (e.g. function-calling
responses, JSON-mode completions) anywhere in the spanforge ecosystem.

Usage::

    from spanforge.schema import validate

    schema = {
        "type": "object",
        "required": ["answer", "confidence"],
        "properties": {
            "answer": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }

    errors = validate({"answer": "Paris", "confidence": 0.95}, schema)
    assert errors == []

    errors = validate({"answer": 42}, schema)
    # errors == ["$.answer: expected type string, got int",
    #            "$: missing required property 'confidence'"]
"""

from __future__ import annotations

from typing import Any

__all__ = ["SchemaValidationError", "validate"]


class SchemaValidationError(ValueError):
    """Raised by :func:`validate_strict` when validation fails.

    Attributes:
        errors:  The list of error strings from :func:`validate`.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


# JSON Schema "type" → Python type(s) mapping
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def validate(
    instance: Any,
    schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Validate *instance* against a JSON Schema subset.

    Supported keywords
    ------------------
    * ``type`` — ``"string"``, ``"number"``, ``"integer"``, ``"boolean"``,
      ``"array"``, ``"object"``, ``"null"``
    * ``enum`` — list of allowed values
    * ``required`` — list of required property names (objects only)
    * ``properties`` — sub-schema per property name (objects only)
    * ``items`` — sub-schema for every array element (arrays only)
    * ``minimum`` / ``maximum`` — inclusive bounds (numbers only)
    * ``minLength`` / ``maxLength`` — length bounds (strings only)

    Args:
        instance:  The Python value to validate.
        schema:    A JSON Schema dict (subset supported as described above).
        path:      JSONPath-style prefix used in error messages.  Defaults to
                   ``"$"`` (document root).  Recursive calls set sub-paths
                   automatically; callers usually leave this as default.

    Returns:
        A list of error strings.  An empty list means the instance is valid.

    Example::

        errors = validate("hello", {"type": "string", "minLength": 3})
        assert errors == []

        errors = validate(2, {"type": "string"})
        assert errors == ["$: expected type string, got int"]
    """
    errors: list[str] = []
    schema_type = schema.get("type")

    # --- type check ---
    if schema_type is not None:
        expected = _TYPE_MAP.get(schema_type)
        if expected is not None:
            # Special case: bool is a subclass of int in Python, but JSON
            # Schema treats them as distinct types.  Check bool BEFORE the
            # isinstance() call because isinstance(True, int) is True.
            if isinstance(instance, bool) and schema_type in ("integer", "number"):
                errors.append(f"{path}: expected type {schema_type}, got bool")
                return errors  # type mismatch; sub-checks meaningless
            if not isinstance(instance, expected):
                errors.append(f"{path}: expected type {schema_type}, got {type(instance).__name__}")
                return errors  # type mismatch; sub-checks are meaningless

    # --- enum check ---
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} not in enum {schema['enum']!r}")

    # --- object checks ---
    if schema_type == "object" and isinstance(instance, dict):
        errors.extend(
            f"{path}: missing required property {key!r}"
            for key in schema.get("required", [])
            if key not in instance
        )
        for key, sub_schema in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(validate(instance[key], sub_schema, f"{path}.{key}"))

    # --- array checks ---
    if schema_type == "array" and isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema is not None:
            for i, item in enumerate(instance):
                errors.extend(validate(item, items_schema, f"{path}[{i}]"))

    # --- numeric bounds ---
    if (
        schema_type in ("number", "integer")
        and isinstance(instance, (int, float))
        and not isinstance(instance, bool)
    ):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} is less than minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} is greater than maximum {schema['maximum']}")

    # --- string length ---
    if schema_type == "string" and isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(
                f"{path}: string length {len(instance)} is less than "
                f"minLength {schema['minLength']}"
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(
                f"{path}: string length {len(instance)} exceeds maxLength {schema['maxLength']}"
            )

    return errors


def validate_strict(
    instance: Any,
    schema: dict[str, Any],
    path: str = "$",
) -> None:
    """Like :func:`validate` but raises :class:`SchemaValidationError` on failure.

    Args:
        instance:  The value to validate.
        schema:    JSON Schema dict.
        path:      Starting path prefix (default ``"$"``).

    Raises:
        SchemaValidationError: When :func:`validate` returns any errors.
    """
    errors = validate(instance, schema, path)
    if errors:
        raise SchemaValidationError(errors)
