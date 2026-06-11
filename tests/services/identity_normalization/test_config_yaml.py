"""config/normalization.yaml round-trip: load_config() reads YAML and populates NormalizationConfig."""

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
# CLASS 1 — The committed config/normalization.yaml file itself
# ===========================================================================


class TestCommittedYamlFileExists:
    """The committed config/normalization.yaml must exist and be loadable.

    WHY: If the file is missing, the service cannot start (§5.1: 'loads and
    validates config/normalization.yaml — invalid config aborts startup').
    The path is also mounted read-only into the container (§5.8 docker-compose).
    """

    def test_config_file_exists_at_committed_path(self) -> None:
        """config/normalization.yaml must exist at REPO_ROOT/config/normalization.yaml.

        WHY: The docker-compose entry mounts ./config:/app/config (read-only).
        If the file does not exist in the repository, the container has nothing
        to mount and startup fails with a file-not-found error.
        """
        assert CONFIG_PATH.exists(), (
            f"config/normalization.yaml must exist at {CONFIG_PATH}. "
            "Spec §5.6 and §5.8: the file is mounted into the container and loaded at startup."
        )

    def test_config_file_is_a_regular_file(self) -> None:
        """config/normalization.yaml must be a regular file, not a directory."""
        assert CONFIG_PATH.is_file(), (
            f"{CONFIG_PATH} must be a regular file, not a directory or symlink. "
            "load_config() opens it with yaml.safe_load()."
        )

    def test_load_config_of_committed_file_does_not_raise(self) -> None:
        """load_config(CONFIG_PATH) must not raise for the committed config.

        WHY: §5.6 validation requirements must all pass for the §5.6 default values.
        If load_config() raises on its own default config, the service cannot start
        even with a correct installation. This is the integration proof that the
        YAML file and the Pydantic validator are in sync.
        """
        from app.normalization_config import load_config

        cfg = load_config(CONFIG_PATH)

        assert cfg is not None, (
            "load_config(CONFIG_PATH) must return a NormalizationConfig object. "
            "The committed config/normalization.yaml must satisfy all §5.6 validation rules."
        )


# ===========================================================================
# CLASS 2 — §5.6 weight values (TRANSCRIBE EXACTLY)
# ===========================================================================


