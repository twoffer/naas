"""app/adapters/_mapping.py: FieldRule mapping engine and declarative adapter tables."""

# third-party
import pytest

# ===========================================================================
# CLASS 1 — Module import
# ===========================================================================


class TestMappingModuleImport:
    """app.adapters._mapping must be importable and expose the required names.

    WHY: Every protocol adapter imports from _mapping at module level.  An
    ImportError here means all three adapters fail to import, shutting down
    the service with no login events processed.
    """

    def test_mapping_module_is_importable(self) -> None:
        """from app.adapters._mapping import ... must not raise.

        WHY: A missing module surfaces as a clear failure rather than a collection error.
        """
        import app.adapters._mapping  # noqa: F401

    def test_coerce_str_is_exported(self) -> None:
        """coerce_str must be a callable in app.adapters._mapping."""
        from app.adapters import _mapping

        assert callable(getattr(_mapping, "coerce_str", None)), (
            "app.adapters._mapping must define a callable coerce_str."
        )

    def test_coerce_str_list_is_exported(self) -> None:
        """coerce_str_list must be a callable in app.adapters._mapping."""
        from app.adapters import _mapping

        assert callable(getattr(_mapping, "coerce_str_list", None)), (
            "app.adapters._mapping must define a callable coerce_str_list."
        )

    def test_field_rule_is_exported(self) -> None:
        """FieldRule must be a class (NamedTuple) in app.adapters._mapping."""
        from app.adapters import _mapping

        assert hasattr(_mapping, "FieldRule"), (
            "app.adapters._mapping must define FieldRule."
        )

    def test_apply_field_rules_is_exported(self) -> None:
        """apply_field_rules must be a callable in app.adapters._mapping."""
        from app.adapters import _mapping

        assert callable(getattr(_mapping, "apply_field_rules", None)), (
            "app.adapters._mapping must define a callable apply_field_rules."
        )

    def test_transform_type_alias_is_exported(self) -> None:
        """Transform type alias must be present in app.adapters._mapping.

        WHY: External code (adapters, tests) that build FieldRule tables use
        Transform as an annotation.  Its absence would force callers to use
        bare Callable, losing the variadic intent in the type signature.
        """
        from app.adapters import _mapping

        assert hasattr(_mapping, "Transform"), (
            "app.adapters._mapping must export Transform (Callable alias). "
            "Spec: Transform = Callable[..., object]."
        )


# ===========================================================================
# CLASS 2 — coerce_str
# ===========================================================================


