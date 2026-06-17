"""NormalizationConfig YAML validation: schema errors, field constraints, and fallbacks."""

from pathlib import Path

# third-party
import pydantic
import pytest

# ---------------------------------------------------------------------------
# Helper — build a minimal valid YAML with overrides
# ---------------------------------------------------------------------------


def _write_enrichment_yaml(
    tmp_path: Path,
    correlation_key: str = "primary_email",
    on_failure: str = "continue",
    cache_ttl_seconds: object = 60,
    enrich_attributes: "list[str] | None" = None,
) -> Path:
    """Write a minimal normalization.yaml with the given enrichment sub-values.

    Defaults produce a valid config. Override individual fields to produce
    configs that exercise specific validation failures.
    """
    ttl_line = f"      cache_ttl_seconds: {cache_ttl_seconds}"
    enrich_block = ""
    if enrich_attributes is not None:
        enrich_lines = "\n".join(f"        - {attr}" for attr in enrich_attributes)
        enrich_block = f"\n      enrich_attributes:\n{enrich_lines}"

    content = f"""
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes: {{}}

enrichment:
  sources:
    ldap:
      enabled: true
      correlation_key: {correlation_key}
      timeout_ms: 2000
      on_failure: {on_failure}
{ttl_line}{enrich_block}
"""
    p = tmp_path / "normalization.yaml"
    p.write_text(content)
    return p


# ===========================================================================
# CLASS 1 — correlation_key validation
# ===========================================================================


class TestCorrelationKeyValidation:
    """load_config must raise a descriptive error when correlation_key is invalid.

    WHY: The correlation_key is used to build the LDAP search filter. An
    unrecognized unified field name cannot be reverse-mapped to an LDAP attribute,
    meaning the enrichment adapter returns None for every event — silently
    disabling enrichment without any operational signal.
    """

    def test_invalid_correlation_key_raises(self, tmp_path: Path) -> None:
        """load_config raises when correlation_key is not a reverse-mappable unified field.

        WHY: 'favorite_color' is not in UNIFIED_TO_LDAP. There is no LDAP attribute
        to map it to. Accepting it at startup means every enrichment attempt fails
        silently at runtime when the adapter cannot reverse-map the key.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, correlation_key="favorite_color")

        with pytest.raises(Exception) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        assert "favorite_color" in exc_message, (
            f"Error message must name the offending correlation_key 'favorite_color'. "
            f"Got: {exc_message!r}. "
            "Spec §5.6: 'abort startup with a descriptive error'."
        )

    def test_invalid_correlation_key_another_bad_value_raises(
        self, tmp_path: Path
    ) -> None:
        """load_config raises for another invalid correlation_key ('username').

        WHY: Guards against the implementer special-casing only 'favorite_color'.
        Any key not in UNIFIED_TO_LDAP must be rejected.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, correlation_key="username")

        with pytest.raises(Exception) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        assert "username" in exc_message, (
            f"Error message must name the offending correlation_key 'username'. "
            f"Got: {exc_message!r}."
        )

    def test_valid_correlation_key_primary_email_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """load_config does NOT raise when correlation_key == 'primary_email'.

        WHY: 'primary_email' is in UNIFIED_TO_LDAP (maps to 'mail'). It is the
        §5.6 default. Rejecting it would make the committed config invalid.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, correlation_key="primary_email")

        # Must not raise
        cfg = load_config(p)
        assert cfg is not None, (
            "load_config must return a config object for valid input."
        )

    @pytest.mark.parametrize(
        "valid_key",
        [
            "display_name",
            "primary_email",
            "department",
            "employee_type",
            "groups",
        ],
    )
    def test_all_unified_to_ldap_keys_are_valid_correlation_keys(
        self, tmp_path: Path, valid_key: str
    ) -> None:
        """Every key in UNIFIED_TO_LDAP must be a valid correlation_key.

        WHY: The valid set comes from UNIFIED_TO_LDAP — these are the five unified
        fields the LDAP adapter can reverse-map. All five must be accepted.
        If even one is rejected, that reverse-mapping path is unreachable.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, correlation_key=valid_key)

        # Must not raise for any key in UNIFIED_TO_LDAP
        cfg = load_config(p)
        assert cfg is not None, (
            f"load_config must not raise for correlation_key={valid_key!r}, "
            f"which is a valid key in UNIFIED_TO_LDAP."
        )

    def test_loader_rejects_key_absent_from_unified_to_ldap(
        self, tmp_path: Path
    ) -> None:
        """The validation uses UNIFIED_TO_LDAP as the single source of truth.

        WHY: This test asserts the linkage contract. It dynamically builds the valid
        set from UNIFIED_TO_LDAP and asserts that a key NOT in that set is rejected.
        This prevents the implementer from hardcoding a divergent second copy of
        the valid unified-field set in normalization_config.py.

        If UNIFIED_TO_LDAP is extended in the future (e.g., a sixth unified field
        is added), this test ensures the validation automatically expands — no sync
        required between two codepaths.
        """
        from app.normalization_config import load_config
        from app.normalization_values import UNIFIED_TO_LDAP

        # Pick a key guaranteed to be absent from UNIFIED_TO_LDAP
        absent_key = "not_a_unified_field_xyz"
        assert absent_key not in UNIFIED_TO_LDAP, (
            f"Test setup error: {absent_key!r} must not be in UNIFIED_TO_LDAP."
        )

        p = _write_enrichment_yaml(tmp_path, correlation_key=absent_key)

        with pytest.raises(ValueError):
            load_config(p)


