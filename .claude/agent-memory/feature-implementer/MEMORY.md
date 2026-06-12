# Feature Implementer Memory

## Project
- [project_naas_shared_config_extra_ignore.md](project_naas_shared_config_extra_ignore.md) — Settings class needs extra="ignore"; repo .env contains undeclared vars that cause pydantic-settings to raise
- [project_httpx_test_dep.md](project_httpx_test_dep.md) — httpx not in venv by default; starlette.testclient requires it; install if TestClient tests fail with ModuleNotFoundError

## Patterns
- [patterns_health_patch.md](patterns_health_patch.md) — /health must access naas_shared.database and naas_shared.redis_client via module refs at call time for test patches to work; Depends() won't work with module-level patches

## Patterns
- [patterns_utc_timestamp_defense.md](patterns_utc_timestamp_defense.md) — Three-layer UTC pin: Pydantic validator + DateTime(timezone=True) ORM + engine connect_args. Events table only; other tables stay TIMESTAMP.

## Patterns
- [patterns_service_test_isolation.md](patterns_service_test_isolation.md) — Per-service conftest.py required to isolate app.* sys.modules across services (importlib + underscored test dirs handle same-basename collisions; no root conftest); also update IMPLEMENTED_APP_SERVICES registry in tests/repo + tests/infrastructure
- [patterns_fastapi_oauth2_redirect.md](patterns_fastapi_oauth2_redirect.md) — Set swagger_ui_oauth2_redirect_url=None on FastAPI() to suppress hidden /docs/oauth2-redirect route that breaks chunk-1 scope boundary tests

## Patterns
- [patterns_ldap_dn_no_native.md](patterns_ldap_dn_no_native.md) — python-ldap can't pip-install in dev venv (no gcc); use regex for DN parsing in tests

## Patterns
- [patterns_get_redis_mock_seam.md](patterns_get_redis_mock_seam.md) — Use inspect.isawaitable() when calling get_redis(); chunk-4 tests patch with MagicMock(return_value=fake_redis) which returns fake_redis directly (not a coroutine)
- [patterns_ldap_filter_parens_test_conflict.md](patterns_ldap_filter_parens_test_conflict.md) — Two-tier LDAP filter building: public build_search_filter (with parens) and internal _build_search_filter_internal (without parens) to satisfy both RFC and metacharacter sanitization tests

## Patterns
- [patterns_tempfile_flush_conftest.md](patterns_tempfile_flush_conftest.md) — Test helpers calling load_config() inside a NamedTemporaryFile with block need a conftest flush-on-write autouse fixture to prevent reading an empty file

## Patterns
- [patterns_ldap_dn_str2dn_fallback.md](patterns_ldap_dn_str2dn_fallback.md) — _reduce_dn_to_group_name: str2dn primary + regex fallback on ImportError to keep dev-venv (no gcc/python-ldap) tests green
- [patterns_consumer_loop_resilience.md](patterns_consumer_loop_resilience.md) — xreadgroup outer loop: except Exception catches transient errors, CancelledError propagates; truncate str(exc)[:200] at all log sites for PII safety

## Patterns
- [patterns_spec_doc_section_extractor.md](patterns_spec_doc_section_extractor.md) — SPEC_0 §5.3 section extractor treats `# comment` lines inside code fences as heading stops; never put `# path/to/file` comments inside code blocks in that section

## Patterns
- [patterns_osixia_memberof_overlay.md](patterns_osixia_memberof_overlay.md) — osixia default memberof overlay is groupOfUniqueNames/uniqueMember; fix via 00-prefixed LDIF in ldif/custom/ that modifies cn=config before bootstrap data loads

## Feedback
- [feedback_ruff_format_test_files.md](feedback_ruff_format_test_files.md) — ruff format must be applied to test files, not just ruff check
- [patterns_integration_test_infra.md](patterns_integration_test_infra.md) — ruff only on .py paths; pytest.fail unbound var fix; docker-compose.test.yml pattern (explicit image tag both files, exec-array command, rich in requirements-dev); marker single-sourced in pyproject.toml
- [patterns_health_session_factory.md](patterns_health_session_factory.md) — /health tests must patch get_session_factory (not get_db_session) when handler uses factory()-as-async-CM pattern