class TestCommittedYamlWeights:
    """Weights from the committed config must match §5.6 exactly.

    All values in this class are labelled [TRANSCRIBE EXACTLY] in the spec.
    A deviation means confidence scores produced by §5.5 do not match the
    §3.3 representative payload example.
    """

    @pytest.fixture(scope="class")
    def cfg(self):
        """Load the committed config/normalization.yaml once for all weight tests."""
        from app.normalization_config import load_config

        return load_config(CONFIG_PATH)

    def test_department_ldap_weight_is_0_90(self, cfg) -> None:
        """weight_for('department', 'ldap') == 0.90.

        WHY: department.weights.ldap == 0.90 in §5.6. LDAP is the authoritative
        source (synced nightly from HR). A lower weight would incorrectly allow
        OIDC or SAML to win department conflicts.
        """
        result = cfg.weight_for("department", "ldap")

        assert result == pytest.approx(0.90), (
            f"Expected weight_for('department', 'ldap') == 0.90, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: department.weights.ldap: 0.90."
        )

    def test_department_oidc_weight_is_0_70(self, cfg) -> None:
        """weight_for('department', 'oidc') == 0.70."""
        result = cfg.weight_for("department", "oidc")

        assert result == pytest.approx(0.70), (
            f"Expected weight_for('department', 'oidc') == 0.70, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: department.weights.oidc: 0.70."
        )

    def test_department_saml_weight_is_0_50(self, cfg) -> None:
        """weight_for('department', 'saml') == 0.50."""
        result = cfg.weight_for("department", "saml")

        assert result == pytest.approx(0.50), (
            f"Expected weight_for('department', 'saml') == 0.50, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: department.weights.saml: 0.50."
        )

    def test_primary_email_oidc_weight_is_0_95(self, cfg) -> None:
        """weight_for('primary_email', 'oidc') == 0.95.

        WHY: OIDC is the most authoritative source for email (recent SSO migration).
        0.95 is the highest weight in the config for any source/attribute combination.
        This ensures OIDC email wins all conflicts.
        """
        result = cfg.weight_for("primary_email", "oidc")

        assert result == pytest.approx(0.95), (
            f"Expected weight_for('primary_email', 'oidc') == 0.95, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: primary_email.weights.oidc: 0.95."
        )

    def test_primary_email_saml_weight_is_0_75(self, cfg) -> None:
        """weight_for('primary_email', 'saml') == 0.75."""
        result = cfg.weight_for("primary_email", "saml")

        assert result == pytest.approx(0.75), (
            f"Expected weight_for('primary_email', 'saml') == 0.75, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: primary_email.weights.saml: 0.75."
        )

    def test_primary_email_ldap_weight_is_0_65(self, cfg) -> None:
        """weight_for('primary_email', 'ldap') == 0.65."""
        result = cfg.weight_for("primary_email", "ldap")

        assert result == pytest.approx(0.65), (
            f"Expected weight_for('primary_email', 'ldap') == 0.65, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: primary_email.weights.ldap: 0.65."
        )

    def test_display_name_ldap_weight_is_0_85(self, cfg) -> None:
        """weight_for('display_name', 'ldap') == 0.85.

        WHY: LDAP is synced from the HR system — authoritative for legal name.
        Rationale from §5.6: display_name.weights.ldap: 0.85.
        """
        result = cfg.weight_for("display_name", "ldap")

        assert result == pytest.approx(0.85), (
            f"Expected weight_for('display_name', 'ldap') == 0.85, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: display_name.weights.ldap: 0.85."
        )

    def test_display_name_saml_weight_is_0_75(self, cfg) -> None:
        """weight_for('display_name', 'saml') == 0.75."""
        result = cfg.weight_for("display_name", "saml")

        assert result == pytest.approx(0.75), (
            f"Expected weight_for('display_name', 'saml') == 0.75, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: display_name.weights.saml: 0.75."
        )

    def test_display_name_oidc_weight_is_0_70(self, cfg) -> None:
        """weight_for('display_name', 'oidc') == 0.70."""
        result = cfg.weight_for("display_name", "oidc")

        assert result == pytest.approx(0.70), (
            f"Expected weight_for('display_name', 'oidc') == 0.70, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: display_name.weights.oidc: 0.70."
        )

    def test_employee_type_ldap_weight_is_0_95(self, cfg) -> None:
        """weight_for('employee_type', 'ldap') == 0.95.

        WHY: HR system (LDAP) is authoritative for employment classification.
        This is security-sensitive: employee_type affects access tiers.
        """
        result = cfg.weight_for("employee_type", "ldap")

        assert result == pytest.approx(0.95), (
            f"Expected weight_for('employee_type', 'ldap') == 0.95, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: employee_type.weights.ldap: 0.95."
        )

    def test_employee_type_saml_weight_is_0_80(self, cfg) -> None:
        """weight_for('employee_type', 'saml') == 0.80."""
        result = cfg.weight_for("employee_type", "saml")

        assert result == pytest.approx(0.80), (
            f"Expected weight_for('employee_type', 'saml') == 0.80, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: employee_type.weights.saml: 0.80."
        )

    def test_employee_type_oidc_weight_is_0_60(self, cfg) -> None:
        """weight_for('employee_type', 'oidc') == 0.60."""
        result = cfg.weight_for("employee_type", "oidc")

        assert result == pytest.approx(0.60), (
            f"Expected weight_for('employee_type', 'oidc') == 0.60, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: employee_type.weights.oidc: 0.60."
        )

    def test_groups_ldap_weight_falls_back_to_default_0_70(self, cfg) -> None:
        """weight_for('groups', 'ldap') == 0.70 because groups has no explicit weights block.

        WHY: §5.6 groups entry has only merge_strategy and rationale — no weights block.
        The accessor must fall back to defaults.source_weights['ldap'] == 0.70.
        This is a regression test for the 'no weights block' fallback path using the
        actual committed YAML, not a synthetic tmp_path config.
        """
        result = cfg.weight_for("groups", "ldap")

        assert result == pytest.approx(0.70), (
            f"Expected weight_for('groups', 'ldap') == 0.70 (default fallback), got {result!r}. "
            "Spec §5.6: groups has no weights block; must fall back to defaults.source_weights.ldap."
        )

    def test_defaults_source_weights_ldap_is_0_70(self, cfg) -> None:
        """defaults.source_weights.ldap == 0.70.

        WHY: This is the fallback weight for ALL attributes without an explicit ldap weight.
        The groups attribute (no weights block) relies on this. If this default is wrong,
        every groups confidence computation is wrong.
        """
        result = cfg.weight_for("groups", "ldap")

        assert result == pytest.approx(0.70), (
            f"Expected defaults.source_weights.ldap == 0.70, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: defaults.source_weights.ldap: 0.7."
        )

    def test_defaults_source_weights_saml_is_0_60(self, cfg) -> None:
        """defaults.source_weights.saml == 0.60 (accessible via groups fallback)."""
        result = cfg.weight_for("groups", "saml")

        assert result == pytest.approx(0.60), (
            f"Expected defaults.source_weights.saml == 0.60, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: defaults.source_weights.saml: 0.6."
        )

    def test_defaults_source_weights_oidc_is_0_80(self, cfg) -> None:
        """defaults.source_weights.oidc == 0.80 (accessible via groups fallback)."""
        result = cfg.weight_for("groups", "oidc")

        assert result == pytest.approx(0.80), (
            f"Expected defaults.source_weights.oidc == 0.80, got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: defaults.source_weights.oidc: 0.8."
        )


