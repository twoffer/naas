"""NormalizationConfig model: load_config(), accessor helpers, fallback behaviour."""

from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------



def _find_repo_root() -> Path:
    """Walk up until docs/architecture/ is found — repo root marker."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Could not locate repo root from {Path(__file__).resolve()}")

REPO_ROOT = _find_repo_root()

CONFIG_PATH = REPO_ROOT / "config" / "normalization.yaml"



# ===========================================================================
# CLASS 1 — Module import
# ===========================================================================


class TestNormalizationConfigImport:
    """app.normalization_config must be importable and expose the required names.

    WHY: main.py calls load_config() at startup. An ImportError means the service
    cannot start at all. Missing names means startup raises AttributeError instead
    of the structured validation error that §5.6 requires.
    """

    def test_module_is_importable(self) -> None:
        """from app.normalization_config import ... must not raise.

        WHY: A missing module surfaces as a clear failure rather than a collection error.
        """
        import app.normalization_config  # noqa: F401

    def test_load_config_is_defined(self) -> None:
        """load_config must be exposed as a callable in the module."""
        from app import normalization_config

        assert callable(getattr(normalization_config, "load_config", None)), (
            "app.normalization_config must define a callable load_config(path) -> NormalizationConfig. "
            "Spec §5.6: config is loaded once at startup via this function."
        )

    def test_normalization_config_class_is_defined(self) -> None:
        """NormalizationConfig must be a class exported from the module."""
        from app import normalization_config

        cls = getattr(normalization_config, "NormalizationConfig", None)
        assert cls is not None, (
            "app.normalization_config must define NormalizationConfig. "
            "Spec §5.6: the Pydantic model wrapping the parsed YAML."
        )
        # Must be a class (Pydantic model or dataclass), not a function or value
        assert isinstance(cls, type), (
            f"NormalizationConfig must be a class, got {type(cls)!r}."
        )


# ===========================================================================
# CLASS 2 — Accessor helper contracts (tmp_path-based valid config)
# ===========================================================================


class TestAccessorHelpers:
    """Accessor helpers return correct values from an in-memory valid config.

    Tests in this class build minimal valid YAML in tmp_path so they are
    independent of config/normalization.yaml existing. They exercise the
    accessor fallback logic in isolation.
    """

    @pytest.fixture()
    def minimal_yaml(self, tmp_path: Path) -> Path:
        """A minimal valid config with only defaults — no per-attribute blocks."""
        content = """
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes: {}