class TestCoerceStr:
    """coerce_str(value) -> str | None.

    Contract: returns value unchanged if isinstance(value, str), else None.

    WHY: Protocol adapters use coerce_str in single-source FieldRules for
    scalar string fields (name, email, display_name, etc.).  Without this
    guard, a non-str value from an IdP (int 42, dict {'x':1}, list) propagates
    to NormalizedAttributes and causes a downstream Pydantic ValidationError in
    the risk evaluator.  Returning None is the safe discard sentinel.
    """

    def test_str_passes_through_unchanged(self) -> None:
        """coerce_str('hello') == 'hello'."""
        from app.adapters._mapping import coerce_str

        result = coerce_str("hello")

        assert result == "hello", (
            f"coerce_str('hello') must return 'hello' unchanged, got {result!r}."
        )

    def test_empty_str_passes_through(self) -> None:
        """coerce_str('') == '' (empty string is still a str)."""
        from app.adapters._mapping import coerce_str

        result = coerce_str("")

        assert result == "", (
            f"coerce_str('') must return '' (empty str passes through), got {result!r}."
        )

    def test_int_returns_none(self) -> None:
        """coerce_str(42) == None.

        WHY: An IdP may send a numeric claim value where a string is expected
        (e.g., Azure AD sometimes sends department as an integer code).
        """
        from app.adapters._mapping import coerce_str

        result = coerce_str(42)

        assert result is None, (
            f"coerce_str(42) must return None for int input, got {result!r}."
        )

    def test_none_returns_none(self) -> None:
        """coerce_str(None) == None (absent key → transform receives None → None)."""
        from app.adapters._mapping import coerce_str

        result = coerce_str(None)

        assert result is None, (
            f"coerce_str(None) must return None, got {result!r}. "
            "apply_field_rules passes raw_attributes.get(key) which is None "
            "for absent keys."
        )

    def test_list_returns_none(self) -> None:
        """coerce_str(['a', 'b']) == None (list is not a str)."""
        from app.adapters._mapping import coerce_str

        result = coerce_str(["a", "b"])

        assert result is None, (
            f"coerce_str(['a', 'b']) must return None for list input, got {result!r}."
        )

    def test_dict_returns_none(self) -> None:
        """coerce_str({'key': 'val'}) == None (dict is not a str)."""
        from app.adapters._mapping import coerce_str

        result = coerce_str({"key": "val"})

        assert result is None, (
            f"coerce_str({{'key': 'val'}}) must return None for dict input, got {result!r}."
        )

    def test_float_returns_none(self) -> None:
        """coerce_str(3.14) == None (float is not a str)."""
        from app.adapters._mapping import coerce_str

        result = coerce_str(3.14)

        assert result is None, (
            f"coerce_str(3.14) must return None for float input, got {result!r}."
        )

    def test_bool_returns_none(self) -> None:
        """coerce_str(True) == None (bool is not a str; note bool is subclass of int).

        WHY: In Python, bool is a subclass of int, not str.  A truthiness check
        ('value' instead of isinstance(value, str)) would erroneously pass True
        through.  coerce_str must use isinstance(value, str) strictly.
        """
        from app.adapters._mapping import coerce_str

        result = coerce_str(True)

        assert result is None, (
            f"coerce_str(True) must return None — bool is not str. "
            f"Got {result!r}. Use isinstance(value, str), not a truthiness check."
        )

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("alice@corp.com", "alice@corp.com"),
            ("Engineering", "Engineering"),
            ("FTE", "FTE"),
            (0, None),
            (-1, None),
            (None, None),
            ([], None),
            ({}, None),
        ],
    )
    def test_coerce_str_parametrized(self, value: object, expected) -> None:
        """Parametrized contract verification for coerce_str."""
        from app.adapters._mapping import coerce_str

        result = coerce_str(value)

        assert result == expected, (
            f"coerce_str({value!r}) expected {expected!r}, got {result!r}."
        )


# ===========================================================================
# CLASS 3 — coerce_str_list
# ===========================================================================