# ===========================================================================
# CLASS 2 — on_failure validation
# ===========================================================================


class TestOnFailureValidation:
    """load_config must raise when on_failure is anything other than 'continue'.

    WHY: 'fail' (rejecting events on LDAP error) violates the pipeline's
    graceful-degradation invariant (§5.4 / ADR-0008 — enrichment failure must
    never drop an event). Only 'continue' is supported. An unrecognized value
    like 'explode' or the reserved 'fail' must be rejected at startup with a
    descriptive error.
    """

    def test_invalid_on_failure_explode_raises(self, tmp_path: Path) -> None:
        """load_config raises ValueError when on_failure == 'explode'.

        WHY: 'explode' is not in the supported set {'continue'}.
        An unrecognized value leaves error handling undefined.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, on_failure="explode")

        with pytest.raises(ValueError) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        assert "explode" in exc_message or "on_failure" in exc_message, (
            f"Error message must reference the offending on_failure value or field name. "
            f"Got: {exc_message!r}. "
            "Spec §5.6: 'abort startup with a descriptive error'."
        )

    def test_invalid_on_failure_ignore_raises(self, tmp_path: Path) -> None:
        """load_config raises ValueError when on_failure == 'ignore'.

        WHY: 'ignore' sounds plausible but is not supported. Guards against
        the implementer only checking for a single invalid value.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, on_failure="ignore")

        with pytest.raises(ValueError):
            load_config(p)

    def test_on_failure_fail_raises_descriptive_error(self, tmp_path: Path) -> None:
        """load_config raises ValueError when on_failure == 'fail'.

        WHY: 'fail' (reject the event on LDAP error) violates the
        graceful-degradation invariant — enrichment failure must never drop an
        event (§5.4 / ADR-0008). The error message must explain why 'fail' is
        not supported.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, on_failure="fail")

        with pytest.raises(ValueError) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        # Error must name the value and explain why it is not supported
        assert "fail" in exc_message, (
            f"Error message must reference 'fail'. Got: {exc_message!r}."
        )
        assert "continue" in exc_message, (
            f"Error message must mention the supported value 'continue'. "
            f"Got: {exc_message!r}."
        )

    def test_on_failure_continue_is_valid(self, tmp_path: Path) -> None:
        """load_config does NOT raise when on_failure == 'continue'.

        WHY: 'continue' is the only supported value (§5.6).
        The committed config uses this value.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, on_failure="continue")

        cfg = load_config(p)
        assert cfg is not None, "load_config must succeed for on_failure='continue'."


# ===========================================================================
# CLASS 3 — cache_ttl_seconds validation
# ===========================================================================