enrichment:
  sources:
    ldap:
      enabled: true
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
        p = tmp_path / "normalization.yaml"
        p.write_text(content)
        return p

    @pytest.fixture()
    def full_spec_yaml(self, tmp_path: Path) -> Path:
        """The §5.6 default config transcribed in full for accessor testing."""
        content = """
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  display_name:
    priority: [ldap, saml, oidc]
    weights: {ldap: 0.90, saml: 0.70, oidc: 0.60}
    rationale: "LDAP synced from HR system"
  primary_email:
    priority: [oidc, saml, ldap]
    weights: {oidc: 0.95, saml: 0.75, ldap: 0.65}
    rationale: "OIDC has the most current email"
  department:
    priority: [ldap, oidc, saml]
    weights: {ldap: 0.90, oidc: 0.70, saml: 0.50}
    rationale: "LDAP synced nightly from HR"
  employee_type:
    priority: [ldap, saml, oidc]
    weights: {ldap: 0.95, saml: 0.80, oidc: 0.60}
    rationale: "HR system is authoritative"
  groups:
    merge_strategy: union
    rationale: "Groups from all sources are valid"

enrichment:
  sources:
    ldap:
      enabled: true
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
        p = tmp_path / "normalization.yaml"
        p.write_text(content)
        return p

    def test_weight_for_explicit_entry_returns_correct_weight(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('department', 'ldap') == 0.90 from the explicit weights block.

        WHY: department has an explicit weights block in §5.6. The accessor must
        return the per-attribute weight, not the default. An incorrect value means
        the wrong source wins priority resolution for department.
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("department", "ldap")

        assert result == pytest.approx(0.90), (
            f"Expected weight_for('department', 'ldap') == 0.90, got {result!r}. "
            "Spec §5.6: department.weights.ldap == 0.90."
        )

    def test_weight_for_returns_explicit_oidc_weight_for_primary_email(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('primary_email', 'oidc') == 0.95.

        WHY: primary_email has oidc as highest-weight source. Returning the default
        (0.8) instead of the explicit 0.95 would lower OIDC's authority for the most
        security-sensitive attribute.
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("primary_email", "oidc")

        assert result == pytest.approx(0.95), (
            f"Expected weight_for('primary_email', 'oidc') == 0.95, got {result!r}. "
            "Spec §5.6: primary_email.weights.oidc == 0.95."
        )

    def test_weight_for_returns_explicit_oidc_weight_for_display_name(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('display_name', 'oidc') == 0.60.

        WHY: display_name has lower OIDC authority (HR/LDAP is authoritative for
        legal name). Using the default 0.8 instead of 0.60 would incorrectly
        elevate OIDC's priority for legal-name conflicts.
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("display_name", "oidc")

        assert result == pytest.approx(0.60), (
            f"Expected weight_for('display_name', 'oidc') == 0.60, got {result!r}. "
            "Spec §5.6: display_name.weights.oidc == 0.60."
        )

    def test_weight_for_returns_explicit_ldap_weight_for_employee_type(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('employee_type', 'ldap') == 0.95.

        WHY: HR system (LDAP) is authoritative for employment classification.
        Returning 0.7 (default) instead of 0.95 would downgrade LDAP authority
        for a security-sensitive attribute (employment type affects access rights).
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("employee_type", "ldap")

        assert result == pytest.approx(0.95), (
            f"Expected weight_for('employee_type', 'ldap') == 0.95, got {result!r}. "
            "Spec §5.6: employee_type.weights.ldap == 0.95."
        )

    def test_weight_for_groups_falls_back_to_defaults(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('groups', 'ldap') == 0.7 (default) because groups has no weights block.

        WHY: The groups attribute has only merge_strategy and rationale in §5.6; it
        has no explicit weights block. The accessor must fall back to
        defaults.source_weights['ldap'] == 0.7. Returning 0.0 or raising KeyError
        would break ListMergeResolution confidence computation for every LDAP event.
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("groups", "ldap")

        assert result == pytest.approx(0.7), (
            f"Expected weight_for('groups', 'ldap') == 0.7 (default fallback), got {result!r}. "
            "Spec §5.6: groups has no weights block; accessor must use defaults.source_weights."
        )

    def test_weight_for_groups_falls_back_for_saml(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('groups', 'saml') == 0.6 (default) because groups has no weights block."""
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("groups", "saml")

        assert result == pytest.approx(0.6), (
            f"Expected weight_for('groups', 'saml') == 0.6 (default), got {result!r}. "
            "Spec §5.6: groups.source_weights falls back to defaults.source_weights.saml == 0.6."
        )

    def test_weight_for_groups_falls_back_for_oidc(
        self, full_spec_yaml: Path
    ) -> None:
        """weight_for('groups', 'oidc') == 0.8 (default) because groups has no weights block."""
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.weight_for("groups", "oidc")

        assert result == pytest.approx(0.8), (
            f"Expected weight_for('groups', 'oidc') == 0.8 (default), got {result!r}. "
            "Spec §5.6: groups.source_weights falls back to defaults.source_weights.oidc == 0.8."
        )

    def test_weight_for_source_not_in_explicit_weights_falls_back_to_defaults(
        self, tmp_path: Path
    ) -> None:
        """weight_for('department', 'saml') == 0.50 (explicit) — source IS in weights block.

        Companion: if a source is NOT in an attribute's explicit weights, it falls back.
        This test verifies a source that IS in the explicit block returns the right value.
        """
        from app.normalization_config import load_config

        # department has explicit saml: 0.50 in the full spec
        content = """
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  department:
    priority: [ldap, oidc, saml]
    weights: {ldap: 0.90, oidc: 0.70, saml: 0.50}

enrichment:
  sources:
    ldap:
      enabled: true
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
        p = tmp_path / "normalization.yaml"
        p.write_text(content)
        cfg = load_config(p)

        result = cfg.weight_for("department", "saml")

        assert result == pytest.approx(0.50), (
            f"Expected weight_for('department', 'saml') == 0.50 (explicit), got {result!r}."
        )

    def test_weight_for_unlisted_source_falls_back_to_defaults(
        self, tmp_path: Path
    ) -> None:
        """weight_for on a source absent from the attribute's weights falls back to defaults.

        WHY: A new protocol source or a source not mentioned in an attribute's
        explicit weights block must not raise KeyError — it must fall back to
        defaults.source_weights. Without this fallback, adding a new protocol
        (e.g. a SCIM adapter) would silently break the weight lookup.
        """
        from app.normalization_config import load_config

        # Define department with weights for only ldap and oidc, NOT saml.
        # saml default weight is 0.6; the accessor must return that for saml.
        content = """
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  department:
    priority: [ldap, oidc]
    weights: {ldap: 0.90, oidc: 0.70}

