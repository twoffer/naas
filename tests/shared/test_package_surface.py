"""Import surface and placeholder module checks for naas_shared.

Verifies that all public naas_shared modules import cleanly and that
placeholder modules (schemas, ml_features, simulation_tools) satisfy their
Spec 0 contracts.
"""

from __future__ import annotations

import importlib

import pytest


# ===========================================================================
# Import surface (§4, §6.6)
# ===========================================================================


class TestPackageImportSurface:
    """Verify that the smoke-test import set from §6.6 all resolve without error.

    These are the imports every downstream service will execute at startup.
    A ModuleNotFoundError here is a total service failure.
    """

    def test_import_get_settings_from_config(self):
        """from naas_shared.config import get_settings must succeed."""
        from naas_shared.config import get_settings  # noqa: F401

    def test_import_login_event_ingest_from_models(self):
        """from naas_shared.models import LoginEventIngest must succeed."""
        from naas_shared.models import LoginEventIngest  # noqa: F401

    def test_import_risk_decision_from_models(self):
        """from naas_shared.models import RiskDecision must succeed."""
        from naas_shared.models import RiskDecision  # noqa: F401

    def test_import_alert_message_from_models(self):
        """from naas_shared.models import AlertMessage must succeed."""
        from naas_shared.models import AlertMessage  # noqa: F401

    def test_import_stream_login_events_from_constants(self):
        """from naas_shared.constants import STREAM_LOGIN_EVENTS must succeed."""
        from naas_shared.constants import STREAM_LOGIN_EVENTS  # noqa: F401

    def test_import_channel_decisions_from_constants(self):
        """from naas_shared.constants import CHANNEL_DECISIONS must succeed."""
        from naas_shared.constants import CHANNEL_DECISIONS  # noqa: F401

    def test_import_setup_logging_from_logging(self):
        """from naas_shared.logging import setup_logging must succeed."""
        from naas_shared.logging import setup_logging  # noqa: F401

    def test_setup_logging_call_does_not_raise(self):
        """setup_logging('test') must complete without raising."""
        from naas_shared.logging import setup_logging

        setup_logging("test")

    def test_get_settings_returns_settings_instance(self):
        """get_settings() must return a Settings object (not None, not raise)."""
        from naas_shared.config import get_settings

        settings = get_settings()
        assert settings is not None, "get_settings() returned None"

    def test_database_url_starts_with_asyncpg_scheme(self):
        """settings.database_url must start with 'postgresql+asyncpg://'."""
        from naas_shared.config import get_settings

        url = get_settings().database_url
        assert url.startswith("postgresql+asyncpg://"), (
            f"Expected database_url to start with 'postgresql+asyncpg://', got: {url!r}"
        )

    def test_database_url_sync_starts_with_sync_scheme(self):
        """settings.database_url_sync must start with 'postgresql://' (no +asyncpg)."""
        from naas_shared.config import get_settings

        url_sync = get_settings().database_url_sync
        assert url_sync.startswith("postgresql://"), (
            f"Expected database_url_sync to start with 'postgresql://', got: {url_sync!r}"
        )
        assert "+asyncpg" not in url_sync, (
            f"database_url_sync must NOT contain '+asyncpg', got: {url_sync!r}"
        )

    def test_full_import_set_from_spec_section_4(self):
        """The complete canonical import block from §4 must succeed in one pass."""
        from naas_shared.constants import (  # noqa: F401
            CHANNEL_ALERTS,
            CHANNEL_DECISIONS,
            GROUP_ENRICHMENT,
            GROUP_EVALUATOR,
            GROUP_NORMALIZATION,
            STREAM_ENRICHED_EVENTS,
            STREAM_LOGIN_EVENTS,
            STREAM_NORMALIZED_EVENTS,
        )
        from naas_shared.database import get_db_session, get_engine  # noqa: F401
        from naas_shared.logging import get_logger, setup_logging  # noqa: F401
        from naas_shared.models import (  # noqa: F401
            AlertMessage,
            HealthResponse,
            LoginEventBase,
            LoginEventIngest,
            LoginEventRecord,
            NormalizedAttributes,
            RiskDecision,
        )
        from naas_shared.redis_client import (  # noqa: F401
            ensure_consumer_group,
            get_redis,
            publish_to_channel,
            publish_to_stream,
        )


# ===========================================================================
# Placeholder modules — schemas, ml_features, simulation_tools
# ===========================================================================


class TestSchemasModule:
    """schemas.py was a Spec 0 placeholder and is now populated by Spec 1 (Base, EventORM).

    ORM surface is covered positively by tests/shared/test_orm_mapping.py; here we
    only smoke-test that the module still imports cleanly.
    """

    def test_schemas_module_imports_without_error(self):
        """schemas.py must be importable without raising any exception."""
        import naas_shared.schemas  # noqa: F401


class TestMlFeaturesPyPlaceholder:
    """ml_features.py is a placeholder in Spec 0 — real content is owned by Spec 3.

    We assert only that it imports cleanly and does not prematurely define feature names.
    """

    def test_ml_features_module_imports_without_error(self):
        """ml_features.py must be importable without raising any exception."""
        import naas_shared.ml_features  # noqa: F401

    def test_ml_features_does_not_define_feature_columns(self):
        """ml_features.py must NOT define a FEATURE_COLUMNS list with actual column names.

        Spec 3 owns the real 16-feature ordering. A placeholder with wrong content
        would silently propagate an incorrect contract to training and inference.
        """
        import naas_shared.ml_features

        for attr_name in ("FEATURE_COLUMNS", "ML_FEATURES", "FEATURE_NAMES"):
            if hasattr(naas_shared.ml_features, attr_name):
                value = getattr(naas_shared.ml_features, attr_name)
                assert value == [] or value is None, (
                    f"ml_features.{attr_name} must be empty or None in the placeholder "
                    f"(Spec 3 owns the real content), got: {value!r}"
                )


class TestSimulationToolsPyPlaceholder:
    """simulation_tools.py is a placeholder in Spec 0 — real content is owned by a later spec.

    We assert only clean import and that no premature tool definitions exist.
    """

    def test_simulation_tools_module_imports_without_error(self):
        """simulation_tools.py must be importable without raising any exception."""
        import naas_shared.simulation_tools  # noqa: F401

    def test_simulation_tools_does_not_define_tool_definitions(self):
        """simulation_tools.py must NOT define TOOL_DEFINITIONS or ToolExecutor with content."""
        import naas_shared.simulation_tools

        for attr_name in ("TOOL_DEFINITIONS", "ToolExecutor"):
            if hasattr(naas_shared.simulation_tools, attr_name):
                value = getattr(naas_shared.simulation_tools, attr_name)
                assert value is None or value == [] or value == {}, (
                    f"simulation_tools.{attr_name} must be None/empty in the placeholder "
                    f"(later spec owns the real content), got: {value!r}"
                )


class TestAllModulesImportCleanly:
    """Regression guard: every module under naas_shared must import without raising.

    Catches circular imports, missing dependencies, and syntax errors that
    only surface at import time.
    """

    @pytest.mark.parametrize(
        "module_name",
        [
            "naas_shared",
            "naas_shared.constants",
            "naas_shared.config",
            "naas_shared.models",
            "naas_shared.database",
            "naas_shared.redis_client",
            "naas_shared.logging",
            "naas_shared.schemas",
            "naas_shared.ml_features",
            "naas_shared.simulation_tools",
        ],
    )
    def test_module_imports_without_error(self, module_name):
        """Each naas_shared module must import without raising any exception."""
        module = importlib.import_module(module_name)
        assert module is not None, f"{module_name} imported as None"
