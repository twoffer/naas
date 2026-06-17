"""Spec 0 documentation mirrors Spec 2 additions: LDAP cache prefix and pool size field."""

# third-party
import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery
# ---------------------------------------------------------------------------
from tests.helpers import REPO_ROOT

SPEC_0_PATH = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "SPEC_0_Project_Scaffold_and_Shared_Foundation.md"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_spec0() -> str:
    """Read SPEC_0 content or raise a clear error if the file is missing."""
    if not SPEC_0_PATH.exists():
        pytest.skip(f"SPEC_0 not found at {SPEC_0_PATH} — cannot validate mirrors")
    return SPEC_0_PATH.read_text(encoding="utf-8")


def _section_content_after(full_text: str, section_header: str) -> str:
    """Return text starting from the first occurrence of section_header.

    Used to constrain assertions to the correct section, preventing a line
    placed in the wrong section from passing a presence-only check.
    """
    idx = full_text.find(section_header)
    if idx == -1:
        return ""
    return full_text[idx:]


# ===========================================================================
# CLASS 1 — §3.3 mirror: LDAP_ENRICHMENT_CACHE_PREFIX
# ===========================================================================


class TestSpec0Section33CachePrefixMirror:
    """SPEC_0 §3.3 must contain the LDAP_ENRICHMENT_CACHE_PREFIX mirror line.

    WHY: §3.3 is the canonical documentation of all cache prefixes defined in
    naas_shared/constants.py. Adding a constant to the code without adding the
    matching line to SPEC_0 breaks the spec/code synchrony guarantee stated in
    spec §1. The risk-evaluator, signal-enrichment, and any future service that
    reads SPEC_0 to understand the cache key namespace would have an incomplete
    picture, leading to potential key collisions or incorrect TTL assumptions.
    """

    def test_spec0_contains_ldap_enrichment_cache_prefix_string(self) -> None:
        """SPEC_0 must contain 'LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"'.

        This is the exact line that §1 mandates be in §3.3. A missing or
        misspelled line fails this test with a clear AssertionError.
        """
        content = _read_spec0()
        target_line = 'LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"'

        assert target_line in content, (
            f"SPEC_0 §3.3 must contain the mirror line:\n"
            f"  {target_line!r}\n"
            f"but it was not found. Add it to the cache prefix block in §3.3 "
            f"(### 3.3 Redis Stream and Channel Names / Constants)."
        )

    def test_spec0_ldap_prefix_appears_in_section_33(self) -> None:
        """The mirror line must appear AFTER the §3.3 section header.

        WHY: A line placed in §3.8 or elsewhere would satisfy a plain presence
        check but would not be in the correct section. This test constrains
        placement so readers can find the constant in the right context.
        """
        content = _read_spec0()
        section_header = "### 3.3"

        section_text = _section_content_after(content, section_header)
        target_line = 'LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"'

        assert section_header in content, (
            f"Section '### 3.3' not found in SPEC_0 at {SPEC_0_PATH}"
        )
        assert target_line in section_text, (
            f"'{target_line}' must appear in or after '### 3.3' in SPEC_0, "
            f"but it was not found in that section's text."
        )

    def test_spec0_section_33_still_contains_existing_prefixes(self) -> None:
        """Adding the new mirror must not remove existing cache prefixes from §3.3.

        WHY: Surgical addition only — do not disturb the pre-existing CACHE_IP_REP_PREFIX,
        CACHE_GEO_PREFIX, CACHE_JWKS, CACHE_POLICY_ACTIVE lines that other services
        depend on as documentation.
        """
        content = _read_spec0()

        pre_existing = [
            'CACHE_IP_REP_PREFIX = "ip_rep:"',
            'CACHE_GEO_PREFIX = "geo:"',
            'CACHE_JWKS = "jwks:keycloak"',
            'CACHE_POLICY_ACTIVE = "policy:active"',
        ]

        for line in pre_existing:
            assert line in content, (
                f"Pre-existing SPEC_0 §3.3 line was removed during the mirror addition: "
                f"{line!r}. The addition must be additive-only."
            )


# ===========================================================================
# CLASS 2 — §3.8 mirror: ldap_pool_size field
# ===========================================================================


