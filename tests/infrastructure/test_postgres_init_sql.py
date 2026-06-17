# Verifies infrastructure/postgres/init.sql DDL contract.
#
# Checks: existence, SQL parsability (sqlparse optional), pgcrypto extension,
# CREATE TABLE count and names, events/risk_assessments columns and constraints,
# six required indexes, seed INSERT, embedded policy YAML values, SQL string
# escaping (doubled single-quotes inside YAML literal), and absence of CREATE DATABASE.

# stdlib
import re

# third-party
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from tests.helpers import REPO_ROOT

INIT_SQL_PATH = REPO_ROOT / "infrastructure" / "postgres" / "init.sql"


# ---------------------------------------------------------------------------
# Module-scoped fixtures — read files once per test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def init_sql_text() -> str:
    """Read init.sql content once for the whole module.

    If the file does not exist, skip all content tests — the existence test
    will already report FAILED, and we don't want a cascade of ERROR results
    obscuring it.
    """
    if not INIT_SQL_PATH.exists():
        pytest.skip("infrastructure/postgres/init.sql not found")
    return INIT_SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def init_sql_upper(init_sql_text: str) -> str:
    """Upper-cased version of init.sql for case-insensitive checks."""
    return init_sql_text.upper()


# ---------------------------------------------------------------------------
# init.sql — existence
# ---------------------------------------------------------------------------


class TestInitSqlExists:
    """Verify infrastructure/postgres/init.sql is present."""

    def test_postgres_directory_exists(self):
        """
        infrastructure/postgres/ directory must exist.
        Missing directory means the entire Postgres init path is absent.
        """
        pg_dir = REPO_ROOT / "infrastructure" / "postgres"
        assert pg_dir.exists(), (
            f"infrastructure/postgres/ directory not found at {pg_dir}"
        )
        assert pg_dir.is_dir(), f"{pg_dir} exists but is not a directory"

    def test_init_sql_file_exists(self):
        """
        infrastructure/postgres/init.sql must exist.
        The Docker Compose postgres service mounts it as the entrypoint init script;
        without it the database starts empty and every service fails on first query.
        """
        assert INIT_SQL_PATH.exists(), (
            f"infrastructure/postgres/init.sql not found at {INIT_SQL_PATH}"
        )

    def test_init_sql_is_a_file_not_directory(self):
        """Guard against accidental creation of an init.sql/ directory."""
        assert INIT_SQL_PATH.is_file(), (
            f"{INIT_SQL_PATH} exists but is not a regular file"
        )


# ---------------------------------------------------------------------------
# init.sql — valid SQL parse (skipped cleanly if sqlparse not installed)
# ---------------------------------------------------------------------------


class TestInitSqlParses:
    """Verify init.sql is syntactically parseable as SQL.

    Uses pytest.importorskip so the test is skipped (not errored) when sqlparse
    is not installed. All structural checks below do NOT depend on sqlparse.
    """

    def test_init_sql_parses_without_error(self, init_sql_text: str):
        """
        init.sql must parse without error using sqlparse.
        A parse failure would indicate a syntax error that Postgres would reject
        at startup, preventing any tables from being created.

        This test is SKIPPED (not FAILED) if sqlparse is not installed.
        """
        sqlparse = pytest.importorskip(
            "sqlparse",
            reason="sqlparse not installed — SQL parse test skipped; install with: pip install sqlparse",
        )
        statements = sqlparse.parse(init_sql_text)
        assert len(statements) > 0, (
            "sqlparse returned zero statements — init.sql may be empty or unparseable"
        )
        # Every non-whitespace statement should have at least one token
        non_empty = [
            s for s in statements if s.get_type() is not None or str(s).strip()
        ]
        assert len(non_empty) > 0, (
            "sqlparse found no meaningful SQL statements in init.sql"
        )


# ---------------------------------------------------------------------------
# init.sql — pgcrypto extension
# ---------------------------------------------------------------------------


class TestInitSqlExtension:
    """Verify the pgcrypto extension is enabled."""

    def test_pgcrypto_extension_present(self, init_sql_text: str):
        """
        init.sql must contain: CREATE EXTENSION IF NOT EXISTS "pgcrypto"
        This enables gen_random_uuid() used as the default for every PK column.
        Without it, every INSERT that relies on gen_random_uuid() fails.
        """
        assert 'CREATE EXTENSION IF NOT EXISTS "pgcrypto"' in init_sql_text, (
            "Expected 'CREATE EXTENSION IF NOT EXISTS \"pgcrypto\"' in init.sql. "
            "Without this, gen_random_uuid() is unavailable and all INSERTs fail."
        )