class TestCoerceStrList:
    """coerce_str_list(value) -> list[str].

    Contract:
      - If value is a list: return [v for v in value if isinstance(v, str)]
      - If value is NOT a list (including str, int, None, dict): return []

    CRITICAL SECURITY INVARIANT: a bare string like "admin" must return [],
    NOT ['a', 'd', 'm', 'i', 'n'].  Python strings are iterable, so a naive
    implementation using `[v for v in value if isinstance(v, str)]` applied to
    a non-list would iterate the string character-by-character — each single
    character is a str, so every char would be included.  The spec is
    deliberately stricter: only list values are iterated.

    WHY this matters for security: if `groups = "admin"` (a single-string
    claim from a misconfigured IdP) iterates to ['a', 'd', 'm', 'i', 'n'],
    then `"admin" in groups` evaluates False (no single element equals
    'admin'), so admin-group policy conditions silently never fire.  If instead
    the bare string is treated as a non-list and returns [], the policy engine
    sees an empty groups list and correctly denies admin-only resources.
    """

    def test_list_of_str_passes_through_unchanged(self) -> None:
        """coerce_str_list(['admin', 'vpn']) == ['admin', 'vpn']."""
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list(["admin", "vpn"])

        assert result == ["admin", "vpn"], (
            f"coerce_str_list(['admin', 'vpn']) must return ['admin', 'vpn'] unchanged, "
            f"got {result!r}."
        )

    def test_empty_list_returns_empty_list(self) -> None:
        """coerce_str_list([]) == []."""
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list([])

        assert result == [], f"coerce_str_list([]) must return [], got {result!r}."

    def test_mixed_type_list_keeps_only_strings(self) -> None:
        """coerce_str_list([1, 'admin', None, 'vpn', 2]) == ['admin', 'vpn'].

        WHY: Some IdPs return heterogeneous list values (e.g., a list of group
        DNs mixed with null sentinels).  Non-str items must be silently dropped.
        """
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list([1, "admin", None, "vpn", 2])

        assert result == ["admin", "vpn"], (
            f"coerce_str_list with mixed types must keep only strings. "
            f"Expected ['admin', 'vpn'], got {result!r}."
        )

    def test_list_of_all_non_str_returns_empty(self) -> None:
        """coerce_str_list([1, 2, None, {}]) == []."""
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list([1, 2, None, {}])

        assert result == [], (
            f"coerce_str_list([1, 2, None, {{}}]) must return [], got {result!r}."
        )

    def test_none_returns_empty_list(self) -> None:
        """coerce_str_list(None) == [] (absent key → None → []).

        WHY: apply_field_rules calls transform(raw_attributes.get(key)); when
        the key is absent raw_attributes.get returns None.  coerce_str_list must
        return [] so the groups field always defaults to a list, not None.
        """
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list(None)

        assert result == [], (
            f"coerce_str_list(None) must return [], got {result!r}. "
            "None is not a list; absent groups key must produce empty list."
        )

    def test_bare_string_returns_empty_list_not_char_list(self) -> None:
        """coerce_str_list('admin') == [] — the critical list-only invariant.

        WHY (SECURITY): A bare string is NOT a list.  The STRICT list-only
        semantics require returning [] rather than iterating the string.
        If this were to return ['a','d','m','i','n'], then any policy condition
        checking `"admin" in groups` would evaluate False — silently not matching
        the intended group name.  This is a privilege-relevant logic error.

        Additionally: iterating a bare 'admin' string to ['a','d','m','i','n']
        would pollute the groups list with single-character noise entries, which
        could interfere with downstream group-merge resolution.

        ASSERT: result is NOT a list containing single-char strings from 'admin'.
        """
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list("admin")

        assert result == [], (
            f"coerce_str_list('admin') must return [] — a bare string is not a list. "
            f"Got {result!r}. "
            "The strict list-only semantics require isinstance(value, list) check. "
            "A naive [v for v in value if isinstance(v, str)] would yield "
            "['a','d','m','i','n'] — this is the critical regression this test prevents."
        )
        # Explicitly confirm no character-by-character iteration occurred
        assert result != list("admin"), (
            "coerce_str_list('admin') must NOT iterate the string character-by-character. "
            "['a','d','m','i','n'] is NOT an acceptable result."
        )

    def test_int_returns_empty_list(self) -> None:
        """coerce_str_list(42) == [] (non-list → [])."""
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list(42)

        assert result == [], (
            f"coerce_str_list(42) must return [] for int input, got {result!r}."
        )

    def test_dict_returns_empty_list(self) -> None:
        """coerce_str_list({'a': 'b'}) == [] (dict is not a list)."""
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list({"a": "b"})

        assert result == [], (
            f"coerce_str_list({{'a': 'b'}}) must return [] for dict input, got {result!r}."
        )

    def test_return_type_is_always_list(self) -> None:
        """coerce_str_list always returns a list regardless of input type.

        WHY: The groups field in the unified schema is typed as list[str]. If
        coerce_str_list ever returns a non-list, every downstream consumer that
        calls len(groups) or iterates groups would raise TypeError.
        """
        from app.adapters._mapping import coerce_str_list

        inputs = [None, "admin", 42, {}, [], ["admin"], [1, "admin", None]]
        for inp in inputs:
            result = coerce_str_list(inp)
            assert isinstance(result, list), (
                f"coerce_str_list({inp!r}) must always return a list. "
                f"Got {type(result).__name__!r}: {result!r}."
            )

    @pytest.mark.parametrize(
        "value,expected",
        [
            (["admin"], ["admin"]),
            (["admin", "vpn"], ["admin", "vpn"]),
            ([], []),
            ([1, "admin", 2], ["admin"]),
            (None, []),
            ("admin", []),  # STRICT: bare string → []
            ("", []),  # empty string is still not a list
            (0, []),
            ({}, []),
            ([True, "valid", False], ["valid"]),  # bool is not str
        ],
    )
    def test_coerce_str_list_parametrized(self, value: object, expected: list) -> None:
        """Parametrized contract verification for coerce_str_list."""
        from app.adapters._mapping import coerce_str_list

        result = coerce_str_list(value)

        assert result == expected, (
            f"coerce_str_list({value!r}) expected {expected!r}, got {result!r}."
        )