enrichment:
  sources:
    ldap:
      enabled: true
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
        p = tmp_path / "normalization.yaml"
        p.write_text(content)
        cfg = load_config(p)

        result = cfg.weight_for("department", "saml")

        assert result == pytest.approx(0.6), (
            f"Expected weight_for('department', 'saml') == 0.6 (default fallback), got {result!r}. "
            "Source not in attribute's explicit weights must fall back to defaults.source_weights."
        )

    def test_weight_for_unknown_attribute_falls_back_to_defaults(
        self, minimal_yaml: Path
    ) -> None:
        """weight_for on an attribute not in the attributes block returns defaults.

        WHY: The minimal_yaml has an empty attributes: {} block. Any attribute name
        must fall back to defaults.source_weights rather than raising KeyError.
        This is the 'no explicit entry' path mentioned in the task brief.
        """
        from app.normalization_config import load_config

        cfg = load_config(minimal_yaml)

        # With empty attributes, all lookups fall back to defaults
        ldap_default = cfg.weight_for("display_name", "ldap")
        saml_default = cfg.weight_for("display_name", "saml")
        oidc_default = cfg.weight_for("display_name", "oidc")

        assert ldap_default == pytest.approx(0.7), (
            f"Expected weight_for('display_name', 'ldap') == 0.7 (default), got {ldap_default!r}."
        )
        assert saml_default == pytest.approx(0.6), (
            f"Expected weight_for('display_name', 'saml') == 0.6 (default), got {saml_default!r}."
        )
        assert oidc_default == pytest.approx(0.8), (
            f"Expected weight_for('display_name', 'oidc') == 0.8 (default), got {oidc_default!r}."
        )

    def test_priority_for_returns_configured_list(
        self, full_spec_yaml: Path
    ) -> None:
        """priority_for('department') == ['ldap', 'oidc', 'saml'].

        WHY: Priority order is used in §5.5 to pick the winner when sources disagree.
        A transposed list (e.g. ['saml', 'oidc', 'ldap']) means a stale SAML attribute
        beats the nightly LDAP sync, breaking the conflict resolution contract.
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.priority_for("department")

        assert result == ["ldap", "oidc", "saml"], (
            f"Expected priority_for('department') == ['ldap', 'oidc', 'saml'], got {result!r}. "
            "Spec §5.6: department.priority = [ldap, oidc, saml]."
        )

    def test_priority_for_returns_empty_list_when_no_priority_configured(
        self, minimal_yaml: Path
    ) -> None:
        """priority_for returns [] when no priority is configured for an attribute.

        WHY: Some attributes (e.g. groups in §5.6) have no priority block —
        only merge_strategy. priority_for must return [] in that case rather than
        raising KeyError, so the resolution engine can detect 'no configured priority'
        and fall back to weight-based winner selection.
        """
        from app.normalization_config import load_config

        cfg = load_config(minimal_yaml)

        result = cfg.priority_for("groups")

        assert result == [], (
            f"Expected priority_for('groups') == [] (no priority configured), got {result!r}. "
            "Attributes without a priority block must return [] — spec §5.5 fallback path."
        )

    def test_priority_for_missing_attribute_returns_empty_list(
        self, minimal_yaml: Path
    ) -> None:
        """priority_for returns [] for an attribute not in the attributes block at all."""
        from app.normalization_config import load_config

        cfg = load_config(minimal_yaml)

        result = cfg.priority_for("unknown_field")

        assert result == [], (
            f"Expected priority_for('unknown_field') == [], got {result!r}. "
            "Unknown attributes must return [] — callers must handle empty priority gracefully."
        )

    def test_merge_strategy_for_returns_union_from_config(
        self, full_spec_yaml: Path
    ) -> None:
        """merge_strategy_for('groups') == 'union' as configured in §5.6.

        WHY: The groups attribute is resolved via ListMergeResolution with the
        configured merge_strategy. An incorrect return value would pass the wrong
        strategy to the merge algorithm, potentially causing intersection instead
        of union (silently dropping group memberships).
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        result = cfg.merge_strategy_for("groups")

        assert result == "union", (
            f"Expected merge_strategy_for('groups') == 'union', got {result!r}. "
            "Spec §5.6: groups.merge_strategy: union."
        )

    def test_merge_strategy_for_returns_union_default_when_not_configured(
        self, minimal_yaml: Path
    ) -> None:
        """merge_strategy_for returns 'union' as the default when no strategy is configured.

        WHY: Spec §5.6 semantics: 'merge_strategy applies to list attributes only'.
        An attribute without an explicit merge_strategy should default to 'union'
        (the §5.5 default) rather than raising or returning None. Returning None
        would cause the resolution engine to pass None to the merge algorithm.
        """
        from app.normalization_config import load_config

        cfg = load_config(minimal_yaml)

        result = cfg.merge_strategy_for("groups")

        assert result == "union", (
            f"Expected merge_strategy_for('groups') == 'union' (default), got {result!r}. "
            "Spec §5.5: union is the default merge strategy when none is configured."
        )

    def test_merge_strategy_for_unknown_attribute_returns_union_default(
        self, minimal_yaml: Path
    ) -> None:
        """merge_strategy_for on an unknown attribute returns 'union'."""
        from app.normalization_config import load_config

        cfg = load_config(minimal_yaml)

        result = cfg.merge_strategy_for("unknown_field")

        assert result == "union", (
            f"Expected merge_strategy_for('unknown_field') == 'union' (default), got {result!r}."
        )

    def test_enrichment_block_is_accessible(self, full_spec_yaml: Path) -> None:
        """The enrichment block is accessible on the loaded config object.

        WHY: The NormalizationService (§5.4) reads cfg.enrichment to decide whether
        to attempt LDAP enrichment. If the enrichment block is inaccessible (None or
        missing), every OIDC/SAML event silently skips enrichment.
        """
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        assert cfg.enrichment is not None, (
            "NormalizationConfig.enrichment must not be None after loading a valid config. "
            "The enrichment block is required for LDAP enrichment decision-making."
        )

    def test_enrichment_ldap_config_is_accessible(
        self, full_spec_yaml: Path
    ) -> None:
        """cfg.enrichment.sources.ldap (or equivalent) exposes the LDAP enrichment sub-config."""
        from app.normalization_config import load_config

        cfg = load_config(full_spec_yaml)

        # Access via whatever attribute path the implementer chooses
        # We test the concrete scalar values rather than exact attribute path,
        # since the Pydantic model structure is up to the implementer.
        # The presence test here just ensures the block exists and is not None.
        ldap_cfg = None
        # Try common access patterns
        try:
            ldap_cfg = cfg.enrichment.sources.ldap  # type: ignore[attr-defined]
        except AttributeError:
            try:
                ldap_cfg = cfg.enrichment.sources["ldap"]  # type: ignore[index]
            except (AttributeError, KeyError, TypeError):
                pass

        assert ldap_cfg is not None, (
            "The LDAP enrichment sub-config must be accessible from the loaded config. "
            "Expected cfg.enrichment.sources.ldap or equivalent to be non-None."
        )