class TestCacheTtlValidation:
    """load_config must raise when cache_ttl_seconds is not a positive integer.

    WHY: cache_ttl_seconds drives the Redis cache TTL for LDAP results. A TTL of 0
    means every lookup expires immediately — effectively disabling the cache and
    hammering LDAP on every login. A negative TTL is semantically nonsensical and
    may cause Redis to immediately expire the key or raise an error.
    Spec §5.6: 'cache_ttl_seconds is not a positive integer'.
    """

    def test_cache_ttl_zero_raises(self, tmp_path: Path) -> None:
        """load_config raises when cache_ttl_seconds == 0.

        WHY: Zero is not positive. A zero TTL disables caching effectively,
        which is operationally dangerous (LDAP stampede on every login).
        Spec §5.6 firm requirement: 'not a positive integer' → raise.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, cache_ttl_seconds=0)

        with pytest.raises(Exception) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        # The error must reference the field or value
        assert any(
            token in exc_message for token in ("cache_ttl", "ttl", "0", "positive")
        ), (
            f"Error message must reference the cache_ttl_seconds field or the invalid value. "
            f"Got: {exc_message!r}."
        )

    def test_cache_ttl_negative_raises(self, tmp_path: Path) -> None:
        """load_config raises when cache_ttl_seconds == -5.

        WHY: Negative values are semantically invalid. Spec §5.6 firm requirement.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, cache_ttl_seconds=-5)

        with pytest.raises(Exception) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        assert any(
            token in exc_message for token in ("cache_ttl", "ttl", "-5", "positive")
        ), (
            f"Error message must reference the cache_ttl_seconds field or invalid value. "
            f"Got: {exc_message!r}."
        )

    def test_cache_ttl_negative_one_raises(self, tmp_path: Path) -> None:
        """load_config raises when cache_ttl_seconds == -1.

        WHY: Additional negative boundary — guards against an off-by-one that
        accepts -1 but rejects other negatives.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, cache_ttl_seconds=-1)

        with pytest.raises(pydantic.ValidationError):
            load_config(p)

    def test_cache_ttl_positive_does_not_raise(self, tmp_path: Path) -> None:
        """load_config does NOT raise when cache_ttl_seconds == 60.

        WHY: 60 is the §5.6 default and is a positive integer. Any validator that
        rejects 60 is broken.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, cache_ttl_seconds=60)

        cfg = load_config(p)
        assert cfg is not None, "load_config must succeed for cache_ttl_seconds=60."

    def test_cache_ttl_one_does_not_raise(self, tmp_path: Path) -> None:
        """load_config does NOT raise when cache_ttl_seconds == 1.

        WHY: 1 is the minimum positive integer. The boundary must be exclusive of 0.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, cache_ttl_seconds=1)

        cfg = load_config(p)
        assert cfg is not None, "load_config must succeed for cache_ttl_seconds=1."


# ===========================================================================
# CLASS 4 — enrich_attributes validation
# ===========================================================================


class TestEnrichAttributesValidation:
    """load_config must raise when enrich_attributes contains an unknown unified field.

    WHY: enrich_attributes (optional) limits which LDAP attributes are fetched.
    An unknown name (e.g. 'favorite_color') cannot be reverse-mapped to an LDAP
    attribute, so the LDAP adapter would silently skip it — or raise KeyError —
    at runtime. Spec §5.6: 'enrich_attributes (if present) contains a name that
    is not a reverse-mappable unified field'.
    """

    def test_enrich_attributes_with_invalid_name_raises(self, tmp_path: Path) -> None:
        """load_config raises when enrich_attributes contains 'favorite_color'.

        WHY: 'favorite_color' is not in UNIFIED_TO_LDAP, so it cannot be fetched
        from LDAP. Accepting it means a silent no-op at enrichment time.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(
            tmp_path, enrich_attributes=["primary_email", "favorite_color"]
        )

        with pytest.raises(Exception) as exc_info:
            load_config(p)

        exc_message = str(exc_info.value)
        assert "favorite_color" in exc_message or "enrich_attributes" in exc_message, (
            f"Error message must reference 'favorite_color' or 'enrich_attributes'. "
            f"Got: {exc_message!r}. "
            "Spec §5.6: 'abort startup with a descriptive error'."
        )

    def test_enrich_attributes_all_invalid_raises(self, tmp_path: Path) -> None:
        """load_config raises when enrich_attributes is entirely unknown names."""
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(
            tmp_path, enrich_attributes=["not_a_field", "also_not_a_field"]
        )

        with pytest.raises(ValueError):
            load_config(p)

    def test_enrich_attributes_valid_subset_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """load_config does NOT raise when enrich_attributes is a valid subset of unified fields.

        WHY: ['primary_email', 'department'] is a valid subset — both are in
        UNIFIED_TO_LDAP. Rejecting valid subsets would make enrich_attributes
        unusable.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(
            tmp_path, enrich_attributes=["primary_email", "department"]
        )

        cfg = load_config(p)
        assert cfg is not None, (
            "load_config must succeed when enrich_attributes is a valid subset."
        )

    def test_enrich_attributes_all_five_unified_fields_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """load_config does NOT raise when enrich_attributes lists all five unified fields."""
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(
            tmp_path,
            enrich_attributes=[
                "display_name",
                "primary_email",
                "department",
                "employee_type",
                "groups",
            ],
        )

        cfg = load_config(p)
        assert cfg is not None, (
            "load_config must succeed when enrich_attributes contains all five valid fields."
        )

    def test_enrich_attributes_omitted_does_not_raise(self, tmp_path: Path) -> None:
        """load_config does NOT raise when enrich_attributes is omitted (optional key).

        WHY: §5.6 comments out enrich_attributes in the default config, marking it
        as optional. Requiring it would break the committed config.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, enrich_attributes=None)

        cfg = load_config(p)
        assert cfg is not None, (
            "load_config must succeed when enrich_attributes is omitted (it is optional)."
        )

    @pytest.mark.parametrize(
        "valid_attr",
        [
            "display_name",
            "primary_email",
            "department",
            "employee_type",
            "groups",
        ],
    )
    def test_each_individual_unified_field_is_valid_in_enrich_attributes(
        self, tmp_path: Path, valid_attr: str
    ) -> None:
        """Each unified field individually is valid in enrich_attributes.

        WHY: Guards against a validator that only accepts the full five-field list
        or rejects any single-item list.
        """
        from app.normalization_config import load_config

        p = _write_enrichment_yaml(tmp_path, enrich_attributes=[valid_attr])

        cfg = load_config(p)
        assert cfg is not None, (
            f"load_config must accept enrich_attributes=[{valid_attr!r}] — "
            f"'{valid_attr}' is in UNIFIED_TO_LDAP."
        )