# ---------------------------------------------------------------------------
# init.sql — CREATE TABLE statements (exactly 5, correct names)
# ---------------------------------------------------------------------------


class TestInitSqlCreateTables:
    """Verify exactly five tables are created with the canonical names."""

    def test_exactly_five_create_table_statements(self, init_sql_text: str):
        """
        init.sql must contain exactly 5 CREATE TABLE statements.
        More or fewer indicates a missing or extra table that breaks
        downstream service assumptions about the schema.
        """
        # Match 'CREATE TABLE IF NOT EXISTS <name>' case-insensitively.
        # Capture the table name to report which tables were found.
        pattern = re.compile(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)",
            re.IGNORECASE,
        )
        found_tables = [m.group(1).lower() for m in pattern.finditer(init_sql_text)]
        assert len(found_tables) == 5, (
            f"Expected exactly 5 CREATE TABLE IF NOT EXISTS statements, "
            f"found {len(found_tables)}: {found_tables}"
        )

    def test_create_table_names_match_expected_set(self, init_sql_text: str):
        """
        The five tables must be exactly: users, events, policies,
        risk_assessments, alerts.  Any deviation breaks the SQLAlchemy ORM
        models in naas_shared/schemas.py and every service that queries them.
        """
        pattern = re.compile(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)",
            re.IGNORECASE,
        )
        found_tables = {m.group(1).lower() for m in pattern.finditer(init_sql_text)}
        expected_tables = {"users", "events", "policies", "risk_assessments", "alerts"}
        assert found_tables == expected_tables, (
            f"Expected tables {expected_tables}, found {found_tables}. "
            f"Missing: {expected_tables - found_tables}. "
            f"Extra: {found_tables - expected_tables}."
        )


# ---------------------------------------------------------------------------
# init.sql — events table columns and constraints
# ---------------------------------------------------------------------------


class TestInitSqlEventsTable:
    """Verify the events table has required columns and CHECK constraints."""

    def test_events_table_has_user_agent_column(self, init_sql_text: str):
        """
        The events table must have a user_agent column.
        Spec architect's note (Gap 2): SYSTEM_ARCHITECTURE.md listed this column
        but the original Implementation Guide DDL omitted it.  The normalization
        service and dashboard both need user_agent for device fingerprinting.
        """
        # Look for 'user_agent' within the events table block.
        # We search the full text case-insensitively; the column name is
        # unambiguous (no other table uses it).
        assert re.search(r"\buser_agent\b", init_sql_text, re.IGNORECASE), (
            "events table is missing 'user_agent' column. "
            "This column is required per SYSTEM_ARCHITECTURE.md and Gap 2 resolution."
        )

    def test_events_table_protocol_check_contains_oidc(self, init_sql_text: str):
        """
        The protocol CHECK constraint must include 'oidc'.
        This restricts protocol to valid values and prevents silent data corruption.
        """
        assert "'oidc'" in init_sql_text, (
            "Expected CHECK constraint value 'oidc' in init.sql events table"
        )

    def test_events_table_protocol_check_contains_saml(self, init_sql_text: str):
        """
        The protocol CHECK constraint must include 'saml'.
        """
        assert "'saml'" in init_sql_text, (
            "Expected CHECK constraint value 'saml' in init.sql events table"
        )

    def test_events_table_protocol_check_contains_ldap(self, init_sql_text: str):
        """
        The protocol CHECK constraint must include 'ldap'.
        """
        assert "'ldap'" in init_sql_text, (
            "Expected CHECK constraint value 'ldap' in init.sql events table"
        )

    def test_events_table_protocol_check_constraint_present(self, init_sql_text: str):
        """
        The protocol column must have a CHECK constraint that lists all three
        valid protocol values inline: CHECK (protocol IN ('oidc', 'saml', 'ldap')).
        This is the complete constraint — missing any value silently allows
        bad data that breaks normalization pipeline routing.
        """
        # Match the CHECK constraint for protocol regardless of whitespace.
        pattern = re.compile(
            r"protocol\s+\w+.*?CHECK\s*\(\s*protocol\s+IN\s*\("
            r"['\"]oidc['\"],\s*['\"]saml['\"],\s*['\"]ldap['\"]\s*\)\s*\)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(init_sql_text), (
            "Expected events.protocol CHECK (protocol IN ('oidc', 'saml', 'ldap')) "
            "in init.sql. All three values must be present in the constraint."
        )

    def test_events_table_created_at_is_timestamptz(self, init_sql_text: str) -> None:
        """events.created_at must be declared TIMESTAMPTZ in init.sql.

        WHY: TIMESTAMPTZ stores a UTC instant regardless of the PostgreSQL session
        timezone, making the ingestion timestamp deterministic across deployments.
        The plain TIMESTAMP type would store a wall-clock value that is ambiguous
        when the session timezone differs from UTC — a silent data-corruption risk
        for downstream risk and alert services that compare timestamps.
        We scope the check to the events table block so this guard pins the events
        contract specifically, independent of the other tables' created_at columns
        (all of which are now also TIMESTAMPTZ).
        """
        # Extract just the events table CREATE TABLE block so this assertion stays
        # specific to events rather than matching any TIMESTAMPTZ occurrence.
        events_block_match = re.search(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+events\s*\(.*?\);",
            init_sql_text,
            re.IGNORECASE | re.DOTALL,
        )
        assert events_block_match, (
            "Could not find the events CREATE TABLE block in init.sql."
        )
        events_block = events_block_match.group(0)
        assert re.search(
            r"\bcreated_at\s+TIMESTAMPTZ\b", events_block, re.IGNORECASE
        ), (
            "events.created_at must be declared as TIMESTAMPTZ in init.sql. "
            "Plain TIMESTAMP is not safe when the Postgres session timezone may differ from UTC."
        )


