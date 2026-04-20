"""tests/test_prompt_registry.py — Unit tests for spanforge.prompt_registry (F-45).

Covers PromptVersion and PromptRegistry: registration, versioning, rendering,
missing-variable errors, list helpers, serialisation round-trip, and the
module-level convenience functions.
"""

from __future__ import annotations

import time
import unittest

from spanforge.prompt_registry import (
    PromptRegistry,
    PromptVersion,
    get_prompt_version,
    register_prompt,
    render_prompt,
)


# ===========================================================================
# Section 1 — PromptVersion
# ===========================================================================

class TestPromptVersion(unittest.TestCase):

    def _make_pv(self, template="Hello, {name}!", version="1.0.0"):
        variables = [m.strip("{}") for m in ["name"] if "{name}" in template]
        return PromptVersion(
            name="greet",
            template=template,
            version=version,
            variables=variables,
        )

    def test_render_substitutes_variables(self):
        pv = PromptVersion(
            name="greet",
            template="Hello, {name}!",
            version="1.0.0",
            variables=["name"],
        )
        self.assertEqual(pv.render({"name": "Alice"}), "Hello, Alice!")

    def test_render_raises_on_missing_variable(self):
        pv = PromptVersion(
            name="greet",
            template="Hello, {name}!",
            version="1.0.0",
            variables=["name"],
        )
        with self.assertRaises(KeyError):
            pv.render({})

    def test_render_ignores_extra_variables(self):
        pv = PromptVersion(
            name="greet",
            template="Hello, {name}!",
            version="1.0.0",
            variables=["name"],
        )
        # Extra keys are OK — Python's str.format ignores them.
        result = pv.render({"name": "Bob", "extra": "ignored"})
        self.assertEqual(result, "Hello, Bob!")

    def test_to_dict_round_trip(self):
        pv = PromptVersion(
            name="sys",
            template="You are {role}.",
            version="2.0.0",
            variables=["role"],
            metadata={"author": "test"},
        )
        d = pv.to_dict()
        restored = PromptVersion.from_dict(d)
        self.assertEqual(restored.name, pv.name)
        self.assertEqual(restored.template, pv.template)
        self.assertEqual(restored.version, pv.version)
        self.assertEqual(restored.variables, pv.variables)
        self.assertEqual(restored.metadata, pv.metadata)

    def test_from_dict_defaults_missing_fields(self):
        d = {"name": "x", "template": "hi", "version": "0.1.0"}
        pv = PromptVersion.from_dict(d)
        self.assertEqual(pv.variables, [])
        self.assertIsNone(pv.metadata)


# ===========================================================================
# Section 2 — PromptRegistry.register
# ===========================================================================

class TestPromptRegistryRegister(unittest.TestCase):

    def setUp(self):
        self.registry = PromptRegistry()

    def test_register_returns_prompt_version(self):
        pv = self.registry.register("greet", "Hello, {name}!", version="1.0.0")
        self.assertIsInstance(pv, PromptVersion)

    def test_register_extracts_variables(self):
        pv = self.registry.register("tmpl", "{a} and {b}", version="1.0.0")
        self.assertIn("a", pv.variables)
        self.assertIn("b", pv.variables)

    def test_register_latest_is_most_recent(self):
        self.registry.register("sys", "v1 {role}", version="1.0.0")
        self.registry.register("sys", "v2 {role}", version="2.0.0")
        pv = self.registry.get("sys")
        self.assertEqual(pv.version, "2.0.0")

    def test_register_allows_multiple_versions(self):
        self.registry.register("t", "first {x}", version="1.0.0")
        self.registry.register("t", "second {x}", version="1.1.0")
        pv_old = self.registry.get("t", version="1.0.0")
        pv_new = self.registry.get("t", version="1.1.0")
        self.assertEqual(pv_old.template, "first {x}")
        self.assertEqual(pv_new.template, "second {x}")


# ===========================================================================
# Section 3 — PromptRegistry.get / list helpers
# ===========================================================================