# ===========================================================================
# CLASS 4 — FieldRule NamedTuple
# ===========================================================================


class TestFieldRule:
    """FieldRule(source_keys, transform) must be a NamedTuple with named accessors.

    WHY: Rule tables are defined at module level in each adapter.  Code that
    inspects rules (e.g., debugging tools, future rule-audit utilities) uses
    .source_keys and .transform as named attributes.  If FieldRule were a plain
    tuple, accessing rule.source_keys would raise AttributeError, making rules
    impossible to introspect without positional indexing — which is fragile.
    """

    def test_field_rule_is_instantiable_with_two_positional_args(self) -> None:
        """FieldRule(('name',), str) must instantiate without raising."""
        from app.adapters._mapping import FieldRule

        rule = FieldRule(("name",), str)

        assert rule is not None, "FieldRule(('name',), str) must instantiate."

    def test_field_rule_source_keys_accessor(self) -> None:
        """rule.source_keys must return the first constructor argument."""
        from app.adapters._mapping import FieldRule

        rule = FieldRule(("email",), str)

        assert rule.source_keys == ("email",), (
            f"rule.source_keys must equal ('email',), got {rule.source_keys!r}."
        )

    def test_field_rule_transform_accessor(self) -> None:
        """rule.transform must return the second constructor argument."""
        from app.adapters._mapping import FieldRule

        def fn(x):
            return x

        rule = FieldRule(("name",), fn)

        assert rule.transform is fn, (
            f"rule.transform must be the callable passed at construction time. "
            f"Got {rule.transform!r}."
        )

    def test_field_rule_is_a_namedtuple(self) -> None:
        """FieldRule must be a NamedTuple (supports _fields, _asdict, indexing).

        WHY: NamedTuple instances support both named attribute access (.source_keys)
        and index access ([0]).  This is required for compatibility with code that
        destructures rules via unpacking.
        """
        from app.adapters._mapping import FieldRule

        rule = FieldRule(("cn",), str)

        # NamedTuple contract
        assert hasattr(rule, "_fields"), (
            "FieldRule must be a NamedTuple — it must have a _fields attribute."
        )
        assert "source_keys" in rule._fields, (
            f"'source_keys' must be in FieldRule._fields, got {rule._fields!r}."
        )
        assert "transform" in rule._fields, (
            f"'transform' must be in FieldRule._fields, got {rule._fields!r}."
        )

    def test_field_rule_source_keys_is_tuple(self) -> None:
        """source_keys must be a tuple (not a list) to support multi-key rules.

        WHY: Tuples are hashable and express immutable ordered key sequences.
        The unpacking convention `transform(*[raw.get(k) for k in rule.source_keys])`
        requires source_keys to be iterable and length-deterministic.
        """
        from app.adapters._mapping import FieldRule

        rule = FieldRule(("a", "b"), lambda x, y: (x, y))

        assert isinstance(rule.source_keys, tuple), (
            f"rule.source_keys must be a tuple, got {type(rule.source_keys).__name__!r}."
        )

    def test_field_rule_multi_key_stores_multiple_keys(self) -> None:
        """FieldRule(('a', 'b'), fn).source_keys must contain both keys."""
        from app.adapters._mapping import FieldRule

        rule = FieldRule(("first_name", "last_name"), lambda f, last: f"{f} {last}")

        assert rule.source_keys == ("first_name", "last_name"), (
            f"Multi-key FieldRule must store all keys in source_keys. "
            f"Got {rule.source_keys!r}."
        )


# ===========================================================================
# CLASS 5 — apply_field_rules
# ===========================================================================