# ===========================================================================
# CLASS 3 — §5.6 priority lists (TRANSCRIBE EXACTLY)
# ===========================================================================


class TestCommittedYamlPriorities:
    """Priority lists from the committed config must match §5.6 exactly.

    WHY: Priority order is the tiebreaker when sources disagree. An incorrect
    order (e.g. ['oidc', 'ldap', 'saml'] instead of ['ldap', 'oidc', 'saml'] for
    department) means a lower-authority source wins conflicts — potentially
    allowing a stale OIDC claim to override the nightly HR sync.
    """

    @pytest.fixture(scope="class")
    def cfg(self):
        """Load the committed config once for all priority tests."""
        from app.normalization_config import load_config

        return load_config(CONFIG_PATH)

    def test_department_priority_is_ldap_oidc_saml(self, cfg) -> None:
        """priority_for('department') == ['ldap', 'oidc', 'saml'].

        WHY: LDAP is nightly HR sync; OIDC is current-login data; SAML may be stale.
        This ordering is §5.6's documented intent ('LDAP synced nightly from HR; OIDC
        updated on login; SAML may be stale').
        """
        result = cfg.priority_for("department")

        assert result == ["ldap", "oidc", "saml"], (
            f"Expected priority_for('department') == ['ldap', 'oidc', 'saml'], got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: department.priority: [ldap, oidc, saml]."
        )

    def test_primary_email_priority_is_oidc_saml_ldap(self, cfg) -> None:
        """priority_for('primary_email') == ['oidc', 'saml', 'ldap'].

        WHY: OIDC has the most current email from a recent SSO migration. LDAP email
        may lag behind. Using LDAP as priority-1 would risk resolving a stale email
        address for every conflict.
        """
        result = cfg.priority_for("primary_email")

        assert result == ["oidc", "saml", "ldap"], (
            f"Expected priority_for('primary_email') == ['oidc', 'saml', 'ldap'], got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: primary_email.priority: [oidc, saml, ldap]."
        )

    def test_display_name_priority_is_oidc_saml_ldap(self, cfg) -> None:
        """priority_for('display_name') == ['oidc', 'saml', 'ldap'].

        WHY: OIDC tokens carry the most current display name from the login provider;
        LDAP may lag behind preferred-name changes.
        """
        result = cfg.priority_for("display_name")

        assert result == ["oidc", "saml", "ldap"], (
            f"Expected priority_for('display_name') == ['oidc', 'saml', 'ldap'], got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: display_name.priority: [oidc, saml, ldap]."
        )

    def test_employee_type_priority_is_ldap_saml_oidc(self, cfg) -> None:
        """priority_for('employee_type') == ['ldap', 'saml', 'oidc'].

        WHY: HR system (LDAP) is authoritative for employment classification.
        This attribute affects access rights — the highest-authority source must win.
        """
        result = cfg.priority_for("employee_type")

        assert result == ["ldap", "saml", "oidc"], (
            f"Expected priority_for('employee_type') == ['ldap', 'saml', 'oidc'], got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: employee_type.priority: [ldap, saml, oidc]."
        )

    def test_groups_has_no_priority_list(self, cfg) -> None:
        """priority_for('groups') returns [] because groups has no priority block in §5.6.

        WHY: groups uses ListMergeResolution, not PriorityResolution. Its §5.6 entry
        has only merge_strategy and rationale. priority_for must return [] rather than
        raising or returning None.
        """
        result = cfg.priority_for("groups")

        assert result == [], (
            f"Expected priority_for('groups') == [], got {result!r}. "
            "Spec §5.6: groups entry has no priority block — only merge_strategy."
        )


