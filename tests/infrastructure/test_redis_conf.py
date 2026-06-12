# Verifies infrastructure/redis/redis.conf configuration.
#
# Checks: existence, the four required directives (maxmemory, maxmemory-policy,
# appendonly, appendfsync), exact substantive-line count, and absence of
# stream pre-creation commands (XADD, XGROUP).

# stdlib
import re

# third-party
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


from tests.helpers import REPO_ROOT

REDIS_CONF_PATH = REPO_ROOT / "infrastructure" / "redis" / "redis.conf"


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def redis_conf_text() -> str:
    """Read redis.conf content once for the whole module."""
    if not REDIS_CONF_PATH.exists():
        pytest.skip("infrastructure/redis/redis.conf not found")
    return REDIS_CONF_PATH.read_text(encoding="utf-8")


class TestRedisConfExists:
    """Verify infrastructure/redis/redis.conf is present."""

    def test_redis_directory_exists(self):
        """
        infrastructure/redis/ directory must exist.
        Missing directory means the Redis config cannot be mounted by Docker Compose.
        """
        redis_dir = REPO_ROOT / "infrastructure" / "redis"
        assert redis_dir.exists(), (
            f"infrastructure/redis/ directory not found at {redis_dir}"
        )
        assert redis_dir.is_dir(), f"{redis_dir} exists but is not a directory"

    def test_redis_conf_file_exists(self):
        """
        infrastructure/redis/redis.conf must exist.
        The Docker Compose redis service mounts it as the server config;
        without it Redis starts with default settings (no maxmemory limit,
        no persistence), which causes silent data loss under load.
        """
        assert REDIS_CONF_PATH.exists(), (
            f"infrastructure/redis/redis.conf not found at {REDIS_CONF_PATH}"
        )

    def test_redis_conf_is_a_file_not_directory(self):
        """Guard against accidental creation of a redis.conf/ directory."""
        assert REDIS_CONF_PATH.is_file(), (
            f"{REDIS_CONF_PATH} exists but is not a regular file"
        )


# ---------------------------------------------------------------------------
# redis.conf — required directives
# ---------------------------------------------------------------------------

EXPECTED_REDIS_DIRECTIVES = [
    "maxmemory 256mb",
    "maxmemory-policy allkeys-lru",
    "appendonly yes",
    "appendfsync everysec",
]


class TestRedisConfDirectives:
    """Verify the four required Redis directives are present."""

    @pytest.mark.parametrize("directive", EXPECTED_REDIS_DIRECTIVES)
    def test_required_directive_present(self, directive: str, redis_conf_text: str):
        """
        Each of the four required directives must appear as a standalone line
        in redis.conf (allowing surrounding whitespace/comments).

        - maxmemory 256mb: caps memory to prevent OOM kills in Docker
        - maxmemory-policy allkeys-lru: evict LRU keys when at capacity
          (correct for pipeline caches; volatile-lru would silently keep
          non-expiring keys and evict only expiring ones, wrong behavior)
        - appendonly yes: enables AOF persistence so stream data survives restarts
        - appendfsync everysec: balances durability with throughput (fsync 1/sec)
        """
        # Each directive should appear as its own line (ignoring leading
        # whitespace and comment lines).
        pattern = re.compile(
            r"^\s*" + re.escape(directive) + r"\s*$",
            re.MULTILINE,
        )
        assert pattern.search(redis_conf_text), (
            f"Required Redis directive '{directive}' not found as a standalone "
            f"line in redis.conf. All four directives are required: "
            f"{EXPECTED_REDIS_DIRECTIVES}"
        )

    def test_exactly_four_substantive_config_lines(self, redis_conf_text: str):
        """
        redis.conf must contain exactly the four required directives as
        substantive config lines (non-comment, non-blank lines).
        Extra directives could override defaults in unexpected ways;
        fewer directives mean missing required settings.

        Comments (lines starting with #) and blank lines are excluded.
        """
        substantive_lines = [
            line.strip()
            for line in redis_conf_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert len(substantive_lines) == 4, (
            f"Expected exactly 4 substantive config lines in redis.conf, "
            f"found {len(substantive_lines)}: {substantive_lines}. "
            f"Required: {EXPECTED_REDIS_DIRECTIVES}"
        )

    def test_all_four_directives_match_exactly(self, redis_conf_text: str):
        """
        The set of substantive config lines must be exactly the four required
        directives, no more, no less.  This guards against typos like
        'maxmemory 256 mb' (space before mb) or 'appendfsync always'
        (wrong fsync mode).
        """
        substantive_lines = {
            line.strip()
            for line in redis_conf_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        expected_set = set(EXPECTED_REDIS_DIRECTIVES)
        assert substantive_lines == expected_set, (
            f"redis.conf substantive lines do not match expected. "
            f"Expected: {sorted(expected_set)}. "
            f"Found: {sorted(substantive_lines)}. "
            f"Missing: {sorted(expected_set - substantive_lines)}. "
            f"Extra: {sorted(substantive_lines - expected_set)}."
        )


# ---------------------------------------------------------------------------
# redis.conf — no stream pre-creation directives
# ---------------------------------------------------------------------------


class TestRedisConfNoStreamDirectives:
    """Verify redis.conf contains no stream pre-creation directives.

    Per Spec 0 §3.2: Streams are lazily created by producers (XADD auto-creates).
    redis.conf is a configuration file — it cannot contain XADD or XGROUP
    commands (those are Redis protocol commands, not config directives).
    This test guards against accidental copy-paste from a setup script into
    the config file.
    """

    def test_no_xadd_directive(self, redis_conf_text: str):
        """
        redis.conf must not contain 'XADD'.
        XADD is a Redis command, not a configuration directive; it has no
        meaning in redis.conf and its presence indicates a file content error.
        Streams are created lazily by the first XADD call from producers.
        """
        assert "XADD" not in redis_conf_text.upper(), (
            "redis.conf contains 'XADD' — this is a Redis command, not a config "
            "directive. Remove it. Streams are created lazily by producers."
        )

    def test_no_xgroup_directive(self, redis_conf_text: str):
        """
        redis.conf must not contain 'XGROUP'.
        XGROUP is a Redis command for creating consumer groups; it belongs in
        service startup code (ensure_consumer_group()), not in redis.conf.
        """
        assert "XGROUP" not in redis_conf_text.upper(), (
            "redis.conf contains 'XGROUP' — this is a Redis command, not a config "
            "directive. Consumer groups are created by each service on startup."
        )