class TestApplyFieldRules:
    """apply_field_rules(raw_attributes, rules) -> dict.

    Contract:
      For each (field_name, rule) in rules.items():
        result[field_name] = rule.transform(*[raw_attributes.get(k) for k in rule.source_keys])

      Single-key rule: transform(raw_attributes.get(key))
      Multi-key rule:  transform(raw_attributes.get(key1), raw_attributes.get(key2), ...)

    WHY: apply_field_rules is the engine that powers all three protocol adapters.
    Any deviation from the positional-unpacking contract silently produces wrong
    values (or crashes with TypeError) for every login event processed by that
    adapter.
    """

    def test_single_key_rule_returns_correct_value(self) -> None:
        """Single-key rule: apply_field_rules({'name': 'Alice'}, rules) → {'display_name': 'Alice'}.

        WHY: This is the canonical single-source lookup pattern used by all adapters
        for scalar string fields.
        """
        from app.adapters._mapping import FieldRule, apply_field_rules, coerce_str

        rules = {"display_name": FieldRule(("name",), coerce_str)}
        raw = {"name": "Alice"}

        result = apply_field_rules(raw, rules)

        assert result == {"display_name": "Alice"}, (
            f"apply_field_rules with single-key rule expected {{'display_name': 'Alice'}}, "
            f"got {result!r}."
        )

    def test_single_key_rule_absent_key_passes_none_to_transform(self) -> None:
        """When the source key is absent, transform receives None.

        WHY: raw_attributes.get(key) returns None for absent keys.  The transform
        function must handle None — this is what makes coerce_str(None) → None
        the correct fallback (rather than raising KeyError).
        """
        from app.adapters._mapping import FieldRule, apply_field_rules, coerce_str

        rules = {"display_name": FieldRule(("name",), coerce_str)}
        raw = {}  # 'name' key absent

        result = apply_field_rules(raw, rules)

        assert result == {"display_name": None}, (
            f"Absent key must cause transform to receive None. "
            f"Expected {{'display_name': None}}, got {result!r}."
        )

    def test_multi_key_rule_passes_both_values_positionally(self) -> None:
        """Multi-key rule: transform receives two positional args in source_keys order.

        WHY: The spec explicitly requires multi-key support so that a single rule
        can aggregate values from two source claims into one unified field
        (e.g., concatenating first+last name, or a composite key lookup).

        Test case: FieldRule(('a', 'b'), lambda x, y: f'{x}-{y}') applied to
        {'a': '1', 'b': '2'} must yield '1-2'.
        """
        from app.adapters._mapping import FieldRule, apply_field_rules

        rules = {"combined": FieldRule(("a", "b"), lambda x, y: f"{x}-{y}")}
        raw = {"a": "1", "b": "2"}

        result = apply_field_rules(raw, rules)

        assert result == {"combined": "1-2"}, (
            f"Multi-key rule must pass both values positionally to the transform. "
            f"Expected {{'combined': '1-2'}}, got {result!r}."
        )

    def test_multi_key_rule_absent_second_key_passes_none(self) -> None:
        """Multi-key rule with one absent key: the missing arg is None.

        WHY: When the second source key is absent, transform receives (value, None).
        The transform must handle None for any of its positional args.
        """
        from app.adapters._mapping import FieldRule, apply_field_rules

        rules = {"combined": FieldRule(("a", "b"), lambda x, y: f"{x}-{y}")}
        raw = {"a": "1"}  # 'b' absent

        result = apply_field_rules(raw, rules)

        assert result == {"combined": "1-None"}, (
            f"Absent second key must pass None to transform. "
            f"Expected {{'combined': '1-None'}}, got {result!r}."
        )

    def test_multiple_rules_all_evaluated(self) -> None:
        """Multiple rules in the table: each rule field appears in the output dict.

        WHY: The full adapter FIELD_RULES table has 5 entries.  All 5 must be
        evaluated and present in the output regardless of which keys are present
        in raw_attributes.
        """
        from app.adapters._mapping import (
            FieldRule,
            apply_field_rules,
            coerce_str,
            coerce_str_list,
        )

        rules = {
            "display_name": FieldRule(("name",), coerce_str),
            "primary_email": FieldRule(("email",), coerce_str),
            "groups": FieldRule(("groups",), coerce_str_list),
        }
        raw = {
            "name": "Alice",
            "email": "alice@corp.com",
            "groups": ["admin"],
        }

        result = apply_field_rules(raw, rules)

        assert result == {
            "display_name": "Alice",
            "primary_email": "alice@corp.com",
            "groups": ["admin"],
        }, f"All rules must be evaluated. Expected full dict, got {result!r}."

    def test_output_dict_has_exactly_the_rule_keys(self) -> None:
        """apply_field_rules output dict must contain exactly the rule field names.

        WHY: The adapter's extract() is defined as a one-liner that returns the
        result of apply_field_rules directly.  NormalizedAttributes construction
        uses the result dict via **kwargs; extra or missing keys would cause
        model validation errors.
        """
        from app.adapters._mapping import FieldRule, apply_field_rules, coerce_str

        rules = {
            "display_name": FieldRule(("name",), coerce_str),
            "primary_email": FieldRule(("email",), coerce_str),
        }
        raw = {"name": "Alice", "email": "alice@corp.com", "extra_key": "ignored"}

        result = apply_field_rules(raw, rules)

        assert set(result.keys()) == {"display_name", "primary_email"}, (
            f"apply_field_rules output must contain exactly the rule keys, "
            f"not raw_attributes keys. Got {set(result.keys())!r}."
        )

    def test_output_key_order_matches_rule_declaration_order(self) -> None:
        """Output dict key order must match the rules dict declaration order.

        WHY: Python 3.7+ dict preserves insertion order.  The adapter spec
        defines a canonical field ordering; preserving declaration order in the
        output dict makes the resulting dict predictable for both dict-equality
        assertions and ordered serialization.
        """
        from app.adapters._mapping import (
            FieldRule,
            apply_field_rules,
            coerce_str,
            coerce_str_list,
        )

        rules = {
            "display_name": FieldRule(("name",), coerce_str),
            "primary_email": FieldRule(("email",), coerce_str),
            "groups": FieldRule(("groups",), coerce_str_list),
        }
        raw = {"name": "Alice", "email": "alice@corp.com", "groups": []}

        result = apply_field_rules(raw, rules)

        assert list(result.keys()) == ["display_name", "primary_email", "groups"], (
            f"Output key order must match rule declaration order. "
            f"Got {list(result.keys())!r}."
        )

    def test_empty_rules_table_returns_empty_dict(self) -> None:
        """apply_field_rules with no rules returns an empty dict.

        WHY: An adapter with a temporarily empty rules table must not crash;
        it should return {} so the NormalizationService handles the empty result
        gracefully (all fields become None via single_source resolution).
        """
        from app.adapters._mapping import apply_field_rules

        result = apply_field_rules({"name": "Alice"}, {})

        assert result == {}, (
            f"apply_field_rules with empty rules table must return {{}}, got {result!r}."
        )

    def test_empty_raw_attributes_all_transforms_receive_none(self) -> None:
        """apply_field_rules({}, rules): every transform receives None.

        WHY: Corresponds to the empty-payload case in adapter tests.  Every
        raw_attributes.get(key) returns None; each coerce_str/coerce_str_list
        call receives None and must return its safe default.
        """
        from app.adapters._mapping import (
            FieldRule,
            apply_field_rules,
            coerce_str,
            coerce_str_list,
        )

        rules = {
            "display_name": FieldRule(("name",), coerce_str),
            "groups": FieldRule(("groups",), coerce_str_list),
        }

        result = apply_field_rules({}, rules)

        assert result == {"display_name": None, "groups": []}, (
            f"Empty raw_attributes must produce display_name=None and groups=[]. "
            f"Got {result!r}."
        )

    def test_transform_callable_is_called_with_correct_value(self) -> None:
        """apply_field_rules must call the rule's transform, not bypass it.

        WHY: If apply_field_rules short-circuits (e.g., returning the raw value
        directly when it is already a str), value normalization transforms like
        normalize_department_value would never run.  We verify the transform is
        actually called by using a side-effecting function.
        """
        from app.adapters._mapping import FieldRule, apply_field_rules

        call_record: list = []

        def recording_transform(value: object) -> str:
            call_record.append(value)
            return "TRANSFORMED"

        rules = {"field": FieldRule(("key",), recording_transform)}
        raw = {"key": "input_value"}

        result = apply_field_rules(raw, rules)

        assert call_record == ["input_value"], (
            f"Transform must be called with the raw value 'input_value'. "
            f"Actual call args: {call_record!r}."
        )
        assert result == {"field": "TRANSFORMED"}, (
            f"Output must contain the transform's return value. Got {result!r}."
        )