# ===========================================================================
# CLASS 4 — §5.6 merge strategy
# ===========================================================================


class TestCommittedYamlMergeStrategy:
    """merge_strategy_for from the committed config must match §5.6."""

    @pytest.fixture(scope="class")
    def cfg(self):
        """Load the committed config once for merge strategy tests."""
        from app.normalization_config import load_config

        return load_config(CONFIG_PATH)

    def test_groups_merge_strategy_is_union(self, cfg) -> None:
        """merge_strategy_for('groups') == 'union'.

        WHY: §5.6: 'merge_strategy: union' for groups. The rationale is
        'Groups from all sources are valid; a user may hold roles in each system.'
        Using 'intersection' instead of 'union' would silently drop group
        memberships that are not present in all sources.
        """
        result = cfg.merge_strategy_for("groups")

        assert result == "union", (
            f"Expected merge_strategy_for('groups') == 'union', got {result!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: groups.merge_strategy: union."
        )


# ===========================================================================
# CLASS 5 — §5.6 enrichment block scalar values
# ===========================================================================


class TestCommittedYamlEnrichment:
    """Enrichment block values from the committed config must match §5.6 exactly.

    WHY: These scalars drive runtime behaviour:
    - enabled: false would disable all LDAP enrichment
    - correlation_key: wrong value means every LDAP query targets the wrong attribute
    - timeout_ms: too low causes spurious ldap_timeout skip reasons
    - on_failure: wrong value changes error handling semantics
    - cache_ttl_seconds: wrong value changes cache duration
    All are set to specific values in §5.6 and must survive round-tripping.
    """

    @pytest.fixture(scope="class")
    def cfg(self):
        """Load the committed config once for enrichment tests."""
        from app.normalization_config import load_config

        return load_config(CONFIG_PATH)

    def _get_ldap_cfg(self, cfg):
        """Extract the LDAP enrichment sub-config regardless of attribute path."""
        try:
            return cfg.enrichment.sources.ldap  # type: ignore[attr-defined]
        except AttributeError:
            try:
                return cfg.enrichment.sources["ldap"]  # type: ignore[index]
            except (AttributeError, KeyError, TypeError):
                pytest.fail(
                    "Cannot access LDAP enrichment sub-config via "
                    "cfg.enrichment.sources.ldap or cfg.enrichment.sources['ldap']. "
                    "NormalizationConfig must expose the LDAP enrichment block."
                )

    def test_enrichment_enabled_is_true(self, cfg) -> None:
        """enrichment.sources.ldap.enabled == True.

        WHY: §5.6 default is 'enabled: true'. If False, enrichment is permanently
        disabled — no OIDC/SAML event would ever get enriched.
        """
        ldap_cfg = self._get_ldap_cfg(cfg)

        assert ldap_cfg.enabled is True, (
            f"Expected enrichment.sources.ldap.enabled == True, got {ldap_cfg.enabled!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: enabled: true."
        )

    def test_enrichment_correlation_key_is_primary_email(self, cfg) -> None:
        """enrichment.sources.ldap.correlation_key == 'primary_email'.

        WHY: §5.6: 'correlation_key: primary_email'. This is the unified field used
        to look up the user in LDAP (reverse-mapped to 'mail'). Any other value would
        search LDAP by the wrong attribute (e.g. searching by display_name instead
        of email address).
        """
        ldap_cfg = self._get_ldap_cfg(cfg)

        assert ldap_cfg.correlation_key == "primary_email", (
            f"Expected enrichment.sources.ldap.correlation_key == 'primary_email', "
            f"got {ldap_cfg.correlation_key!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: correlation_key: primary_email."
        )

    def test_enrichment_timeout_ms_is_2000(self, cfg) -> None:
        """enrichment.sources.ldap.timeout_ms == 2000.

        WHY: §5.6 default. A lower timeout causes spurious ldap_timeout failures;
        too high means LDAP outages stall the normalization pipeline.
        """
        ldap_cfg = self._get_ldap_cfg(cfg)

        assert ldap_cfg.timeout_ms == 2000, (
            f"Expected enrichment.sources.ldap.timeout_ms == 2000, got {ldap_cfg.timeout_ms!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: timeout_ms: 2000."
        )

    def test_enrichment_on_failure_is_continue(self, cfg) -> None:
        """enrichment.sources.ldap.on_failure == 'continue'.

        WHY: §5.6 default. 'continue' means graceful degradation (ADR-0008).
        If this were 'fail', any LDAP outage would reject all OIDC/SAML events.
        """
        ldap_cfg = self._get_ldap_cfg(cfg)

        assert ldap_cfg.on_failure == "continue", (
            f"Expected enrichment.sources.ldap.on_failure == 'continue', "
            f"got {ldap_cfg.on_failure!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: on_failure: continue."
        )

    def test_enrichment_cache_ttl_seconds_is_60(self, cfg) -> None:
        """enrichment.sources.ldap.cache_ttl_seconds == 60.

        WHY: §5.6 default. 60s is the Redis cache TTL for LDAP results (also
        mentioned in CLAUDE.md: 'Cached in Redis (60s TTL)'). If this were 0,
        caching would be effectively disabled and every login would hit LDAP.
        """
        ldap_cfg = self._get_ldap_cfg(cfg)

        assert ldap_cfg.cache_ttl_seconds == 60, (
            f"Expected enrichment.sources.ldap.cache_ttl_seconds == 60, "
            f"got {ldap_cfg.cache_ttl_seconds!r}. "
            "Spec §5.6 [TRANSCRIBE EXACTLY]: cache_ttl_seconds: 60."
        )

    def test_enrichment_enrich_attributes_is_none_or_absent(self, cfg) -> None:
        """enrichment.sources.ldap.enrich_attributes is None or absent (commented out in §5.6).

        WHY: §5.6 comments out the enrich_attributes block: '# enrich_attributes: ...'.
        The committed file must not include it, meaning the config object has None or
        the attribute is absent. If it were populated with an invalid value, load_config
        would raise and the service would not start.
        """
        ldap_cfg = self._get_ldap_cfg(cfg)

        enrich_attrs = getattr(ldap_cfg, "enrich_attributes", None)

        assert enrich_attrs is None, (
            f"Expected enrichment.sources.ldap.enrich_attributes to be None "
            f"(commented out in §5.6), got {enrich_attrs!r}. "
            "The committed config must not include enrich_attributes."
        )
