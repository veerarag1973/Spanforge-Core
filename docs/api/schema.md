# spanforge.schema — JSON Schema validator

> **Module:** `spanforge.schema`  
> **Added in:** 2.0.3

`spanforge.schema` is a lightweight, zero-dependency JSON Schema validator.
It covers the most common subset of JSON Schema keywords and is designed for
validating LLM output payloads and spanforge event fields at runtime.

---

## Quick example

```python
from spanforge.schema import validate, validate_strict, SchemaValidationError

schema = {
    "type": "object",
    "required": ["answer", "confidence"],
    "properties": {
        "answer":     {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "sources":    {"type": "array", "items": {"type": "string"}},
    },
}

# Soft validation — returns a list of error strings
errors = validate({"answer": "Paris", "confidence": 0.95}, schema)
# → []

errors = validate({"answer": "", "confidence": 2.5}, schema)
# → ["$.answer: minLength 1 violated …", "$.confidence: … > maximum 1.0"]

# Strict validation — raises on first failure
try:
    validate_strict(payload, schema)
except SchemaValidationError as exc:
    for err in exc.errors:
        print(err)
```

---

## API

### `validate()`

```python
def validate(
    instance: Any,
    schema: dict,
    path: str = "$",
) -> list[str]: ...
```

Validate *instance* against *schema* and return a (possibly empty) list of
human-readable error strings.  An empty schema `{}` is always valid.

| Parameter | Description |
|-----------|-------------|
| `instance` | The value to validate (dict, list, str, int, …). |
| `schema` | A JSON-Schema-like dict. |
| `path` | JSONPath prefix used in error messages (default `"$"`). |

---

### `validate_strict()`

```python
def validate_strict(
    instance: Any,
    schema: dict,
    path: str = "$",
) -> None: ...
```

Same as `validate()` but raises `SchemaValidationError` if any errors are
found.

---

### `SchemaValidationError`

```python
class SchemaValidationError(ValueError):
    errors: list[str]
```

Raised by `validate_strict()`.  The `errors` attribute contains the full
list of validation error strings.

---

## Supported keywords

| Keyword | Supported values |
|---------|-----------------|
| `type` | `"string"`, `"number"`, `"integer"`, `"boolean"`, `"array"`, `"object"`, `"null"` |
| `enum` | Any list of JSON-compatible values |
| `required` | List of required property names (for `object` types) |
| `properties` | Nested schema per property (for `object` types) |
| `items` | Schema applied to each array element (for `array` types) |
| `minimum` | Inclusive lower bound (for `number`/`integer`) |
| `maximum` | Inclusive upper bound (for `number`/`integer`) |
| `minLength` | Minimum string length (for `string`) |
| `maxLength` | Maximum string length (for `string`) |

> **Note on `boolean` vs `integer`:** Python's `bool` is a subclass of
> `int`, but JSON Schema treats them as distinct types.  `validate()` will
> reject `True`/`False` when the schema type is `"integer"` or `"number"`.