class TestPromptRegistryGet(unittest.TestCase):

    def setUp(self):
        self.registry = PromptRegistry()
        self.registry.register("p", "hello {name}", version="1.0.0")
        self.registry.register("p", "hi {name}", version="2.0.0")

    def test_get_latest_by_default(self):
        pv = self.registry.get("p")
        self.assertEqual(pv.version, "2.0.0")

    def test_get_specific_version(self):
        pv = self.registry.get("p", version="1.0.0")
        self.assertEqual(pv.template, "hello {name}")

    def test_get_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            self.registry.get("nonexistent")

    def test_get_unknown_version_raises(self):
        with self.assertRaises(KeyError):
            self.registry.get("p", version="99.99.99")

    def test_list_versions(self):
        versions = self.registry.list_versions("p")
        self.assertIn("1.0.0", versions)
        self.assertIn("2.0.0", versions)

    def test_list_versions_unknown_raises(self):
        with self.assertRaises(KeyError):
            self.registry.list_versions("does_not_exist")

    def test_list_names(self):
        self.registry.register("q", "other {x}", version="1.0.0")
        names = self.registry.list_names()
        self.assertIn("p", names)
        self.assertIn("q", names)


# ===========================================================================
# Section 4 — PromptRegistry.render
# ===========================================================================

class TestPromptRegistryRender(unittest.TestCase):

    def setUp(self):
        self.registry = PromptRegistry()
        self.registry.register("greet", "Hello, {name}! You are {role}.", version="1.0.0")

    def test_render_returns_string(self):
        result = self.registry.render("greet", {"name": "Alice", "role": "admin"})
        self.assertEqual(result, "Hello, Alice! You are admin.")

    def test_render_specific_version(self):
        self.registry.register("greet", "Hi {name}!", version="2.0.0")
        result = self.registry.render("greet", {"name": "Bob"}, version="2.0.0")
        self.assertEqual(result, "Hi Bob!")

    def test_render_missing_variable_raises(self):
        with self.assertRaises(KeyError):
            self.registry.render("greet", {"name": "Alice"})  # missing 'role'

    def test_render_unknown_prompt_raises(self):
        with self.assertRaises(KeyError):
            self.registry.render("no_such_prompt", {})

    def test_render_no_variables(self):
        self.registry.register("static", "Static response.", version="1.0.0")
        result = self.registry.render("static", {})
        self.assertEqual(result, "Static response.")


# ===========================================================================
# Section 5 — Module-level convenience functions
# ===========================================================================

class TestModuleLevelFunctions(unittest.TestCase):

    def test_register_prompt_and_render(self):
        # Use a unique name to avoid collisions with other tests.
        register_prompt(
            "test_mod_greet",
            "Greetings, {name}!",
            version="1.0.0",
        )
        result = render_prompt("test_mod_greet", {"name": "World"})
        self.assertEqual(result, "Greetings, World!")

    def test_get_prompt_version_returns_version(self):
        register_prompt("test_mod_ver", "Value is {v}", version="3.0.0")
        pv = get_prompt_version("test_mod_ver")
        self.assertEqual(pv.version, "3.0.0")

    def test_get_prompt_version_specific_version(self):
        register_prompt("test_mod_multi", "A {x}", version="1.0.0")
        register_prompt("test_mod_multi", "B {x}", version="2.0.0")
        pv = get_prompt_version("test_mod_multi", version="1.0.0")
        self.assertEqual(pv.template, "A {x}")


# ===========================================================================
# Section 6 — Thread safety (smoke test)
# ===========================================================================

class TestPromptRegistryThreadSafety(unittest.TestCase):

    def test_concurrent_register_and_render(self):
        import threading

        registry = PromptRegistry()
        registry.register("shared", "Hello {name}", version="1.0.0")
        errors: list[Exception] = []

        def _worker():
            try:
                for i in range(20):
                    v = f"1.{i}.0"
                    registry.register("shared", f"Hello {{name}} v{i}", version=v)
                    registry.render("shared", {"name": "tester"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        self.assertEqual(errors, [], f"Thread safety errors: {errors}")


if __name__ == "__main__":
    unittest.main()