class TestSpec0Section38LdapPoolSizeMirror:
    """SPEC_0 §3.8 must contain the ldap_pool_size field mirror line.

    WHY: §3.8 is the canonical documentation of the Settings class defined in
    naas_shared/config.py. Any service implementing LDAP-backed features reads
    SPEC_0 §3.8 to understand what configuration is available. Without the
    ldap_pool_size mirror, a new service author would not know the field exists
    and would either hardcode a pool size or raise AttributeError at runtime.
    """

    def test_spec0_contains_ldap_pool_size_field_line(self) -> None:
        """SPEC_0 must contain 'ldap_pool_size: int = Field(default=3, ge=1, le=10)'.

        This is the exact line that §1 mandates be in §3.8. The exact string
        includes the Field constraints so readers understand the validation rules
        directly from the spec without having to read the source code.
        """
        content = _read_spec0()
        target_line = "ldap_pool_size: int = Field(default=3, ge=1, le=10)"

        assert target_line in content, (
            f"SPEC_0 §3.8 must contain the mirror line:\n"
            f"  {target_line!r}\n"
            f"but it was not found. Add it to the LDAP block in §3.8 "
            f"(### 3.8 Shared Config Module)."
        )

    def test_spec0_ldap_pool_size_appears_in_section_38(self) -> None:
        """The mirror line must appear AFTER the §3.8 section header.

        WHY: Same rationale as the §3.3 placement check — prevent a line in the
        wrong section from silently satisfying a presence-only assertion.
        """
        content = _read_spec0()
        section_header = "### 3.8"

        section_text = _section_content_after(content, section_header)
        target_line = "ldap_pool_size: int = Field(default=3, ge=1, le=10)"

        assert section_header in content, (
            f"Section '### 3.8' not found in SPEC_0 at {SPEC_0_PATH}"
        )
        assert target_line in section_text, (
            f"'{target_line}' must appear in or after '### 3.8' in SPEC_0, "
            f"but it was not found in that section's text."
        )

    def test_spec0_section_38_still_contains_existing_ldap_fields(self) -> None:
        """Adding ldap_pool_size must not remove the existing LDAP Settings fields.

        WHY: The existing ldap_host, ldap_port, ldap_base_dn, ldap_admin_dn, and
        ldap_admin_password fields are already in §3.8. The new ldap_pool_size
        must be added beside them, not in place of them. A missing pre-existing
        field would cause implementers reading SPEC_0 to miss a required Setting.
        """
        content = _read_spec0()

        pre_existing_fields = [
            'ldap_host: str = "openldap"',
            "ldap_port: int = 389",
        ]

        for field_snippet in pre_existing_fields:
            assert field_snippet in content, (
                f"Pre-existing SPEC_0 §3.8 LDAP field was removed: {field_snippet!r}. "
                f"The ldap_pool_size addition must be additive-only."
            )

    def test_spec0_ldap_pool_size_appears_near_other_ldap_fields(self) -> None:
        """ldap_pool_size must appear in the same region as ldap_host and ldap_port.

        WHY: Spec §1 says 'add ldap_pool_size to the Settings snippet's LDAP block'.
        This test verifies co-location: ldap_pool_size must appear after ldap_host
        (i.e., it is in the LDAP block, not at the end of the config class).
        """
        content = _read_spec0()

        ldap_host_pos = content.find('ldap_host: str = "openldap"')
        pool_size_pos = content.find(
            "ldap_pool_size: int = Field(default=3, ge=1, le=10)"
        )

        if ldap_host_pos == -1:
            pytest.skip(
                "ldap_host line not found in SPEC_0 — pre-existing fields check failed first"
            )

        assert pool_size_pos != -1, "ldap_pool_size line not found in SPEC_0"

        # ldap_pool_size should appear within ~500 characters of ldap_host
        # (same Settings LDAP block, not at the end of an unrelated section)
        distance = pool_size_pos - ldap_host_pos
        assert 0 < distance < 500, (
            f"ldap_pool_size must appear near the other LDAP fields in §3.8. "
            f"Distance from ldap_host: {distance} chars. "
            f"Expected it to follow ldap_host within ~500 chars (same LDAP block)."
        )