# ---------------------------------------------------------------------------
# init.sql — risk_assessments table columns and constraints
# ---------------------------------------------------------------------------


class TestInitSqlRiskAssessmentsTable:
    """Verify risk_assessments has shadow columns and decision CHECK."""

    def test_risk_assessments_has_shadow_decision_column(self, init_sql_text: str):
        """
        risk_assessments must have a shadow_decision column.
        Spec architect's note (Gap 3): SYSTEM_ARCHITECTURE.md defines shadow mode
        columns but the Implementation Guide DDL omitted them.
        Shadow mode lets policy changes be evaluated without affecting real decisions.
        """
        assert re.search(r"\bshadow_decision\b", init_sql_text, re.IGNORECASE), (
            "risk_assessments table is missing 'shadow_decision' column. "
            "This column is required for shadow mode policy evaluation (Gap 3)."
        )

    def test_risk_assessments_has_shadow_score_column(self, init_sql_text: str):
        """
        risk_assessments must have a shadow_score column.
        Required alongside shadow_decision for full shadow mode support.
        """
        assert re.search(r"\bshadow_score\b", init_sql_text, re.IGNORECASE), (
            "risk_assessments table is missing 'shadow_score' column. "
            "Required for shadow mode policy evaluation (Gap 3)."
        )

    def test_risk_assessments_decision_check_contains_allow(self, init_sql_text: str):
        """The decision CHECK constraint must include 'allow'."""
        assert "'allow'" in init_sql_text, (
            "Expected CHECK constraint value 'allow' for risk_assessments.decision"
        )

    def test_risk_assessments_decision_check_contains_step_up_mfa(
        self, init_sql_text: str
    ):
        """The decision CHECK constraint must include 'step_up_mfa'."""
        assert "'step_up_mfa'" in init_sql_text, (
            "Expected CHECK constraint value 'step_up_mfa' for risk_assessments.decision"
        )

    def test_risk_assessments_decision_check_contains_deny(self, init_sql_text: str):
        """The decision CHECK constraint must include 'deny'."""
        assert "'deny'" in init_sql_text, (
            "Expected CHECK constraint value 'deny' for risk_assessments.decision"
        )

    def test_risk_assessments_decision_check_constraint_present(
        self, init_sql_text: str
    ):
        """
        The decision column must have a CHECK constraint listing all three valid
        decisions: allow, step_up_mfa, deny.
        These must align exactly with the Literal["allow", "step_up_mfa", "deny"]
        in naas_shared/models.py RiskDecision — any mismatch causes DB-layer
        constraint violations at runtime.
        """
        pattern = re.compile(
            r"decision\s+\w+.*?CHECK\s*\(\s*decision\s+IN\s*\("
            r"['\"]allow['\"],\s*['\"]step_up_mfa['\"],\s*['\"]deny['\"]\s*\)\s*\)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(init_sql_text), (
            "Expected risk_assessments.decision CHECK (decision IN "
            "('allow', 'step_up_mfa', 'deny')) in init.sql."
        )


# ---------------------------------------------------------------------------
# init.sql — indexes (six required)
# ---------------------------------------------------------------------------

EXPECTED_INDEXES = [
    "idx_events_user_id",
    "idx_events_timestamp",
    "idx_events_protocol",
    "idx_risk_assessments_event_id",
    "idx_risk_assessments_decision",
    "idx_alerts_status",
]


class TestInitSqlIndexes:
    """Verify all six required indexes are present."""

    @pytest.mark.parametrize("index_name", EXPECTED_INDEXES)
    def test_expected_index_present(self, index_name: str, init_sql_text: str):
        """
        Each of the six indexes must appear in init.sql by name.
        Missing indexes cause full-table scans on frequently queried columns —
        the dashboard and alert service rely on these for sub-100ms query times
        under realistic event volumes.
        """
        assert index_name in init_sql_text, (
            f"Expected index '{index_name}' not found in init.sql. "
            f"All six indexes are required: {EXPECTED_INDEXES}"
        )

    def test_exactly_six_create_index_statements(self, init_sql_text: str):
        """
        init.sql must contain exactly 6 CREATE INDEX statements.
        More indexes bloat writes; fewer leave critical queries without coverage.
        """
        pattern = re.compile(r"^\s*CREATE\s+INDEX\s+\w+", re.IGNORECASE | re.MULTILINE)
        found = pattern.findall(init_sql_text)
        assert len(found) == 6, (
            f"Expected exactly 6 CREATE INDEX statements, found {len(found)}. "
            f"Required indexes: {EXPECTED_INDEXES}"
        )


# ---------------------------------------------------------------------------
# init.sql — seed INSERT into policies
# ---------------------------------------------------------------------------


class TestInitSqlSeedInsert:
    """Verify the seed INSERT for the default policy."""

    def test_seed_insert_targets_policies_table(self, init_sql_text: str):
        """
        The seed INSERT must target the policies table.
        Without it the risk-evaluator starts with no active policy and
        fails every event assessment.
        """
        pattern = re.compile(r"INSERT\s+INTO\s+policies\b", re.IGNORECASE)
        assert pattern.search(init_sql_text), (
            "Expected 'INSERT INTO policies' statement in init.sql"
        )

    def test_seed_insert_contains_policy_id_default_v1(self, init_sql_text: str):
        """
        The seed INSERT must use policy_id value 'default-v1'.
        This is the stable identifier used by the policy-management service
        to locate the active policy at startup.
        """
        assert "'default-v1'" in init_sql_text, (
            "Expected policy_id value 'default-v1' in the seed INSERT. "
            "The risk-evaluator looks up 'default-v1' on startup."
        )

    def test_seed_insert_sets_is_active_true(self, init_sql_text: str):
        """
        The seed INSERT must set is_active to TRUE.
        A seed policy with is_active=FALSE would leave the system with no
        active policy and cause every risk assessment to fail.
        """
        # Look for TRUE as a SQL keyword (case-insensitive), not 'true' string literal.
        # The value appears as: TRUE, (not 'TRUE')
        assert re.search(r"\bTRUE\b", init_sql_text), (
            "Expected 'TRUE' (boolean, not string) for is_active in the seed INSERT"
        )

    def test_seed_insert_has_on_conflict_do_nothing(self, init_sql_text: str):
        """
        The seed INSERT must have ON CONFLICT (policy_id) DO NOTHING.
        Without this, re-running init.sql (e.g., on container restart with
        persistent volume) causes a duplicate-key error that breaks startup.
        """
        # Check both parts of the clause
        assert re.search(
            r"ON\s+CONFLICT\s*\(\s*policy_id\s*\)\s+DO\s+NOTHING",
            init_sql_text,
            re.IGNORECASE,
        ), (
            "Expected 'ON CONFLICT (policy_id) DO NOTHING' in the seed INSERT. "
            "Without this, re-running init.sql fails with a duplicate key error."
        )


# ---------------------------------------------------------------------------
# init.sql — embedded policy YAML content
# ---------------------------------------------------------------------------


class TestInitSqlEmbeddedYaml:
    """Verify the embedded YAML inside the seed INSERT has required fields and values."""

    def test_embedded_yaml_contains_signal_weights(self, init_sql_text: str):
        """
        The policy YAML inside the INSERT must contain 'signal_weights'.
        This key is required by the risk-evaluator's hybrid scoring engine.
        """
        assert "signal_weights:" in init_sql_text, (
            "Expected 'signal_weights:' in the embedded policy YAML inside the seed INSERT"
        )

    def test_embedded_yaml_contains_conditions(self, init_sql_text: str):
        """
        The policy YAML must contain 'conditions'.
        Conditions are the rule-based part of hybrid scoring;
        missing this key causes KeyError in the risk-evaluator.
        """
        assert "conditions:" in init_sql_text, (
            "Expected 'conditions:' in the embedded policy YAML inside the seed INSERT"
        )

    def test_embedded_yaml_contains_thresholds(self, init_sql_text: str):
        """
        The policy YAML must contain 'thresholds'.
        Thresholds define the allow/step_up_mfa/deny decision boundaries.
        """
        assert "thresholds:" in init_sql_text, (
            "Expected 'thresholds:' in the embedded policy YAML inside the seed INSERT"
        )

    def test_embedded_yaml_step_up_mfa_threshold_is_0_3(self, init_sql_text: str):
        """
        The thresholds section must have step_up_mfa: 0.3.
        This is the exact boundary between ALLOW and STEP_UP_MFA decisions.
        A score of 0.300 triggers MFA; 0.299 allows.
        Any deviation shifts the entire risk threshold calibration.
        """
        assert "step_up_mfa: 0.3" in init_sql_text, (
            "Expected 'step_up_mfa: 0.3' in the embedded policy YAML thresholds section. "
            "This value must be exactly 0.3, not 0.30 or 0.300."
        )

    def test_embedded_yaml_deny_threshold_is_0_7(self, init_sql_text: str):
        """
        The thresholds section must have deny: 0.7.
        This is the exact boundary between STEP_UP_MFA and DENY decisions.
        A score of 0.700 triggers DENY; 0.699 triggers MFA.
        """
        assert "deny: 0.7" in init_sql_text, (
            "Expected 'deny: 0.7' in the embedded policy YAML thresholds section. "
            "This value must be exactly 0.7."
        )

    def test_embedded_yaml_contains_ensemble(self, init_sql_text: str):
        """
        The policy YAML must contain 'ensemble'.
        The ensemble section configures the rule/ML weight split.
        """
        assert "ensemble:" in init_sql_text, (
            "Expected 'ensemble:' in the embedded policy YAML inside the seed INSERT"
        )

    def test_embedded_yaml_rule_weight_is_0_6(self, init_sql_text: str):
        """
        The ensemble section must have rule_weight: 0.6.
        Rule weight + ml_weight must sum to 1.0 per the scoring contract.
        0.6 rule weight gives rule-based scoring dominant influence.
        """
        assert "rule_weight: 0.6" in init_sql_text, (
            "Expected 'rule_weight: 0.6' in the embedded policy YAML ensemble section"
        )

    def test_embedded_yaml_ml_weight_is_0_4(self, init_sql_text: str):
        """
        The ensemble section must have ml_weight: 0.4.
        rule_weight (0.6) + ml_weight (0.4) = 1.0 — required invariant.
        """
        assert "ml_weight: 0.4" in init_sql_text, (
            "Expected 'ml_weight: 0.4' in the embedded policy YAML ensemble section"
        )

    def test_embedded_yaml_weights_sum_to_one(self, init_sql_text: str):
        """
        rule_weight + ml_weight must equal exactly 1.0.
        This test guards against a transcription where both values were changed
        but their sum was neglected. Uses float arithmetic to verify.
        """
        rule_match = re.search(r"rule_weight:\s+([\d.]+)", init_sql_text)
        ml_match = re.search(r"ml_weight:\s+([\d.]+)", init_sql_text)
        assert rule_match and ml_match, (
            "Could not find both rule_weight and ml_weight in init.sql"
        )
        rule_w = float(rule_match.group(1))
        ml_w = float(ml_match.group(1))
        total = rule_w + ml_w
        assert abs(total - 1.0) < 1e-9, (
            f"rule_weight ({rule_w}) + ml_weight ({ml_w}) = {total}, expected 1.0. "
            "Weights must sum to exactly 1.0."
        )


# ---------------------------------------------------------------------------
# init.sql — SQL string escaping (doubled single quotes inside YAML literal)
# ---------------------------------------------------------------------------


class TestInitSqlStringEscaping:
    """Verify SQL string escaping: single quotes inside the YAML are doubled.

    Inside a PostgreSQL string literal delimited by single quotes, any embedded
    single quote must be written as '' (two single quotes).  A single unescaped
    quote terminates the string literal early, causing a syntax error that
    prevents ALL tables from being created.

    This test is the #1 guard against the transcription hazard described in
    SPEC_0 §3.1.
    """

    def test_contractor_value_uses_doubled_quotes(self, init_sql_text: str):
        """
        The YAML expression for contractor check must use ''contractor''
        (doubled single quotes), NOT 'contractor' (single quotes).

        Pattern in spec:
          expression: "user.employee_type == ''contractor'' AND time.hour > 18"

        If single quotes are used instead of doubled quotes, PostgreSQL will see
        the string end after 'user.employee_type == ' and emit a syntax error.
        """
        assert "''contractor''" in init_sql_text, (
            "Expected doubled single-quote escaping: ''contractor'' in init.sql. "
            "Using 'contractor' (unescaped) would break the SQL string literal "
            "and prevent the entire init.sql from executing."
        )

    def test_us_value_uses_doubled_quotes(self, init_sql_text: str):
        """
        The YAML expression for foreign-contractor check must use ''US''
        (doubled single quotes) for the country value.
        """
        assert "''US''" in init_sql_text, (
            "Expected doubled single-quote escaping: ''US'' in init.sql. "
            "The foreign-contractor condition checks signals.country != ''US''."
        )

    def test_ldap_protocol_value_uses_doubled_quotes(self, init_sql_text: str):
        """
        The YAML expression for legacy-protocol-usage must use ''ldap''
        (doubled single quotes) for the protocol value.
        """
        assert "''ldap''" in init_sql_text, (
            "Expected doubled single-quote escaping: ''ldap'' in init.sql. "
            "The legacy-protocol-usage condition checks event.protocol == ''ldap''."
        )

    def test_no_unescaped_contractor_in_yaml_section(self, init_sql_text: str):
        """
        There must be NO occurrence of unescaped 'contractor' (single-quoted,
        not doubled) that would terminate the SQL string literal prematurely.

        This checks that the pattern == 'contractor' does NOT appear — only
        == ''contractor'' (doubled) should exist inside the SQL string.
        """
        # Pattern: a lone 'contractor' (not preceded or followed by another ')
        # i.e., == 'contractor' or 'contractor' alone, but NOT == ''contractor''
        # We look for: single-quote, contractor, single-quote where neither
        # neighbor quote is also a single-quote.
        # Negative lookbehind/lookahead: the adjacent char is not also '
        unescaped = re.search(r"(?<!')'contractor'(?!')", init_sql_text)
        assert not unescaped, (
            "Found unescaped 'contractor' (single quotes not doubled) in init.sql. "
            "This would break the SQL string literal. Use ''contractor'' instead."
        )


# ---------------------------------------------------------------------------
# init.sql — no CREATE DATABASE statement
# ---------------------------------------------------------------------------


class TestInitSqlNoCreateDatabase:
    """Verify init.sql does not contain CREATE DATABASE.

    Per Spec 0 §3.1 architect's note (Gap 1): Keycloak uses its built-in H2
    dev database. Including CREATE DATABASE in init.sql adds complexity, can
    cause transaction-block errors (CREATE DATABASE cannot run inside a
    transaction), and is unnecessary. The Docker Compose postgres service
    creates the naas database via POSTGRES_DB env var automatically.
    """

    def test_no_create_database_statement(self, init_sql_upper: str):
        """
        init.sql must NOT contain 'CREATE DATABASE' (case-insensitive).
        This guards against accidental inclusion which would cause PostgreSQL
        to error with 'CREATE DATABASE cannot run inside a transaction block'
        during the Docker entrypoint init script execution.
        """
        assert "CREATE DATABASE" not in init_sql_upper, (
            "init.sql contains 'CREATE DATABASE' — this must be removed. "
            "The naas database is auto-created by the POSTGRES_DB env var. "
            "Keycloak uses its own H2 dev database (see Spec 0 §3.1 Gap 1)."
        )


# ---------------------------------------------------------------------------
# redis.conf — existence
# ---------------------------------------------------------------------------
